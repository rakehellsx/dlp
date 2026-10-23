"""Integration tests for the C++ dlpcenter backend against disposable PostgreSQL databases.

Run with a PostgreSQL role allowed to CREATE DATABASE, e.g. as the local postgres OS user.
The production database is never used or modified.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from PIL import Image
import psycopg2
from psycopg2 import sql

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'scripts'))
from pg_common import connect


def main():
    admin=connect();admin.autocommit=True
    databases=[];process=None
    with tempfile.TemporaryDirectory(prefix='dlpcenter-verify-') as tmp:
        environment=dict(os.environ,DLP_ADMIN_PASSWORD='Integration-Only-Password!',TZ='Asia/Shanghai',
            DLP_IMAGE_HELPER=str(ROOT/'dlpcenter/tools/image_processor.py'),DLP_CONFIG=str(ROOT/'dlpcenter/config.json'),DLP_STATIC_ROOT=str(ROOT/'static'))
        def database():
            name='dlp_verify_'+secrets.token_hex(5)
            with admin.cursor() as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            databases.append(name);return name
        def script(name,args=(),env=None,check=True):
            return subprocess.run([sys.executable,str(ROOT/'scripts'/name),*args],env=env or environment,capture_output=True,text=True,check=check,timeout=40)
        def start():
            nonlocal process
            binary=Path(os.environ.get('DLP_BINARY',ROOT/'dlpcenter/build/dlpcenter')).resolve()
            process=subprocess.Popen([str(binary)],cwd=ROOT,env=environment,stdout=log,stderr=log)
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('dlpcenter exited: '+Path(tmp,'server.log').read_text()[-2000:])
                try:
                    if urllib.request.urlopen(base+'/health',timeout=1).status==200:return
                except OSError:time.sleep(.1)
            raise RuntimeError('Server did not become ready')
        jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        def request(path,body=None,ok=True,opener=None,csrf=True,token=None):
            headers={'Content-Type':'application/json'}
            if csrf:headers['X-DLP-Request']='1'
            if token:headers['Authorization']='Bearer '+token
            req=urllib.request.Request(base+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers=headers)
            with (opener or client).open(req,timeout=40) as response:
                raw=response.read()
                if 'json' not in response.headers.get('Content-Type',''):assert ok;return raw
                result=json.loads(raw);assert (result.get('code')==0)==ok,(path,result)
                assert response.headers.get('X-Err-Code')==str(result['code'])
                return result
        def login(password='Integration-Only-Password!',username='admin',opener=None,ok=True):
            return request('/api/login',{'username':username,'password_hash':hashlib.sha256(password.encode()).hexdigest()},opener=opener,ok=ok)
        log=Path(tmp,'server.log').open('w')
        try:
            environment['DLP_DB_NAME']=database()
            no_password=dict(environment);no_password.pop('DLP_ADMIN_PASSWORD')
            rejected=script('init_postgres.py',['--with-demo'],env=no_password,check=False)
            assert rejected.returncode and 'DLP_ADMIN_PASSWORD' in rejected.stderr
            script('init_postgres.py',['--with-demo']);script('init_postgres.py',['--with-demo'])
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            environment['DLP_HTTP_PORT']=str(port);environment['DLP_HTTP_HOST']='127.0.0.1';base=f'http://127.0.0.1:{port}'
            start()
            anonymous=urllib.request.build_opener()
            request('/api/bootstrap',ok=False)
            request('/api/login',[],ok=False)
            request('/api/login',{'username':{},'password_hash':[]},ok=False)
            login(password='incorrect',ok=False)
            logged=login();token=logged['token'];assert len(token)==64
            profile=request('/api/user/profile');assert profile['username']=='admin' and profile['role']=='admin'
            assert request('/api/user/profile',opener=anonymous,token=token)['id']==profile['id']
            data=request('/api/bootstrap');assert len(data['events'])==186 and len(data['endpoints'])==128
            assert request('/health')['database']=='PostgreSQL'
            print('PASS PostgreSQL initialization, idempotent demo seed, imported login/profile, Bearer and HttpOnly cookie authentication',flush=True)

            request('/api/user/create',{'username':{},'password_hash':[]},ok=False)
            request('/api/user/disable',{'username':'admin','disabled':'true'},ok=False)
            request('/api/user/change_password',{'old_password_hash':{},'new_password_hash':[]},ok=False)
            user_hash=hashlib.sha256(b'Regular-Test-Only!').hexdigest()
            user=request('/api/user/create',{'username':'verify-user','password_hash':user_hash,'role':'user'})
            assert isinstance(user['id'],int) and user['id']>0
            request('/api/user/create',{'username':'verify-user','password_hash':user_hash},ok=False)
            other=urllib.request.build_opener();regular=login('Regular-Test-Only!','verify-user',opener=other)['token']
            assert request('/api/bootstrap',opener=other,token=regular)['user']['role']=='user'
            request('/api/save',{'kind':'policies','item':{'name':'Denied'}},opener=other,token=regular,ok=False)
            request('/api/user/create',{'username':'denied','password_hash':user_hash},opener=other,token=regular,ok=False)
            request('/api/user/disable',{'username':'admin','disabled':True},ok=False)
            request('/api/user/disable',{'username':'verify-user','disabled':True})
            request('/api/bootstrap',opener=other,token=regular,ok=False)
            login('Regular-Test-Only!','verify-user',opener=other,ok=False)
            request('/api/user/disable',{'username':'verify-user','disabled':False})
            request('/api/user/delete',{'username':'verify-user'})
            request('/api/user/change_password',{'old_password_hash':hashlib.sha256(b'wrong').hexdigest(),'new_password_hash':user_hash},ok=False)
            print('PASS existing user management create/duplicate/role/disable/enable/delete/password validation and authorization',flush=True)

            policy=request('/api/save',{'kind':'policies','item':{'name':'PostgreSQL policy','enabled':True}})['item']
            request('/api/save',{'kind':'policies','item':{'name':'CSRF'}},csrf=False,ok=False)
            request('/api/update',{'kind':'policies','ids':[policy['id']],'changes':{'enabled':False}})
            wm=request('/api/save',{'kind':'watermarks','item':{'name':'测试打印水印','type':'print','content':'内部资料 · {姓名}\n{时间}','paperSize':'A3','bothSides':False,'printers':'测试打印机'}})['item']
            for bad in [{'fontSize':100},{'color':'red;script'},{'opacity':-1},{'angle':100},{'scope':'未知部门'},{'content':''},{'content':'{未知字段}'},{'condition':'apps','apps':[]},{'type':'screenshot','screenshotMethods':[]},{'bold':'true'}]:
                request('/api/save',{'kind':'watermarks','item':{**wm,**bad}},ok=False)
            request('/api/update',{'kind':'watermarks','ids':[wm['id']],'changes':{'enabled':False}})
            event=data['events'][0];ep=data['endpoints'][0]
            request('/api/update',{'kind':'events','ids':[event['id']],'changes':{'status':'resolved','note':'PostgreSQL disposition'}})
            request('/api/update',{'kind':'endpoints','ids':[ep['id']],'changes':{'isolated':True}})
            approval=next(a for a in data['approvals'] if a['status']=='pending')
            def approve(value):
                return request('/api/update',{'kind':'approvals','ids':[approval['id']],'changes':{'status':value}},opener=urllib.request.build_opener(),token=token)['count']
            with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(approve,['approved','rejected']))==[0,1]
            hits=request('/api/detect',{'content':'机密 年度财务预算 13800000000 110101199001010010'})['hits']
            assert {'个人信息','商业机密','财务数据'}<={h['rule'] for h in hits}
            request('/api/scan',{'name':'并发扫描','scope':'研发中心'})
            request('/api/scan',{'name':'重复扫描','scope':'研发中心'},ok=False)
            report=request('/api/report',{'name':'PG report','period':'最近7天'})['item'];assert report['events']>0 and report['assets']==72
            export=request('/api/export?kind=events');assert export.startswith(b'\xef\xbb\xbf') and event['id'].encode() in export
            request('/api/settings',{'company':'PostgreSQL 测试企业','retention':365})
            request('/api/settings',{'retention':1},ok=False)
            print('PASS policies/rules/watermarks, event disposition, isolation, concurrent approval, scanning, detection, reports, CSV and settings',flush=True)

            im=Image.new('RGB',(800,500),'white');from PIL import ImageDraw
            ImageDraw.Draw(im).text((30,30),'WM-TEST-001 192.168.10.20 2026-10-23 10:30:00',fill='black')
            out=io.BytesIO();im.save(out,format='PNG');original=out.getvalue()
            upload={'filename':'PostgreSQL测试.png','data':base64.b64encode(original).decode()}
            imported=request('/api/watermark-images/import',upload);image_id=imported['id']
            assert request('/api/watermark-image/'+image_id)==original
            assert request('/api/watermark-image/'+image_id+'?download=1')==original
            assert request('/api/watermark-image/'+image_id+'?thumb=1').startswith(b'\xff\xd8')
            assert request('/api/watermark-images/import',upload)['duplicate']
            request('/api/watermark-image/'+image_id,opener=anonymous,ok=False)
            for bad in ['not-base64!',base64.b64encode(b'<svg></svg>').decode()]:request('/api/watermark-images/import',{**upload,'data':bad},ok=False)
            for fmt in ['JPEG','WEBP']:
                out=io.BytesIO();im.save(out,format=fmt)
                image=request('/api/watermark-images/import',{'filename':'test.'+fmt.lower(),'data':base64.b64encode(out.getvalue()).decode()})
                assert image['item']['format']==fmt
                request('/api/watermark-images/delete',{'id':image['id']})
            metadata={'title':'PG核验图','type':'screen','status':'reviewed','endpoint':ep['name'],'ip':ep['ip'],'user':ep['user'],'policyId':wm['id'],'time':'2026-10-23T02:30:00Z','content':'已核验水印'}
            request('/api/watermark-images/save',{'id':image_id,'metadata':{**metadata,'ip':'999.1.1.1'}},ok=False)
            request('/api/watermark-images/save',{'id':image_id,'metadata':{**metadata,'policyId':'missing'}},ok=False)
            saved=request('/api/watermark-images/save',{'id':image_id,'metadata':metadata})['item'];assert saved['time']=='2026-10-23 10:30:00'
            if data['imageCapabilities']['ocr']:
                recognized=request('/api/watermark-images/ocr',{'id':image_id});assert recognized['item']['content']=='已核验水印'
            print('PASS PNG/JPEG/WEBP BYTEA originals/thumbnails, authentication, deduplication, rejection, metadata, UTC conversion and OCR',flush=True)

            backup=script('backup_db.py',['--output-dir',str(Path(tmp)/'backups')]).stdout.strip()
            assert Path(backup).stat().st_mode&0o777==0o600
            restored=database()
            restore_env=dict(environment,PGHOST=environment.get('DLP_DB_HOST','127.0.0.1'),PGPORT=environment.get('DLP_DB_PORT','5432'),
                PGUSER=environment.get('DLP_DB_USER','dlpcenter'),PGPASSWORD=environment.get('DLP_DB_PASSWORD',''))
            subprocess.run(['pg_restore','--no-owner','--no-acl','--exit-on-error','--dbname',restored,backup],env=restore_env,check=True,capture_output=True,timeout=30)
            with psycopg2.connect(host=restore_env['PGHOST'],port=restore_env['PGPORT'],user=restore_env['PGUSER'],password=restore_env['PGPASSWORD'],dbname=restored) as restored_db:
                with restored_db.cursor() as c:
                    c.execute('SELECT original FROM dlp_watermark_images WHERE id=%s',(image_id,));assert bytes(c.fetchone()[0])==original
                    c.execute("SELECT data FROM dlp_records WHERE kind='watermarkImages' AND id=%s",(image_id,));assert c.fetchone()[0]['content']=='已核验水印'
            print('PASS pg_restore into a separate database, including original bytes and metadata',flush=True)
            process.terminate();process.wait(timeout=10);start()
            persisted=request('/api/bootstrap');assert next(e for e in persisted['events'] if e['id']==event['id'])['note']=='PostgreSQL disposition'
            assert next(w for w in persisted['watermarkImages'] if w['id']==image_id)['content']=='已核验水印'
            assert request('/api/watermark-image/'+image_id)==original
            for kind,ident in [('watermarks',wm['id']),('policies',policy['id'])]:request('/api/delete',{'kind':kind,'id':ident})
            request('/api/watermark-images/delete',{'id':image_id});request('/api/watermark-image/'+image_id,ok=False)
            request('/api/logout',{});request('/api/bootstrap',ok=False)
            print('PASS pg_dump backup, restart persistence, delete and logout revocation',flush=True)

            # Exercise the old SQLite upgrade path without importing old runtime sessions.
            legacy=Path(tmp)/'legacy.db';salt='verification-salt';password=environment['DLP_ADMIN_PASSWORD']
            with sqlite3.connect(legacy) as c:
                c.executescript('CREATE TABLE records(kind TEXT,id TEXT,data TEXT);CREATE TABLE users(name TEXT,salt TEXT,hash TEXT);CREATE TABLE sessions(token TEXT,expires REAL);CREATE TABLE settings(id INTEGER,data TEXT);CREATE TABLE watermark_images(id TEXT,original BLOB,thumbnail BLOB,hash TEXT,mime TEXT);CREATE TABLE audit(id INTEGER,time TEXT,actor TEXT,action TEXT,target TEXT,detail TEXT);CREATE TABLE migrations(name TEXT);')
                sample={'id':'legacy-record','title':'保留的既有记录'}
                c.execute('INSERT INTO records VALUES(?,?,?)',('events',sample['id'],json.dumps(sample)))
                c.execute('INSERT INTO users VALUES(?,?,?)',('admin',salt,hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),200000).hex()))
                c.execute('INSERT INTO settings VALUES(1,?)',(json.dumps(data['settings']),))
                c.execute('INSERT INTO watermark_images VALUES(?,?,?,?,?)',('WIMG-0123456789AB',original,original,hashlib.sha256(original).hexdigest(),'image/png'))
                c.execute("INSERT INTO migrations VALUES('watermarks-v1')")
                c.execute('INSERT INTO audit VALUES(1,?,?,?,?,?)',('2026-10-23 10:30:00','旧管理员','旧操作','旧目标','旧记录'))
            migration_env=dict(environment,DLP_DB_NAME=database())
            migrated=script('migrate_sqlite_to_postgres.py',['--sqlite',str(legacy)],env=migration_env)
            repeated=script('migrate_sqlite_to_postgres.py',['--sqlite',str(legacy)],env=migration_env)
            assert '跳过' in repeated.stdout
            settings=dict(host=migration_env.get('DLP_DB_HOST','127.0.0.1'),port=migration_env.get('DLP_DB_PORT','5432'),user=migration_env.get('DLP_DB_USER','dlpcenter'),password=migration_env.get('DLP_DB_PASSWORD',''),dbname=migration_env['DLP_DB_NAME'])
            with psycopg2.connect(**settings) as target:
                with target.cursor() as c:
                    c.execute('SELECT data FROM dlp_records');assert c.fetchone()[0]==sample
                    c.execute('SELECT original FROM dlp_watermark_images');assert bytes(c.fetchone()[0])==original
                    c.execute('SELECT count(*) FROM user_tokens');assert c.fetchone()[0]==0
                    c.execute('SELECT operator_name FROM operation_logs');assert c.fetchone()[0]=='旧管理员'
            print('PASS transactional SQLite-to-PostgreSQL migration, JSON/BYTEA integrity, audit preservation, account conversion and rerun protection',flush=True)
            print('All PostgreSQL integration checks passed.',flush=True)
        finally:
            if process and process.poll() is None:process.terminate();process.wait(timeout=10)
            log.close()
            for name in databases:
                with admin.cursor() as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            admin.close()


if __name__=='__main__':main()
