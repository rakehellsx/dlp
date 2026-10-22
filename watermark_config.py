"""Watermark policy validation and non-destructive prototype migration."""
import json
import re
from datetime import datetime, timedelta, timezone

TYPES = {'print', 'screen', 'screenshot'}
SCOPES = {'全体终端', '研发中心', '市场营销部', '财务部', '人力资源部', '产品设计部', '行政管理部'}
APPS = {'Office 文档', 'PDF 阅读器', '浏览器', '即时通讯', '其他应用'}
TOKENS = {'企业名称', '姓名', '账号', '部门', '终端', '终端IP', '时间', '文档名称'}


def validate(item):
    if not isinstance(item, dict):
        raise ValueError('无效的水印配置')
    name = str(item.get('name', '')).strip()
    content = str(item.get('content', '')).strip()
    if not name or len(name) > 80:
        raise ValueError('水印策略名称需为1–80个字符')
    if not content or len(content) > 240 or len(content.splitlines()) > 4:
        raise ValueError('水印内容不能为空，最多240个字符、4行文本')
    if set(re.findall(r'\{([^{}]+)\}', content)) - TOKENS:
        raise ValueError('水印内容包含不支持的动态字段')
    result = {'name': name, 'content': content}
    enums = {
        'type': (TYPES, 'screen'), 'scope': (SCOPES, '全体终端'),
        'condition': ({'always', 'sensitive', 'apps'}, 'always'),
        'fontFamily': ({'Microsoft YaHei', 'SimSun', 'Arial'}, 'Microsoft YaHei'),
        'position': ({'tile', 'center', 'top', 'bottom'}, 'tile'),
        'paperSize': ({'A4', 'A3'}, 'A4'),
        'screenTarget': ({'all', 'primary'}, 'all'),
    }
    for key, (allowed, default) in enums.items():
        value = item.get(key, default)
        if not isinstance(value, str) or value not in allowed:
            raise ValueError('水印类型、范围或显示选项无效')
        result[key] = value
    for key, default, low, high in [('fontSize', 20, 12, 48), ('opacity', 18, 5, 80),
                                    ('angle', -30, -90, 90), ('spacing', 180, 100, 360),
                                    ('priority', 10, 1, 999)]:
        value = item.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value) or not low <= value <= high:
            raise ValueError(f'{key} 的取值范围为 {low}–{high} 的整数')
        result[key] = int(value)
    color = item.get('color', '#66737f')
    if not isinstance(color, str) or not re.fullmatch(r'#[a-fA-F0-9]{6}', color):
        raise ValueError('请选择有效的水印颜色')
    result['color'] = color
    for key, default in [('enabled', True), ('bold', False), ('bothSides', True)]:
        value = item.get(key, default)
        if not isinstance(value, bool):
            raise ValueError('水印开关必须为布尔值')
        result[key] = value
    for key, allowed, default in [('apps', APPS, []), ('screenshotMethods', {'system', 'tools', 'clipboard'}, ['system', 'tools', 'clipboard'])]:
        value = item.get(key, default)
        if not isinstance(value, list) or len(value) > len(allowed) or any(not isinstance(v, str) or v not in allowed for v in value):
            raise ValueError('应用或截屏方式配置无效')
        result[key] = list(dict.fromkeys(value))
    if result['condition'] == 'apps' and not result['apps']:
        raise ValueError('请至少选择一个适用应用')
    if result['type'] == 'screenshot' and not result['screenshotMethods']:
        raise ValueError('请至少选择一种截屏方式')
    result['printers'] = str(item.get('printers', '全部打印机')).strip()
    if not result['printers'] or len(result['printers']) > 200:
        raise ValueError('请填写打印机范围，最多200个字符')
    result['description'] = str(item.get('description', ''))[:240]
    ident = item.get('id')
    if ident:
        if not isinstance(ident, str) or not re.fullmatch(r'WM-[A-Z0-9-]{1,60}', ident):
            raise ValueError('水印策略编号无效')
        result['id'] = ident
    return result


def migrate(c, put, audit):
    c.execute('CREATE TABLE IF NOT EXISTS migrations(name TEXT PRIMARY KEY)')
    if c.execute("SELECT 1 FROM migrations WHERE name='watermarks-v1'").fetchone():
        return
    specs = [
        ('WM-PRINT-001', '机密文档打印水印', 'print', '内部资料 · {姓名}\n{部门} · {时间}', True, '全体终端', 'sensitive'),
        ('WM-SCREEN-001', '办公屏幕可见水印', 'screen', '{企业名称}\n{姓名} · {终端IP}', True, '全体终端', 'always'),
        ('WM-CAPTURE-001', '研发资料截屏水印', 'screenshot', '仅限内部使用 · {姓名}\n{终端} · {时间}', False, '研发中心', 'sensitive'),
    ]
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    legacy = c.execute('SELECT data FROM settings WHERE id=1').fetchone()
    legacy_template = json.loads(legacy[0]).get('watermark', '') if legacy else ''
    for i, (ident, name, kind, content, enabled, scope, condition) in enumerate(specs):
        if c.execute("SELECT 1 FROM records WHERE kind='watermarks' AND id=?", (ident,)).fetchone():
            continue
        if kind == 'print' and isinstance(legacy_template, str) and legacy_template.strip() and len(legacy_template) <= 240 and len(legacy_template.splitlines()) <= 4 and not set(re.findall(r'\{([^{}]+)\}', legacy_template)) - TOKENS:
            content = legacy_template
        item = validate({'id': ident, 'name': name, 'type': kind, 'content': content,
                         'enabled': enabled, 'scope': scope, 'condition': condition,
                         'priority': (i+1)*10, 'opacity': [18, 12, 22][i]})
        item['updated'] = stamp
        put(c, 'watermarks', item)
    c.execute("INSERT INTO migrations VALUES('watermarks-v1')")
    audit(c, '初始化水印管理', '水印策略', '新增打印、屏幕、截屏水印演示配置')
