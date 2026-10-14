// Real preview controllers with synthetic data, delayed fetches and frame messages.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {fixture, tick} = require('./resume_embedded.dom.js');
const templates = ['a', 'b', 'c', 'd'].map(id => ({id, name:id.toUpperCase()}));
const html = id => `<html><body><p>${id}</p></body></html>`;
const settle = async () => { for (let i = 0; i < 5; i++) await tick(); };
async function setup(editor, idle = true) {
  const f = fixture(editor ? 'resume.html' : 'index.html', {idle});
  const queued = [], measurements = [];
  Object.getPrototypeOf(f.document.body).getBoundingClientRect = () => ({top:0, bottom:100, height:100});
  f.ids.get(editor ? 'preview-scroll' : 'canvas-sheet-wrap').clientWidth = 900;
  f.window.performance = {mark: name => measurements.push(name), measure: name => measurements.push(name), clearMarks() {}, clearMeasures() {}};
  f.context.localStorage.setItem = () => {};
  f.context.fetch = (url, options) => {
    if (url === '/api/resume/templates') return Promise.resolve({ok:true, json:async () => ({templates})});
    if (url === '/api/resume/sample') return Promise.resolve({ok:true, json:async () => ({basic_info:{name:'虚构同学'}, sections:[]})});
    return new Promise(resolve => queued.push({url, options, resolve}));
  };
  let chips, select, edit, reset;
  if (editor) {
    f.run('resume-editor.js', code => code.replace('  initialise();', '  window.test = {state, changed, renderPreview, controls}; initialise();'));
    await settle();
    chips = f.ids.get('template-list').children;
    select = i => chips[i].click();
    edit = () => { f.window.test.state.requireAccount = false; f.window.test.state.data.basic_info.name += '!'; f.window.test.changed('/basic_info/name', '新值'); };
    reset = () => f.fire('huhua-account-reset', {});
  } else {
    f.run('template-preview.js');
    const source = fs.readFileSync(require('node:path').join(__dirname, '../web/index.html'), 'utf8');
    f.context.SESSION_ID = 'synthetic'; f.context.localRead = () => null;
    chips = templates.map(t => { const b = f.document.createElement('button'); b.dataset.id = t.id; return b; });
    f.ids.get('tpl-rail').querySelectorAll = () => chips;
    const script = source.slice(source.indexOf('const canvasState ='), source.indexOf('async function refreshCanvas()'));
    vm.runInNewContext(script + '\nwindow.test = {canvasState, loadTemplates, paintSheet, resetCanvasPreview, highlightBullet};', f.context);
    await f.window.test.loadTemplates();
    f.window.test.canvasState.data = {basic_info:{name:'虚构同学'}};
    select = i => chips[i].click();
    edit = () => { f.window.test.canvasState.data.basic_info.name += '!'; f.window.test.paintSheet(f.window.test.canvasState.data); };
    reset = () => { f.window.test.canvasState.data = null; f.window.test.resetCanvasPreview(); };
    select(0); await settle();
  }
  const id = editor ? 'preview-frame' : 'live-sheet';
  const front = () => f.ids.get(id), back = () => f.ids.get(id + '-back');
  const token = frame => Number(frame.srcdoc.match(/token: (\d+)/)[1]);
  const ready = (frame = back(), value = token(frame)) => f.fire('message', {source:frame.contentWindow, data:{type:'huhua-preview-loaded',token:value,height:1300}});
  const invariant = () => {
    assert.equal([front(), back()].filter(p => p.style.visibility === 'visible').length, 1);
    assert.equal(front().attributes['aria-hidden'], 'false'); assert.equal(front().inert, false);
    assert.equal(back().attributes['aria-hidden'], 'true'); assert.equal(back().attributes.tabindex, '-1');
    assert.equal(back().inert, true); assert.ok('inert' in back().attributes);
  };
  const resolve = async (index, value) => { queued[index].resolve({ok:true,text:async () => html(value)}); await settle(); };
  const emit = (index, event) => { for (const handler of chips[index].handlers[event] || []) handler({}); };
  const runTimers = async delay => {
    for (const [id, timer] of [...f.timers]) if (timer.delay === delay) { f.timers.delete(id); timer.fn(); }
    await settle();
  };
  assert.equal(queued.length, 1); invariant();
  await resolve(0, 'a');
  assert.ok(!front().srcdoc, 'old visible document is preserved until background ready');
  ready(); await settle(); invariant(); assert.ok(front().srcdoc.includes('<p>a</p>'));
  return {f, queued, select, edit, reset, front, back, ready, token, invariant, resolve, emit, runTimers, measurements, editor};
}
async function cache(editor) {
  const t = await setup(editor);
  t.select(1); await settle(); await t.resolve(1, 'b'); t.invariant();
  assert.ok(t.front().srcdoc.includes('<p>a</p>'));
  t.ready(); await settle();
  t.select(0); await settle(); assert.equal(t.queued.length, 2, 'cached A does not fetch');
  t.ready(); await settle(); t.select(1); await settle(); t.ready(); await settle();
  assert.equal(t.queued.length, 2); t.invariant();
  assert.ok(t.front().style.transform.startsWith('scale('));
  assert.equal(t.front().style.transform, t.back().style.transform);
  assert.ok(t.measurements.includes('huhua-template-switch'));
}
async function hover(editor) {
  const t = await setup(editor);
  t.emit(1, 'pointerenter'); await t.runTimers(80); assert.equal(t.queued.length, 2);
  t.select(1); await settle(); assert.equal(t.queued.length, 2, 'click shares in-flight prefetch');
  assert.equal(t.queued[1].options.signal.aborted, false);
  await t.resolve(1, 'b'); t.ready(); await settle();
  t.emit(2, 'focus'); await t.runTimers(80); await t.resolve(2, 'c');
  t.select(2); await settle(); assert.equal(t.queued.length, 3, 'completed focus prefetch hits cache');
  t.ready(); await settle(); t.invariant();
}
async function revision(editor) {
  const t = await setup(editor);
  t.emit(1, 'pointerenter'); await t.runTimers(80); await t.resolve(1, 'old-b');
  t.emit(2, 'focus'); await t.runTimers(80);
  t.edit(); await settle(); assert.equal(t.queued[2].options.signal.aborted, true, 'revision cancels speculative request');
  await t.resolve(2, 'old-c');
  if (editor) {
    const before = t.queued.length;
    t.emit(3, 'pointerenter'); await t.runTimers(80); await t.runTimers('idle');
    assert.equal(t.queued.length, before, 'editing debounce suppresses prefetch');
    await t.runTimers(180);
  }
  const latest = t.queued.length - 1;
  await t.resolve(latest, 'new-a'); t.ready(); await settle();
  const before = t.queued.length;
  t.select(1); await settle(); assert.equal(t.queued.length, before + 1, 'revision drops cached B');
  await t.resolve(before, 'new-b'); t.ready(); await settle();
  t.select(2); await settle(); assert.equal(t.queued.length, before + 2, 'aborted late C cannot poison current cache');
}
async function rapid(editor) {
  const t = await setup(editor);
  // Let B enter the background, then click A -> B -> C before any load finishes.
  t.select(1); await settle(); await t.resolve(1, 'b');
  const oldBack = t.back(), oldToken = t.token(oldBack);
  t.select(0); t.select(1); t.select(2); await settle();
  t.ready(oldBack, oldToken); t.invariant();
  assert.ok(t.front().srcdoc.includes('<p>a</p>'), 'stale background ready cannot switch');
  const c = t.queued.at(-1); assert.ok(c.url.includes('/c?') || c.url.endsWith('/c'));
  await t.resolve(t.queued.length - 1, 'c');
  // Same WindowProxy is reused: source alone is insufficient for load messages.
  t.ready(t.back(), oldToken); assert.ok(t.front().srcdoc.includes('<p>a</p>'));
  t.ready(); await settle(); assert.ok(t.front().srcdoc.includes('<p>c</p>')); t.invariant();
  t.ready(oldBack, oldToken); assert.ok(t.front().srcdoc.includes('<p>c</p>'));
}
async function staleNetwork(editor) {
  const t = await setup(editor);
  t.select(1); await settle(); t.select(2); await settle();
  assert.equal(t.queued[1].options.signal.aborted, true);
  await t.resolve(2, 'c'); t.ready(); await settle();
  await t.resolve(1, 'b'); assert.ok(t.front().srcdoc.includes('<p>c</p>'));
  t.invariant();
}
async function idle(editor, available = true) {
  const t = await setup(editor, available);
  const delay = available ? 'idle' : 200;
  await t.runTimers(delay); assert.equal(t.queued.length, 2); assert.ok(t.queued[1].url.includes('/b'));
  await t.runTimers(delay); assert.equal(t.queued.length, 2, 'idle walk is serial');
  t.emit(2, 'focus'); await t.runTimers(80); assert.equal(t.queued.length, 3);
  t.emit(3, 'pointerenter'); await t.runTimers(80); assert.equal(t.queued.length, 3, 'at most two prefetches');
  await t.resolve(1, 'b'); await t.runTimers(delay); assert.equal(t.queued.length, 3, 'idle walk shares hover promise');
  await t.resolve(2, 'c'); await t.runTimers(delay); assert.equal(t.queued.length, 4); assert.ok(t.queued[3].url.includes('/d'));
}
async function reset(editor) {
  const t = await setup(editor);
  t.select(1); await settle(); await t.resolve(1, 'b');
  const staleFrame = t.back(), staleToken = t.token(staleFrame);
  t.emit(2, 'focus'); await t.runTimers(80);
  t.reset(); assert.equal(t.queued[2].options.signal.aborted, true);
  t.ready(staleFrame, staleToken); await t.resolve(2, 'late-c'); await t.runTimers('idle');
  assert.equal(t.front().srcdoc, ''); assert.equal(t.back().srcdoc, ''); t.invariant();
}
async function failed(editor) {
  const t = await setup(editor);
  t.emit(1, 'focus'); await t.runTimers(80); t.queued[1].resolve({ok:false, json:async () => ({})}); await settle();
  t.select(1); await settle(); assert.equal(t.queued.length, 3, 'failed prefetch is retried');
  await t.resolve(2, 'b'); await t.runTimers(15000);
  assert.ok(t.front().srcdoc.includes('<p>a</p>'), 'load timeout leaves old preview visible'); t.invariant();
  t.select(1); await settle(); assert.equal(t.queued.length, 3); t.ready(); await settle();
  assert.ok(t.front().srcdoc.includes('<p>b</p>'));
}
async function interactions() {
  const t = await setup(true), {f} = t;
  let focuses = 0;
  f.window.test.controls.get('/basic_info/name').input.focus = () => { focuses++; };
  const message = (source, data) => f.fire('message', {source:source.contentWindow, data});
  // Height and hover reports from the hidden buffer must not alter the visible page.
  const height = f.window.test.state.height;
  message(t.back(), {type:'resume-preview-ready',height:9999});
  message(t.back(), {type:'resume-field-hover',path:'/basic_info/name'});
  assert.equal(f.window.test.state.height, height); assert.equal(f.window.test.state.previewHover, null);
  message(t.front(), {type:'resume-field-hover',path:'/basic_info/name'});
  assert.equal(f.window.test.state.previewHover, '/basic_info/name');
  message(t.back(), {type:'resume-field-select',path:'/basic_info/name'}); assert.equal(focuses, 0);
  message(t.front(), {type:'resume-field-select',path:'/basic_info/name'}); assert.equal(focuses, 1);
  t.select(1); await settle(); await t.resolve(1, 'b');
  const previous = t.front(); t.ready(); await settle();
  message(previous, {type:'resume-field-hover',path:'/basic_info/name'});
  assert.equal(f.window.test.state.previewHover, null);
  f.ids.get('export-menu').hidden = false;
  message(previous, {type:'resume-preview-escape'}); assert.equal(f.ids.get('export-menu').hidden, false);
  message(t.front(), {type:'resume-preview-escape'}); assert.equal(f.ids.get('export-menu').hidden, true);
  message(t.front(), {type:'resume-preview-ready',height:1400}); assert.equal(f.window.test.state.height, 1400);
  const posts = [];
  t.front().contentWindow.postMessage = data => posts.push(data);
  t.back().contentWindow.postMessage = () => assert.fail('field update must use visible frame');
  t.edit(); assert.equal(posts.at(-1).type, 'resume-field-value');
  // Main canvas marks only the displayed copy; raw HTML stays reusable in cache.
  const main = await setup(false);
  main.f.window.test.highlightBullet('a'); await settle(); main.ready(); await settle();
  assert.ok(main.front().srcdoc.includes('data-located'));
  main.f.window.test.highlightBullet(null); await settle(); main.ready(); await settle();
  assert.equal(main.queued.length, 1); assert.ok(!main.front().srcdoc.includes('data-located'));
}
async function fonts() {
  const t = await setup(true);
  t.select(1); await settle(); await t.resolve(1, 'b');
  const script = t.back().srcdoc.match(/<script>([\s\S]*?)<\/script>/)[1];
  for (const timeout of [false, true]) {
    const events = {}, timers = new Map(), messages = [];
    let resolveFonts;
    const ready = new Promise(resolve => { resolveFonts = resolve; });
    vm.runInNewContext(script, {
      window:{addEventListener:(name, fn) => { events[name] = fn; }}, parent:{postMessage:message => messages.push(message)},
      document:{fonts:{ready}, body:{getBoundingClientRect:() => ({height:1250})}},
      setTimeout:(fn, delay) => { timers.set(delay, fn); return delay; }, clearTimeout: id => timers.delete(id),
    });
    assert.equal(messages.length, 0); events.load(); await settle(); assert.equal(messages.length, 0, 'wait for fonts after load');
    if (timeout) timers.get(300)(); else resolveFonts();
    await settle(); assert.equal(messages.length, 1); assert.equal(messages[0].height, 1250); assert.equal(timers.size, 0);
    resolveFonts(); await settle(); assert.equal(messages.length, 1, 'late fonts cannot double-commit');
  }
}
const checks = {cache, hover, revision, rapid, staleNetwork, idle, fallback:(editor) => idle(editor, false), reset, failed, interactions, fonts};
(async () => {
  const scenario = process.argv[2] || 'staleNetwork';
  if (['fonts','interactions'].includes(scenario)) await checks[scenario]();
  else for (const editor of [false, true]) await checks[scenario](editor);
  console.log('template switch DOM checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
