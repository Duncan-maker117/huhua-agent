// Minimal DOM fixture for the actual renderer and existing send/deduplication path.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.handlers = {}; this.attributes = {}; this.textContent = ''; }
  append(...rows) { this.children.push(...rows); }
  replaceChildren(...rows) { this.children = rows; }
  addEventListener(event, handler) { this.handlers[event] = handler; }
  setAttribute(key, value) { this.attributes[key] = value; }
  get childElementCount() { return this.children.length; }
}
const dock = new Element('div');
const context = {window: {}, document: {createElement: tag => new Element(tag), getElementById: () => dock}, Set, Map, JSON};
const code = fs.readFileSync(process.argv[2], 'utf8').replace('window.HuhuaWorkspace =', `window.fixture = (data, sender) => {
  workspace = data; callbacks = {session: () => 'synthetic', sendChoice: sender}; renderGuidance();
}; window.HuhuaWorkspace =`);
vm.runInNewContext(code, context);
const plan = {label: '主线叙事型', positioning: '修复记忆污染', thesis: '跨语言记忆处理',
  section_order: ['open_source', 'awards', 'projects'], experience_plan: [
    {item_id: 'o1', name: '合成仓库', treatment: 'lead', reason: '对应记忆处理'},
    {item_id: 'p1', name: '合成项目', treatment: 'backup', reason: '本版不写'}]};
const guidance = {kind: 'structure_plan', turn_id: 'synthetic-plan', structure_plan: {recommended: plan, alternatives: [
  {label: '均衡型', positioning: '', thesis: '实践记录', section_order: ['projects', 'open_source'], experience_plan: []}]},
  options: [{label: '按推荐写', value: '按推荐写'}, {label: '用备选：均衡型', value: '用备选：均衡型'}]};
function all(node) { return [node, ...node.children.flatMap(all)]; }
(async () => {
  const sent = [];
  context.window.fixture({guidance, tailor: {questions: [{q: '不该抢占方案卡'}]}}, async value => {sent.push(value); return true;});
  const nodes = all(dock), text = nodes.map(row => row.textContent).join('\n');
  assert.ok(text.includes('定位：修复记忆污染'));
  assert.ok(text.includes('主线：跨语言记忆处理'));
  assert.ok(text.includes('开源贡献 → 竞赛荣誉 → 项目经历'));
  assert.ok(text.includes('合成仓库 · 写（重点）：对应记忆处理'));
  assert.ok(text.includes('合成项目 · 不写：本版不写'));
  assert.ok(text.includes('也可以直接说想怎么改'));
  assert.equal(nodes.filter(row => row.tagName === 'details').length, 1);
  assert.ok(text.includes('展开看差异'));
  const recommended = nodes.find(row => row.tagName === 'button' && row.textContent === '按推荐写');
  await recommended.handlers.click();
  await recommended.handlers.click();
  assert.deepEqual(sent, ['按推荐写']);
  context.window.fixture({guidance: {...guidance, turn_id: 'new-card'}}, async value => {sent.push(value); return true;});
  await all(dock).find(row => row.tagName === 'button' && row.textContent.startsWith('用备选')).handlers.click();
  assert.deepEqual(sent, ['按推荐写', '用备选：均衡型']);
  console.log('structure plan DOM checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
