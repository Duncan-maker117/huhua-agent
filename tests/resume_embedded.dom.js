// Execute production controllers with a small DOM and deterministic idle/network queues.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = require('node:path').resolve(__dirname, '..');
const tick = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function fixture(page, {idle = true, embedded = false} = {}) {
  const ids = new Map(), timers = new Map(), events = {}, posts = [];
  let sequence = 0;
  const document = {activeElement: null, getElementById: id => ids.get(id), createElement: tag => new Element(tag),
    querySelector: () => main, querySelectorAll: () => [], addEventListener() {}};
  class Element {
    constructor(tag) {
      this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {}; this.handlers = {};
      this.style = {}; this.textContent = ''; this.hidden = false; this.disabled = false; this.scrollTop = 0;
      this.classList = {toggle() {}, add() {}, remove() {}, contains: () => false};
      this.contentWindow = {postMessage: (data, origin) => posts.push({data, origin})};
    }
    set id(value) { if (ids.get(this._id) === this) ids.delete(this._id); this._id = value; ids.set(value, this); } get id() { return this._id; }
    get childElementCount() { return this.children.length; }
    append(...nodes) { for (const n of nodes) { n.parentElement = this; this.children.push(n); } }
    insertBefore(node) { this.append(node); }
    replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(n => n !== this); ids.delete(this.id); }
    addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; }
    querySelectorAll() { return []; }
    focus() { document.activeElement = this; }
    scrollIntoView() { this.scrolled = true; }
    async click() { if (this.disabled) return; this.clicks = (this.clicks || 0) + 1; for (const fn of this.handlers.click || []) await fn({preventDefault() {}}); }
  }
  const html = fs.readFileSync(root + '/web/' + page, 'utf8');
  for (const m of html.matchAll(/<([\w-]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const element = new Element(m[1]); element.id = m[3];
    element.hidden = /\bhidden\b/.test(m[2].replace(/class="[^"]*"/, ''));
    element.disabled = /\bdisabled\b/.test(m[2]);
  }
  const main = new Element('main'); document.body = new Element('body'); document.activeElement = document.body;
  const schedule = (fn, delay) => { const id = ++sequence; timers.set(id, {fn, delay}); return id; };
  const window = {addEventListener: (type, fn) => (events[type] ||= []).push(fn), parent: {postMessage: (data, origin) => posts.push({data, origin})}};
  if (idle) { window.requestIdleCallback = fn => schedule(fn, 'idle'); window.cancelIdleCallback = id => timers.delete(id); }
  const context = {window, document, location: {origin: 'https://huhua.test', href: 'https://huhua.test/', search: embedded ? '?session_id=session-a&embedded=1' : ''},
    URL, URLSearchParams, Blob, TextDecoder, Uint8Array, AbortController, structuredClone,
    setTimeout: schedule, clearTimeout: id => timers.delete(id), requestAnimationFrame: fn => fn(),
    matchMedia: () => ({matches: false}), ResizeObserver: class {observe() {}},
    localStorage: {getItem() {}}, getComputedStyle: () => ({paddingLeft: '0', paddingRight: '0'}),
    fetch: async () => { throw new Error('unexpected fetch'); }};
  return {context, window, document, ids, main, posts, timers,
    run(name, transform = x => x) {
      if (name === 'resume-editor.js' && !window.HuhuaTemplatePreview) vm.runInNewContext(fs.readFileSync(root + '/web/template-preview.js', 'utf8'), context);
      vm.runInNewContext(transform(fs.readFileSync(root + '/web/' + name, 'utf8')), context);
    },
    fire(type, event) { for (const fn of events[type] || []) fn(event); },
    async advance(delay) { for (const [id, timer] of [...timers]) if (timer.delay === delay) { timers.delete(id); await timer.fn(); } await tick(); },
  };
}
async function parentChecks(idle) {
  const f = fixture('index.html', {idle});
  f.run('resume-actions.js'); f.run('resume-workspace.js');
  const $ = id => f.ids.get(id), actions = f.window.HuhuaResumeActions;
  let session = 'session-a', reads = 0, data = {basic_info: {name: '虚构'}};
  actions.init({session: () => session, template: () => 't003-shenlan', data: () => data, refresh: async () => { reads++; return true; }});
  let choices = 0;
  f.window.HuhuaWorkspace.init({session: () => session, sendChoice: async () => { choices++; return true; }});
  assert.deepEqual($('stage-rail').children.map(el => el.textContent), ['读岗位', '挖经历', '写简历', '核对']);
  assert.equal($('workspace-panel-export'), undefined);
  for (const id of ['btn-edit-resume', 'btn-export-pdf', 'btn-export-docx']) assert.equal($(id).disabled, true);
  assert.equal($('resume-actions-hint').textContent, '先生成简历');
  actions.sync({has_data: true, data, revision: 'r1'});
  assert.equal($('resume-editor-overlay').children.length, 0, 'preload waits until idle');
  await f.advance(idle ? 'idle' : 500);
  const frame = $('resume-editor-frame');
  assert.equal(new URL(frame.src, f.context.location.origin).searchParams.get('session_id'), session);
  assert.ok(frame.src.endsWith('&embedded=1')); assert.equal($('resume-editor-overlay').hidden, true);
  const event = (type, origin = f.context.location.origin, source = frame.contentWindow) => f.fire('message', {origin, source, data: {type, revision: 'r1'}});
  $('btn-edit-resume').focus(); $('messages').scrollTop = 321; $('input').value = '保留输入';
  await $('btn-edit-resume').click();
  assert.equal(f.context.location.href, 'https://huhua.test/'); assert.equal(f.main.inert, true);
  assert.equal($('resume-editor-loading').hidden, false);
  await $('btn-cancel-editor-load').click(); assert.equal($('resume-editor-overlay').hidden, true, 'failed or slow load can be closed');
  await $('btn-edit-resume').click();
  event('resume-editor-ready');
  assert.equal($('resume-editor-loading').hidden, true);
  assert.ok(f.posts.some(p => p.data.type === 'resume-editor-open'));
  event('resume-saved', 'https://evil.test'); event('resume-saved', f.context.location.origin, {});
  assert.equal(reads, 0);
  event('resume-saved'); assert.equal(reads, 1);
  event('resume-editor-close', 'https://evil.test'); assert.equal($('resume-editor-overlay').hidden, false);
  event('resume-editor-close'); assert.equal($('resume-editor-overlay').hidden, true);
  assert.equal($('messages').scrollTop, 321); assert.equal($('input').value, '保留输入');
  await $('btn-edit-resume').click(); assert.equal($('resume-editor-frame'), frame, 'reopen reuses editor');
  actions.sync({has_data: true, data, revision: 'r2'});
  assert.ok(f.posts.some(p => p.data.type === 'resume-refresh' && p.data.revision === 'r2'));
  assert.ok(f.posts.every(p => p.origin === f.context.location.origin));
  event('resume-editor-close');
  f.window.HuhuaWorkspace.update({resume: {has_data: true}, focus: 'resume', focus_download: true}, {focus: true});
  assert.equal($('workspace-panel-resume').hidden, false); assert.equal(f.document.activeElement, $('btn-export-pdf'));
  f.window.HuhuaWorkspace.openTab('export'); assert.equal($('workspace-panel-resume').hidden, false);
  f.window.HuhuaWorkspace.update({resume: {has_data: true}, guidance: {question: '下一步', options: [{label: '导出当前版本', value: '导出当前版本'}]}});
  const all = element => [element, ...element.children.flatMap(all)];
  await all($('guidance-dock')).find(element => element.tagName === 'BUTTON' && element.textContent === '导出当前版本').click();
  assert.equal(choices, 0, 'download shortcut navigates locally without sending a model turn');
  assert.equal(f.document.activeElement, $('btn-export-pdf'));
  let accountRefreshes = 0;
  f.window.HuhuaAccount = {guest: () => false, refreshAccount: async () => { accountRefreshes++; }};
  event('resume-account-changed', 'https://evil.test'); assert.equal(accountRefreshes, 0);
  event('resume-account-changed'); await tick(); assert.equal(accountRefreshes, 1);
  f.fire('huhua-account-changed', {});
  assert.equal(f.posts.at(-1).data.type, 'resume-account-changed');
  f.window.HuhuaAccount = null;
  let exports = 0, release;
  f.context.fetch = async (url, options) => { exports++; assert.ok(url.includes('/pdf/t003-shenlan?session_id=session-a')); assert.deepEqual(JSON.parse(options.body), data); return new Promise(resolve => { release = resolve; }); };
  const exporting = $('btn-export-pdf').click(); await tick();
  assert.equal($('btn-export-pdf').textContent, '正在生成…'); await $('btn-export-pdf').click(); assert.equal(exports, 1);
  release({ok: false, json: async () => ({detail: {message: 'PDF 生成暂时失败'}})}); await exporting;
  assert.ok($('workspace-export-status').textContent.includes('PDF 生成暂时失败')); assert.equal($('btn-export-pdf').disabled, false);
  f.window.HuhuaAccount = {requireLogin: () => true}; await $('btn-export-pdf').click(); assert.equal(exports, 1, 'guest gate prevents export');
  f.window.HuhuaAccount = null;
  f.context.fetch = async () => ({ok: true, blob: async () => new Blob(['not-a-pdf'])});
  await $('btn-export-pdf').click(); assert.ok($('workspace-export-status').textContent.includes('文件内容异常'));
  f.context.fetch = async () => ({ok: true, headers: {get: () => "attachment; filename*=UTF-8''%E7%AE%80%E5%8E%86.pdf"}, blob: async () => new Blob(['%PDF-1.7'])});
  await $('btn-export-pdf').click();
  assert.equal($('workspace-export-download').download, '简历.pdf');
  assert.equal($('workspace-export-download').clicks, 1); assert.equal($('workspace-export-open').hidden, false);
  f.context.fetch = async (_, options) => ({ok: true, blob: () => new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(Object.assign(new Error('abort'), {name: 'AbortError'}))))});
  const stalled = $('btn-export-pdf').click(); await tick(); await f.advance(60000); await stalled;
  assert.ok($('workspace-export-status').textContent.includes('等待超时')); assert.equal($('btn-export-pdf').disabled, false);
  f.context.fetch = async () => new Promise(resolve => {release = resolve;});
  const staleExport = $('btn-export-docx').click(); await tick();
  session = 'session-b'; actions.sync({has_data: true, data, revision: 'b1'}); await f.advance(idle ? 'idle' : 500);
  release({ok: true, headers: {get: () => ''}, blob: async () => new Blob(['PK\x03\x04'])}); await staleExport;
  assert.equal($('workspace-export-result').hidden, true, 'old export response cannot attach to new session');
  assert.notEqual($('resume-editor-frame'), frame); assert.ok($('resume-editor-frame').src.includes('session-b'));
  const before = reads; event('resume-saved'); assert.equal(reads, before, 'old iframe cannot refresh new session');
  actions.reset(); await f.advance(idle ? 'idle' : 500); assert.equal($('resume-editor-overlay').children.length, 0);
}
async function editorChecks() {
  const f = fixture('resume.html', {embedded: true}), $ = id => f.ids.get(id);
  f.run('resume-editor.js', code => code.replace('  initialise();', `  window.fixture = {state, initialise, changed, flushSave, seed() {
    state.session = 'session-a'; state.serverRevision = 'r1'; state.canSave = true; editorLoaded = true;
    activateData({basic_info: {name: '虚构'}, sections: []}, 'personal');
  }};`));
  const editor = f.window.fixture; editor.seed();
  assert.equal($('header').hidden, true); assert.equal($('embedded-toolbar').hidden, false);
  let reads = 0, release;
  f.context.fetch = async () => { reads++; return new Promise(resolve => {release = resolve;}); };
  const send = (revision, origin = f.context.location.origin, source = f.window.parent) => f.fire('message', {origin, source, data: {type: 'resume-refresh', revision}});
  let accountRefreshes = 0;
  f.window.HuhuaAccount = {guest: () => false, refreshAccount: async () => { accountRefreshes++; }};
  f.fire('message', {origin: f.context.location.origin, source: f.window.parent, data: {type: 'resume-account-changed'}});
  await tick(); assert.equal(accountRefreshes, 1); f.window.HuhuaAccount = null;
  send('r2', 'https://evil.test'); send('r2', f.context.location.origin, {}); assert.equal(reads, 0);
  send('r2'); await tick(); assert.equal(reads, 1);
  editor.state.data.basic_info.name = '正在输入'; editor.changed();
  release({ok: true, json: async () => ({has_data: true, revision: 'r2', data: {basic_info: {name: '不应覆盖'}}})}); await tick();
  assert.equal(editor.state.data.basic_info.name, '正在输入');
  assert.equal($('chat-version-message').textContent, '对话里有新版本，保存后可刷新');
  assert.equal($('btn-refresh-chat-version').disabled, true);
  send('r3'); assert.equal(reads, 1, 'dirty editor never reloads');
  f.context.fetch = async (_, options) => ({ok: true, json: async () => ({saved: true, revision: 'saved-r3', data: JSON.parse(options.body).resume_data})});
  await editor.flushSave();
  assert.ok(f.posts.some(p => p.data.type === 'resume-saved' && p.data.revision === 'saved-r3' && p.origin === f.context.location.origin));
  assert.equal($('btn-refresh-chat-version').disabled, false);
  f.context.fetch = async () => ({ok: true, json: async () => ({has_data: true, revision: 'r4', data: {basic_info: {name: '最新保存稿'}, sections: []}})});
  await $('btn-refresh-chat-version').click();
  assert.equal(editor.state.data.basic_info.name, '最新保存稿'); assert.equal($('chat-version-notice').hidden, true);
  await $('btn-finish-edit').click(); assert.ok(f.posts.some(p => p.data.type === 'resume-editor-close'));
  f.posts.length = 0;
  editor.state.data.basic_info.name = '冲突时保留'; editor.changed();
  f.context.fetch = async () => ({ok: false, status: 409, json: async () => ({detail: {message: '会话内容已更新'}})});
  await $('btn-finish-edit').click();
  assert.equal(editor.state.data.basic_info.name, '冲突时保留'); assert.equal(editor.state.conflict, true);
  assert.equal($('btn-load-latest').hidden, false); assert.equal(f.posts.length, 0, 'save failure keeps editor open');
  const direct = fixture('resume.html');
  direct.run('resume-editor.js', code => code.replace('  initialise();', ''));
  assert.equal(direct.ids.get('header').hidden, false); assert.equal(direct.ids.get('embedded-toolbar').hidden, true);
}
module.exports = {fixture, tick};
if (require.main === module) (async () => { await parentChecks(true); await parentChecks(false); await editorChecks(); console.log('embedded resume DOM checks passed'); })().catch(error => {console.error(error); process.exitCode = 1;});
