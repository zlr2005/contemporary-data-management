/* 独立临时数据库上的真实页面流程；需要可用的 MongoDB 和 Playwright。 */
const {chromium}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const path=require('node:path');
const fs=require('node:fs');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');

const root=path.resolve(__dirname,'..');
const python=process.env.TEST_PYTHON||path.resolve(root,'.venv/Scripts/python.exe');
const database='questionnaire_test_ui_'+crypto.randomBytes(8).toString('hex');
const port=Number(process.env.UI_TEST_PORT||8002),base=`http://127.0.0.1:${port}`;
const output=path.resolve(root,'../测试/第二阶段截图');fs.mkdirSync(output,{recursive:true});
const server=spawn(python,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',String(port)],
  {cwd:root,env:{...process.env,MONGO_DATABASE:database,JWT_SECRET:'browser-test-only-local-secret'},windowsHide:true,stdio:['ignore','pipe','pipe']});
let serverLog='',browser;
server.stdout.on('data',d=>serverLog+=d);server.stderr.on('data',d=>serverLog+=d);
async function main(){
  let ready=false;
  for(let i=0;i<80;i++){
    if(server.exitCode!==null)throw new Error('测试服务启动失败：'+serverLog);
    try{const r=await fetch(base+'/api/health');const data=await r.json();if(data.database_name===database){ready=true;break;}throw new Error('测试端口被其他服务占用');}
    catch(e){if(e.message==='测试端口被其他服务占用')throw e;await new Promise(r=>setTimeout(r,250));}
  }
  assert(ready,'测试服务未就绪：'+serverLog);
  browser=await chromium.launch({channel:process.env.TEST_BROWSER||'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1050}}),page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  page.setDefaultTimeout(15000);
  await page.goto(base);
  await page.locator('#register-tab').click();
  await page.locator('#username').fill('阶段二页面验证');await page.locator('#password').fill('browser-test-password');
  await page.getByRole('button',{name:'创建账号',exact:true}).click();
  await page.getByRole('heading',{name:'我的问卷',exact:true}).waitFor();
  const token=await page.evaluate(()=>sessionStorage.getItem('token'));
  const get=async url=>{const r=await context.request.get(base+'/api'+url,{headers:{Authorization:'Bearer '+token}});assert(r.ok(),await r.text());return r.json();};
  await page.getByRole('link',{name:'题目管理',exact:true}).click();
  await page.getByRole('link',{name:'＋ 新建题目'}).click();
  await page.locator('#q-name').fill('常用年龄题');await page.locator('#q-type').selectOption('number');
  await page.locator('#q-title').fill('你的年龄');await page.locator('#q-required').check();
  await page.locator('[data-validation=min_value]').fill('0');await page.locator('[data-validation=max_value]').fill('120');
  await page.locator('[data-validation=integer_only]').check();
  await page.getByRole('button',{name:'保存为 v1',exact:true}).click();
  await page.getByRole('heading',{name:'常用年龄题',exact:true}).waitFor();
  const series=(await get('/question-series')).items[0],sid=series._id,v1=series.latest_version;
  await page.getByRole('button',{name:'加入新问卷',exact:true}).click();
  await page.locator('#title').fill('版本复用问卷 A');
  await page.getByRole('button',{name:'保存并发布',exact:true}).click();
  await page.locator('.notice').filter({hasText:'问卷已发布'}).waitFor();
  let surveys=(await get('/surveys')).items,a=surveys.find(s=>s.title==='版本复用问卷 A');
  const originalA=await get('/surveys/'+a._id);
  await page.getByRole('link',{name:'我的问卷',exact:true}).click();
  await page.locator('#create').click();await page.locator('#title').fill('版本复用问卷 B');
  await page.getByRole('button',{name:'从已有题目选取',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'查看版本并选择'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'选用此版本',exact:true}).click();
  await page.getByRole('button',{name:'保存问卷',exact:true}).click();
  await page.getByText('问卷已保存',{exact:true}).waitFor();
  surveys=(await get('/surveys')).items;const b=surveys.find(s=>s.title==='版本复用问卷 B');
  const originalB=await get('/surveys/'+b._id);
  assert.equal(originalB.questions[0].version_id,v1._id);assert.notEqual(originalB.questions[0].id,originalA.questions[0].id);
  // 已保存编辑器的取消导航要保留内容和真实 edit URL。
  await page.locator('#title').fill('尚未保存的标题');page.once('dialog',d=>d.dismiss());
  await page.getByRole('link',{name:'题目管理',exact:true}).click();
  await page.waitForURL(base+'/#edit/'+b._id);assert.equal(await page.locator('#title').inputValue(),'尚未保存的标题');
  page.once('dialog',d=>d.accept());await page.getByRole('link',{name:'题目管理',exact:true}).click();
  await page.getByRole('link',{name:'查看版本与使用情况'}).click();
  await page.getByRole('link',{name:'基于此版本编辑',exact:true}).click();
  await page.locator('#q-title').fill('年龄（调整后）');await page.getByRole('button',{name:'保存为新版本',exact:true}).click();
  await page.getByRole('heading',{name:'常用年龄题',exact:true}).waitFor();
  const v2=(await get('/question-series/'+sid)).latest_version;
  assert.equal(v2.version_no,2);assert.deepEqual((await get('/surveys/'+a._id)).questions,originalA.questions);
  await page.getByRole('link',{name:'我的问卷',exact:true}).click();
  await page.locator('.card').filter({has:page.getByRole('heading',{name:'版本复用问卷 B',exact:true})}).getByRole('button',{name:'编辑',exact:true}).click();
  await page.getByRole('button',{name:'选择其他版本',exact:true}).click();
  await page.getByRole('dialog').locator('section').filter({has:page.getByRole('heading',{name:'年龄（调整后）',exact:true})}).getByRole('button',{name:'选用此版本',exact:true}).click();
  await page.getByRole('button',{name:'保存问卷',exact:true}).click();await page.getByText('问卷已保存',{exact:true}).waitFor();
  const updatedB=await get('/surveys/'+b._id);assert.equal(updatedB.questions[0].id,originalB.questions[0].id);assert.equal(updatedB.questions[0].version_id,v2._id);
  await page.screenshot({path:path.join(output,'02_草稿主动替换版本.png'),fullPage:true});
  await page.getByRole('button',{name:'保存并发布',exact:true}).click();await page.locator('.notice').filter({hasText:'问卷已发布'}).waitFor();
  await page.goto(base+'/#question/'+sid);await page.getByRole('heading',{name:'常用年龄题',exact:true}).waitFor();
  page.once('dialog',d=>d.accept());
  await page.locator('section.panel').filter({has:page.locator('strong').filter({hasText:/^v1$/})}).getByRole('button',{name:'以此内容创建新版本',exact:true}).click();
  await page.getByText('已创建 v3，已有问卷保持不变',{exact:true}).waitFor();
  const restored=(await get('/question-series/'+sid)).latest_version;
  assert.equal(restored.version_no,3);assert.equal(restored.restored_from_version_id,v1._id);
  assert.deepEqual((await get('/surveys/'+a._id)).questions,originalA.questions);
  assert.equal((await get('/surveys/'+b._id)).questions[0].version_id,v2._id);
  await page.screenshot({path:path.join(output,'01_版本历史与恢复.png'),fullPage:true});
  await page.goto(base+'/survey/'+a.share_code);await page.getByRole('heading',{name:'你的年龄',exact:false}).waitFor();
  await page.locator('#answer').fill('0');await page.getByRole('button',{name:'下一步',exact:true}).click();
  await page.getByRole('button',{name:'提交问卷',exact:true}).click();await page.getByRole('heading',{name:'感谢你的回答',exact:true}).waitFor();
  await page.goto(base+'/#stats/'+a._id);await page.getByText('平均值：',{exact:false}).waitFor();
  const stats=await get('/surveys/'+a._id+'/statistics');assert.equal(stats.questions[0].average,0);assert.equal(stats.total_responses,1);
  await page.screenshot({path:path.join(output,'03_原问卷填写与统计.png'),fullPage:true});
  await page.goto(base+'/#questions');await page.getByRole('heading',{name:'题目管理',exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'移动页面发生横向溢出');
  await page.screenshot({path:path.join(output,'04_移动端题目管理.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1050});
  // 配置字段顺序和显式 null 不应让未修改的选题误生成版本。
  const configured=await context.request.post(base+'/api/question-series',{headers:{Authorization:'Bearer '+token},data:{name:'配置顺序验证题',content:{type:'number',title:'配置顺序验证题',required:false,options:[],validation:{integer_only:true,min_value:null,max_value:120}},request_key:crypto.randomUUID()}});
  assert(configured.ok(),await configured.text());const orderedQuestion=await configured.json();
  await page.goto(base+'/#new');await page.locator('#title').fill('直接编题与已有版本验证');
  await page.getByRole('button',{name:'从已有题目选取',exact:true}).click();
  await page.getByRole('dialog').locator('section').filter({has:page.getByRole('heading',{name:'配置顺序验证题',exact:true})}).getByRole('button',{name:'查看版本并选择'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'选用此版本',exact:true}).click();
  await page.getByRole('button',{name:'＋ 文本填空',exact:true}).click();
  await page.locator('[data-title]').last().fill('直接编写的新题目');
  await page.getByRole('button',{name:'保存问卷',exact:true}).click();
  await page.getByText('问卷已保存',{exact:true}).waitFor();
  const directSurvey=(await get('/surveys')).items.find(s=>s.title==='直接编题与已有版本验证');
  const directDetail=await get('/surveys/'+directSurvey._id);assert.equal(directDetail.questions.length,2);
  assert.equal(directDetail.questions[0].version_id,orderedQuestion.version._id);
  assert.equal((await get('/question-series/'+orderedQuestion.series._id)).version_count,1);
  await page.locator('[data-title]').last().fill('直接修改后的题目');
  await page.locator('[data-question]').last().getByRole('button',{name:'保存题目版本',exact:true}).click();
  await page.getByText('题目版本已保存；仍需保存整份问卷',{exact:true}).waitFor();
  await page.getByRole('button',{name:'保存问卷',exact:true}).click();await page.getByText('问卷已保存',{exact:true}).waitFor();
  assert.equal((await get('/question-series/'+directDetail.questions[1].series_id)).version_count,2);
  // 延迟旧页面请求，确认快速切换后不会覆盖当前页面。
  await page.route('**/api/question-series?**',async r=>{await new Promise(resolve=>setTimeout(resolve,250));await r.continue();});
  await page.getByRole('link',{name:'题目管理',exact:true}).click();await page.getByRole('link',{name:'我的问卷',exact:true}).click();
  await page.getByRole('heading',{name:'我的问卷',exact:true}).waitFor();await page.waitForTimeout(400);
  assert.equal(await page.getByRole('heading',{name:'我的问卷',exact:true}).count(),1);
  assert.deepEqual(errors,[],'页面出现未处理 JavaScript 错误');
  console.log(JSON.stringify({passed:true,flows:['注册登录','保存题目','跨问卷复用','取消未保存导航','生成新版本','主动替换草稿版本','历史恢复','发布锁定','原问卷填写与数值0统计','移动端布局','原编辑器直接编题改题','不变内容不生成版本','快速导航无旧页面覆盖'],screenshots:output,database}));
}
main().catch(async e=>{console.error(e.stack);if(browser){const contexts=browser.contexts();const page=contexts[0]?.pages()[0];if(page)await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});}process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();
  if(server.exitCode===null){server.kill();await Promise.race([new Promise(r=>server.once('exit',r)),new Promise(r=>setTimeout(r,5000))]);}
  // 只清理脚本创建的随机临时库，绝不删除正式库。
  const cleanup=spawnSync(python,['-c',"import os; from pymongo import MongoClient; name=os.environ['UI_TEST_DATABASE']; assert name.startswith('questionnaire_test_ui_'); c=MongoClient(os.environ.get('MONGO_URI','mongodb://127.0.0.1:27018')); c.drop_database(name); c.close()"],{cwd:root,env:{...process.env,UI_TEST_DATABASE:database},windowsHide:true,encoding:'utf8'});
  if(cleanup.status!==0){console.error('临时测试库清理失败',cleanup.stderr);process.exitCode=1;}
});
