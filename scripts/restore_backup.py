"""Restore a PostgreSQL dump and its paired file archive into an empty target.
Stop the target application first. Existing business data or nonempty file directories are refused.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
from pg_common import connect,file_root


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump',type=Path,required=True)
    args=parser.parse_args();dump=args.dump.resolve(strict=True);files=dump.with_suffix('.files.tar.gz').resolve(strict=True)
    root=file_root()
    if root.exists() and any(root.iterdir()):raise SystemExit('目标文件目录非空，已取消恢复；请使用新的目录')
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            if c.fetchone()[0]:raise SystemExit('目标数据库非空，已取消恢复；请使用新建空库')
    root.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.restore-',dir=root.parent) as staging:
        target=Path(staging)/'files';target.mkdir()
        with tarfile.open(files,'r:gz') as archive:
            for member in archive.getmembers():
                if member.isdir():
                    if not re.fullmatch(r'files(?:/[a-f0-9]{64})?',member.name):raise SystemExit('文件归档包含无效目录')
                    continue
                if not member.isfile() or not re.fullmatch(r'files/[a-f0-9]{64}/(?:original|thumbnail\.jpg)',member.name):raise SystemExit('文件归档包含无效文件')
                path=Path(staging)/member.name;path.parent.mkdir(exist_ok=True,mode=0o750)
                with path.open('xb') as output:output.write(archive.extractfile(member).read())
                path.chmod(0o600)
        env=dict(os.environ)
        for key,default in [('HOST','127.0.0.1'),('PORT','5432'),('NAME','dlpcenter'),('USER','dlpcenter'),('PASSWORD','')]:
            env['PGDATABASE' if key=='NAME' else 'PG'+key]=os.environ.get('DLP_DB_'+key,default)
        subprocess.run(['pg_restore','--single-transaction','--no-owner','--no-acl','--exit-on-error','--dbname',env['PGDATABASE'],str(dump)],env=env,check=True)
        with connect() as db:
            with db.cursor() as c:
                c.execute('SELECT original_path,thumbnail_path,hash FROM dlp_watermark_images')
                for original,thumb,digest in c.fetchall():
                    if original!=digest+'/original' or thumb!=digest+'/thumbnail.jpg' or hashlib.sha256((target/original).read_bytes()).hexdigest()!=digest or not (target/thumb).is_file():raise SystemExit('恢复后的文件路径或哈希校验失败，请保留停止状态并检查备份')
        if root.exists():root.rmdir()
        os.replace(target,root)
    print('数据库与配套文件恢复并校验完成：'+str(root))


if __name__=='__main__':main()
