const assert = require('node:assert/strict');
const {authFixture, response, tick} = require('./home_auth.dom.js');
const all = element => [element, ...element.children.flatMap(all)];
async function setup(initial = {authenticated: false, login_available: true}) {
  const f = authFixture('connect.html'), calls = [], copied = [];
  let account = initial, listFails = false, tokenFails = false;
  const tokens = [
    {id: 'live/1', name: '<img src=x>', scopes: ['profile:read', 'resume:read'], expires_at: '2099-01-02T03:04:00Z', last_used_at: null, revoked_at: null},
    {id: 'revoked', name: '旧令牌', scopes: ['profile:propose'], expires_at: '2099-01-02T03:04:00Z', revoked_at: '2026-10-10T00:00:00Z'},
    {id: 'expired', name: '过期令牌', scopes: ['resume:export'], expires_at: '2020-01-02T03:04:00Z'},
  ];
  f.context.fetch = async (url, options) => {
    calls.push({url, options});
    assert.equal(options.credentials, 'same-origin'); assert.equal(options.cache, 'no-store');
    if (url.endsWith('/me')) return account.error ? response({detail: account.error}, 503) : response(account);
    if (url.endsWith('/start')) return response({sent: true});
    if (url.endsWith('/verify')) { account = {authenticated: true, login_available: true}; return response({authenticated: true}); }
    if (options.method === 'DELETE') { tokens[0].revoked_at = '2026-10-17T00:00:00Z'; return response({revoked: true}); }
    if (options.method === 'POST') return tokenFails ? response({}, 500) : response({token: 'hh_synthetic_only'});
    if (url.endsWith('/tokens')) return listFails ? response({}, 503) : response({tokens, recent_calls: [
      {called_at: '2026-10-17T00:00:00Z', token_id: 'live/1', tool: 'huhua_profile_get', duration_ms: 123, status_code: 200},
    ]});
    throw new Error(url);
  };
  f.context.navigator.clipboard.writeText = async text => copied.push(text);
  f.run('home-auth.js'); f.run('connect.js');
  assert.equal(f.$('connect-state-loading').hidden, false);
  await f.window.HuhuaHomeAuth.ready; await tick();
  return {...f, calls, copied, tokens, setAccount: value => { account = value; }, failList: () => { listFails = true; }, failToken: value => { tokenFails = value; }};
}
function checkState(f, name) {
  for (const key of ['loading', 'guest', 'unavailable']) assert.equal(f.$('connect-state-' + key).hidden, key !== name);
  assert.equal(f.$('token-form').hidden, name !== 'authenticated'); assert.equal(f.$('connect-manage').hidden, name !== 'authenticated');
}
async function guestToLogin() {
  const f = await setup(), {$, emit} = f;
  checkState(f, 'guest'); assert.equal($('nav-account').textContent, '登录');
  assert.equal(f.calls.filter(call => call.url.endsWith('/tokens')).length, 0);
  assert.ok($('config-text').textContent.includes('<你的令牌>')); assert.ok($('config-text').textContent.includes('https://huhua.test/mcp'));
  await $('connect-login').click(); assert.equal($('auth-lead').textContent, '登录后即可生成 MCP 令牌。');
  $('auth-email').value = 'synthetic@example.test'; await emit($('auth-form'), 'submit');
  $('auth-code').value = '123456'; await emit($('auth-form'), 'submit'); await tick();
  checkState(f, 'authenticated'); assert.equal($('nav-account').textContent, '我的档案'); assert.equal($('nav-account-mobile').textContent, '我的档案');
  assert.equal($('nav-workspace-label').textContent, '进入工作台'); assert.equal($('nav-mobile-label').textContent, '工作台');
  assert.equal($('token-list').children.length, 3);
  assert.equal(all($('token-list')).find(n => n.className === 'token-row-name').textContent, '<img src=x>', '名称只作为文本');
  assert.ok(all($('token-list')).some(n => n.textContent === '读取档案 · 读取简历'));
  assert.ok(all($('token-list')).some(n => n.textContent.includes('尚未使用')));
  assert.deepEqual(all($('token-list')).filter(n => n.className === 'token-badge').map(n => n.textContent), ['已吊销', '已过期']);
  assert.equal($('token-empty').hidden, true); assert.equal($('call-empty').hidden, true);
  assert.ok($('call-list').children[0].textContent.endsWith(' · <img src=x> · huhua_profile_get · 123ms · 200'));
  const date = new Date('2099-01-02T03:04:00Z'), pad = value => String(value).padStart(2, '0');
  const localTime = date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
  assert.ok(all($('token-list')).some(n => n.textContent.includes(localTime)));
}
async function tokensAndConfig() {
  const f = await setup({authenticated: true, login_available: true}), {$, emit} = f;
  checkState(f, 'authenticated');
  f.scopes.forEach(input => { input.checked = false; }); await emit($('token-form'), 'submit');
  assert.equal($('connect-status').textContent, '至少选一项权限'); assert.equal(f.calls.filter(call => call.options.method === 'POST').length, 0);
  f.scopes[0].checked = true; f.failList(); await emit($('token-form'), 'submit');
  const post = f.calls.find(call => call.options.method === 'POST');
  assert.deepEqual(JSON.parse(post.options.body), {name: '我的 AI 助手', expires_days: 90, scopes: ['profile:read']});
  assert.equal($('token-once').hidden, false); assert.equal($('token-once').scrolled, true);
  assert.equal($('token-value').textContent, 'hh_synthetic_only'); assert.ok($('config-text').textContent.includes('hh_synthetic_only'));
  assert.equal($('config-hint').textContent, '已填入刚生成的令牌。'); assert.ok($('connect-status').textContent.includes('列表未能刷新'));
  await $('config-tab-cursor').click();
  assert.deepEqual(JSON.parse($('config-text').textContent), {mcpServers: {huhua: {url: 'https://huhua.test/mcp', headers: {Authorization: 'Bearer hh_synthetic_only'}}}});
  assert.equal($('config-label').textContent, '写入 ~/.cursor/mcp.json');
  for (const name of ['claude', 'cursor', 'codex']) {
    assert.equal($('config-tab-' + name).getAttribute('aria-selected'), String(name === 'cursor'));
    assert.equal($('config-tab-' + name).tabIndex, name === 'cursor' ? 0 : -1);
  }
  assert.equal($('config-panel').getAttribute('aria-labelledby'), 'config-tab-cursor');
  assert.equal(await emit($('config-tab-cursor'), 'keydown', {key: 'End'}), true);
  assert.equal(f.document.activeElement, $('config-tab-codex'));
  assert.equal($('config-text').textContent, '[mcp_servers.huhua]\nurl = "https://huhua.test/mcp"\nhttp_headers = { Authorization = "Bearer hh_synthetic_only" }');
  await emit($('config-tab-codex'), 'keydown', {key: 'ArrowRight'}); assert.equal(f.document.activeElement, $('config-tab-claude'));
  await emit($('config-tab-claude'), 'keydown', {key: 'ArrowLeft'}); assert.equal(f.document.activeElement, $('config-tab-codex'));
  await emit($('config-tab-codex'), 'keydown', {key: 'Home'}); assert.equal(f.document.activeElement, $('config-tab-claude'));
  for (const [button, source, status] of [
    ['copy-token', 'token-value', 'connect-status'], ['copy-config', 'config-text', 'copy-config-status'],
    ...['tailor', 'project', 'check'].map(key => ['copy-task-' + key, 'mcp-task-' + key, 'copy-task-' + key + '-status']),
  ]) {
    const label = $(button).textContent;
    await $(button).click(); assert.equal(f.copied.at(-1), $(source).textContent); assert.equal($(button).textContent, '已复制');
    await f.advance(4000); assert.equal($(button).textContent, label); assert.equal($(status).textContent, '');
  }
  f.context.navigator.clipboard.writeText = async () => { throw new Error('denied'); };
  await $('copy-config').click(); assert.ok($('copy-config-status').textContent.includes('手动复制'));
  const hint = '生成令牌后，这里会自动填入真实令牌。';
  await $('token-dismiss').click(); assert.equal($('token-once').hidden, true); assert.equal($('token-value').textContent, '');
  assert.ok($('config-text').textContent.includes('<你的令牌>')); assert.ok(!$('config-text').textContent.includes('hh_synthetic_only')); assert.equal($('config-hint').textContent, hint);
  await $('config-tab-cursor').click(); assert.equal(JSON.parse($('config-text').textContent).mcpServers.huhua.headers.Authorization, 'Bearer <你的令牌>');
  f.failToken(true); await emit($('token-form'), 'submit'); assert.ok($('connect-status').textContent.includes('服务暂时不可用')); assert.equal($('token-once').hidden, true);
}
async function revocationAndRetry() {
  const f = await setup({authenticated: true, login_available: true});
  const revoke = all(f.$('token-list')).find(node => node.className === 'token-revoke');
  await revoke.click(); assert.equal(revoke.textContent, '确认吊销？'); assert.equal(revoke.classList.contains('is-confirming'), true);
  assert.equal(f.calls.filter(call => call.options.method === 'DELETE').length, 0);
  await f.advance(3000); assert.equal(revoke.textContent, '吊销'); assert.equal(revoke.classList.contains('is-confirming'), false);
  await revoke.click(); await revoke.click(); await tick();
  assert.equal(f.calls.filter(call => call.options.method === 'DELETE').length, 1);
  assert.ok(f.calls.some(call => call.url.endsWith('/tokens/live%2F1')));
  assert.equal(all(f.$('token-list')).filter(node => node.className === 'token-revoke').length, 0);
  for (const initial of [{authenticated: false, login_available: false}, {authenticated: false, error: '测试连接失败'}]) {
    const g = await setup(initial); checkState(g, 'unavailable');
    assert.ok(g.$('connect-unavailable-message').textContent.includes(initial.error || '暂未配置'));
    g.setAccount({authenticated: false, login_available: true}); await g.$('connect-retry').click();
    await tick(); checkState(g, 'guest'); assert.equal(g.window.HuhuaHomeAuth.me().login_available, true);
    await g.$('connect-login').click(); assert.equal(g.$('auth-fields').hidden, false);
    await g.$('menu-toggle').click(); assert.equal(g.$('menu-toggle').getAttribute('aria-expanded'), 'true');
    await g.key('Escape'); assert.equal(g.$('menu-toggle').getAttribute('aria-expanded'), 'false');
    assert.equal(g.document.activeElement, g.$('menu-toggle'));
  }
  const empty = authFixture('connect.html');
  empty.context.fetch = async url => response(url.endsWith('/me') ? {authenticated: true} : {tokens: [], recent_calls: []});
  empty.run('home-auth.js'); empty.run('connect.js'); await empty.window.HuhuaHomeAuth.ready; await tick();
  assert.equal(empty.$('token-empty').hidden, false); assert.equal(empty.$('call-empty').hidden, false);
}
(async () => {
  await guestToLogin(); await tokensAndConfig(); await revocationAndRetry();
  console.log('connect DOM checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
