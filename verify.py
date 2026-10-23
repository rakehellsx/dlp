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
import tarfile
import time
import urllib.parse
import urllib.error
import urllib.request

from PIL import Image
import psycopg2
from psycopg2 import sql

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'scripts'))
from pg_common import connect


def connect_test(env):
    return psycopg2.connect(host=env.get('DLP_DB_HOST','127.0.0.1'),port=env.get('DLP_DB_PORT','5432'),user=env.get('DLP_DB_USER','dlpcenter'),password=env.get('DLP_DB_PASSWORD',''),dbname=env['DLP_DB_NAME'],options='-c timezone=Asia/Shanghai')

def main():
    admin=connect();admin.autocommit=True
    databases=[];process=None
    with tempfile.TemporaryDirectory(prefix='dlpcenter-verify-') as tmp:
        environment=dict(os.environ,DLP_PYTHON=sys.executable,PYTHONUTF8='1',DLP_ADMIN_PASSWORD='Integration-Only-Password!',TZ='Asia/Shanghai',
            DLP_FILE_ROOT=str(Path(tmp)/'files'),DLP_IMAGE_HELPER=str(ROOT/'dlpcenter/tools/image_processor.py'),DLP_CONFIG=str(ROOT/'dlpcenter/config.json'),DLP_STATIC_ROOT=str(ROOT/'static'))
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
        def state():
            result=request('/api/bootstrap')
            for kind in ['events','endpoints','policies','rules','assets','approvals','scans','reports','watermarks','watermarkImages']:
                found=[];page=1
                while True:
                    response=request('/api/query?'+urllib.parse.urlencode({'kind':kind,'pageSize':100,'page':page}))
                    found.extend(response['items'])
                    if len(found)>=response['total']:break
                    page+=1
                result[kind]=found
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
            # Exercise a legacy PostgreSQL layout, including ambiguous and conflicting evidence.
            legacy_endpoint_env=dict(environment,DLP_DB_NAME=database())
            with connect_test(legacy_endpoint_env) as db,db.cursor() as c:
                from psycopg2.extras import Json
                c.execute((ROOT/'dlpcenter/sql/init.sql').read_text())
                for code,name,ip in [('EP-A','shared','10.1.0.1'),('EP-B','shared','10.1.0.2'),('EP-C','unique','10.1.0.3')]:
                    c.execute('INSERT INTO dlp_records(kind,id,data) VALUES(%s,%s,%s)',('endpoints',code,Json({'id':code,'name':name,'ip':ip,'custom':'preserved'})))
                for ident,values in [('explicit',{'endpointId':'EP-A'}),('unique',{'endpoint':'unique'}),('ambiguous',{'endpoint':'shared'}),('conflicting',{'endpoint':'unique','ip':'10.1.0.1'}),('unknown',{'endpoint':'absent'}),('bad-code',{'endpointId':'EP-MISSING'})]:
                    c.execute('INSERT INTO dlp_records(kind,id,data) VALUES(%s,%s,%s)',('events',ident,Json({'id':ident,**values})))
            rejected=script('migrate_endpoints.py',env=legacy_endpoint_env,check=False)
            assert rejected.returncode and 'Unknown legacy endpointId' in rejected.stderr
            with connect_test(legacy_endpoint_env) as db,db.cursor() as c:
                c.execute("SELECT count(*) FROM dlp_records WHERE kind='endpoints'");assert c.fetchone()[0]==3
                c.execute("SELECT to_regclass('endpoints')");assert c.fetchone()[0] is None
                c.execute("DELETE FROM dlp_records WHERE id='bad-code'")
            script('migrate_endpoints.py',env=legacy_endpoint_env)
            with connect_test(legacy_endpoint_env) as db,db.cursor() as c:
                c.execute('SELECT endpoint_code,endpoint_uid::text FROM endpoints ORDER BY endpoint_code');identities=dict(c.fetchall())
                c.execute("SELECT data FROM endpoint_records WHERE id='EP-C'");assert c.fetchone()[0]['custom']=='preserved'
                c.execute("SELECT id,endpoint_uid::text FROM dlp_records ORDER BY id");links=dict(c.fetchall())
                assert links['explicit']==identities['EP-A'] and links['unique']==identities['EP-C']
                assert all(links[k] is None for k in ['ambiguous','conflicting','unknown'])
            script('migrate_endpoints.py',env=legacy_endpoint_env)
            with connect_test(legacy_endpoint_env) as db,db.cursor() as c:
                c.execute('SELECT endpoint_code,endpoint_uid::text FROM endpoints ORDER BY endpoint_code');assert dict(c.fetchall())==identities
            print('PASS endpoint migration rollback, stable UUIDs, unique/conflicting/ambiguous matching, unknown sources and custom-field preservation',flush=True)

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
            data=state();assert len(data['events'])==186 and len(data['endpoints'])==128
            assert request('/health')['database']=='PostgreSQL'
            import uuid
            endpoint=data['endpoints'][0];uid=endpoint['endpointUid']
            assert str(uuid.UUID(uid))==uid and len({e['endpointUid'] for e in data['endpoints']})==128
            with connect_test(environment) as db,db.cursor() as c:
                c.execute("SELECT count(*) FROM dlp_records WHERE kind='endpoints'");assert c.fetchone()[0]==0
                c.execute('SELECT count(*) FROM endpoints');assert c.fetchone()[0]==128
                c.execute("SELECT kind,count(*),count(endpoint_uid) FROM dlp_records WHERE kind IN ('events','assets') GROUP BY kind")
                assert {k:(n,linked) for k,n,linked in c.fetchall()}=={'events':(186,186),'assets':(72,72)}
            initial_detail=request('/api/detail?kind=endpoints&id='+uid)
            initial_related=initial_detail['related']['eventCount'];assert initial_related>0
            assert request('/api/query?kind=events&endpointUid='+uid)['total']==initial_related
            request('/api/query?kind=events&endpointUid=invalid',ok=False)
            for badsql,args in [
                ('INSERT INTO endpoints(endpoint_code) VALUES(%s)',(endpoint['id'],)),
                ('UPDATE endpoints SET endpoint_uid=%s WHERE endpoint_uid=%s',(str(uuid.uuid4()),uid)),
                ('DELETE FROM endpoints WHERE endpoint_uid=%s',(uid,)),
                ("UPDATE dlp_records SET endpoint_uid=%s WHERE kind='events' AND id=%s",(str(uuid.uuid4()),data['events'][0]['id'])),
                ("INSERT INTO dlp_records(kind,id,data) VALUES('endpoints','FORBIDDEN','{}')",())]:
                try:
                    with connect_test(environment) as db,db.cursor() as c:c.execute(badsql,args)
                    raise AssertionError('Database constraint accepted invalid data')
                except psycopg2.Error:pass
            with connect_test(environment) as db,db.cursor() as c:
                c.execute("UPDATE endpoints SET name='renamed-device',ip_address='10.99.0.7' WHERE endpoint_uid=%s",(uid,))
            renamed=request('/api/detail?kind=endpoints&id='+uid)
            assert renamed['item']['name']=='renamed-device' and renamed['related']['eventCount']==initial_related
            assert request('/api/query?kind=endpoints&q=10.99.0.7')['items'][0]['endpointUid']==uid
            with connect_test(environment) as db,db.cursor() as c:
                c.execute('UPDATE endpoints SET name=%s,ip_address=%s WHERE endpoint_uid=%s',(endpoint['name'],endpoint['ip'],uid))
            print('PASS dedicated endpoint table, UUID search/detail/filter, SQL foreign keys, immutable identity, legacy code compatibility and rename/IP-stable relationships',flush=True)

            print('PASS PostgreSQL initialization, idempotent demo seed, imported login/profile, Bearer and HttpOnly cookie authentication',flush=True)
            boot=request('/api/bootstrap');assert 'events' not in boot and len(boot['options']['departments'])==6
            first=request('/api/query?kind=events&pageSize=7&page=1');second=request('/api/query?kind=events&pageSize=7&page=2')
            assert first['total']==186 and len(first['items'])==7 and not {r['id'] for r in first['items']}&{r['id'] for r in second['items']}
            for filters in [{'q':data['events'][0]['user']},{'department':'研发中心','status':'pending'},{'severity':'high','channel':'即时通讯'}]:
                actual=request('/api/query?'+urllib.parse.urlencode(dict(kind='events',pageSize=100,**filters)))
                matching=[r for r in data['events'] if all((value in ' '.join(str(r.get(k,'')) for k in ['id','title','file','user','endpoint','ip','department'])) if key=='q' else r.get(key)==value for key,value in filters.items())]
                assert actual['total']==len(matching) and {r['id'] for r in actual['items']}=={r['id'] for r in matching}
            for bad in ['kind=events&page=0','kind=events&pageSize=10000','kind=events&sort=bad','kind=missing']:
                request('/api/query?'+bad,ok=False)
            assert request('/api/query?'+urllib.parse.urlencode({'kind':'events','q':"' OR 1=1 --"}))['total']==0
            request('/api/statistics?period=2',ok=False)
            # Direct SQL changes must appear immediately in every endpoint, without a restart or browser cache refresh.
            from psycopg2.extras import Json
            injected={**data['events'][0],'id':'DB-ONLY-5001','title':'SQL_LIVE_百分号%下划线_','status':'pending','severity':'high','time':time.strftime('%Y-%m-%d %H:%M:%S')}
            with connect_test(environment) as db:
                with db.cursor() as c:c.execute('INSERT INTO dlp_records(kind,id,data) VALUES(%s,%s,%s)',('events',injected['id'],Json(injected)))
            try:
                queried=request('/api/query?'+urllib.parse.urlencode({'kind':'events','q':'SQL_LIVE_百分号%下划线_'}));assert queried['total']==1 and queried['items'][0]['id']==injected['id']
                assert request('/api/search?'+urllib.parse.urlencode({'q':'SQL_LIVE_百分号%下划线_'}))['items'][0]['id']==injected['id']
                assert request('/api/detail?kind=events&id='+injected['id'])['item']['title']==injected['title']
                stats=request('/api/statistics?period=30');assert stats['counts']['events']==187
                assert sum(r['all'] for r in stats['trend'])>0
                assert stats['navigation']['pendingEvents']==sum(r['status']=='pending' for r in data['events'])+1
                assert injected['id'].encode() in request('/api/export?'+urllib.parse.urlencode({'kind':'events','q':'SQL_LIVE_百分号%下划线_'}))
                endpoint=request('/api/detail?kind=endpoints&id='+injected['endpointId']);assert endpoint['related']['eventCount']>=1
            finally:
                with connect_test(environment) as db:
                    with db.cursor() as c:c.execute("DELETE FROM dlp_records WHERE kind='events' AND id=%s",(injected['id'],))
            print('PASS SQL filtering, server pagination, literal wildcard/injection safety, live DB search/detail/aggregate/export and relationships',flush=True)


            request('/api/user/list',opener=anonymous,ok=False)
            for query in ['page=0','page=-1','page=99999999','pageSize=101','pageSize=no','role=invalid','status=invalid']:
                request('/api/user/list?'+query,ok=False)
            request('/api/user/delete',{'username':'admin'},ok=False)
            request('/api/user/create',{'username':{},'password_hash':[]},ok=False)
            request('/api/user/disable',{'username':'admin','disabled':'true'},ok=False)
            request('/api/user/change_password',{'old_password_hash':{},'new_password_hash':[]},ok=False)
            user_hash=hashlib.sha256(b'Regular-Test-Only!').hexdigest()
            user=request('/api/user/create',{'username':'verify-user','password_hash':user_hash,'role':'user'})
            assert isinstance(user['id'],int) and user['id']>0
            listing=request('/api/user/list?pageSize=1')
            assert listing['total']==2 and listing['pageSize']==1 and len(listing['items'])==1
            assert listing['items'][0]['username']=='verify-user'
            assert listing['stats']=={'total':2,'enabled':2,'disabled':0,'admins':1}
            assert set(listing['items'][0])=={'id','username','role','disabled','created_at'}
            assert request('/api/user/list?pageSize=1&page=2')['items'][0]['username']=='admin'
            assert request('/api/user/list?pageSize=1&page=99')['page']==2
            assert request('/api/user/list?q=VERIFY&role=user&status=enabled')['total']==1
            assert request('/api/user/list?role=admin')['items'][0]['username']=='admin'
            for word in ['%', '_', "' OR 1=1 --"]:
                assert request('/api/user/list?'+urllib.parse.urlencode({'q':word}))['total']==0
            with connect_test(environment) as db:
                with db.cursor() as c:
                    c.execute('SELECT username,role,disabled FROM users WHERE id=%s',(user['id'],))
                    assert c.fetchone()==('verify-user','user',False)

            request('/api/user/create',{'username':'verify-user','password_hash':user_hash},ok=False)
            other=urllib.request.build_opener();regular=login('Regular-Test-Only!','verify-user',opener=other)['token']
            assert request('/api/bootstrap',opener=other,token=regular)['user']['role']=='user'
            request('/api/save',{'kind':'policies','item':{'name':'Denied'}},opener=other,token=regular,ok=False)
            request('/api/user/create',{'username':'denied','password_hash':user_hash},opener=other,token=regular,ok=False)
            request('/api/user/list',opener=other,token=regular,ok=False)
            request('/api/user/delete',{'username':'admin'},opener=other,token=regular,ok=False)
            request('/api/user/disable',{'username':'admin','disabled':True},ok=False)
            request('/api/user/disable',{'username':'verify-user','disabled':True})
            disabled_users=request('/api/user/list?status=disabled')
            assert disabled_users['total']==1 and disabled_users['items'][0]['disabled'] is True
            assert disabled_users['stats']['disabled']==1 and disabled_users['stats']['enabled']==1
            with connect_test(environment) as db:
                with db.cursor() as c:
                    c.execute('SELECT count(*) FROM user_tokens WHERE user_id=%s',(user['id'],))
                    assert c.fetchone()[0]==0

            request('/api/bootstrap',opener=other,token=regular,ok=False)
            login('Regular-Test-Only!','verify-user',opener=other,ok=False)
            request('/api/user/disable',{'username':'verify-user','disabled':False})
            assert request('/api/user/list?status=enabled')['total']==2
            regular=login('Regular-Test-Only!','verify-user',opener=other)['token']
            request('/api/user/delete',{'username':'verify-user'})
            assert request('/api/user/list?q=verify-user')['total']==0
            request('/api/user/profile',opener=other,token=regular,ok=False)
            with connect_test(environment) as db:
                with db.cursor() as c:
                    c.execute('SELECT count(*) FROM user_tokens WHERE user_id=%s',(user['id'],))
                    assert c.fetchone()[0]==0

            request('/api/user/change_password',{'old_password_hash':hashlib.sha256(b'wrong').hexdigest(),'new_password_hash':user_hash},ok=False)
            print('PASS user management SQL search/filter/pagination/stats, create/duplicate, access control, self protection, disable/enable/delete and session revocation',flush=True)

            original_hash=hashlib.sha256(b'Integration-Only-Password!').hexdigest()
            changed_password='Updated-Integration-Only!'
            changed_hash=hashlib.sha256(changed_password.encode()).hexdigest()
            second_token=login(opener=anonymous)['token']
            before_tokens=request('/api/user/tokens')['count']
            request('/api/user/change_password',{'old_password_hash':original_hash,'new_password_hash':original_hash},ok=False)
            request('/api/user/change_password',{'old_password_hash':original_hash,'new_password_hash':changed_hash},csrf=False,ok=False)
            request('/api/user/change_password',{'old_password_hash':hashlib.sha256(b'wrong').hexdigest(),'new_password_hash':changed_hash},ok=False)
            assert request('/api/user/tokens')['count']==before_tokens
            request('/api/user/change_password',{'old_password_hash':original_hash,'new_password_hash':changed_hash})
            assert not any(cookie.name=='dlp_token' for cookie in jar)
            request('/api/user/profile',opener=anonymous,token=token,ok=False)
            request('/api/user/profile',opener=anonymous,token=second_token,ok=False)
            login(ok=False)
            token=login(changed_password)['token']
            with connect_test(environment) as db:
                with db.cursor() as c:
                    c.execute("SELECT password_hash FROM users WHERE username='admin'")
                    stored=c.fetchone()[0]
                    assert stored.startswith('$2') and original_hash not in stored and changed_hash not in stored
                    c.execute("SELECT count(*) FROM operation_logs WHERE action='change_password' AND success AND detail LIKE '%撤销%'")
                    assert c.fetchone()[0]==1
            # Restore only the disposable test account so later migration/restore checks use its original password.
            request('/api/user/change_password',{'old_password_hash':changed_hash,'new_password_hash':original_hash})
            token=login()['token']
            print('PASS password changes: old/same password and CSRF validation, atomic bcrypt update and audit, all-session revocation, cookie expiry and new-password login',flush=True)

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
            request('/api/settings',{'company':'PostgreSQL 测试企业','retention':365,'email':'pg@example.test','offlineProtection':False,'autoUpdate':False,'notification':False})
            saved_settings=request('/api/bootstrap')['settings'];assert saved_settings['retention']==365 and saved_settings['email']=='pg@example.test' and not saved_settings['offlineProtection'] and not saved_settings['autoUpdate'] and not saved_settings['notification']
            with connect_test(environment) as db:
                with db.cursor() as c:c.execute('SELECT data FROM dlp_settings WHERE id=1');assert c.fetchone()[0]==saved_settings
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
            metadata={'title':'PG核验图','type':'screen','status':'reviewed','endpoint':ep['name'],'endpointUid':ep['endpointUid'],'ip':ep['ip'],'user':ep['user'],'policyId':wm['id'],'time':'2026-10-23T02:30:00Z','content':'已核验水印'}
            request('/api/watermark-images/save',{'id':image_id,'metadata':{**metadata,'ip':'999.1.1.1'}},ok=False)
            request('/api/watermark-images/save',{'id':image_id,'metadata':{**metadata,'policyId':'missing'}},ok=False)
            saved=request('/api/watermark-images/save',{'id':image_id,'metadata':metadata})['item'];assert saved['time']=='2026-10-23 10:30:00'
            if data['imageCapabilities']['ocr']:
                recognized=request('/api/watermark-images/ocr',{'id':image_id});assert recognized['item']['content']=='已核验水印'
            print('PASS PNG/JPEG/WEBP disk originals/thumbnails with PG metadata, authentication, deduplication, rejection, metadata, UTC conversion and OCR',flush=True)

            backup=script('backup_db.py',['--output-dir',str(Path(tmp)/'backups')]).stdout.strip()
            assert os.name == 'nt' or Path(backup).stat().st_mode&0o777==0o600
            restored=database();restored_root=Path(tmp)/'restored-files'
            restored_env=dict(environment,DLP_DB_NAME=restored,DLP_FILE_ROOT=str(restored_root))
            script('restore_backup.py',['--dump',backup],env=restored_env)
            with connect_test(restored_env) as restored_db:
                with restored_db.cursor() as c:
                    c.execute('SELECT original_path,original FROM dlp_watermark_images WHERE id=%s',(image_id,));image_path,blob=c.fetchone();assert blob is None and (restored_root/image_path).read_bytes()==original
                    c.execute("SELECT data FROM dlp_records WHERE kind='watermarkImages' AND id=%s",(image_id,));assert c.fetchone()[0]['content']=='已核验水印'
            assert script('restore_backup.py',['--dump',backup],env=restored_env,check=False).returncode
            print('PASS restore into an empty database with paired disk files, SHA integrity and overwrite refusal',flush=True)
            process.terminate();process.wait(timeout=10);start()
            persisted=state();assert persisted['settings']==saved_settings
            assert next(e for e in persisted['events'] if e['id']==event['id'])['note']=='PostgreSQL disposition'
            assert next(w for w in persisted['watermarkImages'] if w['id']==image_id)['content']=='已核验水印'
            related=request('/api/detail?kind=watermarkImages&id='+image_id)
            assert related['item']['endpointUid']==ep['endpointUid'] and related['related']['endpoint']['endpointUid']==ep['endpointUid']
            assert request('/api/query?kind=watermarkImages&endpointUid='+ep['endpointUid'])['total']>=1
            request('/api/watermark-images/save',{'id':image_id,'metadata':{**metadata,'endpointUid':str(uuid.uuid4())}},ok=False)
            # Reusing the old name/IP on another device cannot steal the saved association.
            with connect_test(environment) as db,db.cursor() as c:
                c.execute("UPDATE endpoints SET name='renamed-after-watermark',ip_address='10.88.0.1' WHERE endpoint_uid=%s",(ep['endpointUid'],))
                c.execute('INSERT INTO endpoints(endpoint_code,name,ip_address) VALUES(%s,%s,%s)',('EP-REUSED-IP',ep['name'],ep['ip']))
            related=request('/api/detail?kind=watermarkImages&id='+image_id)
            assert related['related']['endpoint']['endpointUid']==ep['endpointUid'] and related['related']['endpoint']['name']=='renamed-after-watermark'
            with connect_test(environment) as db,db.cursor() as c:
                c.execute("DELETE FROM endpoints WHERE endpoint_code='EP-REUSED-IP'")
                c.execute('UPDATE endpoints SET name=%s,ip_address=%s WHERE endpoint_uid=%s',(ep['name'],ep['ip'],ep['endpointUid']))
            request('/api/watermark-images/save',{'id':image_id,'metadata':{**metadata,'endpointUid':''}})
            assert request('/api/detail?kind=watermarkImages&id='+image_id)['related'].get('endpoint') is None
            request('/api/watermark-images/save',{'id':image_id,'metadata':metadata})
            print('PASS explicit watermark UUID association, invalid references, unbinding and protection against reused hostname/IP',flush=True)

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
            c.close()  # SQLite's transaction context does not close the Windows file handle.
            migration_env=dict(environment,DLP_DB_NAME=database(),DLP_FILE_ROOT=str(Path(tmp)/'migrated-files'))
            migrated=script('migrate_sqlite_to_postgres.py',['--sqlite',str(legacy)],env=migration_env)
            repeated=script('migrate_sqlite_to_postgres.py',['--sqlite',str(legacy)],env=migration_env)
            assert '跳过' in repeated.stdout
            script('migrate_image_files.py',env=migration_env)
            script('migrate_image_files.py',env=migration_env)
            settings=dict(host=migration_env.get('DLP_DB_HOST','127.0.0.1'),port=migration_env.get('DLP_DB_PORT','5432'),user=migration_env.get('DLP_DB_USER','dlpcenter'),password=migration_env.get('DLP_DB_PASSWORD',''),dbname=migration_env['DLP_DB_NAME'])
            with psycopg2.connect(**settings) as target:
                with target.cursor() as c:
                    c.execute('SELECT data FROM dlp_records');assert c.fetchone()[0]==sample
                    c.execute('SELECT original_path,original FROM dlp_watermark_images');relative,blob=c.fetchone();assert blob is None and (Path(migration_env['DLP_FILE_ROOT'])/relative).read_bytes()==original
                    c.execute('SELECT count(*) FROM user_tokens');assert c.fetchone()[0]==0
                    c.execute('SELECT operator_name FROM operation_logs');assert c.fetchone()[0]=='旧管理员'
            print('PASS transactional SQLite-to-PostgreSQL migration, JSON/disk integrity, audit preservation, account conversion and rerun protection',flush=True)
            print('All PostgreSQL integration checks passed.',flush=True)
        finally:
            if process and process.poll() is None:process.terminate();process.wait(timeout=10)
            log.close()
            for name in databases:
                with admin.cursor() as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            admin.close()


if __name__=='__main__':main()
