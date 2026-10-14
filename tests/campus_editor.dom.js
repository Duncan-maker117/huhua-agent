// Campus fields use the existing editor paths, without changing preview behavior.
const assert = require('node:assert/strict');
const {fixture} = require('./resume_embedded.dom.js');
const f = fixture('resume.html');
f.run('resume-editor.js', code => code.replace('  initialise();',
  '  window.campusFixture = {state, normaliseData, buildContributionContent, builtinSections, itemGroups};'));
const api = f.window.campusFixture;
assert.ok(api.builtinSections.some(section => section.kind === 'campus' && section.title === '校园经历'));
assert.ok(api.itemGroups.includes('campus'));
assert.equal(api.normaliseData({}).campus.length, 0);
api.state.data = api.normaliseData({campus: [{name: '观影协会', role: '宣传部副部长', bullets: ['制作海报']}]});
const body = f.document.createElement('div');
api.buildContributionContent(body, 'campus');
const descendants = node => [node, ...node.children.flatMap(descendants)];
const inputs = descendants(body).filter(node => node.dataset.inputPath);
for (const field of ['name', 'role', 'start_date', 'end_date', 'bullets/0']) {
  assert.ok(inputs.some(input => input.dataset.inputPath === '/campus/0/' + field), field);
}
const role = inputs.find(input => input.dataset.inputPath === '/campus/0/role');
role.value = '宣传部干事';
for (const handler of role.handlers.input) handler();
assert.equal(api.state.data.campus[0].role, '宣传部干事');
assert.equal(api.state.data.open_source.length, 0);
assert.equal(api.state.data.projects.length, 0);
console.log('campus editor DOM checks passed');
