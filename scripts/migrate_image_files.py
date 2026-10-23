"""Move legacy PostgreSQL BYTEA images to immutable disk files, retaining all metadata in PG.
Run while the application is stopped. Back up the database before upgrading.
"""
import hashlib
import os
from pathlib import Path
import tempfile
from pg_common import connect,schema


def write(root,relative,data):
    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True,mode=0o750)
    if path.exists():
        if path.read_bytes()!=data:raise RuntimeError('存储文件冲突：'+relative)
        return
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.migrate-')
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    root=Path(os.environ.get('DLP_FILE_ROOT','/var/lib/sentinel-dlp/files'));root.mkdir(parents=True,exist_ok=True,mode=0o750)
    with connect() as db:
        with db.cursor() as c:
            c.execute('SELECT pg_advisory_xact_lock(728114)');schema(c)
            c.execute('SELECT id,original,thumbnail,hash,original_path,thumbnail_path FROM dlp_watermark_images FOR UPDATE')
            rows=c.fetchall()
            for ident,original,thumb,digest,original_path,thumbnail_path in rows:
                op=digest+'/original';tp=digest+'/thumbnail.jpg'
                if original is not None:
                    original=bytes(original);thumb=bytes(thumb)
                    if hashlib.sha256(original).hexdigest()!=digest:raise RuntimeError('原图哈希不符：'+ident)
                    write(root,op,original);write(root,tp,thumb)
                else:
                    if original_path!=op or thumbnail_path!=tp or hashlib.sha256((root/op).read_bytes()).hexdigest()!=digest or not (root/tp).is_file():raise RuntimeError('文件路径或哈希校验失败：'+ident)
                c.execute('UPDATE dlp_watermark_images SET original_path=%s,thumbnail_path=%s,size=%s,original=NULL,thumbnail=NULL WHERE id=%s',(op,tp,(root/op).stat().st_size,ident))
            c.execute("INSERT INTO dlp_migrations(name) VALUES('image-disk-v1') ON CONFLICT DO NOTHING")
    print(f'已校验并迁移 {len(rows)} 张原图和缩略图；路径、元数据及检索信息保留于 PostgreSQL。')


if __name__=='__main__':main()
