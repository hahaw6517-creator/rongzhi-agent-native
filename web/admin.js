'use strict';
// 管理后台：与主站共用 JWT（用户名+密码+图形验证码，仅 role=1 可进），
// 维护平台托管模型与 AI 供应商注册表；密钥加密存储、仅显示掩码、编辑留空保留原密钥。
// 布局与主站同构：左侧品牌侧边栏 + 右侧内容区（移动端抽屉化）；
// 平台托管模型表单复用 model-picker.js，与前台「模型设置」同一套字段与交互。
const app=document.querySelector('#admin-app');
const TOKEN_KEY='finbridge_token',USER_KEY='finbridge_user';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// 品牌标（与主站 favicon / 侧边栏一致，修复此前误用的字母方块）
const BRAND_MARK='<svg viewBox="0 0 30 30" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M8 23V7h17M8 15h13M16 23v-8"/></svg>';
const AICONS={
  menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
  chevron:'<path d="m9 18 6-6-6-6"/>',
  lock:'<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>',
  arrow:'<path d="M5 12h14m-7-7 7 7-7 7"/>',
  check:'<path d="M20 6 9 17l-5-5"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  close:'<path d="M18 6 6 18M6 6l12 12"/>',
  users:'<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>'
};
const ico=(name,cls='')=>`<svg class="icon ${cls}" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${AICONS[name]||''}</svg>`;
let user=null,captcha=null,models=[],providers=[],users=[],section='platform',adminMobile=false,busy=false;
// 后台侧边栏桌面收缩态（独立于主站的持久化键；移动端仍走抽屉）
let adminSb=(()=>{try{return localStorage.getItem('finbridge_admin_sb')==='1';}catch{return false;}})();
// 平台托管模型表单状态：pmMode=null|'pick'|'form'；pmEditing=编辑中的 id；pmForm=共享表单数据
let pmMode=null,pmEditing=null,pmForm=null;
// 供应商表单状态：pvMode=null|'form'；editingProvider=编辑中的 id；pvForm=表单草稿
let pvMode=null,editingProvider=null,pvForm=null;

function token(){try{return localStorage.getItem(TOKEN_KEY)||'';}catch{return '';}}
function saveSession(data){try{localStorage.setItem(TOKEN_KEY,data.token);localStorage.setItem(USER_KEY,JSON.stringify(data.user));}catch{}user=data.user;}
function clearSession(){try{localStorage.removeItem(TOKEN_KEY);localStorage.removeItem(USER_KEY);}catch{}user=null;}

async function api(url,options={}){
  const headers=options.body?{'Content-Type':'application/json'}:{};
  const current=token();
  if(current)headers['Authorization']='Bearer '+current;
  const response=await fetch(url,{headers,method:options.method||'GET',body:options.body?JSON.stringify(options.body):undefined,credentials:'same-origin'});
  const contentType=response.headers.get('content-type')||'';
  const data=contentType.includes('json')?await response.json():null;
  if(!response.ok){
    if(response.status===401&&user){clearSession();render();toast('登录已过期，请重新登录。');}
    throw new Error(data?.detail||data?.error||data?.message||'请求未完成，请稍后重试。');
  }
  return data;
}
function toast(text){const t=document.querySelector('#toast');t.textContent=text;t.classList.add('visible');clearTimeout(toast._t);toast._t=setTimeout(()=>t.classList.remove('visible'),3800);}

async function loadCaptcha(){
  try{captcha=await api('/api/auth/captcha');}
  catch(err){captcha=null;toast(err.message);}
  document.querySelector('#captcha-img')?.setAttribute('src',captcha?captcha.imageBase64:'');
}

