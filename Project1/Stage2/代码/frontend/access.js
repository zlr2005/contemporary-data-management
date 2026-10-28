import {api,escapeHtml as h,toast} from './api.js?v=20261023';

export async function accessPanel({seriesId=null,surveyId=null,questionId=null,title='',type='text'}={}){
  const sharing=Boolean(seriesId),path=sharing?`/question-series/${seriesId}/shares`:`/surveys/${surveyId}/questions/${encodeURIComponent(questionId)}/statistic-grants`;
  const dialog=document.createElement('dialog');dialog.className='picker-dialog';
  dialog.setAttribute('aria-label',sharing?'题目共享使用':'单题统计授权');document.body.append(dialog);
  let closed=false,busy=false,page=1;
  return new Promise(resolve=>{
    function close(){if(closed||busy)return;closed=true;dialog.close();dialog.remove();resolve();}
    dialog.addEventListener('cancel',e=>{e.preventDefault();close();});dialog.showModal();
    async function action(fn){if(busy)return;busy=true;dialog.querySelectorAll('button,input').forEach(el=>el.disabled=true);let error;
      try{await fn();}catch(e){error=e.message;}finally{busy=false;await load(error);}}
    async function load(error=''){
      if(closed)return;
      try{
        const data=await api(path+`?page=${page}&size=20`);if(closed)return;
        dialog.innerHTML=`<div class="toolbar"><h2>${sharing?'共享题目使用权':'授权本题统计'}</h2><button id="access-close">关闭</button></div><h3 class="answer-text">${h(title)}</h3><p class="hint">${sharing?'授权覆盖现有及后续正式版本；允许使用和派生，不开放你的问卷回答。撤销后保留原问卷引用，但禁止新增使用。':'只开放这份问卷中的当前题目，不开放整份问卷、其他题目或填写者身份。内容权限与基础统计分开设置。'}</p><form id="access-form"><label>接收者的准确用户名<input name="username" maxlength="50" required autocomplete="off"></label>${!sharing&&['text','number'].includes(type)?'<label class="check"><input name="allow_contents" type="checkbox">允许查看本题填写内容（不含账号身份）</label>':''}<button type="submit" class="primary">${sharing?'授予使用权':'保存统计授权'}</button></form><div id="access-error" class="error" role="alert">${h(error)}</div><h3 style="margin-top:24px">已发出的授权</h3>${data.items.map((item,i)=>`<section class="panel"><strong>${h(item.username)}</strong> <span class="badge">${item.status==='active'?'有效':'已撤销'}</span>${!sharing?`<p class="hint">${item.allow_contents?'基础统计及填写内容':'仅基础统计'}</p>`:''}<div class="actions">${!sharing&&item.status==='active'&&['text','number'].includes(type)?`<button data-toggle="${i}">${item.allow_contents?'改为仅基础统计':'允许查看填写内容'}</button>`:''}<button data-revoke="${i}" ${item.status==='active'?'':'disabled'}>撤销授权</button></div></section>`).join('')||'<p class="muted">尚未授予权限。</p>'}<div class="pagination"><button id="access-prev" ${page===1?'disabled':''}>上一页</button><span>第 ${page} 页</span><button id="access-next" ${page*20>=data.total?'disabled':''}>下一页</button></div>`;
        dialog.querySelector('#access-close').onclick=close;
        dialog.querySelector('#access-form').onsubmit=e=>{e.preventDefault();const values=new FormData(e.target);action(async()=>{
          const body={username:values.get('username')};if(!sharing)body.allow_contents=values.get('allow_contents')==='on';
          await api(path,{method:'PUT',body:JSON.stringify(body)});toast('授权已保存');
        });};
        dialog.querySelectorAll('[data-revoke]').forEach(b=>b.onclick=()=>{const item=data.items[Number(b.dataset.revoke)];if(!confirm(`撤销 ${item.username} 的${sharing?'题目使用权':'本题统计权'}？已有问卷和答卷保留。`))return;action(async()=>{await api(path+'/'+item.grantee_id,{method:'DELETE'});toast('授权已撤销');});});
        dialog.querySelectorAll('[data-toggle]').forEach(b=>b.onclick=()=>action(async()=>{const item=data.items[Number(b.dataset.toggle)];await api(path,{method:'PUT',body:JSON.stringify({username:item.username,allow_contents:!item.allow_contents})});toast('内容权限已更新');}));
        dialog.querySelector('#access-prev').onclick=()=>{page--;load();};dialog.querySelector('#access-next').onclick=()=>{page++;load();};
      }catch(e){if(!closed){dialog.innerHTML=`<p class="error" role="alert">${h(e.message)}</p><button id="access-retry">重试</button><button id="access-close">关闭</button>`;dialog.querySelector('#access-close').onclick=close;dialog.querySelector('#access-retry').onclick=()=>load();}}
    }
    load();
  });
}
