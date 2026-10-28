import {api,escapeHtml as h,toast} from './api.js?v=20261023';
import {contentPreview,TYPES} from './questions.js?v=20261023';

const number=v=>v==null?'暂无数据':new Intl.NumberFormat('zh-CN',{maximumSignificantDigits:12}).format(v);
function summary(data){
  const q=data.version.content;
  const access=['text','number'].includes(q.type)?`<p>可查看 ${data.content_access.answered} 份内容，基础统计共 ${data.answered} 份回答</p><p class="hint">内容权限独立，不返回填写者账号、答卷编号或逐条提交时间。</p>`:'<p>按选项统计选择次数</p><p class="hint">每份有效提交独立计数；多选题的一份回答可包含多个选项。</p>';
  let body=`<div class="cards"><section class="panel"><span class="metric">${data.answered}</span>份有效回答<p class="hint">${data.total_responses} 份答卷 · ${data.source_survey_count} 份来源问卷。未答、跳过不计入有效回答。</p></section><section class="panel">${access}</section></div>`;
  if(!data.source_survey_count)body+='<p class="notice">当前没有可统计的问卷。</p>';
  else if(!data.answered)body+='<p class="notice">当前来源尚无本题的有效回答。</p>';
  if(data.options)body+=`<section class="panel"><h2>选项统计</h2>${data.options.map(o=>`<div class="bar-row"><div class="bar-label"><span>${h(o.label)}</span><span>${o.count} 次</span></div><div class="bar"><span style="width:${data.answered?o.count/data.answered*100:0}%"></span></div></div>`).join('')}</section>`;
  if(q.type==='number')body+=`<section class="panel"><h2>数字统计</h2><p>平均值：<strong>${number(data.average)}</strong> · 最小值：${number(data.minimum)} · 最大值：${number(data.maximum)}</p><h3>范围分布</h3>${data.distribution.map(bin=>{
    const label=bin.min==null?`小于 ${number(bin.max)}`:bin.max==null?`大于等于 ${number(bin.min)}`:bin.min===bin.max?`数值 ${number(bin.min)}`:`${number(bin.min)} 至${bin.include_max?'包含':'不足'} ${number(bin.max)}`;
    const exact=`下界：${bin.min==null?'无限制':bin.min}（${bin.include_min?'包含':'不包含'}）；上界：${bin.max==null?'无限制':bin.max}（${bin.include_max?'包含':'不包含'}）`;
    return `<div class="bar-row"><div class="bar-label"><span title="${h(exact)}">${h(label)}</span><span>${bin.count} 份</span></div><div class="bar"><span style="width:${data.answered?bin.count/data.answered*100:0}%"></span></div></div>`;
  }).join('')||'<p class="muted">暂无分布数据</p>'}</section>`;
  return body;
}

export async function crossStatsList(root){
  let page=1,keyword='',series='',alive=true,busy=false,loadId=0;const selected=new Map();
  async function load(){
    const generation=++loadId;const data=await api(`/question-statistics/versions?page=${page}&size=10&keyword=${encodeURIComponent(keyword)}${series?'&series_id='+series:''}`);if(!alive||generation!==loadId)return;
    root.innerHTML=`<div class="toolbar"><div><div class="eyebrow">CROSS SURVEY INSIGHTS</div><h1>跨问卷统计</h1><p class="muted">同一具体版本跨问卷汇总，不混合不同版本。</p></div></div><form id="cross-search" class="panel filter-row"><label>题目标题<input name="keyword" maxlength="200" value="${h(keyword)}"></label><button type="submit">查询</button>${series?'<button type="button" id="clear-series">取消系列筛选</button>':''}</form><p class="hint">包括自己的题目、共享题目、既有问卷引用及收到的单题统计授权；每次查询按当前权限计算。</p><div class="cards">${data.items.map((v,i)=>`<article class="card"><span class="badge">v${v.version_no} · ${h(TYPES[v.content.type])}</span><h2>${h(v.content.title)}</h2><div class="actions"><a class="button" href="/#question-stats/${v._id}">查看本版本统计</a><button data-series="${v.series_id}">查看同系列版本</button></div><label class="check"><input data-compare="${i}" type="checkbox" ${selected.has(v._id)?'checked':''}>加入版本对比</label></article>`).join('')||'<p class="empty">暂无可查看的题目版本。可先创建问卷，或由问卷创建者授予单题统计权。</p>'}</div><div class="pagination"><button id="cross-prev" ${page===1?'disabled':''}>上一页</button><span>第 ${page} 页</span><button id="cross-next" ${page*10>=data.total?'disabled':''}>下一页</button></div><div class="actions"><button id="compare-load">加载版本对比</button><button id="compare-clear">清空对比选择</button></div><p class="hint">最多选择同一系列的 4 个版本，分别展示，不生成跨版本总平均值。</p><div id="compare-result"></div>`;
    root.querySelector('#cross-search').onsubmit=e=>{e.preventDefault();keyword=new FormData(e.target).get('keyword');page=1;load().catch(e=>toast(e.message));};
    root.querySelector('#clear-series')?.addEventListener('click',()=>{series='';page=1;load().catch(e=>toast(e.message));});
    root.querySelectorAll('[data-series]').forEach(b=>b.onclick=()=>{series=b.dataset.series;page=1;load().catch(e=>toast(e.message));});
    for(const [id,delta] of [['cross-prev',-1],['cross-next',1]])root.querySelector('#'+id).onclick=()=>{page+=delta;load().catch(e=>toast(e.message));};
    root.querySelectorAll('[data-compare]').forEach(box=>box.onchange=()=>{const v=data.items[Number(box.dataset.compare)];if(!box.checked){selected.delete(v._id);return;}if(selected.size>=4||[...selected.values()].some(x=>x.series_id!==v.series_id)){box.checked=false;toast('最多选择同一题目系列的 4 个版本');return;}selected.set(v._id,v);});
    root.querySelector('#compare-clear').onclick=()=>{selected.clear();load().catch(e=>toast(e.message));};
    root.querySelector('#compare-load').onclick=async e=>{if(busy)return;if(!selected.size){toast('请先选择版本');return;}busy=true;e.target.disabled=true;const area=root.querySelector('#compare-result');area.textContent='正在按当前权限查询…';
      try{const results=await Promise.all([...selected.keys()].map(id=>api(`/question-statistics/versions/${id}`)));if(alive)area.innerHTML=results.map(d=>`<section><h2>v${d.version.version_no} · ${h(d.version.content.title)}</h2>${summary(d)}</section>`).join('');}
      catch(error){area.textContent=error.message;}finally{busy=false;e.target.disabled=false;}};
  }
  await load();const cleanup=()=>{alive=false;};cleanup.isBusy=()=>busy;return cleanup;
}

