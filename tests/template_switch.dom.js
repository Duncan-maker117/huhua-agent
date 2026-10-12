const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {fixture, tick} = require('./resume_embedded.dom.js');
const templates = [{id:'t004-jianyue', name:'灰条夹页'}, {id:'t003-shenlan', name:'深蓝细线'}];
async function check(editor) {
  const f = fixture(editor ? 'resume.html' : 'index.html');
  const queued = [];
  f.context.localStorage.setItem = () => {};
  f.context.fetch = (url, options) => {
    if (url === '/api/resume/templates') return Promise.resolve({json: async () => ({templates})});
    return new Promise(resolve => queued.push({url, options, resolve}));
  };
  let select, frame;
  if (editor) {
    f.run('resume-editor.js', code => code.replace('  initialise();', '  window.test = {state, selectTemplate};'));
    f.window.test.state.data = {basic_info:{name:'虚构同学'}};
    f.window.test.state.session = 'synthetic';
    select = i => f.window.test.selectTemplate(templates[i]);
    frame = f.ids.get('preview-frame');
  } else {
    const html = fs.readFileSync(require('node:path').join(__dirname, '../web/index.html'), 'utf8');
    f.context.SESSION_ID = 'synthetic'; f.context.localRead = () => null;
    const chips = templates.map(t => {const b = f.document.createElement('button'); b.dataset.id = t.id; return b;});
    f.ids.get('tpl-rail').querySelectorAll = () => chips;
    const script = html.slice(html.indexOf('const canvasState ='), html.indexOf('async function refreshCanvas()'));
    vm.runInNewContext(script + '\nwindow.test = {canvasState, loadTemplates};', f.context);
    await f.window.test.loadTemplates();
    f.window.test.canvasState.data = {basic_info:{name:'虚构同学'}};
    select = i => chips[i].click();
    frame = f.ids.get('live-sheet');
  }
  select(0); await tick(); assert.equal(queued.length, 1);
  select(1); await tick(); assert.equal(queued.length, 2, 'new selection starts before old response');
  assert.ok(queued[1].url.includes('t003-shenlan'));
  assert.equal(queued[0].options.signal.aborted, true, 'old request is cancelled');
  queued[1].resolve({ok:true, text:async () => 'NEW TEMPLATE'}); await tick();
  assert.equal(frame.srcdoc, 'NEW TEMPLATE');
  // Simulate a network layer that ignores abort, including a delayed body.
  queued[0].resolve({ok:true, text:async () => 'OLD TEMPLATE'}); await tick();
  assert.equal(frame.srcdoc, 'NEW TEMPLATE', 'late response never overwrites current choice');
}
(async () => {await check(false); await check(true); console.log('template switch DOM checks passed');})().catch(e => {console.error(e); process.exitCode = 1;});
