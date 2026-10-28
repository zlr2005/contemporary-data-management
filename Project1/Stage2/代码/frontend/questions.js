import {api,post,escapeHtml as h,toast} from './api.js?v=20261023';
import {accessPanel} from './access.js?v=20261023';

export const TYPES={single:'单选题',multiple:'多选题',text:'文本填空',number:'数字填空'};
const defaults={single:{},multiple:{},text:{format:'plain'},number:{integer_only:false}};
const uuid=()=>crypto.randomUUID();
const option=()=>({id:uuid(),label:'新选项'});
const date=v=>new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
let queuedVersion=null;
export function queueVersion(v){queuedVersion=v;}
export function takeQueuedVersion(){const v=queuedVersion;queuedVersion=null;return v;}
export const contentOf=q=>Object.fromEntries(['type','title','required','options','validation'].map(k=>[k,structuredClone(q[k])]));
export function contentSignature(q){
  const ordered=value=>Array.isArray(value)?value.map(ordered):value!==null&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,ordered(value[k])])):value;
  return JSON.stringify(ordered(contentOf(q)));
}

function hints(q){
  const c=q.validation, parts=[q.required?'必答':'选答'];
  for(const [key,label] of Object.entries({min_choices:'至少选',max_choices:'最多选',exact_choices:'恰好选',min_length:'最少字数',max_length:'最多字数',min_value:'最小值',max_value:'最大值'})){
    if(c[key]!=null)parts.push(`${label} ${c[key]}`);
  }
  if(c.integer_only)parts.push('只允许整数');
  if(c.format==='digits')parts.push('纯数字字符，保留前导零');
  return parts.join(' · ');
}
export function contentPreview(q){
  return `<h3 class="answer-text">${h(q.title)}</h3><p class="hint">${h(TYPES[q.type])} · ${h(hints(q))}</p>${q.options.length?`<ol class="content-list">${q.options.map(o=>`<li>${h(o.label)}</li>`).join('')}</ol>`:''}`;
}

