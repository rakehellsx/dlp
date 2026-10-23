// Watermark configuration and SVG previews share one rendering path.
export function createWatermarkModule(h) {
  const {getState, esc, icon, btn, link, badge, toggle, heading, table, empty,
    filterInput, filterSelect, filterRows, paginate, pagination, opts, modal, toast, download,ensureDetail} = h;
  const types = {print:['打印水印','printer','在纸质文档上保留身份标识，让打印流转有迹可循。'],screen:['屏幕水印','monitor','持续显示操作者与设备信息，提升屏幕内容可追溯性。'],screenshot:['截屏水印','scan','为截屏添加身份与时间标识，保护图片中的敏感信息。']};
  const conditions = {always:'全部内容',sensitive:'仅敏感内容',apps:'指定应用'};
  const scopes = ()=>['全体终端',...getState().options.departments];
  const apps = ['Office 文档','PDF 阅读器','浏览器','即时通讯','其他应用'];
  const tokens = ['企业名称','姓名','账号','部门','终端','终端IP','时间','文档名称'];
  const methods = [['system','系统快捷键'],['tools','截屏工具'],['clipboard','复制到剪贴板']];
  let tab = 'all', previewSequence = 0;

  function defaults(type='screen') {
    return {name:'',type,scope:'全体终端',condition:'always',content:'{企业名称}\n{姓名} · {终端IP}',
      fontFamily:'Microsoft YaHei',fontSize:20,color:'#66737f',opacity:18,angle:-30,
      position:'tile',spacing:180,priority:10,enabled:true,bold:false,bothSides:true,
      paperSize:'A4',printers:'全部打印机',screenTarget:'all',apps:[],
      screenshotMethods:['system','tools','clipboard'],description:''};
  }

  function render() {
    const state = getState(), records = state.watermarks || [];
    const rows=records,summary=state.stats.watermarks;
    return heading('水印管理','统一管理打印、屏幕与截屏水印，让敏感内容流转可识别、可追溯',
      btn('水印追踪','nav','eye','','data-target="watermark-images"')+btn('导出配置','export','download','','data-kind="watermarks"')+btn('新建水印策略','watermark-new','plus','primary'))+
      `<div class="wm-categories">${Object.entries(types).map(([key,[label,ico,desc]])=>{
        const total=summary[key]?.total||0,enabled=summary[key]?.enabled||0;
        return `<button class="wm-category ${tab===key?'selected':''}" data-action="watermark-tab" data-value="${key}">
          <div class="between"><span class="wm-category-icon">${icon(ico)}</span><span class="tag">${total} 项策略</span></div>
          <h2>${label}</h2><p>${desc}</p><div class="between"><span class="wm-category-status"><i class="dot ${enabled?'green':'muted'}"></i>${enabled} 项已启用</span><span class="wm-category-more">配置管理 ${icon('arrow')}</span></div></button>`;
      }).join('')}</div>
      <div class="info-banner">${icon('info')}配置打印、屏幕和截屏水印，实时查看效果预览。同类策略按优先级从小到大匹配，终端水印需接入客户端。</div>
      <section class="panel"><div class="tabs">${[['all','全部水印'],...Object.entries(types).map(([k,v])=>[k,v[0]])].map(([k,label])=>
        `<button class="${tab===k?'active':''}" data-action="watermark-tab" data-value="${k}">${label}<em>${k==='all'?(state.stats.counts.watermarks||0):(summary[k]?.total||0)}</em></button>`).join('')}</div>
      <div class="toolbar">${filterInput('搜索策略名称、水印内容或范围')}${filterSelect('scope',scopes(),'全部适用范围')}${filterSelect('enabledState',[['enabled','已启用'],['disabled','已停用']],'全部启用状态')}<span class="grow"></span>${btn('重置','reset','refresh')}</div>
      ${rows.length?table(['水印策略','水印类型','内容模板','适用范围 / 优先级','生效条件','启用状态','更新时间','操作'],paginate(rows).map(w=>`<tr>
        <td><div class="cell-title">${esc(w.name)}</div><div class="cell-sub mono">${esc(w.id)}</div></td>
        <td><span class="tag">${icon(types[w.type][1])}${types[w.type][0]}</span></td>
        <td><div class="wm-template-cell" title="${esc(w.content)}">${esc(w.content).replace(/\n/g,'<br>')}</div></td>
        <td>${esc(w.scope)}<div class="cell-sub">优先级 ${w.priority}</div></td><td>${conditions[w.condition]}</td>
        <td>${toggle(w.enabled,'watermarks',w.id)}</td><td class="mono" style="font-size:10px">${w.updated.slice(5,16)}</td>
        <td><div class="table-actions">${link('预览','watermark-preview',`data-id="${esc(w.id)}"`)}${link('编辑','watermark-edit',`data-id="${esc(w.id)}"`)}${link('删除','delete',`data-kind="watermarks" data-id="${esc(w.id)}"`)}</div></td>
      </tr>`)):empty('没有匹配的水印策略','可调整筛选条件，或新建一项水印策略')}${pagination(rows.length)}</section>`;
  }

  function group(label,control,note='') {
    return `<div class="form-group"><label>${label}</label>${control}${note?`<small>${note}</small>`:''}</div>`;
  }

  async function form(id='',type='') {
    const item=(id?await ensureDetail('watermarks',id):null)||defaults(type|| (tab==='all'?'screen':tab));
    const isNew=!id,ep=getState().options.preview||{};
    modal(isNew?'新建水印策略':'编辑水印策略',`<div class="wm-editor"><form id="watermark-form" data-form="watermark">
      <input type="hidden" name="id" value="${esc(id)}">
      <div class="wm-form-section"><h3><span>01</span>基本信息</h3>
      ${group('策略名称 <span class="required">*</span>',`<input name="name" value="${esc(item.name)}" placeholder="例如：研发文档打印水印" maxlength="80" required>`)}
      <div class="form-grid">${group('水印类型',`<select name="type">${opts(Object.entries(types).map(([k,v])=>[k,v[0]]),item.type)}</select>`)}
      ${group('适用范围',`<select name="scope">${opts(scopes(),item.scope)}</select>`)}</div>
      <div class="form-grid" style="margin-top:18px">${group('生效条件',`<select name="condition">${opts(Object.entries(conditions),item.condition)}</select>`)}
      ${group('优先级',`<input type="number" name="priority" value="${item.priority}" min="1" max="999" required>`)}</div>
      <div class="wm-app-options ${item.condition==='apps'?'':'hidden'}">${group('适用应用',`<div class="check-group">${apps.map(a=>`<label><input type="checkbox" name="apps" value="${a}" ${item.apps.includes(a)?'checked':''}>${a}</label>`).join('')}</div>`)}</div>
      </div><div class="wm-form-section"><h3><span>02</span>水印内容</h3>
      ${group('内容模板 <span class="required">*</span>',`<textarea name="content" id="watermark-content" rows="3" maxlength="240" required placeholder="请输入水印内容，可插入下方动态字段">${esc(item.content)}</textarea>`,'支持4行文本、最多240个字符；动态字段将由终端实际信息替换。')}
      <div class="wm-tokens">${tokens.map(t=>`<button type="button" data-action="watermark-token" data-token="${t}">{${t}}</button>`).join('')}</div>
      </div><div class="wm-form-section"><h3><span>03</span>显示样式</h3>
      <div class="form-grid">${group('字体',`<select name="fontFamily">${opts([['Microsoft YaHei','微软雅黑'],['SimSun','宋体'],['Arial','Arial']],item.fontFamily)}</select>`)}
      ${group('字号 / px',`<input type="number" name="fontSize" value="${item.fontSize}" min="12" max="48" required>`)}</div>
      <div class="form-grid" style="margin-top:18px">${group('文字颜色',`<div class="wm-color-field"><input type="color" name="color" value="${esc(item.color)}" aria-label="水印文字颜色"><span id="wm-color-value" class="mono">${esc(item.color)}</span></div>`)}
      ${group('布局方式',`<select name="position">${opts([['tile','全屏平铺'],['center','居中显示'],['top','顶部显示'],['bottom','底部显示']],item.position)}</select>`)}</div>
      <div class="wm-range-row"><label for="wm-opacity">不透明度 <output id="wm-opacity-value">${item.opacity}%</output></label><input id="wm-opacity" type="range" name="opacity" value="${item.opacity}" min="5" max="80" step="1"></div>
      <div class="wm-range-row"><label for="wm-angle">旋转角度 <output id="wm-angle-value">${item.angle}°</output></label><input id="wm-angle" type="range" name="angle" value="${item.angle}" min="-90" max="90" step="1"></div>
      <div class="wm-spacing-options ${item.position==='tile'?'':'hidden'}">${group('平铺间距 / px',`<input name="spacing" type="number" value="${item.spacing}" min="100" max="360" required>`)}</div>
      <label class="wm-checkbox"><input type="checkbox" name="bold" ${item.bold?'checked':''}>加粗水印文字</label>
      </div><div class="wm-form-section"><h3><span>04</span>场景设置</h3>
      <div class="wm-type-options ${item.type==='print'?'':'hidden'}" data-wm-type="print">
        <div class="form-grid">${group('纸张预览',`<select name="paperSize">${opts(['A4','A3'],item.paperSize)}</select>`)}
        ${group('打印机范围',`<input name="printers" value="${esc(item.printers)}" maxlength="200" placeholder="全部打印机 / 指定打印机名称">`)}</div>
        <label class="wm-checkbox" style="margin-top:17px"><input type="checkbox" name="bothSides" ${item.bothSides?'checked':''}>双面打印时，两面均添加水印</label>
      </div><div class="wm-type-options ${item.type==='screen'?'':'hidden'}" data-wm-type="screen">
        ${group('显示器范围',`<select name="screenTarget">${opts([['all','全部显示器'],['primary','仅主显示器']],item.screenTarget)}</select>`,'覆盖桌面及应用窗口，预览展示单个显示器上的效果。')}
      </div><div class="wm-type-options ${item.type==='screenshot'?'':'hidden'}" data-wm-type="screenshot">
        ${group('适用截屏方式',`<div class="check-group">${methods.map(([key,label])=>`<label><input type="checkbox" name="screenshotMethods" value="${key}" ${item.screenshotMethods.includes(key)?'checked':''}>${label}</label>`).join('')}</div>`,'截屏水印单独配置，预览展示生成图片中的水印效果。')}
      </div></div><div class="wm-form-section wm-form-last">
      ${group('策略说明',`<input name="description" value="${esc(item.description||'')}" maxlength="240" placeholder="可填写业务场景与配置说明">`)}
      <label class="wm-checkbox"><input type="checkbox" name="enabled" ${item.enabled?'checked':''}>保存后启用此水印策略</label>
      </div></form><aside class="wm-preview-column"><div class="between"><strong>实时效果预览</strong><span class="product-badge">示例信息</span></div>
      <div class="wm-preview-stage" id="watermark-live-preview">${svg(item)}</div>
      <div class="wm-preview-context" id="watermark-preview-context">${context(item)}</div>
      <p class="wm-preview-tip">${icon('info')}预览采用已保存的用户与终端信息，不会对当前电脑施加水印。</p>
      <div class="wm-preview-sample"><span>预览用户</span><strong>${esc(ep.user||'未指定用户')} · ${esc(ep.department||'未指定部门')}</strong><span>终端 IP</span><strong>${esc(ep.ip||'未指定IP')}</strong></div>
      <button type="button" class="btn" data-action="watermark-draft-download">${icon('download')}下载预览 SVG</button>
      </aside></div>`,btn('取消','close')+'<button class="btn primary" type="submit" form="watermark-form">'+icon('check')+'保存水印策略</button>',true);
    document.querySelector('.modal').classList.add('wm-editor-modal');
  }

  function readForm(form,validate=true) {
    const fd=new FormData(form),value={...defaults(),...Object.fromEntries(fd)};
    for (const key of ['fontSize','opacity','angle','spacing','priority']) value[key]=Number(value[key]);
    for (const key of ['enabled','bold','bothSides']) value[key]=fd.has(key);
    value.apps=fd.getAll('apps');value.screenshotMethods=fd.getAll('screenshotMethods');
    if(validate){
      if(!value.content.trim())throw new Error('请填写水印内容');
      if(value.content.split(/\r?\n/).length>4)throw new Error('水印内容最多支持4行');
      if(value.condition==='apps'&&!value.apps.length)throw new Error('请至少选择一个适用应用');
      if(value.type==='screenshot'&&!value.screenshotMethods.length)throw new Error('请至少选择一种截屏方式');
      const unknown=[...value.content.matchAll(/\{([^{}]+)\}/g)].find(m=>!tokens.includes(m[1]));
      if(unknown)throw new Error('不支持的动态字段：'+unknown[0]);
    }
    return value;
  }

  function onInput(target) {
    const form=target.closest?.('#watermark-form');
    if(!form)return;
    const w=readForm(form,false);
    document.querySelectorAll('[data-wm-type]').forEach(e=>e.classList.toggle('hidden',e.dataset.wmType!==w.type));
    document.querySelector('.wm-app-options').classList.toggle('hidden',w.condition!=='apps');
    document.querySelector('.wm-spacing-options').classList.toggle('hidden',w.position!=='tile');
    document.querySelector('#wm-opacity-value').textContent=w.opacity+'%';
    document.querySelector('#wm-angle-value').textContent=w.angle+'°';
    document.querySelector('#wm-color-value').textContent=w.color;
    document.querySelector('#watermark-live-preview').innerHTML=svg(w);
    document.querySelector('#watermark-preview-context').innerHTML=context(w);
  }

  function insertToken(token) {
    const input=document.querySelector('#watermark-content');if(!input||!tokens.includes(token))return;
    const text='{'+token+'}',start=input.selectionStart,end=input.selectionEnd;
    if(input.value.length-(end-start)+text.length>240){toast('水印内容不能超过240个字符',true);return;}
    input.setRangeText(text,start,end,'end');input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();
  }

  function context(w) {
    return `<span class="tag">${icon(types[w.type]?.[1]||'monitor')}${types[w.type]?.[0]||''}</span><span class="tag">${w.type==='print'?esc(w.paperSize)+' · '+(w.bothSides?'双面水印':'单面水印'):w.type==='screen'?(w.screenTarget==='all'?'全部显示器':'主显示器'):'截屏图片'}</span><span class="tag">${conditions[w.condition]}</span>`;
  }

  function sampleLines(w) {
    const state=getState(),ep=state.options.preview||{};const sample={'企业名称':state.settings.company,'姓名':ep.user||'未指定用户','账号':state.user.username,'部门':ep.department||'未指定部门','终端':ep.name||'未指定终端','终端IP':ep.ip||'未指定IP','时间':state.serverTime,'文档名称':'预览文档.pdf'};
    return String(w.content).slice(0,240).replace(/\{([^{}]+)\}/g,(all,key)=>sample[key]??all).split(/\r?\n/).slice(0,4);
  }

  function svg(config) {
    const w={...defaults(),...config},print=w.type==='print',W=print?720:960,H=print?960:600;
    const uid='wm-svg-'+(++previewSequence),font=Math.min(48,Math.max(12,Number(w.fontSize)||20));
    const opacity=Math.min(80,Math.max(5,Number(w.opacity)||5))/100,angle=Math.min(90,Math.max(-90,Number(w.angle)||0));
    const spacing=Math.min(360,Math.max(100,Number(w.spacing)||180)),cellWidth=spacing*2.2;
    const color=/^#[a-f\d]{6}$/i.test(w.color)?w.color:'#66737f',family=['Microsoft YaHei','SimSun','Arial'].includes(w.fontFamily)?w.fontFamily:'Microsoft YaHei';
    const lines=sampleLines(w),lineHeight=font*1.55;
    const text=(x,y)=>`<g transform="rotate(${angle} ${x} ${y})" fill="${color}" opacity="${opacity}"><text text-anchor="middle" font-family="${family}" font-size="${font}" font-weight="${w.bold?700:400}">${lines.map((s,i)=>`<tspan x="${x}" y="${y+(i-(lines.length-1)/2)*lineHeight}">${esc(s)}</tspan>`).join('')}</text></g>`;
    const state=getState(),ep=state.options.preview||{},company=esc(state.settings.company);
    const documentScene=`<rect width="720" height="960" rx="3" fill="white"/><rect x="52" y="45" width="5" height="25" rx="2" fill="#168d78"/><text x="70" y="65" fill="#548573" font-size="17" font-family="sans-serif">${company}</text><text x="52" y="123" fill="#344b42" font-size="27" font-weight="600" font-family="sans-serif">产品项目评审资料</text><text x="52" y="157" fill="#9baaa1" font-size="13" font-family="sans-serif">${esc(ep.department||'未指定部门')} / 内部文件 / ${esc(String(state.serverTime).slice(0,4))}</text><line x1="52" y1="183" x2="668" y2="183" stroke="#e7eeea"/><text x="52" y="231" fill="#697d72" font-size="17" font-family="sans-serif">一、项目概述与实施计划</text>${Array.from({length:8},(_,i)=>`<rect x="52" y="${258+i*26}" width="${i%3===2?462:616}" height="7" rx="3" fill="#e5ece8"/>`).join('')}<rect x="52" y="490" width="616" height="190" rx="5" fill="#f4f8f5"/>${[0,1,2].map((i)=>`<rect x="${83+i*196}" y="525" width="160" height="15" rx="3" fill="#dce9e1"/><rect x="${83+i*196}" y="557" width="130" height="6" rx="3" fill="#e3ece6"/><rect x="${83+i*196}" y="578" width="138" height="6" rx="3" fill="#e3ece6"/>`).join('')}<text x="52" y="735" fill="#697d72" font-size="17" font-family="sans-serif">二、数据使用及保密要求</text>${Array.from({length:4},(_,i)=>`<rect x="52" y="${763+i*26}" width="${i===3?390:616}" height="7" rx="3" fill="#e5ece8"/>`).join('')}<line x1="52" y1="898" x2="668" y2="898" stroke="#e7eeea"/><text x="52" y="925" fill="#a9b4ae" font-size="12" font-family="sans-serif">内部资料 · 请妥善保管</text><text x="640" y="925" fill="#a9b4ae" font-size="12">1 / 3</text>`;
    const screenScene=`<rect width="960" height="600" rx="7" fill="#f5f8f6"/><path d="M0 7a7 7 0 0 1 7-7h946a7 7 0 0 1 7 7v31H0z" fill="#2d5244"/><circle cx="18" cy="19" r="4" fill="#7c9d89"/><circle cx="33" cy="19" r="4" fill="#8faf9b"/><circle cx="48" cy="19" r="4" fill="#afc9b7"/><text x="80" y="24" fill="#cce0d1" font-size="12" font-family="sans-serif">${w.type==='screenshot'?'截屏图片预览':'企业协作空间'} · ${company}</text><rect y="38" width="176" height="562" fill="#fff"/><text x="25" y="82" fill="#416655" font-size="17" font-weight="600" font-family="sans-serif">工作空间</text><rect x="15" y="108" width="146" height="38" rx="5" fill="#e9f3ed"/><text x="31" y="132" fill="#67917a" font-size="13" font-family="sans-serif">项目资料</text>${[0,1,2,3].map(i=>`<rect x="31" y="${177+i*50}" width="${90-i*8}" height="7" rx="3" fill="#e3eae6"/>`).join('')}<rect x="201" y="64" width="733" height="508" rx="7" fill="#fff"/><text x="230" y="108" fill="#3c5c4b" font-size="21" font-weight="600" font-family="sans-serif">产品项目评审</text><text x="230" y="136" fill="#a2afa6" font-size="12" font-family="sans-serif">${esc(ep.user||'未指定用户')} · ${esc(ep.department||'未指定部门')} · 项目文档</text><rect x="230" y="165" width="675" height="68" rx="5" fill="#edf5ef"/><text x="250" y="192" fill="#6e927b" font-size="13" font-family="sans-serif">项目概述</text><rect x="250" y="207" width="505" height="6" rx="3" fill="#d8e7dc"/>${Array.from({length:9},(_,i)=>`<rect x="230" y="${264+i*26}" width="${i%4===3?480:675}" height="7" rx="3" fill="#e5ece7"/>`).join('')}<rect x="230" y="522" width="106" height="27" rx="4" fill="#e4f1e9"/><text x="250" y="540" fill="#789c84" font-size="11" font-family="sans-serif">内部协作资料</text>`;
    const y=w.position==='top'?font*2+lines.length*lineHeight/2:w.position==='bottom'?H-font*2-lines.length*lineHeight/2:H/2;
    return `<svg class="wm-preview-svg" xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${types[w.type]?.[0]||'水印'}效果预览"><defs><pattern id="${uid}" width="${cellWidth}" height="${spacing}" patternUnits="userSpaceOnUse">${text(cellWidth/2,spacing/2)}</pattern><clipPath id="${uid}-clip"><rect width="${W}" height="${H}" rx="${print?3:7}"/></clipPath></defs><g clip-path="url(#${uid}-clip)">${print?documentScene:screenScene}${w.position==='tile'?`<rect width="${W}" height="${H}" fill="url(#${uid})"/>`:text(W/2,y)}</g></svg>`;
  }

  async function preview(id) {
    const w=await ensureDetail('watermarks',id);if(!w)return;
    modal('水印效果预览',`<div class="wm-preview-heading"><div><h3>${esc(w.name)}</h3><p>${esc(w.scope)} · ${conditions[w.condition]} · 优先级 ${w.priority}</p></div>${badge(w.enabled?'resolved':'offline',w.enabled?'已启用':'已停用')}</div>
      <div class="wm-standalone-preview">${svg(w)}</div><div class="wm-preview-context">${context(w)}</div><p class="wm-preview-tip">${icon('info')}示例水印使用已保存的用户信息；预览与已保存的内容、字体、布局及透明度保持一致。</p>`,
      btn('关闭','close')+btn('下载预览','watermark-download','download','',`data-id="${esc(id)}"`)+btn('编辑配置','watermark-edit','edit','primary',`data-id="${esc(id)}"`),true);
  }

  function downloadPreview(id) {
    let w;
    if(id)w=getState().watermarks.find(w=>w.id===id);
    else {const form=document.querySelector('#watermark-form');if(form)w=readForm(form);}
    if(!w)return;
    download((w.name||types[w.type][0])+'-预览.svg',svg(w),'image/svg+xml;charset=utf-8');
    toast('水印预览已下载');
  }

  return {getTab:()=>tab,render,form,readForm,onInput,insertToken,preview,downloadPreview,setTab:value=>{tab=value in types?value:'all';}};
}
