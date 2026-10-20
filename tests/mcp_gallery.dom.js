// 真实编辑器启动：查询参数优先于本地偏好，非法参数不进入渲染 URL。
const assert = require('node:assert/strict');
const {fixture, tick} = require('./resume_embedded.dom.js');
const templates = ['t001-jianyue', 't1002-jianyue'].map(id => ({id, name: id}));
(async () => {
  for (const [query, expected] of [
    ['?template=t1002-jianyue', 't1002-jianyue'],
    ['?template=%3Cscript%3E', 't001-jianyue'],
    ['?template=../../secret', 't001-jianyue'], ['', 't001-jianyue'],
  ]) {
    const f = fixture('resume.html');
    const renders = [];
    f.context.location.search = query;
    f.context.localStorage.getItem = () => 't001-jianyue';
    f.context.localStorage.setItem = () => {};
    f.context.fetch = async url => {
      if (url === '/api/resume/templates') return {ok: true, json: async () => ({templates})};
      if (url === '/api/resume/sample') return {ok: true, json: async () => ({basic_info: {}, sections: []})};
      renders.push(url);
      return {ok: true, text: async () => '<html><body>测试</body></html>'};
    };
    f.run('resume-editor.js');
    for (let i = 0; i < 6; i++) await tick();
    const rows = f.ids.get('template-list').children;
    assert.equal(rows.length, 2);
    assert.equal(rows.filter(row => row.attributes['aria-pressed'] === 'true').length, 1);
    const selected = rows.find(row => row.dataset.templateId === expected);
    assert.equal(selected.attributes['aria-pressed'], 'true');
    assert.equal(selected.scrolled, true);
    assert.equal(f.ids.get('current-tpl').textContent, expected);
    assert.equal(renders.length, 1);
    assert.ok(renders[0].includes('/render/' + expected + '?'));
  }
  console.log('MCP gallery DOM checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