// ---- 登录视图（复刻模板：用户名 + 密码 + 图形验证码；品牌标与主站一致） ----
function loginView(){
  return `<div class="admin-wrap"><div class="card login-card">
  <div class="admin-top"><span class="brand-mark">${BRAND_MARK}</span><div><h1 style="margin:0;font-size:20px">管理后台</h1><p class="subtle-caption" style="margin:2px 0 0">融智 FinBridge · 管理员登录</p></div></div>
  <form id="login-form" style="margin-top:18px">
    <div class="field"><label for="username">用户名</label><input id="username" name="username" required maxlength="32" autocomplete="username" placeholder="管理员用户名"></div>
    <div class="field"><label for="password">密码</label><input id="password" name="password" type="password" required maxlength="64" autocomplete="current-password" placeholder="登录密码"></div>
    <div class="field"><label for="captcha-code">图形验证码</label>
      <div class="captcha-row"><input id="captcha-code" name="captchaCode" required maxlength="8" autocomplete="off" placeholder="区分大小写">
      <img id="captcha-img" class="captcha-img" alt="验证码，点击刷新" title="点击刷新" src="${captcha?esc(captcha.imageBase64):''}"></div></div>
    <div class="form-actions"><button type="submit" class="btn primary" style="width:100%">登录管理后台</button></div>
    <div id="login-error" class="form-error" role="alert"></div>
    <p class="subtle-caption">仅管理员账号（role=1）可进入。默认账号由部署时 ADMIN_PASSWORD 环境变量播种；普通用户登录将提示无权限。</p>
  </form></div></div>`;
}

// ---- 平台托管模型板块：表单复用共享组件（与前台模型设置同交互） ----
function platformSection(){
  const list=models.length?models.map(m=>`<div class="model-item ${m.enabled?'sel':''}"><div class="model-item-main">
    <strong>${esc(m.name)}</strong>${m.enabled?'<span class="badge green">启用</span>':'<span class="badge">停用</span>'}${m.isDefault?'<span class="badge green">默认生效</span>':''}
    <small>${esc(m.modelId)} · ${mpProtocolText(m.protocol)} · ${esc(m.baseUrl)}</small>
    <small>密钥 ${m.hasKey?esc(m.keyMasked):'未配置'}</small></div>
    <div class="model-item-ops"><button class="btn ghost small" data-mact="test" data-id="${m.id}" ${busy?'disabled':''}>测试</button>
    <button class="btn ghost small" data-mact="edit" data-id="${m.id}">编辑</button>
    <button class="btn ghost small" data-mact="delete" data-id="${m.id}" ${busy?'disabled':''}>删除</button></div></div>`).join('')
    :`<p class="subtle-caption">还没有平台托管模型。添加并启用后，未自配模型的用户将使用这里的配置运行 AI 环节。</p>`;
  let form='';
  if(pmMode==='pick'){
    form=`<div class="admin-form-card"><div class="cfg-group-head"><h3>选择供应商</h3><small>与用户侧「模型设置」同一套供应商注册表。</small></div>
    ${mpProvGrid(providers,'pm')}
    <div class="form-actions"><button type="button" class="btn" data-action="pm-cancel">取消</button></div></div>`;
  }else if(pmMode==='form'){
    const provider=providers.find(p=>p.providerKey===pmForm.provider);
    form=`<div class="admin-form-card"><div class="cfg-group-head"><h3>${pmEditing?'编辑平台托管模型':'添加平台托管模型'}</h3><small>密钥加密存储、仅显示掩码。</small></div>
    ${mpFormHtml(pmForm,provider,{mode:pmEditing?'edit':'add',prefix:'pm',submitText:pmEditing?'保存修改':'添加模型',
      firstColHtml:`<label class="field"><span>配置名称</span><input name="name" required maxlength="64" placeholder="如 平台默认模型" value="${esc(pmForm.name||'')}"></label>`,
      afterHtml:`<div class="fields-row"><label class="field"><span>排序序号</span><input name="sortOrder" type="number" step="1" value="${esc(pmForm.sortOrder??0)}"></label>
      <label class="field"><span>状态</span><label class="check-row"><input name="enabled" type="checkbox" ${pmForm.enabled!==false?'checked':''}> 启用（未自配模型的用户将使用此配置）</label></label></div>`})}
    </div>`;
  }
  return `<section class="admin-section"><div class="admin-section-head"><div><h2 class="section-title">平台托管模型</h2>
  <p class="subtle-caption">由平台统一配置密钥；用户在「模型设置」中一键选用、免配置。</p></div>
  ${pmMode?'':`<button class="btn primary small" data-action="pm-add">${ico('plus')}添加模型</button>`}</div>
  <div class="model-list">${list}</div>${form}</section>`;
}

