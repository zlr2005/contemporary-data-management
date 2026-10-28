import {api,post,escapeHtml as h,toast} from './api.js?v=20261023';
import {versionPicker,contentPreview,takeQueuedVersion,queueVersion} from './questions.js?v=20261023';

export async function bankList(root){
  let page=1,alive=true,busy=false,dirty=false,pending=takeQueuedVersion();
  async function load(){
    const data=await api(`/question-banks?page=${page}&size=10`);if(!alive)return;
    root.innerHTML=`<div class="toolbar"><div><div class="eyebrow">QUESTION BANKS</div><h1>我的题库</h1><p class="muted">按用途整理题目，成员固定到具体版本。</p></div></div>${pending?`<div class="notice">待加入：${h(pending.content.title)} · v${pending.version_no}。选择一个题库后，还需点击“保存题库”。<button id="cancel-pending">取消待加入题目</button></div>`:''}<form id="bank-create" class="panel"><h2>创建题库</h2><label>题库名称<input name="name" maxlength="200" required></label><label>说明<textarea name="description" maxlength="5000"></textarea></label><div class="error" id="bank-error" role="alert"></div><button type="submit" class="primary">创建题库</button></form><div class="cards">${data.items.map(b=>`<article class="card"><h2>${h(b.name)}</h2><p class="answer-text">${h(b.description)}</p><p class="hint">${b.member_count} 个题目版本</p><a class="button" data-bank="${b._id}" href="/#bank/${b._id}">${pending?'选择此题库':'管理题库'}</a></article>`).join('')||'<p class="empty">还没有题库，可以先创建一个。</p>'}</div><div class="pagination"><button id="bank-prev" ${page===1?'disabled':''}>上一页</button><span>第 ${page} 页</span><button id="bank-next" ${page*10>=data.total?'disabled':''}>下一页</button></div>`;
    root.querySelector('#cancel-pending')?.addEventListener('click',e=>{pending=null;e.target.parentElement.remove();root.querySelectorAll('[data-bank]').forEach(a=>a.textContent='管理题库');});
    root.querySelector('#bank-create').oninput=()=>{dirty=true;};
    root.querySelector('#bank-create').onsubmit=async e=>{e.preventDefault();if(busy)return;busy=true;const button=e.target.querySelector('button');button.disabled=true;const values=new FormData(e.target);
      try{const made=await post('/question-banks',{name:values.get('name'),description:values.get('description')});dirty=false;if(pending)queueVersion(pending);location.hash=`bank/${made._id}`;}
      catch(error){root.querySelector('#bank-error').textContent=error.message;}finally{busy=false;button.disabled=false;}};
    root.querySelectorAll('[data-bank]').forEach(a=>a.onclick=()=>{if(pending)queueVersion(pending);});
    for(const [id,delta] of [['bank-prev',-1],['bank-next',1]])root.querySelector('#'+id).onclick=async()=>{if(dirty&&!confirm('尚有未保存的题库名称或说明，仍要翻页吗？'))return;dirty=false;page+=delta;try{await load();}catch(e){toast(e.message);}};
  }
  await load();const cleanup=()=>{alive=false;};cleanup.isDirty=()=>dirty;cleanup.isBusy=()=>busy;return cleanup;
}

