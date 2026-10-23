"""Explicitly import labeled synthetic watermark examples; safe to rerun, no startup seeding."""
import argparse
import base64
import getpass
import hashlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import urllib.parse
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFont, ImageFilter

TAG = '[watermark-demo-v1]'
STAMP = '2026-10-22'
CASES = [
    ('screen', 'reviewed', '研发方案屏幕水印', '研发中心', 'PNG', '研发技术方案 · 内部评审'),
    ('print', 'reviewed', '财务预算打印水印', '财务部', 'JPEG', '季度预算汇总 · 演示文档'),
    ('screenshot', 'reviewed', '客户资料截屏水印', '市场营销部', 'PNG', '客户协作台账 · 模拟样本'),
    ('screen', 'pending', '人事台账待核验', '人力资源部', 'WEBP', '人员台账 · 合成数据'),
    ('print', 'pending', '供应商报价纸张照片', '行政管理部', 'JPEG', '供应商报价 · 测试样张'),
    ('screenshot', 'pending', '产品设计截屏待核验', '产品设计部', 'PNG', '产品设计评审 · 交互原型'),
    ('screen', 'reviewed', '市场分析屏幕水印', '市场营销部', 'WEBP', '市场分析简报 · 业务演示'),
    ('print', 'reviewed', '合作协议打印水印', '行政管理部', 'JPEG', '合作协议摘要 · 非真实合同'),
    ('screenshot', 'reviewed', '研发文档截屏溯源', '研发中心', 'PNG', '技术文档索引 · 测试记录'),
    ('screen', 'pending', '财务报表淡色水印', '财务部', 'PNG', '财务报表预览 · 合成数据'),
    ('print', 'pending', '人事清单打印照片', '人力资源部', 'JPEG', '人员信息清单 · 虚构样本'),
    ('unknown', 'pending', '来源未知图片人工核验', '', 'PNG', '待确认来源 · 手工核验练习'),
]


