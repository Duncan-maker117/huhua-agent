// Guest onboarding and login handoff regression. Run against web/ on port 8896.
// Every /api request is mocked: no real mail, model, server data or credentials.
async (page) => {
  const base = 'http://127.0.0.1:8896';
  const checks = [], errors = [], requests = [];
  const check = (condition, name) => { if (!condition) throw new Error(name); checks.push(name); };
  const queryValue = (value, key) => { const query = value.split('?')[1] || ''; const pair = query.split('&').find(part => part.split('=')[0] === key); return pair ? decodeURIComponent(pair.split('=').slice(1).join('=')) : null; };
  let authenticated = false, claimFails = true, claimed = false, revision = 1, created = 0;
  const session = {session_id:'guest-fixture-1', title:'临时体验', messages:[], stage:'JD_INPUT'};
  let data = null;
  const sample = {basic_info:{name:'模板样例', email:'sample@example.invalid'}, projects:[], education:[], work_experience:[], skills:{}, verification_notes:[]};
  const render = value => '<!doctype html><html><body><article>' + String(value?.basic_info?.name || '模板预览') + '</article></body></html>';
  const current = () => ({session_id:session.session_id, has_data:Boolean(data), data, revision:String(revision), can_save:true, has_jd:false, match_enabled:false, stage:session.stage});
  page.removeAllListeners('pageerror'); page.removeAllListeners('dialog');
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.unroute('**/api/**'); await page.unroute('**/static/**');
  await page.route(base + '/chat**', route => route.fulfill({path: 'web/index.html'}));
  await page.route('**/static/**', route => route.continue({url:route.request().url().replace('/static/', '/')}));
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({contentType:'text/css', body:''}));
  await page.route('**/api/**', async route => {
    const req = route.request(), url = req.url(), path = '/' + url.split('/').slice(3).join('/').split('?')[0];
    const body = req.postData() ? req.postDataJSON() : null;
    requests.push({path, method:req.method(), body, query:url.includes('?') ? '?' + url.split('?').slice(1).join('?') : '', authenticated});
    if (path === '/api/account/me') return route.fulfill({json:{authenticated, require_account:true, guest_allowed:true, guest_retention_hours:24, login_available:true, account:authenticated ? {email:'guest-test@example.invalid'} : null}});
    if (path === '/api/account/login/start') return route.fulfill({json:{sent:true, retry_after:1, expires_in:600}});
    if (path === '/api/account/login/verify') { authenticated = true; return route.fulfill({json:{authenticated:true}}); }
    if (path === '/api/account/claim-guest') {
      if (claimFails) return route.fulfill({status:503, json:{detail:'模拟关联失败'}});
      const count = claimed ? 0 : 1; claimed = true;
      return route.fulfill({json:{session_id:session.session_id, claimed:count}});
    }
    if (path === '/api/chat/conversations') {
      if (req.method() === 'POST') { created += 1; return route.fulfill({json:{...session, ...current()}}); }
      return authenticated ? route.fulfill({json:{conversations:[{...session, ...current()}], retention_days:0}}) : route.fulfill({status:401,json:{detail:'请登录后读取历史'}});
    }
    if (path === '/api/chat/conversations/' + session.session_id) return route.fulfill({json:{...session, ...current()}});
    if (path === '/api/chat/stream') {
      const reply = '已根据你的真实经历生成临时简历。';
      session.messages.push(body.messages.at(-1), {role:'assistant',content:reply}); session.stage='EVALUATING';
      data = {...sample, basic_info:{name:'游客当前简历',email:'fixture@example.invalid'}};
      return route.fulfill({contentType:'text/event-stream',body:'data: ' + JSON.stringify({content:reply}) + '\n\ndata: [DONE]\n\n'});
    }
    if (path === '/api/resume/current') {
      if (req.method() === 'PUT') { data = body.resume_data; revision += 1; return route.fulfill({json:{saved:true, revision:String(revision), data}}); }
      return route.fulfill({json:current()});
    }
    if (path === '/api/resume/templates') return route.fulfill({json:{templates:[{id:'fixture-a',name:'简约模板',style:'简约'},{id:'fixture-b',name:'经典模板',style:'经典'}]}});
    if (path === '/api/resume/sample') return route.fulfill({json:sample});
    if (path.startsWith('/api/resume/render/')) return route.fulfill({contentType:'text/html',body:render(body)});
    if (path.startsWith('/api/resume/export/docx/')) return route.fulfill({contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',body:'PK\x03\x04MOCK-DOCX'});
    if (path.startsWith('/api/resume/export/pdf/')) return route.fulfill({contentType:'application/pdf',headers:{'Content-Disposition':"attachment; filename*=UTF-8''guest-fixture.pdf"},body:'%PDF-1.4\n% synthetic fixture\n%%EOF'});
    if (path === '/api/profile') return route.fulfill({json:{revision:0,facts:[],preferences:[],jobs:[],conflicts:[]}});
    return route.fulfill({status:404,json:{detail:'未使用的替身接口：' + path}});
  });
  await page.setViewportSize({width:1440,height:960});
  await page.goto(base + '/resume.html');
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.reload();
  await page.waitForFunction(() => document.querySelectorAll('#template-list button').length === 2 && document.getElementById('preview-frame').srcdoc.includes('模板样例'));
  check(await page.locator('#profile-overlay').isHidden(), '初访模板不弹登录且显示样例');
  await page.locator('[data-template-id="fixture-b"]').click();
  check((await page.locator('#current-tpl').textContent()) === '经典模板', '未登录可以切换模板');
  check(!requests.some(r => r.path === '/api/account/login/start'), '浏览模板不会发送验证码');
  await page.locator('#btn-export').click(); await page.getByLabel('登录邮箱',{exact:true}).waitFor();
  check((await page.locator('#profile-content').textContent()).includes('导出'), '点击模板导出才提示登录');
  await page.locator('#btn-close-profile').click();
  await page.goto(base + '/chat');
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled);
  check(created === 1, '初访自动创建单个临时会话');
  check(!requests.some(r => r.path === '/api/chat/conversations' && r.method === 'GET' && !r.authenticated), '游客不会请求长期历史目录');
  await page.locator('#input').fill('我用 Python 写过一个课程工具，请生成简历。'); await page.locator('#btn-send').click();
  await page.waitForFunction(() => document.getElementById('conversation-status').textContent.includes('闲置') && document.getElementById('live-sheet').srcdoc.includes('游客当前简历'));
  check((await page.locator('#messages').textContent()).includes('已根据你的真实经历'), '游客能聊天并预览当前简历');
  check(await page.evaluate(() => localStorage.getItem('huhua_session_id') === null && sessionStorage.getItem('huhua_guest_session_id') === 'guest-fixture-1'), '游客会话标识仅留标签页存储');
  await page.locator('#btn-history').click(); await page.getByLabel('登录邮箱',{exact:true}).waitFor();
  check((await page.locator('#profile-content').textContent()).includes('历史'), '历史入口说明登录后保留');
  await page.locator('#btn-close-profile').click();
  await page.locator('#workspace-tab-resume').click();
  await page.locator('#input').fill('尚未发送的补充资料');
  await page.locator('#btn-export-docx').click(); await page.getByLabel('登录邮箱',{exact:true}).waitFor();
  check(!requests.some(r => r.path.startsWith('/api/resume/export/')), '游客导出未向下载接口发请求');
  await page.getByLabel('登录邮箱',{exact:true}).fill('guest-test@example.invalid');
  await page.getByRole('button',{name:'发送验证码',exact:true}).click();
  await page.getByLabel('邮箱验证码',{exact:true}).fill('123456');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.getByRole('button',{name:'重试保留当前对话',exact:true}).waitFor();
  check(await page.locator('#input').inputValue() === '尚未发送的补充资料', '认领失败保留未发送输入');
  check((await page.locator('#messages').textContent()).includes('已根据你的真实经历'), '认领失败保留当前聊天');
  check(await page.locator('main').evaluate(el => el.inert), '认领失败冻结当前会话的后续操作');
  claimFails = false;
  await page.getByRole('button',{name:'重试保留当前对话',exact:true}).click();
  await page.waitForFunction(() => document.getElementById('profile-overlay').hidden && !document.querySelector('main').inert && document.getElementById('btn-account-profile').textContent === '我的档案');
  check(queryValue(page.url(), 'session') === session.session_id, '认领成功继续同一会话');
  check(await page.locator('#input').inputValue() === '尚未发送的补充资料', '登录成功原页保留输入草稿');
  check(requests.filter(r => r.path === '/api/account/login/verify').length === 1 && requests.filter(r => r.path === '/api/account/claim-guest').length === 2, '重试认领不重复验证码验证');
  check(!requests.some(r => r.path === '/api/account/claim-browser'), '登录不会认领浏览器的全部旧会话');
  const exported = page.waitForEvent('download');
  await page.locator('#btn-export-docx').click();
  check(await (await exported).failure() === null, '登录后 Word 下载完成');
  check(requests.some(r => r.path.startsWith('/api/resume/export/docx/') && r.authenticated), '登录后可以导出刚聊好的简历');
  check(await page.evaluate(() => [...Object.values(localStorage),...Object.values(sessionStorage)].every(v => !/尚未发送|真实经历|游客当前简历/.test(v))), '浏览器存储无聊天和简历正文');
  await page.locator('#input').fill('');
  // A second simulated guest starts directly in the editor. Verification must flush its edits.
  authenticated = false; claimed = false; claimFails = false;
  await page.goto(base + '/resume.html?session=' + session.session_id);
  const name = page.locator('[data-input-path="/basic_info/name"]'); await name.waitFor();
  await name.fill('登录前刚修改的姓名');
  await page.locator('#btn-export').click();
  await page.getByLabel('登录邮箱',{exact:true}).fill('guest-test@example.invalid');
  await page.getByRole('button',{name:'发送验证码',exact:true}).click();
  await page.getByLabel('邮箱验证码',{exact:true}).fill('123456');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.waitForFunction(() => document.getElementById('profile-overlay').hidden && document.getElementById('btn-account-profile').textContent === '我的档案');
  check(await name.inputValue() === '登录前刚修改的姓名' && data.basic_info.name === '登录前刚修改的姓名', '登录前保存并原页保留编辑器修改');
  const lastVerify = requests.map(r => r.path).lastIndexOf('/api/account/login/verify');
  check(requests.slice(0,lastVerify).some(r => r.path === '/api/resume/current' && r.method === 'PUT'), '先保存表单再完成身份切换');
  check(!requests.filter(r => r.path.startsWith('/api/resume/render/')).some(r => r.query.includes('export=true')), '普通模板预览不带导出权限标记');
  await page.locator('#btn-export').click();
  const pdfReady = page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 PDF',exact:true}).click();
  const pdf = await pdfReady;
  check(await pdf.failure() === null && pdf.suggestedFilename().endsWith('.pdf'), '正式 PDF 以文件下载完成');
  const pdfRequest = requests.filter(r => r.path.startsWith('/api/resume/export/pdf/')).at(-1);
  check(pdfRequest?.authenticated && queryValue(pdfRequest.query, 'session_id') === session.session_id, '正式 PDF 请求使用登录后的当前会话');
  check(pdfRequest.body.basic_info.name === '登录前刚修改的姓名', 'PDF 导出使用身份切换前已保存的最新编辑');
  check(!requests.filter(r => r.path.startsWith('/api/resume/render/')).some(r => r.query.includes('export=true')), 'PDF 下载不再复用预览端点');
  check(errors.length === 0, '页面无 JavaScript 异常');
  return {scope:'All business APIs mocked. No email or model request.',checks,errors};
}
