'use strict';

const repaymentHelp = "CFADS＝每年真正可用于还本付息的现金；DSCR＝这笔现金÷未来12个月已有及新增债务应还本息。比如DSCR为1.20倍，就是每还100元有120元还款现金；利润和账上现金不能直接代替CFADS。";
const stressHelp = "红色虚线是本项目设定的还款安全线1.20倍（不是银行统一审批标准）；每根柱子表示一种情景下的还款覆盖倍数。绿色≥1.20，黄色在1.00至1.20之间、余量偏薄，红色<1.00、现金不足以还本付息。";
const cashGapHelp = "“达到目标还需年度现金”是达到1.20倍安全线还需增加的年度还款现金，不是建议新增借款；即使当前够还本息，也可能尚未达到这条安全线。";
const financeTerms = {"CFADS": "可用于偿债现金流：企业扣除必要经营和维持性支出后，可用于还本付息的年度现金。它不是净利润，也不是账上现金余额；本项目优先使用企业核验值，缺少时按经营现金流净额减维持性资本支出作代理估算。", "DSCR": "偿债覆盖倍数＝同口径年度可用于偿债现金流（CFADS）÷未来12个月已有及新增债务应还本金和利息。1.00倍表示刚好够还；1.20倍表示每还100元有120元还款现金。没有本息负担或资料不足时不硬算倍数。", "EBIT": "息税前利润：还没有扣除利息和所得税的利润，用来观察利润能否覆盖利息；利润不代表已经收到了现金。", "EBITDA": "息税折旧摊销前利润：本项目按息税前利润加折旧摊销计算，用来辅助观察盈利和债务规模；它不等于可用于还款的现金。", "LPR": "贷款市场报价利率：观察贷款定价环境的参考指标，不是银行对这家企业的实际报价；实际利率还取决于企业资质、担保、期限和合同。", "PMI": "采购经理指数：观察相关行业景气变化的调查指标。通常以50为荣枯分界；它反映整体变化方向，不能直接当作本企业收入或现金流预测。", "pp / 百分点": "表示两个百分比之间的差。利率从5%升到6%，是上升1个百分点（1 pp），不是只上升原利率的1%。"};
function terminologyHtml(){return `<details><summary>术语说明 · 英文缩写是什么意思</summary>${Object.entries(financeTerms).map(([key,value])=>`<p><strong>${e(key)}</strong>：${e(value)}</p>`).join('')}</details>`;}


const paths = {
  home:'M3 10.5 12 3l9 7.5M5 9v11h5v-6h4v6h5V9',
  dashboard:'M3 3h7v7H3zM14 3h7v4h-7zM14 11h7v10h-7zM3 14h7v7H3z',
  building:'M4 21V7l8-4 8 4v14M8 10h1m6 0h1M8 14h1m6 0h1M10 21v-4h4v4M2 21h20',
  branch:'M6 3v12a4 4 0 0 0 4 4h8M6 7h8a4 4 0 0 1 4 4v8M3 3h6v6H3zM15 16h6v6h-6zM15 3h6v6h-6z',
  chart:'M4 3v18h17M8 15l4-5 4 3 5-7M8 18v-3m4 3v-8m4 8v-5m4 5V8',
  folder:'M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v2M3 7h16a2 2 0 0 1 2 2l-2 11H4L2 9a2 2 0 0 1 1-2z',
  book:'M3 4h7a3 3 0 0 1 3 3v14a3 3 0 0 0-3-3H3zM13 7a3 3 0 0 1 3-3h5v14h-5a3 3 0 0 0-3 3M6 8h4m6 0h2M6 12h4m6 0h2',
  arrow:'M5 12h14M13 6l6 6-6 6',
  chevron:'m9 6 6 6-6 6',
  plus:'M12 5v14M5 12h14',
  play:'m8 5 11 7-11 7V5z',
  check:'m5 12 4 4L19 6',
  shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6',
  bolt:'m13 2-9 12h7l-1 8 10-12h-7l1-8z',
  document:'M14 2H5v20h14V7zM14 2v5h5M8 11h8M8 15h8M8 18h5',
  upload:'M12 16V3M7 8l5-5 5 5M4 15v6h16v-6',
  download:'M12 3v13M7 11l5 5 5-5M4 15v6h16v-6',
  clock:'M12 7v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  layers:'m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5',
  search:'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  info:'M12 11v6M12 7h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  warning:'m12 3 10 18H2zM12 9v5m0 3h.01',
  globe:'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0M2 12h20M12 2c6 6 6 14 0 20-6-6-6-14 0-20',
  menu:'M4 6h16M4 12h16M4 18h16',
  close:'m6 6 12 12M6 18 18 6',
  external:'M14 3h7v7M21 3l-10 10M10 3H3v18h18v-7',
  refresh:'M20 7a9 9 0 1 0 1 8M20 2v6h-6',
  mail:'M3 5h18v14H3zM3 5l9 8 9-8',
  send:'m22 2-8 20-4-8-8-4zM22 2 10 14',
  leaf:'M20 3C8 2 2 9 5 16s17 6 15-13M5 19l10-10',
  lock:'M6 10V7a6 6 0 0 1 12 0v3M4 10h16v12H4zM12 14v4',
  chat:'M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5zM8 11h.01M12 11h.01M16 11h.01',
  user:'M20 21a8 8 0 1 0-16 0M12 13a4 4 0 1 0 0-8 4 4 0 0 0 0 8',
  trash:'M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15M10 10v7m4-7v7',
};
const icon = (name, cls='') => `<svg class="icon ${cls}" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="${paths[name]||paths.document}"/></svg>`;
const e = v => String(v??'').replace(/(?:预计)?(?:可用于还款的?现金|还款现金)/g,'预计可用于偿债的现金').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (v,d=1) => v==null?'—':Number(v).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d});
const amountNumber = v => v==null?'—':Number(v).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:Math.abs(v)>0&&Math.abs(v)<.01?8:4});
const money = v => v==null?'待补充':`${amountNumber(Number(v)/1e8)} 亿元`;
const valueFmt = (v,unit='') => v==null?'待补充':unit==='%'?`${number(v*100)}%`:unit==='元'?money(v):`${number(v,2)} ${unit}`.trim();
const badge = (text,color='') => `<span class="badge ${color}">${e(text)}</span>`;
const notice = (text,tone='') => `<div class="notice ${tone}">${icon(tone==='red'||tone==='amber'?'warning':'info')}<span>${e(text)}</span></div>`;
const btn = (text,action,ico='arrow',type='') => `<button class="btn ${type}" data-action="${action}">${icon(ico)}${e(text)}</button>`;
const tabs = (items,current) => `<div class="page-tabs" role="tablist">${items.map(([id,label])=>`<button type="button" role="tab" aria-selected="${id===current}" class="${id===current?'active':''}" data-tab="${id}">${e(label)}</button>`).join('')}</div>`;
const nav = [ ['workspace','分析工作台','dashboard','/workspace'],['company','企业与数据','building','/company'],['execution','财务分析','chart','/analysis'],['solutions','融资决策','layers','/solutions'],['risk','风险评估','shield','/risk'],['delivery','分析报告','folder','/delivery'],['knowledge','模型方法','book','/knowledge'] ];
const AUTH_KEY='finbridge_token',AUTH_USER_KEY='finbridge_user';
function loadAuth(){try{return {token:localStorage.getItem(AUTH_KEY)||null,user:JSON.parse(localStorage.getItem(AUTH_USER_KEY)||'null')};}catch{return {token:null,user:null};}}
function saveAuth(data){state.auth={token:data.token,user:data.user};localStorage.setItem(AUTH_KEY,data.token);localStorage.setItem(AUTH_USER_KEY,JSON.stringify(data.user));}
function clearAuth(){state.auth={token:null,user:null};state.userMenuOpen=false;localStorage.removeItem(AUTH_KEY);localStorage.removeItem(AUTH_USER_KEY);}
const state = {boot:null,run:null,page:'workspace',tab:{company:'import',execution:'timeline',delivery:'report',knowledge:'sources'},goal:'融资组合',busy:false,upload:null,filter:'全部',messages:[],mobile:false,query:'',fieldGroup:null,companyDraft:null,runId:sessionStorage.getItem('finbridge_run')||null,auth:loadAuth(),authOpen:false,authTab:'login',authCaptcha:{id:'',img:''},authDraft:{username:'',password:'',nickname:''},userMenuOpen:false,histOpen:false,histList:[],histAuth:false,modelOpen:false,models:{list:[],selectedId:null,platform:[]},modelProviders:[],modelMode:null,modelEditing:null,modelForm:null,chatModelOpen:false,chatModelsLoaded:false,sidebarCollapsed:localStorage.getItem('finbridge_sb')==='1'};
let pollTimer, toastTimer;
async function api(url,options={}){
  const headers = {...options.headers};
  if(state.auth?.token)headers['Authorization']='Bearer '+state.auth.token;
  if(options.body && !(options.body instanceof FormData)){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);}
  const response=await fetch(url,{...options,headers,credentials:'same-origin'});
  const contentType=response.headers.get('content-type')||'';
  const data=contentType.includes('json')?await response.json():null;
  if(!response.ok){if(response.status===401&&state.auth?.token)clearAuth();throw new Error(data?.detail||data?.error||data?.message||'请求未完成，请稍后重试。');}
  return data;
}
function toast(text){const t=document.querySelector('#toast');t.textContent=text;t.classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove('visible'),3800);}
function routePage(){return location.pathname==='/execution'?'execution':nav.find(x=>x[3]===location.pathname)?.[0]||'workspace';}
function navigate(page){state.page=page;state.mobile=false;history.pushState({},'',nav.find(x=>x[0]===page)?.[3]||'/');render();window.scrollTo({top:0,behavior:'instant'});}
function heading(kicker,title,description,actions=''){return `<div class="page-heading"><div><div class="eyebrow">${e(kicker)}</div><h1>${e(title)}</h1><p class="page-sub">${e(description)}</p></div>${actions?`<div class="heading-actions">${actions}</div>`:''}</div>`;}
function cardTitle(title,ico,extra=''){return `<div class="card-title"><h2>${icon(ico)}${e(title)}</h2>${extra}</div>`;}
function metrics(items){return `<div class="metrics">${items.map(([label,value,unit,note,ico])=>`<div class="metric"><div class="metric-label">${e(label)}${icon(ico)}</div><div class="metric-value">${e(value)}${unit?`<span class="unit">${e(unit)}</span>`:''}</div><div class="metric-note">${e(note)}</div></div>`).join('')}</div>`;}
function field(label,name,value,type='text',extra=''){return `<label class="field"><span>${e(label)}</span><input type="${type}" name="${name}" value="${e(value)}" ${extra}></label>`;}
function selectField(label,name,options,value){return `<label class="field"><span>${e(label)}</span>${uiSelect(name,options,value)}</label>`;}
function snapshotBanner(){let s=notice(`${state.run.id} · ${state.run.data.company_name} · ${state.run.created_at.slice(0,16).replace('T',' ')} · ${state.run.mode}`);if(state.run.stale)s+=notice('企业数据或融资需求已更新。当前为历史任务快照，请重新执行后使用。','amber');if(state.run.model_warning)s+=notice(state.run.model_warning,'amber');return s;}
function noRun(){return `<div class="empty-state">${icon('document')}<h2>从一个融资目标开始</h2><p>先确认企业数据与融资需求，启动任务后即可在这里查看结果。</p>${btn('创建融资分析任务','new-task','plus','primary')}</div>`;}
function isComplete(){return !!state.run?.outputs?.prepare_deliverables;}
function download(format,label,ico='download',primary=false){return `<a class="btn ${primary?'primary':''}" data-report-download="${format}" href="/api/runs/${encodeURIComponent(state.run.id)}/download?format=${format}" download>${icon(ico)}${e(label)}</a>`;}
const protocolText=p=>p==='anthropic'?'Anthropic 格式':'OpenAI 兼容格式';
const truncate=(v,n)=>{const s=String(v||'').replace(/\s+/g,' ').trim();return s.length>n?s.slice(0,n)+'…':s;};
function timeAgo(iso){const t=new Date(iso).getTime();if(!t)return '';const s=Math.floor((Date.now()-t)/1000);if(s<60)return '刚刚';if(s<3600)return `${Math.floor(s/60)} 分钟前`;if(s<86400)return `${Math.floor(s/3600)} 小时前`;return `${Math.floor(s/86400)} 天前`;}
async function loadCaptcha(){try{const data=await api('/api/auth/captcha');state.authCaptcha={id:data.captchaId,img:data.imageBase64};}catch{state.authCaptcha={id:'',img:''};}const img=document.querySelector('#captcha-img');if(img&&state.authCaptcha.img)img.src=state.authCaptcha.img;}
// 顶栏用户区：未登录展示「登录 / 注册」；已登录展示昵称 + 菜单（模型设置 / 历史分析 / 管理后台 / 退出）
function userArea(){
  const u=state.auth.user;
  if(!u)return `<button type="button" class="btn small" data-action="auth-open">${icon('lock')}登录 / 注册</button>`;
  return `<div class="user-chip ${state.userMenuOpen?'open':''}"><button type="button" class="user-chip-btn" data-action="user-menu" aria-expanded="${state.userMenuOpen}">${icon('lock')}<span class="user-chip-name">${e(u.nickname||u.username)}</span>${u.role===1?badge('管理员','blue'):''}</button><div class="user-menu" role="menu"><button type="button" role="menuitem" data-action="model-settings">${icon('lock')}模型设置</button><button type="button" role="menuitem" data-action="hist-open">${icon('clock')}历史分析</button>${u.role===1?`<a role="menuitem" href="/admin.html" target="_blank" rel="noopener">${icon('shield')}管理后台</a>`:''}<button type="button" role="menuitem" data-action="logout">${icon('close')}退出登录</button></div></div>`;
}

