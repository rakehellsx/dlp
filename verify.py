"""Run integration checks against an isolated temporary database; requires Pillow."""
import base64
import hashlib
import io
import random
from PIL import Image
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def main():
    with tempfile.TemporaryDirectory(prefix='sentinel-verify-') as tmp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, DLP_DB=str(Path(tmp) / 'test.db'), DLP_ADMIN_PASSWORD='Test-Only-Password!')
        command = [sys.executable, str(Path(__file__).with_name('server.py')), '--port', str(port)]
        jar = http.cookiejar.CookieJar()
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def start():
            p = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                try:
                    urllib.request.urlopen(base + '/health', timeout=1).read(); return p
                except OSError:
                    time.sleep(.05)
            p.terminate(); raise RuntimeError('Server did not start')

        def request(path, body=None, expected=200, protected=True):
            headers = {'Content-Type': 'application/json'}
            if protected: headers['X-DLP-Request'] = '1'
            req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
            try:
                response = client.open(req, timeout=5)
            except urllib.error.HTTPError as exc:
                assert exc.code == expected, (path, exc.code, expected)
                return json.load(exc)
            assert response.status == expected, (path, response.status, expected)
            data = response.read()
            return json.loads(data) if 'json' in response.headers.get('Content-Type', '') else data

        no_password = dict(env, DLP_DB=str(Path(tmp) / 'unconfigured.db'))
        no_password.pop('DLP_ADMIN_PASSWORD', None)
        missing = subprocess.run(command, env=no_password, capture_output=True, timeout=10)
        assert missing.returncode != 0 and b'DLP_ADMIN_PASSWORD' in missing.stderr
        print('PASS fresh installation requires an explicit administrator password')
        process = start()
        try:
            request('/api/bootstrap', expected=401)
            request('/api/watermark-image/WIMG-0123456789AB', expected=401)
            request('/api/login', {'username': 'admin', 'password': 'wrong'}, expected=401)
            request('/api/login', {'username': 'admin', 'password': 'Test-Only-Password!'})
            data = request('/api/bootstrap')
            assert len(data['events']) == 186 and len(data['endpoints']) == 128
            print('PASS login, authentication, initial data')

            # Exercise the upgrade path of an existing installation, including its legacy template.
            request('/api/settings', {'watermark': '既有企业模板 · {姓名}'})
            process.terminate(); process.wait(timeout=5)
            env.pop('DLP_ADMIN_PASSWORD')  # Existing credentials survive upgrades without this variable.
            with sqlite3.connect(env['DLP_DB']) as c:
                c.execute("DELETE FROM records WHERE kind='watermarks'")
                c.execute("DELETE FROM migrations WHERE name='watermarks-v1'")
            process = start()
            data = request('/api/bootstrap')
            assert len(data['events']) == 186 and len(data['endpoints']) == 128
            assert next(w for w in data['watermarks'] if w['type'] == 'print')['content'] == '既有企业模板 · {姓名}'
            print('PASS existing database upgrade preserves business records and legacy watermark content')

            assert {w['type'] for w in data['watermarks']} == {'print', 'screen', 'screenshot'}
            wm = request('/api/save', {'kind': 'watermarks', 'item': {
                'name': '研发打印水印验证', 'type': 'print', 'scope': '研发中心',
                'condition': 'apps', 'apps': ['Office 文档', 'PDF 阅读器'],
                'content': '内部资料 · {姓名}\n{时间}', 'fontSize': 24, 'opacity': 30,
                'angle': -25, 'position': 'tile', 'color': '#528d73', 'bold': True,
                'paperSize': 'A3', 'bothSides': False, 'printers': '研发打印机',
            }})['item']
            request('/api/save', {'kind': 'watermarks', 'item': {**wm, 'content': '修改后 · {部门}'}})
            request('/api/update', {'kind': 'watermarks', 'ids': [wm['id']], 'changes': {'enabled': False}})
            saved_wm = next(w for w in request('/api/bootstrap')['watermarks'] if w['id'] == wm['id'])
            assert saved_wm['content'] == '修改后 · {部门}' and not saved_wm['enabled']
            assert saved_wm['paperSize'] == 'A3' and saved_wm['bothSides'] is False
            for changes in [{'fontSize': 100}, {'color': 'red;script'}, {'opacity': -1},
                            {'angle': 100}, {'scope': '未知部门'}, {'content': ''},
                            {'content': '{不支持的字段}'}, {'apps': []}, {'type': 'unknown'},
                            {'type': 'screenshot', 'screenshotMethods': []}, {'bold': 'yes'}]:
                request('/api/save', {'kind': 'watermarks', 'item': {**wm, **changes}}, expected=400)
            request('/api/update', {'kind': 'watermarks', 'ids': [wm['id']], 'changes': {'enabled': 'false'}}, expected=400)
            request('/api/delete', {'kind': 'watermarks', 'id': 'WM-CAPTURE-001'})
            print('PASS watermark types, create/edit/toggle, scenario settings and invalid configuration rejection')

            assert data['imageCapabilities']['images']
            image = Image.frombytes('RGB', (512,512), random.Random(42).randbytes(512*512*3))
            stream = io.BytesIO(); image.save(stream, format='PNG'); original = stream.getvalue()
            upload = {'filename':'水印测试.png', 'data':base64.b64encode(original).decode(), 'note':'图片导入验证'}
            imported = request('/api/watermark-images/import', upload)
            image_id = imported['id']; record = imported['item']
            assert not imported['duplicate'] and record['status'] == 'pending'
            assert record['hash'] == hashlib.sha256(original).hexdigest()
            assert request('/api/watermark-image/'+image_id) == original
            assert request('/api/watermark-image/'+image_id+'?download=1') == original
            assert request('/api/watermark-image/'+image_id+'?thumb=1').startswith(b'\xff\xd8')
            duplicate = request('/api/watermark-images/import',upload)
            assert duplicate['duplicate'] and duplicate['id'] == image_id
            assert len(request('/api/bootstrap')['watermarkImages']) == 1
            for bad in ['not-base64!', base64.b64encode(b'<svg></svg>').decode()]:
                request('/api/watermark-images/import', {**upload,'data':bad}, expected=400)
            tiny=io.BytesIO();Image.new('RGB',(10,10)).save(tiny,format='PNG')
            request('/api/watermark-images/import', {**upload,'data':base64.b64encode(tiny.getvalue()).decode()},expected=400)
            for fmt in ['JPEG','WEBP']:
                buf=io.BytesIO();image.save(buf,format=fmt)
                other=request('/api/watermark-images/import', {'filename':'测试.'+fmt.lower(),'data':base64.b64encode(buf.getvalue()).decode()})
                assert other['item']['format'] == fmt
                request('/api/watermark-images/delete', {'id':other['id']})
                request('/api/watermark-image/'+other['id'], expected=404)
            ep_image=data['endpoints'][0]; wm_image=data['watermarks'][0]
            meta={'title':'已核验的水印截图','type':'screen','status':'reviewed','endpoint':ep_image['name'],
                  'ip':ep_image['ip'],'user':ep_image['user'],'department':ep_image['department'],
                  'time':'2026-10-22T10:30:00Z','policyId':wm_image['id'],'content':'仅供内部使用','note':'人工核验'}
            request('/api/watermark-images/save', {'id':image_id,'metadata':{**meta,'ip':'999.1.1.1'}},expected=400)
            request('/api/watermark-images/save', {'id':image_id,'metadata':{**meta,'policyId':'missing'}},expected=400)
            saved_image=request('/api/watermark-images/save', {'id':image_id,'metadata':meta})['item']
            assert saved_image['time']=='2026-10-22 18:30:00'
            from watermark_images import suggestions
            hints=suggestions(f"{ep_image['ip']} 2026-10-22 18:30:00 {wm_image['id']}",data['endpoints'],data['watermarks'])
            assert hints['endpoint']==ep_image['name'] and hints['user']==ep_image['user'] and hints['policyId']==wm_image['id']
            assert image_id.encode() in request('/api/export?kind=watermarkImages')
            print('PASS PNG/JPEG/WEBP imports, original integrity, thumbnail, deduplication, invalid files, metadata, associations and export')

            backup_result = subprocess.run([sys.executable, str(Path(__file__).parent/'scripts'/'backup_db.py'),
                '--database',env['DLP_DB'],'--output-dir',str(Path(tmp)/'backups')],
                check=True, capture_output=True, text=True, timeout=15)
            backup_path = Path(backup_result.stdout.strip())
            assert backup_path.stat().st_mode & 0o777 == 0o600
            with sqlite3.connect(backup_path) as backup:
                assert backup.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                assert backup.execute('SELECT original FROM watermark_images WHERE id=?',(image_id,)).fetchone()[0] == original
                metadata_backup = json.loads(backup.execute("SELECT data FROM records WHERE kind='watermarkImages' AND id=?",(image_id,)).fetchone()[0])
                assert metadata_backup['content'] == '仅供内部使用' and metadata_backup['status'] == 'reviewed'
            print('PASS live SQLite backup includes original image and verified metadata with private file permissions')

            request('/api/save', {'kind': 'policies', 'item': {'name': 'CSRF'}}, expected=403, protected=False)
            policy = request('/api/save', {'kind': 'policies', 'item': {'name': '测试防护策略', 'rule': '个人信息', 'channels': 'USB 外设', 'scope': '研发中心', 'action': 'block', 'priority': 9}})['item']
            request('/api/update', {'kind': 'policies', 'ids': [policy['id']], 'changes': {'enabled': False}})
            saved = next(x for x in request('/api/bootstrap')['policies'] if x['id'] == policy['id'])
            assert not saved['enabled']
            print('PASS policy create/update/toggle, CSRF protection')

            event = data['events'][0]
            request('/api/update', {'kind': 'events', 'ids': [event['id']], 'changes': {'status': 'resolved', 'note': '测试处置记录'}})
            ep = data['endpoints'][0]
            request('/api/update', {'kind': 'endpoints', 'ids': [ep['id']], 'changes': {'isolated': True}})
            approval = next(a for a in data['approvals'] if a['status'] == 'pending')
            request('/api/update', {'kind': 'approvals', 'ids': [approval['id']], 'changes': {'status': 'approved', 'comment': '同意测试'}})
            result = request('/api/update', {'kind': 'approvals', 'ids': [approval['id']], 'changes': {'status': 'rejected', 'comment': '重复审批'}})
            assert result['count'] == 0
            print('PASS event disposition, endpoint isolation, approval and duplicate protection')

            result = request('/api/detect', {'content': '机密，年度财务预算，测试手机号13800000000，身份证110101199001010010'})
            assert {'个人信息', '商业机密', '财务数据'} <= {x['rule'] for x in result['hits']}
            request('/api/scan', {'name': '测试扫描', 'scope': '研发中心'})
            request('/api/scan', {'name': '重复扫描', 'scope': '研发中心'}, expected=409)
            report = request('/api/report', {'name': '集成验证报告', 'period': '最近7天'})['item']
            assert report['events'] > 0 and report['blocked'] > 0 and report['assets'] == 72
            export = request('/api/export?kind=events')
            assert export.startswith(b'\xef\xbb\xbf') and event['id'].encode() in export
            request('/api/settings', {'company': '测试企业', 'retention': 365})
            request('/api/settings', {'retention': 1}, expected=400)
            print('PASS detection, scan lifecycle guards, report snapshot, CSV export, settings')

            process.terminate(); process.wait(timeout=5)
            process = start()
            data = request('/api/bootstrap')
            assert next(e for e in data['events'] if e['id'] == event['id'])['note'] == '测试处置记录'
            assert next(e for e in data['endpoints'] if e['id'] == ep['id'])['isolated']
            assert next(a for a in data['approvals'] if a['id'] == approval['id'])['status'] == 'approved'
            assert data['settings']['company'] == '测试企业' and data['settings']['retention'] == 365
            persisted = next(w for w in data['watermarks'] if w['id'] == wm['id'])
            assert persisted['content'] == '修改后 · {部门}' and persisted['enabled'] is False
            assert not any(w['id'] == 'WM-CAPTURE-001' for w in data['watermarks'])
            persisted_image=next(w for w in data['watermarkImages'] if w['id']==image_id)
            assert persisted_image['status']=='reviewed' and persisted_image['content']=='仅供内部使用'
            assert request('/api/watermark-image/'+image_id)==original
            request('/api/watermark-images/delete', {'id':image_id})
            assert not request('/api/bootstrap')['watermarkImages']
            request('/api/watermark-image/'+image_id, expected=404)
            print('PASS original image and verified metadata survive restart, deletion removes both')
            request('/api/delete', {'kind': 'watermarks', 'id': wm['id']})
            assert not any(w['id'] == wm['id'] for w in request('/api/bootstrap')['watermarks'])
            assert len(data['audit']) >= 10
            request('/api/delete', {'kind': 'policies', 'id': policy['id']})
            request('/api/logout', {})
            request('/api/bootstrap', expected=401)
            print('PASS database/session persistence after restart, audit trail, delete, logout')
            print('All integration checks passed.')
        finally:
            process.terminate(); process.wait(timeout=5)


if __name__ == '__main__':
    main()
