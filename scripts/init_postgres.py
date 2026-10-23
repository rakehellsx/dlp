"""Initialize the imported dlpcenter schema and optionally seed the DLP prototype."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os

import bcrypt
from psycopg2.extras import Json
from pg_common import ROOT, connect, schema
from migrate_endpoints import migrate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-demo',action='store_true',help='Initialize business demo data once; deleted entries stay deleted')
    args=parser.parse_args()
    with connect() as db:
        with db.cursor() as c:
            c.execute('SELECT pg_advisory_xact_lock(728112)')
            schema(c)
            c.execute('SELECT 1 FROM users LIMIT 1')
            if not c.fetchone():
                password=os.environ.get('DLP_ADMIN_PASSWORD')
                if not password:raise SystemExit('首次初始化必须设置 DLP_ADMIN_PASSWORD')
                hashed=bcrypt.hashpw(hashlib.sha256(password.encode()).hexdigest().encode(),bcrypt.gensalt(rounds=10)).decode()
                c.execute("INSERT INTO users(username,password_hash,role) VALUES('admin',%s,'admin')",(hashed,))
            fixture=json.loads((ROOT/'dlpcenter'/'sql'/'demo.json').read_text())
            c.execute('INSERT INTO dlp_settings(id,data) VALUES(1,%s) ON CONFLICT(id) DO NOTHING',(Json(fixture['settings']),))
            if args.with_demo:
                c.execute("SELECT 1 FROM dlp_migrations WHERE name='prototype-demo-v1'")
                if not c.fetchone():
                    c.execute("SELECT 1 FROM dlp_records LIMIT 1")
                    if c.fetchone():raise SystemExit('业务库已有记录，未导入默认演示数据；请保留已有数据')
                    c.execute("SELECT to_regclass('public.endpoints')")
                    if c.fetchone()[0]:
                        c.execute('SELECT 1 FROM endpoints LIMIT 1')
                        if c.fetchone():raise SystemExit('终端表已有记录，未导入默认演示数据；请保留已有数据')
                    event_index=0
                    for row in fixture['records']:
                        item=row['data']
                        if row['kind']=='events':
                            item['time']=(datetime.now(timezone(timedelta(hours=8)))-timedelta(hours=((event_index/186)**1.45)*7*24,minutes=event_index%5*4+3)).strftime('%Y-%m-%d %H:%M:%S');event_index+=1
                        c.execute('INSERT INTO dlp_records(kind,id,data) VALUES(%s,%s,%s)',(row['kind'],item['id'],Json(item)))
                    c.execute('INSERT INTO dlp_settings(id,data) VALUES(1,%s) ON CONFLICT(id) DO NOTHING',(Json(fixture['settings']),))
                    c.execute("INSERT INTO dlp_migrations(name) VALUES('prototype-demo-v1'),('watermarks-v1') ON CONFLICT DO NOTHING")
            migrate(c)
            print('PostgreSQL schema and administrator ready'+('; demo initialization requested' if args.with_demo else ''))


if __name__=='__main__':main()
