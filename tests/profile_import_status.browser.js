// Targeted UI fixture: import queue is distinct from archive tasks.
async (page) => {
  const checks=[],requests=[];
  const check=(id,value)=>{checks.push({id,passed:Boolean(value)});if(!value)throw new Error(id);};
  let retried=false;
  await page.route('**/api/**',async route=>{
    const path='/' + route.request().url().split('/').slice(3).join('/').split('?')[0];requests.push(path);
    if(path==='/api/account/me') return route.fulfill({json:{authenticated:true,account:{id:'fixture',email:'fixture@example.invalid'},require_account:true,login_available:true}});
    if(path==='/api/profile') return route.fulfill({json:{profile_id:'profile',revision:1,facts:[],preferences:[],conflicts:[],jobs:[],import_status:{pending:2,running:1,failed:1,completed:3,tasks:[{session_id:'legacy-history-id',status:'failed',error_code:'PRIVATE_EXCEPTION_TOKEN',reason_type:'import_unavailable'}]},archive_status:{failed:retried?1:2,tasks:[{id:'missing-model-id',status:'failed',reason_type:'model_unavailable',message:'等待配置模型后整理',retryable:false},...(retried?[]:[{id:'archive-id',status:'failed',error_code:'INTERNAL_ARCHIVE_ERROR',retryable:true}])]}}});
    if(path==='/api/profile/tasks/archive-id/retry') {retried=true;return route.fulfill({json:{status:'pending'}});}
    if(path==='/api/resume/templates')return route.fulfill({json:{templates:[]}});
    if(path==='/api/chat/conversations')return route.fulfill({json:{conversations:[]}});
    return route.fulfill({status:404,json:{detail:'unused fixture'}});
  });
  await page.goto(page.url().split('/').slice(0,3).join('/')+'/chat');await page.locator('#btn-account-profile').click();
  await page.locator('[aria-label="旧对话导入状态"]').waitFor();
  check('import-counts-visible',(await page.locator('[aria-label="旧对话导入状态"]').textContent()).includes('2 待导入 · 1 处理中 · 1 失败 · 3 已完成'));
  check('errors-not-exposed',!(await page.locator('#profile-content').textContent()).includes('PRIVATE_EXCEPTION_TOKEN')&&!(await page.locator('#profile-content').textContent()).includes('INTERNAL_ARCHIVE_ERROR'));
  check('only-archive-offers-retry',await page.getByRole('button',{name:'重试整理',exact:true}).count()===1);
  check('unconfigured-model-has-clear-status',(await page.locator('#profile-content').textContent()).includes('等待配置模型后整理'));
  await page.getByRole('button',{name:'重试整理',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.profile-status').textContent.includes('重新加入'));
  check('retry-uses-archive-id',requests.includes('/api/profile/tasks/archive-id/retry')&&!requests.some(p=>p.includes('/tasks/legacy-history-id')));
  check('import-failure-does-not-offer-wrong-retry',await page.getByRole('button',{name:'重试整理',exact:true}).count()===0);
  check('unconfigured-model-not-retried',!requests.some(p=>p.includes('/tasks/missing-model-id')));
  return{scope:'Targeted synthetic import/archive status UI only.',checks};
}
