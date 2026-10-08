// UI error and OTP lifecycle regression. Only fabricated HTTP responses, no mail sent.
async (page) => {
  const checks = [], errors = [], requests = [];
  let mode = 'legacy', authenticated = false, sendMode = 'ok', verifyMode = 'invalid', profileExpired = false;
  const check = (id, condition) => { checks.push({id, passed: Boolean(condition)}); if (!condition) throw new Error(id); };
  await page.unroute('**/static/**');
  await page.route('**/static/**', route => route.continue({url:route.request().url().replace('/static/', '/')}));
  await page.unroute('**/api/**'); page.removeAllListeners('pageerror');
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), path = '/' + request.url().split('/').slice(3).join('/').split('?')[0];
    requests.push({path, body: request.postData() ? request.postDataJSON() : null});
    if (path === '/api/account/me') {
      if (mode === 'legacy') return route.fulfill({status:404, json:{detail:'Not Found'}});
      if (mode === 'network') return route.abort('connectionfailed');
      if (mode === 'unavailable') return route.fulfill({status:503, json:{detail:'Internal Server Error'}});
      if (mode === 'invalid-body') return route.fulfill({contentType:'text/html', body:'<!doctype html><p>Not Found</p>'});
      return route.fulfill({json:{authenticated, require_account:true, login_available:mode !== 'no-mail', account:authenticated ? {email:'ui@huhua-fixture.invalid'} : null}});
    }
    if (path === '/api/account/login/start') {
      if (sendMode === 'fail') return route.fulfill({status:503, json:{detail:'验证码暂时发送失败，请稍后重试'}});
      if (sendMode === 'unconfirmed') return route.fulfill({json:{sent:false}});
      if (sendMode === 'long-throttle') return route.fulfill({status:429, headers:{'Retry-After':'604800'}, json:{detail:'本月邮件额度已用完，请下个月重试。'}});
      if (sendMode === 'throttle') return route.fulfill({status:429, headers:{'Retry-After':'2'}, json:{detail:'Too Many Requests'}});
      return route.fulfill({json:{sent:true, delivery_status:'provider_accepted', message:'验证码已提交邮件服务，请检查收件箱或垃圾邮件。', retry_after:2, expires_in:600}});
    }
    if (path === '/api/account/login/verify') {
      if (verifyMode === 'invalid') return route.fulfill({status:400, json:{detail:'验证码无效或已过期，请重新获取'}});
      authenticated = true; return route.fulfill({json:{authenticated:true}});
    }
    if (path === '/api/profile') return profileExpired ? route.fulfill({status:401,json:{detail:'Unauthorized'}}) : route.fulfill({json:{revision:0,facts:[],preferences:[],jobs:[],conflicts:[]}});
    if (path === '/api/resume/templates') return route.fulfill({json:{templates:[]}});
    if (path === '/api/chat/conversations') return route.fulfill({json:{conversations:[]}});
    return route.fulfill({json:{}});
  });
  const open = async () => { await page.goto('http://127.0.0.1:8896/'); await page.locator('#btn-account-profile').click(); };
  const status = () => page.locator('.profile-status');
  await page.setViewportSize({width:1440,height:960}); await open();
  await page.getByText('当前服务尚未启用账号登录，请等待服务更新后重试。',{exact:true}).waitFor();
  check('legacy-404-localized',!(await page.locator('#profile-drawer').textContent()).includes('Not Found'));
  check('logged-out-title-and-entry',await page.locator('#profile-heading').textContent()==='登录账号' && await page.locator('#btn-account-profile').textContent()==='登录账号');
  check('legacy-has-retry-no-code-form',await page.getByRole('button',{name:'重试连接',exact:true}).count()===1 && await page.getByRole('button',{name:'发送验证码',exact:true}).count()===0);
  mode='network';await page.getByRole('button',{name:'重试连接',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.profile-status').textContent.includes('连接失败'));
  check('network-distinct-from-unconfigured',(await status().textContent()).includes('检查网络'));
  mode='unavailable';await page.getByRole('button',{name:'重试连接',exact:true}).click();
  await page.getByText('服务暂时不可用，请稍后重试。',{exact:true}).waitFor(); check('server-error-localized',true);
  mode='invalid-body';await page.getByRole('button',{name:'重试连接',exact:true}).click();
  await page.getByText('账号服务响应异常，请稍后重试。',{exact:true}).waitFor();check('invalid-200-not-treated-as-account',true);
  mode='no-mail';await page.getByRole('button',{name:'重试连接',exact:true}).click();
  await page.getByRole('button',{name:'重新检查',exact:true}).waitFor();
  check('no-mail-state-connected',(await status().textContent()).includes('邮件发送尚未就绪') && await page.getByRole('button',{name:'发送验证码',exact:true}).count()===0);
  mode='ready';await page.getByRole('button',{name:'重新检查',exact:true}).click();
  await page.getByLabel('登录邮箱',{exact:true}).fill('ui@huhua-fixture.invalid');
  await page.getByLabel('登录邮箱',{exact:true}).press('Enter');
  await page.getByLabel('邮箱验证码',{exact:true}).waitFor();
  check('enter-email-sends-not-verifies',requests.filter(r=>r.path.endsWith('/login/start')).length===1 && !requests.some(r=>r.path.endsWith('/login/verify')));
  check('provider-acceptance-message',await status().textContent()==='验证码已提交邮件服务，请检查收件箱或垃圾邮件。');
  check('sent-destination-visible',(await page.locator('#profile-code-destination').textContent()).includes('ui@huhua-fixture.invalid'));
  check('resend-cooldown',await page.getByRole('button',{name:/秒后可重发/}).isDisabled());
  await page.evaluate(()=>{for(let i=0;i<10;i++)document.querySelector('#profile-content form > button').click();});
  check('click-spam-one-request',requests.filter(r=>r.path.endsWith('/login/start')).length===1);
  await page.getByLabel('邮箱验证码',{exact:true}).fill('123');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  check('short-code-client-validation',!requests.some(r=>r.path.endsWith('/login/verify')));
  await page.getByLabel('邮箱验证码',{exact:true}).fill('123456');await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.getByText('验证码无效或已过期，请重新获取',{exact:true}).waitFor();
  check('invalid-code-keeps-email',await page.getByLabel('登录邮箱',{exact:true}).inputValue()==='ui@huhua-fixture.invalid');
  await page.getByLabel('登录邮箱',{exact:true}).fill('other@huhua-fixture.invalid');
  check('changing-address-hides-previous-code',await page.getByLabel('邮箱验证码',{exact:true}).isHidden());
  await page.getByRole('button',{name:'发送验证码',exact:true}).waitFor({state:'visible'});
  sendMode='fail';await page.getByRole('button',{name:'发送验证码',exact:true}).click();
  await page.getByText('验证码暂时发送失败，请稍后重试',{exact:true}).waitFor();
  check('failed-send-never-shows-success',await page.getByLabel('邮箱验证码',{exact:true}).isHidden());
  sendMode='unconfirmed';await page.getByRole('button',{name:'发送验证码',exact:true}).click();
  await page.getByText('未确认验证码发送成功，请稍后重试。',{exact:true}).waitFor();check('unconfirmed-send-rejected',true);
  sendMode='throttle';await page.getByRole('button',{name:'发送验证码',exact:true}).click();
  await page.getByText('操作过于频繁，请稍后重试。',{exact:true}).waitFor();
  check('server-rate-limit-cooldown',await page.getByRole('button',{name:/秒后可重发/}).isDisabled());
  sendMode='ok';await page.getByRole('button',{name:'发送验证码',exact:true}).click();
  await page.getByLabel('邮箱验证码',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  check('mobile-login-no-overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth && document.getElementById('profile-drawer').getBoundingClientRect().width<=innerWidth));
  await page.screenshot({path:'evaluation/login-ui-2026-10-04/mobile-login.png'});
  verifyMode='ok';await page.getByLabel('邮箱验证码',{exact:true}).fill('654321');await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('btn-account-profile')?.textContent==='我的档案');
  check('successful-verify-before-account-entry',requests.some(r=>r.path.endsWith('/login/verify')&&r.body.code==='654321'));
  await page.locator('#btn-account-profile').click();await page.getByRole('button',{name:'补充一条信息',exact:true}).waitFor();
  check('authenticated-profile-title',await page.locator('#profile-heading').textContent()==='个人档案');
  profileExpired=true;await page.getByRole('button',{name:'刷新档案',exact:true}).click();await page.getByLabel('登录邮箱',{exact:true}).waitFor();
  check('expired-session-returns-to-login',await page.locator('#profile-heading').textContent()==='登录账号'&&(await status().textContent()).includes('登录已过期'));
  sendMode='long-throttle';await page.getByLabel('登录邮箱',{exact:true}).fill('ui@huhua-fixture.invalid');await page.getByRole('button',{name:'发送验证码',exact:true}).click();
  await page.getByText('本月邮件额度已用完，请下个月重试。',{exact:true}).waitFor();
  check('monthly-budget-friendly-text',await page.getByRole('button',{name:'发送暂受限',exact:true}).isDisabled());
  check('no-page-errors',errors.length===0);
  return {scope:'UI-only: synthetic HTTP responses on separate static port 8896; no real email sent.',checks,errors};
}