export async function bankDetail(root,bid){
  let bank=await api(`/question-banks/${bid}`),dirty=false,busy=false;
  const addVersion=v=>{
    if(bank.items.some(i=>i.version_id===v._id)){toast('此版本已经在题库中');return;}
    bank.items.push({series_id:v.series_id,version_id:v._id,content:structuredClone(v.content),version_no:v.version_no,
      source_actions:v.source_actions,actions:{can_select:true,can_update:false,can_view_history:true}});dirty=true;
  };
  const pending=takeQueuedVersion();if(pending)addVersion(pending);
  function sync(){bank.name=root.querySelector('#bank-name').value;bank.description=root.querySelector('#bank-description').value;}
  function render(error=''){
    root.innerHTML=`<div class="toolbar"><div><div class="eyebrow">BANK EDITOR</div><h1>${h(bank.name)}</h1><p class="muted">更新题库不会替换已有问卷中的版本。</p></div><a href="/#banks">返回题库列表</a></div><section class="panel"><label for="bank-name">题库名称</label><input id="bank-name" value="${h(bank.name)}" maxlength="200"><label for="bank-description">说明</label><textarea id="bank-description" maxlength="5000">${h(bank.description)}</textarea><div class="actions"><button id="bank-add">加入题目</button><button id="bank-save" class="primary">保存题库</button><button id="bank-delete" class="danger">删除题库</button></div><p class="hint">${bank.items.length} / 500 个题目版本 · ${dirty?'有未保存修改':'已保存'}</p><div class="error" id="bank-error" role="alert">${h(error)}</div></section>${bank.items.map((item,i)=>`<section class="panel"><span class="badge">v${item.version_no??'—'}</span>${contentPreview(item.content)}<p class="hint">${h(item.unavailable_reason||'')}${item.actions.can_update?' · 有新版本可更新':''}</p><div class="actions"><button data-update="${i}" ${item.actions.can_select?'':'disabled'}>选择版本更新</button><button data-use="${i}" ${item.actions.can_select?'':'disabled'}>加入新问卷</button><button data-remove="${i}" class="danger">移出题库</button></div></section>`).join('')||'<p class="empty">题库暂无成员，点击“加入题目”选择已有版本。</p>'}`;
    root.querySelector('#bank-add').onclick=async()=>{if(busy)return;sync();const v=await versionPicker({exclude:bank.items.map(i=>i.version_id)});if(v){addVersion(v);render();}};
    root.querySelector('#bank-save').onclick=()=>save();
    root.querySelector('#bank-delete').onclick=async()=>{if(busy||!confirm('删除题库容器及未保存编辑？题目历史、已有问卷和答卷会保留。'))return;busy=true;
      try{await api(`/question-banks/${bid}`,{method:'DELETE',body:JSON.stringify({revision:bank.revision})});dirty=false;busy=false;toast('题库已删除，题目与问卷保留');location.hash='banks';}catch(e){busy=false;render(e.message);}};
    root.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{if(busy)return;sync();bank.items.splice(Number(b.dataset.remove),1);dirty=true;render();});
    root.querySelectorAll('[data-update]').forEach(b=>b.onclick=async()=>{if(busy)return;sync();const i=Number(b.dataset.update),old=bank.items[i];const v=await versionPicker({seriesId:old.series_id,exclude:bank.items.filter((_,n)=>n!==i).map(q=>q.version_id)});if(v){bank.items[i]={series_id:v.series_id,version_id:v._id,version_no:v.version_no,content:v.content,source_actions:v.source_actions,actions:{can_select:true,can_update:false}};dirty=true;render();}});
    root.querySelectorAll('[data-use]').forEach(b=>b.onclick=()=>{if(busy)return;const item=bank.items[Number(b.dataset.use)];queueVersion({...item,_id:item.version_id});location.hash='new';});
  }
  async function save(){if(busy)return;sync();busy=true;root.querySelectorAll('button,input,textarea').forEach(el=>el.disabled=true);let error='';
    try{bank=await api(`/question-banks/${bid}`,{method:'PUT',body:JSON.stringify({name:bank.name,description:bank.description,version_ids:bank.items.map(i=>i.version_id),revision:bank.revision})});dirty=false;toast('题库已保存');}
    catch(e){error=e.message;}finally{busy=false;render(error);}}
  root.oninput=()=>{dirty=true;};render();const cleanup=()=>{root.oninput=null;};cleanup.isDirty=()=>dirty;cleanup.isBusy=()=>busy;return cleanup;
}