export async function versionPicker({seriesId=null,exclude=[],source='owned'}={}){
  const dialog=document.createElement('dialog');dialog.className='picker-dialog';
  dialog.setAttribute('aria-label','选择题目版本');document.body.append(dialog);
  let page=1,selectedSeries=seriesId,selectedBank=null,scope=source,keyword='',closed=false,loadId=0;
  return new Promise(resolve=>{
    const finish=value=>{if(closed)return;closed=true;dialog.close();dialog.remove();resolve(value);};
    dialog.addEventListener('cancel',e=>{e.preventDefault();finish(null);});
    dialog.addEventListener('close',()=>finish(null));
    dialog.showModal();
    async function load(){
      const request=++loadId;
      dialog.innerHTML='<p role="status">正在加载题目…</p><button id="picker-cancel">取消</button>';
      dialog.querySelector('#picker-cancel').onclick=()=>finish(null);
      try{
        let data;
        if(selectedSeries)data=await api(`/question-series/${selectedSeries}/versions?page=${page}&size=10`);
        else if(selectedBank){const bank=await api(`/question-banks/${selectedBank}`);data={items:bank.items.slice((page-1)*10,page*10).map(item=>({...item,_id:item.version_id})),total:bank.items.length};}
        else data=await api(scope==='banks'?`/question-banks?page=${page}&size=10`:`/question-series?page=${page}&size=10&scope=${scope}&keyword=${encodeURIComponent(keyword)}`);
        if(closed||request!==loadId)return;
        const picking=selectedSeries||selectedBank;
        dialog.innerHTML=`<div class="toolbar"><h2>${selectedSeries?'选择具体版本':selectedBank?'从题库选题':'选择题目来源'}</h2><button id="picker-cancel">取消</button></div>${!seriesId?`<div class="tabs"><button data-scope="owned" class="${scope==='owned'?'active':''}">我的题目</button><button data-scope="shared" class="${scope==='shared'?'active':''}">共享给我的</button><button data-scope="banks" class="${scope==='banks'?'active':''}">我的题库</button></div>`:''}${!picking&&scope!=='banks'?`<form id="picker-search" class="actions"><label class="visually-hidden" for="picker-keyword">题目名称</label><input id="picker-keyword" maxlength="200" value="${h(keyword)}" placeholder="搜索题目名称"><button>搜索</button></form>`:picking&&!seriesId?'<button id="picker-back">返回来源列表</button>':''}<p class="hint">选取只加入当前页面，保存问卷或题库后才生效；问卷跳转需另行设置。</p><div>${data.items.map((item,i)=>picking?`<section class="panel"><span class="badge">v${item.version_no}</span>${contentPreview(item.content)}${item.unavailable_reason?`<p class="hint">${h(item.unavailable_reason)}</p>`:''}<button data-pick="${i}" ${exclude.includes(item._id)||item.actions?.can_select===false?'disabled':''}>${exclude.includes(item._id)?'此版本已在列表中':item.actions?.can_select===false?'当前不可选用':'选用此版本'}</button></section>`:scope==='banks'?`<section class="panel"><h3>${h(item.name)}</h3><p class="hint">${item.member_count} 个题目版本</p><button data-bank="${item._id}">查看题库并选题</button></section>`:`<section class="panel"><h3>${h(item.name)}</h3><p>${h(item.latest_version.content.title)}</p><p class="hint">${h(TYPES[item.latest_version.content.type])} · 最新 v${item.latest_version.version_no}${scope==='shared'?' · 来自 '+h(item.owner.username):''}</p><button data-series="${item._id}">查看版本并选择</button></section>`).join('')||'<p class="empty">暂无符合条件的题目或题库。</p>'}</div><div class="error" id="picker-error" role="alert"></div><div class="pagination"><button id="picker-prev" ${page===1?'disabled':''}>上一页</button><span>第 ${page} 页</span><button id="picker-next" ${page*10>=data.total?'disabled':''}>下一页</button></div>`;
        dialog.querySelector('#picker-cancel').onclick=()=>finish(null);
        dialog.querySelector('#picker-back')?.addEventListener('click',()=>{selectedSeries=null;selectedBank=null;page=1;load();});
        dialog.querySelectorAll('[data-scope]').forEach(b=>b.onclick=()=>{scope=b.dataset.scope;selectedBank=selectedSeries=null;page=1;load();});
        dialog.querySelector('#picker-search')?.addEventListener('submit',e=>{e.preventDefault();keyword=dialog.querySelector('#picker-keyword').value;page=1;load();});
        dialog.querySelectorAll('[data-series]').forEach(b=>b.onclick=()=>{selectedSeries=b.dataset.series;page=1;load();});
        dialog.querySelectorAll('[data-bank]').forEach(b=>b.onclick=()=>{selectedBank=b.dataset.bank;page=1;load();});
        dialog.querySelectorAll('[data-pick]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const item=data.items[Number(b.dataset.pick)];const [v,s]=await Promise.all([api(`/question-versions/${item._id}`),api(`/question-series/${item.series_id}`)]);if(!s.actions.can_select)throw new Error('题目当前不可选用');finish({...v,source_actions:s.actions});}catch(e){if(!closed){dialog.querySelector('#picker-error').textContent=e.message;b.disabled=false;}}});
        dialog.querySelector('#picker-prev').onclick=()=>{page--;load();};
        dialog.querySelector('#picker-next').onclick=()=>{page++;load();};
      }catch(e){if(!closed&&request===loadId){dialog.innerHTML=`<p class="error" role="alert">${h(e.message)}</p><button id="retry">重试</button><button id="cancel">取消</button>`;dialog.querySelector('#retry').onclick=load;dialog.querySelector('#cancel').onclick=()=>finish(null);}}
    }
    load();
  });
}

export async function questionList(root){
  let page=1,keyword='',status='active',scope='owned',alive=true,loadId=0;
  async function load(){
    const request=++loadId;
    try{
      const data=await api(`/question-series?page=${page}&size=10&status=${status}&scope=${scope}&keyword=${encodeURIComponent(keyword)}`);
      if(!alive||request!==loadId)return;
      root.innerHTML=`<div class="toolbar"><div><div class="eyebrow">QUESTION LIBRARY</div><h1>题目管理</h1><p class="muted">保存一个版本，在多份问卷中重复使用。</p></div><a class="button primary" href="/#question-new">＋ 新建题目</a></div><form id="question-search" class="panel filter-row"><label>题目名称<input name="keyword" value="${h(keyword)}" placeholder="输入名称搜索"></label><label>状态<select name="status"><option value="active" ${status==='active'?'selected':''}>可用题目</option><option value="archived" ${status==='archived'?'selected':''}>已归档</option><option value="all" ${status==='all'?'selected':''}>全部</option></select></label><button type="submit">查询</button></form><p class="hint">共 ${data.total} 个题目系列。修改会生成新版本，已发布问卷保持原版本。</p><div class="cards">${data.items.map(s=>`<article class="card"><div><span class="badge">${s.status==='active'?'可用':'已归档'}</span> <span class="badge">最新 v${s.latest_version.version_no}</span></div><h2>${h(s.name)}</h2><p class="answer-text">${h(s.latest_version.content.title)}</p><p class="hint">${h(TYPES[s.latest_version.content.type])} · ${s.version_count} 个版本</p><a class="button" href="/#question/${s._id}">查看版本与使用情况</a></article>`).join('')||'<p class="empty">暂无符合条件的题目，可以先新建题目，或在问卷中直接编题后保存。</p>'}</div><div class="pagination"><button id="prev" ${page===1?'disabled':''}>上一页</button><span>第 ${page} 页</span><button id="next" ${page*10>=data.total?'disabled':''}>下一页</button></div>`;
      root.querySelector('#question-search').onsubmit=e=>{e.preventDefault();const f=new FormData(e.target);keyword=f.get('keyword');status=scope==='shared'?'active':f.get('status');page=1;load();};
      const tabs=document.createElement('div');tabs.className='tabs';tabs.innerHTML=`<button data-tab="owned" class="${scope==='owned'?'active':''}">我的题目</button><button data-tab="shared" class="${scope==='shared'?'active':''}">共享给我的</button>`;
      root.querySelector('#question-search').before(tabs);tabs.querySelectorAll('button').forEach(b=>b.onclick=()=>{scope=b.dataset.tab;status='active';page=1;load();});
      if(scope==='shared'){root.querySelector('[name=status]').disabled=true;root.querySelectorAll('.card').forEach((card,i)=>{const p=document.createElement('p');p.className='hint';p.textContent='来自 '+data.items[i].owner.username;card.append(p);});}
      root.querySelector('#prev').onclick=()=>{page--;load();};root.querySelector('#next').onclick=()=>{page++;load();};
    }catch(e){if(alive)toast(e.message);}
  }
  await load();return ()=>{alive=false;};
}

export async function questionDetail(root,sid){
  let page=1,usagePage=1,alive=true,busy=false;
  const retryKeys=new Map();
  async function run(button,fn){if(busy)return;busy=true;button.disabled=true;try{await fn();}catch(e){toast(e.message);}finally{busy=false;if(button.isConnected)button.disabled=false;}}
  async function load(){
    const [s,history,uses]=await Promise.all([api(`/question-series/${sid}`),api(`/question-series/${sid}/versions?page=${page}&size=10`),api(`/question-series/${sid}/usages?page=${usagePage}&size=10`)]);
    if(!alive)return;
    root.innerHTML=`<div class="toolbar"><div><div class="eyebrow">VERSION HISTORY</div><h1>${h(s.name)}</h1><p class="muted">${s.version_count} 个版本 · ${s.status==='active'?'可用':'已归档'}</p></div><a href="/#questions">返回题目管理</a></div><div class="actions"><button id="rename">修改管理名称</button><button id="archive">${s.status==='active'?'归档题目':'恢复为可用'}</button></div><p class="hint">正式版本不能覆盖；新版本不会自动替换已有问卷。${s.forked_from_version_id?'此题由已有版本派生，保留来源记录。':''}</p><h2>版本历史</h2>${history.items.map((v,i)=>`<section class="panel"><div class="title-line"><strong>v${v.version_no}</strong><span class="muted">${date(v.created_at)}</span><span class="badge">${({create:'初次保存',edit:'修改',restore:'恢复',fork:'派生',migrate:'旧题迁移'})[v.operation]}</span></div><p class="hint">${v.parent_version_no?`基于 v${v.parent_version_no}`:'此系列的首个版本'}${v.restored_from_version_no?` · 恢复 v${v.restored_from_version_no} 的内容`:''}</p>${contentPreview(v.content)}<div class="actions"><a class="button" href="/#question/${sid}/edit/${v._id}" ${s.status==='active'?'':'hidden'}>基于此版本编辑</a><button data-new-survey="${i}" ${s.status==='active'?'':'disabled'}>加入新问卷</button><button data-restore="${i}" ${s.status==='active'?'':'disabled'}>以此内容创建新版本</button></div></section>`).join('')}<div class="pagination"><button id="prev-version" ${page===1?'disabled':''}>上一页</button><span>第 ${page} 页</span><button id="next-version" ${page*10>=history.total?'disabled':''}>下一页</button></div><h2>问卷使用情况</h2><p class="hint">共 ${uses.visible_total} 份问卷；同一份问卷可以使用同一系列的不同版本。</p>${uses.visible_items.map(u=>`<section class="panel"><h3>${h(u.title)}</h3><p class="hint">${({draft:'草稿',published:'已发布',closed:'已关闭'})[u.status]}</p><div class="actions"><a class="button" href="/#edit/${u.survey_id}">查看问卷</a><a class="button" href="/#stats/${u.survey_id}">查看原问卷统计</a></div></section>`).join('')||'<p class="muted">暂未被保存的问卷使用。</p>'}<div class="pagination"><button id="prev-use" ${usagePage===1?'disabled':''}>上一页</button><span>第 ${usagePage} 页</span><button id="next-use" ${usagePage*10>=uses.visible_total?'disabled':''}>下一页</button></div>`;
    if(s.forked_from_version_id){const note=document.createElement('p');note.className='hint';note.textContent=s.forked_from?`派生来源：${s.forked_from.name} · v${s.forked_from.version_no}`:'派生来源标识已保留，当前没有源题目历史的查看权限。';root.querySelector('.toolbar').after(note);}
    if(s.actions.can_manage){
      root.querySelector('#rename').onclick=e=>run(e.target,async()=>{const name=prompt('题目管理名称',s.name);if(name===null)return;await api(`/question-series/${sid}`,{method:'PATCH',body:JSON.stringify({name})});await load();});
      root.querySelector('#archive').onclick=e=>run(e.target,async()=>{const status=s.status==='active'?'archived':'active';if(status==='archived'&&!confirm('归档后不能新增使用或版本，已有问卷保持可用。确定归档吗？'))return;await api(`/question-series/${sid}`,{method:'PATCH',body:JSON.stringify({status})});await load();});
      const share=document.createElement('button');share.id='share-question';share.textContent='共享使用';root.querySelector('#rename').parentElement.append(share);
      share.onclick=()=>accessPanel({seriesId:sid,title:s.name});
    }else{root.querySelector('#rename').remove();root.querySelector('#archive').remove();root.querySelectorAll('[data-restore]').forEach(b=>b.remove());root.querySelectorAll('a[href*="/edit/"]').forEach(a=>a.textContent='派生为我的题目');}
    root.querySelectorAll('[data-new-survey]').forEach((button,i)=>{
      const v=history.items[i],actions=button.parentElement;
      const add=document.createElement('button');add.textContent='加入题库';add.disabled=!s.actions.can_select;add.onclick=()=>{queueVersion(v);location.hash='banks';};actions.append(add);
      const stats=document.createElement('a');stats.className='button';stats.textContent='跨问卷统计';stats.href=`/#question-stats/${v._id}`;actions.append(stats);
    });
    if(uses.restricted_survey_count>0){const note=document.createElement('p');note.className='hint';note.textContent=`另有 ${uses.restricted_survey_count} 份问卷在使用，尚未授权你查看其明细。`;root.querySelectorAll('h2').forEach(el=>{if(el.textContent==='问卷使用情况')el.after(note);});}
    for(const u of uses.visible_items){if(u.owner_context!=='owned'){const link=root.querySelector(`a[href="/#edit/${u.survey_id}"]`);if(link)link.parentElement.innerHTML=`<a class="button" href="/#question-stats/${u.version_ids[0]}">查看已授权的单题统计</a>`;}}
    root.querySelectorAll('[data-new-survey]').forEach(b=>b.onclick=()=>{queuedVersion=history.items[Number(b.dataset.newSurvey)];location.hash='new';});
    root.querySelectorAll('[data-restore]').forEach(b=>b.onclick=()=>run(b,async()=>{
      const v=history.items[Number(b.dataset.restore)];
      if(!confirm(`将以 v${v.version_no} 内容创建新版本，基准为最新 v${s.latest_version.version_no}；已有版本和问卷不会更改。继续吗？`))return;
      const identity=`${s.latest_version._id}:${v._id}`;if(!retryKeys.has(identity))retryKeys.set(identity,uuid());
      const result=await post(`/question-series/${sid}/restorations`,{base_version_id:s.latest_version._id,restore_version_id:v._id,request_key:retryKeys.get(identity)});
      retryKeys.delete(identity);toast(`已创建 v${result.version_no}，已有问卷保持不变`);page=1;await load();
    }));
    for(const [id,fn] of [['prev-version',()=>page--],['next-version',()=>page++],['prev-use',()=>usagePage--],['next-use',()=>usagePage++]])root.querySelector('#'+id).onclick=e=>run(e.target,async()=>{fn();await load();});
  }
  await load();return ()=>{alive=false;};
}

export async function questionEditor(root,sid=null,vid=null){
  const series=sid?await api(`/question-series/${sid}`):null;
  if(series&&!series.actions.can_edit&&!series.actions.can_fork)throw new Error('题目当前不能修改或派生');
  const source=vid?await api(`/question-versions/${vid}`):null;
  if(source&&source.series_id!==sid)throw new Error('版本不属于当前题目');
  let q=source?structuredClone(source.content):{type:'text',title:'',required:false,options:[],validation:{format:'plain'}};
  const forkMode=Boolean(source&&!series.actions.can_manage);
  let name=forkMode?(series.name.slice(0,190)+'（我的副本）'):series?.name||'',dirty=false,saving=false,requestKey=null,requestText=null;
  const read=()=>{
    name=root.querySelector('#q-name').value;q.type=root.querySelector('#q-type').value;
    q.title=root.querySelector('#q-title').value;q.required=root.querySelector('#q-required').checked;
    q.options=[...root.querySelectorAll('[data-option]')].map((el,i)=>({...q.options[i],label:el.value}));
    const previous=q.validation;q.validation={};root.querySelectorAll('[data-validation]').forEach(el=>{
      const value=el.type==='checkbox'?el.checked:el.type==='number'?(el.value===''?null:Number(el.value)):el.value;
      if(value!==null||Object.hasOwn(previous,el.dataset.validation))q.validation[el.dataset.validation]=value;
    });
  };
  const field=(label,key,type='number')=>`<label>${label}<input data-validation="${key}" type="${type}" step="any" value="${h(q.validation[key]??'')}"></label>`;
  function render(){
    let validation='';
    if(q.type==='multiple')validation=`<div class="row three">${field('至少选择','min_choices')}${field('最多选择','max_choices')}${field('恰好选择','exact_choices')}</div>`;
    if(q.type==='text')validation=`<div class="row">${field('最少字数','min_length')}${field('最多字数','max_length')}</div><label>文本格式<select data-validation="format"><option value="plain">普通文本</option><option value="digits" ${q.validation.format==='digits'?'selected':''}>纯数字字符（如手机号）</option></select></label>`;
    if(q.type==='number')validation=`<div class="row">${field('最小值','min_value')}${field('最大值','max_value')}</div><label class="check"><input data-validation="integer_only" type="checkbox" ${q.validation.integer_only?'checked':''}>必须为整数</label>`;
    root.innerHTML=`<div class="toolbar"><div><div class="eyebrow">QUESTION EDITOR</div><h1>${source?`基于 v${source.version_no} 编辑`:'新建题目'}</h1><p class="muted">保存后生成正式版本，不自动修改问卷或题库。</p></div><a href="/#${sid?'question/'+sid:'questions'}">返回</a></div><form id="question-form" class="panel"><label for="q-name">管理名称</label><input id="q-name" maxlength="200" required ${source?'readonly':''} value="${h(name)}"><div class="row"><label>题型<select id="q-type">${Object.entries(TYPES).map(([key,label])=>`<option value="${key}" ${q.type===key?'selected':''}>${label}</option>`).join('')}</select></label><label class="check"><input id="q-required" type="checkbox" ${q.required?'checked':''}>必答</label></div><label for="q-title">题目标题</label><input id="q-title" maxlength="500" value="${h(q.title)}" required>${q.options.map((o,i)=>`<div class="option-row"><input data-option value="${h(o.label)}" aria-label="选项 ${i+1}" maxlength="200" required><button type="button" data-remove="${i}">删除选项</button></div>`).join('')}${['single','multiple'].includes(q.type)?'<button type="button" id="add-option">添加选项</button>':''}${validation}<p class="hint">题序和跳转规则在具体问卷中设置，不保存在可复用题目版本内。</p><div class="error" id="question-error" role="alert"></div><button class="primary" type="submit">${source?'保存为新版本':'保存为 v1'}</button></form>`;
    root.querySelector('#question-form').oninput=()=>{dirty=true;};
    if(forkMode){root.querySelector('h1').textContent=`从共享 v${source.version_no} 派生`;root.querySelector('#q-name').readOnly=false;root.querySelector('[type=submit]').textContent='保存为我的题目 v1';}
    root.querySelector('#q-type').onchange=e=>{read();q.type=e.target.value;q.options=['single','multiple'].includes(q.type)?[option(),option()]:[];q.validation=structuredClone(defaults[q.type]);dirty=true;render();};
    root.querySelector('#add-option')?.addEventListener('click',()=>{read();q.options.push(option());dirty=true;render();});
    root.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{read();q.options.splice(Number(b.dataset.remove),1);dirty=true;render();});
    root.querySelector('#question-form').onsubmit=async e=>{
      e.preventDefault();if(saving)return;read();const button=e.target.querySelector('[type=submit]');saving=true;button.disabled=true;
      const body=source&&!forkMode?{parent_version_id:source._id,content:q}:{name,content:q};
      const text=JSON.stringify(body);if(requestText!==text){requestText=text;requestKey=uuid();}
      try{const result=await post(forkMode?`/question-versions/${source._id}/forks`:source?`/question-series/${sid}/versions`:'/question-series',{...body,request_key:requestKey});dirty=false;toast(forkMode?'派生题目及 v1 已保存':source?`已保存为 v${result.version_no}`:'题目和 v1 已保存');location.hash=`question/${source&&!forkMode?sid:result.series._id}`;}
      catch(error){root.querySelector('#question-error').textContent=error.message;}
      finally{saving=false;button.disabled=false;}
    };
  }
  render();const cleanup=()=>{};cleanup.isDirty=()=>dirty;cleanup.isBusy=()=>saving;return cleanup;
}
