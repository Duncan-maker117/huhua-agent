// 执行真实前端控制器；结构、提交及失败重试均用轻量 DOM 桩验证。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.handlers = {}; this.attributes = {}; this.value = ''; this.hidden = false; this.disabled = false; }
  append(...rows) { this.children.push(...rows); }
  replaceChildren(...rows) { this.children = rows; }
  addEventListener(event, handler) { this.handlers[event] = handler; }
  setAttribute(key, value) { this.attributes[key] = value; }
  get childElementCount() { return this.children.length; }
  focus() { this.focused = true; }
}
const all = node => [node, ...node.children.flatMap(all)];
const dock = new Element('div');
const context = {window: {}, document: {createElement: tag => new Element(tag),
  createTextNode: text => Object.assign(new Element('#text'), {textContent: text}), getElementById: () => dock}, Set, Map, JSON};
const source = fs.readFileSync(path.join(__dirname, '../web/resume-workspace.js'), 'utf8').replace('window.HuhuaWorkspace =', `window.fixture = (data, sender, busy = false, session = 'session') => {
  workspace = data; streaming = busy; callbacks = {session: () => session, sendChoice: sender}; renderGuidance();
}; window.HuhuaWorkspace =`);
vm.runInNewContext(source, context);
const finds = cls => all(dock).filter(row => row.className?.split(' ').includes(cls));
const find = cls => finds(cls)[0];
const fields = name => all(dock).filter(row => row.name === name);
const click = async row => { if (!row.disabled) await row.handlers.click?.(); };
const fill = (name, value, index = 0) => { const input = fields(name)[index]; input.value = value; (input.handlers.input || input.handlers.change)(); };
const submit = () => find('intake-card').handlers.submit({preventDefault() {}});
const experience = {kind: 'intake_experiences', title: '经历清单', turn_id: 'exp', items: [{item_id: 'p1', name: '胡话简历', type: '项目', start: '', end: '', role: '', summary: ''}]};
(async () => {
  const sent = [], sender = async (text, payload) => { sent.push(JSON.parse(JSON.stringify({text, payload}))); return true; };
  context.window.fixture({guidance: experience}, sender);
  assert.equal(find('intake-card').tagName, 'FORM');
  assert.equal(find('intake-card').dataset.intake, 'experiences');
  assert.equal(find('intake-card').attributes['aria-label'], '经历清单');
  assert.equal(find('intake-row').tagName, 'FIELDSET');
  assert.equal(fields('type')[0].tagName, 'SELECT');
  assert.equal(fields('start')[0].type, 'month');
  assert.equal(find('intake-row-remove').hidden, true);
  await click(find('intake-add'));
  assert.equal(finds('intake-row').length, 2);
  assert.ok(finds('intake-row-remove').every(row => !row.hidden));
  await submit();
  assert.equal(sent.length, 0);
  assert.equal(finds('intake-error')[1].attributes.role, 'alert');
  assert.equal(finds('intake-error')[1].hidden, false);
  assert.equal(fields('name')[1].focused, true);
  fill('name', '校园比赛', 1); fill('type', '竞赛', 1);
  fill('start', '2026-07'); fill('end', '2026-09'); fill('role', '独立开发');
  const checkbox = all(find('intake-check')).find(row => row.type === 'checkbox');
  checkbox.checked = true; checkbox.handlers.change();
  assert.equal(fields('end')[0].disabled, true);
  checkbox.checked = false; checkbox.handlers.change();
  assert.equal(fields('end')[0].value, '2026-09');
  checkbox.checked = true; checkbox.handlers.change();
  await click(finds('intake-row-remove')[1]);
  assert.equal(finds('intake-row').length, 1);
  assert.equal(fields('name')[0].value, '胡话简历');
  fill('summary', '通过对话帮助学生整理经历');
  const oldForm = find('intake-card');
  await submit(); await oldForm.handlers.submit({preventDefault() {}});
  assert.equal(sent.length, 1);
  assert.equal(sent[0].payload.intake.items[0].item_id, 'p1');
  assert.equal(sent[0].payload.intake.items[0].end, '至今');
  assert.equal(sent[0].payload.intake.items[0].start, '2026-07');
  assert.match(sent[0].text, /胡话简历.*2026-07 至今.*独立开发/);
  assert.doesNotMatch(sent[0].text, /至 至今/);
  assert.equal(dock.hidden, true);
  const retry = {...experience, turn_id: 'retry'};
  context.window.fixture({guidance: retry}, async () => false);
  fill('name', '重试保留'); fill('role', '产品设计'); await submit();
  assert.equal(dock.hidden, false); assert.equal(fields('name')[0].value, '重试保留');
  context.window.fixture({guidance: retry}, sender, true); assert.equal(dock.hidden, true);
  context.window.fixture({guidance: retry}, sender); assert.equal(fields('role')[0].value, '产品设计');
  const basics = {kind: 'intake_basics', title: '确认基本信息', turn_id: 'basic', values: {name: '张三', school: '测试大学'}};
  context.window.fixture({guidance: basics}, sender);
  assert.equal(fields('name')[0].value, '张三');
  assert.equal(fields('degree')[0].tagName, 'SELECT');
  assert.equal(fields('graduation')[0].type, 'month');
  assert.equal(fields('phone').length + fields('email').length, 2);
  assert.equal(fields('availability')[0].placeholder, '找实习再填，全职可留空');
  assert.equal(find('intake-submit').type, 'submit');
  fill('degree', '本科'); fill('graduation', '2027-06'); fill('availability', '每周4天，3个月');
  await submit();
  assert.equal(sent[1].payload.intake.values.degree, '本科');
  assert.match(sent[1].text, /每周4天/);
  context.window.fixture({guidance: {...basics, turn_id: 'skip'}}, sender);
  await click(find('intake-skip')); assert.equal(sent[2].payload.intake.skipped, true);
  const plan = {kind: 'structure_plan', turn_id: 'plan', structure_plan: {recommended: {label: '推荐', section_order: [], experience_plan: []}, alternatives: []}, options: []};
  context.window.fixture({guidance: plan}, sender);
  assert.equal(find('intake-card'), undefined); assert.equal(find('ask-card'), undefined);
  for (const [start, end, expected] of [
    ['2026-08', '至今', '2026-08 至今'], ['2026-07', '2026-09', '2026-07 至 2026-09'],
    ['2026-08', '', '2026-08'], ['', '2026-09', '2026-09'], ['', '至今', '至今'], ['', '', ''],
  ]) {
    const guidance = {...experience, turn_id: `date-${start}-${end}`, items: [{...experience.items[0], start, end}]};
    context.window.fixture({guidance}, sender);
    await submit();
    const latest = sent.at(-1);
    assert.equal(latest.text, '经历清单：\n「胡话简历」；类型：项目' + (expected ? '；时间：' + expected : ''));
    assert.equal(latest.payload.intake.items[0].start, start);
    assert.equal(latest.payload.intake.items[0].end, end);
  }
  context.window.fixture({guidance: {...basics, turn_id: 'partial', missing_fields: ['major', 'degree', 'graduation', 'location', 'availability', 'phone', 'email']}}, sender);
  assert.equal(find('intake-existing-fields').hidden, true);
  assert.match(all(find('intake-profile-summary')).map(row => row.textContent || '').join(''), /张三.*测试大学/);
  await click(find('intake-edit-existing'));
  assert.equal(find('intake-existing-fields').hidden, false);
  fill('phone', '13900001234'); fill('email', 'returning@example.test');
  await submit();
  assert.equal(sent.at(-1).payload.intake.values.phone, '13900001234');
  assert.match(sent.at(-1).text, /手机：13900001234.*邮箱：returning@example.test/);
  const catalog = {kind: 'intake_experiences', title: '从档案选经历', turn_id: 'catalog', items: [], selected_profile_ids: ['p1'],
    profile_items: [{id: 'p1', name: '检索工具', category: 'project', start: '2026-01', end: '至今', summary: '支持引用核对'},
      {id: 'p2', name: '校园活动', category: 'campus', summary: '协助登记'}]};
  context.window.fixture({guidance: catalog}, sender);
  assert.equal(finds('intake-row').length, 0);
  assert.equal(fields('name').length, 0);
  assert.equal(fields('profile_item_ids')[0].checked, true);
  const check = fields('profile_item_ids')[1]; check.checked = true; check.handlers.change();
  await submit();
  assert.deepEqual(sent.at(-1).payload.intake.profile_item_ids, ['p1', 'p2']);
  assert.deepEqual(sent.at(-1).payload.intake.items, []);
  assert.match(sent.at(-1).text, /检索工具、校园活动/);
  context.window.fixture({guidance: {...catalog, turn_id: 'catalog-empty', selected_profile_ids: []}}, sender);
  const before = sent.length; await submit(); assert.equal(sent.length, before);
  assert.equal(find('intake-selection-error').hidden, false);
  await click(find('intake-add'));
  assert.equal(finds('intake-row').length, 1);
  assert.equal(find('intake-row-remove').hidden, false);
  await click(find('intake-row-remove'));
  assert.equal(finds('intake-row').length, 0);
  const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
  assert.match(html, /intake = null/); assert.match(html, /\.\.\.\(intake \? \{intake\} : \{\}\)/);
  console.log('intake DOM checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
