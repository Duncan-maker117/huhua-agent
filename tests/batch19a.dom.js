const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {fixture} = require('./resume_embedded.dom.js');
const all = el => [el, ...el.children.flatMap(all)];
const contents = el => [el.textContent, ...el.children.map(contents)].filter(Boolean).join('\n');
const event = extra => ({preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }, ...extra});
function setup() {
  const f = fixture('index.html'), $ = id => f.ids.get(id), docEvents = {};
  const proto = Object.getPrototypeOf($('evidence-card'));
  const originalReplace = proto.replaceChildren;
  proto.replaceChildren = function (...nodes) { this.textContent = ''; originalReplace.call(this, ...nodes); };
  proto.contains = function (target) { return all(this).includes(target); };
  proto.appendChild = function (child) { this.append(child); return child; };
  proto.getAttribute = function (key) { return this.attributes[key]; };
  proto.hasAttribute = function (key) { return Object.hasOwn(this.attributes, key); };
  proto.getBoundingClientRect = function () { return this.rect || {left: 700, right: 1020, top: 100, bottom: 580, width: 320, height: 480}; };
  proto.getClientRects = function () { return this.hidden ? [] : [this.getBoundingClientRect()]; };
  proto.querySelectorAll = function () { return all(this).slice(1).filter(el => ['BUTTON', 'SUMMARY'].includes(el.tagName)); };
  f.document.addEventListener = (type, fn) => (docEvents[type] ||= []).push(fn);
  f.doc = (type, data) => { for (const fn of docEvents[type] || []) fn(event(data)); };
  f.document.head = f.document.createElement('head');
  f.context.Element = proto.constructor;
  f.window.innerWidth = 1440; f.window.innerHeight = 960;
  $('live-sheet').clientWidth = 794;
  $('live-sheet').rect = {left: 780, right: 1415.2, top: 250, bottom: 1148, width: 635.2, height: 898};
  $('workspace-body').rect = {left: 750, right: 1440, top: 100, bottom: 960, width: 690, height: 860};
  $('input').value = '';
  let session = 'evidence-a', sends = 0, located;
  const store = new Map();
  f.context.localStorage = {getItem: key => store.get(key), setItem: (key, value) => store.set(key, value)};
  // Exercise the actual page draft-preserving callback, not a reimplementation.
  const html = fs.readFileSync(require('node:path').join(__dirname, '../web/index.html'), 'utf8');
  f.context.inputEl = $('input'); f.context.autoResize = () => {};
  vm.runInNewContext('window.prefill = function(value) {' + html.match(/fillInput\(value\) \{([\s\S]*?)\n  \},/)[1] + '\n}', f.context);
  f.run('resume-evidence.js'); f.run('resume-workspace.js');
  f.window.HuhuaWorkspace.init({session: () => session, fillInput: f.window.prefill,
    sendChoice() { sends++; }, highlight(value) { located = value; }});
  const data = {projects: [{item_id: 'p', name: '测试项目', tech_stack: ['Python'],
    polished_bullets: ['实现页面选择', '整理反馈并优化流程', '手动写的句子', '完成上线', '未找到材料的句子']}]};
  const fact = (body, extra = {}) => ({item_id: 'p', kind: 'action', text: body, source_quote: body, active: true, ...extra});
  const workspace = {resume: {version: 'v1', has_data: true}, focus: 'resume',
    jd: {info: {role_profile: {requirements: [{id: 'r1', text: '根据反馈迭代流程'}]}}},
    tailor: {evidence: {facts: {f1: fact('我做了页面选择'), f2: fact('我整理过反馈'), f3: fact('材料三'),
      f4: fact('材料四'), f5: fact('材料五', {source_quote: ''}), old: fact('当时说已经上线', {active: false})}},
      match_plan: {requirements: [{req_id: 'r1', status: 'transferable'}]},
      resume_meta: {tech_stack: {p: [{fact_ids: ['f1']}]}, bullets: {p: [
        {fact_ids: ['f1']}, {fact_ids: ['f2', 'f2', 'f3', 'f4', 'f5'], req_ids: ['r1'], flags: ['transferable', 'secret_unknown_code'], needs_metric: true, metric_question: '一共整理了多少条反馈？'},
        {}, {fact_ids: ['old']}, {fact_ids: ['missing']} ]}}}};
  const update = () => {
    f.window.HuhuaWorkspace.update(workspace);
    f.window.HuhuaWorkspace.canvasResult({data, has_data: true, workspace});
  };
  const select = (index, source = $('live-sheet').contentWindow, rect = {left: 30, right: 700, top: 100, bottom: 120}) =>
    f.fire('message', {source, data: {type: 'huhua-evidence-select', path: '/projects/0/polished_bullets/' + index, rect}});
  const click = label => all($('evidence-card')).find(el => el.tagName === 'BUTTON' && el.textContent === label).click();
  const state = () => f.posts.filter(post => post.data.type === 'huhua-evidence-state').at(-1).data;
  return {...f, $, data, workspace, update, select, click, state, store,
    setSession: value => { session = value; }, sends: () => sends, located: () => located};
}
const cases = {
  async stats() {
    const f = setup(), {$, workspace, data} = f;
    f.update();
    assert.equal(contents($('evidence-summary')), '6 条要点 · 2 条能对上你的原话\n · \n3 条待你确认\n · 1 条是你手动写的');
    assert.equal($('evidence-toggle').getAttribute('aria-pressed'), 'true');
    workspace.tailor.resume_meta = {}; f.update();
    assert.equal(contents($('evidence-summary')), '这份稿是手动编辑的，暂无可追溯的原话');
    assert.equal($('evidence-toggle').disabled, true);
    workspace.tailor.resume_meta = {bullets: {p: data.projects[0].polished_bullets.map(() => ({fact_ids: ['f1']}))}, tech_stack: {p: [{fact_ids: ['f1']}]}};
    f.update(); assert.ok(contents($('evidence-summary')).includes('6 条能对上你的原话'));
    assert.ok(!contents($('evidence-summary')).includes('待你确认'), 'no pending link when everything is supported');
    f.fire('message', {source: $('live-sheet').contentWindow, data: {type: 'huhua-evidence-ready', paths: ['/projects/0/polished_bullets/0']}});
    assert.ok(contents($('evidence-summary')).startsWith('1 条要点'), 'counts actual template-visible fields');
  },
  async preferences() {
    const f = setup(), {$} = f; f.update();
    await $('evidence-toggle').click(); assert.equal(f.state().enabled, false);
    assert.equal(f.store.get('huhua_resume_evidence:evidence-a'), 'false');
    f.update(); assert.equal(f.state().enabled, false);
    f.setSession('evidence-b'); f.update(); assert.equal(f.state().enabled, true);
    f.setSession('evidence-a'); f.update(); assert.equal(f.state().enabled, false);
    f.context.localStorage = {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }};
    f.setSession('evidence-c'); f.update(); assert.equal(f.state().enabled, true);
    await $('evidence-toggle').click(); assert.equal(f.state().enabled, false);
  },
  async cards() {
    const f = setup(), {$} = f; f.update();
    assert.deepEqual(Array.from(f.state().rows, row => row.state), ['supported', 'supported', 'pending', 'manual', 'pending', 'pending']);
    f.select(0); assert.ok(contents($('evidence-card')).includes('「我做了页面选择」'));
    assert.equal(f.document.activeElement, $('evidence-card'));
    assert.ok(parseFloat($('evidence-card').style.top) >= 250 + 120 * .8, 'below scaled bullet without overlap');
    f.select(1);
    let content = contents($('evidence-card'));
    for (const part of ['待你确认', '根据反馈迭代流程', '可迁移', '再看 1 条', '整理自你的材料', '可以补一个数字：一共整理了多少条反馈？', '这句借用了你的相关经历']) assert.ok(content.includes(part), part);
    assert.equal(content.split('「我整理过反馈」').length, 2, 'deduplicated quotes');
    assert.ok(!content.includes('secret_unknown_code') && !content.includes('r1'));
    f.workspace.tailor.evidence.facts.duplicate = {...f.workspace.tailor.evidence.facts.f2, active: false};
    f.workspace.tailor.resume_meta.bullets.p[1].fact_ids.push('duplicate');
    f.update(); f.select(1); content = contents($('evidence-card'));
    assert.equal(content.split('「我整理过反馈」').length, 2, 'identical quotes across fact IDs still appear once');
    assert.ok(content.includes('依据已更新，待确认'));
    f.select(2); assert.ok(contents($('evidence-card')).includes('这句是你手动改的，没有关联原话'));
    f.select(3); content = contents($('evidence-card'));
    assert.ok(content.includes('依据已更新，待确认') && content.includes('你后来更正过这里的说法'));
    f.select(4); assert.ok(contents($('evidence-card')).includes('未找到依据'));
    f.workspace.tailor.match_plan.requirements[0].status = 'direct'; f.update(); f.select(1);
    assert.ok(contents($('evidence-card')).includes('直接证据'));
    f.workspace.tailor.evidence.facts.f1.source_quote = '<img src=x onerror=alert(1)>'; f.update(); f.select(0);
    assert.equal(all($('evidence-card')).filter(el => ['IMG', 'SCRIPT'].includes(el.tagName)).length, 0);
    assert.ok(contents($('evidence-card')).includes('<img src=x onerror=alert(1)>'));
  },
  async actions() {
    const f = setup(), {$} = f; f.update();
    $('input').value = '我的未发送草稿'; f.select(0); await f.click('在对话里改这句');
    assert.equal($('input').value, '我的未发送草稿\n把这句改一下：「实现页面选择」');
    assert.equal(f.sends(), 0); assert.equal(f.document.activeElement, $('input'));
    f.window.HuhuaWorkspace.setStreaming(true);
    f.select(1); await f.click('回答这个问题');
    assert.ok($('input').value.endsWith('\n一共整理了多少条反馈？')); assert.equal(f.sends(), 0);
    f.window.HuhuaWorkspace.setStreaming(false);
    f.select(0); await f.click('定位到写简历'); assert.equal(f.located(), '实现页面选择');
    assert.equal($('workspace-panel-resume').hidden, false);
    const paths = Array.from(f.state().rows, row => row.path);
    f.window.HuhuaEvidence.attach();
    f.fire('message', {source: $('live-sheet').contentWindow, data: {type: 'huhua-evidence-ready', paths}});
    assert.equal(f.posts.at(-1).data.type, 'huhua-evidence-reveal');
    assert.equal(f.posts.at(-1).data.path, '/projects/0/polished_bullets/0');
    f.fire('message', {source: $('live-sheet').contentWindow, data: {type: 'huhua-evidence-select', path: '/projects/0/tech_stack', rect: {left: 30, right: 700, top: 100, bottom: 120}}});
    await f.click('定位到写简历');
    f.window.HuhuaEvidence.attach();
    f.fire('message', {source: $('live-sheet').contentWindow, data: {type: 'huhua-evidence-ready', paths}});
    assert.equal(f.posts.at(-1).data.path, '/projects/0/tech_stack', 'technical-line markup does not break locate');
    await all($('evidence-summary')).find(el => el.tagName === 'BUTTON').click();
    assert.equal(f.posts.at(-1).data.path, '/projects/0/polished_bullets/1');
    await all($('evidence-summary')).find(el => el.tagName === 'BUTTON').click();
    assert.equal(f.posts.at(-1).data.path, '/projects/0/polished_bullets/3', 'hand-written lines are not pending');
  },
  async closing() {
    const f = setup(), {$} = f; f.update(); f.select(0);
    const buttons = all($('evidence-card')).filter(el => el.tagName === 'BUTTON');
    const reverseTab = event({key: 'Tab', shiftKey: true});
    $('evidence-card').handlers.keydown[0](reverseTab);
    assert.equal(reverseTab.prevented, true); assert.equal(f.document.activeElement, buttons.at(-1));
    $('evidence-card').handlers.keydown[0](event({key: 'Tab'}));
    assert.equal(f.document.activeElement, buttons[0]);
    f.doc('keydown', {key: 'Escape'}); assert.equal($('evidence-card').hidden, true); assert.equal(f.document.activeElement, $('live-sheet'));
    f.select(0); f.doc('pointerdown', {target: $('input')}); assert.equal($('evidence-card').hidden, true);
    f.select(0); f.select(0); assert.equal($('evidence-card').hidden, true);
    f.select(0); f.doc('scroll', {target: $('evidence-card')}); assert.equal($('evidence-card').hidden, false);
    f.doc('scroll', {target: $('workspace-body')}); assert.equal($('evidence-card').hidden, true);
    f.select(0); f.fire('resize', {}); assert.equal($('evidence-card').hidden, true);
    f.select(0); await $('evidence-toggle').click(); f.select(1); assert.equal($('evidence-card').hidden, true);
    assert.equal(f.state().enabled, false);
  },
  async switching() {
    const f = setup(), {$} = f; f.update(); f.select(0);
    const old = $('live-sheet'), next = $('live-sheet-back'); old.id = 'old-sheet'; next.id = 'live-sheet';
    next.clientWidth = 794; next.rect = old.rect;
    f.window.HuhuaEvidence.attach(); assert.equal($('evidence-card').hidden, true);
    f.select(0, old.contentWindow); assert.equal($('evidence-card').hidden, true);
    f.select(0); assert.equal($('evidence-card').hidden, false);
    assert.ok(contents($('evidence-card')).includes('我做了页面选择'));
    f.select(1, {}); assert.ok(contents($('evidence-card')).includes('我做了页面选择'), 'foreign messages ignored');
    f.window.HuhuaWorkspace.update({...f.workspace, resume: {version: 'v2', has_data: true}});
    f.select(1); assert.equal($('evidence-card').hidden, true, 'ahead metadata never attaches to old rendered prose');
    f.workspace.resume.version = 'v2'; f.data.projects[0].polished_bullets[0] = '手改后的要点'; f.workspace.tailor.resume_meta.bullets.p[0] = {};
    f.update(); f.select(0); assert.ok(contents($('evidence-card')).includes('手动改的'));
    f.window.innerWidth = 390; f.window.HuhuaEvidence.close(); f.select(1);
    assert.equal($('evidence-card').style.top, '', 'mobile position delegated to CSS bottom sheet');
    f.window.HuhuaWorkspace.reset(); assert.equal($('evidence-card').hidden, true); assert.equal($('evidence-toggle').disabled, true);
  },
  async bridge() {
    const f = setup(), proto = f.context.Element.prototype;
    const fields = ['polished_bullets/0', 'polished_bullets/1', 'polished_bullets/2', 'tech_stack'].map(path => {
      const el = f.document.createElement('span'); el.dataset.fieldPath = '/projects/0/' + path; return el;
    });
    proto.closest = function () { return fields.includes(this) ? this : this.parentElement?.closest(); };
    f.document.querySelectorAll = () => fields;
    f.run('resume-evidence-preview.js');
    const send = data => f.fire('message', {source: f.window.parent, data});
    const config = {type: 'huhua-evidence-state', enabled: true, rows: fields.map((el, i) => ({path: el.dataset.fieldPath, state: ['supported', 'pending', 'manual', 'pending'][i]}))};
    send(config);
    for (const [i, el] of fields.entries()) assert.equal(el.getAttribute('data-evidence-state'), config.rows[i].state);
    f.doc('click', {target: fields[1]}); assert.equal(f.posts.at(-1).data.path, '/projects/0/polished_bullets/1');
    assert.ok(Number.isFinite(f.posts.at(-1).data.rect.top));
    f.doc('keydown', {target: fields[0], key: 'Enter'}); assert.equal(f.posts.at(-1).data.type, 'huhua-evidence-select');
    send({type: 'huhua-evidence-reveal', path: fields[1].dataset.fieldPath}); assert.equal(fields[1].scrolled, true);
    assert.equal(f.posts.at(-1).data.type, 'huhua-evidence-revealed');
    send({...config, enabled: false});
    assert.ok(fields.every(el => !el.hasAttribute('data-evidence-state') && !el.hasAttribute('role')));
    const count = f.posts.length; f.doc('click', {target: fields[1]}); assert.equal(f.posts.length, count);
    f.fire('message', {source: {}, data: config}); assert.ok(fields.every(el => !el.hasAttribute('data-evidence-state')));
    const css = f.document.head.children.at(-1).textContent;
    assert.ok(css.includes('underline wavy #d97706') && css.includes('@media print') && css.includes('text-decoration: none !important'));
  },
};
(async () => {
  const names = process.argv[2] ? [process.argv[2]] : Object.keys(cases);
  for (const name of names) { await cases[name](); console.log('evidence DOM passed: ' + name); }
})().catch(error => { console.error(error); process.exit(1); });
