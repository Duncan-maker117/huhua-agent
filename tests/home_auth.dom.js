const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {fixture, tick} = require('./resume_embedded.dom.js');

// 沿用现有 fake DOM，补齐原生 dialog、表单校验与可控时钟。
function authFixture(page = 'home.html') {
  const f = fixture(page), $ = id => f.ids.get(id);
  const html = fs.readFileSync(path.join(__dirname, '../web', page), 'utf8');
  const decode = text => text.replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&');
  const descendants = element => element.children.flatMap(child => [child, ...descendants(child)]);
  const decorate = element => {
    element.value = ''; element.checked = false;
    element.getAttribute = name => element.attributes[name];
    const classes = new Set();
    element.classList = {add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name),
      toggle(name, value) { const add = value === undefined ? !classes.has(name) : value; add ? classes.add(name) : classes.delete(name); }};
    element.querySelectorAll = selector => descendants(element).filter(child => selector.split(',').some(tag => child.tagName === tag.toUpperCase()));
    element.reportValidity = () => element.id !== 'auth-email' || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(element.value);
    Object.defineProperty(element, 'innerHTML', {set() { throw new Error('禁止用 innerHTML 渲染账号或令牌'); }});
    return element;
  };
  const create = f.document.createElement;
  f.document.createElement = tag => decorate(create(tag));
  for (const element of f.ids.values()) decorate(element);
  for (const match of html.matchAll(/<([\w-]+)\b([^>]*\bid="([^"]+)"[^>]*)>([^<]*)/g)) {
    const element = $(match[3]);
    for (const attr of match[2].matchAll(/([\w-]+)="([^"]*)"/g)) element.setAttribute(attr[1], attr[2]);
    element.value = element.getAttribute('value') || '';
    element.textContent = decode(match[4]);
  }
  const openers = [...html.matchAll(/<[^>]+id="([^"]+)"[^>]*data-auth-open[^>]*>/g)].map(match => $(match[1]));
  f.document.querySelectorAll = selector => selector === '[data-auth-open]' ? openers : [];
  const docEvents = {};
  f.document.addEventListener = (type, fn) => (docEvents[type] ||= []).push(fn);
  async function emit(element, type, event = {}) {
    let prevented = false;
    event = {target: element, preventDefault() { prevented = true; }, ...event};
    // 浏览器同步派发所有监听器，不等待前一个异步监听器完成。
    await Promise.all((element.handlers[type] || []).map(fn => fn(event)));
    await tick(); return prevented;
  }
  for (const element of f.ids.values()) element.click = () => element.disabled ? Promise.resolve(false) : emit(element, 'click');
  const dialog = $('auth-dialog'); dialog.open = false; dialog.showCount = 0;
  dialog.showModal = () => { dialog.open = true; dialog.showCount++; };
  dialog.close = () => { dialog.open = false; for (const fn of dialog.handlers.close || []) fn({target: dialog}); };
  const controls = ['auth-close', 'auth-email', 'auth-code', 'auth-submit', 'auth-resend'].map($);
  $('auth-form').querySelectorAll = () => controls;
  const scopes = [];
  if ($('token-form')) {
    for (const match of html.matchAll(/<input type="checkbox" name="scope" value="([^"]+)"([^>]*)>/g)) {
      const input = f.document.createElement('input'); input.value = match[1]; input.checked = match[2].includes('checked'); scopes.push(input);
    }
    $('token-days').value = '90';
    $('token-form').querySelectorAll = selector => selector === 'input[name="scope"]' ? scopes : [$('token-name'), $('token-days'), $('token-submit'), ...scopes];
  }
  let now = Date.parse('2026-10-17T00:00:00Z'), timerId = 0;
  const timers = new Map();
  const schedule = (fn, delay, repeat = false) => { const id = ++timerId; timers.set(id, {fn, delay, at: now + delay, repeat}); return id; };
  f.context.Date = class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } };
  f.context.setTimeout = (fn, delay) => schedule(fn, delay);
  f.context.setInterval = (fn, delay) => schedule(fn, delay, true);
  f.context.clearTimeout = f.context.clearInterval = id => timers.delete(id);
  f.context.console = console;
  const forbiddenStorage = new Proxy({}, {get() { throw new Error('登录与令牌不得使用浏览器存储'); }});
  f.context.localStorage = f.context.sessionStorage = forbiddenStorage;
  f.context.navigator = {clipboard: {writeText: async () => {}}};
  return {...f, $, scopes, controls, timers, emit, async key(key) { for (const fn of docEvents.keydown || []) await fn({key}); },
    async advance(ms) {
      const until = now + ms;
      while (true) {
        const next = [...timers].filter(([, timer]) => timer.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        const [id, timer] = next; now = timer.at;
        if (timer.repeat) timer.at += timer.delay; else timers.delete(id);
        await timer.fn(); await tick();
      }
      now = until; await tick();
    },
  };
}
function response(body, status = 200, retryAfter = 0) {
  return {ok: status >= 200 && status < 300, status, headers: {get: () => String(retryAfter)}, json: async () => body};
}
async function loginChecks(page) {
  const f = authFixture(page), {$, emit} = f, calls = [], changes = [];
  let authenticated = false, releaseSend;
  f.context.fetch = async (url, options) => {
    calls.push({url, options});
    assert.equal(options.credentials, 'same-origin'); assert.equal(options.cache, 'no-store');
    if (url.endsWith('/me')) return response({authenticated, login_available: true});
    if (url.endsWith('/start')) return new Promise(resolve => { releaseSend = () => resolve(response({sent: true, retry_after: 120})); });
    if (url.endsWith('/verify')) { authenticated = true; return response({authenticated: true}); }
    throw new Error(url);
  };
  f.run('home-auth.js'); const auth = f.window.HuhuaHomeAuth;
  auth.onChange(account => changes.push(account.authenticated));
  await auth.ready;
  assert.deepEqual(changes, [false]);
  let late; auth.onChange(account => { late = account; }); assert.equal(late, auth.me());
  assert.equal(await $('nav-account').click(), true);
  assert.equal($('auth-dialog').open, true); assert.equal($('auth-dialog').showCount, 1);
  assert.equal(f.document.activeElement, $('auth-email'));
  const defaultLead = $('auth-lead').textContent;
  auth.open('测试登录原因'); assert.equal($('auth-lead').textContent, '测试登录原因');
  $('auth-email').value = 'bad'; await emit($('auth-form'), 'submit'); assert.equal(calls.length, 1);
  $('auth-email').value = 'fixture@example.test';
  const sending = emit($('auth-form'), 'submit'); await tick();
  assert.equal($('auth-form').getAttribute('aria-busy'), 'true'); assert.ok(f.controls.every(control => control.disabled));
  await emit($('auth-form'), 'submit'); assert.equal(calls.filter(call => call.url.endsWith('/start')).length, 1);
  releaseSend(); await sending;
  assert.equal($('auth-code-step').hidden, false); assert.equal($('auth-submit').textContent, '登录');
  assert.equal($('auth-destination').textContent, '验证码已发到 fixture@example.test，10 分钟内有效。没收到请看看垃圾邮件。');
  assert.equal($('auth-resend').textContent, '2 分钟后可重发');
  assert.equal(f.document.activeElement, $('auth-code'));
  await f.advance(60000); assert.equal($('auth-resend').textContent, '60 秒后可重发');
  await $('auth-close').click(); assert.equal($('auth-dialog').open, false);
  assert.equal($('auth-lead').textContent, defaultLead); assert.equal(f.timers.size, 0);
  await f.advance(60000); auth.open(); assert.equal($('auth-code-step').hidden, false);
  assert.equal($('auth-resend').textContent, '重新发送'); assert.equal($('auth-resend').disabled, false);
  $('auth-code').value = '12x'; await emit($('auth-form'), 'submit'); assert.equal(calls.length, 2);
  $('auth-code').value = '123456'; await emit($('auth-form'), 'submit');
  assert.deepEqual(JSON.parse(calls.find(call => call.url.endsWith('/verify')).options.body), {email: 'fixture@example.test', code: '123456'});
  assert.deepEqual(changes, [false, true]); assert.equal($('auth-status').textContent, '已登录');
  assert.equal($('auth-dialog').open, true); await f.advance(600); assert.equal($('auth-dialog').open, false);
  assert.equal(await $('nav-account').click(), false, '登录后的链接不拦截');
  assert.equal($('auth-dialog').open, false);
}
async function errorsAndReset() {
  for (const [status, body, message] of [[404, {}, '尚未启用'], [401, {}, '登录已过期'], [429, {}, '操作过于频繁'],
    [400, {detail: {message: '中文详情'}}, '中文详情'], [503, {}, '服务暂时不可用'], [400, {}, '操作未完成']]) {
    const f = authFixture(); f.context.fetch = async () => response(body, status);
    f.run('home-auth.js'); const account = await f.window.HuhuaHomeAuth.ready;
    assert.equal(account.authenticated, false); assert.equal(account.errorStatus, status); assert.ok(account.error.includes(message));
    f.window.HuhuaHomeAuth.open(); assert.equal(f.$('auth-fields').hidden, true); assert.equal(f.$('auth-submit').textContent, '重试连接');
    f.context.fetch = async () => response({authenticated: false, login_available: true});
    await f.emit(f.$('auth-form'), 'submit'); assert.equal(f.$('auth-fields').hidden, false); assert.equal(f.window.HuhuaHomeAuth.me().error, undefined);
  }
  const f = authFixture(), {$, emit} = f;
  f.context.fetch = async () => response({authenticated: false, login_available: false});
  f.run('home-auth.js'); await f.window.HuhuaHomeAuth.ready; f.window.HuhuaHomeAuth.open();
  assert.equal($('auth-fields').hidden, true);
  assert.equal($('auth-status').textContent, '邮箱登录暂未配置，邮件服务准备好后就能获取验证码。');
  assert.equal($('auth-submit').textContent, '我知道了'); await emit($('auth-form'), 'submit'); assert.equal($('auth-dialog').open, false);
  const g = authFixture(), authCalls = []; let sendBody = {sent: false}, status = 200;
  g.context.fetch = async url => { authCalls.push(url); return url.endsWith('/me') ? response({authenticated: false, login_available: true}) : response(sendBody, status, 75); };
  g.run('home-auth.js'); await g.window.HuhuaHomeAuth.ready; g.window.HuhuaHomeAuth.open();
  g.$('auth-email').value = 'fixture@example.test'; await g.emit(g.$('auth-form'), 'submit');
  assert.equal(g.$('auth-code-step').hidden, true); assert.ok(g.$('auth-status').textContent.includes('未确认验证码发送成功'));
  status = 429; await g.emit(g.$('auth-form'), 'submit'); assert.equal(g.$('auth-submit').disabled, true);
  const count = authCalls.length; await g.emit(g.$('auth-form'), 'submit'); assert.equal(authCalls.length, count);
  await g.advance(75000); status = 200; sendBody = {sent: true}; await g.emit(g.$('auth-form'), 'submit');
  g.$('auth-code').value = '123456'; await g.emit(g.$('auth-form'), 'submit'); assert.ok(g.$('auth-status').textContent.includes('未确认登录成功'));
  g.$('auth-email').value = 'another@example.test'; await g.emit(g.$('auth-email'), 'input');
  assert.equal(g.$('auth-code-step').hidden, true); assert.equal(g.$('auth-submit').textContent, '发送验证码');
  await g.emit(g.$('auth-dialog'), 'cancel'); assert.equal(g.$('auth-dialog').open, false); assert.equal(g.timers.size, 0);
  g.window.HuhuaHomeAuth.open(); await g.emit(g.$('auth-dialog'), 'click', {target: g.$('auth-form')}); assert.equal(g.$('auth-dialog').open, true);
  await g.emit(g.$('auth-dialog'), 'click'); assert.equal(g.$('auth-dialog').open, false);
  for (const fetch of [async () => { throw new Error('offline'); }, async () => response(null)]) {
    const f = authFixture(); f.context.fetch = fetch; f.run('home-auth.js');
    assert.equal((await f.window.HuhuaHomeAuth.ready).authenticated, false); assert.match(f.window.HuhuaHomeAuth.me().error, /[\u3400-\u9fff]/);
  }
}
if (require.main === module) (async () => {
  await loginChecks('home.html'); await loginChecks('connect.html'); await errorsAndReset();
  console.log('home auth DOM checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = {authFixture, response, tick};
