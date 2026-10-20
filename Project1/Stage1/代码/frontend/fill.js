import {api,post,escapeHtml as h,toast} from './api.js';

export async function fill(root,code,preview=false){
  const survey=await api(preview?`/surveys/${code}`:`/fill/${code}`);
  if(!survey.questions.length){root.innerHTML='<div class="empty"><h2>还没有题目</h2><p>请先在编辑页面添加题目并保存。</p><a href="/#">返回列表</a></div>';return;}
  let answers={},path=[survey.questions[0].id],current=path[0],complete=false;
  let key=crypto.randomUUID();
  const questions=new Map(survey.questions.map(q=>[q.id,q]));
  const requestAnswers=()=>Object.entries(answers).map(([question_id,value])=>({question_id,value}));
  function collect(){
    const q=questions.get(current);if(!q)return;
    let value;
    if(q.type==='single')value=root.querySelector('input[name=answer]:checked')?.value??null;
    else if(q.type==='multiple')value=[...root.querySelectorAll('input[name=answer]:checked')].map(e=>e.value);
    else{const input=root.querySelector('#answer');value=q.type==='number'?(input.value===''?null:Number(input.value)):input.value;}
    return value;
  }
  function inputHtml(q){
    const value=answers[q.id];
    if(['single','multiple'].includes(q.type))return q.options.map(o=>`<label class="answer-option"><input name="answer" type="${q.type==='single'?'radio':'checkbox'}" value="${h(o.id)}" ${(Array.isArray(value)?value.includes(o.id):value===o.id)?'checked':''}><span>${h(o.label)}</span></label>`).join('');
    if(q.type==='number')return `<label for="answer">请输入数字</label><input id="answer" type="number" step="any" value="${h(value??'')}" placeholder="请输入数值">`;
    return `<label for="answer">${q.validation.format==='digits'?'仅允许 0–9，保留前导零':'请输入你的回答'}</label><textarea id="answer" maxlength="10000" ${q.validation.format==='digits'?'inputmode="numeric"':''}>${h(value??'')}</textarea>`;
  }
  function hints(q){
    const c=q.validation,out=[];
    if(c.min_choices!=null)out.push(`至少选 ${c.min_choices} 个`);
    if(c.max_choices!=null)out.push(`最多选 ${c.max_choices} 个`);
    if(c.exact_choices!=null)out.push(`恰好选 ${c.exact_choices} 个`);
    if(c.min_length!=null)out.push(`至少 ${c.min_length} 字`);
    if(c.max_length!=null)out.push(`最多 ${c.max_length} 字`);
    if(c.min_value!=null)out.push(`最小值 ${c.min_value}`);
    if(c.max_value!=null)out.push(`最大值 ${c.max_value}`);
    if(c.integer_only)out.push('必须为整数');
    return out.join(' · ');
  }
  function render(){
    const q=questions.get(current),index=path.indexOf(current);
    root.innerHTML=`<div class="fill"><div class="eyebrow">${preview?'SURVEY PREVIEW':'YOUR VOICE MATTERS'}</div><h1>${h(survey.title)}</h1><p class="muted answer-text">${h(survey.description)}</p><div class="notice">${preview?'预览模式：仅检查填写流程，不保存正式答卷。':survey.allow_anonymous?'匿名问卷：仍需登录，创建者看不到你的账号身份。':'此问卷为实名填写。'} ${!preview?(survey.allow_repeat?'允许重复填写，每次提交独立计数。':'每个账号仅能提交一次。'):''}</div><div class="progress"><span style="width:${complete?100:Math.round((survey.questions.findIndex(t=>t.id===current)+1)/survey.questions.length*100)}%"></span></div>${complete?'<section class="panel"><h2>已完成所有问题</h2><p class="muted">确认后提交本次回答。</p></section>':`<section class="panel"><p class="muted">第 ${survey.questions.findIndex(t=>t.id===current)+1} 题 / 共 ${survey.questions.length} 题</p><h2>${h(q.title)} ${q.required?'<small>必答</small>':'<small>选答</small>'}</h2><p class="hint">${h(hints(q))}</p>${inputHtml(q)}</section>`}<div class="error" id="fill-error" role="alert"></div><div class="toolbar"><button id="prev" ${(!complete&&index<=0)?'disabled':''}>上一题</button><button id="next" class="primary">${complete?(preview?'完成预览':'提交问卷'):'下一步'}</button></div><a href="/">返回我的问卷</a></div>`;
    root.querySelector('#prev').onclick=()=>{if(complete){complete=false;current=path.at(-1);}else{current=path[index-1];}render();};
    root.querySelector('#next').onclick=advance;
  }
  async function advance(){
    const btn=root.querySelector('#next');btn.disabled=true;
    try{
      if(complete){
        if(preview){toast('预览完成，未保存答卷');location.href='/';return;}
        const result=await post(`/fill/${code}/submit`,{submission_key:key,answers:requestAnswers()});
        root.innerHTML=`<div class="fill empty"><div class="success-mark">✓</div><h1>感谢你的回答</h1><p class="muted">问卷已成功提交并保存。</p><p class="hint">提交编号：${h(result.response_id)}</p><div class="actions" style="justify-content:center"><a href="/">返回我的问卷</a>${survey.allow_repeat?'<button id="again">再填写一次</button>':''}</div></div>`;
        root.querySelector('#again')?.addEventListener('click',()=>{answers={};path=[survey.questions[0].id];current=path[0];complete=false;key=crypto.randomUUID();render();});
        return;
      }
      const value=collect();
      const previous=answers[current];
      // 上一题修改后丢弃后续缓存，重新确认实际路径，防止旧分支答案混入。
      if(JSON.stringify(previous)!==JSON.stringify(value)){
        const position=survey.questions.findIndex(q=>q.id===current);
        for(const q of survey.questions.slice(position+1))delete answers[q.id];
      }
      answers[current]=value;
      const result=await post(preview?`/surveys/${code}/preview`:`/fill/${code}/evaluate`,{answers:requestAnswers()});
      path=result.path;
      for(const qid of Object.keys(answers))if(!path.includes(qid))delete answers[qid];
      for(const a of result.answers)answers[a.question_id]=a.value;
      const position=path.indexOf(current);
      if(position<path.length-1)current=path[position+1];
      else if(result.complete)complete=true;
      else current=result.next_question_id;
      render();
    }catch(e){
      root.querySelector('#fill-error').textContent=e.message;
      if(e.status===401){const link=document.createElement('a');link.href='/';link.textContent=' 返回登录';root.querySelector('#fill-error').append(link);}
    }finally{btn.disabled=false;}
  }
  render();
}
