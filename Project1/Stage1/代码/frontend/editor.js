import {api,post,escapeHtml as h,toast} from './api.js';

const TYPES={single:'单选题',multiple:'多选题',text:'文本填空',number:'数字填空'};
const OPS={eq:'等于',ne:'不等于',gt:'大于',gte:'大于等于',lt:'小于',lte:'小于等于',between:'区间（含两端）',contains_any:'包含任一',contains_all:'包含全部',exact_set:'完全一致'};
const id=()=>crypto.randomUUID();
const option=()=>({id:id(),label:'新选项'});
const defaults={single:{},multiple:{},text:{format:'plain'},number:{integer_only:false}};
const field=(label,key,value,type='number')=>`<label>${label}<input data-v="${key}" type="${type}" step="any" value="${h(value??'')}" placeholder="不限制"></label>`;

function localDate(iso){
  if(!iso)return '';
  return new Date(new Date(iso).getTime()+8*3600000).toISOString().slice(0,16);
}

export async function editor(root,sid,onBack){
  const capabilities=await api('/capabilities');
  let survey=sid?await api(`/surveys/${sid}`):{title:'',description:'',allow_anonymous:false,allow_repeat:false,deadline_at:null,questions:[],status:'draft'};
  let dirty=false;
  const locked=()=>survey.status!=='draft';
  const warn=e=>{if(dirty){e.preventDefault();e.returnValue='';}};
  window.addEventListener('beforeunload',warn);
  const leave=()=>{if(!dirty||confirm('有未保存的修改，仍要离开吗？')){window.removeEventListener('beforeunload',warn);onBack();}};
  function sync(){
    survey.title=root.querySelector('#title').value;
    survey.description=root.querySelector('#description').value;
    const date=root.querySelector('#deadline').value;
    survey.deadline_at=date?new Date(date+'+08:00').toISOString():null;
    if(locked())return;
    survey.allow_anonymous=root.querySelector('#anonymous').checked;
    survey.allow_repeat=root.querySelector('#repeat').checked;
    root.querySelectorAll('[data-question]').forEach((el,index)=>{
      const q=survey.questions[index];
      q.title=el.querySelector('[data-title]').value;
      q.required=el.querySelector('[data-required]').checked;
      el.querySelectorAll('[data-option]').forEach((input,i)=>q.options[i].label=input.value);
      const validation={};
      el.querySelectorAll('[data-v]').forEach(input=>{
        const value=input.type==='checkbox'?input.checked:input.type==='number'?(input.value===''?null:Number(input.value)):input.value;
        if(value!==null)validation[input.dataset.v]=value;
      });
      q.validation=validation;
      el.querySelectorAll('[data-rule]').forEach((r,i)=>{
        const rule=q.jump_rules[i];
        rule.operator=r.querySelector('[data-op]').value;
        rule.target_question_id=r.querySelector('[data-target]').value;
        if(q.type==='single')rule.value=r.querySelector('[data-condition]').value;
        else if(q.type==='multiple')rule.value=[...r.querySelector('[data-condition]').selectedOptions].map(o=>o.value);
        else if(r.querySelector('[data-low]'))rule.value={min:Number(r.querySelector('[data-low]').value),max:Number(r.querySelector('[data-high]').value)};
        else rule.value=Number(r.querySelector('[data-condition]').value);
      });
    });
  }
  function ruleHtml(q,r,ri,qi){
    let values='';
    if(q.type==='single'||q.type==='multiple'){
      const chosen=Array.isArray(r.value)?r.value:[r.value];
      values=`<label>条件选项${q.type==='multiple'?'（按 Ctrl 可多选）':''}<select data-condition ${q.type==='multiple'?'multiple size="3"':''}>${q.options.map(o=>`<option value="${h(o.id)}" ${chosen.includes(o.id)?'selected':''}>${h(o.label)}</option>`).join('')}</select></label>`;
    }else if(r.operator==='between'){
      values=`<div class="row">${field('区间下界','unused',typeof r.value==='object'?r.value.min:0).replace('data-v="unused"','data-low')}${field('区间上界','unused',typeof r.value==='object'?r.value.max:100).replace('data-v="unused"','data-high')}</div>`;
    }else values=`<label>比较数值<input data-condition type="number" step="any" value="${h(typeof r.value==='number'?r.value:0)}"></label>`;
    return `<div class="rule" data-rule="${ri}"><div class="row"><label>匹配方式<select data-op>${capabilities.operators[q.type].map(op=>`<option value="${op}" ${op===r.operator?'selected':''}>${OPS[op]||op}</option>`).join('')}</select></label><label>跳转目标<select data-target><option value="">请选择后面的题目</option>${survey.questions.slice(qi+1).map((target,i)=>`<option value="${h(target.id)}" ${target.id===r.target_question_id?'selected':''}>第 ${qi+i+2} 题 · ${h(target.title||'未命名')}</option>`).join('')}</select></label></div>${values}<div class="actions rule-buttons"><button type="button" data-action="rule-up" data-ri="${ri}">上移</button><button type="button" data-action="rule-down" data-ri="${ri}">下移</button><button type="button" class="danger" data-action="rule-remove" data-ri="${ri}">删除规则</button></div></div>`;
  }
  function questionHtml(q,i){
    const c=q.validation;let controls='';
    if(q.type==='multiple')controls=`<div class="row three">${field('至少选择','min_choices',c.min_choices)}${field('最多选择','max_choices',c.max_choices)}${field('恰好选择','exact_choices',c.exact_choices)}</div><p class="hint">恰好数量与最少、最多数量二选一。正数最少或恰好数量会自动设为必答。</p>`;
    if(q.type==='text')controls=`<div class="row three">${field('最少字数','min_length',c.min_length)}${field('最多字数','max_length',c.max_length)}<label>文本格式<select data-v="format"><option value="plain">普通文本</option><option value="digits" ${c.format==='digits'?'selected':''}>纯数字字符（如手机号）</option></select></label></div>`;
    if(q.type==='number')controls=`<div class="row">${field('最小值','min_value',c.min_value)}${field('最大值','max_value',c.max_value)}</div><label class="check"><input data-v="integer_only" type="checkbox" ${c.integer_only?'checked':''}>必须为整数</label>`;
    return `<section class="panel" data-question="${i}"><div class="question-head"><strong>第 ${i+1} 题</strong><div class="actions"><button type="button" data-action="question-up">上移</button><button type="button" data-action="question-down">下移</button><button type="button" class="danger" data-action="question-remove">删除题目</button></div></div><div class="row"><label>题目类型<select data-type>${Object.entries(TYPES).map(([type,label])=>`<option value="${type}" ${q.type===type?'selected':''}>${label}</option>`).join('')}</select></label><label class="check"><input data-required type="checkbox" ${q.required?'checked':''}>此题必答</label></div><label>题目标题<input data-title maxlength="500" value="${h(q.title)}" placeholder="请输入题目"></label>${q.options.map((o,oi)=>`<div class="option-row"><span class="muted">${oi+1}.</span><input data-option value="${h(o.label)}" maxlength="200" aria-label="选项 ${oi+1}"><button type="button" data-action="option-remove" data-oi="${oi}" aria-label="删除选项">×</button></div>`).join('')}${['single','multiple'].includes(q.type)?'<button type="button" data-action="option-add">＋ 添加选项</button>':''}${controls}<hr class="divider"><h3>跳转规则</h3><p class="hint">从上往下匹配，第一条命中生效；否则进入下一题。仅支持向后跳转。</p>${q.jump_rules.map((r,ri)=>ruleHtml(q,r,ri,i)).join('')}${q.type!=='text'?'<button type="button" data-action="rule-add">＋ 添加跳转规则</button>':'<p class="hint">文本填空不设置跳转规则。</p>'}</section>`;
  }
  function render(){
    root.innerHTML=`<div class="toolbar"><div><div class="eyebrow">SURVEY EDITOR</div><h1>${sid?'编辑问卷':'创建问卷'}</h1><p class="muted">把你的问题，组织成一份清晰的问卷。</p></div><button id="back">返回列表</button></div>${locked()?'<div class="notice">问卷已发布，题目与填写设置已锁定。可以修改标题、说明、截止时间。</div>':''}<section class="panel"><h2>基本信息</h2><label for="title">问卷标题</label><input id="title" maxlength="200" value="${h(survey.title)}" placeholder="例如：大学生学习习惯调查"><label for="description">问卷说明</label><textarea id="description" maxlength="5000" placeholder="向填写者介绍这份问卷">${h(survey.description)}</textarea><label for="deadline">截止时间（北京时间，可不设置）</label><input id="deadline" type="datetime-local" value="${localDate(survey.deadline_at)}"><fieldset ${locked()?'disabled':''}><div class="row"><label class="check"><input id="anonymous" type="checkbox" ${survey.allow_anonymous?'checked':''}>匿名填写（对创建者隐藏账号身份）</label><label class="check"><input id="repeat" type="checkbox" ${survey.allow_repeat?'checked':''}>允许同一账号重复填写</label></div></fieldset></section><fieldset ${locked()?'disabled':''} id="questions">${survey.questions.map(questionHtml).join('')}</fieldset>${!locked()?`<div class="panel soft"><h3>添加一道题</h3><div class="actions">${Object.entries(TYPES).map(([type,label])=>`<button data-add="${type}">＋ ${label}</button>`).join('')}</div><p class="hint">最多 100 题，每题最多 50 个选项、20 条规则。文本最多 10000 个码点。</p></div>`:''}<div class="error" id="editor-error"></div><div class="editor-bottom"><span class="muted">${survey.questions.length} 道题 · ${locked()?'已锁定结构':'草稿'}</span><div class="actions"><button id="preview" ${!sid?'disabled':''}>预览已保存问卷</button><button class="primary" id="save">保存问卷</button>${!locked()?'<button class="primary" id="publish">保存并发布</button>':''}</div></div>`;
    root.querySelector('#back').onclick=leave;
    root.querySelector('#save').onclick=()=>perform(false);
    root.querySelector('#publish')?.addEventListener('click',()=>perform(true));
    root.querySelector('#preview').onclick=()=>{if(dirty)toast('请先保存当前修改');else location.hash=`preview/${sid}`;};
  }
  async function perform(publish){
    const buttons=[...root.querySelectorAll('.editor-bottom button')];buttons.forEach(b=>b.disabled=true);
    try{
      sync();
      const data={title:survey.title,description:survey.description,deadline_at:survey.deadline_at};
      if(!locked())Object.assign(data,{allow_anonymous:survey.allow_anonymous,allow_repeat:survey.allow_repeat,questions:survey.questions});
      survey=await api(sid?`/surveys/${sid}`:'/surveys',{method:sid?(locked()?'PATCH':'PUT'):'POST',body:JSON.stringify(data)});
      sid=survey._id;dirty=false;
      history.replaceState(null,'',`/#edit/${sid}`);
      if(publish)survey=await post(`/surveys/${sid}/publish`);
      toast(publish?'问卷已发布，可以分享链接了':'问卷已保存');render();
    }catch(e){root.querySelector('#editor-error').textContent=e.message;}
    finally{buttons.forEach(b=>b.disabled=false);}
  }
  root.oninput=()=>{dirty=true;};
  root.onchange=e=>{
    const qel=e.target.closest('[data-question]');if(!qel)return;
    try{
      sync();const q=survey.questions[Number(qel.dataset.question)];
      if(e.target.matches('[data-type]')){
        q.type=e.target.value;q.validation=structuredClone(defaults[q.type]);q.jump_rules=[];
        q.options=['single','multiple'].includes(q.type)?[option(),option()]:[];render();
      }else if(e.target.matches('[data-op]')){
        const r=q.jump_rules[Number(e.target.closest('[data-rule]').dataset.rule)];
        if(q.type==='number')r.value=r.operator==='between'?{min:0,max:100}:0;
        render();
      }
    }catch(e){toast(e.message);}
  };
  root.onclick=e=>{
    const btn=e.target.closest('button');if(!btn)return;
    const action=btn.dataset.action,add=btn.dataset.add;if(!action&&!add)return;
    try{
      sync();dirty=true;
      if(add){survey.questions.push({id:id(),type:add,title:'',required:false,options:['single','multiple'].includes(add)?[option(),option()]:[],validation:structuredClone(defaults[add]),jump_rules:[]});render();return;}
      const index=Number(btn.closest('[data-question]').dataset.question),q=survey.questions[index];
      const ri=Number(btn.dataset.ri);
      if(action==='question-remove')survey.questions.splice(index,1);
      if(action==='question-up'&&index>0)[survey.questions[index-1],survey.questions[index]]=[q,survey.questions[index-1]];
      if(action==='question-down'&&index<survey.questions.length-1)[survey.questions[index+1],survey.questions[index]]=[q,survey.questions[index+1]];
      if(action==='option-add')q.options.push(option());
      if(action==='option-remove')q.options.splice(Number(btn.dataset.oi),1);
      if(action==='rule-remove')q.jump_rules.splice(ri,1);
      if(action==='rule-up'&&ri>0)[q.jump_rules[ri-1],q.jump_rules[ri]]=[q.jump_rules[ri],q.jump_rules[ri-1]];
      if(action==='rule-down'&&ri<q.jump_rules.length-1)[q.jump_rules[ri+1],q.jump_rules[ri]]=[q.jump_rules[ri],q.jump_rules[ri+1]];
      if(action==='rule-add')q.jump_rules.push({id:id(),operator:q.type==='multiple'?'contains_any':'eq',value:q.type==='multiple'?[q.options[0]?.id]:q.type==='single'?(q.options[0]?.id||''):0,target_question_id:survey.questions[index+1]?.id||''});
      render();
    }catch(e){toast(e.message);}
  };
  render();
  return ()=>{root.onclick=root.oninput=root.onchange=null;window.removeEventListener('beforeunload',warn);};
}
