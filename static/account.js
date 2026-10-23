import {sha256Hex} from './auth.js';

export function createAccountModule({getState,esc,icon,btn,modal,api,onChanged}) {
  function form() {
    modal('修改密码',`<form id="change-password-form" data-form="change-password"><div class="info-banner">${icon('lock')}正在修改 ${esc(getState().user.username)} 的密码。修改成功后所有登录会话将退出，请使用新密码重新登录。</div><input type="text" name="username" value="${esc(getState().user.username)}" autocomplete="username" hidden><div class="form-group"><label for="current-password">当前密码<span class="required">*</span></label><input id="current-password" name="current" type="password" autocomplete="current-password" required maxlength="128" placeholder="请输入当前密码"></div><div class="form-group"><label for="new-password">新密码<span class="required">*</span></label><input id="new-password" name="password" type="password" autocomplete="new-password" required minlength="8" maxlength="128" placeholder="8–128 个字符"></div><div class="form-group"><label for="confirm-password">确认新密码<span class="required">*</span></label><input id="confirm-password" name="confirm" type="password" autocomplete="new-password" required minlength="8" maxlength="128" placeholder="再次输入新密码"></div><div id="change-password-error" class="login-error" role="alert" aria-live="polite"></div></form>`,btn('取消','close')+'<button class="btn primary" form="change-password-form" type="submit">确认修改</button>');
  }
  async function submit(form) {
    const v=Object.fromEntries(new FormData(form)),error=form.querySelector('[role=alert]');
    error.textContent='';
    try {
      if(!v.current)throw new Error('请输入当前密码');
      if(v.password.length<8||v.password.length>128)throw new Error('新密码长度应为 8–128 个字符');
      if(v.current===v.password)throw new Error('新密码不能与当前密码相同');
      if(v.password!==v.confirm)throw new Error('两次输入的新密码不一致');
      const result=await api('user/change_password',{old_password_hash:await sha256Hex(v.current),new_password_hash:await sha256Hex(v.password)});
      onChanged(result.msg);
    }catch(e){error.textContent=e.message;}
  }
  return {form,submit};
}