export async function crossStatsDetail(root,vid){
  let scope='all',boundaries='',alive=true,generation=0;
  const endpoint=`/question-statistics/versions/${vid}`;
  const initial=await api(endpoint);
  root.innerHTML=`<div class="toolbar"><div><div class="eyebrow">QUESTION INSIGHTS</div><h1>跨问卷单题统计</h1></div><a href="/#question-stats">返回统计列表</a></div><section class="panel"><span class="badge">v${initial.version.version_no}</span>${contentPreview(initial.version.content)}</section><section class="panel"><label>统计来源<select id="cross-scope"><option value="all">全部有权限来源</option><option value="own">我的问卷</option><option value="authorized">他人授权</option></select></label>${initial.version.content.type==='number'?'<form id="boundary-form"><label>自定义分布边界<input id="cross-boundaries" placeholder="如 18,35,60；留空使用默认分布"></label><button type="submit">应用分布边界</button><p class="hint">2～20 个严格递增数字；首尾另外统计低于首边界和不低于末边界的回答。</p></form>':''}<button id="cross-refresh">刷新当前权限和统计</button><div class="error" id="cross-error" role="alert"></div></section><div id="cross-result"></div>`;
  function query(){let q='?scope='+scope;if(boundaries.trim()){for(const text of boundaries.trim().split(/[,，\s]+/))q+='&boundaries='+encodeURIComponent(text);}return q;}
  function render(data){
    const area=root.querySelector('#cross-result');
    area.innerHTML=summary(data)+`<div class="actions"><button id="source-load">查看统计来源</button>${['text','number'].includes(data.version.content.type)?`<button id="content-load" ${data.content_access.source_question_count?'':'disabled'}>查看填写内容</button>`:''}</div>${['text','number'].includes(data.version.content.type)&&!data.content_access.source_question_count?'<p class="hint">当前范围未获得填写内容权限。</p>':''}<div id="source-area"></div><div id="content-area"></div>`;
    area.querySelector('#source-load').onclick=()=>load('sources',1);
    area.querySelector('#content-load')?.addEventListener('click',()=>load('contents',1));
  }
  async function load(kind=null,page=1){
    const current=++generation;root.querySelector('#cross-error').textContent='';root.querySelector('#cross-result').textContent='正在按当前权限查询…';
    try{
      const requests=[api(endpoint+query())];if(kind)requests.push(api(endpoint+'/'+kind+`?scope=${scope}&page=${page}&size=20`));
      const [data,list]=await Promise.all(requests);if(!alive||current!==generation)return;render(data);
      if(kind){const area=root.querySelector(kind==='sources'?'#source-area':'#content-area');
        area.innerHTML=`<section class="panel"><h2>${kind==='sources'?'统计来源':'可见的填写内容'}</h2>${kind==='sources'?list.items.map(item=>`<p class="answer-text">${h(item.title)} · ${item.owned?'自己的问卷':'他人单题授权'} · ${item.allow_contents?'可查看内容':'仅基础统计'}</p>`).join(''):`<p class="hint">当前可查看 ${list.total} 份内容。</p><ol class="content-list" start="${(page-1)*20+1}">${list.items.map(item=>`<li class="answer-text">${h(item.value)}</li>`).join('')}</ol>`}${!list.items.length?'<p class="muted">此范围暂无可见记录。</p>':''}<div class="pagination"><button data-prev ${page===1?'disabled':''}>上一页</button><span>第 ${page} 页</span><button data-next ${page*20>=list.total?'disabled':''}>下一页</button></div></section>`;
        area.querySelector('[data-prev]').onclick=()=>load(kind,page-1);area.querySelector('[data-next]').onclick=()=>load(kind,page+1);
      }
    }catch(error){if(alive&&current===generation){root.querySelector('#cross-error').textContent=error.message;root.querySelector('#cross-result').textContent='未显示旧结果，请修正输入或刷新当前权限后重试。';}}
  }
  root.querySelector('#cross-scope').onchange=e=>{scope=e.target.value;load();};
  root.querySelector('#cross-refresh').onclick=()=>load();
  root.querySelector('#boundary-form')?.addEventListener('submit',e=>{e.preventDefault();boundaries=root.querySelector('#cross-boundaries').value;load();});
  render(initial);return ()=>{alive=false;};
}