def font(size, bold=False):
    suffix = 'Bold' if bold else 'Regular'
    candidates = [f'/usr/share/fonts/opentype/noto/NotoSansCJK-{suffix}.ttc',
                  f'/usr/share/fonts/opentype/noto/NotoSerifCJK-{suffix}.ttc',
                  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for name in candidates:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    raise RuntimeError('请安装中文字体 fonts-noto-cjk 后生成演示图片')


def document(index, kind, title, endpoint, policy, timestamp):
    """Draw synthetic document contents; every image visibly identifies itself as a demo."""
    image = Image.new('RGB', (1440,960), '#f2f6f7')
    d = ImageDraw.Draw(image)
    d.rectangle((0,0,1440,65), fill='#183d45')
    d.text((35,12), 'Sentinel Workspace  /  演示样本 · 合成数据', font=font(27,True), fill='white')
    d.rectangle((35,90,1405,925),fill='white',outline='#d8e2e5',width=2)
    d.text((80,125),title,font=font(40,True),fill='#23454b')
    d.text((80,192),'仅用于水印追踪功能测试 · 非真实业务资料',font=font(23),fill='#819095')
    d.line((80,246,1360,246),fill='#e5ecee',width=2)
    d.rounded_rectangle((80,280,1360,342),radius=5,fill='#eaf4f0')
    for x,text in [(105,'样本编号'),(390,'项目 / 资料名称'),(940,'数据等级'),(1185,'示例状态')]:
        d.text((x,296),text,font=font(24,True),fill='#3c6e60')
    for row in range(5):
        y=367+row*66
        if row%2==0:d.rectangle((80,y-4,1360,y+55),fill='#f7f9fa')
        for x,text in [(105,f'DEMO-{index:02d}-{row+1:03d}'),(390,['评审材料（虚构）','协作记录（虚构）','业务摘要（虚构）','内部说明（虚构）','附件索引（虚构）'][row]),(940,'内部 / L1'),(1185,'测试记录')]:
            d.text((x,y+5),text,font=font(23),fill='#5e747a')
    user = endpoint.get('user','来源待确认')
    ep = endpoint.get('name','未匹配终端')
    ip = endpoint.get('ip','待人工补充')
    code = f'WM-DEMO-{index:03d}'
    # Repeated diagonal visible watermark; the footer remains sharp for OCR exercises.
    layer=Image.new('RGBA',image.size,(0,0,0,0))
    tile=Image.new('RGBA',(880,150),(0,0,0,0));td=ImageDraw.Draw(tile)
    alpha=32 if index==10 else 65
    td.text((12,15),f'内部使用 · {user} · {code}',font=font(38,True),fill=(50,118,102,alpha))
    td.text((12,78),f'{ep}  |  {ip}',font=font(26),fill=(50,118,102,alpha))
    tile=tile.rotate(24,expand=True,resample=Image.Resampling.BICUBIC)
    for y in [260,500]:
        layer.alpha_composite(tile,(100 if y==260 else 380,y-50))
    image=Image.alpha_composite(image.convert('RGBA'),layer).convert('RGB');d=ImageDraw.Draw(image)
    d.rectangle((80,747,1360,879),fill='#f1f6f3',outline='#dfeae4',width=1)
    d.text((100,758),f'{code}  |  {user}  |  {endpoint.get("department","待核验")}',font=font(23),fill='#477362')
    d.text((100,797),f'{ep}  |  {ip}  |  {timestamp}',font=font(22),fill='#477362')
    policy_text=policy.get('id','无已知策略')
    d.text((100,838),f'{policy_text}  |  演示样本，关联信息为模拟记录',font=font(20),fill='#779286')
    if kind=='print':
        # A rendered paper-photo fixture, rather than a claim of an actual photograph.
        paper=image.resize((1050,700),Image.Resampling.LANCZOS).rotate(-3 if index%2 else 3,expand=True,resample=Image.Resampling.BICUBIC,fillcolor='#e7e5df')
        desk=Image.new('RGB',(1440,1000),'#d7d3c9')
        shadow=Image.new('RGBA',desk.size,(0,0,0,0));sd=ImageDraw.Draw(shadow)
        x=(1440-paper.width)//2;y=(1000-paper.height)//2
        sd.rectangle((x+15,y+20,x+paper.width+15,y+paper.height+20),fill=(33,45,40,55));shadow=shadow.filter(ImageFilter.GaussianBlur(15))
        desk=Image.alpha_composite(desk.convert('RGBA'),shadow).convert('RGB');desk.paste(paper,(x,y))
        ImageDraw.Draw(desk).text((32,30),'打印照片模拟样本 · 非真实拍摄',font=font(25,True),fill='#665f51')
        image=desk
    return image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8091')
    parser.add_argument('--username',default='admin')
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'artifacts'/'watermark-demo')
    args=parser.parse_args();password=os.environ.get('DLP_DEMO_PASSWORD') or getpass.getpass('控制台密码：')
    client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def api(path,payload=None):
        req=urllib.request.Request(args.base_url.rstrip('/')+'/api/'+path,
            data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None,
            headers={'Content-Type':'application/json','X-DLP-Request':'1'})
        try:
            with client.open(req,timeout=35) as response:
                result=json.load(response)
                if result.get('code')!=0:raise RuntimeError(result.get('error','请求失败'))
                return result
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'{path}: {json.load(exc).get("error",exc.code)}') from None
    api('login',{'username':args.username,'password_hash':hashlib.sha256(password.encode()).hexdigest()})
    state=api('bootstrap')
    for kind in ['endpoints','watermarks','watermarkImages']:
        state[kind]=[];page=1
        while True:
            result=api('query?'+urllib.parse.urlencode({'kind':kind,'page':page,'pageSize':100}))
            state[kind].extend(result['items'])
            if len(state[kind])>=result['total']:break
            page+=1
    existing={w['filename'] for w in state['watermarkImages'] if TAG in w.get('note','')}
    args.output.mkdir(parents=True,exist_ok=True)
    report=[]
    for index,(kind,status,label,department,fmt,title) in enumerate(CASES,1):
        extension={'JPEG':'jpg','PNG':'png','WEBP':'webp'}[fmt];filename=f'watermark-demo-v1-{index:02d}.{extension}'
        if filename in existing:
            report.append({'filename':filename,'skipped':True});continue
        endpoint=next((e for e in state['endpoints'] if e['department']==department),{}) if department else {}
        policy=next((p for p in state['watermarks'] if p['type']==kind),{})
        timestamp=f'{STAMP} {8+(index//4):02d}:{(index*7)%60:02d}:00'
        image=document(index,kind,title,endpoint,policy,timestamp)
        buffer=io.BytesIO();image.save(buffer,format=fmt,**({'quality':91} if fmt in {'JPEG','WEBP'} else {}))
        raw=buffer.getvalue();(args.output/filename).write_bytes(raw)
        content=f'内部使用 · {endpoint.get("user","来源待确认")} · WM-DEMO-{index:03d}\n{endpoint.get("name","未匹配终端")} · {endpoint.get("ip","待人工补充")} · {timestamp}'
        note=f'{TAG} 合成测试样本，非真实泄漏证据。'+('演示已核验状态，用于关联终端与事件下钻。' if status=='reviewed' else '演示待核验状态，请尝试辅助识别并人工核验。')
        metadata={'type':kind,'status':status,'code':f'WM-DEMO-{index:03d}',
                  'user':endpoint.get('user',''),'department':endpoint.get('department',''),
                  'endpoint':endpoint.get('name',''),'ip':endpoint.get('ip',''),
                  'time':timestamp if kind!='unknown' else '', 'policyId':policy.get('id',''),
                  'content':content if status=='reviewed' else ''}
        result=api('watermark-images/import',{'filename':filename,'data':base64.b64encode(raw).decode(),
                    'title':'[演示] '+label,'note':note,'metadata':metadata})
        report.append({'filename':filename,'id':result['id'],'duplicate':result['duplicate']})
        print(f'{index:02d} {label}: '+('已存在' if result['duplicate'] else '已导入'),flush=True)
    (args.output/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(f'完成：新导入 {sum(not r.get("skipped") and not r.get("duplicate") for r in report)}，跳过 {sum(bool(r.get("skipped") or r.get("duplicate")) for r in report)}。',flush=True)
    api('logout',{})


if __name__=='__main__':
    main()
