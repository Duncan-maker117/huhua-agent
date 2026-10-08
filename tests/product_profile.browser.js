// Disposable account/profile/adoption fixture. Every API uses synthetic data.
async (page) => {
  const checks = [], errors = [], requests = [];
  await page.unroute('**/api/**');
  page.removeAllListeners('pageerror');
  page.removeAllListeners('dialog');
  const check = (id, value) => { checks.push({id, passed: Boolean(value)}); if (!value) throw new Error(id); };
  let authenticated = true, loginAvailable = true, staleEdit = false, applyCount = 0, denySuggestion = false;
  let revision = 'revision-1', bullet = '完成本地 PDF 合并功能';
  let profile = {profile_id: 'test-profile', revision: 2, facts: [{id:'f1', revision:2, category:'project',subject:'虚构项目',field:'role',value:'负责后端开发',sources:[{id:'source1',kind:'chat',session_id:'profile-fixture',excerpt:'我只负责后端，尚未上线。',recorded_at:'2026-10-04'}]}],preferences:[],conflicts:[{id:'c1',fact_id:'f1',expected_revision:2,subject:'虚构项目',field:'role',current_value:'负责后端开发',proposed_value:'负责全部开发'}],jobs:[{id:'j1',revision:1,name:'虚构AI岗位',session_id:'profile-fixture',stale:true}],archive_status:{pending:0,running:0,failed:1,tasks:[{id:'task1',status:'failed',error_code:'retryable'}]}};
  const workspace = () => ({jd:{},experiences:{items:[]},review:{items:[]},resume:{has_data:true,version:revision},suggestions:[{title:'精简表达',detail:'保留本地实现的事实边界。',source_text:'完成本地 PDF 合并功能',suggested_text:'实现本地 PDF 合并功能'}]});
  const current = () => ({has_data:true,data:{basic_info:{name:'虚构测试人'},projects:[{name:'PDF工具',polished_bullets:[bullet]}]},revision,stage:'EVALUATING',workspace:workspace()});
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.route('**/api/**', async route => {
    const path = '/' + route.request().url().split('/').slice(3).join('/').split('?')[0], method = route.request().method(), body = method === 'POST' || method === 'PATCH' ? route.request().postDataJSON() : null;
    requests.push({path,method,body,url:route.request().url()});
    if(path==='/api/account/me') return route.fulfill({json:{authenticated,account: authenticated ? {id:'account1',email:'example@example.com'} : null,require_account:true,login_available:loginAvailable}});
    if(path==='/api/account/login/start') return route.fulfill({json:{sent:true}});
    if(path==='/api/account/login/verify') {authenticated=true;return route.fulfill({json:{authenticated:true}});}
    if(path==='/api/account/logout') {authenticated=false;return route.fulfill({json:{logged_out:true}});}
    if(path==='/api/account/claim-browser') return route.fulfill({json:{claimed:1}});
    if(path==='/api/profile') return route.fulfill({json:profile});
    if(path==='/api/profile/facts' && method==='POST') {if(body.source) return route.fulfill({status:422,json:{detail:'source由服务端确定'}});profile.facts.push({id:'f2',revision:1,...body});return route.fulfill({json:profile.facts.at(-1)});}
    if(path.endsWith('/profile-facts')) return route.fulfill({json:{revision,data:current().data}});
    if(path==='/api/profile/facts/f1' && method==='PATCH') {
      if(staleEdit) return route.fulfill({status:409,json:{detail:{message:'档案已更新'}}});
      profile.facts[0].value=body.value;profile.facts[0].revision++;return route.fulfill({json:profile.facts[0]});
    }
    if(path==='/api/profile/facts/f1' && method==='DELETE') {profile.facts=[]; return route.fulfill({json:{deleted:true}});}
    if(path==='/api/profile/conflicts/c1/resolve') {profile.conflicts=[];return route.fulfill({json:{resolved:true}});}
    if(path==='/api/profile/tasks/task1/retry') {profile.archive_status={pending:1,failed:0,tasks:[]};return route.fulfill({json:{status:'pending'}});}
    if(path==='/api/profile/jobs' || path==='/api/profile/jobs/j1') return route.fulfill({json:{id:'j1',revision:2,...body}});
    if(path.endsWith('/suggestions/preview')) return route.fulfill({json:{suggestion_id:'s1',revision,source_text:body.source_text,suggested_text:body.suggested_text,reason:'原义不变',evidence:['我完成了本地PDF合并'],can_apply:!denySuggestion,blocking_reason:denySuggestion?'没有上线依据':null}});
    if(path.endsWith('/suggestions/apply')) {applyCount++;revision='revision-2';bullet='实现本地 PDF 合并功能';return route.fulfill({json:{revision,change_id:'change1',workspace:workspace()}});}
    if(path.endsWith('/suggestions/undo')) {revision='revision-3';bullet='完成本地 PDF 合并功能';return route.fulfill({json:{revision,workspace:workspace()}});}
    if(path==='/api/resume/current') return route.fulfill({json:current()});
    if(path==='/api/resume/templates') return route.fulfill({json:{templates:[{id:'fixture',name:'测试模板'}]}});
    if(path.startsWith('/api/resume/render/')) return route.fulfill({contentType:'text/html',body:'<!doctype html><html><body>'+bullet+'</body></html>'});
    if(path==='/api/chat/conversations') return route.fulfill({json:{conversations:[{session_id:'profile-fixture',title:'虚构测试',updated_at:'2026-10-04'}]}});
    if(path==='/api/chat/conversations/profile-fixture') return route.fulfill({json:{session_id:'profile-fixture',messages:[],workspace:workspace(),stage:'EVALUATING'}});
    return route.fulfill({status:404,json:{detail:'未使用的模拟接口'}});
  });
  await page.addInitScript(() => { if (window !== window.top) return; localStorage.setItem('huhua_messages','敏感旧消息'); localStorage.setItem('huhua_chat_backup:old','敏感旧备份'); sessionStorage.setItem('huhua_editor_draft:old','旧简历'); });
  await page.setViewportSize({width:1440,height:960});
  await page.goto('http://127.0.0.1:8893/?session=profile-fixture');
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled);
  check('private-cache-cleared', await page.evaluate(() => !localStorage.getItem('huhua_messages') && !localStorage.getItem('huhua_chat_backup:old') && !sessionStorage.getItem('huhua_editor_draft:old')));
  await page.locator('#btn-account-profile').click();
  await page.locator('[data-fact-id="f1"]').waitFor();
  check('profile-identity', (await page.locator('#profile-content').textContent()).includes('本人唯一主档案'));
  await page.getByText('查看来源与时间', {exact:true}).click();
  check('provenance', (await page.locator('#profile-content').textContent()).includes('我只负责后端，尚未上线。'));
  check('stale-job', (await page.locator('#profile-content').textContent()).includes('档案已有更正'));
  await page.getByRole('button',{name:'保留原记录',exact:true}).click();
  await page.waitForFunction(() => !document.querySelector('.profile-card.conflict'));
  check('conflict-version-bound', requests.find(r=>r.path.endsWith('/conflicts/c1/resolve')).body.expected_revision===2);
  await page.getByRole('button',{name:'重试整理',exact:true}).click();
  await page.waitForFunction(() => document.getElementById('profile-content').textContent.includes('1 待处理'));
  check('archive-retry-visible',requests.some(r=>r.path.endsWith('/tasks/task1/retry')));
  await page.locator('[data-fact-id="f1"]').getByRole('button',{name:'更正',exact:true}).click();
  await page.getByLabel('更正本人事实',{exact:true}).fill('仅负责接口开发');
  await page.getByRole('button',{name:'保存更正',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.profile-value')?.textContent==='仅负责接口开发');
  check('fact-edited',requests.find(r=>r.method==='PATCH'&&r.path.endsWith('/facts/f1')).body.expected_revision===2);
  staleEdit=true;
  await page.locator('[data-fact-id="f1"]').getByRole('button',{name:'更正',exact:true}).click();
  await page.getByLabel('更正本人事实',{exact:true}).fill('过期修改');
  await page.getByRole('button',{name:'保存更正',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.profile-status').textContent.includes('另一处更新'));
  check('stale-card-no-overwrite',await page.locator('.profile-value').textContent()==='仅负责接口开发');
  await page.getByRole('button',{name:'导入此浏览器旧对话',exact:true}).click();
  check('claim-needs-explicit-click',!requests.some(r=>r.path==='/api/account/claim-browser'));
  await page.getByRole('button',{name:'确认导入本人旧对话',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.profile-status').textContent.includes('已认领'));
  check('claim-explicit',requests.filter(r=>r.path==='/api/account/claim-browser').length===1);
  await page.setViewportSize({width:390,height:844});
  check('mobile-drawer-bounds',await page.evaluate(()=>document.getElementById('profile-drawer').getBoundingClientRect().width<=innerWidth && document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'evaluation/product-profile-mobile.png'});
  await page.keyboard.press('Escape'); check('drawer-keyboard-close',await page.locator('#profile-overlay').isHidden());
  await page.setViewportSize({width:1440,height:960});
  await page.getByRole('button',{name:'核对并采用措辞',exact:true}).click();
  await page.evaluate(() => refreshCanvas());
  check('proposal-survives-same-revision-refresh',await page.getByLabel('拟采用的建议句',{exact:true}).inputValue()==='实现本地 PDF 合并功能');
  await page.getByRole('button',{name:'核对依据与改动',exact:true}).click();
  await page.getByRole('button',{name:'采用这句',exact:true}).waitFor();
  await page.evaluate(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent==='采用这句');for(let i=0;i<20;i++)b.click();});
  await page.getByRole('button',{name:'撤销本次采用',exact:true}).waitFor();
  check('adopt-once',applyCount===1);
  check('apply-revision-bound',requests.find(r=>r.path.endsWith('/suggestions/apply')).body.expected_revision==='revision-1');
  await page.waitForFunction(()=>document.getElementById('live-sheet').srcdoc.includes('实现本地 PDF'));
  check('canonical-preview-updated',true);
  await page.getByRole('button',{name:'撤销本次采用',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('live-sheet').srcdoc.includes('完成本地 PDF'));
  check('undo-revision-bound',requests.find(r=>r.path.endsWith('/suggestions/undo')).body.expected_revision==='revision-2');
  denySuggestion=true;
  await page.getByRole('button',{name:'核对并采用措辞',exact:true}).click();
  await page.getByRole('button',{name:'核对依据与改动',exact:true}).click();
  await page.getByText('没有上线依据',{exact:true}).waitFor(); check('ungrounded-suggestion-blocked',await page.getByRole('button',{name:'采用这句',exact:true}).isDisabled());
  check('no-private-browser-storage',await page.evaluate(()=>!Object.keys(localStorage).some(k=>/^huhua_(messages|chat_backup:|chat_recovery:)/.test(k))));
  await page.locator('#btn-account-profile').click();
  await page.getByRole('button',{name:'用于当前简历',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.profile-status').textContent.includes('已用于当前简历'));
  check('fact-reuse-explicit',requests.find(r=>r.path.endsWith('/profile-facts')).body.fact_ids[0]==='f1');
  await page.locator('[data-fact-id="f1"]').getByRole('button',{name:'删除',exact:true}).click();
  check('fact-delete-explains-scope',(await page.locator('#profile-content').textContent()).includes('相关原始聊天可能仍保留'));
  check('fact-delete-waits-for-confirmation',!requests.some(r=>r.path==='/api/profile/facts/f1'&&r.method==='DELETE'));
  await page.getByRole('button',{name:'确认删除这条事实',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('[data-fact-id="f1"]'));
  check('fact-delete-revision-bound',requests.find(r=>r.path==='/api/profile/facts/f1'&&r.method==='DELETE').url.includes('expected_revision=3'));
  await page.getByRole('button',{name:'补充一条信息',exact:true}).click();
  await page.getByLabel('资料类别',{exact:true}).selectOption('project');
  await page.getByLabel('属于哪段经历或信息',{exact:true}).fill('虚构第二项目');
  await page.getByLabel('信息类型',{exact:true}).selectOption('deliverable');
  await page.getByLabel('本人提供的内容',{exact:true}).fill('完成本地演示');
  await page.getByRole('button',{name:'加入个人档案',exact:true}).click();
  await page.locator('[data-fact-id="f2"]').waitFor();
  check('manual-fact-schema',requests.find(r=>r.path==='/api/profile/facts'&&r.method==='POST').body.field==='deliverable' && !requests.find(r=>r.path==='/api/profile/facts'&&r.method==='POST').body.source);
  authenticated=false;loginAvailable=false;await page.reload();
  await page.locator('#btn-account-profile').click();
  await page.getByText('邮箱登录暂未配置。',{exact:false}).waitFor();
  check('mail-not-configured-honest',await page.getByRole('button',{name:'发送验证码',exact:true}).count()===0);
  check('requires-account-blocks-chat',await page.locator('#btn-send').isDisabled());
  loginAvailable=true;await page.reload();await page.locator('#btn-account-profile').click();
  await page.getByLabel('登录邮箱',{exact:true}).fill('example@example.com');await page.getByRole('button',{name:'发送验证码',exact:true}).click();
  await page.getByLabel('邮箱验证码',{exact:true}).waitFor();await page.getByLabel('邮箱验证码',{exact:true}).fill('123456');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('btn-account-profile')?.textContent==='我的档案');
  check('login-verified',requests.some(r=>r.path==='/api/account/login/verify'&&r.body.code==='123456'));
  await page.locator('#btn-account-profile').click();
  await page.getByRole('button',{name:'退出登录',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('btn-account-profile')?.textContent==='登录账号');
  check('logout-server-and-memory-reset',requests.some(r=>r.path==='/api/account/logout') && await page.evaluate(()=>chatBackups.size===0 && messages.length===0));
  check('no-script-errors ' + JSON.stringify(errors),errors.length===0);
  return {scope:'All APIs mocked, synthetic accounts and facts; static-only local server.',checks,errors};
}
