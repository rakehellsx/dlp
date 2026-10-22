#!/usr/bin/env python3
"""Sentinel DLP prototype. Image imports use Pillow; optional OCR uses Tesseract."""
import argparse
import csv
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from watermark_config import migrate as migrate_watermarks, validate as validate_watermark
import watermark_images

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('DLP_DB', str(ROOT / 'data' / 'sentinel.db')))
TZ = timezone(timedelta(hours=8))
COLLECTIONS = {'events', 'endpoints', 'policies', 'rules', 'assets', 'approvals', 'scans', 'reports', 'watermarks', 'watermarkImages'}


def now():
    return datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')


def connect():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def audit(c, action, target, detail=''):
    c.execute('INSERT INTO audit(time,actor,action,target,detail) VALUES(?,?,?,?,?)',
              (now(), '安全管理员', action, target, detail))


def put(c, kind, item):
    c.execute('INSERT INTO records(kind,id,data) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',
              (kind, item['id'], json.dumps(item, ensure_ascii=False)))


def items(c, kind):
    return [json.loads(r['data']) for r in c.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid', (kind,))]


def seed():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS records(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,time TEXT,actor TEXT,action TEXT,target TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,data TEXT);
        CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY,salt TEXT,hash TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,expires REAL);
        ''')
        if not c.execute('SELECT 1 FROM users').fetchone():
            salt = secrets.token_hex(16)
            pw = os.environ.get('DLP_ADMIN_PASSWORD')
            if not pw:
                raise SystemExit('首次启动请通过 DLP_ADMIN_PASSWORD 环境变量设置管理员密码')
            digest = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200000).hex()
            c.execute('INSERT INTO users VALUES(?,?,?)', ('admin', salt, digest))
        migrate_watermarks(c, put, audit)
        watermark_images.migrate(c)
        if c.execute("SELECT 1 FROM records WHERE kind='endpoints' LIMIT 1").fetchone():
            return
        departments = ['研发中心', '市场营销部', '财务部', '人力资源部', '产品设计部', '行政管理部']
        names = ['张明', '李欣', '王磊', '陈晨', '刘洋', '赵敏', '周远', '林晓', '许诺', '吴桐', '郑宇', '沈悦']
        channels = ['即时通讯', 'USB 外设', '浏览器上传', '电子邮件', '打印输出', '剪贴板']
        files = ['2026年Q4客户信息汇总.xlsx', '核心产品源代码.zip', '员工薪酬明细_10月.xlsx', '产品设计方案V3.2.pdf', '战略合作协议_未公开.docx', '年度财务预算表.xlsx', '客户联系方式.csv', '项目技术架构设计.pdf', '供应商报价单.xlsx', '研发路线图_2027.pptx', '员工个人信息登记.xlsx', '市场分析报告.pdf']
        for i in range(128):
            dep = departments[i % 6]
            put(c, 'endpoints', {'id': f'EP-{i+1:04d}', 'name': f'{["RD","MKT","FIN","HR","PD","ADM"][i%6]}-{["DESKTOP","LAPTOP"][i%2]}-{i+1:03d}', 'user': names[i%12], 'department': dep, 'ip': f'192.168.{10+i%6}.{20+i}', 'os': ['Windows 11', 'Windows 10', 'macOS 15', '统信 UOS'][i%4], 'status': 'offline' if i%19==18 else 'online', 'risk': 'high' if i%13==0 else ('medium' if i%5==0 else 'low'), 'version': '3.6.2', 'policy': ['研发源代码保护','客户信息外发防护','财务数据外发管控','客户信息外发防护','客户信息外发防护','客户信息外发防护'][i%6], 'lastSeen': now(), 'isolated': False})
        for i in range(186):
            ep = items(c, 'endpoints')[i%128]
            stamp = datetime.now(TZ) - timedelta(hours=((i/186)**1.45)*7*24, minutes=i%5*4+3)
            severity = 'high' if i%5 in (0,1) else ('medium' if i%5 in (2,3) else 'low')
            channel = channels[[0,0,1,0,2,1,3,2,0,4,3,5][i%12]]
            put(c, 'events', {'id': f'DLP-{stamp:%Y%m%d}-{186-i:04d}', 'title': ['敏感文件通过即时通讯外发', '敏感文件拷贝至移动设备', '敏感文件上传至外部网站', '敏感文件发送至外部邮箱', '敏感文档异常打印', '批量复制敏感文本'][channels.index(channel)], 'file': files[i%12], 'user': ep['user'], 'department': ep['department'], 'endpoint': ep['name'], 'endpointId': ep['id'], 'ip': ep['ip'], 'channel': channel, 'severity': severity, 'action': 'blocked' if i%4!=3 else 'audited', 'status': ['pending', 'pending', 'processing', 'resolved'][i%4], 'time': stamp.strftime('%Y-%m-%d %H:%M:%S'), 'policy': ['客户信息外发防护', '研发源代码保护', '财务数据外发管控'][i%3], 'matches': [128, 24, 86, 12, 36, 18][i%6], 'destination': ['微信 · 个人联系人', 'Kingston DataTraveler / USB', 'pan.baidu.com', 'partner@example.com', 'HP LaserJet M404', '系统剪贴板'][channels.index(channel)], 'size': f'{[2.4,18.6,1.8,4.2,0.8,0.1][i%6]} MB', 'note': ''})
        policy_specs = [('客户信息外发防护', '个人信息', '即时通讯、浏览器上传、电子邮件', 'block', '全体终端', 1), ('研发源代码保护', '源代码', 'USB 外设、浏览器上传', 'block', '研发中心', 1), ('财务数据外发管控', '财务数据', '电子邮件、USB 外设、打印输出', 'approval', '财务部', 1), ('机密文档打印审计', '商业机密', '打印输出', 'audit', '全体终端', 1), ('移动存储设备管控', '全部敏感数据', 'USB 外设', 'block', '全体终端', 1), ('办公文档水印保护', '内部文件', '屏幕显示、打印输出', 'watermark', '全体终端', 1), ('离职人员重点防护', '全部敏感数据', '所有通道', 'block', '人力资源部', 0), ('外部合作文件审批', '商业机密', '电子邮件、浏览器上传', 'approval', '市场营销部', 1)]
        for i, (name, rule, channel, action, scope, enabled) in enumerate(policy_specs):
            put(c, 'policies', {'id': f'POL-{i+1:03d}', 'name': name, 'rule': rule, 'channels': channel, 'action': action, 'scope': scope, 'enabled': bool(enabled), 'priority': i+1, 'updated': now(), 'description': '依据敏感内容识别结果，对指定终端和外发通道实施数据保护。'})
        for i, (name, method, level, desc) in enumerate([('个人信息', '正则表达式', 'high', '身份证号码、手机号码、银行卡号等个人身份信息'), ('源代码', '文件特征', 'high', '源代码文件、代码仓库压缩包与技术工程文件'), ('财务数据', '关键词匹配', 'high', '薪酬、财务、预算、账户、报价等财务信息'), ('商业机密', '关键词匹配', 'high', '机密、保密、未公开、战略与核心技术内容'), ('内部文件', '关键词匹配', 'medium', '内部使用、禁止外传与企业内部业务文件'), ('合同文档', '关键词匹配', 'medium', '合同、协议与供应商合作文档')]):
            put(c, 'rules', {'id': f'CLS-{i+1:03d}', 'name': name, 'method': method, 'level': level, 'description': desc, 'enabled': True, 'keywords': ['手机号,身份证,客户','源代码,代码仓库','薪酬,财务,预算,账户,报价','机密,保密,未公开,战略','内部使用,禁止外传','合同,协议,供应商'][i]})
        for i in range(72):
            ep = items(c, 'endpoints')[i%128]
            put(c, 'assets', {'id': f'AST-{i+1:04d}', 'name': files[i%12], 'type': ['个人信息','源代码','财务数据','商业机密','合同文档','财务数据'][i%6], 'level': 'high' if i%3!=2 else 'medium', 'endpoint': ep['name'], 'department': ep['department'], 'owner': ep['user'], 'path': f'C:\\Users\\{ep["user"]}\\Documents\\{files[i%12]}', 'matches': 12+i*3, 'size': f'{1.2+i%9*.7:.1f} MB', 'time': now()})
        for i in range(9):
            put(c, 'approvals', {'id': f'AP-{i+1:04d}', 'user': names[i], 'department': departments[i%6], 'file': files[i%12], 'channel': channels[i%4], 'recipient': f'partner{i+1}@example.com', 'reason': ['客户项目交付，需发送已脱敏的合作资料。','供应商对接，需要共享评审后的产品方案。','季度审计材料提交，请审批外发。'][i%3], 'status': 'pending' if i<5 else ('approved' if i<7 else 'rejected'), 'time': now(), 'comment': ''})
        put(c, 'scans', {'id': 'SCAN-001', 'name': '全网敏感数据例行扫描', 'scope': '全体终端', 'status': 'completed', 'progress': 100, 'found': 72, 'started': now(), 'createdAt': time.time()-3600})
        c.execute('INSERT INTO settings VALUES(1,?)', (json.dumps({'company': '星云科技有限公司', 'retention': 180, 'notification': True, 'email': 'security@example.com', 'watermark': '内部资料 · {姓名} · {时间}', 'autoUpdate': True, 'offlineProtection': True}, ensure_ascii=False),))
        audit(c, '系统初始化', '演示环境', '已载入终端、事件、策略和敏感数据演示记录')


class Handler(BaseHTTPRequestHandler):
    server_version = 'SentinelDLP/1.0'

    def log_message(self, fmt, *args):
        # Never log request bodies or passwords.
        super().log_message(fmt, *args)

    def send(self, data, status=200, content_type='application/json; charset=utf-8', headers=None):
        body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict,list)) else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store' if self.path.startswith('/api') else 'no-cache')
        for k,v in (headers or {}).items():
            self.send_header(k,v)
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self, c):
        match = re.search(r'(?:^|;\s*)dlp_session=([a-f0-9]{64})(?:;|$)', self.headers.get('Cookie',''))
        return match and c.execute('SELECT 1 FROM sessions WHERE token=? AND expires>?', (hashlib.sha256(match[1].encode()).hexdigest(),time.time())).fetchone()

    def done(self, c, data, headers=None):
        # Commit before replying: a browser can issue its next request immediately.
        c.commit()
        return self.send(data, headers=headers)

    def do_GET(self):
        try:
            url = urlparse(self.path)
            path = url.path
            if path == '/health':
                return self.send({'status':'ok','product':'Sentinel DLP','mode':'prototype'})
            if path.startswith('/api/'):
                with connect() as c:
                    if not self.authenticated(c):
                        return self.send({'error':'请先登录'},401)
                    image_match=re.fullmatch(r'/api/watermark-image/(WIMG-[A-F0-9]{12})',path)
                    if image_match:
                        row=c.execute('SELECT * FROM watermark_images WHERE id=?',(image_match[1],)).fetchone()
                        if not row:
                            return self.send({'error':'图片不存在或已删除'},404)
                        query=parse_qs(url.query)
                        if query.get('thumb')==['1']:
                            return self.send(bytes(row['thumbnail']),content_type='image/jpeg')
                        if query.get('download')==['1']:
                            ext={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}[row['mime']]
                            audit(c,'下载水印原图',row['id']);c.commit()
                            return self.send(bytes(row['original']),content_type=row['mime'],headers={'Content-Disposition':f'attachment; filename="{row["id"]}.{ext}"'})
                        return self.send(bytes(row['original']),content_type=row['mime'])
                    if path == '/api/bootstrap':
                        data = {kind:items(c,kind) for kind in COLLECTIONS}
                        for task in data['scans']:
                            if task['status']=='running':
                                task['progress']=min(100,int((time.time()-task['createdAt'])*5))
                                if task['progress']>=100:
                                    task.update(status='completed',found=sum(1 for a in data['assets'] if task['scope']=='全体终端' or a['department']==task['scope']))
                                put(c,'scans',task)
                        data['audit']=[dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 500')]
                        data['settings']=json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
                        data['user']={'name':'安全管理员','username':'admin','role':'超级管理员'}
                        data['serverTime']=now()
                        data['imageCapabilities']=watermark_images.capabilities()
                        return self.done(c,data)
                    if path == '/api/export':
                        kind=parse_qs(url.query).get('kind',['events'])[0]
                        if kind not in COLLECTIONS | {'audit'}:
                            return self.send({'error':'不支持的导出类型'},400)
                        rows=[dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC')] if kind=='audit' else items(c,kind)
                        stream=io.StringIO(); stream.write('\ufeff')
                        if rows:
                            writer=csv.DictWriter(stream, fieldnames=list(rows[0]),extrasaction='ignore'); writer.writeheader()
                            for row in rows:
                                writer.writerow({k: ('\''+str(v) if str(v).startswith(('=','+','-','@')) else v) for k,v in row.items()})
                        audit(c,'导出数据',kind,f'导出 {len(rows)} 条记录')
                        c.commit()
                        return self.send(stream.getvalue().encode(), content_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="sentinel-{kind}.csv"'})
                    return self.send({'error':'接口不存在'},404)
            candidate=(ROOT/'static'/path.lstrip('/')).resolve()
            if not candidate.is_relative_to((ROOT/'static').resolve()):
                return self.send({'error':'禁止访问'},403)
            if path=='/' or (not candidate.is_file() and '.' not in path.rsplit('/',1)[-1]):
                candidate=ROOT/'static'/'index.html'
            if not candidate.is_file():
                return self.send({'error':'文件不存在'},404)
            ct=mimetypes.guess_type(str(candidate))[0] or 'application/octet-stream'
            self.send(candidate.read_bytes(),content_type=ct+('; charset=utf-8' if ct.startswith('text/') or 'javascript' in ct else ''))
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception as e:
            self.log_error('%s',type(e).__name__)
            self.send({'error':'服务器处理失败'},500)

    def do_POST(self):
        try:
            if self.headers.get('X-DLP-Request')!='1':
                return self.send({'error':'无效请求来源'},403)
            path=urlparse(self.path).path
            length=int(self.headers.get('Content-Length','0'))
            if length<0 or length>(watermark_images.MAX_BODY if path=='/api/watermark-images/import' else 128000):
                return self.send({'error':'请求体过大'},413)
            payload=json.loads(self.rfile.read(length) or b'{}')
            path=urlparse(self.path).path
            with connect() as c:
                if path=='/api/login':
                    key=self.client_address[0]
                    attempts=self.server.login_attempts.get(key,[])
                    attempts=[t for t in attempts if time.time()-t<60]
                    if len(attempts)>=10:
                        return self.send({'error':'登录尝试过于频繁，请一分钟后重试'},429)
                    row=c.execute('SELECT * FROM users WHERE name=?',(payload.get('username',''),)).fetchone()
                    digest=hashlib.pbkdf2_hmac('sha256',str(payload.get('password','')).encode(),row['salt'].encode() if row else b'unknown',200000).hex()
                    if not row or not hmac.compare_digest(digest,row['hash']):
                        self.server.login_attempts[key]=attempts+[time.time()]
                        return self.send({'error':'账号或密码错误'},401)
                    token=secrets.token_hex(32)
                    c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
                    c.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),time.time()+43200))
                    audit(c,'登录系统','管理控制台')
                    return self.done(c,{'ok':True},headers={'Set-Cookie':f'dlp_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'})
                if not self.authenticated(c):
                    return self.send({'error':'请先登录'},401)
                if path=='/api/logout':
                    cookie=re.search(r'dlp_session=([a-f0-9]{64})',self.headers.get('Cookie',''))
                    if cookie: c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(cookie[1].encode()).hexdigest(),))
                    return self.done(c,{'ok':True},headers={'Set-Cookie':'dlp_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict'})
                if path=='/api/watermark-images/import':
                    try:
                        result=watermark_images.import_image(c,payload,put,audit,now)
                    except ValueError as exc:
                        return self.send({'error':str(exc)},400)
                    return self.done(c,{'ok':True,**result})
                if path in {'/api/watermark-images/save','/api/watermark-images/ocr','/api/watermark-images/delete'}:
                    ident=payload.get('id','')
                    row=c.execute("SELECT data FROM records WHERE kind='watermarkImages' AND id=?",(ident,)).fetchone()
                    if not row:
                        return self.send({'error':'水印图片记录不存在'},404)
                    item=json.loads(row['data'])
                    if path.endswith('/delete'):
                        c.execute('DELETE FROM watermark_images WHERE id=?',(ident,))
                        c.execute("DELETE FROM records WHERE kind='watermarkImages' AND id=?",(ident,))
                        audit(c,'删除水印图片',item['filename'],ident)
                        return self.done(c,{'ok':True})
                    if path.endswith('/ocr'):
                        blob=c.execute('SELECT original FROM watermark_images WHERE id=?',(ident,)).fetchone()
                        if not blob:
                            return self.send({'error':'图片已删除'},404)
                        try:
                            text=watermark_images.extract_text(bytes(blob[0]))
                        except ValueError as exc:
                            return self.send({'error':str(exc)},400)
                        c.execute('BEGIN IMMEDIATE')
                        latest=c.execute("SELECT data FROM records WHERE kind='watermarkImages' AND id=?",(ident,)).fetchone()
                        if not latest:
                            return self.send({'error':'图片已删除，识别结果未保存'},404)
                        item=json.loads(latest['data'])
                        item.update(ocrText=text,ocrState='completed' if text else 'empty',ocrTime=now())
                        hints=watermark_images.suggestions(text,items(c,'endpoints'),items(c,'watermarks'))
                        put(c,'watermarkImages',item);audit(c,'识别水印图片文字',item['filename'],f'识别到 {len(text)} 个字符；结果待人工核验')
                        return self.done(c,{'ok':True,'item':item,'suggestions':hints})
                    try:
                        metadata=watermark_images.validate_metadata(payload.get('metadata',{}))
                    except ValueError as exc:
                        return self.send({'error':str(exc)},400)
                    if metadata['policyId'] and not c.execute("SELECT 1 FROM records WHERE kind='watermarks' AND id=?",(metadata['policyId'],)).fetchone():
                        return self.send({'error':'关联水印策略不存在，请重新选择'},400)
                    item.update(metadata,updated=now())
                    put(c,'watermarkImages',item);audit(c,'保存水印图片信息',item['title'],ident)
                    return self.done(c,{'ok':True,'item':item})
                if path=='/api/save':
                    kind=payload.get('kind'); item=payload.get('item',{})
                    if kind=='watermarks':
                        try:
                            item=validate_watermark(item)
                        except (ValueError, OverflowError) as exc:
                            return self.send({'error':str(exc)},400)
                        item['id']=item.get('id') or 'WM-'+secrets.token_hex(4).upper()
                        item['updated']=now()
                        put(c,kind,item); audit(c,'保存水印策略',item['name'],item['type'])
                        return self.done(c,{'ok':True,'item':item})
                    if kind not in {'policies','rules'} or not str(item.get('name','')).strip():
                        return self.send({'error':'请填写有效的名称和类型'},400)
                    if len(item['name'])>80:
                        return self.send({'error':'名称不能超过80个字符'},400)
                    item['id']=item.get('id') or f'{"POL" if kind=="policies" else "CLS"}-{secrets.token_hex(3).upper()}'
                    item['updated']=now()
                    item['enabled']=bool(item.get('enabled',True))
                    put(c,kind,item); audit(c,'保存配置',item['name'],kind)
                    return self.done(c,{'ok':True,'item':item})
                if path=='/api/update':
                    kind=payload.get('kind'); ids=payload.get('ids',[]); changes=payload.get('changes',{})
                    allowed={'events':{'status','note'},'endpoints':{'isolated','policy'},'policies':{'enabled'},'rules':{'enabled'},'approvals':{'status','comment'},'watermarks':{'enabled'}}
                    if kind not in allowed or not set(changes)<=allowed[kind] or not isinstance(ids,list):
                        return self.send({'error':'无效更新'},400)
                    if kind=='events' and 'status' in changes and changes['status'] not in {'pending','processing','resolved'}:
                        return self.send({'error':'无效事件状态'},400)
                    if kind=='approvals' and changes.get('status') not in {'approved','rejected'}:
                        return self.send({'error':'无效审批结果'},400)
                    if kind=='watermarks' and ('enabled' not in changes or not isinstance(changes['enabled'],bool)):
                        return self.send({'error':'水印启停状态必须为布尔值'},400)
                    count=0
                    for ident in ids:
                        row=c.execute('SELECT data FROM records WHERE kind=? AND id=?',(kind,ident)).fetchone()
                        if not row: continue
                        item=json.loads(row['data'])
                        if kind=='approvals' and item['status']!='pending': continue
                        item.update(changes); count+=1
                        if kind=='watermarks':
                            item['updated']=now()
                        put(c,kind,item)
                        audit(c,{'events':'处置事件','endpoints':'终端管控','policies':'切换策略','rules':'切换规则','approvals':'审批外发','watermarks':'切换水印策略'}[kind],ident,json.dumps(changes,ensure_ascii=False))
                    return self.done(c,{'ok':True,'count':count})
                if path=='/api/delete':
                    kind=payload.get('kind')
                    if kind not in {'policies','rules','watermarks'}: return self.send({'error':'不支持删除'},400)
                    c.execute('DELETE FROM records WHERE kind=? AND id=?',(kind,payload.get('id')))
                    audit(c,'删除配置',payload.get('id',''),kind)
                    return self.done(c,{'ok':True})
                if path=='/api/scan':
                    scope=payload.get('scope','全体终端')
                    if scope not in ['全体终端','研发中心','市场营销部','财务部','人力资源部','产品设计部','行政管理部']:
                        return self.send({'error':'无效扫描范围'},400)
                    running=next((x for x in items(c,'scans') if x['status']=='running' and time.time()-x['createdAt']<20),None)
                    if running: return self.send({'error':'已有扫描任务正在执行'},409)
                    task={'id':'SCAN-'+secrets.token_hex(3).upper(),'name':str(payload.get('name','敏感数据发现任务'))[:80],'scope':scope,'status':'running','progress':0,'found':0,'started':now(),'createdAt':time.time()}
                    put(c,'scans',task); audit(c,'创建扫描任务',task['name'],scope)
                    return self.done(c,{'ok':True,'item':task})
                if path=='/api/detect':
                    content=str(payload.get('content',''))[:30000]
                    hits=[]
                    for r in items(c,'rules'):
                        if not r.get('enabled'): continue
                        words=[w.strip() for w in r.get('keywords','').replace('，',',').split(',') if w.strip()]
                        matched=[{'value':w,'count':len(re.findall(re.escape(w),content,re.I))} for w in words if re.search(re.escape(w),content,re.I)]
                        if r['name']=='个人信息':
                            for label,pattern in [('手机号码',r'(?<!\d)1[3-9]\d{9}(?!\d)'),('身份证号',r'(?<!\d)\d{17}[\dXx](?!\d)')]:
                                results=re.findall(pattern,content)
                                if results: matched.append({'value':label,'count':len(results)})
                        if matched: hits.append({'rule':r['name'],'level':r['level'],'matches':matched,'count':sum(m['count'] for m in matched)})
                    audit(c,'规则检测测试','内容识别引擎',f'命中 {len(hits)} 类规则')
                    return self.done(c,{'ok':True,'hits':hits,'mode':'demo'})
                if path=='/api/settings':
                    old=json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
                    for k in old:
                        if k in payload: old[k]=payload[k]
                    if not str(old['company']).strip() or not 7<=int(old['retention'])<=3650:
                        return self.send({'error':'请填写企业名称，日志保留天数需在7–3650天之间'},400)
                    c.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(old,ensure_ascii=False),)); audit(c,'更新系统设置','系统配置')
                    return self.done(c,{'ok':True})
                if path=='/api/report':
                    period=payload.get('period','最近7天')
                    days={'最近7天':7,'最近30天':30,'全部数据':36500}.get(period,7)
                    cutoff=(datetime.now(TZ)-timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
                    events=[e for e in items(c,'events') if e['time']>=cutoff]
                    report={'id':'RPT-'+secrets.token_hex(3).upper(),'name':str(payload.get('name','数据安全运营报告'))[:80],'period':period,'time':now(),'status':'completed','events':len(events),'endpoints':len(items(c,'endpoints')),'blocked':sum(e['action']=='blocked' for e in events),'high':sum(e['severity']=='high' for e in events),'pending':sum(e['status']=='pending' for e in events),'assets':len(items(c,'assets'))}
                    put(c,'reports',report); audit(c,'生成报告',report['name'])
                    return self.done(c,{'ok':True,'item':report})
                return self.send({'error':'接口不存在'},404)
        except (ValueError,TypeError,KeyError,json.JSONDecodeError):
            self.send({'error':'请求参数不正确'},400)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception as e:
            self.log_error('%s',type(e).__name__); self.send({'error':'服务器处理失败'},500)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8091)
    args=parser.parse_args(); seed()
    server=ThreadingHTTPServer((args.host,args.port),Handler); server.login_attempts={}
    print(f'Sentinel DLP listening on {args.host}:{args.port}',flush=True)
    server.serve_forever()
