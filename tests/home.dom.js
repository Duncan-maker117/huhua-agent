const assert = require('node:assert/strict');
const {fixture, tick} = require('./resume_embedded.dom.js');

async function checkNavigation(authenticated, failed = false) {
  const f = fixture('home.html'), $ = id => f.ids.get(id), copied = [], events = {};
  f.context.location.origin = 'https://preview.example.test';
  f.context.location.hash = '#privacy';
  f.document.addEventListener = (type, fn) => { events[type] = fn; };
  for (const element of f.ids.values()) element.getAttribute = name => element.attributes[name];
  $('nav-account').textContent = '登录';
  $('nav-workspace-label').textContent = '开始写简历';
  let menuOpen = false;
  $('site-nav').classList.toggle = (_, open) => { menuOpen = open; };
  f.context.fetch = async (url, options) => {
    assert.equal(url, '/api/account/me');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(options.cache, 'no-store');
    if (failed) throw new Error('offline');
    return {ok: true, json: async () => ({authenticated})};
  };
  f.context.navigator = {clipboard: {writeText: async value => copied.push(value)}};
  f.run('home.js'); await tick();
  assert.equal($('nav-account').textContent, authenticated && !failed ? '我的档案' : '登录');
  assert.equal($('nav-workspace-label').textContent, authenticated && !failed ? '进入工作台' : '开始写简历');
  assert.equal($('privacy').open, true);
  await $('copy-command').click();
  assert.equal(copied[0], 'claude mcp add --transport http huhua https://preview.example.test/mcp --header "Authorization: Bearer <你的令牌>"');
  assert.equal($('copy-command').textContent, '已复制');
  assert.ok($('copy-status').textContent.includes('已复制'));
  await f.advance(4000); assert.equal($('copy-command').textContent, '复制');
  f.context.navigator.clipboard.writeText = async () => { throw new Error('denied'); };
  await $('copy-command').click();
  assert.ok($('copy-status').textContent.includes('手动复制'));
  assert.equal($('copy-command').disabled, false);
  await $('menu-toggle').click(); assert.equal(menuOpen, true);
  assert.equal($('menu-toggle').getAttribute('aria-expanded'), 'true');
  events.keydown({key: 'Escape'});
  assert.equal(menuOpen, false); assert.equal(f.document.activeElement, $('menu-toggle'));
  await $('menu-toggle').click();
  for (const fn of $('site-nav').handlers.click) fn({target: {closest: () => ({})}});
  assert.equal(menuOpen, false);
}
(async () => {
  await checkNavigation(false);
  await checkNavigation(true);
  await checkNavigation(false, true);
  console.log('home DOM checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
