const assert = require('node:assert/strict');
const {fixture, tick} = require('./resume_embedded.dom.js');
const f = fixture('index.html');
f.context.clearInterval = () => {}; f.context.setInterval = () => 1;
f.context.location.search = '?session_id=synthetic-profile';
const facts = [
  ['work','虚构实习','description','参与接口测试'],
  ['project','虚构项目','description','开发本地原型'],
  ['skill','语言','skill','Python'],
  ['education','虚构大学','major','计算机'],
  ['basic','基础信息','name','虚构同学'],
  ['project','虚构项目','tool','SQLite'],
  ['open_source','虚构仓库','description','补充单元测试'],
  ['awards','虚构竞赛','level','参与奖'],
  ['project','虚构项目','role','参与者'],
].map(([category,subject,field,value], i) => ({id:'f'+i, revision:1, category,subject,field,value,sources:[]}));
let profile = {revision:1, facts, conflicts:[{id:'c1', subject:'虚构项目', field:'role', current_value:'参与者', proposed_value:'负责人', expected_revision:1}],
  updates:[{fact_id:'f8', revision:2, subject:'虚构项目',field:'status',previous_value:'原型',value:'内测'}],
  archive_status:{failed:1,tasks:[{id:'task1',status:'failed',message:'这次整理超时，已保存的聊天仍在，可以稍后重试。',retryable:true}]}};
const calls = [];
f.context.fetch = async (url, options) => {
  calls.push({url, options});
  if (url === '/api/account/me') return {ok:true,json:async () => ({authenticated:true,login_available:true,account:{email:'fiction@example.test'}})};
  if (url.endsWith('/resolve')) profile = {...profile, conflicts:[]};
  if (url.endsWith('/undo-update')) profile = {...profile, updates:[]};
  if (url.endsWith('/retry')) profile = {...profile, archive_status:{pending:1,tasks:[]}};
  return {ok:true,json:async () => url === '/api/profile' ? structuredClone(profile) : {}};
};
function descendants(element) {return [element,...element.children.flatMap(descendants)];}
const all = () => descendants(f.ids.get('profile-content'));
const buttons = text => all().filter(n => n.tagName === 'BUTTON' && n.textContent === text);
const cls = (name, nodes = all()) => nodes.filter(n => n.className.split(' ').includes(name));
(async () => {
  f.run('account-profile.js'); await tick();
  await f.window.HuhuaAccount.open(); await tick();
  assert.ok(all().some(n => n.textContent === '已有信息'));
  assert.equal(cls('conflict').length, 0, 'confirmation list is collapsed on open');
  assert.equal(cls('profile-confirm-badge')[0].textContent, '1');
  assert.deepEqual(cls('profile-entry').map(n => n.dataset.category), ['basic','education','project','work','open_source','awards','skill']);
  const project = cls('profile-entry').find(n => n.dataset.category === 'project');
  assert.equal(cls('profile-fact-row',descendants(project)).length, 3, 'one card combines project fields');
  assert.equal(descendants(project).filter(n => n.textContent === '更正').length, 3);
  assert.equal(descendants(project).filter(n => n.textContent === '删除').length, 3);
  assert.equal(descendants(project).filter(n => n.textContent === '查看来源与时间').length, 3);
  const uses = descendants(project).filter(n => n.textContent === '用于当前简历');
  assert.equal(uses.length, 1);
  await uses[0].click(); await tick();
  const imported = calls.find(n => n.url.endsWith('/profile-facts'));
  assert.deepEqual(JSON.parse(imported.options.body).fact_ids, ['f1','f5','f8']);
  assert.ok(imported.url.includes('synthetic-profile'));
  await buttons('更正')[0].click(); assert.equal(all().filter(n => n.tagName === 'TEXTAREA').length, 1);
  await buttons('取消')[0].click(); assert.equal(all().filter(n => n.tagName === 'TEXTAREA').length, 0);
  await buttons('信息确认')[0].click();
  assert.equal(cls('conflict').length, 1); assert.equal(cls('profile-entry').length, 0);
  const before = calls.length;
  await buttons('我来更正')[0].click(); assert.equal(all().filter(n => n.tagName === 'TEXTAREA').length, 1);
  await buttons('取消')[0].click();
  assert.equal(calls.length, before, 'cancel without input performs no request');
  assert.equal(all().filter(n => n.tagName === 'TEXTAREA').length, 0);
  assert.equal(buttons('采用新说法').length, 1);
  await buttons('保留原记录')[0].click(); await tick();
  assert.equal(cls('profile-confirm-badge').length, 0);
  assert.ok(all().some(n => n.textContent === '没有待确认的信息。'));
  await f.window.HuhuaAccount.open(); await tick();
  assert.ok(all().some(n => n.textContent === '已有信息'), 'reopening defaults to existing information');
  assert.ok(all().some(n => n.textContent.includes('这次整理超时')));
  await buttons('重试整理')[0].click(); await tick();
  assert.ok(calls.some(n => n.url === '/api/profile/tasks/task1/retry'));
  await buttons('撤销更新')[0].click(); await tick();
  const undone = calls.find(n => n.url.endsWith('/undo-update'));
  assert.deepEqual(JSON.parse(undone.options.body), {expected_revision:2});
  assert.equal(buttons('撤销更新').length, 0);
  console.log('account profile DOM checks passed');
})().catch(e => {console.error(e); process.exitCode = 1;});