function bindReportDownloads(){
 document.querySelectorAll('[data-report-download]').forEach(link=>link.addEventListener('click',async event=>{
  if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
  event.preventDefault();if(link.getAttribute('aria-busy')==='true')return;
  const original=link.innerHTML;link.setAttribute('aria-busy','true');link.innerHTML='<span class="spinner"></span>正在准备文件…';
  try{
   const response=await fetch(link.href,{credentials:'same-origin'});
   if(!response.ok){const data=await response.json().catch(()=>null);throw Error(data?.detail||data?.error||'报告下载未完成，请重试。');}
   const disposition=response.headers.get('content-disposition')||'',utf=disposition.match(/filename\*=UTF-8''([^;]+)/i),plain=disposition.match(/filename="([^"]+)"/i);
   const filename=utf?decodeURIComponent(utf[1]):plain?.[1]||'融资分析报告.docx';
   const objectUrl=URL.createObjectURL(await response.blob()),anchor=document.createElement('a');anchor.href=objectUrl;anchor.download=filename;anchor.hidden=true;document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(objectUrl),2000);
   toast('文件已交给浏览器下载，请查看下载列表。');
  }catch(error){toast(error.message);}
  finally{link.removeAttribute('aria-busy');link.innerHTML=original;}
 }));
}

function shell(content){
  const b=state.boot,p=nav.find(x=>x[0]===state.page);
  const data=b.data;
  return `<div class="mobile-scrim ${state.mobile?'visible':''}" data-action="close-menu"></div><aside class="sidebar ${state.mobile?'open':''}" id="workspace-navigation" aria-label="主导航"><a class="brand" href="/" data-page="workspace"><span class="brand-mark"><svg viewBox="0 0 30 30" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M8 23V7h17M8 15h13M16 23v-8"/></svg></span><span><span class="brand-name">融智 FinBridge</span><span class="brand-sub">FINBRIDGE AI</span></span></a><nav>${nav.filter(x=>x[0]!=="knowledge").map(([id,label,ico,url])=>`<a class="nav-link ${state.page===id?'active':''}" href="${url}" data-page="${id}" title="${e(label)}" ${state.page===id?'aria-current="page"':''}>${icon(ico)}${label}</a>`).join('')}</nav><div class="sidebar-bottom"><div class="sidebar-company"><small>当前分析企业</small><strong>${e(data.company_name||'待载入企业')}</strong>${badge(data.report_period||'待确认报告期')}</div></div></aside><div class="shell"><header class="topbar"><div class="breadcrumbs"><button class="icon-btn menu-btn" data-action="menu" aria-label="展开导航" aria-expanded="${state.mobile}" aria-controls="workspace-navigation">${icon('menu')}</button><span>财务决策工作空间</span>${icon('chevron')}<b>${p[1]}</b></div><div class="topbar-actions"><button type="button" class="btn small" data-action="model-settings" title="管理使用的模型接口">${icon('lock')}<span class="topbar-btn-text">${b.model_configured?'模型已就绪':'模型设置'}</span></button><button type="button" class="btn small" data-action="hist-open" title="历史分析">${icon('clock')}<span class="topbar-btn-text">历史分析</span></button><button class="btn small" data-action="new-task">${icon('plus')}<span class="topbar-btn-text">新建融资分析</span></button>${userArea()}</div></header><main class="main" id="main">${content}<footer class="section-footer"><span>© 融智 FinBridge · 企业财务分析与融资决策</span><div class="footer-items"><span>${icon('shield')}数据隔离</span><span>${icon('check')}证据可追溯</span><span>${icon('leaf')}审慎分析</span></div></footer></main></div>`;
}

function flowArt(){return `<svg class="hero-art" aria-hidden="true" viewBox="0 0 390 180"><path class="flow-line" d="M40 96H90M165 96h55M293 96h40M129 72V38h126v34M129 120v29h126v-29"/><circle cx="40" cy="96" r="6" fill="#a6bea0"/><circle cx="337" cy="96" r="6" fill="#a6bea0"/><rect x="90" y="70" width="76" height="53" rx="10" class="flow-node"/><rect x="219" y="70" width="76" height="53" rx="10" class="flow-node"/><rect x="167" y="21" width="54" height="34" rx="8" fill="#d9e5d0" stroke="#bdcfb2"/><text x="128" y="102" text-anchor="middle" class="flow-label">任务目标</text><text x="257" y="102" text-anchor="middle" class="flow-label">成果交付</text><text x="194" y="43" text-anchor="middle" fill="#6e875e" font-size="10">Agent</text><rect x="168" y="133" width="53" height="32" rx="7" fill="#d9e5d0" stroke="#bdcfb2"/><path d="m184 149 6 5 13-12" fill="none" stroke="#879f74" stroke-width="1.8"/><circle cx="193" cy="96" r="13" fill="#bdd0ad" fill-opacity=".3"/><circle cx="193" cy="96" r="5" fill="#8eaa79"/></svg>`;}

// 模型设置弹窗：复刻 template（大福食刻）AI 助手配置方法
// 状态条 → 平台托管模型分组 → 我的模型列表 → ＋添加模型（供应商宫格 → 表单，含官方文档链接）
function modelItem(m,kind){
  return `<div class="model-item ${m.isSelected?'sel':''}">
    <div class="model-item-main"><strong>${e(m.name||m.displayName||m.modelId)}</strong>${m.isSelected?badge('使用中','green'):''}<small>${e(m.modelId)} · ${protocolText(m.protocol)}</small>${kind==='platform'?`<small>平台托管 · 免配置密钥</small>`:`<small>${e(m.baseUrl)}</small><small>${e(m.apiKeyMasked||'未设置密钥')}</small>`}</div>
    <div class="model-item-ops">${m.isSelected?'':`<button type="button" class="btn ghost small" data-action="${kind==='platform'?'platform-use':'model-use'}" data-model="${m.id}">使用</button>`}${kind==='self'?`<button type="button" class="btn ghost small" data-action="model-test" data-model="${m.id}">测试</button><button type="button" class="btn ghost small" data-action="model-edit" data-model="${m.id}">编辑</button><button type="button" class="btn ghost small" data-action="model-delete" data-model="${m.id}">删除</button>`:''}</div>
  </div>`;
}
// 表单复用共享组件 model-picker.js（与后台平台托管模型同一套字段与交互）
function modelForm(mode){
  const form=state.modelForm,provider=state.modelProviders.find(p=>p.providerKey===form?.provider);
  return mpFormHtml(form,provider,{mode,prefix:'model'});
}
function modelDialog(){
  const data=state.models||{list:[],selectedId:null,platform:[]};
  const selected=data.list.find(m=>m.id===data.selectedId);
  const platformSel=(data.platform||[]).find(p=>p.isSelected);
  let body='';
  if(state.modelMode==='pick'){
    body=`<div class="cfg-group"><div class="cfg-group-head"><h3>选择供应商</h3><small>官方注册表，也可选「自定义」手动填写。</small></div>
    ${mpProvGrid(state.modelProviders,'model')}
    <div class="form-actions"><button type="button" class="btn" data-action="model-cancel">取消</button></div></div>`;
  }else if(state.modelMode==='form'){
    body=`<div class="cfg-group"><div class="cfg-group-head"><h3>${state.modelEditing?'编辑模型':'添加模型'}</h3><small>密钥加密存储、仅显示掩码。</small></div>${modelForm(state.modelEditing?'edit':'add')}</div>`;
  }else{
    body=`<div class="cfg-state ${selected||platformSel?'on':''}">${icon(selected||platformSel?'check':'info')}<span>${selected?`使用中 · ${e(selected.displayName||selected.modelId)}`:platformSel?`使用中 · 平台托管 · ${e(platformSel.name)}`:'未选择模型 · 使用环境变量配置'}</span></div>
    <div class="cfg-group"><div class="cfg-group-head"><h3>平台托管模型</h3><small>由管理员在后台配置密钥，选用即生效。</small></div>${data.platform.length?data.platform.map(p=>modelItem(p,'platform')).join(''):`<p class="subtle-caption">平台暂未提供托管模型，可在管理后台配置。</p>`}</div>
    <div class="cfg-group"><div class="cfg-group-head"><h3>我的模型</h3><small>最多添加 6 个；首个自动「使用中」，删除使用中项自动回落。</small></div>${data.list.length?data.list.map(m=>modelItem(m,'self')).join(''):`<p class="subtle-caption">还没有自配模型。点击下方「＋ 添加模型」，选择供应商后填写接口信息。</p>`}</div>
    <div class="form-actions"><button type="button" class="btn primary" data-action="model-add">${icon('plus')}添加模型</button></div>`;
  }
  return `<div class="dialog-backdrop" data-action="model-close"><div class="dialog dialog-wide" role="dialog" aria-modal="true" aria-label="模型设置">
  <div class="dialog-head"><h2>${icon('lock')}模型设置</h2><button class="icon-btn" data-action="model-close" aria-label="关闭设置">${icon('close')}</button></div>
  <p class="subtle-caption">登录用户可添加自己的模型接口（OpenAI 兼容 / Anthropic），多套配置随时切换「使用中」；AI 理解、调度与解释环节使用当前配置，密钥加密存储、仅显示掩码。未配置时依次使用平台托管与环境变量模型，Python 计算与验证不受影响。</p>
  ${body}
  </div></div>`;
}

// 登录 / 注册弹窗：图形验证码点击刷新，提交失败自动换图并清空验证码输入
function authDialog(){
  const isLogin=state.authTab==='login';
  return `<div class="dialog-backdrop" data-action="auth-close"><div class="dialog auth-dialog" role="dialog" aria-modal="true" aria-label="${isLogin?'登录':'注册'}">
  <div class="dialog-head"><h2>${icon('lock')}${isLogin?'登录融智 FinBridge':'注册融智账号'}</h2><button class="icon-btn" data-action="auth-close" aria-label="关闭">${icon('close')}</button></div>
  <p class="subtle-caption">${isLogin?'登录后可配置自己的模型接口，分析问答将同步到历史分析。':'注册后即可使用模型设置与历史分析管理。'}</p>
  <div class="auth-tabs" role="tablist"><button type="button" role="tab" aria-selected="${isLogin}" class="${isLogin?'active':''}" data-action="auth-tab" data-tab="login">登录</button><button type="button" role="tab" aria-selected="${!isLogin}" class="${!isLogin?'active':''}" data-action="auth-tab" data-tab="register">注册</button></div>
  <form id="auth-form">
    ${field('用户名','auth_username',state.authDraft.username,'text','required minlength="3" maxlength="32" pattern="[A-Za-z0-9_]{3,32}" title="3-32 位字母、数字或下划线" autocomplete="username"')}
    ${isLogin?'':field('昵称（选填）','auth_nickname',state.authDraft.nickname,'text','maxlength="32"')}
    ${field('密码','auth_password',state.authDraft.password,'password','required minlength="6" maxlength="64" autocomplete="current-password"')}
    ${isLogin?'':field('确认密码','auth_password2',state.authDraft.password2||'','password','required minlength="6" maxlength="64" autocomplete="new-password" placeholder="再次输入相同密码"')}
    <div class="captcha-row"><label class="field"><span>图形验证码</span><input type="text" name="captchaCode" required maxlength="6" autocomplete="off" placeholder="不区分大小写"></label><img id="captcha-img" class="captcha-img" src="${state.authCaptcha.img}" alt="图形验证码，看不清可点击刷新" title="点击刷新" data-action="captcha-refresh"></div>
    <div class="form-actions"><button type="submit" class="btn primary">${icon('check')}${isLogin?'登录':'注册'}</button></div>
    <div id="auth-error" class="form-error" role="alert"></div>
  </form></div></div>`;
}

// 历史分析抽屉：上方为当前分析企业与历史分析项目（可点击切换查看），下方为登录用户的问答留痕；「新融资分析」即新建项目
function historyDrawer(){
  const runs=state.boot.runs||[];
  const runItem=x=>`<div class="hist-run ${x.id===state.runId?'current':''}" data-action="hist-run" data-hist-run="${e(x.id)}"><div class="hist-run-head"><strong>${e(x.goal)}</strong>${x.id===state.runId?badge('当前分析','green'):badge(x.status,x.status==='已完成'?'green':'amber')}</div><div class="hist-run-sub">${e(x.company_name)}${x.report_period?` · ${e(x.report_period)}`:''}</div><div class="hist-run-meta"><span>${timeAgo(x.created_at)}</span>${x.stale?'<span>数据已更新 · 历史快照</span>':''}</div></div>`;
  const qaList=state.histAuth
    ?(state.histList.length?state.histList.map(h=>`<div class="hist-item" data-action="hist-view"><div class="hist-q">${icon('chat')}${e(h.question)}</div><div class="hist-a">${e(truncate(h.answer,140))}</div><div class="hist-meta"><span>${timeAgo(h.createdAt)}</span><button type="button" class="icon-btn small" data-action="hist-del" data-hist="${h.id}" aria-label="删除该条记录">${icon('close')}</button></div></div>`).join(''):`<div class="empty-small">${icon('clock')}<div><p>还没有问答记录</p><small>在任务结果页追问，问答会留存在这里，最多保留 20 条。</small></div></div>`)
    :`<div class="empty-small">${icon('lock')}<div><p>登录后可查看问答留痕</p><small>分析项目跟随当前会话；问答留痕与登录账号绑定，最多保留 20 条。</small></div></div>`;
  return `<div class="drawer-backdrop" data-action="hist-close"><aside class="drawer" role="dialog" aria-modal="true" aria-label="历史分析">
  <div class="drawer-head"><h2>${icon('clock')}历史分析</h2><button class="icon-btn" data-action="hist-close" aria-label="关闭">${icon('close')}</button></div>
  <div class="hist-ops"><button type="button" class="btn small" data-action="hist-new-task">${icon('plus')}新融资分析</button><button type="button" class="btn ghost small" data-action="hist-clear">${icon('warning')}清空问答</button></div>
  <div class="hist-list">
    <div class="hist-current"><small>当前分析企业</small><strong>${e(state.boot.data.company_name||'待载入企业')}</strong><span>${e(state.boot.data.report_period||'待确认报告期')}</span></div>
    <div class="hist-group-head"><span>分析项目</span><small>${runs.length?runs.length+' 项':'暂无'}</small></div>
    ${runs.length?runs.map(runItem).join(''):`<div class="empty-small">${icon('document')}<div><p>还没有分析项目</p><small>点击「新融资分析」创建第一个融资分析任务。</small></div></div>`}
    <div class="hist-group-head"><span>分析问答</span><small>${state.histAuth?`${state.histList.length} 条`:'需登录'}</small></div>
    ${qaList}
  </div>
  </aside></div>`;
}

