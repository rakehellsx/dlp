"""One-time, transactional migration from the original SQLite prototype to dlpcenter."""
import argparse
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3

import bcrypt
import psycopg2
from psycopg2.extras import Json
from pg_common import connect, schema

MARKER='sqlite-prototype-v1'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sqlite',type=Path,required=True,help='Consistent SQLite backup; source is opened read-only')
    args=parser.parse_args()
    path=args.sqlite.resolve(strict=True)
    source=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);source.row_factory=sqlite3.Row
    try:
        if source.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise SystemExit('SQLite 校验失败')
        records=list(source.execute('SELECT kind,id,data FROM records ORDER BY rowid'))
        images=list(source.execute('SELECT * FROM watermark_images'))
        # Validate every original before opening the PostgreSQL transaction.
        for image in images:
            if hashlib.sha256(image['original']).hexdigest()!=image['hash']:raise SystemExit('原图校验失败：'+image['id'])
        with connect() as target:
            with target.cursor() as c:
                c.execute('SELECT pg_advisory_xact_lock(728112)');schema(c)
                c.execute('SELECT 1 FROM dlp_migrations WHERE name=%s',(MARKER,))
                if c.fetchone():print('已完成过 SQLite 迁移，跳过，不覆盖 PostgreSQL 后续修改');return
                c.execute('SELECT count(*) FROM dlp_records')
                if c.fetchone()[0]:raise SystemExit('目标业务库非空，已取消迁移，避免覆盖已有数据')
                users=list(source.execute('SELECT * FROM users'))
                for user in users:
                    c.execute('SELECT id FROM users WHERE username=%s',(user['name'],))
                    if c.fetchone():continue  # Retain the imported project's existing PostgreSQL accounts.
                    password=os.environ.get('DLP_ADMIN_PASSWORD') or getpass.getpass('原 SQLite 账号 '+user['name']+' 的密码：')
                    actual=hashlib.pbkdf2_hmac('sha256',password.encode(),user['salt'].encode(),200000).hex()
                    if not hmac.compare_digest(actual,user['hash']):raise SystemExit('旧账号密码校验失败，迁移已回滚')
                    hashed=bcrypt.hashpw(hashlib.sha256(password.encode()).hexdigest().encode(),bcrypt.gensalt(rounds=10)).decode()
                    c.execute("INSERT INTO users(username,password_hash,role) VALUES(%s,%s,'admin')",(user['name'],hashed))
                for row in records:
                    item=json.loads(row['data'])
                    if item.get('id')!=row['id']:raise SystemExit('业务记录 ID 不一致')
                    c.execute('INSERT INTO dlp_records(kind,id,data) VALUES(%s,%s,%s)',(row['kind'],row['id'],Json(item)))
                for image in images:
                    c.execute('INSERT INTO dlp_watermark_images(id,original,thumbnail,hash,mime) VALUES(%s,%s,%s,%s,%s)',
                        (image['id'],psycopg2.Binary(image['original']),psycopg2.Binary(image['thumbnail']),image['hash'],image['mime']))
                settings=source.execute('SELECT data FROM settings WHERE id=1').fetchone()
                if settings:c.execute('INSERT INTO dlp_settings(id,data) VALUES(1,%s)',(Json(json.loads(settings[0])),))
                for row in source.execute('SELECT * FROM audit ORDER BY id'):
                    c.execute('INSERT INTO operation_logs(operator_id,operator_name,action,target,detail,created_at,success) VALUES(0,%s,%s,%s,%s,%s,true)',
                        (row['actor'],row['action'],row['target'],row['detail'],row['time']+'+08:00'))
                if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migrations'").fetchone():
                    for row in source.execute('SELECT name FROM migrations'):c.execute('INSERT INTO dlp_migrations(name) VALUES(%s) ON CONFLICT DO NOTHING',(row[0],))
                c.execute("INSERT INTO dlp_migrations(name) VALUES(%s),('prototype-demo-v1') ON CONFLICT DO NOTHING",(MARKER,))
                # Compare all migrated JSON and binary contents inside the same transaction.
                c.execute('SELECT kind,id,data FROM dlp_records');result={(kind,ident):data for kind,ident,data in c.fetchall()}
                if result!={(r['kind'],r['id']):json.loads(r['data']) for r in records}:raise SystemExit('业务数据对比失败，迁移已回滚')
                c.execute('SELECT id,original,thumbnail,hash FROM dlp_watermark_images');result={row[0]:row[1:] for row in c.fetchall()}
                for image in images:
                    actual=result[image['id']]
                    if bytes(actual[0])!=image['original'] or bytes(actual[1])!=image['thumbnail'] or actual[2]!=image['hash']:raise SystemExit('图片数据对比失败，迁移已回滚')
                print(f'迁移完成：{len(records)} 条业务记录，{len(images)} 张图片；JSON、原图和缩略图逐条核对通过。旧会话不迁移，请重新登录。')
    finally:source.close()


if __name__=='__main__':main()
