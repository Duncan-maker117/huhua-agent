// Run the real change card against a small offline DOM. All content is fictional.
const assert = require('node:assert/strict');
const {fixture} = require('./resume_embedded.dom.js');
const f = fixture('index.html');
f.run('change-card.js');
const create = f.window.HuhuaChangeCard.create;
const before = {item_id: 'p', name: '合成项目', polished_bullets: ['开发查询接口']};
const entry = after => ({section: 'projects', item_id: 'p', before, after});
for (const after of [structuredClone(before), {...before, source: 'profile', hidden: false},
  {...before, polished_bullets: ['开发查询接口\u200b']}]) {
  assert.equal(create({diff: [entry(after)], change_summary: ['✅ 已更新稿件']}), null);
}
const card = create({diff: [entry({...before, tech_stack: ['Python']})], change_summary: ['修改技术栈']});
const all = node => [node, ...node.children.flatMap(all)];
assert.equal(all(card).filter(node => node.className === 'change-bullet change-bullet-removed').length, 0);
assert.equal(all(card).filter(node => node.className === 'change-bullet change-bullet-add').length, 0);
assert.ok(all(card).some(node => node.textContent.includes('技术栈：')));
const real = create({diff: [entry({...before, polished_bullets: ['开发缓存查询接口']})]});
assert.equal(all(real).filter(node => node.className === 'change-bullet change-bullet-removed').length, 1);
assert.equal(all(real).filter(node => node.className === 'change-bullet change-bullet-add').length, 1);
assert.ok(create({diff: [], change_summary: ['⚠ 需要补充资料']}));
console.log('quality change card: 8 checks passed');
