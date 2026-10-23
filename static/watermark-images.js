export function createWatermarkImageModule(h) {
  const {getState,api,esc,icon,btn,link,badge,heading,table,empty,filterInput,filterSelect,
    filterRows,paginate,pagination,opts,modal,drawer,toast,close,refreshAfter,load,download}=h;
  const typeNames={print:'打印水印',screen:'屏幕水印',screenshot:'截屏水印',unknown:'待确认'};
  let files=[],reading=false,uploading=false,ocrBusy=false,view=null;
  const imageUrl=(id,thumb=false)=>'/api/watermark-image/'+encodeURIComponent(id)+(thumb?'?thumb=1':'');
  const bytes=n=>n>=1024*1024?(n/1024/1024).toFixed(2)+' MB':Math.ceil(n/1024)+' KB';
  const status=w=>badge(w.status==='reviewed'?'resolved':'pending',w.status==='reviewed'?'已核验':'待核验');
  const field=(label,control,note='')=>`<div class="form-group"><label>${label}</label>${control}${note?`<small>${note}</small>`:''}</div>`;

  function render() {
    const state=getState(),all=state.watermarkImages||[],rows=filterRows(all,['title','filename','content','code','user','endpoint','ip','note']).sort((a,b)=>b.importedAt.localeCompare(a.importedAt));
    return heading('水印追踪','导入带水印的截图或照片，核验水印内容，查看关联用户、终端与风险事件',
      btn('导出信息','export','download','','data-kind="watermarkImages"')+btn('导入图片','wi-import','plus','primary'))+
      `<div class="wi-summary"><div><span class="wi-summary-icon">${icon('folder')}</span><div><span>已导入图片</span><strong>${all.length}<small>张</small></strong></div></div>
      <div><span class="wi-summary-icon amber">${icon('clock')}</span><div><span>待核验信息</span><strong>${all.filter(w=>w.status==='pending').length}<small>条</small></strong></div></div>
      <div><span class="wi-summary-icon">${icon('checklist')}</span><div><span>已核验信息</span><strong>${all.filter(w=>w.status==='reviewed').length}<small>条</small></strong></div></div>
      <div><span class="wi-summary-icon blue">${icon('harddrive')}</span><div><span>原图存储量</span><strong style="font-size:22px">${bytes(all.reduce((n,w)=>n+w.size,0))}</strong></div></div></div>
      <div class="info-banner">${icon('info')}支持 PNG、JPG/JPEG、WEBP 截图或照片，每张最多10 MB。可辅助识别可见文字，识别内容需人工核验；暗水印解码需接入对应厂商解析能力。</div>
      <section class="panel"><div class="toolbar">${filterInput('搜索水印编号、文字、用户或终端')}${filterSelect('type',Object.entries(typeNames),'全部水印类型')}${filterSelect('status',[['pending','待核验'],['reviewed','已核验']],'全部核验状态')}<span class="grow"></span>${btn('重置','reset','refresh')}</div>
      ${rows.length?`<div class="wi-gallery">${paginate(rows).map(w=>`<article class="wi-card"><button class="wi-card-image" data-action="wi-detail" data-id="${w.id}" aria-label="查看 ${esc(w.title)}"><img src="${imageUrl(w.id,true)}" loading="lazy" alt="${esc(w.title)}"><span>${icon('eye')}查看图片</span></button><div class="wi-card-body"><div class="between"><span class="tag">${typeNames[w.type]}</span>${status(w)}</div><h2 title="${esc(w.title)}">${esc(w.title)}</h2><p>${w.user?esc(w.user)+' · ':''}${esc(w.endpoint||w.ip||'尚未关联终端')}</p><div class="wi-card-bottom"><span>${w.importedAt.slice(5,16)}</span>${link('查看详情 →','wi-detail',`data-id="${w.id}"`)}</div></div></article>`).join('')}</div>`:empty(all.length?'没有匹配的图片':'还没有导入水印图片',all.length?'请调整搜索或筛选条件':'点击“导入图片”，上传带水印的截图或照片，开始核验与溯源')}
      ${pagination(rows.length)}</section><div class="wi-page-note">${icon('lock')}原图与关联信息保存在当前服务器，需登录后访问 · 相同原图按 SHA-256 去重</div>`;
  }

  function importForm() {
    if(uploading||reading){toast('图片正在处理，请稍候再开始新的导入');return;}
    files=[];reading=false;
    modal('导入水印截图 / 照片',`<form id="wi-upload-form" data-form="watermark-images">
      <div class="wi-dropzone" data-wi-drop><input id="wi-files" type="file" accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp" multiple hidden>
      <span class="wi-drop-icon">${icon('folder')}</span><strong>将截图或照片拖拽到此处</strong><p>PNG / JPG / WEBP · 每张最多10 MB · 一次最多5张</p>${btn('选择图片','wi-pick','plus','','type="button"')}</div>
      <div id="wi-selected-files"></div><div class="form-group" style="margin-top:21px"><label>导入备注</label><textarea name="note" maxlength="1000" rows="2" placeholder="可填写图片来源、发现渠道或核验事项"></textarea></div>
      <div class="wi-import-help">${icon('info')}导入后可查看原图、放大和旋转，辅助识别可见文字并填写用户、终端和时间等关联信息。</div></form>`,
      btn('取消','close')+'<button class="btn primary" type="submit" form="wi-upload-form" id="wi-import-submit" disabled>'+icon('plus')+'确认导入</button>',true);
  }

  function renderFiles() {
    const box=document.querySelector('#wi-selected-files');if(!box)return;
    box.innerHTML=files.map((f,i)=>`<div class="wi-file-row"><img src="${f.url}" alt="待导入图片"><div class="grow"><strong>${esc(f.file.name)}</strong><small>${bytes(f.file.size)}</small></div><span id="wi-file-state-${i}" class="muted small">待导入</span><button type="button" class="icon-btn" data-action="wi-remove" data-index="${i}" aria-label="移除图片">${icon('close')}</button></div>`).join('');
    const submit=document.querySelector('#wi-import-submit');if(submit)submit.disabled=!files.length||reading||uploading;
  }

  async function selectFiles(input) {
    if(reading||uploading)return;
    const chosen=Array.from(input);
    if(chosen.length+files.length>5){toast('一次最多导入5张图片',true);return;}
    reading=true;
    try{
      for(const file of chosen){
        if(!/\.(png|jpe?g|webp)$/i.test(file.name)||!['image/png','image/jpeg','image/webp',''].includes(file.type)){toast(file.name+'：仅支持 PNG、JPEG 或 WEBP',true);continue;}
        if(!file.size||file.size>10*1024*1024){toast(file.name+'：图片为空或超过10 MB',true);continue;}
        const url=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(new Error('读取图片失败'));r.readAsDataURL(file);});
        files.push({file,url});
      }
    }catch(e){toast(e.message,true);}finally{reading=false;renderFiles();}
  }

  async function submit(form) {
    if(reading||uploading)return;
    if(!files.length)throw new Error('请先选择需要导入的图片');
    uploading=true;renderFiles();
    const note=new FormData(form).get('note')||'',results=[];
    try{
      for(let i=0;i<files.length;i++){
        const f=files[i],state=document.querySelector('#wi-file-state-'+i);
        if(state)state.textContent='正在导入…';
        try{
          const result=await api('watermark-images/import',{filename:f.file.name,data:f.url.split(',')[1],note});
          results.push({name:f.file.name,...result});if(state)state.textContent=result.duplicate?'原图已存在':'导入成功';
        }catch(e){results.push({name:f.file.name,error:e.message});if(state)state.textContent='导入失败';}
      }
      await load(false);close();await refreshAfter('图片导入处理完成');
      const success=results.filter(r=>!r.error&&!r.duplicate).length,duplicates=results.filter(r=>r.duplicate).length,failed=results.filter(r=>r.error).length;
      modal('图片导入结果',`<div class="wi-result-summary"><span><strong>${success}</strong>导入成功</span><span><strong>${duplicates}</strong>原图已存在</span><span><strong>${failed}</strong>导入失败</span></div>
        ${results.map(r=>`<div class="wi-result-row"><div><strong>${esc(r.name)}</strong><p>${esc(r.error||(r.duplicate?'相同原图已存在，已跳过重复导入':'原图及文件信息已保存，可以继续核验水印信息'))}</p></div>${r.id?link('查看详情','wi-detail',`data-id="${r.id}"`):badge('high','失败')}</div>`).join('')}`,
        btn('完成','close')+(results.find(r=>r.id)?btn('查看图片信息','wi-detail','eye','primary',`data-id="${results.find(r=>r.id).id}"`):''),true);
      files=[];
    }finally{uploading=false;renderFiles();}
  }

  function detail(id) {
    const s=getState(),w=s.watermarkImages.find(w=>w.id===id);if(!w)return;
    const ep=s.endpoints.find(e=>(w.endpoint&&e.name===w.endpoint)||(w.ip&&e.ip===w.ip));
    const events=ep?s.events.filter(e=>e.endpointId===ep.id).slice(0,4):[];
    const policy=s.watermarks.find(p=>p.id===w.policyId);
    drawer('水印图片与关联信息',`<div class="between"><span class="mono muted">${w.id}</span>${status(w)}</div>
      <h2 class="drawer-title">${esc(w.title)}</h2><button class="wi-detail-image" data-action="wi-view" data-id="${id}" aria-label="放大查看原图"><img src="${imageUrl(id,true)}" alt="${esc(w.title)}"><span>${icon('eye')}放大查看原图</span></button>
      <div class="between wi-image-meta"><span>${w.width} × ${w.height} px · ${w.format} · ${bytes(w.size)}</span>${link('下载原图','wi-download',`data-id="${id}"`)}</div>
      <section class="detail-section"><div class="between" style="margin-bottom:15px"><h3 style="margin:0">水印信息核验</h3>${btn(w.ocrState==='not_run'?'辅助识别文字':'重新识别文字','wi-ocr','spark','',`data-id="${id}" ${s.imageCapabilities?.ocr?'':'disabled title="服务器未启用识别组件"'}`)}</div>
      <p class="wi-assist-note">识别图片中的可见文字，结果可辅助填写下方字段。淡色、倾斜或暗水印可能无法识别，请以人工核验为准。</p>
      <div id="wi-ocr-status" class="wi-ocr-status ${w.ocrState==='not_run'?'hidden':''}">${w.ocrState==='empty'?'上次未提取到可用文字，可手动填写水印信息。':'已提取文字，请核验关联字段后保存。'}</div>
      <details class="wi-ocr-result ${w.ocrState==='not_run'?'hidden':''}" id="wi-ocr-result"><summary>查看提取的原始文字</summary><textarea readonly id="wi-ocr-text" aria-label="提取的原始文字">${esc(w.ocrText||'')}</textarea></details>
      <form id="wi-metadata-form" data-form="watermark-image-metadata"><input type="hidden" name="id" value="${id}">
      ${field('图片标题 <span class="required">*</span>',`<input name="title" value="${esc(w.title)}" maxlength="100" required>`)}
      <div class="form-grid">${field('水印类型',`<select name="type">${opts(Object.entries(typeNames),w.type)}</select>`)}${field('核验状态',`<select name="status">${opts([['pending','待核验'],['reviewed','已核验']],w.status)}</select>`)}</div>
      <div class="form-group" style="margin-top:19px"><label>图片中的水印文字</label><textarea name="content" maxlength="4000" placeholder="可填写或粘贴图片中可见的水印内容">${esc(w.content)}</textarea></div>
      <div class="form-grid">${field('水印编号 / 标识',`<input name="code" value="${esc(w.code)}" maxlength="128" placeholder="可选">`)}${field('用户姓名',`<input name="user" value="${esc(w.user)}" maxlength="80" placeholder="例如：张明">`)}</div>
      <div class="form-grid" style="margin-top:19px">${field('所属部门',`<input name="department" value="${esc(w.department)}" maxlength="80">`)}${field('终端名称',`<input name="endpoint" value="${esc(w.endpoint)}" maxlength="120" placeholder="例如：RD-DESKTOP-001">`)}</div>
      <div class="form-grid" style="margin-top:19px">${field('终端 IP',`<input name="ip" value="${esc(w.ip)}" maxlength="45" placeholder="例如：192.168.10.20">`)}${field('水印时间',`<input name="time" type="datetime-local" step="1" value="${esc(w.time?.replace(' ','T')||'')}">`)}</div>
      <div class="form-group" style="margin-top:19px"><label>关联水印策略</label><select name="policyId">${opts(s.watermarks.map(p=>[p.id,p.name]),w.policyId,'未关联策略')}</select></div>
      ${field('核验备注',`<textarea name="note" maxlength="1000" placeholder="记录图片来源、核验依据或发现事项">${esc(w.note)}</textarea>`)}
      </form></section>
      <section class="detail-section"><h3>已保存的关联关系</h3>${ep?`<div class="wi-related"><div>${icon('monitor')}<strong>${esc(ep.name)}</strong><small>${esc(ep.user)} · ${esc(ep.department)} · ${ep.ip}</small></div>${link('查看终端','endpoint-detail',`data-id="${ep.id}"`)}</div>`:'<p class="wi-assist-note">尚未匹配纳管终端。填写准确的终端名称或 IP 并保存后，可查看关联终端与风险事件。</p>'}
      ${policy?`<div class="wi-related"><div>${icon('layers')}<strong>${esc(policy.name)}</strong><small>${typeNames[policy.type]}</small></div>${link('策略预览','watermark-preview',`data-id="${policy.id}"`)}</div>`:''}
      ${events.map(e=>`<div class="wi-related"><div>${icon('alert')}<strong>${esc(e.title)}</strong><small>${e.time} · ${esc(e.file)}</small></div>${link('查看事件','event-detail',`data-id="${e.id}"`)}</div>`).join('')}</section>
      <section class="detail-section"><h3>原图信息</h3><div class="detail-grid">${[['文件名',w.filename],['导入时间',w.importedAt],['导入人',w.actor],['相机 / 设备',w.camera||'无 EXIF 设备信息'],['EXIF 拍摄时间',w.capturedAt||'未包含'],['信息更新时间',w.updated]].map(([k,v])=>`<div><span class="detail-label">${k}</span><span class="detail-value">${esc(v)}</span></div>`).join('')}</div><p class="wi-hash"><span>原图 SHA-256</span>${w.hash}</p><p class="wi-assist-note">EXIF 为原图自带信息，关联字段为辅助识别建议或人工核验记录，不作为身份真实性证明。</p></section>`,
      btn('删除图片','wi-delete','trash','danger',`data-id="${id}"`)+btn('关闭','close')+'<button class="btn primary" type="submit" form="wi-metadata-form">'+icon('check')+'保存核验信息</button>');
  }

  async function saveMetadata(form) {
    const data=Object.fromEntries(new FormData(form));
    await api('watermark-images/save',{id:data.id,metadata:data});
    await refreshAfter('水印图片关联信息已保存');detail(data.id);
  }

  async function ocr(id) {
    if(ocrBusy)return;ocrBusy=true;
    const button=document.querySelector('[data-action=wi-ocr]'),state=document.querySelector('#wi-ocr-status');
    if(button){button.disabled=true;button.textContent='正在识别…';}
    if(state){state.classList.remove('hidden');state.textContent='正在识别图片中的可见文字，请稍候…';}
    try{
      const result=await api('watermark-images/ocr',{id});
      const record=getState().watermarkImages.find(w=>w.id===id);Object.assign(record,result.item);
      const form=document.querySelector('#wi-metadata-form');
      if(!form||form.elements.id.value!==id)return;
      for(const [key,value] of Object.entries(result.suggestions)){
        const input=form.elements.namedItem(key);if(input&&(!input.value||(key==='type'&&input.value==='unknown')))input.value=key==='time'?value.replace(' ','T'):value;
      }
      if(!form.elements.content.value)form.elements.content.value=result.item.ocrText.slice(0,4000);
      document.querySelector('#wi-ocr-result').classList.remove('hidden');document.querySelector('#wi-ocr-text').value=result.item.ocrText;
      state.textContent=result.item.ocrText?'已提取文字，识别建议已填入空白字段；请核验后保存。':'未提取到可用文字，可手动填写关联信息。';
    }catch(e){if(state)state.textContent=e.message;toast(e.message,true);}finally{ocrBusy=false;if(button){button.disabled=false;button.innerHTML=icon('spark')+'重新识别文字';}}
  }

  function viewer(id) {
    const w=getState().watermarkImages.find(w=>w.id===id);if(!w)return;
    view={id,zoom:1,rotation:0};
    modal('查看水印原图',`<div class="wi-view-toolbar"><span class="grow">${esc(w.filename)}</span>${btn('−','wi-zoom-out')}${btn('适应窗口','wi-fit')}${btn('＋','wi-zoom-in')}${btn('旋转','wi-rotate','refresh')}<span id="wi-zoom-label">100%</span></div><div class="wi-viewer" id="wi-viewer"><div id="wi-view-box"><img src="${imageUrl(id)}" alt="${esc(w.title)}" id="wi-original"></div></div><p class="wi-assist-note">使用缩放、旋转和滚动条查看细节。旋转仅影响查看效果，保留上传原图。</p>`,
      btn('关闭','close')+btn('返回关联信息','wi-detail','policy','',`data-id="${id}"`)+btn('下载原图','wi-download','download','primary',`data-id="${id}"`),true);
    document.querySelector('.modal').classList.add('wi-viewer-modal');updateViewer();
  }

  function updateViewer() {
    if(!view)return;const w=getState().watermarkImages.find(w=>w.id===view.id),container=document.querySelector('#wi-viewer');if(!w||!container)return;
    const rotated=view.rotation%180!==0,W=rotated?w.height:w.width,H=rotated?w.width:w.height;
    const fit=Math.min((container.clientWidth-48)/W,(container.clientHeight-48)/H,1),scale=fit*view.zoom;
    const box=document.querySelector('#wi-view-box'),img=document.querySelector('#wi-original');
    box.style.width=W*scale+'px';box.style.height=H*scale+'px';img.style.width=w.width*scale+'px';img.style.height=w.height*scale+'px';img.style.transform=`translate(-50%,-50%) rotate(${view.rotation}deg)`;
    document.querySelector('#wi-zoom-label').textContent=Math.round(scale*100)+'%';
  }

  async function action(a,d) {
    if(a==='wi-import')importForm();
    else if(a==='wi-pick')document.querySelector('#wi-files')?.click();
    else if(a==='wi-remove'){if(uploading)return;files.splice(Number(d.index),1);renderFiles();}
    else if(a==='wi-detail')detail(d.id);
    else if(a==='wi-view')viewer(d.id);
    else if(a==='wi-ocr')await ocr(d.id);
    else if(a==='wi-download'){
      const res=await fetch(imageUrl(d.id)+'?download=1');if(!res.ok||res.headers.get('Content-Type')?.includes('json'))throw new Error('下载失败，请重新登录后重试');
      const w=getState().watermarkImages.find(w=>w.id===d.id);download(w.filename,await res.blob(),w.mime);toast('原图已下载');
    }
    else if(a==='wi-delete'){const w=getState().watermarkImages.find(w=>w.id===d.id);modal('删除水印图片',`<p class="detail-value" style="font-size:12px">确认删除「${esc(w.title)}」及其关联信息？</p>`,btn('取消','wi-detail','','',`data-id="${d.id}"`)+btn('确认删除','wi-delete-confirm','trash','danger',`data-id="${d.id}"`));}
    else if(a==='wi-delete-confirm'){await api('watermark-images/delete',{id:d.id});close();await refreshAfter('水印图片及关联信息已删除');}
    else if(a==='wi-zoom-in'){view.zoom=Math.min(8,view.zoom*1.3);updateViewer();}
    else if(a==='wi-zoom-out'){view.zoom=Math.max(.4,view.zoom/1.3);updateViewer();}
    else if(a==='wi-fit'){view.zoom=1;view.rotation=0;updateViewer();}
    else if(a==='wi-rotate'){view.rotation=(view.rotation+90)%360;updateViewer();}
  }

  async function onChange(target){if(target.id==='wi-files'){await selectFiles(target.files);target.value='';}}
  return {render,importForm,submit,saveMetadata,action,onChange,selectFiles,updateViewer};
}
