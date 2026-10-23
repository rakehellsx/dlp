"""Provision a local PostgreSQL role/database and a root-only systemd environment file.

Run as root after installing PostgreSQL and python3-psycopg2. Existing databases,
roles and environment files are preserved; this command never resets passwords.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',default='dlpcenter')
    parser.add_argument('--user',default='dlpcenter')
    parser.add_argument('--env-file',type=Path,default=Path('/etc/dlpcenter.env'))
    parser.add_argument('--root-dir',type=Path,default=Path('/opt/sentinel-dlp'))
    parser.add_argument('--http-port',type=int,default=8091)
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('请以 root 执行')
    if any(not re.fullmatch(r'[a-z][a-z0-9_]{0,40}',s) for s in [args.database,args.user]):raise SystemExit('数据库及角色名仅允许小写字母、数字和下划线')
    if args.env_file.exists():raise SystemExit('环境文件已存在，已保留。请使用现有配置，不会重置密码。')
    password=secrets.token_urlsafe(36)
    provision='''import json,sys,psycopg2
from psycopg2 import sql
p=json.load(sys.stdin)
c=psycopg2.connect(dbname="postgres",host="/var/run/postgresql");c.autocommit=True
with c.cursor() as q:
 q.execute("SELECT 1 FROM pg_roles WHERE rolname=%s",(p["user"],))
 if q.fetchone():raise SystemExit("角色已存在，已取消；请配置现有数据库凭据")
 q.execute("SELECT 1 FROM pg_database WHERE datname=%s",(p["database"],))
 if q.fetchone():raise SystemExit("数据库已存在，已取消；请配置现有数据库凭据")
 q.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE").format(sql.Identifier(p["user"])),(p["password"],))
 q.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(p["database"]),sql.Identifier(p["user"])))
c.close()
'''
    fd=os.open(args.env_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as output:
            subprocess.run(['runuser','-u','postgres','--','/usr/bin/python3','-c',provision],
                input=json.dumps({'user':args.user,'database':args.database,'password':password}),text=True,check=True)
            root=args.root_dir.resolve()
            values={'DLP_DB_HOST':'127.0.0.1','DLP_DB_PORT':'5432','DLP_DB_NAME':args.database,'DLP_DB_USER':args.user,
                'DLP_DB_PASSWORD':password,'DLP_HTTP_HOST':'127.0.0.1','DLP_HTTP_PORT':str(args.http_port),
                'DLP_CONFIG':str(root/'dlpcenter/config.json'),'DLP_STATIC_ROOT':str(root/'static'),
                'DLP_IMAGE_HELPER':str(root/'dlpcenter/tools/image_processor.py'),'DLP_FILE_ROOT':'/var/lib/sentinel-dlp/files','TZ':'Asia/Shanghai'}
            for key,value in values.items():output.write(key+'='+json.dumps(value)+'\n')
    except BaseException:
        args.env_file.unlink(missing_ok=True);raise
    print('PostgreSQL 角色、数据库和环境文件已创建；凭据仅保存于 '+str(args.env_file))


if __name__=='__main__':main()
