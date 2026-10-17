// 执行生产 DOM 控制器；不联网、不依赖 CSS 或真实浏览器。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.handlers = {}; this.attributes = {}; this.textContent = ''; this.value = ''; this.hidden = false; this.disabled = false; }
  append(...rows) { this.children.push(...rows); }
  replaceChildren(...rows) { this.children = rows; }
  addEventListener(event, handler) { this.handlers[event] = handler; }
  setAttribute(key, value) { this.attributes[key] = value; }
  get childElementCount() { return this.children.length; }
  querySelectorAll(selector) { return all(this).slice(1).filter(row => selector.split(',').includes(row.tagName.toLowerCase())); }
  querySelector(selector) { return this.querySelectorAll(selector)[0]; }
  focus() { this.focused = true; }
}
const all = node => [node, ...node.children.flatMap(all)];
const dock = new Element('div');
const context = {window: {}, document: {createElement: tag => new Element(tag), getElementById: () => dock}, Set, Map, JSON};
const source = fs.readFileSync(path.join(__dirname, '../web/resume-workspace.js'), 'utf8').replace('window.HuhuaWorkspace =', `window.fixture = (data, sender, busy = false) => {
  workspace = data; streaming = busy; callbacks = {session: () => 'test-session', sendChoice: sender}; renderGuidance();
}; window.HuhuaWorkspace =`);
vm.runInNewContext(source, context);
const find = cls => all(dock).find(row => row.className?.split(' ').includes(cls));
const finds = cls => all(dock).filter(row => row.className?.split(' ').includes(cls));
const click = async element => { if (!element.disabled) await element.handlers.click?.(); };
const key = async (value, tag = 'BUTTON') => { find('ask-card').handlers.keydown({key: value, target: {tagName: tag}, preventDefault() {}}); for (let i = 0; i < 8; i++) await Promise.resolve(); };
const guidance = {kind: 'ask_user', turn_id: 'ask-1', subject: 'AI 简历', questions: [
  {id: 'status', prompt: '现在什么状态？', kind: 'single', options: ['原型能跑', '已上线'], allow_other: true},
  {id: 'work', prompt: '你本人做了哪些？', kind: 'multi', options: ['想需求', '技术开发'], allow_other: true},
  {id: 'problem', prompt: '解决什么问题？', kind: 'text', placeholder: '一句话'},
  {id: 'users', prompt: '多少人在用？', kind: 'single', options: ['仅自己', '有人使用']},
]};
(async () => {
  const sent = [];
  const sender = async (text, payload) => { sent.push(JSON.parse(JSON.stringify({text, payload}))); return true; };
  context.window.fixture({guidance, tailor: {questions: [{q: '旧问题不应出现', question_id: 'old', options: ['有', '无']}]}}, sender);
  assert.equal(find('ask-card').attributes['aria-label'], '补充问题');
  assert.equal(find('ask-card-progress').textContent, '1 / 4');
  assert.equal(find('ask-card-prev').disabled, true);
  assert.equal(finds('ask-card-page').filter(row => !row.hidden).length, 1);
  assert.equal(find('ask-text').placeholder, '一句话');
  await click(finds('ask-option').find(row => row.textContent === '已上线'));
  assert.equal(find('ask-card-progress').textContent, '2 / 4');
  assert.equal(finds('ask-option').find(row => row.textContent === '已上线').attributes['aria-pressed'], 'true');
  await key('ArrowLeft');
  assert.equal(find('ask-card-progress').textContent, '1 / 4');
  await click(finds('ask-option').find(row => row.textContent === '原型能跑'));
  assert.equal(finds('ask-option').find(row => row.textContent === '已上线').attributes['aria-pressed'], 'false');
  await click(finds('ask-option').find(row => row.textContent === '想需求'));
  await click(finds('ask-option').find(row => row.textContent === '技术开发'));
  assert.equal(find('ask-card-progress').textContent, '2 / 4');
  await click(finds('ask-other')[1]);
  assert.equal(finds('ask-other-input')[1].hidden, false);
  finds('ask-other-input')[1].value = '写提示词'; finds('ask-other-input')[1].handlers.input();
  await click(find('ask-card-next'));
  find('ask-text').value = '学生不会写简历'; find('ask-text').handlers.input();
  await key('Enter', 'TEXTAREA');
  assert.equal(sent.length, 0);
  await key('ArrowRight', 'TEXTAREA');
  assert.equal(find('ask-card-progress').textContent, '3 / 4');
  await click(finds('ask-skip')[2]);
  assert.equal(find('ask-card-progress').textContent, '4 / 4');
  await click(finds('ask-unknown')[3]);
  assert.equal(sent.length, 0);
  const oldSubmit = find('ask-submit');
  await key('Enter', 'BUTTON');
  assert.equal(sent.length, 0);
  await key('Enter', 'INPUT');
  await click(oldSubmit);
  assert.equal(sent.length, 1);
  assert.equal(dock.hidden, true);
  assert.deepEqual(sent[0].payload.answers, {turn_id: 'ask-1', items: [
    {id: 'status', value: '原型能跑', skipped: false, unknown: false},
    {id: 'work', value: ['想需求', '技术开发', '写提示词'], skipped: false, unknown: false},
    {id: 'problem', value: '', skipped: true, unknown: false},
    {id: 'users', value: '', skipped: false, unknown: true},
  ]});
  assert.match(sent[0].text, /想需求、技术开发、写提示词/);
  assert.match(sent[0].text, /多少人在用：不知道/);
  context.window.fixture({guidance}, sender); assert.equal(dock.hidden, true);
  const next = {...guidance, turn_id: 'ask-2'};
  context.window.fixture({guidance: next}, sender, true); assert.equal(dock.hidden, true);
  context.window.fixture({guidance: next}, sender);
  await click(find('ask-submit'));
  assert.ok(sent[1].payload.answers.items.every(item => item.skipped && !item.unknown));
  context.window.fixture({guidance: {...guidance, turn_id: 'retry'}}, async () => false);
  await click(find('ask-submit'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(dock.hidden, false);
  const plan = {kind: 'structure_plan', turn_id: 'plan', structure_plan: {recommended: {label: '推荐', bullet_style: 'plain', section_order: [], experience_plan: []}, alternatives: []}, options: [{label: '按推荐写', value: '按推荐写'}]};
  context.window.fixture({guidance: plan}, sender);
  await click(all(dock).find(row => row.textContent === '问题-决策-结果'));
  assert.equal(sent.length, 2);
  assert.equal(all(dock).find(row => row.textContent === '问题-决策-结果').attributes['aria-pressed'], 'true');
  await click(all(dock).find(row => row.textContent === '按推荐写'));
  assert.deepEqual(sent[2], {text: '按推荐写，写法：问题-决策-结果', payload: {plan_choice: {option: '按推荐写', bullet_style: 'labeled'}}});
  const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
  assert.match(html, /sendChoice: \(value, payload = \{\}\) => send\(value, \{\.\.\.payload, quickReply: true\}\)/);
  assert.match(html, /\.\.\.\(answers \? \{answers\} : \{\}\)/);
  const ids = new Map();
  const webContext = {window: {}, URL, document: {getElementById: id => {
    if (!ids.has(id)) ids.set(id, new Element('div')); return ids.get(id);
  }}};
  const webCode = fs.readFileSync(path.join(__dirname, '../web/web-research.js'), 'utf8').replace('window.HuhuaWebResearch =',
    'window.capabilitiesFixture = value => { capabilities = value; sync(); }; window.HuhuaWebResearch =');
  vm.runInNewContext(webCode, webContext);
  webContext.window.capabilitiesFixture({read_url: false, search: false});
  assert.equal(ids.get('web-read-toggle').hidden, true);
  assert.equal(ids.get('web-search-toggle').hidden, true);
  assert.equal(ids.get('web-tool-actions').hidden, true);
  assert.ok(!ids.get('web-search-toggle').textContent.includes('未开通'));
  webContext.window.capabilitiesFixture({read_url: true, search: false});
  assert.equal(ids.get('web-read-toggle').hidden, false);
  assert.equal(ids.get('web-search-toggle').hidden, true);
  assert.equal(ids.get('web-tool-actions').hidden, false);
  console.log('ask_user DOM checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