function workspace(){
  const b=state.boot,p=b.profile,q=b.quality,r=state.run,delivery=r?.outputs?.prepare_deliverables;
  const remaining=(r?.tasks||[]).filter(t=>!t.completed).length;
  return heading('FINANCING WORKSPACE','让财务数据，形成可计算的融资组合。','把资金缺口、渠道容量、成本和压力偿付约束，放到同一个预算中。')+
  `<section class="hero"><div><div class="hero-kicker">${icon('bolt')}FINBRIDGE INTELLIGENCE</div><h1>每一笔资金，都有计算依据。</h1><p>上传财务输入，让 Agent 求解组合、核验压力，<br>量化资金缺口，并给出经营改善建议。</p><button class="btn ghost" data-action="method">了解 Agent 的工作方式 ${icon('arrow')}</button></div>${flowArt()}</section>`+
  metrics([['本次外部资金缺口',amountNumber(Math.max(0,p.amount-p.internal_funds)/1e8),'亿元','需求总额 − 可用自有资金','chart'],['财务数据覆盖率',q.coverage,'%','衡量资料完整性，不是信用评分','layers'],['已执行融资分析任务',b.runs.length,'项','当前工作空间真实任务记录','document'],['待完成准备事项',r?remaining:'—','项',r?'来自当前任务的行动清单':'执行任务后自动生成','clock']])+
  `<div class="grid-main"><section class="card" id="task-card">${cardTitle('创建融资分析任务','document',`<span class="model-pill">目标驱动 · 工具执行</span>`)}<form id="task-form"><div class="segment" role="group" aria-label="选择任务目标">${Object.keys(b.goals).map(g=>`<button type="button" data-goal="${g}" class="${g===state.goal?'active':''}">${g}</button>`).join('')}</div><label class="field"><span>任务说明</span><textarea name="objective" rows="3" maxlength="2000" placeholder="描述你希望解决的融资问题…">${e(p.objective)}</textarea></label><div class="fields-row"><label class="field"><span>资金需求总额</span><div class="input-suffix" data-unit="亿元"><input name="amount" type="number" min="0" max="100000000000" step="0.01" value="${e(p.amount/1e8)}" required></div></label><label class="field"><span>可用自有资金</span><div class="input-suffix" data-unit="亿元"><input name="internal_funds" type="number" min="0" max="100000000000" step="0.01" value="${e(p.internal_funds/1e8)}" required></div></label></div><div class="fields-row">${selectField('融资期限（月）','months',[...new Set([6,12,18,24,36,60,p.months])].sort((a,b)=>a-b).map(String),String(p.months))}${selectField('资金用途','purpose',['经营周转','订单备货','设备购置','综合融资'],p.purpose)}</div><div class="request-summary"><span>本次预计外部融资缺口</span><strong id="gap-preview">${money(Math.max(0,p.amount-p.internal_funds))}</strong></div><div class="switch-row"><div><div class="switch-label">${icon('bolt')}AI 自主规划</div><p class="switch-copy">开启后，模型根据目标选择工具，观察结果并完成任务。</p></div><label class="switch"><input name="use_ai" type="checkbox" aria-label="启用 AI 自主规划" ${b.model_configured?'':'disabled'}><span class="switch-track"></span></label></div><p class="consent-note">启用后将企业数据发送至原配置模型，并执行行业地区近期检索、正文核验与市场情景重算；公开检索仅发送行业与地区。关闭时不调用模型或联网检索。</p><div class="form-actions"><button type="submit" class="btn primary" ${state.busy?'disabled':''}>${state.busy?'<span class="spinner"></span>':icon('play')}${state.busy?'正在启动…':'启动融资分析任务'}</button><button type="button" class="btn" data-action="save-task">保存需求</button></div><div id="task-error" class="form-error" role="alert"></div></form></section><div class="side-stack"><section class="card">${cardTitle('当前企业档案','building',btn('管理','company','arrow','ghost small'))}<div class="company-heading"><span class="company-symbol">${icon('building')}</span><div><h3>${e(b.data.company_name||'待载入企业')}</h3><p>${e(p.industry||'行业待确认')} · ${e(p.region||'地区待确认')}</p></div></div><div class="company-meta"><span>报告期间</span><strong>${e(b.data.report_period||'待确认')}</strong></div><div class="company-meta"><span>数据来源</span><strong>${e(b.source)}</strong></div><div class="company-meta"><span>核验状态</span>${badge(q.blocked?'需修正数据':q.core_missing.length?'资料待补充':'基础字段齐备',q.blocked?'red':q.core_missing.length?'amber':'green')}</div><div class="coverage-line"><span style="width:${q.coverage}%"></span></div><p class="coverage-caption">资料覆盖 ${q.coverage}% · 真实性仍需人工核验</p><a href="/company" data-page="company" class="btn wide small">${icon('upload')}导入或补充企业资料</a></section><section class="card">${cardTitle('一次任务，完整交付','folder')}<div class="tools-mini">${[['shield','风险诊断'],['branch','组合求解'],['chart','压力测试'],['document','融资分析报告']].map(([ico,label])=>`<div class="tool-mini"><div class="mini-icon">${icon(ico)}</div>${label}</div>`).join('')}</div><p class="subtle-caption">关键判断关联输入与公式，任务结果随数据变化；每份交付保留执行依据。</p></section></div></div>`+
  `<section class="card" style="margin-top:25px">${cardTitle('最近融资分析任务','clock',r?btn('查看当前交付','delivery','arrow','ghost small'):'<small>执行后自动记录</small>')}${b.runs.length?`<div class="data-scroll"><table class="recent-table"><thead><tr><th>任务与企业</th><th>执行模式</th><th>创建时间</th><th>状态</th><th></th></tr></thead><tbody>${b.runs.map(x=>`<tr><td><span class="task-name">${e(x.goal)} · ${e(x.id)}</span><small>${e(x.company_name||x.data?.company_name||'')}</small></td><td>${e(x.mode)}</td><td>${e((x.created_at||'').slice(0,16).replace('T',' '))}</td><td>${badge(x.status,x.status==='已完成'?'green':'amber')}</td><td><button class="btn ghost small" data-run="${e(x.id)}">查看${icon('arrow')}</button></td></tr>`).join('')}</tbody></table></div>`:`<div class="empty-small">${icon('clock')}<div><p>还没有执行任务</p><small>从上方提交第一个融资目标，开始建立企业的融资分析记录。</small></div></div>`}</section>`;
}

function companyCatalog(){
  return state.boot.field_catalog||Object.fromEntries(state.boot.fields.map(key=>[key,{label:state.boot.labels[key]||key,unit:'元',group:'财务数据',source:''}]));
}
function companyDraft(){
  if(!state.companyDraft)state.companyDraft={data:{...state.boot.data,financing_need:state.boot.profile.amount,available_internal_funds:state.boot.profile.internal_funds},profile:{...state.boot.profile}};
  return state.companyDraft;
}
function captureCompanyDraft(){
  const form=document.querySelector('#company-form');
  if(!form)return;
  const draft=companyDraft(),values=new FormData(form),catalog=companyCatalog();
  for(const [key,value]of values){
    if(!key.startsWith('data:'))continue;
    const name=key.slice(5),raw=String(value).trim();
    draft.data[name]=raw===''?null:Number(raw)/(catalog[name]?.unit==='%'?100:1);
  }
  for(const key of ['company_name','report_period'])draft.data[key]=String(values.get(key)||'').trim();
  for(const key of ['industry','region','purpose'])if(values.has(key)){draft.profile[key]=String(values.get(key)||'').trim();draft.data[key]=draft.profile[key];}
  if(Number.isFinite(draft.data.financing_need)&&draft.data.financing_need>=0)draft.profile.amount=draft.data.financing_need;
  if(Number.isFinite(draft.data.available_internal_funds)&&draft.data.available_internal_funds>=0)draft.profile.internal_funds=draft.data.available_internal_funds;
}
function importedProfile(row){
  if(row.statement_schema==='public-v2')return {...state.boot.profile,analysis_mode:'public-v2',industry:row.industry||'未披露',region:row.region||'未披露'};
  const validMoney=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0;
  const purposes=['经营周转','订单备货','设备购置','综合融资'];
  return {...state.boot.profile,amount:validMoney(row.financing_need)?row.financing_need:0,
    internal_funds:validMoney(row.available_internal_funds)?row.available_internal_funds:0,
    industry:String(row.industry||''),region:String(row.region||''),purpose:purposes.includes(row.purpose)?row.purpose:'经营周转',
    collateral:'未确认',receivables:'未确认',objective:'基于当前企业财务输入与已确认渠道容量，计算资金组合、假设成本和压力偿付能力。'};
}
function company(){
  const b=state.boot,q=b.quality,tab=state.tab.company;
  let content='';
  if(tab==='import')content=`<div class="grid-main"><section class="card">${cardTitle('导入企业财务数据','upload')}<label class="upload-area" id="drop-zone">${icon('upload')}<strong>点击选择，或将财务表格拖入这里</strong><p>支持 CSV、XLSX、XLSM · 单文件不超过10MB</p><input type="file" id="upload-input" accept=".csv,.xlsx,.xlsm" aria-label="上传财务表格"></label><p class="subtle-caption">中文XLSX模板按分组填写，并附字段、单位和来源说明。比例填5.2表示5.2%；每行一家企业，可合并同企业同期间工作表。暂不支持扫描PDF。</p><div class="inline-actions" style="margin-top:18px"><a class="btn small" href="/api/template" download>${icon('download')}中文XLSX模板</a><a class="btn small" href="/api/template?format=csv" download>${icon('download')}CSV模板</a><a class="btn small" href="/api/template?example=1" download>${icon('document')}带数值的模拟示例</a></div>${state.upload?`<div class="file-preview">${notice(`已读取${state.upload.filename}，识别出${state.upload.records.length}条企业记录。`)}<label class="field"><span>选择企业与期间</span>${uiSelect('upload-row',state.upload.records.map((row,i)=>({value:String(i),label:row.company_name+' · '+(row.report_period||'待确认期间')})),'0')}</label><button class="btn primary" data-action="use-upload">${icon('check')}使用这份企业数据</button><p class="subtle-caption">同时载入该记录的资金需求、自有资金、行业、地区及融资用途。未填写需求金额时设为0待确认，避免沿用其他企业需求。</p></div>`:''}</section><section class="card">${cardTitle('体验模拟案例','layers')}<p class="subtle-caption" style="margin:0 0 15px">虚构场景，用于观察财务变化如何影响资金组合。</p>${b.cases.map((c,i)=>`<div class="case-option"><div class="company-symbol">${icon(['building','warning','document'][i]||'building')}</div><div><strong>${e(c.name)}</strong><p>${e(c.description)}</p></div><button class="btn small" data-demo="${e(c.id)}">载入</button></div>`).join('')}</section></div>`;
  else{
    const draft=companyDraft(),catalog=companyCatalog(),entries=Object.entries(catalog).filter(([,meta])=>['元','%','月','年'].includes(meta.unit));
    const groups=[...new Set(entries.map(([,meta])=>meta.group||'其他字段'))];
    if(!groups.includes(state.fieldGroup))state.fieldGroup=groups[0];
    const selected=entries.filter(([,meta])=>(meta.group||'其他字段')===state.fieldGroup);
    const rows=selected.map(([key,meta])=>{
      const value=draft.data[key],display=value==null?'':meta.unit==='%'?Number((Number(value)*100).toPrecision(12)):value;
      return `<tr><td>${e(meta.label||b.labels[key]||key)}<small>${e(meta.source||'来源待核验')}</small></td><td><input type="number" step="any" name="data:${e(key)}" value="${e(display)}" ${['financing_need','available_internal_funds'].includes(key)?'min="0" required':''} aria-label="${e(meta.label||key)}（${e(meta.unit)}）"></td><td>${e(meta.unit)}</td><td><details><summary>字段口径</summary><code>${e(key)}</code><p class="subtle-caption">${e(meta.meaning||meta.note||meta.description||'按资料来源核对数值和报告期间。')}</p></details></td></tr>`;
    }).join('');
    content=`<form id="company-form"><section class="card">${cardTitle('企业档案与融资用途','building')}<div class="fields-row">${field('企业名称','company_name',draft.data.company_name,'text','required maxlength="100"')}${field('报告期间','report_period',draft.data.report_period||'','text','placeholder="例如：2025年度" maxlength="50"')}</div><div class="fields-row">${field('所属行业','industry',draft.profile.industry||'','text','maxlength="100"')}${field('所在地区','region',draft.profile.region||'','text','maxlength="100"')}</div><div class="fields-row">${selectField('本次融资用途','purpose',['经营周转','订单备货','设备购置','综合融资'],draft.profile.purpose)}${selectField('财务字段分组','field-group',groups,state.fieldGroup)}</div><p class="subtle-caption">金额填元；比例填百分数，例如5.2表示5.2%；期限填月。留空表示缺失，0为确认的零值。分组切换保留未保存修改，点击保存后统一提交。</p><p class="subtle-caption">组合容量以“已确认可用信用额度、合格应收、无负担资产及设备采购金额”独立填写，不能把账面资产自动视为额度。CFADS是每年可用于还本付息的现金，不等于净利润或账上现金余额。</p><div class="data-scroll" style="margin-top:20px"><table class="data-table"><thead><tr><th>字段与来源</th><th>数值</th><th>单位</th><th>口径说明</th></tr></thead><tbody>${rows}</tbody></table></div><div class="form-actions"><button class="btn primary" type="submit">${icon('check')}保存全部已编辑字段</button></div><div id="company-error" class="form-error" role="alert"></div></section></form><section class="card">${cardTitle('数据核验结果','shield')}${q.blocked?notice([...(q.issues||[]),...(q.invalid||[]).map(key=>`无效字段：${b.labels[key]||key}`)].join('；'),'red'):notice('已通过字段与金额关系检查；仍需核验数据真实性。')}${q.missing.length?`<details><summary>待补充${q.missing.length}项字段</summary><p class="subtle-caption">${q.missing.map(key=>e(b.labels[key]||key)).join('、')}</p></details>`:''}${!q.period_known?notice('报告期间未确认，请补充准确的报告期。','amber'):''}</section>`;
  }
  return heading('COMPANY & DATA','企业与数据','按中文模板提供财务、融资容量与用途资料，保留来源、单位和期间。')+tabs([['import','导入与案例'],['profile','档案与财务字段']],tab)+content;
}

