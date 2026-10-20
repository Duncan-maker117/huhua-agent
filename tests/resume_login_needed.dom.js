// A linked ?session= draft that cannot be read must prompt login, not show the sample resume.
const assert = require('node:assert/strict');
const {fixture, tick} = require('./resume_embedded.dom.js');
const templates = [{id: 't001-jianyue', name: '简约'}];

async function load({linked, account}) {
  const f = fixture('resume.html');
  f.context.location.search = linked ? '?session=abc&template=t001-jianyue' : '';
  const opened = [], fetched = [];
  f.context.location.reload = () => { f.reloaded = true; };
  f.window.HuhuaAccount = {ready: Promise.resolve({require_account: true}), claimPending: () => false,
    rememberedSession: () => null, rememberSession() {}, guest: () => account === 'guest', open: reason => opened.push(reason)};
  f.context.fetch = async url => {
    fetched.push(url);
    if (url === '/api/resume/templates') return {ok: true, json: async () => ({templates})};
    if (url === '/api/resume/sample') return {ok: true, json: async () => ({basic_info: {name: '示例'}, sections: []})};
    return {ok: false, status: 401, json: async () => ({})};
  };
  f.run('resume-editor.js');
  for (let i = 0; i < 6; i++) await tick();
  return {f, opened, fetched};
}

(async () => {
  const linked = await load({linked: true});
  const text = node => [node.textContent, ...(node.children || []).map(text)].join('|');
  const body = text(linked.f.ids.get('form-editor'));
  assert.ok(body.includes('这份简历需要登录对应账号后查看'), body);
  assert.ok(!linked.fetched.includes('/api/resume/sample'), 'linked draft must not fall back to the sample');
  const login = linked.f.ids.get('form-editor').children[0].children.find(n => n.tagName === 'BUTTON');
  await login.click();
  assert.equal(linked.opened.length, 1);
  linked.f.fire('huhua-account-changed', {});
  assert.equal(linked.f.reloaded, true, 'login returns to the same URL');

  const pub = await load({linked: false});
  assert.ok(!text(pub.f.ids.get('form-editor')).includes('需要登录对应账号'));
  console.log('resume login-needed DOM checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