// ---- AI 供应商板块 ----
function providerSection(){
  const list=providers.length?providers.map(p=>`<div class="model-item ${p.enabled?'sel':''}"><div class="model-item-main">
    <strong>${esc(p.name)}</strong><span class="badge">${esc(p.providerKey)}</span>${p.enabled?'<span class="badge green">启用</span>':'<span class="badge">停用</span>'}
    <small>${mpProtocolText(p.protocol)} · ${esc(p.baseUrl)||'未配置地址'}</small></div>
    <div class="model-item-ops"><button class="btn ghost small" data-pact="edit" data-id="${p.id}">编辑</button>
    <button class="btn ghost small" data-pact="delete" data-id="${p.id}" ${busy?'disabled':''}>删除</button></div></div>`).join('')
    :`<p class="subtle-caption">还没有供应商。用户在前台「模型设置」添加自配模型时从这里选择。</p>`;
  const p=pvForm;
  const form=p?`<div class="admin-form-card"><div class="cfg-group-head"><h3>${editingProvider?'编辑供应商':'添加供应商'}</h3><small>停用后用户侧不可见。</small></div>
  <form id="provider-form">
    <div class="fields-row">
      <label class="field"><span>供应商名称</span><input name="name" required maxlength="64" placeholder="如 DeepSeek" value="${esc(p.name)}"></label>
      <label class="field"><span>供应商标识</span><input name="providerKey" required maxlength="32" pattern="[a-z0-9_]{2,32}" placeholder="小写字母/数字/下划线，如 deepseek" value="${esc(p.providerKey)}"></label>
    </div>
    <div class="fields-row"><label class="field"><span>接口类型</span>${uiSelect('protocol',[['openai','OpenAI 兼容格式'],['anthropic','Anthropic 格式']],p.protocol)}</label><label class="field"><span>接口地址</span><input name="baseUrl" maxlength="255" placeholder="https://api.deepseek.com" value="${esc(p.baseUrl)}"></label></div>
    <div class="fields-row">
      <label class="field"><span>控制台链接</span><input name="consoleUrl" maxlength="255" placeholder="https://platform.deepseek.com" value="${esc(p.consoleUrl)}"></label>
      <label class="field"><span>模型文档链接</span><input name="modelDocUrl" maxlength="255" placeholder="https://api-docs.deepseek.com" value="${esc(p.modelDocUrl)}"></label>
    </div>
    <div class="fields-row"><label class="field"><span>排序序号</span><input name="sortOrder" type="number" step="1" value="${esc(p.sortOrder??0)}"></label>
    <label class="field"><span>状态</span><label class="check-row"><input name="enabled" type="checkbox" ${p.enabled!==false?'checked':''}> 启用（用户添加模型时可见）</label></label></div>
    <div class="form-actions"><button type="submit" class="btn primary">${ico('check')}${editingProvider?'保存修改':'添加供应商'}</button><button type="button" class="btn" data-action="pv-cancel">取消</button></div>
    <div id="provider-error" class="form-error" role="alert"></div>
  </form></div>`:'';
  return `<section class="admin-section"><div class="admin-section-head"><div><h2 class="section-title">AI 供应商管理</h2>
  <p class="subtle-caption">用户添加自配模型时可选的供应商注册表；平台托管模型也复用这里的接口地址。</p></div>
  ${p?'':`<button class="btn primary small" data-action="pv-add">${ico('plus')}添加供应商</button>`}</div>
  <div class="model-list">${list}</div>${form}</section>`;
}

// ---- 用户管理板块：账户清单 + 重置密码 / 禁用启用 / 删除 ----
function fmtTime(ts){if(!ts)return '—';const d=new Date(ts*1000);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;}

