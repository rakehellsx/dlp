import {sha256Hex} from './auth.js';

export function createUserModule({getState,esc,icon,btn,link,badge,heading,table,empty,filterInput,filterSelect,pagination,modal,close,api,refreshAfter}) {
  function render() {
    const s=getState();
    if(s.user.role!=='admin')return heading('用户管理','管理控制台账号与登录权限')+empty('需要管理员权限','请使用管理员账号访问用户管理');
    const stats=s.listing.stats;
    const cards=[['全部用户',stats.total,'users','blue'],['已启用',stats.enabled,'check',''],['已禁用',stats.disabled,'lock','amber'],['管理员',stats.admins,'shield','blue']];
    return heading('用户管理','统一管理控制台账号、角色与登录权限',btn('新增用户','user-new','plus','primary'))+
      `<div class="stats-grid">${cards.map(([title,value,ico,color])=>`<section class="stat-card"><div class="stat-top"><span>${title}</span><span class="stat-icon ${color}">${icon(ico)}</span></div><div class="stat-number">${value}<small>人</small></div></section>`).join('')}</div>`+
      `<div class="info-banner">${icon('info')}禁用用户会立即撤销其登录会话；重新启用后，该用户可再次登录。当前登录账号不能被删除或禁用。</div>`+
      `<section class="panel"><div class="toolbar">${filterInput('搜索用户名')}${filterSelect('role',[['admin','管理员'],['user','普通用户']],'全部角色')}${filterSelect('status',[['enabled','已启用'],['disabled','已禁用']],'全部状态')}<span class="grow"></span>${btn('重置','reset','refresh')}</div>`+
      (s.users.length?table(['用户名','角色','账号状态','创建时间（北京时间）','操作'],s.users.map(u=>`<tr><td><div class="cell-person"><div class="avatar">${esc(u.username.slice(-1))}</div><div class="cell-title">${esc(u.username)}${u.username===s.user.username?' <span class="tag">当前账号</span>':''}</div></div></td><td>${badge(u.role==='admin'?'processing':'low',u.role==='admin'?'管理员':'普通用户')}</td><td>${badge(u.disabled?'offline':'online',u.disabled?'已禁用':'已启用')}</td><td class="mono">${esc(u.created_at)}</td><td>${u.username===s.user.username?'<span class="muted">当前登录账号</span>':`${link(u.disabled?'启用':'禁用','user-status',`data-id="${u.id}"`)} ${link('删除','user-delete',`data-id="${u.id}"`)}`}</td></tr>`)):empty())+pagination()+'</section>';
  }
  function createForm() {
    modal('新增用户',`<form id="user-create-form" data-form="user-create"><div class="form-group"><label for="new-user-name">用户名<span class="required">*</span></label><input id="new-user-name" name="username" required maxlength="64" autocomplete="off" placeholder="请输入用户名"></div><div class="form-group"><label for="new-user-role">用户角色</label><select id="new-user-role" name="role"><option value="user">普通用户</option><option value="admin">管理员</option></select><p class="form-note">管理员可以管理用户并修改系统配置；普通用户可查看业务数据。</p></div><div class="form-group"><label for="new-user-password">初始密码<span class="required">*</span></label><input id="new-user-password" name="password" type="password" required minlength="8" maxlength="128" autocomplete="new-password" placeholder="至少 8 个字符"></div><div class="form-group"><label for="new-user-confirm">确认密码<span class="required">*</span></label><input id="new-user-confirm" name="confirm" type="password" required minlength="8" maxlength="128" autocomplete="new-password" placeholder="再次输入初始密码"></div></form>`,btn('取消','close')+'<button class="btn primary" type="submit" form="user-create-form">创建用户</button>');
  }
  function confirm(action,id) {
    const u=getState().users.find(u=>String(u.id)===id);
    if(!u)throw new Error('用户不存在，请刷新列表');
    const deleting=action==='user-delete',disabled=!u.disabled,label=deleting?'删除':disabled?'禁用':'启用';
    modal(label+'用户',`<form id="user-action-form" data-form="user-action"><input type="hidden" name="username" value="${esc(u.username)}"><input type="hidden" name="operation" value="${deleting?'delete':'disable'}"><input type="hidden" name="disabled" value="${disabled}"><p>确认${label}用户 <strong>${esc(u.username)}</strong>？</p><p class="muted">${deleting?'删除后该账号将无法登录，已有登录会话会被清除，历史审计记录保留。':disabled?'该用户将立即退出登录，并且无法再次登录。':'该用户可使用原密码重新登录。'}</p></form>`,btn('取消','close')+`<button class="btn ${deleting||disabled?'danger':'primary'}" type="submit" form="user-action-form">确认${label}</button>`);
  }
  async function submit(form) {
    const v=Object.fromEntries(new FormData(form));
    let result;
    if(form.dataset.form==='user-create'){
      const username=v.username.trim();
      if(!username)throw new Error('请输入用户名');
      if(new TextEncoder().encode(username).length>64)throw new Error('用户名不能超过 64 字节');
      if(v.password.length<8)throw new Error('初始密码至少需要 8 个字符');
      if(v.password!==v.confirm)throw new Error('两次输入的密码不一致');
      result=await api('user/create',{username,role:v.role,password_hash:await sha256Hex(v.password)});
    }else{
      result=await api('user/'+v.operation,{username:v.username,...(v.operation==='disable'?{disabled:v.disabled==='true'}:{})});
    }
    close();await refreshAfter(result.msg||'用户已创建');
  }
  return {render,createForm,confirm,submit};
}
