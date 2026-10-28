import {api,post,escapeHtml as h,toast,bindForm} from './api.js?v=20261023';
import {editor} from './editor.js?v=20261023';
import {fill} from './fill.js?v=20261023';
import {statistics} from './stats.js?v=20261023';
import {questionList,questionDetail,questionEditor} from './questions.js?v=20261023';
import {bankList,bankDetail} from './banks.js?v=20261023';
import {crossStatsList,crossStatsDetail} from './cross-stats.js?v=20261023';
const root=document.querySelector('#app');
let currentUser=null,cleanup=null,listPage=1;
let acceptedUrl=location.href,skipUnload=false,routeGeneration=0;
const labels={draft:'草稿',published:'已发布',closed:'已关闭'};

function account(){
  document.querySelector('#workspace-nav').hidden=!currentUser;
  const el=document.querySelector('#account');
  el.innerHTML=currentUser?`<span>${h(currentUser.username)}</span><button class="link" id="logout">退出登录</button>`:'<span class="muted">欢迎来到问序</span>';
  el.querySelector('#logout')?.addEventListener('click',()=>{if(cleanup?.isBusy?.()){toast('正在保存，请稍候');return;}if(cleanup?.isDirty?.()&&!confirm('有未保存的修改，仍要退出登录吗？'))return;skipUnload=true;sessionStorage.removeItem('token');currentUser=null;location.href='/';});
}
function auth(register=false){
  root.innerHTML=`<div class="auth"><div class="auth-intro"><div class="eyebrow">WELCOME TO WENXU</div><h1>从一个好问题开始</h1><p class="muted">创建问卷，收集回答，发现答案。</p></div><div class="panel"><div class="tabs"><button id="login-tab" class="${register?'':'active'}">登录</button><button id="register-tab" class="${register?'active':''}">注册</button></div><form id="auth-form"><label for="username">用户名</label><input id="username" name="username" maxlength="50" required autocomplete="username"><label for="password">密码</label><input id="password" name="password" type="password" minlength="8" maxlength="128" required autocomplete="${register?'new-password':'current-password'}"><p class="hint">密码至少 8 个字符。填写问卷也需要先登录。</p><div class="error" role="alert"></div><button type="submit" class="primary full">${register?'创建账号':'登录'}</button></form></div></div>`;
  root.querySelector('#login-tab').onclick=()=>auth(false);root.querySelector('#register-tab').onclick=()=>auth(true);
  bindForm(root.querySelector('form'),async data=>{
    const credentials={username:data.get('username'),password:data.get('password')};
    if(register)await post('/auth/register',credentials);
    const result=await post('/auth/login',credentials);sessionStorage.setItem('token',result.access_token);currentUser=result.user;
    account();await route();
  });
}
async function dashboard(target){
  const root=target;
  const data=await api(`/surveys?page=${listPage}&size=10`);
  root.innerHTML=`<div class="toolbar"><div><div class="eyebrow">MY WORKSPACE</div><h1>我的问卷</h1><p class="muted">记录好奇，听见更多声音。共 ${data.total} 份问卷。</p></div><button class="primary" id="create">＋ 创建问卷</button></div>${data.items.length?`<div class="cards">${data.items.map(s=>{const expired=s.status==='published'&&s.deadline_at&&new Date(s.deadline_at)<=new Date();return `<article class="card"><div><span class="badge ${h(s.status)}">${expired?'已截止':labels[s.status]}</span> <small>${s.allow_anonymous?'匿名':'实名'} · ${s.allow_repeat?'允许重复':'每人一次'}</small></div><h2>${h(s.title)}</h2><p class="muted answer-text">${h(s.description||'暂无说明')}</p><p class="hint">创建于 ${new Date(s.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}${s.deadline_at?`<br>截止于 ${new Date(s.deadline_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}`:''}</p><div class="actions"><button data-edit="${s._id}">编辑</button><button data-preview="${s._id}">预览</button><button data-stats="${s._id}">统计</button>${s.status==='published'?`<button data-share="${h(s.share_code)}">分享链接</button><button class="danger" data-close="${s._id}">关闭</button>`:''}</div></article>`;}).join('')}</div>`:'<div class="empty"><div class="success-mark">＋</div><h2>你的第一份问卷，从这里开始</h2><p class="muted">支持选择题、填空题，以及根据答案跳转。</p><button class="primary" id="create-empty">创建第一份问卷</button></div>'}<div class="pagination"><button id="prev-page" ${listPage<=1?'disabled':''}>上一页</button><span class="muted">第 ${listPage} 页</span><button id="next-page" ${listPage*10>=data.total?'disabled':''}>下一页</button></div>`;
  root.querySelector('#create').onclick=()=>location.hash='new';root.querySelector('#create-empty')?.addEventListener('click',()=>location.hash='new');
  root.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>location.hash=`edit/${b.dataset.edit}`);
  root.querySelectorAll('[data-preview]').forEach(b=>b.onclick=()=>location.hash=`preview/${b.dataset.preview}`);
  root.querySelectorAll('[data-stats]').forEach(b=>b.onclick=()=>location.hash=`stats/${b.dataset.stats}`);
  root.querySelectorAll('[data-share]').forEach(b=>b.onclick=async()=>{const url=location.origin+'/survey/'+b.dataset.share;try{await navigator.clipboard.writeText(url);toast('分享链接已复制');}catch{prompt('复制问卷链接',url);}});
  root.querySelectorAll('[data-close]').forEach(b=>b.onclick=async()=>{if(!confirm('关闭后将不再接收答卷，确定关闭吗？'))return;try{await post(`/surveys/${b.dataset.close}/close`);toast('问卷已关闭');await dashboard(root);}catch(e){toast(e.message);}});
  root.querySelector('#prev-page').onclick=()=>{listPage--;dashboard(root).catch(e=>toast(e.message));};
  root.querySelector('#next-page').onclick=()=>{listPage++;dashboard(root).catch(e=>toast(e.message));};
}
async function route(){
  if(cleanup?.isBusy?.()){history.replaceState(null,'',cleanup.currentUrl?.()||acceptedUrl);toast('正在保存，请稍候');return;}
  if(cleanup?.isDirty?.()&&!confirm('有未保存的修改，仍要离开吗？')){history.replaceState(null,'',cleanup.currentUrl?.()||acceptedUrl);return;}
  acceptedUrl=location.href;
  const generation=++routeGeneration,viewRoot=document.createElement('div');
  cleanup?.();cleanup=null;viewRoot.innerHTML='<p class="muted">正在加载…</p>';root.replaceChildren(viewRoot);
  try{
    if(!sessionStorage.getItem('token')){auth();return;}
    if(!currentUser){currentUser=await api('/auth/me');account();}
    if(generation!==routeGeneration)return;
    const code=location.pathname.startsWith('/survey/')?location.pathname.split('/')[2]:null;
    if(code){await fill(viewRoot,code);return;}
    const [view,id,action,versionId]=location.hash.slice(1).split('/');
    let nextCleanup;
    if(view==='new'||view==='edit')nextCleanup=await editor(viewRoot,view==='new'?null:id,()=>location.hash='');
    else if(view==='preview')await fill(viewRoot,id,true);
    else if(view==='stats')await statistics(viewRoot,id);
    else if(view==='questions')nextCleanup=await questionList(viewRoot);
    else if(view==='question-new')nextCleanup=await questionEditor(viewRoot);
    else if(view==='question'&&action==='edit')nextCleanup=await questionEditor(viewRoot,id,versionId);
    else if(view==='question')nextCleanup=await questionDetail(viewRoot,id);
    else if(view==='banks')nextCleanup=await bankList(viewRoot);
    else if(view==='bank')nextCleanup=await bankDetail(viewRoot,id);
    else if(view==='question-stats')nextCleanup=await(id?crossStatsDetail(viewRoot,id):crossStatsList(viewRoot));
    else await dashboard(viewRoot);
    if(generation===routeGeneration)cleanup=nextCleanup;else nextCleanup?.();
  }catch(e){if(generation!==routeGeneration)return;if(e.status===401){currentUser=null;account();auth();}else viewRoot.innerHTML=`<div class="empty"><h2>暂时无法打开</h2><p class="error">${h(e.message)}</p><a href="/">返回首页</a></div>`;}
}
window.addEventListener('beforeunload',e=>{if(!skipUnload&&(cleanup?.isDirty?.()||cleanup?.isBusy?.())){e.preventDefault();e.returnValue='';}});
window.addEventListener('hashchange',route);account();route();
