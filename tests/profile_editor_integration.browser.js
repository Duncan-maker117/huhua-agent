// All account, archive, save, and render APIs mocked; tests editor/profile handoff.
async (page) => {
  await page.unroute('**/api/**'); page.removeAllListeners('pageerror'); page.removeAllListeners('dialog');
  const checks = [], errors = []; let failSave = false, imports = 0, saves = 0, revision = 'v1';
  const check = (id, passed) => {checks.push({id,passed:Boolean(passed)});if(!passed) throw new Error(id);};
  let data = {basic_info:{name:'虚构测试人'},projects:[{name:'本地项目',role:'开发',polished_bullets:['完成本地工具']}],education:[],work_experience:[],skills:[]};
  page.on('pageerror',e=>errors.push(e.message)); page.on('dialog',d=>d.accept());
  await page.route('**/api/**',async route=>{
    const path='/' + route.request().url().split('/').slice(3).join('/').split('?')[0], method=route.request().method();
    if(path==='/api/account/me') return route.fulfill({json:{authenticated:true,account:{id:'a',email:'fixture@example.com'},require_account:true,login_available:true}});
    if(path==='/api/profile') return route.fulfill({json:{profile_id:'p',revision:1,facts:[{id:'f',revision:1,category:'project',subject:'本地项目',field:'role',value:'后端开发'}],preferences:[],conflicts:[],jobs:[]}});
    if(path==='/api/resume/templates') return route.fulfill({json:{templates:[{id:'fixture',name:'测试'}]}});
    if(path==='/api/resume/current') {
      if(method==='PUT') {if(failSave)return route.fulfill({status:503,json:{detail:{message:'模拟保存失败'}}});data=route.request().postDataJSON().resume_data;revision='saved-'+(++saves);return route.fulfill({json:{saved:true,revision,data}});}
      return route.fulfill({json:{has_data:true,data,revision,can_save:true}});
    }
    if(path.endsWith('/profile-facts')) {imports++;data.projects[0].role='后端开发';revision='imported-'+imports;return route.fulfill({json:{data,revision}});}
    if(path.startsWith('/api/resume/render/')) return route.fulfill({contentType:'text/html',body:'<!doctype html><html><body>虚构预览</body></html>'});
    return route.fulfill({status:404,json:{detail:'模拟范围外'}});
  });
  await page.goto('http://127.0.0.1:8893/resume?session=editor-profile-fixture');
  await page.locator('[data-input-path="/basic_info/name"]').waitFor();
  await page.locator('[data-input-path="/basic_info/name"]').fill('待保存的真实修改');
  await page.locator('#btn-account-profile').click(); await page.getByRole('button',{name:'用于当前简历',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.profile-status').textContent.includes('已用于当前简历'));
  check('save-before-profile-import',saves===1&&data.basic_info.name==='待保存的真实修改'&&imports===1);
  await page.keyboard.press('Escape');
  check('editor-refreshed-after-import',await page.locator('[data-input-path="/projects/0/role"]').inputValue()==='后端开发');
  check('no-session-storage-json',await page.evaluate(()=>!Object.keys(sessionStorage).some(k=>k.startsWith('huhua_editor_draft:'))));
  failSave=true;await page.locator('[data-input-path="/basic_info/name"]').fill('尚未成功保存');await page.locator('#btn-account-profile').click();await page.getByRole('button',{name:'用于当前简历',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.profile-status').textContent.includes('未保存修改'));
  check('failed-save-blocks-import',imports===1);
  await page.keyboard.press('Escape');check('failed-save-keeps-edit',await page.locator('[data-input-path="/basic_info/name"]').inputValue()==='尚未成功保存');
  check('script-errors',errors.length===0);return{checks,errors,scope:'All APIs mocked, no database/model request.'};
}
