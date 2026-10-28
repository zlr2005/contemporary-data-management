/* 三个独立登录会话，验证共享、题库、统计授权及撤销后的页面行为。 */
const {chromium}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),python=process.env.TEST_PYTHON||path.resolve(root,'.venv/Scripts/python.exe');
const database='questionnaire_test_ui_full_'+crypto.randomBytes(7).toString('hex');
const port=Number(process.env.UI_TEST_PORT||8003),base=`http://127.0.0.1:${port}`;
const output=path.resolve(root,'../测试/第二阶段截图');fs.mkdirSync(output,{recursive:true});
const server=spawn(python,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',String(port)],{cwd:root,env:{...process.env,MONGO_DATABASE:database,JWT_SECRET:'collaboration-browser-test-secret'},windowsHide:true,stdio:['ignore','pipe','pipe']});
let serverLog='',browser,lastPage;const errors=[];
server.stdout.on('data',d=>serverLog+=d);server.stderr.on('data',d=>serverLog+=d);
async function user(name){
  const context=await browser.newContext({viewport:{width:1440,height:1050}}),page=await context.newPage();page.setDefaultTimeout(15000);lastPage=page;page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.locator('#register-tab').click();await page.locator('#username').fill(name);await page.locator('#password').fill('browser-only-password');await page.getByRole('button',{name:'创建账号',exact:true}).click();await page.getByRole('heading',{name:'我的问卷',exact:true}).waitFor();
  const token=await page.evaluate(()=>sessionStorage.getItem('token'));
  const get=async url=>{const r=await context.request.get(base+'/api'+url,{headers:{Authorization:'Bearer '+token}});assert(r.ok(),await r.text());return r.json();};
  return {page,context,token,get,name};
}
async function nav(actor,label){lastPage=actor.page;await actor.page.locator('#workspace-nav').getByRole('link',{name:label,exact:true}).click();}
async function authorize(actor,survey,title,recipient,contents=false){
  const p=actor.page;lastPage=p;await p.goto(base+'/#stats/'+survey._id);await p.getByRole('button',{name:'授权本题统计',exact:true}).click();
  const dialog=p.getByRole('dialog');await dialog.locator('[name=username]').fill(recipient);if(contents)await dialog.locator('[name=allow_contents]').check();
  await dialog.getByRole('button',{name:'保存统计授权',exact:true}).click();await p.getByText('授权已保存',{exact:true}).waitFor();await dialog.getByRole('button',{name:'关闭',exact:true}).click();
}
async function answer(actor,survey,value){const p=actor.page;lastPage=p;await p.goto(base+'/survey/'+survey.share_code);await p.locator('#answer').fill(String(value));await p.getByRole('button',{name:'下一步',exact:true}).click();await p.getByRole('button',{name:'提交问卷',exact:true}).click();await p.getByRole('heading',{name:'感谢你的回答',exact:true}).waitFor();}
async function main(){
  let ready=false;for(let i=0;i<80;i++){if(server.exitCode!==null)throw new Error(serverLog);try{const r=await fetch(base+'/api/health');const data=await r.json();if(data.database_name!==database)throw new Error('测试端口被其他实例占用');ready=true;break;}catch(e){if(e.message.includes('端口'))throw e;await new Promise(r=>setTimeout(r,250));}}assert(ready,serverLog);
  browser=await chromium.launch({channel:process.env.TEST_BROWSER||'msedge',headless:true});
  const a=await user('教师甲'),b=await user('学生乙'),c=await user('分析员丙'),pa=a.page,pb=b.page,pc=c.page;
  await nav(a,'题目管理');await pa.getByRole('link',{name:'＋ 新建题目'}).click();await pa.locator('#q-name').fill('共享年龄题');await pa.locator('#q-type').selectOption('number');await pa.locator('#q-title').fill('你的年龄');await pa.locator('#q-required').check();await pa.locator('[data-validation=min_value]').fill('0');await pa.locator('[data-validation=max_value]').fill('120');await pa.getByRole('button',{name:'保存为 v1',exact:true}).click();await pa.getByRole('heading',{name:'共享年龄题',exact:true}).waitFor();
  const series=(await a.get('/question-series')).items[0],sid=series._id,v1=series.latest_version;
  await pa.getByRole('button',{name:'共享使用',exact:true}).click();let dialog=pa.getByRole('dialog');await dialog.locator('[name=username]').fill(b.name);await dialog.getByRole('button',{name:'授予使用权',exact:true}).click();await pa.getByText('授权已保存',{exact:true}).waitFor();await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  await nav(b,'题目管理');await pb.getByRole('button',{name:'共享给我的',exact:true}).click();await pb.getByRole('link',{name:'查看版本与使用情况'}).click();await pb.getByRole('link',{name:'派生为我的题目',exact:true}).waitFor();assert.equal(await pb.getByRole('button',{name:'修改管理名称'}).count(),0);assert.equal(await pb.getByRole('link',{name:'派生为我的题目',exact:true}).count(),1);
  await pb.getByRole('button',{name:'加入新问卷',exact:true}).click();assert.equal(await pb.locator('[data-title]').isDisabled(),true);await pb.locator('#title').fill('学生问卷');await pb.getByRole('button',{name:'保存并发布',exact:true}).click();await pb.locator('.notice').filter({hasText:'问卷已发布'}).waitFor();
  const bSurvey=(await b.get('/surveys')).items.find(s=>s.title==='学生问卷'),bDetail=await b.get('/surveys/'+bSurvey._id),bQid=bDetail.questions[0].id;
  await pa.getByRole('button',{name:'加入新问卷',exact:true}).click();await pa.locator('#title').fill('教师问卷');await pa.getByRole('button',{name:'保存并发布',exact:true}).click();await pa.locator('.notice').filter({hasText:'问卷已发布'}).waitFor();
  const aSurvey=(await a.get('/surveys')).items.find(s=>s.title==='教师问卷');await answer(a,aSurvey,0);await answer(b,bSurvey,40);
  const before=await a.get('/question-statistics/versions/'+v1._id);assert.equal(before.answered,1);
  await authorize(b,bSurvey,'你的年龄',a.name);
  await nav(a,'跨问卷统计');await pa.getByRole('link',{name:'查看本版本统计',exact:true}).click();await pa.getByText('可查看 1 份内容，基础统计共 2 份回答',{exact:true}).waitFor();
  await pa.getByRole('button',{name:'查看统计来源',exact:true}).click();await pa.locator('#source-area').getByText('学生问卷',{exact:false}).waitFor();await pa.screenshot({path:path.join(output,'05_跨问卷统计与来源.png'),fullPage:true});
  await pa.getByRole('button',{name:'查看填写内容',exact:true}).click();await pa.locator('#content-area').getByText('当前可查看 1 份内容。',{exact:true}).waitFor();assert.equal(await pa.locator('#content-area li').count(),1);
  await authorize(b,bSurvey,'你的年龄',a.name,true);
  await pa.getByRole('button',{name:'刷新当前权限和统计',exact:true}).click();await pa.getByText('可查看 2 份内容，基础统计共 2 份回答',{exact:true}).waitFor();await pa.getByRole('button',{name:'查看填写内容',exact:true}).click();await pa.locator('#content-area').getByText('当前可查看 2 份内容。',{exact:true}).waitFor();assert.deepEqual((await pa.locator('#content-area li').allTextContents()).sort(),['0','40']);
  await pa.locator('#cross-boundaries').fill('10,30');await pa.getByRole('button',{name:'应用分布边界',exact:true}).click();await pa.getByRole('heading',{name:'范围分布',exact:true}).waitFor();assert.deepEqual((await a.get('/question-statistics/versions/'+v1._id+'?boundaries=10&boundaries=30')).distribution.map(x=>x.count),[1,0,1]);await pa.screenshot({path:path.join(output,'06_内容权限与数字分布.png'),fullPage:true});
  await nav(b,'题库');await pb.locator('#bank-create [name=name]').fill('共享常用题库');await pb.locator('#bank-create [name=description]').fill('学生使用的常见题目');await pb.getByRole('button',{name:'创建题库',exact:true}).click();await pb.getByRole('button',{name:'加入题目',exact:true}).click();dialog=pb.getByRole('dialog');await dialog.getByRole('button',{name:'共享给我的',exact:true}).click();await dialog.getByRole('button',{name:'查看版本并选择',exact:true}).click();await dialog.getByRole('button',{name:'选用此版本',exact:true}).click();await pb.getByRole('button',{name:'保存题库',exact:true}).click();await pb.getByText('题库已保存',{exact:true}).waitFor();
  const bank=(await b.get('/question-banks')).items[0],bid=bank._id;
  await nav(b,'我的问卷');await pb.locator('#create').click();await pb.locator('#title').fill('从题库选题问卷');await pb.getByRole('button',{name:'从题库选取',exact:true}).click();dialog=pb.getByRole('dialog');await dialog.getByRole('button',{name:'查看题库并选题',exact:true}).click();await dialog.getByRole('button',{name:'选用此版本',exact:true}).click();await pb.getByRole('button',{name:'保存问卷',exact:true}).click();await pb.getByText('问卷已保存',{exact:true}).waitFor();
  const bankSurvey=(await b.get('/surveys')).items.find(s=>s.title==='从题库选题问卷');
  await pa.goto(base+'/#question/'+sid);await pa.getByRole('link',{name:'基于此版本编辑',exact:true}).click();await pa.locator('#q-title').fill('年龄（第二版）');await pa.getByRole('button',{name:'保存为新版本',exact:true}).click();await pa.getByRole('heading',{name:'共享年龄题',exact:true}).waitFor();const v2=(await a.get('/question-series/'+sid)).latest_version;
  await pb.goto(base+'/#bank/'+bid);await pb.getByRole('button',{name:'选择版本更新',exact:true}).click();dialog=pb.getByRole('dialog');await dialog.locator('section').filter({has:pb.getByRole('heading',{name:'年龄（第二版）',exact:true})}).getByRole('button',{name:'选用此版本',exact:true}).click();await pb.getByRole('button',{name:'保存题库',exact:true}).click();await pb.getByText('题库已保存',{exact:true}).waitFor();
  assert.equal((await b.get('/question-banks/'+bid)).items[0].version_id,v2._id);assert.equal((await b.get('/surveys/'+bSurvey._id)).questions[0].version_id,v1._id);assert.equal((await b.get('/surveys/'+bankSurvey._id)).questions[0].version_id,v1._id);await pb.screenshot({path:path.join(output,'07_题库成员版本更新.png'),fullPage:true});
  await pb.getByRole('button',{name:'加入新问卷',exact:true}).click();await pb.locator('#title').fill('撤销后发布的问卷');await pb.getByRole('button',{name:'保存问卷',exact:true}).click();await pb.getByText('问卷已保存',{exact:true}).waitFor();const retained=(await b.get('/surveys')).items.find(s=>s.title==='撤销后发布的问卷');
  // 从共享版本管理页派生，不能覆盖原系列。
  await pb.goto(base+'/#question/'+sid);await pb.locator('section.panel').filter({has:pb.locator('strong').filter({hasText:/^v2$/})}).getByRole('link',{name:'派生为我的题目',exact:true}).click();await pb.locator('#q-name').fill('学生派生年龄题');await pb.locator('#q-title').fill('学生自己的年龄题');await pb.getByRole('button',{name:'保存为我的题目 v1',exact:true}).click();await pb.getByRole('heading',{name:'学生派生年龄题',exact:true}).waitFor();assert.equal((await a.get('/question-series/'+sid)).latest_version._id,v2._id);
  // 原编辑器中显式派生后再改题。
  await pb.goto(base+'/#edit/'+bankSurvey._id);await pb.getByRole('button',{name:'派生为我的题目后编辑',exact:true}).click();await pb.getByText('已派生为自己的题目，可以编辑；仍需保存问卷',{exact:true}).waitFor();await pb.locator('[data-title]').fill('在原编辑器修改的派生题');await pb.getByRole('button',{name:'保存问卷',exact:true}).click();await pb.getByText('问卷已保存',{exact:true}).waitFor();assert.notEqual((await b.get('/surveys/'+bankSurvey._id)).questions[0].series_id,sid);
  // 取消共享后旧问卷仍可发布，题库保留原快照但不能新增选用。
  await pa.getByRole('button',{name:'共享使用',exact:true}).click();dialog=pa.getByRole('dialog');pa.once('dialog',d=>d.accept());await dialog.getByRole('button',{name:'撤销授权',exact:true}).click();await pa.getByText('授权已撤销',{exact:true}).waitFor();await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  assert.equal((await b.get('/question-series?scope=shared')).total,0);
  await pb.goto(base+'/#edit/'+retained._id);await pb.getByRole('button',{name:'保存并发布',exact:true}).click();await pb.locator('.notice').filter({hasText:'问卷已发布'}).waitFor();assert.equal((await b.get('/surveys/'+retained._id)).questions[0].version_id,v2._id);
  await pb.goto(base+'/#bank/'+bid);assert.equal(await pb.getByRole('button',{name:'加入新问卷',exact:true}).isDisabled(),true);assert.equal(await pb.getByRole('button',{name:'选择版本更新',exact:true}).isDisabled(),true);
  assert.equal((await a.get('/question-statistics/versions/'+v1._id)).answered,2,'使用权撤销不应撤销独立统计授权');
  // 未获得题目使用权的第三人只看到所授单题版本和基础统计。
  await authorize(b,bSurvey,'你的年龄',c.name);await nav(c,'跨问卷统计');await pc.getByRole('link',{name:'查看本版本统计',exact:true}).click();await pc.getByText('可查看 0 份内容，基础统计共 1 份回答',{exact:true}).waitFor();assert.equal(await pc.getByRole('button',{name:'查看填写内容',exact:true}).isDisabled(),true);assert.equal((await c.get('/question-statistics/versions')).total,1);await pc.screenshot({path:path.join(output,'08_仅单题统计授权.png'),fullPage:true});
  await pb.goto(base+'/#stats/'+bSurvey._id);await pb.getByRole('button',{name:'授权本题统计',exact:true}).click();dialog=pb.getByRole('dialog');const ownerRow=dialog.locator('section').filter({has:pb.locator('strong').filter({hasText:a.name})});pb.once('dialog',d=>d.accept());await ownerRow.getByRole('button',{name:'撤销授权',exact:true}).click();await pb.getByText('授权已撤销',{exact:true}).waitFor();await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  await pa.goto(base+'/#question-stats/'+v1._id);await pa.getByText('可查看 1 份内容，基础统计共 1 份回答',{exact:true}).waitFor();assert.equal((await a.get('/question-statistics/versions/'+v1._id)).answered,1);
  await pc.setViewportSize({width:390,height:844});assert.equal(await pc.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);await pc.screenshot({path:path.join(output,'09_移动端跨问卷统计.png'),fullPage:true});
  // 相同题干的两道题，统计授权按钮仍必须定位到正确的内部题目。
  const request=async(actor,method,url,data)=>{const r=await actor.context.request.fetch(base+'/api'+url,{method,data,headers:{Authorization:'Bearer '+actor.token}});assert(r.ok(),await r.text());return r.json();};
  const content={type:'text',title:'相同标题的填空题',required:true,options:[],validation:{format:'plain'}};
  const t1=await request(a,'POST','/question-series',{name:'未授权文本题',content,request_key:crypto.randomUUID()}),t2=await request(a,'POST','/question-series',{name:'授权文本题',content,request_key:crypto.randomUUID()});
  const bind=(version,id)=>({id,...version.content,series_id:version.series_id,version_id:version._id,jump_rules:[]});
  const textSurvey=await request(a,'POST','/surveys',{title:'同名题授权验证',allow_anonymous:true,questions:[bind(t1.version,'first'),bind(t2.version,'second')]});
  await request(a,'POST',`/surveys/${textSurvey._id}/publish`,{});
  const markup='<img src=x onerror="window.__escaped=false">';
  await request(a,'POST',`/fill/${textSurvey.share_code}/submit`,{submission_key:crypto.randomUUID(),answers:[{question_id:'first',value:'未授权的另一题'},{question_id:'second',value:markup}]});
  await pa.goto(base+'/#stats/'+textSurvey._id);await pa.getByRole('button',{name:'授权本题统计',exact:true}).nth(1).click();dialog=pa.getByRole('dialog');await dialog.locator('[name=username]').fill(c.name);await dialog.locator('[name=allow_contents]').check();await dialog.getByRole('button',{name:'保存统计授权',exact:true}).click();await pa.getByText('授权已保存',{exact:true}).waitFor();await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  const permitted=await c.get('/question-statistics/versions');assert(permitted.items.some(v=>v._id===t2.version._id));assert(!permitted.items.some(v=>v._id===t1.version._id));
  await pc.setViewportSize({width:1440,height:1050});await pc.goto(base+'/#question-stats/'+t2.version._id);await pc.getByRole('button',{name:'查看填写内容',exact:true}).click();await pc.locator('#content-area li').waitFor();assert.equal(await pc.locator('#content-area li').textContent(),markup);assert.equal(await pc.locator('#content-area img').count(),0);assert.equal(await pc.evaluate(()=>window.__escaped),undefined);await pc.screenshot({path:path.join(output,'10_文本内容与单题权限.png'),fullPage:true});
  assert.deepEqual(errors,[],'出现未处理页面错误');console.log(JSON.stringify({passed:true,actors:3,flows:['共享与后续版本','共享题只读及派生','两种选题入口','跨问卷汇总','单题基础与内容授权','数字分布','题库主动升级','撤销后保留引用和发布','共享撤销与统计授权独立','第三人仅单题统计','统计撤销实时生效','移动布局','同名题精确授权','文本内容转义'],screenshots:output,database}));
}
main().catch(async e=>{console.error(e.stack);if(lastPage)await lastPage.screenshot({path:path.join(output,'collaboration_failure.png'),fullPage:true}).catch(()=>{});process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();if(server.exitCode===null){server.kill();await Promise.race([new Promise(r=>server.once('exit',r)),new Promise(r=>setTimeout(r,5000))]);}
  const result=spawnSync(python,['-c',"import os; from pymongo import MongoClient; n=os.environ['UI_TEST_DATABASE']; assert n.startswith('questionnaire_test_ui_full_'); c=MongoClient(os.environ.get('MONGO_URI','mongodb://127.0.0.1:27018')); c.drop_database(n); c.close()"],{cwd:root,env:{...process.env,UI_TEST_DATABASE:database},windowsHide:true,encoding:'utf8'});if(result.status!==0){console.error(result.stderr);process.exitCode=1;}
});
