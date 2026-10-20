import {api,escapeHtml as h} from './api.js';

export async function statistics(root,sid){
  const survey=await api(`/surveys/${sid}`);
  root.innerHTML=`<div class="toolbar"><div><div class="eyebrow">SURVEY INSIGHTS</div><h1>${h(survey.title)}</h1><p class="muted">每一份回答，都在这里汇集。</p></div><a href="/#">返回列表</a></div><div class="panel soft"><span class="metric" id="total">—</span>份有效答卷<p class="hint">按提交份数统计，同一账号的多次提交分别计数。</p></div><label for="question-filter">统计范围</label><select id="question-filter"><option value="">整份问卷</option>${survey.questions.map((q,i)=>`<option value="${h(q.id)}">第 ${i+1} 题 · ${h(q.title)}</option>`).join('')}</select><div id="stats" style="margin-top:24px"></div>`;
  async function load(qid=''){
    const data=await api(`/surveys/${sid}/statistics${qid?'?question_id='+encodeURIComponent(qid):''}`);
    root.querySelector('#total').textContent=data.total_responses;
    root.querySelector('#stats').innerHTML=data.questions.map(q=>`<section class="panel"><h2>${h(q.title)}</h2><p class="muted">${q.answered} 份回答</p>${q.options?q.options.map(o=>`<div class="bar-row"><div class="bar-label"><span>${h(o.label)}</span><span>${o.count} 次</span></div><div class="bar"><span style="width:${q.answered?o.count/q.answered*100:0}%"></span></div></div>`).join(''):`${q.type==='number'?`<p>平均值：<strong>${q.average==null?'暂无数据':Number(q.average.toFixed(4))}</strong></p>`:''}<div class="content-area" data-contents="${h(q.question_id)}"><button data-load="${h(q.question_id)}">查看填写内容</button></div>`}</section>`).join('')||'<div class="empty">还没有题目</div>';
    root.querySelectorAll('[data-load]').forEach(b=>b.onclick=()=>contents(b.dataset.load,1));
  }
  async function contents(qid,page){
    try{
      const data=await api(`/surveys/${sid}/questions/${qid}/contents?page=${page}&size=20`);
      const area=[...root.querySelectorAll('[data-contents]')].find(el=>el.dataset.contents===qid);
      area.innerHTML=`${data.items.length?`<ol class="content-list" start="${(page-1)*20+1}">${data.items.map(x=>`<li class="answer-text">${h(x.value)}</li>`).join('')}</ol>`:'<p class="muted">暂无填写内容</p>'}<div class="actions"><button data-prev ${page===1?'disabled':''}>上一页</button><span class="hint">第 ${page} 页</span><button data-next ${data.items.length<20?'disabled':''}>下一页</button></div>`;
      area.querySelector('[data-prev]').onclick=()=>contents(qid,page-1);
      area.querySelector('[data-next]').onclick=()=>contents(qid,page+1);
    }catch(e){const {toast}=await import('./api.js');toast(e.message);}
  }
  root.querySelector('#question-filter').onchange=async e=>{try{await load(e.target.value);}catch(e){root.querySelector('#stats').textContent=e.message;}};
  await load();
}