function marketTable(headers,rows){
  const status={'通过':'green','未通过':'red','达到安全线':'green','需调整':'amber'};
  const cell=c=>{const value=String(c??'');const numeric=/^[+−-]?\d[\d,]*(?:\.\d+)?\s*(?:亿元|%|倍|天|个月)?$/.test(value);return `<td${numeric?' class="numeric"':''}>${Object.hasOwn(status,value)?badge(value,status[value]):e(c)}</td>`;};
  return `<div class="data-scroll"><table class="data-table"><thead><tr>${headers.map(h=>`<th>${e(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function marketDecisionHtml(d){
  if(!d)return '';
  const stress=d.planning_stress;
  let out=`<h3>近期市场证据与融资决策</h3><p>${e(d.as_of)} · 近${e(d.window_days)}天 · ${e(d.status)}</p>`;
  out+=`<p class="subtle-caption">LPR是贷款市场报价利率，不能当作企业实际报价；PMI是采购经理指数，用来观察行业景气。利率上行1个百分点，例如从5%升到6%。</p>`;
  out+=notice(`市场情景：CFADS下降${(stress.cash_drop*100).toFixed(0)}%，利率上行${(stress.rate_up*100).toFixed(2)}个百分点；目标DSCR ${stress.target_dscr.toFixed(2)}。这是敏感性情景，不是预测。`);
  out+=marketTable(['指标','基础组合','市场情景组合','变化'],d.comparison.map(r=>[r.label,money(r.baseline),money(r.market),money(r.delta)]));
  out+=`<p>${e(d.action)}</p><details ${d.changed?'open':''}><summary>触发规则、市场组合与压力测试</summary>`;
  out+=d.accepted_signals.map(s=>`<p><strong>${e(s.rule_id+' · '+s.label+' · '+s.source_id)}</strong><br>${e(s.quote)}<br><small>${e(s.reason)}</small></p>`).join('');
  out+=d.rejected_signals.map(s=>`<p>未采用：${e(s.source_id+' · '+s.reason)}</p>`).join('');
  out+=d.lpr_observations.map(x=>`<p>央行公告 ${e(x.date)}：1年期LPR ${(x.one_year*100).toFixed(2)}% · ${e(x.source_id)}（非企业报价）</p>`).join('');
  if(d.portfolio?.available){
    out+=marketTable(['渠道','市场情景本金'],d.portfolio.composition.map(c=>[c.name,money(c.amount)]));
    out+=marketTable(['压力情景','DSCR','达目标还需年度现金流'],d.portfolio.scenarios.map(s=>[s.label,valueFmt(s.dscr,'倍'),money(s.gap_to_target)]));
  }
  out+=`<p>${e(d.decision_note)}</p>`+d.limitations.map(x=>`<p class="subtle-caption">${e(x)}</p>`).join('');
  return out+`<small>证据版本 ${e(d.evidence_fingerprint)} · ${e(d.version)}</small></details>`;
}

function industryContextHtml(){
  const c=state.run?.outputs?.analyze_industry_region;
  if(!c)return notice('本历史任务尚无行业地区分析。','amber');
  return `<section class="card"><h3>行业地区分析 · ${e(c.status)}</h3><p class="subtle-caption">${e(c.source_status||c.summary)}</p><details><summary>查看行业地区结论、来源与检索过程</summary>${industryContextDetailsHtml()}</details></section>`;
}

function industryContextDetailsHtml(){
  const c=state.run?.outputs?.analyze_industry_region;
  if(!c)return notice('本历史任务未包含行业地区分析，请重新生成任务。','amber');
  let result=`<section class="card">${cardTitle('行业与地区融资分析','building',badge(c.status,c.available?'green':'amber'))}<p class="subtle-caption">${e(c.industry)} · ${e(c.region)}</p><p>${e(c.summary)}</p>`;
  result+=marketDecisionHtml(c.market_decision);
  if(c.research_coverage)result+=`<h3>资料覆盖与替代范围</h3>`+Object.entries(c.research_coverage).map(([k,v])=>`<p class="subtle-caption">${e(k+'：'+v)}</p>`).join('');
  result+=(c.peer_references||[]).map(p=>`<article class="route-card"><h4>${e(p.company_name+' · '+p.classification)}</h4><p>${e('相似分 '+p.score+'/100 · 来源 '+p.source_id+' · '+p.differences.join('；'))}</p><p class="subtle-caption">${e(p.limit)}</p></article>`).join('');
  result+=(c.research_steps||[]).map(s=>`<p class="subtle-caption">${e(s.step+" · "+s.status+"："+s.detail)}</p>`).join('');
  if(c.available){
    if(c.financial_anchor)result+=notice(c.financial_anchor);
    result+=`<p class="subtle-caption">${e(c.source_status)} · 同行观察不构成统计对标</p><details><summary>查看行业、地区、同行与融资建议</summary>`;
    const sections={industry:'行业经营与资金特点',region:'地区融资环境',peers:'同行融资观察',implications:'对本企业融资组合的影响',actions:'建议与下一步'};
    for(const [key,title] of Object.entries(sections)){
      result+=`<h3>${title}</h3>`+(c.sections[key]||[]).map(item=>`<article class="route-card" style="margin:12px 0"><h4>${e(item.title)}</h4><p>${e(item.analysis)}</p><p class="subtle-caption">${e(item.basis)}${item.metric_keys.length?'；财务依据：'+item.metric_keys.map(k=>{const m=state.run.outputs.calculate_ratios[k];return m?e(m.label+' '+valueFmt(m.value,m.unit)):e(k);}).join('、'):''}${item.source_ids.length?'；资料：'+item.source_ids.map(e).join('、'):''}</p></article>`).join('');
    }
    result+=(c.data_gaps||[]).map(x=>`<p class="subtle-caption">尚缺资料：${e(x)}</p>`).join('');
    result+=(c.sources||[]).map(s=>`<p><a class="link" href="${e(s.url)}" target="_blank" rel="noopener noreferrer">${e(s.id+' · '+s.title)}</a><br><small>原文/条目日期：${e(s.published_at)}；${e(s.evidence_status)}</small></p>`).join('');
    result+=`<p class="subtle-caption">生成时间：${e(c.analyzed_at)}；模型：${e(c.model)}</p></details>`;
  }
  return result+`<p class="subtle-caption">${e(c.boundary)}</p></section>`;
}

function execution(){
  let result=heading('EXECUTION & EVIDENCE','执行与证据','从工具调用到财务公式，每一个关键判断都可以回看。');
  if(!state.run)return result+noRun();
  const r=state.run,out=r.outputs||{},tab=state.tab.execution;
  result+=snapshotBanner();
  if(!isComplete())result+=r.status!=='执行中'?notice(r.error||'本次任务未完成，请检查数据后重新创建任务。','amber'):`<div class="progress-banner"><h2><span class="spinner"></span>正在执行融资分析任务</h2><p>已完成 ${r.events?.filter(x=>x.status==='完成').length||0} 项工具调用。模型规划与工具观察会陆续更新。</p></div>`;
  result+=tabs([['timeline','执行轨迹'],['metrics','财务证据'],['risk','风险依据'],['context','行业与地区'],['snapshot','输入快照']],tab);
  if(tab==='timeline'){
    result+=`<section class="card">${cardTitle('实际工具执行记录','branch',`<small>${(r.events||[]).length} 次调用</small>`)}<div class="timeline">${(r.events||[]).map(x=>`<div class="timeline-item ${x.status==='失败'?'failed':''}"><div class="timeline-marker">${x.status==='完成'?icon('check'):icon('warning')}</div><div class="timeline-head"><h3>${e(x.label)}</h3><small>${e(x.status)} · ${number(x.duration_ms,1)} ms${x.cached?' · 复用结果':''}</small></div><p>${e(x.tool)}</p><details><summary>查看输入与工具观察 ${icon('chevron')}</summary><pre class="json-code">${e(JSON.stringify({arguments:x.arguments,observation:x.result},null,2))}</pre></details></div>`).join('')||'<p class="subtle-caption">正在等待第一项工具返回结果…</p>'}</div><p class="subtle-caption">以上是实际工具执行记录，不展示模型内部思维链。行业地区工具耗时包含检索与专项模型请求；其他工具时间不含规划模型请求。</p>${isComplete()?`<div style="margin-top:18px">${download('json','下载执行证据')}</div>`:''}</section>`;
  } else if(tab==='context'){
    result+=industryContextHtml();
  } else if(tab==='metrics'){
    result+=`<section class="card">${cardTitle('财务指标与计算依据','chart')}<p class="subtle-caption">${e(repaymentHelp)}</p>${terminologyHtml()}<div class="data-scroll"><table class="data-table"><thead><tr><th>指标</th><th>结果</th><th>计算公式</th><th>来源与期间</th><th>数据问题</th></tr></thead><tbody>${Object.values(out.calculate_ratios||{}).map(x=>`<tr><td>${e(x.label)}</td><td style="white-space:nowrap">${e(valueFmt(x.value,x.unit))}</td><td>${e(x.formula)}</td><td>${x.sources.map(f=>e(state.boot.labels[f]||f)).join('、')}<br><small>${e(x.period)}</small></td><td>${e(x.data_issue||'—')}</td></tr>`).join('')}</tbody></table></div></section>`;
  } else if(tab==='risk'){
    result+=notice(out.assess_risk?.methodology||'风险工具尚未完成。');
    result+=`<div class="risk-grid">${Object.values(out.assess_risk?.dimensions||{}).map(d=>`<section class="card"><div class="card-title"><h2>${e(d.label)}</h2>${badge(d.risk_level,d.risk_level==='较高'?'red':d.risk_level==='关注'||d.risk_level==='无法判断'?'amber':'green')}</div><p class="subtle-caption">${e(d.data_sufficiency)}</p><div class="risk-evidence">${d.evidence.map(x=>`<p>${e(x.rule_label||x.rule)} · 实际 ${e(valueFmt(x.value,x.unit))} ${badge(x.triggered?'已触发':'未触发',x.triggered?'amber':'green')}</p>`).join('')||'资料不足，无法判断。'}</div></section>`).join('')}</div>`;
  } else result+=`<section class="card">${cardTitle('本次任务锁定快照','lock')}<pre class="json-code" style="max-height:700px">${e(JSON.stringify({source:r.source,fingerprint:r.fingerprint,data:r.data,profile:r.profile},null,2))}</pre></section>`;
  if(isComplete())result+=`<div class="inline-actions" style="margin-top:23px">${btn('查看融资方案','solutions','chart','primary')}${btn('打开交付中心','delivery','folder')}</div>`;
  return result;
}

function financingFundingBar(plan){
  const f=plan.funding;
  if(!plan.available||!(f.need>0))return '';
  const colors=['#087f73','#5b86a6','#a083ac','#d3a654','#72b8a0','#c95a4f'];
  const parts=[{name:'自有资金',amount:f.internal_used,color:colors[0]},...plan.composition.map((c,i)=>({name:c.name,amount:c.amount,color:colors[i+1]})),{name:'未覆盖用途缺口',amount:f.unfunded_gap,color:colors[5]}].filter(x=>x.amount>0);
  let cursor=16;
  return `<div class="chart-wrap"><svg viewBox="0 0 760 70" role="img" aria-label="资金结构：自有资金、融资组合本金和未覆盖用途缺口"><rect x="16" y="18" width="728" height="30" rx="6" fill="#edf1e7"/>${parts.map(x=>{const width=x.amount/f.need*728,left=cursor;cursor+=width;return `<rect x="${left}" y="18" width="${width}" height="30" fill="${x.color}"><title>${e(x.name)}：${e(money(x.amount))}，占需求${number(x.amount/f.need*100)}%</title></rect>`;}).join('')}</svg></div><div class="tags">${parts.map(x=>`<span class="badge" style="border-left:4px solid ${x.color}">${e(x.name)} ${e(money(x.amount))}</span>`).join('')}</div>`;
}
function portfolioStressHtml(plan){
  const rows=plan.scenarios||[];
  const stress=plan.algorithm?.planning_stress||{cash_drop:.2,rate_up:.01};
  if(!rows.length)return notice('偿付输入尚未齐备，暂不生成压力结果。','amber');
  const values=rows.map(x=>x.dscr).filter(x=>x!=null&&Number.isFinite(x));
  let content=`<section class="card">${cardTitle('同一融资组合的压力测试','chart')}<p class="subtle-caption">${e(repaymentHelp)}</p><p class="subtle-caption">项目假设目标DSCR为1.20，主组合约束使用CFADS下降${(stress.cash_drop*100).toFixed(0)}%与利率上行${(stress.rate_up*100).toFixed(2)}个百分点。下降30%为额外探索，不是预测；营收变化不自动等同CFADS变化。</p><div class="data-scroll"><table class="data-table"><thead><tr><th>情景</th><th>还款现金（CFADS）</th><th>新增未来12个月本息</th><th>存量未来12个月本息</th><th>还款覆盖倍数（DSCR）</th><th>达到目标还需年度现金</th></tr></thead><tbody>${rows.map(s=>`<tr><td>${e(s.label)}</td><td>${e(money(s.cfads))}</td><td>${e(money(s.new_annual_service))}</td><td>${e(money(s.existing_annual_service))}</td><td>${badge(valueFmt(s.dscr,'倍'),s.dscr==null?'amber':s.dscr>=1.2?'green':'red')}</td><td>${e(money(s.gap_to_target))}</td></tr>`).join('')}</tbody></table></div>`;
  if(values.length){
    const low=Math.min(0,...values),high=Math.max(1.6,...values)*1.12,y=v=>205-(v-low)/(high-low)*165;
    const labels={base:'基准',cash_drop:`CFADS −${(stress.cash_drop*100).toFixed(0)}%`,rate_up:`利率 +${(stress.rate_up*100).toFixed(2)}个百分点`,double:'双重压力',cash_drop_30:'CFADS −30%'};
    content+=`<div class="chart-wrap"><svg viewBox="0 0 760 260" role="img" aria-label="五种情景的整体偿债覆盖率，虚线为项目假设目标1.20"><line x1="30" y1="${y(0)}" x2="730" y2="${y(0)}" stroke="#dce6d3"/><line x1="30" y1="${y(1.2)}" x2="730" y2="${y(1.2)}" stroke="#a64c40" stroke-dasharray="6 5"/><text x="32" y="${y(1.2)-7}" font-size="10" fill="#a64c40">还款安全线 1.20倍</text>${rows.map((s,i)=>{const x=77+i*140,v=s.dscr;return `${v!=null?`<rect x="${x}" y="${y(Math.max(0,v))}" width="54" height="${Math.abs(y(v)-y(0))}" rx="4" fill="${v>=1.2?'#80a784':v>=1?'#c4a578':'#c95a4f'}"><title>${e(s.label)}：DSCR ${number(v,3)}</title></rect>`:''}<text x="${x+27}" y="${v==null?y(0)-12:y(Math.max(0,v))-10}" text-anchor="middle" font-size="12" fill="#5d7255">${v==null?'待补充':number(v,2)}</text><text x="${x+27}" y="244" text-anchor="middle" font-size="11" fill="#829676">${e(labels[s.id]||s.label)}</text>`;}).join('')}</svg></div>`;
  }
  return content+`<p class="subtle-caption">${e(plan.repayment_note)} ${e(stressHelp)}</p><p class="subtle-caption">${e(cashGapHelp)}</p></section>`;
}
function taskFocusHtml(){
  const f=state.run?.outputs?.prepare_deliverables?.task_focus;
  if(!f)return '';
  let out=`<section class="card">${cardTitle('本次分析重点 · '+f.goal,'chart')}<h2>${e(f.title)}</h2><p>${e(f.summary)}</p>`;
  out+=(f.funding_steps||[]).map(c=>`<article class="route-card"><h4>${e(c.channel)}：${e(money(c.amount))}</h4><p>${e(c.reason)}</p><p>假设全期限利息与费用：${e(money(c.cost))}</p></article>`).join('');
  if(f.risk){
    const t=f.risk.threshold;
    if(t){const limit=t.already_below?'已低于安全线':t.cash_drop_limit==null?'不适用':(t.cash_drop_limit*100).toFixed(1)+'%';
      out+=marketTable(['最多可下降的还款现金','每年至少需要的还款现金','通过设定压力还需改善现金'],[[limit,money(t.minimum_cash),money(t.cash_improvement)]]);
      out+=`<p class="subtle-caption">${e(repaymentHelp)} ${e(t.note)}</p>`;
      if(t.cash_improvement>0)out+=notice('至少增加年度还款现金 '+money(t.cash_improvement)+'，或减少对应年度本息 '+money(t.service_reduction)+'；两种路径不能重复计入。','amber');
    }
    out+=marketTable(['先看什么问题','关注程度','实际依据'],f.risk.ranked.map(r=>[r.question,r.level,r.reason]));
    out+=f.risk.improvements.filter(d=>d.unit==='元').slice(0,2).map(d=>`<p>${e(d.title+'：'+money(d.value))}</p><p class="subtle-caption">${e(d.action)} 这是条件式试算，不是已到账资金。</p>`).join('');
  }
  if(f.comparison){
    out+=marketTable(['方案','新增借款','还差的钱','全期限利息与费用','加息后新增一年内还款','统一压力覆盖倍数'],f.comparison.options.map(p=>[p.title,money(p.debt),money(p.gap),money(p.total_cost),money(p.new_service),p.common_stress_dscr==null?'无本息负担':p.common_stress_dscr.toFixed(2)]));
    out+=f.comparison.options.map(p=>`<details><summary>${e(p.title+' · 适合什么情况、具体借法')}</summary><p>${e(p.reason)}</p><p>${e(p.status)}</p>${p.composition.map(c=>`<p>${e(c.name+'：'+money(c.amount)+'，'+c.months+'个月')}</p>`).join('')}</details>`).join('');
    out+=f.comparison.duplicates.map(d=>`<p class="subtle-caption">${e(d)}</p>`).join('');
    out+=`<p class="subtle-caption">${e(f.comparison.note)}</p>`;
  }
  return out+'</section>';
}

function financingPortfolioHtml(compact=false){
  const market=state.run?.outputs?.analyze_industry_region?.market_decision;
  const p=market?.changed&&market?.portfolio?.available?market.portfolio:state.run?.outputs?.optimize_financing_portfolio;
  if(!p)return notice('此任务尚未计算融资组合，请重新生成。','amber');
  const f=p.funding,r=state.run.outputs.prepare_deliverables?.decision_review;
  const title=r?.title||(!p.available?'输入未通过核验，暂不能给出金额':f.debt_total===0&&f.gap>0?'本次新增融资本金为0：先核对容量和偿债预算':f.unfunded_gap>0?'组合仍有资金缺口，需要调整计划':'用途本金已覆盖，仍需核实费用与合同');
  const rows=r?.channels||(p.composition||[]).map(c=>({channel:c.name,field:state.boot?.labels?.[c.capacity_input]||c.capacity_input,raw:state.run.profile[c.capacity_input]??state.run.data[c.capacity_input],source:'本次任务快照',capacity:c.capacity,amount:c.amount,status:!c.enabled?'用途不适用':c.capacity===0?'容量为0，核对字段':c.amount>0?'已纳入组合':'有容量，未选用'}));
  let result=`<section class="card">${cardTitle('本次融资结论','chart')}<h2>${e(title)}</h2><p class="subtle-caption">本次测算结果 · ${e(state.run.id)} · 依据任务生成时的数据</p>`;
  result+=(r?.causes||[]).map(c=>notice(c,'amber')).join('');
  result+=metrics([['可配置新增债务',f.debt_total==null?'待补充':amountNumber(f.debt_total/1e8),'亿元','计算结果','chart'],['尚缺用途资金',f.unfunded_gap==null?'待补充':amountNumber(f.unfunded_gap/1e8),'亿元','需要调整或落实资金','clock'],['另需一次性费用',f.fees_due==null?'待补充':amountNumber(f.fees_due/1e8),'亿元','费用单列','layers']]);
  result+=marketTable(['渠道','建议本金','可用容量','当前状态','需要核对的字段'],rows.map(c=>[c.channel,money(c.amount),money(c.capacity),c.status,c.field]));
  result+=`<details ${f.debt_total===0?'open':''}><summary>核对本次实际读到的数据</summary>`+marketTable(['容量依据字段','实际输入','来源'],rows.map(c=>[c.field,money(c.raw),c.source]))+`<p>新增未来12个月本息预算：${e(money(p.algorithm?.service_budget))}，这不是贷款本金。</p></details><p class="subtle-caption">修改路径：企业与数据 → 档案与财务字段。仅根据真实资料修改，保存后返回工作台重新生成；历史报告不会自动更新。</p><a class="btn" href="/company">核对或修改企业数据</a> <a class="btn primary" href="/">返回工作台重新生成</a></section>`;
  return taskFocusHtml()+adjustmentHtml()+terminologyHtml()+`<section class="card"><h3>调整前先核对什么</h3><p>${e({融资组合:"核实渠道额度、用途和报价，再处理剩余缺口。",风险分析:"优先核实还款现金、已有本息和回款情况。",方案比较:"明确资金覆盖、近期还款与抗压余量的取舍；方案不能叠加。"}[state.run.goal]||"")}</p><details><summary>渠道诊断、原始输入与修改入口</summary>${result}</details></section>`+`<details><summary>查看完整测算、压力测试与计算依据</summary>${financingPortfolioDetailsHtml(compact)}</details>`;
}

function financingPortfolioDetailsHtml(compact=false){
  const market=state.run?.outputs?.analyze_industry_region?.market_decision;
  const p=market?.changed&&market?.portfolio?.available?market.portfolio:state.run?.outputs?.optimize_financing_portfolio;
  if(!p)return notice('此任务尚未执行融资组合工具，请重新启动分析。','amber');
  const f=p.funding;
  let result=`<section class="card">${cardTitle('融资组合预算','chart',badge(p.risk_status||p.status,'amber'))}<h2 style="font-size:24px;margin-bottom:14px">${e(p.status)}</h2>${metrics([['资金需求',f.need==null?'待确认':amountNumber(f.need/1e8),'亿元','用户申报项目需求','building'],['投入自有资金',f.internal_used==null?'待确认':amountNumber(f.internal_used/1e8),'亿元','仍需核验可支配性','layers'],['组合债务本金',f.debt_total==null?'暂停':amountNumber(f.debt_total/1e8),'亿元','条件预算，授信尚未落实','chart'],['未覆盖用途缺口',f.unfunded_gap==null?'待确认':amountNumber(f.unfunded_gap/1e8),'亿元','未落实资金不计作已筹','clock']])}<p class="subtle-caption">${e(f.note)}</p>${(p.risk_flags||[]).map(flag=>notice(flag,'amber')).join('')}${financingFundingBar(p)}</section>`;
  if(market?.changed)result+=notice('当前主建议采用近期证据触发的市场压力组合。基础组合及差异见行业地区分析，两者不可叠加。');
  if(!p.available)return result;
  result+=`<section class="card">${cardTitle('各渠道金额、容量与假设成本','layers')}<div class="data-scroll"><table class="data-table"><thead><tr><th>渠道</th><th>本金预算</th><th>占新增债务</th><th>渠道容量</th><th>假设年利率</th><th>期限</th><th>假设月供</th><th>全期限利息</th><th>一次性费</th></tr></thead><tbody>${p.composition.map(c=>`<tr><td>${e(c.name)}</td><td>${e(money(c.amount))}</td><td>${e(valueFmt(c.share,'%'))}</td><td>${e(money(c.capacity))}</td><td>${e(valueFmt(c.rate,'%'))}</td><td>${e(c.months)}个月</td><td>${e(money(c.monthly_payment))}</td><td>${e(money(c.total_interest))}</td><td>${e(money(c.total_fee))}</td></tr>`).join('')}</tbody></table></div><p class="subtle-caption">本金配置共用一个项目缺口和偿付预算。各渠道为组合组成部分，备选对照不再叠加。报价及实际还款结构尚待核验。</p>${notice(`用途本金之外，假设一次性费用为${money(f.fees_due)}，费用待筹缺口${money(f.fee_funding_gap)}，用途与费用合计待筹${money(f.total_unfunded_cash)}。未知费率0为占位假设，不代表实际免费。`,'amber')}${p.composition.map(c=>`<details ${c.amount>0?'open':''}><summary>${e(c.name)} · ${e(money(c.amount))}</summary><p>${e(c.reason)}</p>${(c.assumed||[]).map(a=>`<p class="subtle-caption">${e(a)}</p>`).join('')}</details>`).join('')}</section>`;
  result+=`<section class="card">${cardTitle('量化建议与下一步','document')}${(p.recommendations||[]).map(r=>`<article class="route-card" style="margin-bottom:14px"><h3>${e(r.title)}</h3><p>${e(r.quantification)}</p><p class="subtle-caption">原因：${e(r.reason)}</p><p>建议：${e(r.action)}</p></article>`).join('')}</section>`;
  if(compact)return result+`<p class="subtle-caption">完整五情景压力结果、渠道对照和计算约束见“融资组合”；导出报告保留当前任务快照。</p>`;
  result+=portfolioStressHtml(p);
  const allocation=p.purpose_allocation;
  if(allocation)result+=`<section class="card">${cardTitle('资金用途拆分','building')}<div class="data-scroll"><table class="data-table"><thead><tr><th>用途</th><th>需求子预算</th><th>债务配置</th><th>自有资金</th><th>未覆盖</th></tr></thead><tbody>${[['经营周转','working',allocation.working_capital_funding_need??allocation.working_capital_need],['设备投入','equipment',allocation.equipment_funding_need]].map(([name,key,need])=>`<tr><td>${name}</td><td>${e(money(need))}</td><td>${e(money(allocation[key+'_debt']))}</td><td>${e(money(allocation[key+'_internal']))}</td><td>${e(money(allocation[key+'_unfunded']))}</td></tr>`).join('')}</tbody></table></div><p class="subtle-caption">${e(allocation.note)}</p></section>`;
  if(p.alternatives?.length)result+=`<section class="card">${cardTitle('单渠道替代对照','branch')}<p class="subtle-caption">对照采用同一项目需求和压力偿付预算；每项替代当前组合，不与组合金额相加。</p><div class="data-scroll"><table class="data-table"><thead><tr><th>替代方式</th><th>本金预算</th><th>未覆盖用途缺口</th><th>假设月供</th><th>假设总利息与费</th><th>双重压力DSCR</th></tr></thead><tbody>${p.alternatives.map(a=>`<tr><td>${e(a.title)}</td><td>${e(money(a.debt_total))}</td><td>${e(money(a.unfunded_gap))}</td><td>${e(money(a.monthly_payment))}</td><td>${e(money(a.total_cost))}</td><td>${e(valueFmt(a.stress_dscr,'倍'))}</td></tr>`).join('')}</tbody></table></div></section>`;
  const industry=p.industry;
  if(industry)result+=`<section class="card">${cardTitle('行业与回款周期 · '+industry.name,'building')}<ul class="route-list">${(industry.pain_points||[]).map(x=>`<li>${e(x)}</li>`).join('')}</ul><p>${e(industry.repayment_match)}</p><p class="subtle-caption">专项核验：${(industry.verification_materials||[]).map(e).join('、')}</p><p class="subtle-caption">${e(industry.note)}</p></section>`;
  const drivers=state.run?.outputs?.prepare_deliverables?.drivers||[];
  if(drivers.length)result+=`<section class="card">${cardTitle('经营改善与资金敏感性','chart')}${drivers.map(d=>`<article class="route-card" style="margin-bottom:14px"><h3>${e(d.title)} · ${e(valueFmt(d.value,d.unit))}</h3><p class="subtle-caption">${e(d.reason)}</p><p>${e(d.action)}</p></article>`).join('')}</section>`;
  const algorithm=p.algorithm;
  result+=`<section class="card"><details><summary>计算目标、约束与假设</summary><h3>${e(algorithm.name)}</h3><ol>${algorithm.objective.map(x=>`<li>${e(x)}</li>`).join('')}</ol><p class="subtle-caption">检查候选顶点 ${e(algorithm.checked_candidates)} 个；最优仅限当前候选、输入和假设，不代表真实市场最低成本。</p><div class="data-scroll"><table class="data-table"><thead><tr><th>约束</th><th>上限</th><th>已使用</th><th>剩余空间</th><th>是否达到上限</th></tr></thead><tbody>${algorithm.constraints.map(c=>`<tr><td>${e(c.label)}${c.unit==='元/年'?'<br><small>未来12个月</small>':''}</td><td>${e(money(c.limit))}</td><td>${e(money(c.used))}</td><td>${e(money(c.remaining))}</td><td>${badge(c.binding==null?'待核验':c.binding?'已达到':'尚有空间',c.binding?'amber':'')}</td></tr>`).join('')}</tbody></table></div>${algorithm.assumptions.map(x=>`<p class="subtle-caption">${e(x)}</p>`).join('')}</details></section>`;
  return result;
}
function solutions(){
  let content=heading('FINANCING PORTFOLIO','融资组合','用同一个资金缺口与压力偿付预算，比较可核验渠道的金额、成本和用途。');
  if(!isComplete())return content+noRun();
  const routes=state.run.outputs.match_routes||[];
  content+=snapshotBanner()+financingPortfolioHtml()+industryContextHtml();
  if(routes.length)content+=`<section class="card"><details><summary>各融资渠道的核验依据</summary><div class="route-grid">${routes.map(x=>`<article class="route-card"><h3>${e(x.name)}</h3>${badge(x.status,'amber')}<ul class="route-list">${(x.evidence||[]).map(v=>`<li>${e(v)}</li>`).join('')}</ul><p class="subtle-caption">核验条件：${(x.conditions||[]).map(e).join('；')}</p><p class="subtle-caption">材料：${(x.materials||[]).map(e).join('、')}</p><a class="link" href="${e(state.boot.knowledge.find(k=>k.id===x.source)?.url||'#')}" target="_blank" rel="noopener noreferrer">${e(x.source)} · 查看依据 ${icon('external')}</a></article>`).join('')}</div></details></section>`;
  return content+`<div class="inline-actions" style="margin-top:23px">${btn('前往分析报告与行动','delivery','folder','primary')}</div>`;
}



function adjustmentHtml(){
 const r=state.run,market=r.outputs.analyze_industry_region?.market_decision,p=market?.changed&&market?.portfolio?.available?market.portfolio:r.outputs.optimize_financing_portfolio,stress=p?.algorithm?.planning_stress||{};
 if(!p?.available)return '';
 const defs={融资组合:[['internal_funds','试算自有资金','亿元',1e8,0,1e15],['confirmed_credit_limit','试算已确认可用信用额度','亿元',1e8,0,1e15]],风险分析:[['cash_flow_available_for_debt_service','试算年度还款现金','亿元',1e8,-1e15,1e15],['scheduled_debt_service','试算已有债务年度本息','亿元',1e8,0,1e15]],方案比较:[['cash_drop','试算还款现金下降','%',.01,.2,.4],['rate_up','试算利率上行','个百分点',.01,.01,.05]]}[r.goal];
 return `<section class="card">${cardTitle('改一个条件，看看结果怎么变','chart')}<p class="subtle-caption">假设试算：重新计算指标、风险和组合。沿用本任务市场压力口径，不重新联网、不调用模型、不覆盖原报告。</p><form id="adjustment-form"><div class="fields-row">${defs.map(([key,label,unit,factor,low,high])=>{const value=key in stress?stress[key]:r.profile[key]??r.data[key];return `<label class="field"><span>${e(label)}（${e(unit)}）</span><input name="${key}" data-factor="${factor}" type="number" step="any" min="${low/factor}" max="${high/factor}" value="${value==null?'':value/factor}" required></label>`;}).join('')}</div><button class="btn primary" type="submit">计算调整后的结果</button></form><div id="adjustment-result" aria-live="polite"></div></section>`;
}

function reportBriefHtml(){
  const b=state.run.report_brief;
  if(!b)return notice('请刷新本任务以载入成果摘要；完整报告仍可下载。','amber');
  let out=`<section class="card">${cardTitle('这次分析在解决什么问题','document')}<h3>${e(b.question)}</h3><p class="subtle-caption">${e([b.company,b.industry,b.region,b.period,b.source].join(' · '))}</p><p>资金需求 ${e(money(b.request.need))}，自有资金 ${e(money(b.request.own))}，${e(b.request.months)}个月，用于${e(b.request.purpose)}。</p><h3>${e(b.title)}</h3>${notice(b.conclusion,b.available?'':'amber')}</section>`;
  if(b.goal==='融资组合')out+=`<section class="card">${cardTitle('筹资安排','branch')}${marketTable(['渠道','金额','期限','假设利息及费用'],b.channels.map(c=>[c.channel,money(c.amount),c.months+'个月',money(c.cost)]))}<p>用途缺口 ${e(money(b.funding.unfunded_gap))}；一次性费用另需 ${e(money(b.funding.fees_due))}。</p></section>`;
  if(b.goal==='风险分析'&&b.threshold){const t=b.threshold;out+=`<section class="card">${cardTitle('还款余量与改善目标','shield')}<p>每年至少需 ${e(money(t.minimum_cash))} 还款现金；现金下降临界点 ${t.already_below?'已低于安全线':t.cash_drop_limit==null?'不适用':e(number(t.cash_drop_limit*100,1))+'%'}；通过设定压力还需改善 ${e(money(t.cash_improvement))}。</p><p class="subtle-caption">${e(t.note)}</p></section>`;}
  if(b.comparison)out+=`<section class="card">${cardTitle('不同借法的效果与代价','branch')}${marketTable(['方案','借款','缺口','全期限成本','加息后新增一年内本息','统一压力覆盖倍数'],b.comparison.options.map(p=>[p.title,money(p.debt),money(p.gap),money(p.total_cost),money(p.new_service),valueFmt(p.common_stress_dscr,'倍')]))}${b.comparison.duplicates.map(x=>`<p class="subtle-caption">${e(x)}</p>`).join('')}<p class="subtle-caption">${e(b.comparison.note)}</p></section>`;
  out+=`<section class="card">${cardTitle('哪些数据支撑这个结论','chart')}${marketTable(['关键指标','本次结果','为什么看它','待核对'],b.metrics.map(m=>[m.label,m.value,m.why,m.issue||'—']))}<p class="subtle-caption">${e(repaymentHelp)}</p></section>`;
  out+=`<section class="card">${cardTitle('最需要注意的风险','shield')}${b.risks.map(r=>`<h3>${e(r.question)} · ${e(r.level)}</h3><p>${e(r.reason)}</p>`).join('')}</section>`;
  out+=`<section class="card">${cardTitle('压力下还能不能还款','chart')}${b.scenarios.length?marketTable(['情景','年度还款现金','一年内已有及新增本息','覆盖倍数','达到安全线还需年度现金'],b.scenarios.map(x=>[x.label,money(x.cfads),money(x.new_annual_service+x.existing_annual_service),valueFmt(x.dscr,'倍'),money(x.gap_to_target)])):notice('数据未通过核验，暂不能验证偿付能力。','amber')}<p class="subtle-caption">${e(cashGapHelp)}</p></section>`;
  out+=`<section class="card">${cardTitle('建议怎么做，以及要付出什么','check')}${b.strategies.map((x,i)=>`<h3>${i+1}. ${e(x.title)}</h3><p>${e(x.detail)}</p>`).join('')}</section>`;
  out+=`<section class="card">${cardTitle('近期市场有没有改变结论','globe')}<p>${e(b.market.impact)}</p><p class="subtle-caption">${e(b.market.source_status)}</p>${b.market.evidence.map(x=>`<h3>${e(x.title)}</h3><p>${e(x.analysis)}</p><small>${e(x.source_ids.join('、')||'模型判断，未引用来源')}</small>`).join('')}<details><summary>资料引用与完整行业地区依据</summary>${industryContextHtml()}</details></section>`;
  return out+`<section class="card"><details><summary>本次方法、指标公式和结论边界</summary><p>${e(b.methods)}</p>${b.metrics.map(m=>`<p>${e(m.label+'：'+m.formula)}</p>`).join('')}<p>${e(b.boundary)}</p></details>${terminologyHtml()}</section>`;
}

function delivery(){
  let content=heading('DELIVERABLES & ACTIONS','交付与行动','把融资分析结果交给负责人，把下一步落实到具体准备事项。');
  if(!isComplete())return content+noRun();
  const r=state.run,d=r.outputs.prepare_deliverables,tab=state.tab.delivery;
  content+=snapshotBanner()+tabs([['report','融资分析报告'],['actions','改善建议与行动'],['questions','结果追问']],tab);
  if(tab==='report')content+=reportBriefHtml();
  if(tab==='report')content+=`<div class="grid-main"><section class="card">${cardTitle('企业融资分析报告','document',badge(r.reviewed?'已人工复核':'待人工复核',r.reviewed?'green':'amber'))}<label class="review-row"><input id="review-input" type="checkbox" ${r.reviewed?'checked':''}><span>我已核对数据来源、报告期间与测算假设。<br><small>会话复核标记不是电子签名或正式授信审批。</small></span></label><div class="download-grid">${download('zip','下载完整交付包','folder',true)}${download('html','可打印报告','document')}${download('markdown','Markdown 报告','download')}</div><p class="subtle-caption">交付包包含报告、执行证据、当前行动进度和复核状态。</p></section><section class="card">${cardTitle('使用边界','shield')}${d.limitations.map(x=>`<p class="subtle-caption" style="margin-bottom:14px">${e(x)}</p>`).join('')}<button class="btn wide small" data-action="execution">${icon('branch')}回看执行依据</button></section></div>`;
  else if(tab==='actions'){
    const done=r.tasks.filter(x=>x.completed).length;
    const items=r.tasks.filter(x=>state.filter==='全部'||(state.filter==='未完成'?!x.completed:x.priority===state.filter));
    content+=`<section class="card"><div class="action-progress"><h2>融资分析进度</h2><span>${done} / ${r.tasks.length} 已完成</span></div><div class="coverage-line" style="height:6px"><span style="width:${r.tasks.length?done/r.tasks.length*100:0}%"></span></div><div class="action-filter" role="group" aria-label="筛选行动任务">${['全部','优先','常规','未完成'].map(x=>`<button data-filter="${x}" class="${state.filter===x?'active':''}">${x}</button>`).join('')}</div>${items.map(x=>`<label class="action-item ${x.completed?'done':''}"><input type="checkbox" data-task="${e(x.id)}" ${x.completed?'checked':''}><span><strong>${e(x.title)}</strong><small>${e(x.id)} · ${e(x.owner)}<br>依据：${e(x.evidence)}</small></span>${badge(x.priority,x.priority==='优先'?'amber':'')}</label>`).join('')||'<p class="subtle-caption">当前筛选下没有任务。</p>'}<div style="margin-top:20px">${download('csv','导出当前行动进度')}</div></section>`;
  } else content+=`<section class="card">${cardTitle('围绕本次结果继续追问','mail')}<p class="subtle-caption">解释已有证据和测算假设。追问不会修改报告或代替你提交银行申请。</p><div class="inline-actions" style="margin:20px 0">${['为什么这样分配各渠道金额？','回款提速能释放多少资金？','现金流下行时应怎样调整组合？'].map(x=>`<button class="btn small" data-question="${e(x)}">${e(x)}</button>`).join('')}</div><div id="chat-messages">${state.messages.map(x=>`<div class="chat-message ${x.role}">${e(x.content)}</div>`).join('')}</div><form id="question-form"><div class="chat-model-line"><span class="subtle-caption" style="margin:0">本轮对话使用的模型</span><span class="chat-model-slot"><button type="button" class="btn ghost small" data-action="chat-model" aria-haspopup="menu" aria-expanded="${!!state.chatModelOpen}" title="选择本轮对话使用的模型">${icon('bolt')}${chatModelLabel()}${icon('chevron')}</button>${state.chatModelOpen?chatModelPopover():''}</span></div><label class="review-row"><input type="checkbox" name="consent" required ${state.boot.model_configured?'':'disabled'}><span>允许将本任务数据与报告发送到已配置的模型服务，用于结果解释。</span></label><div class="chat-compose"><textarea name="question" rows="3" maxlength="2000" placeholder="例如：为什么这样分配融资金额，回款提速后组合会怎样变化？" required ${state.boot.model_configured?'':'disabled'}></textarea><button class="btn primary" type="submit" ${state.boot.model_configured?'':'disabled'}>${icon('send')}发送</button></div></form>${!state.boot.model_configured?notice('当前模型未配置，仍可使用完整的本地分析与报告功能。','amber'):''}</section>`;
  return content;
}

function knowledge(){
  const b=state.boot,tab=state.tab.knowledge;
  let content=heading('KNOWLEDGE & METHODOLOGY','知识与方法','理解资料来源、分析方法，以及系统判断的适用边界。')+tabs([['sources','来源知识库'],['methods','Agent 方法'],['examples','任务示例']],tab);
  if(tab==='sources'){
    const docs=b.knowledge.filter(x=>!state.query||[x.title,x.text,...x.tags].join(' ').includes(state.query));
    content+=`<form id="knowledge-form" class="knowledge-search">${icon('search')}<input name="query" value="${e(state.query)}" placeholder="检索流动资金、应收账款、担保或租赁…" aria-label="检索融资知识"></form><div class="knowledge-grid">${docs.map(x=>`<article class="card knowledge-card"><div class="section-kicker">${e(x.id)} / ${e(x.scope)}</div><h2>${e(x.title)}</h2><small>${e(x.publisher)} · ${e(x.date)}</small><p>${e(x.text)}</p><div class="tags">${x.tags.map(t=>badge(t)).join('')}</div><a class="link" href="${e(x.url)}" target="_blank" rel="noopener noreferrer">打开原始来源 ${icon('external')}</a></article>`).join('')||notice('没有匹配的知识条目，请尝试其他关键词。')}</div><p class="subtle-caption">精选公开资料摘要，整理于2026-10-11。融资适配、组合测算和阈值是本项目的演示方法，引用资料不代表监管机构认可结论。</p>`;
  }else if(tab==='methods')content+=`<section class="hero"><div><div class="hero-kicker">GOAL → TOOLS → OBSERVATION → DELIVERY</div><h1>目标驱动，证据支撑。</h1><p>模型理解任务并选择工具，服务端校验依赖与输入，<br>工具返回观察结果，最终生成报告和行动计划。</p></div>${flowArt()}</section><div class="method-grid">${b.tools.map(x=>`<section class="card method-card"><div class="section-kicker">${e(x.id)}</div><h2>${e(x.label)}</h2><p>${e(x.description)}</p><small>前置依赖：${e(x.dependencies?.join('、')||'无')}</small></section>`).join('')}</div><section class="card" style="margin-top:20px">${cardTitle('执行模式与边界','shield')}<p class="subtle-caption">AI 自主规划：模型选择工具并观察返回结果，最多10轮规划和16次工具请求。连接或规划中断会明确显示本地续跑。</p><p class="subtle-caption">本地工作流：关闭 AI 时执行同一套 Python 工具，不请求外部模型。指标不由模型猜测，关键数据缺失时生成补充任务。</p><p class="subtle-caption">当前没有银行受理、征信、税务或实时产品接口。资料以用户提供或模拟数据为基础；演示规则尚未做行业校准。</p></section>`;
  else content+=`<div class="method-grid">${[['融资组合','经营周转资金需求0.03亿元，自有0.005亿元，计算信用、应收和抵质押融资组合。','制造业案例 · 24个月 · 经营周转'],['风险分析','重点检查短期偿债和现金流问题，把资料缺失与风险转化为优先行动。','食品科技案例 · 现金流承压'],['方案比较','设备采购比较融资方式，测试CFADS下降20%及利率上行1个百分点。','制造业案例 · 设备购置']].map(([title,text,example])=>`<section class="card method-card"><div class="section-kicker">TASK EXAMPLE</div><h2>${title}</h2><p>${text}</p><small>${example}</small><div style="margin-top:18px"><button class="btn small" data-example="${title}">${icon('arrow')}创建此类任务</button></div></section>`).join('')}</div>`;
  return content;
}

function render(){
 if(!state.boot)return;
 const root=document.querySelector('#app'),runKey=state.run?.id||'',company=state.boot.data.company_name;
 const sameView=root.dataset.viewPage===state.page&&root.dataset.viewRun===runKey&&root.dataset.viewCompany===company;
 const savedY=window.scrollY,oldLog=document.querySelector('#sme-chat-log'),savedLog=oldLog?.scrollTop;
 const details=sameView?[...root.querySelectorAll('main details')].map(d=>({label:d.querySelector(':scope>summary')?.textContent.trim(),open:d.open})):[];
 const focused=sameView&&root.contains(document.activeElement)?document.activeElement:null;
 const focusId=focused?.id,selection=focused&&typeof focused.selectionStart==='number'?[focused.selectionStart,focused.selectionEnd]:null;
 const views={workspace,company,execution,solutions,delivery,knowledge,risk:publicRisk};
 if(state.boot.data.statement_schema==='public-v2')Object.assign(views,{workspace:publicWorkspace,company:publicCompany,execution:publicExecution,solutions:publicSolutions,risk:publicRisk,delivery:publicDelivery,knowledge:publicKnowledge});
 root.innerHTML=shell(views[state.page]())+(state.modelOpen?modelDialog():'')+(state.authOpen?authDialog():'')+(state.histOpen?historyDrawer():'');root.dataset.viewPage=state.page;root.dataset.viewRun=runKey;root.dataset.viewCompany=company;
 document.title=`${nav.find(x=>x[0]===state.page)[1]} · 融智 FinBridge`;
 const queues=new Map();for(const d of details){if(!queues.has(d.label))queues.set(d.label,[]);queues.get(d.label).push(d.open);}
 for(const d of root.querySelectorAll('main details')){const matches=queues.get(d.querySelector(':scope>summary')?.textContent.trim());if(matches?.length)d.open=matches.shift();}
 document.body.classList.toggle('nav-open',state.mobile);
 document.body.classList.toggle('sb-collapsed',state.sidebarCollapsed);
 bind();window.scrollTo({top:savedY,behavior:'instant'});
 const newLog=document.querySelector('#sme-chat-log');if(newLog&&savedLog!=null)newLog.scrollTop=savedLog;
 if(focusId){const next=document.getElementById(focusId);next?.focus({preventScroll:true});if(next&&selection)try{next.setSelectionRange(...selection);}catch{}}
 updateDialogueHeight();
}
function taskProfile(){const f=new FormData(document.querySelector('#task-form'));return {...state.boot.profile,objective:f.get('objective'),amount:Number(f.get('amount'))*1e8,internal_funds:Number(f.get('internal_funds'))*1e8,months:Number(f.get('months')),purpose:f.get('purpose')};}
function syncTaskDraft(profile){
  if(!state.companyDraft)return;
  for(const key of ['amount','internal_funds','months','purpose','objective'])state.companyDraft.profile[key]=profile[key];
  Object.assign(state.companyDraft.data,{financing_need:profile.amount,available_internal_funds:profile.internal_funds,purpose:profile.purpose});
}
async function refreshBoot(){state.boot=await api('/api/bootstrap');if(!Object.hasOwn(state.boot.goals,state.goal))state.goal=Object.keys(state.boot.goals)[0]||'融资组合';}
async function loadRun(id,poll=false){
  const run=await api(`/api/runs/${encodeURIComponent(id)}`);if(state.runId!==id)state.messages=[];state.run=run;state.runId=id;sessionStorage.setItem('finbridge_run',id);
  refreshChatModels();
  if(poll&&run.status==='执行中')schedulePoll();else clearTimeout(pollTimer);
  return run;
}
async function refreshChatModels(){
  // 决策对话区的模型按钮文案需要已选模型名；载入分析后静默预取一次，失败时按钮回退"默认模型"
  if(state.chatModelsLoaded)return;state.chatModelsLoaded=true;
  try{state.models=await api('/api/ai/models');render();}catch{}
}
function schedulePoll(){clearTimeout(pollTimer);pollTimer=setTimeout(async()=>{try{await loadRun(state.runId,true);if(isComplete()){await refreshBoot();toast('融资分析任务已完成，报告与行动清单已生成。');}if(state.page==='execution'||state.page==='workspace')render();}catch(err){toast(err.message);}},1200);}
async function saveTask(start=false){
  const f=document.querySelector('#task-form');if(!f.reportValidity())return;
  const profile=taskProfile();state.busy=true;
  const submit=f.querySelector('[type=submit]');submit.disabled=true;submit.innerHTML='<span class="spinner"></span>正在启动…';
  try{
    if(!start){state.boot=await api('/api/company',{method:'POST',body:{data:state.boot.data,profile,source:state.boot.source}});syncTaskDraft(state.boot.profile);if(state.runId)await loadRun(state.runId);state.busy=false;toast('融资需求已保存。');render();return;}
    const response=await api('/api/runs',{method:'POST',body:{goal:state.goal,profile,use_ai:f.elements.use_ai.checked}});
    await refreshBoot();syncTaskDraft(state.boot.profile);await loadRun(response.id,true);navigate('execution');
  }catch(err){const error=document.querySelector('#task-error');if(error)error.textContent=err.message;else toast(err.message);}
  finally{state.busy=false;if(document.contains(submit)){submit.disabled=false;submit.innerHTML=icon('play')+'启动融资分析任务';}}
}
async function uploadFile(file){if(!file)return;if(file.size>10*1024*1024){toast('文件超过10MB，请缩小后上传。');return;}const f=new FormData();f.append('file',file);toast('正在读取财务表格…');try{state.upload=await api('/api/upload',{method:'POST',body:f});render();toast('已识别企业记录，请确认后使用。');}catch(err){toast(err.message);}}

function bind(){
  bindReportDownloads();
  if(typeof bindPublic==='function')bindPublic();
  document.querySelectorAll('[data-page]').forEach(el=>el.addEventListener('click',event=>{if(event.ctrlKey||event.metaKey)return;event.preventDefault();navigate(el.dataset.page);}));
  document.querySelectorAll('[data-action]').forEach(el=>el.addEventListener('click',async()=>{
    const action=el.dataset.action;
    if(nav.some(x=>x[0]===action)){navigate(action);return;}
    if(action==='new-task'||action==='hist-new-task'){
      // 新建融资分析项目：清空当前企业数据与需求；已有分析保留在历史分析中可恢复
      if(!(await uiConfirm({title:'新建融资分析项目？',message:'当前未保存的企业数据与融资需求将被清除；已有分析仍保留在「历史分析」中，可随时恢复继续。',confirmText:'新建项目'})))return;
      try{
        state.boot=await api('/api/workspace/new',{method:'POST'});
        state.companyDraft=null;state.run=null;state.runId=null;state.messages=[];
        state.decisionChat=null;state.decisionChatFor=null;state.decisionChatDraft='';state.decisionChatError='';
        sessionStorage.removeItem('finbridge_run');
        state.histOpen=false;render();navigate('workspace');
        document.querySelector('#task-card')?.scrollIntoView({behavior:'smooth',block:'start'});
        toast('已新建融资分析项目，请先载入企业数据。');
      }catch(err){toast(err.message);}
      return;}
    if(action==='method'){state.tab.knowledge='methods';navigate('knowledge');return;}
    if(action==='menu'||action==='close-menu'){
      // 对标主流 AI 工作台：桌面端左上角按钮收起/展开侧边栏（窄条图标态），移动端仍是抽屉导航
      if(window.matchMedia('(max-width:760px)').matches){state.mobile=action==='menu'?!state.mobile:false;document.querySelector('.sidebar').classList.toggle('open',state.mobile);document.querySelector('.mobile-scrim').classList.toggle('visible',state.mobile);document.body.classList.toggle('nav-open',state.mobile);document.querySelector('.menu-btn')?.setAttribute('aria-expanded',String(state.mobile));}
      else{state.sidebarCollapsed=!state.sidebarCollapsed;localStorage.setItem('finbridge_sb',state.sidebarCollapsed?'1':'0');render();}
      return;}
    if(action==='save-task'){await saveTask();return;}
    if(action==='model-settings'){
      if(!state.auth.token){state.authTab='login';state.authOpen=true;await loadCaptcha();render();toast('请先登录后再配置模型。');return;}
      try{[state.models,state.modelProviders]=await Promise.all([api('/api/ai/models'),api('/api/ai/providers').then(d=>d.list||[])]);}catch{state.models={list:[],selectedId:null,platform:[]};state.modelProviders=[];}
      state.modelOpen=true;state.modelMode=null;state.modelEditing=null;state.modelForm=null;render();return;}
    if(action==='model-close'){state.modelOpen=false;state.modelMode=null;state.modelEditing=null;state.modelForm=null;render();return;}
    if(action==='chat-model'){
      // 决策对话区的模型快捷选择：懒加载模型列表后开关气泡，选中即用 platform-use / model-use 既有切换逻辑
      if(!state.chatModelsLoaded){state.chatModelsLoaded=true;try{state.models=await api('/api/ai/models');}catch{state.models={list:[],selectedId:null,platform:[]};}}
      state.chatModelOpen=!state.chatModelOpen;render();return;}
    if(action==='chat-model-manage'){
      if(!state.auth.token){state.chatModelOpen=false;state.authTab='login';state.authOpen=true;await loadCaptcha();render();toast('请先登录后再配置模型。');return;}
      state.chatModelOpen=false;
      try{[state.models,state.modelProviders]=await Promise.all([api('/api/ai/models'),api('/api/ai/providers').then(d=>d.list||[])]);state.chatModelsLoaded=true;}catch{state.models={list:[],selectedId:null,platform:[]};state.modelProviders=[];}
      state.modelOpen=true;state.modelMode=null;state.modelEditing=null;state.modelForm=null;render();return;}
    if(action==='platform-use'){try{await api(`/api/ai/platform-models/${el.dataset.model}/select`,{method:'PUT'});state.models=await api('/api/ai/models');await refreshBoot();render();toast('已切换为平台托管模型。');}catch(err){toast(err.message);}return;}
    if(action==='model-use'){try{await api(`/api/ai/models/${el.dataset.model}/select`,{method:'PUT'});state.models=await api('/api/ai/models');await refreshBoot();render();toast('已切换为该模型配置。');}catch(err){toast(err.message);}return;}
    if(action==='model-add'){state.modelMode='pick';state.modelEditing=null;state.modelForm=null;render();return;}
    if(action==='model-pick'){const p=state.modelProviders.find(x=>x.providerKey===el.dataset.provider);if(!p)return;state.modelMode='form';state.modelEditing=null;state.modelForm={provider:p.providerKey,protocol:p.protocol,baseUrl:p.baseUrl,modelId:'',displayName:'',apiKey:''};render();return;}
    if(action==='model-repick'){state.modelMode='pick';render();return;}
    if(action==='model-cancel'){state.modelMode=null;state.modelEditing=null;state.modelForm=null;render();return;}
    if(action==='model-edit'){const item=(state.models.list||[]).find(m=>m.id===Number(el.dataset.model));if(!item)return;state.modelMode='form';state.modelEditing=item.id;state.modelForm={provider:item.provider,protocol:item.protocol,baseUrl:item.baseUrl,modelId:item.modelId,displayName:item.displayName,apiKey:''};render();return;}
    if(action==='model-delete'){if(!(await uiConfirm({title:'删除该模型配置？',message:'删除「使用中」项后会自动回落到其他配置。',confirmText:'删除',danger:true})))return;try{const result=await api(`/api/ai/models/${el.dataset.model}`,{method:'DELETE'});state.models=result.models||await api('/api/ai/models');if(state.modelEditing===Number(el.dataset.model)){state.modelEditing=null;state.modelMode=null;}await refreshBoot();render();toast('已删除该模型配置。');}catch(err){toast(err.message);}return;}
    if(action==='model-test'){el.disabled=true;const label=el.textContent;el.textContent='测试中…';try{await api(`/api/ai/models/${el.dataset.model}/test`,{method:'POST'});toast('连通性测试通过，该模型可正常调用。');}catch(err){toast(err.message);}finally{el.disabled=false;el.textContent=label;}return;}
    if(action==='auth-open'){state.authTab='login';state.authOpen=true;await loadCaptcha();render();return;}
    if(action==='auth-close'){state.authOpen=false;render();return;}
    if(action==='auth-tab'){const f=document.querySelector('#auth-form');if(f)state.authDraft={username:f.auth_username?.value||'',password:f.auth_password?.value||'',password2:f.auth_password2?.value||'',nickname:f.auth_nickname?.value||''};state.authTab=el.dataset.tab;await loadCaptcha();render();return;}
    if(action==='captcha-refresh'){await loadCaptcha();return;}
    if(action==='user-menu'){state.userMenuOpen=!state.userMenuOpen;render();return;}
    if(action==='logout'){clearAuth();try{await refreshBoot();}catch{}render();toast('已退出登录。');return;}
    if(action==='hist-open'){
      // 分析项目对所有会话可用；问答留痕需登录，拉取失败（未登录/过期）时仅在抽屉内提示
      state.histList=[];state.histAuth=!!state.auth.token;
      if(state.histAuth){try{state.histList=(await api('/api/ai/history')).list||[];}catch{state.histAuth=false;}}
      state.histOpen=true;render();return;}
    if(action==='hist-close'){state.histOpen=false;render();return;}
    if(action==='hist-view'){el.classList.toggle('expanded');return;}
    if(action==='hist-del'){if(!(await uiConfirm({title:'删除这条问答记录？',confirmText:'删除',danger:true})))return;try{await api(`/api/ai/history/${el.dataset.hist}`,{method:'DELETE'});state.histList=(await api('/api/ai/history')).list||[];render();}catch(err){toast(err.message);}return;}
    if(action==='hist-clear'){if(!(await uiConfirm({title:'清空全部分析问答？',message:'此操作不可恢复，将删除最近 20 条问答留痕。',confirmText:'全部清空',danger:true})))return;try{await api('/api/ai/history',{method:'DELETE'});state.histList=[];render();toast('已清空问答记录。');}catch(err){toast(err.message);}return;}
    if(action==='hist-run'){try{
      // 恢复历史分析项目：后端将该项目当时的企业数据与融资需求设为当前工作空间
      state.histOpen=false;
      state.boot=await api(`/api/runs/${encodeURIComponent(el.dataset.histRun)}/restore`,{method:'POST'});
      state.companyDraft=null;
      await loadRun(el.dataset.histRun,true);
      navigate(isComplete()?'delivery':'execution');
    }catch(err){toast(err.message);}return;}
    if(action==='use-upload'){
      const row=state.upload.records[Number(document.querySelector('input[name=upload-row]')?.value||0)];
      try{const profile=importedProfile(row);state.boot=await api('/api/company',{method:'POST',body:{data:row,source:'用户上传 · '+state.upload.filename,profile}});state.companyDraft=null;state.upload=null;if(!state.boot.active_run_id){state.run=null;state.runId=null;state.decisionChat=null;state.decisionChatFor=null;state.decisionChatDraft='';sessionStorage.removeItem('finbridge_run');}if(state.runId)await loadRun(state.runId);state.tab.company='profile';render();toast('企业数据及融资需求已同步，请核对金额与用途。');}catch(err){toast(err.message);}return;
    }
  }));
  document.querySelectorAll('[data-tab]').forEach(el=>el.addEventListener('click',()=>{if(state.page==='company')captureCompanyDraft();state.tab[state.page]=el.dataset.tab;render();}));
  document.querySelectorAll('[data-goal]').forEach(el=>el.addEventListener('click',()=>{state.goal=el.dataset.goal;document.querySelectorAll('[data-goal]').forEach(b=>b.classList.toggle('active',b===el));}));
  document.querySelectorAll('[data-demo]').forEach(el=>el.addEventListener('click',async()=>{el.disabled=true;try{state.boot=await api('/api/demo',{method:'POST',body:{id:el.dataset.demo}});
  clearTimeout(pollTimer);state.companyDraft=null;state.upload=null;state.run=null;state.runId=null;state.messages=[];state.tab.company='profile';
  state.decisionChat=null;state.decisionChatFor=null;state.decisionChatDraft='';state.decisionChatError='';sessionStorage.removeItem('finbridge_run');
  navigate('workspace');document.querySelector('#task-card')?.scrollIntoView({block:'start'});
  toast('案例已载入。请调整融资金额，再点击“开始完整分析”。');}catch(err){toast(err.message);el.disabled=false;}}));
  document.querySelectorAll('[data-run]').forEach(el=>el.addEventListener('click',async()=>{try{await loadRun(el.dataset.run,true);navigate(isComplete()?'delivery':'execution');}catch(err){toast(err.message);}}));
  document.querySelectorAll('[data-filter]').forEach(el=>el.addEventListener('click',()=>{state.filter=el.dataset.filter;render();}));
  document.querySelectorAll('[data-task]').forEach(el=>el.addEventListener('change',async()=>{try{const response=await api(`/api/runs/${state.run.id}`,{method:'PATCH',body:{tasks:[{id:el.dataset.task,completed:el.checked}]}});state.run=response;render();}catch(err){el.checked=!el.checked;toast(err.message);}}));
  document.querySelectorAll('[data-example]').forEach(el=>el.addEventListener('click',()=>{state.goal=Object.hasOwn(state.boot.goals,el.dataset.example)?el.dataset.example:'融资组合';navigate('workspace');document.querySelector('#task-card').scrollIntoView({behavior:'smooth'});}));
  document.querySelectorAll('[data-question]').forEach(el=>el.addEventListener('click',()=>{document.querySelector('[name=question]').value=el.dataset.question;document.querySelector('[name=question]').focus();}));
  document.querySelector('#adjustment-form')?.addEventListener('submit',async ev=>{
    ev.preventDefault();const form=ev.currentTarget,button=form.querySelector('button'),target=document.querySelector('#adjustment-result');
    const changes=Object.fromEntries([...form.querySelectorAll('input')].map(x=>[x.name,Number(x.value)*Number(x.dataset.factor)]));
    button.disabled=true;target.textContent='正在重新计算…';
    try{const result=await api(`/api/runs/${state.run.id}/adjustment`,{method:'POST',body:{changes}});
      const market=state.run.outputs.analyze_industry_region?.market_decision;
      const original=market?.changed&&market?.portfolio?.available?market.portfolio:state.run.outputs.optimize_financing_portfolio;
      target.innerHTML=`<h3>调整试算结果 · 不是原报告</h3><p>${e(result.focus.summary)}</p>${marketTable(['项目','原方案','试算方案','变化（试算减原方案）'],[['新增借款','debt_total'],['用途缺口','unfunded_gap'],['一次性费用','fees_due']].map(([label,key])=>[label,money(original.funding[key]),money(result.plan.funding[key]),money(result.delta[key])]))}${result.focus.risk?.threshold?`<p>调整后每年至少需还款现金 ${e(money(result.focus.risk.threshold.minimum_cash))}；通过设定压力还需改善 ${e(money(result.focus.risk.threshold.cash_improvement))}。</p>`:''}${(result.focus.comparison?.options||[]).map(p=>`<p>${e(p.title)}：借款 ${e(money(p.debt))}，缺口 ${e(money(p.gap))}，全期限利息及费用 ${e(money(p.total_cost))}。</p>`).join('')}<p class="subtle-caption">${e(result.note)}</p>`;
    }catch(error){target.textContent=error.message;}finally{button.disabled=false;}
  });
  document.querySelector('#task-form')?.addEventListener('submit',ev=>{ev.preventDefault();saveTask(true);});
  document.querySelectorAll('#task-form [name=amount],#task-form [name=internal_funds]').forEach(el=>el.addEventListener('input',()=>{const p=taskProfile();document.querySelector('#gap-preview').textContent=money(Math.max(0,p.amount-p.internal_funds));}));
  document.querySelector('#upload-input')?.addEventListener('change',ev=>uploadFile(ev.target.files[0]));
  const drop=document.querySelector('#drop-zone');if(drop){drop.addEventListener('dragover',ev=>{ev.preventDefault();drop.classList.add('case-active');});drop.addEventListener('dragleave',()=>drop.classList.remove('case-active'));drop.addEventListener('drop',ev=>{ev.preventDefault();drop.classList.remove('case-active');uploadFile(ev.dataTransfer.files[0]);});}
  document.querySelector('[name=field-group]')?.addEventListener('change',ev=>{captureCompanyDraft();state.fieldGroup=ev.target.value;render();});
  document.querySelector('#company-form')?.addEventListener('submit',async ev=>{
    ev.preventDefault();if(!ev.currentTarget.reportValidity())return;captureCompanyDraft();
    const draft=companyDraft(),data={...draft.data},profile={...draft.profile};
    try{state.boot=await api('/api/company',{method:'POST',body:{data,profile,source:state.boot.source.startsWith('模拟')?'模拟案例 · 手动修订':'用户提供 · 手动修订'}});state.companyDraft=null;if(state.runId)await loadRun(state.runId);render();toast('全部已编辑分组已保存；已有分析保留为历史快照。');}catch(err){document.querySelector('#company-error').textContent=err.message;}
  });
  document.querySelector('#review-input')?.addEventListener('change',async ev=>{try{state.run=await api(`/api/runs/${state.run.id}`,{method:'PATCH',body:{reviewed:ev.target.checked}});render();toast(state.run.reviewed?'已记录本次人工复核。':'已取消复核标记。');}catch(err){toast(err.message);}});
  document.querySelector('#knowledge-form')?.addEventListener('submit',ev=>{ev.preventDefault();state.query=new FormData(ev.currentTarget).get('query').trim();render();});
  document.querySelector('#question-form')?.addEventListener('submit',async ev=>{ev.preventDefault();const f=new FormData(ev.currentTarget),question=f.get('question').trim();if(!question)return;const button=ev.currentTarget.querySelector('button[type=submit]');button.disabled=true;button.innerHTML='<span class="spinner"></span>正在解释';try{const answer=await api(`/api/runs/${state.run.id}/question`,{method:'POST',body:{question,consent:f.get('consent')==='on'}});state.messages.push({role:'user',content:question},{role:'assistant',content:answer.answer});render();}catch(err){toast(err.message);button.disabled=false;button.innerHTML=icon('send')+'发送';}});
  // 弹窗与抽屉：内部点击不冒泡，点击遮罩按归属关闭
  document.querySelectorAll('.dialog,.drawer').forEach(panel=>panel.addEventListener('click',ev=>ev.stopPropagation()));
  document.querySelectorAll('.dialog-backdrop').forEach(backdrop=>backdrop.addEventListener('click',ev=>{
    if(ev.target!==backdrop)return;
    if(backdrop.dataset.action==='auth-close')state.authOpen=false;
    else{state.modelOpen=false;state.modelMode=null;state.modelEditing=null;state.modelForm=null;}
    render();
  }));
  document.querySelector('.drawer-backdrop')?.addEventListener('click',ev=>{if(ev.target===ev.currentTarget){state.histOpen=false;render();}});
  // 登录 / 注册：验证码错误或口令错误后自动换图并清空验证码输入
  document.querySelector('#auth-form')?.addEventListener('submit',async ev=>{
    ev.preventDefault();const form=ev.currentTarget,button=form.querySelector('[type=submit]');button.disabled=true;
    // 注册时校验两次输入的密码一致，不一致则保留已填内容并刷新验证码
    if(state.authTab==='register'&&form.auth_password2&&form.auth_password2.value!==form.auth_password.value){
      document.querySelector('#auth-error').textContent='两次输入的密码不一致，请重新输入';
      form.auth_password2.value='';form.captchaCode.value='';await loadCaptcha();button.disabled=false;return;
    }
    const body={username:form.auth_username.value.trim(),password:form.auth_password.value,captchaId:state.authCaptcha.id,captchaCode:form.captchaCode.value.trim()};
    if(state.authTab==='register')body.nickname=form.auth_nickname?.value.trim()||'';
    try{
      const data=await api(state.authTab==='register'?'/api/auth/register':'/api/auth/login',{method:'POST',body});
      saveAuth(data);state.authOpen=false;state.userMenuOpen=false;state.authDraft={username:'',password:'',nickname:''};
      // 重新拉取 bootstrap：历史分析按账户合并，登录后立即可见该账号的分析记录
      await refreshBoot();render();
      toast(state.authTab==='register'?'注册成功，欢迎加入融智 FinBridge。':`欢迎回来，${data.user.nickname||data.user.username}。`);
    }catch(err){
      document.querySelector('#auth-error').textContent=err.message;
      form.captchaCode.value='';await loadCaptcha();
    }finally{button.disabled=false;}
  });
  // 模型配置：表单来自共享组件，值统一由 mpCollect 收集（编辑留空保留原值）
  document.querySelector('#model-form')?.addEventListener('submit',async ev=>{
    ev.preventDefault();const form=ev.currentTarget,button=form.querySelector('[type=submit]');button.disabled=true;
    const wasEdit=!!state.modelEditing;
    const body={...mpCollect(form),provider:state.modelForm.provider};
    try{
      const result=wasEdit?await api(`/api/ai/models/${state.modelEditing}`,{method:'PUT',body}):await api('/api/ai/models',{method:'POST',body});
      state.models=result.models||await api('/api/ai/models');
      state.modelMode=null;state.modelEditing=null;state.modelForm=null;await refreshBoot();render();
      toast(wasEdit?'模型配置已保存。':'模型已添加，可点击「使用」切换。');
    }catch(err){document.querySelector('#model-error').textContent=err.message;}
    finally{button.disabled=false;}
  });
}

window.addEventListener('popstate',()=>{state.page=routePage();state.mobile=false;render();});
(async()=>{try{state.page=routePage();if(state.auth.token){try{const me=await api('/api/auth/me');state.auth.user=me.user;localStorage.setItem(AUTH_USER_KEY,JSON.stringify(me.user));}catch{clearAuth();}}await refreshBoot();const id=state.runId||state.boot.active_run_id;if(id){try{await loadRun(id,true);}catch{state.runId=null;sessionStorage.removeItem('finbridge_run');}}render();}catch(err){document.querySelector('#app').innerHTML=`<div class="error-panel"><h2>暂时无法连接工作空间</h2><p>${e(err.message)}</p><button class="btn" id="reconnect">重新连接</button></div>`;document.querySelector('#reconnect').addEventListener('click',()=>location.reload());}})();

window.addEventListener('keydown',event=>{if(event.key!=='Escape')return;if(state.dialogueExpanded){document.querySelector('#expand-dialogue')?.click();document.querySelector('#expand-dialogue')?.focus({preventScroll:true});}else if(state.mobile){document.querySelector('[data-action=close-menu]')?.click();document.querySelector('.menu-btn')?.focus({preventScroll:true});}});
document.addEventListener('toggle',event=>{if(event.target.closest?.('#decision-chat'))requestAnimationFrame(updateDialogueHeight);},true);
