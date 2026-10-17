// 加载 index.html 引用的实际控制器，验证无旧按钮时初始化和岗位卡结构。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.handlers = {}; this.attributes = {}; this.textContent = ''; this.dataset = {}; this.hidden = false; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
}
const all = node => [node, ...node.children.flatMap(all)];
const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element('div')]));
const document = {createElement: tag => new Element(tag), getElementById: id => ids.get(id) || null};
const context = {window: {}, document, URL, Set, Map, JSON};
for (const name of ['web-research.js', 'resume-workspace.js']) {
  assert.ok(html.includes('/static/' + name));
  let source = fs.readFileSync(path.join(__dirname, '../web', name), 'utf8');
  if (name === 'resume-workspace.js') source = source.replace('window.HuhuaWorkspace =',
    "window.renderIntelFixture = info => {workspace = {jd: {info}}; callbacks = {}; renderJd();}; window.HuhuaWorkspace =");
  vm.runInNewContext(source, context);
}
for (const id of ['web-read-toggle', 'web-search-toggle', 'web-read-panel', 'web-search-panel', 'web-tool-actions', 'web-research-panel']) assert.equal(ids.has(id), false);
assert.ok(ids.has('file-input'));
let input = '这个岗位 https://example.org/job';
const web = context.window.HuhuaWebResearch;
web.init({input: () => input}); web.setStreaming(true); web.setStreaming(false); web.toolStatus({message: '读取成功'});
assert.ok(!html.includes('web_tool:'));
assert.ok(!html.includes('HuhuaWebResearch?.infer'));
assert.equal(web.safeUrl('javascript:alert(1)'), null);
const profile = {source: 'market_sample', direction: 'AI 产品经理', sample_count: 6, fetched_at: '2026-10-17T00:00:00Z',
  skills: [{text: 'RAG', count: 4}], responsibilities: [{text: '调研', count: 6}], bonuses: [],
  sources: [{url: 'https://example.org/1', job_title: '产品实习', company: '纸舟'}]};
const info = {job_card: {job_title: '<img onerror=alert(1)>', company: '纸舟', location: '深圳', salary: '200元/天', fetched_at: '2026-10-17',
  requirements: [{text: '熟悉 RAG'}], raw_text: '<script>bad()</script>', url: 'https://example.org/1'}, role_profile: profile,
  company: {name: '纸舟', source: 'company_search', industry: {text: '软件', url: 'https://example.org/about'},
    description: {text: '开发软件', url: 'javascript:bad()'}, official_site: {text: 'https://example.org', url: 'https://example.org/about'}}};
context.window.renderIntelFixture(info);
const panel = ids.get('workspace-panel-jd');
const finds = cls => all(panel).filter(el => el.className?.split(' ').includes(cls));
assert.equal(finds('intel-card').length, 3);
assert.equal(finds('intel-title')[0].textContent, '<img onerror=alert(1)> · 纸舟');
assert.equal(finds('intel-raw')[0].children[0].textContent, '展开原文');
assert.equal(finds('intel-group').length, 3);
assert.deepEqual(finds('intel-group').map(el => el.children[0].textContent), ['高频职责', '高频技能', '加分项']);
assert.ok(finds('intel-count').some(el => el.textContent === '4/6'));
assert.equal(finds('intel-sources').length, 1);
for (const a of finds('intel-source')) { assert.equal(a.target, '_blank'); assert.equal(a.rel, 'noopener'); assert.match(a.href, /^https:/); }
assert.ok(!all(panel).some(el => el.tagName === 'SCRIPT' || el.tagName === 'IMG'));
// 切换会话时旧卡会移除，而不是继续复用上次公司的资料。
context.window.renderIntelFixture({role_profile: profile});
assert.equal(finds('intel-company').length, 0); assert.equal(finds('intel-job').length, 0);
context.window.renderIntelFixture({role_profile: {source: 'direction', status: 'pending', candidate_count: 7}});
assert.equal(finds('intel-profile').length, 1);
assert.equal(finds('intel-profile')[0].tagName, 'ARTICLE');
assert.equal(finds('intel-profile')[0].dataset.state, 'pending');
assert.equal(finds('intel-title')[0].textContent, '正在整理 7 条真实岗位…');
assert.equal(finds('intel-group').length, 0);
context.window.renderIntelFixture({role_profile: {source: 'direction', status: 'failed', message: '暂未完成，请继续聊经历。'}});
assert.equal(finds('intel-profile')[0].dataset.state, 'failed');
assert.equal(finds('intel-meta')[0].textContent, '暂未完成，请继续聊经历。');
context.window.renderIntelFixture({role_profile: profile});
assert.equal(finds('intel-profile')[0].dataset.state, 'ready');
for (const n of [3, 4]) {
  context.window.renderIntelFixture({role_profile: {...profile, sample_count: n, low_sample: true,
    frequency_basis: 'company', company_count: 2, skills: [{text: 'RAG', count: 1, total: 2}],
    weighting_note: '频次按公司统计，同一公司对同一项最多计 1 次；公司未知时按域名归组。'}});
  assert.equal(finds('intel-profile')[0].dataset.state, 'ready');
  assert.ok(finds('intel-title')[0].textContent.includes(`仅基于 ${n} 条岗位`));
  assert.ok(finds('intel-meta').some(el => el.textContent.includes('同一公司对同一项最多计 1 次')));
  assert.ok(finds('intel-count').some(el => el.textContent === '1/2'));
  assert.ok(!finds('intel-count').some(el => el.textContent === `1/${n}`));
}
context.window.renderIntelFixture({role_profile: {...profile, low_sample: false}});
assert.ok(!finds('intel-title')[0].textContent.includes('仅基于'));
context.window.renderIntelFixture({company: {name: '美团', source: 'company_search', description: {text: '本地生活服务', url: 'https://baike.baidu.com/item/x', source_type: '百科'}}});
assert.ok(finds('intel-source').some(el => el.textContent.includes('百科')));
console.log('intel DOM checks passed');
