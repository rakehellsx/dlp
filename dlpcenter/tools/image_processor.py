"""Image evidence import, optional visible-text OCR and metadata validation."""
import base64
import binascii
import hashlib
import io
import ipaddress
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import warnings
from datetime import datetime, timedelta, timezone

MAX_FILE = 10*1024*1024
MAX_BODY = 15*1024*1024
KINDS = {'print', 'screen', 'screenshot', 'unknown'}
MIMES = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}


def capabilities():
    try:
        from PIL import Image
        images = True
    except ImportError:
        images = False
    return {'images': images, 'ocr': images and bool(shutil.which('tesseract')), 'formats': ['PNG', 'JPEG', 'WEBP'], 'maxSizeMB': 10}


def parse_file(payload):
    name = str(payload.get('filename', '')).replace('\\', '/').rsplit('/', 1)[-1]
    if not name or len(name) > 200:
        raise ValueError('请提供有效的图片文件名，最多200个字符')
    encoded = payload.get('data', '')
    if not isinstance(encoded, str) or len(encoded) > ((MAX_FILE+2)//3)*4:
        raise ValueError('图片不能超过10 MB')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('图片编码无效，请重新选择文件')
    if not raw or len(raw) > MAX_FILE:
        raise ValueError('图片为空或超过10 MB')
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        raise ValueError('服务器尚未安装图片处理组件，请联系管理员')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                fmt, width, height = original.format, *original.size
                if fmt not in MIMES or getattr(original, 'n_frames', 1) != 1:
                    raise ValueError('仅支持单张 PNG、JPEG 或 WEBP 图片')
                if width*height > 40_000_000 or width > 16000 or height > 16000 or min(width,height) < 32:
                    raise ValueError('图片尺寸需至少32×32，最多4000万像素且单边不超过16000像素')
                original.verify()
            with Image.open(io.BytesIO(raw)) as original:
                exif = original.getexif()
                camera = ' '.join(str(exif.get(k, '')).strip() for k in [271,272]).strip()[:160]
                captured = str(exif.get(36867, exif.get(306, '')))[:40]
                image = ImageOps.exif_transpose(original).convert('RGB')
                width, height = image.size
                image.thumbnail((720, 480))
                out = io.BytesIO(); image.save(out, format='JPEG', quality=82)
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValueError('图片损坏、格式无效或尺寸过大，请重新选择')
    return raw, out.getvalue(), {'filename': name, 'size': len(raw), 'width': width, 'height': height,
                               'format': fmt, 'mime': MIMES[fmt], 'hash': hashlib.sha256(raw).hexdigest(),
                               'camera': camera, 'capturedAt': captured}


def validate_metadata(payload):
    if not isinstance(payload, dict):
        raise ValueError('无效的图片关联信息')
    result = {}
    limits = {'title':100, 'code':128, 'user':80, 'department':80, 'endpoint':120, 'ip':45,
              'time':40, 'policyId':80, 'content':4000, 'note':1000}
    for key, limit in limits.items():
        value = payload.get(key, '')
        if not isinstance(value, str):
            raise ValueError('图片关联信息必须为文本')
        value = value.strip()
        if len(value) > limit:
            raise ValueError(f'{key} 内容过长，最多{limit}个字符')
        result[key] = value
    if not result['title']:
        raise ValueError('请填写图片标题')
    result['type'] = payload.get('type', 'unknown')
    result['status'] = payload.get('status', 'pending')
    if not isinstance(result['type'], str) or not isinstance(result['status'], str) or result['type'] not in KINDS or result['status'] not in {'pending', 'reviewed'}:
        raise ValueError('水印类型或核验状态无效')
    if result['ip']:
        try:
            result['ip'] = str(ipaddress.ip_address(result['ip']))
        except ValueError:
            raise ValueError('终端 IP 地址无效')
    if result['time']:
        try:
            dt = datetime.fromisoformat(result['time'].replace('Z', '+00:00'))
            if dt.tzinfo:
                dt = dt.astimezone(timezone(timedelta(hours=8)))
            result['time'] = dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            raise ValueError('水印时间格式无效')
    return result


def extract_text(raw):
    if not shutil.which('tesseract'):
        raise ValueError('当前服务器未启用文字识别组件，可手动填写水印信息')
    from PIL import Image, ImageOps
    with tempfile.TemporaryDirectory(prefix='sentinel-watermark-ocr-') as temp:
        with Image.open(io.BytesIO(raw)) as original:
            image = ImageOps.exif_transpose(original).convert('RGB')
            image.thumbnail((3000,3000))
            if max(image.size) < 1500:
                ratio = 1500/max(image.size)
                image = image.resize((int(image.width*ratio), int(image.height*ratio)))
            image = ImageOps.autocontrast(ImageOps.grayscale(image))
            path = temp+'/source.png'; image.save(path)
        try:
            proc = subprocess.run(['tesseract',path,'stdout','-l','chi_sim+eng','--psm','11'],
                                  capture_output=True, timeout=20, check=False)
        except subprocess.TimeoutExpired:
            raise ValueError('文字识别超时，请尝试更清晰或更小的图片，或手动填写')
        if proc.returncode:
            raise ValueError('图片文字识别失败，可手动填写水印信息')
        return proc.stdout.decode('utf-8','replace').strip()[:16000]


def suggestions(text, endpoints, policies):
    hints = {}
    ip = re.search(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)', text)
    if ip:
        try:
            hints['ip'] = str(ipaddress.ip_address(ip[0]))
        except ValueError:
            pass
    date = re.search(r'20\d{2}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?', text)
    if date:
        try:
            hints['time'] = datetime.fromisoformat(date[0].replace('/','-')).strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass
    code = re.search(r'(?:WM[-_][A-Z0-9_-]{4,100}|WIMG-[A-F0-9]{12})', text, re.I)
    if code:
        hints['code'] = code[0]
    for ep in endpoints:
        if ep['name'].casefold() in text.casefold() or (hints.get('ip') and ep['ip'] == hints['ip']):
            hints.update(endpoint=ep['name'], ip=ep['ip'], user=ep['user'], department=ep['department'])
            break
    for policy in policies:
        if policy['id'] in text or policy['name'] in text:
            hints.update(policyId=policy['id'],type=policy['type'])
            break
    return hints


if __name__ == '__main__':
    import sys
    try:
        payload = json.load(sys.stdin)
        action = payload.get('action')
        if action == 'import':
            raw, thumbnail, info = parse_file(payload)
            result = {'info': info, 'original': base64.b64encode(raw).decode(), 'thumbnail': base64.b64encode(thumbnail).decode()}
        elif action == 'ocr':
            text = extract_text(base64.b64decode(payload['original'], validate=True))
            result = {'text': text, 'suggestions': suggestions(text, payload['endpoints'], payload['policies'])}
        elif action == 'capabilities':
            result = capabilities()
        else:
            raise ValueError('无效的图片处理操作')
        json.dump({'ok': True, **result}, sys.stdout, ensure_ascii=False)
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else '图片处理失败，请重新选择文件'
        json.dump({'ok': False, 'error': message}, sys.stdout, ensure_ascii=False)