function usersSection(){
  const rows=users.length?users.map(u=>`<tr>
    <td><strong>${esc(u.username)}</strong>${u.id===user?.id?'<span class="badge blue">当前登录</span>':''}</td>
    <td>${esc(u.nickname||'—')}</td>
    <td>${u.role===1?'<span class="badge green">管理员</span>':'<span class="badge">用户</span>'}</td>
    <td>${u.disabled?'<span class="badge red">已禁用</span>':'<span class="badge green">正常</span>'}</td>
    <td>${u.runs}</td>
    <td>${fmtTime(u.created)}</td>
    <td>${fmtTime(u.lastLogin)}</td>
    <td><div class="model-item-ops">
      <button class="btn ghost small" data-uact="reset" data-id="${u.id}" ${busy?'disabled':''}>重置密码</button>
      <button class="btn ghost small" data-uact="status" data-id="${u.id}" data-disabled="${u.disabled?0:1}" ${busy?'disabled':''}>${u.disabled?'启用':'禁用'}</button>
      <button class="btn ghost small" data-uact="delete" data-id="${u.id}" data-name="${esc(u.username)}" ${busy?'disabled':''}>删除</button>
    </div></td></tr>`).join('')
    :'<tr><td colspan="8" class="subtle-caption">暂无账户。</td></tr>';
  return `<section class="admin-section"><div class="admin-section-head"><div><h2 class="section-title">用户管理</h2>
  <p class="subtle-caption">全部注册账户；禁用后立即无法登录与调用接口，删除将同时清理该账户的历史分析、自配模型与问答记录。</p></div>
  <button class="btn small" data-action="users-refresh" ${busy?'disabled':''}>${ico('arrow')}刷新列表</button></div>
  <div class="data-scroll"><table class="data-table"><thead><tr>
    <th>用户名</th><th>昵称</th><th>角色</th><th>状态</th><th>历史分析</th><th>注册时间</th><th>最近登录</th><th>操作</th>
  </tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

// ---- 整体布局：品牌侧边栏 + 内容区（与主站同构；移动端抽屉化） ----
function adminView(){
  const titles={platform:['平台托管模型','平台托管模型与 AI 供应商注册表'],providers:['AI 供应商','平台托管模型与 AI 供应商注册表'],users:['用户管理','全部注册账户与状态管理']};
  const current=titles[section]||titles.platform;
  return `<div class="admin-shell">
  <div class="admin-scrim ${adminMobile?'visible':''}" data-action="admin-menu-close"></div>
  <aside class="admin-side ${adminMobile?'open':''}" id="admin-nav" aria-label="管理后台导航">
    <a class="brand" href="/"><span class="brand-mark">${BRAND_MARK}</span><span><span class="brand-name">融智 FinBridge</span><span class="brand-sub">管理后台</span></span></a>
    <div class="nav-label">平台管理</div>
    <nav>
      <button type="button" class="nav-link ${section==='platform'?'active':''}" data-action="admin-section" data-section="platform" ${section==='platform'?'aria-current="page"':''}>${ico('lock')}平台托管模型</button>
      <button type="button" class="nav-link ${section==='providers'?'active':''}" data-action="admin-section" data-section="providers" ${section==='providers'?'aria-current="page"':''}>${ico('shield')}AI 供应商</button>
      <button type="button" class="nav-link ${section==='users'?'active':''}" data-action="admin-section" data-section="users" ${section==='users'?'aria-current="page"':''}>${ico('users')}用户管理</button>
    </nav>
    <div class="admin-side-foot">
      <a class="btn ghost small" href="/" target="_blank" rel="noopener">${ico('arrow')}<span>打开工作台</span></a>
      <button class="btn small" id="logout"><span>退出登录</span></button>
    </div>
  </aside>
  <main class="admin-main">
    <header class="admin-topbar">
      <button class="icon-btn menu-btn" data-action="admin-menu" aria-label="${adminSb&&!adminMobile?'展开导航':'收起导航'}" aria-expanded="${String(adminMobile||!adminSb)}" aria-controls="admin-nav">${ico('menu')}</button>
      <div class="breadcrumbs"><span>管理后台</span>${ico('chevron')}<b>${current[0]}</b></div>
      <div class="admin-user">${ico('lock')}<span>${esc(user?.nickname||user?.username||'管理员')}</span><span class="badge blue">管理员</span></div>
    </header>
    <div class="admin-content">
      ${section==='platform'?platformSection():section==='users'?usersSection():providerSection()}
      <p class="subtle-caption admin-foot-note">连通性测试以 1 个 token 的最小补全验证地址、密钥与模型名；所有 AI 调用优先级：用户自配 → 平台托管 → 环境变量。</p>
    </div>
  </main>
  </div>`;
}

function render(){
  document.body.classList.toggle('admin-collapsed',adminSb);
  app.innerHTML=user?adminView():loginView();
  if(!user){loadCaptcha();bindLogin();return;}
  bindAdmin();
}

// ---- 登录交互 ----
function bindLogin(){
  document.querySelector('#captcha-img')?.addEventListener('click',loadCaptcha);
  document.querySelector('#login-form')?.addEventListener('submit',async ev=>{
    ev.preventDefault();
    const error=document.querySelector('#login-error'),button=ev.currentTarget.querySelector('[type=submit]');
    button.disabled=true;error.textContent='';
    try{
      const data=await api('/api/auth/login',{method:'POST',body:{
        username:document.querySelector('#username').value.trim(),
        password:document.querySelector('#password').value,
        captchaId:captcha?captcha.captchaId:'',
        captchaCode:document.querySelector('#captcha-code').value.trim()}});
      if(data.user.role!==1){clearSession();captcha=null;render();document.querySelector('#login-error').textContent='需要管理员权限';return;}
      saveSession(data);pmMode=null;pmEditing=null;pmForm=null;pvMode=null;editingProvider=null;pvForm=null;await refreshAll();render();toast('欢迎回来，'+(data.user.nickname||data.user.username)+'。');
    }catch(err){
      captcha=null;render(); // 验证码一次性消费，失败后必须换图重填；render 重建 DOM 后再写入错误
      document.querySelector('#login-error').textContent=err.message;
    }finally{button.disabled=false;}
  });
}

// ---- 管理交互 ----
async function refreshAll(){
  const [m,p,u]=await Promise.all([api('/api/admin/platform-models'),api('/api/admin/ai-providers'),api('/api/admin/users')]);
  models=m.list;providers=p.list;users=u.list||[];
}

function resetPm(){pmMode=null;pmEditing=null;pmForm=null;}
function resetPv(){pvMode=null;editingProvider=null;pvForm=null;}

function bindAdmin(){
  document.querySelector('#logout')?.addEventListener('click',()=>{clearSession();resetPm();resetPv();render();});
  document.querySelectorAll('[data-action=admin-section]').forEach(el=>el.addEventListener('click',()=>{
    section=el.dataset.section;adminMobile=false;resetPm();resetPv();render();window.scrollTo({top:0,behavior:'instant'});
  }));
  document.querySelector('[data-action=admin-menu]')?.addEventListener('click',()=>{
    // 对标主站：桌面端左上角按钮收起/展开侧边栏（窄条图标态），移动端仍是抽屉导航
    if(window.matchMedia('(max-width:760px)').matches){adminMobile=!adminMobile;render();}
    else{adminSb=!adminSb;try{localStorage.setItem('finbridge_admin_sb',adminSb?'1':'0');}catch{}render();}
  });
  document.querySelector('[data-action=admin-menu-close]')?.addEventListener('click',()=>{adminMobile=false;render();});
  // 用户管理：重置密码 / 禁用启用 / 删除 / 刷新
  document.querySelector('[data-action=users-refresh]')?.addEventListener('click',async()=>{busy=true;render();try{await refreshAll();}catch(err){toast(err.message);}finally{busy=false;}render();});
  app.querySelectorAll('[data-uact]').forEach(el=>el.addEventListener('click',async ev=>{
    const id=Number(el.dataset.id),act=el.dataset.uact,target=users.find(x=>x.id===id);
    if(act==='reset'){
      const pwd=await uiPrompt({title:`重置 ${target?.username||'该账户'} 的密码`,message:'请输入新密码，重置后请通知该用户使用新密码登录。',placeholder:'新密码（至少 6 位）',type:'password',required:true,minlength:6,confirmText:'重置密码'});
      if(pwd===null)return;
      busy=true;render();try{await api(`/api/admin/users/${id}/reset-password`,{method:'POST',body:{password:pwd}});toast('密码已重置。');}catch(err){toast(err.message);}finally{busy=false;}render();return;
    }
    if(act==='status'){
      const disable=el.dataset.disabled==='1';
      if(disable&&!(await uiConfirm({title:'禁用该账户？',message:'禁用后该用户将立即无法登录与调用接口；启用后恢复。',confirmText:'禁用',danger:true})))return;
      busy=true;render();try{await api(`/api/admin/users/${id}/status`,{method:'POST',body:{disabled:disable}});await refreshAll();toast(disable?'账户已禁用。':'账户已启用。');}catch(err){toast(err.message);}finally{busy=false;}render();return;
    }
    if(act==='delete'){
      if(!(await uiConfirm({title:`删除账户 ${target?.username||''} ？`,message:'将同时删除该账户的历史分析、自配模型与问答记录，操作不可恢复。',confirmText:'删除',danger:true})))return;
      busy=true;render();try{await api(`/api/admin/users/${id}`,{method:'DELETE'});await refreshAll();toast('账户已删除。');}catch(err){toast(err.message);}finally{busy=false;}render();return;
    }
  }));
  // 平台托管模型：添加（选供应商 → 共享表单）/ 编辑 / 删除 / 测试
  document.querySelector('[data-action=pm-add]')?.addEventListener('click',()=>{resetPm();pmMode='pick';render();});
  app.querySelectorAll('[data-action=pm-pick]').forEach(el=>el.addEventListener('click',()=>{
    const p=providers.find(x=>x.providerKey===el.dataset.provider);if(!p)return;
    pmMode='form';pmEditing=null;pmForm={provider:p.providerKey,protocol:p.protocol,baseUrl:p.baseUrl,modelId:'',name:'',sortOrder:0,enabled:true};render();
  }));
  app.querySelectorAll('[data-action=pm-repick]').forEach(el=>el.addEventListener('click',()=>{pmMode='pick';render();}));
  document.querySelector('[data-action=pm-cancel]')?.addEventListener('click',()=>{resetPm();render();});
  app.querySelectorAll('[data-mact]').forEach(el=>el.addEventListener('click',async ev=>{
    const id=Number(el.dataset.id),act=el.dataset.mact;
    if(act==='edit'){const m=models.find(x=>x.id===id);if(!m)return;resetPv();pmMode='form';pmEditing=id;
      pmForm={provider:m.provider||'',protocol:m.protocol,baseUrl:m.baseUrl,modelId:m.modelId,name:m.name,sortOrder:m.sortOrder,enabled:m.enabled};render();return;}
    if(act==='delete'){
      if(!(await uiConfirm({title:'删除该平台托管模型？',message:'已选用它的用户将回落到自配或环境变量。',confirmText:'删除',danger:true})))return;
      busy=true;render();try{await api(`/api/admin/platform-models/${id}`,{method:'DELETE'});await refreshAll();toast('已删除。');}catch(err){toast(err.message);}finally{busy=false;}render();return;
    }
    if(act==='test'){el.disabled=true;el.textContent='测试中…';try{await api(`/api/admin/platform-models/${id}/test`,{method:'POST'});toast('连通性测试通过，该模型可正常调用。');}catch(err){toast(err.message);}finally{el.disabled=false;el.textContent='测试';}}
  }));
  // 平台模型表单：值由共享 mpCollect 收集，另带后台专属的名称 / 排序 / 启用
  document.querySelector('#model-form')?.addEventListener('submit',async ev=>{
    ev.preventDefault();
    const form=ev.currentTarget,error=document.querySelector('#model-error'),button=form.querySelector('[type=submit]');
    button.disabled=true;busy=true;
    const collected=mpCollect(form);
    const body={...collected,name:form.querySelector('[name=name]').value.trim(),
      enabled:form.querySelector('[name=enabled]')?.checked??true,
      sortOrder:Number(form.querySelector('[name=sortOrder]')?.value)||0};
    try{
      if(pmEditing)await api(`/api/admin/platform-models/${pmEditing}`,{method:'PUT',body});
      else await api('/api/admin/platform-models',{method:'POST',body});
      resetPm();await refreshAll();toast('平台模型配置已保存。');
    }catch(err){error.textContent=err.message;}
    finally{button.disabled=false;busy=false;}render();
  });
  // 供应商：添加 / 编辑 / 删除
  document.querySelector('[data-action=pv-add]')?.addEventListener('click',()=>{resetPv();pvMode='form';pvForm={name:'',providerKey:'',protocol:'openai',baseUrl:'',consoleUrl:'',modelDocUrl:'',sortOrder:0,enabled:true};render();});
  document.querySelector('[data-action=pv-cancel]')?.addEventListener('click',()=>{resetPv();render();});
  app.querySelectorAll('[data-pact]').forEach(el=>el.addEventListener('click',async ev=>{
    const id=Number(el.dataset.id),act=el.dataset.pact;
    if(act==='edit'){const p=providers.find(x=>x.id===id);if(!p)return;resetPm();pvMode='form';editingProvider=id;
      pvForm={name:p.name,providerKey:p.providerKey,protocol:p.protocol,baseUrl:p.baseUrl,consoleUrl:p.consoleUrl,modelDocUrl:p.modelDocUrl,sortOrder:p.sortOrder,enabled:p.enabled};render();return;}
    if(act==='delete'){
      if(!(await uiConfirm({title:'删除该供应商？',message:'仅影响用户后续新增模型的可选项。',confirmText:'删除',danger:true})))return;
      busy=true;render();try{await api(`/api/admin/ai-providers/${id}`,{method:'DELETE'});await refreshAll();toast('已删除。');}catch(err){toast(err.message);}finally{busy=false;}render();return;
    }
  }));
  document.querySelector('#provider-form')?.addEventListener('submit',async ev=>{
    ev.preventDefault();
    const form=ev.currentTarget,error=document.querySelector('#provider-error'),button=form.querySelector('[type=submit]');
    button.disabled=true;busy=true;
    const body={name:form.querySelector('[name=name]').value.trim(),providerKey:form.querySelector('[name=providerKey]').value.trim(),
      protocol:form.querySelector('[name=protocol]').value,baseUrl:form.querySelector('[name=baseUrl]').value.trim(),
      consoleUrl:form.querySelector('[name=consoleUrl]').value.trim(),modelDocUrl:form.querySelector('[name=modelDocUrl]').value.trim(),
      enabled:form.querySelector('[name=enabled]').checked,sortOrder:Number(form.querySelector('[name=sortOrder]').value)||0};
    try{
      if(editingProvider)await api(`/api/admin/ai-providers/${editingProvider}`,{method:'PUT',body});
      else await api('/api/admin/ai-providers',{method:'POST',body});
      resetPv();await refreshAll();toast('供应商已保存。');
    }catch(err){error.textContent=err.message;}
    finally{button.disabled=false;busy=false;}render();
  });
}

window.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||!adminMobile)return;
  adminMobile=false;render();
});

(async()=>{ // 进入页面先校验本地 JWT：有效且 role=1 直接进管理页，否则回到登录
  const current=token();
  if(current){
    try{
      const me=await api('/api/auth/me');
      if(me.user.role===1){user=me.user;await refreshAll();}
      else{clearSession();toast('需要管理员权限');}
    }catch{clearSession();}
  }
  render();
})();
