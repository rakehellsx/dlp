#!/usr/bin/env python3
"""生成业务 JSON，或将其事务导入已初始化的 PostgreSQL（Windows / Linux）。"""
import argparse
import base64
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
KINDS = {'endpoints', 'events', 'assets', 'policies', 'rules', 'approvals', 'scans',
         'reports', 'watermarks', 'watermarkImages'}
EP_FIELDS = {'id': 'endpoint_code', 'name': 'name', 'user': 'username',
             'department': 'department', 'ip': 'ip_address', 'os': 'os',
             'status': 'status', 'risk': 'risk', 'version': 'agent_version',
             'policy': 'policy', 'lastSeen': 'last_seen', 'isolated': 'isolated'}
TZ = timezone(timedelta(hours=8))


def stamp():
    return datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')


def image_module():
    spec = importlib.util.spec_from_file_location('dlp_image_processor', ROOT/'dlpcenter/tools/image_processor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate(args):
    if not re.fullmatch(r'[A-Z0-9-]{1,24}', args.prefix):
        raise ValueError('prefix 仅允许 1–24 位大写字母、数字和连字符')
    if not 1 <= args.endpoints <= 10000 or any(not 0 <= n <= 100000 for n in [args.events, args.assets, args.approvals]) or not 0 <= args.images <= 200:
        raise ValueError('终端数需为1–10000，事件/资产/审批数0–100000，图片数0–200')
    output = args.output.resolve()
    if output.exists():
        raise ValueError('输出文件已存在，请更换路径；不会覆盖原 JSON')
    output.parent.mkdir(parents=True, exist_ok=True)
    fixture = json.loads((ROOT/'dlpcenter/sql/demo.json').read_text(encoding='utf-8'))
    templates = defaultdict(list)
    for row in fixture['records']:
        templates[row['kind']].append(row['data'])
    rng = random.Random(args.seed)
    rows = []
    groups = defaultdict(list)
    current = datetime.now(TZ)
    now = stamp()

    def add(kind, data, **extra):
        rows.append({'kind': kind, 'data': data, **extra})
        groups[kind].append(data)
        return data

    def ident(tag, index):
        return f'{tag}-{args.prefix}-{index:04d}'

    for kind, tag in [('rules', 'CLS'), ('policies', 'POL'), ('watermarks', 'WM')]:
        for i, template in enumerate(templates[kind], 1):
            item = deepcopy(template)
            item['id'] = ident(tag, i)
            if 'updated' in item:
                item['updated'] = now
            add(kind, item)
    for i in range(args.endpoints):
        item = deepcopy(templates['endpoints'][i % len(templates['endpoints'])])
        item.update(id=ident('EP', i+1), endpointUid=str(uuid.uuid4()),
                    name=f'{args.prefix}-PC-{i+1:04d}', ip=f'10.200.{i//250}.{i%250+1}',
                    lastSeen=now, isolated=False)
        add('endpoints', item)
    for kind, count, tag in [('events', args.events, 'DLP'), ('assets', args.assets, 'AST'), ('approvals', args.approvals, 'AP')]:
        for i in range(count):
            ep = groups['endpoints'][i % args.endpoints]
            item = deepcopy(rng.choice(templates[kind]))
            item.update(id=ident(tag, i+1), endpointUid=ep['endpointUid'],
                        endpoint=ep['name'], department=ep['department'],
                        time=(current-timedelta(minutes=i*13+1)).strftime('%Y-%m-%d %H:%M:%S'))
            if kind != 'assets':
                item['user'] = ep['user']
            else:
                item['owner'] = ep['user']
                item['path'] = f'C:\\Users\\{ep["user"]}\\Documents\\{item["name"]}'
            if kind == 'events':
                item.update(endpointId=ep['id'], ip=ep['ip'])
            add(kind, item)
    add('scans', {'id': ident('SCAN', 1), 'name': '敏感数据盘点', 'scope': '全体终端',
                  'status': 'completed', 'progress': 100, 'found': args.assets,
                  'started': now, 'createdAt': int(current.timestamp())})
    add('reports', {'id': ident('RPT', 1), 'name': '数据安全运营报告', 'period': '全部数据',
                    'time': now, 'status': 'completed', 'events': args.events,
                    'blocked': sum(e['action']=='blocked' for e in groups['events']),
                    'high': sum(e['severity']=='high' for e in groups['events']),
                    'pending': sum(e['status']=='pending' for e in groups['events']),
                    'endpoints': args.endpoints, 'assets': args.assets})
    if args.images:
        from PIL import Image, ImageDraw, ImageFont
        folder = output.parent/(output.stem+'-files')
        folder.mkdir(exist_ok=True)
        for i in range(args.images):
            ep = groups['endpoints'][i % args.endpoints]
            policy = groups['watermarks'][i % len(groups['watermarks'])]
            code = f'WM-{args.prefix}-{i+1:04d}'
            lines = ['SYNTHETIC WATERMARK TEST IMAGE', code, ep['name'], ep['ip'], now, policy['id']]
            image = Image.new('RGB', (1400, 800), 'white')
            draw = ImageDraw.Draw(image)
            # Pillow 自带字体，Windows/Linux 无需额外安装字体。
            try:
                font = ImageFont.load_default(size=30)
            except TypeError:  # Pillow 10.0 仍可生成图片。
                font = ImageFont.load_default()
            for line_index, line in enumerate(lines):
                draw.text((50, 65+line_index*105), line, fill='#243b35', font=font)
            filename = f'{args.prefix}-{i+1:04d}.png'
            path = folder/filename
            with path.open('xb') as f:
                image.save(f, format='PNG')
            # 标题和待核验元数据随 JSON 传入，水印字段可再通过 --ocr 提取。
            add('watermarkImages', {'id': 'WIMG-'+uuid.uuid4().hex[:12].upper(),
                'title': f'水印测试图片 {i+1}', 'type': policy['type'], 'status': 'pending',
                'code': '', 'user': '', 'department': '', 'endpoint': '', 'endpointUid': '',
                'ip': '', 'time': '', 'policyId': '', 'content': '',
                'note': '合成测试图片，关联字段待识别和核验'}, sourceFile=path.relative_to(output.parent).as_posix())
    departments = ['研发中心', '市场营销部', '财务部', '人力资源部', '产品设计部', '行政管理部']
    channels = [('im','即时通讯','message'), ('usb','USB 外设','usb'), ('web','浏览器上传','globe'),
                ('mail','电子邮件','mail'), ('print','打印输出','printer'), ('clipboard','剪贴板','clipboard')]
    bundle = {'schemaVersion': 1, 'generatedAt': now, 'records': rows,
              'settings': fixture['settings'],
              'catalogs': [{'category': 'department', 'key': key, 'label': label, 'position': i+1, 'config': {}}
                           for i, (key, label) in enumerate(zip(['rd','marketing','finance','hr','design','admin'], departments))] +
                          [{'category': 'channel', 'key': key, 'label': label, 'position': i+1, 'config': {'icon': icon}}
                           for i, (key,label,icon) in enumerate(channels)]}
    output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('已生成：'+str(output))
    print(json.dumps(dict(Counter(row['kind'] for row in rows)), ensure_ascii=False))
    return output


def validate(bundle):
    if not isinstance(bundle, dict) or bundle.get('schemaVersion') != 1 or not isinstance(bundle.get('records'), list):
        raise ValueError('需要 schemaVersion=1 及 records 数组')
    if len(bundle['records']) > 320000:
        raise ValueError('单文件记录数过多')
    seen = set()
    fixture = json.loads((ROOT/'dlpcenter/sql/demo.json').read_text(encoding='utf-8'))
    examples = {r['kind']: r['data'] for r in fixture['records']}
    examples['reports'] = {'id': '', 'name': '', 'period': '', 'time': '', 'status': '',
                           'events': 0, 'blocked': 0, 'high': 0, 'pending': 0, 'endpoints': 0, 'assets': 0}
    examples['watermarkImages'] = {'id': '', 'title': '', 'type': '', 'status': ''}
    for row in bundle['records']:
        if not isinstance(row, dict) or row.get('kind') not in KINDS or not isinstance(row.get('data'), dict):
            raise ValueError('记录须为 {kind,data}，且 kind 为支持的业务类型')
        kind, item = row['kind'], row['data']
        for key, sample in examples[kind].items():
            if key not in item or (key == 'createdAt' and type(item[key]) not in (float, int)) or (key != 'createdAt' and type(item[key]) is not type(sample)):
                raise ValueError(f'{kind}.{key} 缺失或类型错误')
        ident = item['id']
        if not ident or len(ident)>100 or (kind, ident) in seen:
            raise ValueError('记录编号为空、过长或重复：'+str(ident))
        seen.add((kind, ident))
        # 纯 JSON 扩展属性允许保留，但字符串不能包含 PostgreSQL 不支持的 NUL。
        if '\\u0000' in json.dumps(item):
            raise ValueError('记录包含空字符：'+ident)
        uid = item.get('endpointUid')
        if kind == 'endpoints' and not uid:
            raise ValueError('终端必须提供 endpointUid：'+ident)
        if uid:
            if not isinstance(uid, str) or str(uuid.UUID(uid)) != uid:
                raise ValueError('endpointUid 必须是标准小写 UUID：'+ident)
        for key in ['time', 'lastSeen', 'started', 'updated']:
            if item.get(key):
                datetime.strptime(item[key], '%Y-%m-%d %H:%M:%S')
        for key in ['matches','events','blocked','high','pending','endpoints','assets','found']:
            if key in item and (type(item[key]) is not int or item[key]<0):
                raise ValueError(f'{kind}.{key} 必须为非负整数')
        options = {'endpoints': {'status': {'online','offline'}, 'risk': {'low','medium','high'}},
                   'events': {'severity': {'low','medium','high'}, 'status': {'pending','processing','resolved'}, 'action': {'blocked','audited'}},
                   'assets': {'level': {'low','medium','high'}},
                   'rules': {'level': {'low','medium','high'}},
                   'policies': {'action': {'block','audit','approval','watermark'}},
                   'approvals': {'status': {'pending','approved','rejected'}},
                   'scans': {'status': {'running','completed'}}, 'reports': {'status': {'completed'}},
                   'watermarkImages': {'type': {'print','screen','screenshot','unknown'}, 'status': {'pending','reviewed'}}}
        for key, allowed in options.get(kind, {}).items():
            if item[key] not in allowed:
                raise ValueError(f'{kind}.{key} 选项无效：{item[key]}')
        if kind == 'scans' and (type(item['progress']) is not int or not 0<=item['progress']<=100):
            raise ValueError('扫描 progress 必须为0–100整数')
        if kind == 'watermarkImages' and not re.fullmatch(r'WIMG-[A-F0-9]{12}', ident):
            raise ValueError('图片 id 必须为 WIMG- 加12位大写十六进制')
        if kind == 'watermarks':
            choices = {'type': {'print','screen','screenshot'}, 'condition': {'always','sensitive','apps'},
                       'fontFamily': {'Microsoft YaHei','SimSun','Arial'}, 'position': {'tile','center','top','bottom'},
                       'paperSize': {'A3','A4'}, 'screenTarget': {'all','primary'}}
            for key, values in choices.items():
                if item[key] not in values:
                    raise ValueError('水印选项无效：'+key)
            for key, low, high in [('fontSize',12,48),('opacity',5,80),('angle',-90,90),('spacing',100,360),('priority',1,999)]:
                if type(item[key]) is not int or not low<=item[key]<=high:
                    raise ValueError('水印参数超出范围：'+key)
            for key, values in [('apps',{'Office 文档','PDF 阅读器','浏览器','即时通讯','其他应用'}),('screenshotMethods',{'system','tools','clipboard'})]:
                if len(item[key])>5 or any(not isinstance(v,str) or v not in values for v in item[key]):
                    raise ValueError('水印数组选项无效：'+key)
            if not re.fullmatch(r'WM-[A-Z0-9-]{1,60}',ident) or not re.fullmatch(r'#[a-fA-F0-9]{6}',item['color']):
                raise ValueError('水印编号或颜色格式无效')
            if not item['name'].strip() or len(item['name'])>80 or not item['content'].strip() or len(item['content'])>240 or item['content'].count('\n')>3:
                raise ValueError('水印名称或内容无效')
            if any(t not in {'企业名称','姓名','账号','部门','终端','终端IP','时间','文档名称'} for t in re.findall(r'\{([^{}]+)\}',item['content'])):
                raise ValueError('水印动态字段无效')
            if (item['condition']=='apps' and not item['apps']) or (item['type']=='screenshot' and not item['screenshotMethods']):
                raise ValueError('适用应用或截屏方式不能为空')
    if 'settings' in bundle and not isinstance(bundle['settings'], dict):
        raise ValueError('settings 须为对象')
    if 'catalogs' in bundle and (not isinstance(bundle['catalogs'], list) or any(not isinstance(x,dict) or not all(isinstance(x.get(k), str) and x[k] for k in ['category','key','label']) or type(x.get('position')) is not int or not isinstance(x.get('config'),dict) for x in bundle['catalogs'])):
        raise ValueError('catalogs 字典字段缺失或类型错误')


def prepare_images(bundle, source, ocr):
    prepared = {}
    total_bytes = 0
    helper = image_module() if any(r['kind']=='watermarkImages' for r in bundle['records']) else None
    for row in bundle['records']:
        if row['kind'] != 'watermarkImages':
            continue
        relative = row.get('sourceFile')
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError('图片记录须提供 sourceFile 相对路径')
        path = (source.parent/relative).resolve()
        if not path.is_relative_to(source.parent.resolve()):
            raise ValueError('图片 sourceFile 不得超出 JSON 所在目录')
        if path.stat().st_size>helper.MAX_FILE:
            raise ValueError('图片不能超过10 MB')
        total_bytes += path.stat().st_size
        if len(prepared)>=200 or total_bytes>300*1024*1024:
            raise ValueError('单批图片不能超过200张或300 MB')
        raw, thumb, info = helper.parse_file({'filename': path.name, 'data': base64.b64encode(path.read_bytes()).decode()})
        meta = helper.validate_metadata(row['data'])
        meta['endpointUid'] = row['data'].get('endpointUid', '')
        text = helper.extract_text(raw) if ocr else ''
        prepared[row['data']['id']] = (raw, thumb, info, meta, text)
    return prepared


def import_bundle(args, source):
    # 仅导入数据库时加载 psycopg2；纯 JSON 生成不依赖数据库组件。
    from psycopg2.extras import Json
    from pg_common import connect, file_root
    from migrate_image_files import write
    bundle = json.loads(source.read_text(encoding='utf-8-sig'))
    validate(bundle)
    prepared = prepare_images(bundle, source, args.ocr)
    counts = Counter()
    root = file_root()
    with connect() as db:
        with db.cursor() as c:
            c.execute("SET LOCAL statement_timeout='30s'")
            c.execute("SET LOCAL lock_timeout='10s'")
            c.execute('SELECT pg_advisory_xact_lock(728112)')
            c.execute('SELECT pg_advisory_xact_lock(728114)')
            c.execute("SELECT 1 FROM dlp_migrations WHERE name='endpoints-uuid-v1'")
            if not c.fetchone():
                raise ValueError('请先运行 init_postgres.py 或 migrate_endpoints.py 完成终端表迁移')
            ordered = sorted(bundle['records'], key=lambda r: 0 if r['kind']=='endpoints' else 2 if r['kind']=='watermarkImages' else 1)
            for row in ordered:
                kind, item = row['kind'], deepcopy(row['data'])
                ident = item['id']
                if kind == 'endpoints':
                    c.execute('SELECT endpoint_uid::text FROM endpoints WHERE endpoint_code=%s', (ident,))
                    found = c.fetchone()
                    if found and found[0] != item['endpointUid']:
                        raise ValueError('终端编号已存在且 UUID 不同，拒绝改绑：'+ident)
                else:
                    c.execute('SELECT 1 FROM dlp_records WHERE kind=%s AND id=%s', (kind, ident))
                    found = c.fetchone()
                if found:
                    if args.on_conflict == 'skip':
                        counts['skipped'] += 1
                        continue
                    raise ValueError(f'记录已存在：{kind}/{ident}；可使用 --on-conflict skip 跳过')
                uid = item.get('endpointUid')
                if uid and kind != 'endpoints':
                    c.execute('SELECT 1 FROM endpoints WHERE endpoint_uid=%s', (uid,))
                    if not c.fetchone():
                        raise ValueError('关联终端 UUID 不存在：'+ident)
                if kind == 'endpoints':
                    fields = list(EP_FIELDS)
                    columns = ','.join(EP_FIELDS[k] for k in fields)
                    extra = {k:v for k,v in item.items() if k not in EP_FIELDS and k!='endpointUid'}
                    c.execute(f'INSERT INTO endpoints(endpoint_uid,{columns},extra) VALUES({",".join(["%s"]*(len(fields)+2))})',
                              [item['endpointUid'], *(item[k] for k in fields), Json(extra)])
                elif kind == 'watermarkImages':
                    raw, thumb, info, meta, text = prepared[ident]
                    c.execute('SELECT 1 FROM dlp_watermark_images WHERE hash=%s', (info['hash'],))
                    if c.fetchone():
                        if args.on_conflict=='skip':
                            counts['skipped'] += 1
                            continue
                        raise ValueError('图片内容已存在：'+ident)
                    policy_id = meta['policyId']
                    if policy_id:
                        c.execute("SELECT 1 FROM dlp_records WHERE kind='watermarks' AND id=%s", (policy_id,))
                        if not c.fetchone():
                            raise ValueError('关联水印策略不存在：'+ident)
                    c.execute('SELECT count(*),coalesce(sum(size),0) FROM dlp_watermark_images')
                    n, size = c.fetchone()
                    if n>=200 or size+len(raw)>300*1024*1024:
                        raise ValueError('水印图片超出200张或300 MB存储限制')
                    hints = image_module().suggestions(text, [], []) if args.ocr else {}
                    if args.ocr:
                        c.execute("SELECT data FROM endpoint_records WHERE (%s<>'' AND data->>'ip'=%s) OR (data->>'name'<>'' AND strpos(lower(%s),lower(data->>'name'))>0) ORDER BY seq LIMIT 2", (hints.get('ip',''),hints.get('ip',''),text))
                        devices = c.fetchall()
                        if len(devices)==1:
                            ep = devices[0][0]
                            hints.update({k:ep[k] for k in ['user','department','ip','endpointUid']})
                            hints['endpoint'] = ep['name']
                        c.execute("SELECT data FROM dlp_records WHERE kind='watermarks' AND (strpos(%s,data->>'id')>0 OR strpos(%s,data->>'name')>0) ORDER BY seq LIMIT 1", (text,text))
                        policy = c.fetchone()
                        if policy:
                            hints.update(policyId=policy[0]['id'], type=policy[0]['type'])
                    item = {**meta, **info, 'id': ident, 'actor': 'business_data.py', 'importedAt': stamp(),
                            'updated': stamp(), 'ocrText': text, 'ocrTime': stamp() if args.ocr else '',
                            'ocrState': ('completed' if text else 'empty') if args.ocr else 'not_run', 'ocrSuggestions': hints}
                    op, tp = info['hash']+'/original', info['hash']+'/thumbnail.jpg'
                    if not args.dry_run:
                        write(root, op, raw)
                        write(root, tp, thumb)
                    c.execute('INSERT INTO dlp_watermark_images(id,hash,mime,size,original_path,thumbnail_path) VALUES(%s,%s,%s,%s,%s,%s)',
                              (ident,info['hash'],info['mime'],len(raw),op,tp))
                    c.execute('INSERT INTO dlp_records(kind,id,data) VALUES(%s,%s,%s)', (kind,ident,Json(item)))
                else:
                    c.execute('INSERT INTO dlp_records(kind,id,data) VALUES(%s,%s,%s)', (kind,ident,Json(item)))
                counts[kind] += 1
            if args.apply_settings:
                settings = bundle.get('settings')
                if not settings or set(settings)!={'company','email','retention','offlineProtection','autoUpdate','notification','watermark'}:
                    raise ValueError('settings 须包含完整的7个系统设置字段')
                if not all(isinstance(settings[k],str) for k in ['company','email','watermark']) or not settings['company'].strip() or type(settings['retention']) is not int or not 7<=settings['retention']<=3650 or not all(type(settings[k]) is bool for k in ['offlineProtection','autoUpdate','notification']):
                    raise ValueError('系统设置字段类型或范围错误')
                if settings['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',settings['email']):
                    raise ValueError('系统设置 email 格式错误')
                c.execute('INSERT INTO dlp_settings(id,data) VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data', (Json(settings),))
                counts['settings'] += 1
            if args.apply_catalogs:
                for item in bundle.get('catalogs', []):
                    c.execute('INSERT INTO dlp_catalogs(category,key,label,position,config) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                              (item['category'],item['key'],item['label'],item['position'],Json(item['config'])))
                    counts['catalogs'] += c.rowcount
            c.execute('INSERT INTO operation_logs(operator_name,action,target,detail,success) VALUES(%s,%s,%s,%s,true)',
                      ('business_data.py','导入业务JSON',source.name,json.dumps(dict(counts),ensure_ascii=False)))
            if args.dry_run:
                db.rollback()
    print(('试运行完成，事务已回滚，未写图片文件：' if args.dry_run else '已提交数据库事务：')+json.dumps(dict(counts),ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    gen = sub.add_parser('generate', help='生成 JSON 及可选测试图片，默认不连接数据库')
    gen.add_argument('--output', type=Path, required=True)
    gen.add_argument('--prefix', default='SYN-'+datetime.now(TZ).strftime('%Y%m%d%H%M%S'))
    gen.add_argument('--endpoints', type=int, default=10)
    gen.add_argument('--events', type=int, default=30)
    gen.add_argument('--assets', type=int, default=20)
    gen.add_argument('--approvals', type=int, default=5)
    gen.add_argument('--images', type=int, default=0)
    gen.add_argument('--seed', type=int, default=42)
    gen.add_argument('--write', action='store_true', help='生成后立即导入数据库')
    imp = sub.add_parser('import', help='导入已生成或编辑的 JSON 文件')
    imp.add_argument('--input', type=Path, required=True)
    for command in [gen, imp]:
        command.add_argument('--dry-run', action='store_true', help='执行数据库校验后回滚，不写图片文件')
        command.add_argument('--on-conflict', choices=['error','skip'], default='error')
        command.add_argument('--apply-settings', action='store_true', help='显式覆盖系统设置')
        command.add_argument('--apply-catalogs', action='store_true', help='补充缺少的部门/通道字典，不覆盖既有字典')
        command.add_argument('--ocr', action='store_true', help='导入图片时识别文字并保存候选字段，仍须人工核验')
    args = parser.parse_args()
    try:
        if args.command=='generate':
            if not args.write and (args.dry_run or args.ocr or args.apply_settings or args.apply_catalogs):
                parser.error('生成后的数据库操作参数需同时传入 --write')
            source = generate(args)
            if args.write:
                import_bundle(args, source)
        else:
            import_bundle(args, args.input.resolve())
    except Exception as exc:
        # 数据库错误不回显连接串或记录内容；全部数据库写入均由上下文回滚。
        if exc.__class__.__module__.startswith('psycopg2'):
            print('导入失败：PostgreSQL 操作失败，事务已回滚（SQLSTATE '+str(getattr(exc,'pgcode',None))+'）；检查连接、约束及数据库日志。', file=sys.stderr)
        else:
            print('执行失败：'+str(exc), file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
