const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {fixture, tick} = require('./resume_embedded.dom.js');
const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const entry = html.match(/const entryPanel = [\s\S]*?(?=<\/script>)/)[0];
const descendants = element => [element, ...element.children.flatMap(descendants)];

async function checkPanel(panel, authenticated, claim = false, trigger = '') {
  const f = fixture('index.html'), handlers = {}, calls = [];
  f.context.location = {origin: 'https://huhua.test', href: 'https://huhua.test/chat?panel=' + panel, search: '?panel=' + panel};
  f.context.clearInterval = () => {}; f.context.setInterval = () => 1;
  f.context.sessionStorage = {getItem() {}, setItem() {}, removeItem() {}};
  f.context.CustomEvent = class {constructor(type, options) {this.type = type; this.detail = options.detail;}};
  f.context.Event = class {constructor(type) {this.type = type;}};
  f.window.dispatchEvent = event => f.fire(event.type, event);
  let replaced;
  f.context.history = {replaceState: (_, __, value) => {replaced = value;}};
  f.document.readyState = 'loading';
  f.document.addEventListener = (type, fn) => (handlers[type] ||= []).push(fn);
  const create = f.document.createElement;
  f.document.createElement = tag => {
    const element = create(tag);
    element.reportValidity = () => true;
    element.querySelector = () => null;
    return element;
  };
  f.context.fetch = async (url, options = {}) => {
    calls.push(url);
    let body = {};
    if (url === '/api/account/me') body = {authenticated, login_available: true, guest_allowed: true, require_account: true};
    if (url === '/api/account/login/start') body = {sent: true};
    if (url === '/api/account/login/verify') { authenticated = true; body = {authenticated: true}; }
    if (url === '/api/account/claim-guest') body = {claimed: true, session_id: 'guest-fixture'};
    if (url === '/api/profile') body = {revision: 1, facts: [], conflicts: []};
    if (url === '/api/account/mcp/inbox') body = {items: [], pending_count: 0};
    if (url === '/api/account/mcp/tokens') body = {tokens: [], recent_calls: []};
    return {ok: true, json: async () => body};
  };
  f.run('account-profile.js');
  if (!trigger) vm.runInNewContext(entry, f.context);
  for (const fn of handlers.DOMContentLoaded) fn();
  await tick(); await tick();
  if (trigger) {
    const link = f.ids.get(trigger);
    let prevented = false;
    for (const fn of link.handlers.click || []) await fn({preventDefault() { prevented = true; }});
    assert.equal(prevented, false, 'MCP 入口保留浏览器原生跳转');
    assert.equal(link.tagName, 'A');
    assert.ok(html.includes('id="' + trigger + '"') && new RegExp('id="' + trigger + '"[^>]*href="/connect"').test(html));
    assert.equal(f.ids.get('profile-overlay').hidden, true, '新入口不打开旧抽屉');
    assert.equal(link.attributes['aria-controls'], undefined);
    return;
  }
  assert.equal(f.ids.get('profile-overlay').hidden, false);
  const all = () => descendants(f.ids.get('profile-content'));
  if (!authenticated) {
    assert.equal(f.ids.get('profile-heading').textContent, panel === 'connect' ? '连接 AI 助手' : '登录账号');
    if (panel === 'connect') assert.ok(all().some(n => n.textContent.includes('登录后可生成 MCP 令牌')));
    if (claim) f.window.HuhuaAccount.rememberSession('guest-fixture');
    const fields = all().filter(n => n.tagName === 'INPUT');
    fields[0].value = 'synthetic@example.test';
    await all().find(n => n.textContent === '发送验证码').click();
    fields[1].value = '123456';
    const form = all().find(n => n.tagName === 'FORM');
    for (const fn of form.handlers.submit) await fn({preventDefault() {}});
    await tick();
    assert.ok(calls.includes('/api/account/login/verify'));
    if (claim) {
      assert.ok(calls.includes('/api/account/claim-guest'));
      assert.ok(replaced.startsWith('/chat?'));
    }
  }
  assert.equal(f.ids.get('profile-overlay').hidden, false, 'requested view remains open after login');
  if (panel === 'connect') {
    assert.equal(f.ids.get('profile-heading').textContent, '连接 AI 助手');
    assert.ok(all().some(n => n.className === 'profile-connections'));
    assert.ok(!all().some(n => n.className === 'profile-actions'));
    assert.ok(!all().some(n => n.textContent.includes('次修订')));
    assert.ok(!calls.includes('/api/profile'));
    assert.ok(!calls.includes('/api/account/mcp/inbox'));
  }
  else assert.ok(all().some(n => n.textContent === '已有信息'));
}
(async () => {
  for (const trigger of ['btn-ai-assistant', 'btn-ai-assistant-mobile']) {
    await checkPanel('connect', true, false, trigger);
    await checkPanel('connect', false, false, trigger);
  }
  await checkPanel('profile', true);
  await checkPanel('profile', false);
  await checkPanel('connect', true);
  await checkPanel('connect', false);
  await checkPanel('connect', false, true);
  for (const requested of ['chosen', 'unknown']) {
    const f = fixture('resume.html');
    f.context.location.search = '?template=' + requested;
    f.context.localStorage.getItem = () => 'remembered';
    f.run('resume-editor.js', code => code.replace('  initialise();', '  window.test = {state, restoreTemplate};'));
    f.window.test.state.templates = [{id: 'first'}, {id: 'remembered'}, {id: 'chosen'}];
    assert.equal(f.window.test.restoreTemplate().id, requested === 'chosen' ? 'chosen' : 'remembered');
  }
  console.log('home entry DOM checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
