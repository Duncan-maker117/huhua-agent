// Focused static + pure-input regression: no browser, network, model or project data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const checks = [];
const check = (name, fn) => { fn(); checks.push(name); };
const toolsCode = read('web/web-research.js'), workspace = read('web/resume-workspace.js'), page = read('web/index.html');
const context = {window:{},document:{},URL};
vm.runInNewContext(toolsCode, context);
const tools = context.window.HuhuaWebResearch;
check('pure HTTPS URL becomes explicit read-url payload', () => {
  const value = tools.infer('https://careers.example.invalid/jobs/123?lang=zh');
  assert.equal(value.action, 'read_url'); assert.equal(value.url, 'https://careers.example.invalid/jobs/123?lang=zh');
});
check('HTTP supported', () => assert.equal(tools.infer('http://careers.example.invalid/job').action, 'read_url'));
check('GitHub links use public reference mode with and without scheme', () => {
  for (const url of ['https://github.com/example/tool', 'github.com/example']) {
    assert.equal(tools.infer(url).action, 'read_public_url');
  }
  assert.equal(tools.infer('github.com/example', 1), null);
  assert.equal(tools.infer('https://github.com.example.org/jobs/123').action, 'read_url');
});
check('surrounding whitespace accepted', () => assert.equal(tools.infer('  https://example.invalid/job  ').url, 'https://example.invalid/job'));
check('mixed personal material is never automatically read', () => assert.equal(tools.infer('我的项目用了 Python，参考 https://example.invalid/job'), null));
check('two links never become one tool action', () => assert.equal(tools.infer('https://a.example.invalid https://b.example.invalid'), null));
check('attachments prevent URL auto-reading', () => assert.equal(tools.infer('https://example.invalid/job', 1), null));
check('unsafe and credential-bearing protocols rejected', () => {
  for (const url of ['javascript:alert(1)','data:text/html,hello','file:///tmp/a','//example.invalid','https://user:pass@example.invalid','https://']) assert.equal(tools.safeUrl(url), null, url);
});
check('keyword fields bounded and separate', () => {
  assert.match(page, /id="web-search-company" maxlength="80"/); assert.match(page, /id="web-search-role" maxlength="80"/);
  assert.match(toolsCode, /tool = \{action, company, role\}/); assert.match(toolsCode, /if \(!company && !role\)/);
});
check('explicit tools preserve existing composer and attachment draft', () => {
  assert.match(toolsCode, /webTool:tool, keepDraft:true/); assert.match(page, /quickReply \|\| webTool \? \[\] : \[\.\.\.attachments\]/);
  assert.match(page, /if \(!quickReply && !keepDraft\) clearAttachments\(\)/);
});
check('tool metadata is handled before content and returns early', () => {
  const status = page.indexOf("parsed.type === 'tool_status'"); const sources = page.indexOf("parsed.type === 'sources'"); const content = page.indexOf("typeof parsed.content === 'string'", sources);
  assert.ok(status > 0 && sources > status && content > sources);
  assert.match(page.slice(sources, content), /setWebSources\(parsed.sources, submittedSession\); return;/);
});
check('failed requests restore input before or after tool status without replacing later draft', () => {
  assert.match(page, /if \(!completed\) \{\s*if \(!quickReply && !keepDraft && !inputEl.value.trim\(\)\) \{ inputEl.value = text;/);
});
check('source metadata rendered with textContent and safe external links', () => {
  assert.match(workspace, /el.textContent = plain\(text\)/); assert.match(workspace, /link.rel = 'noopener noreferrer'/);
  assert.match(workspace, /\['http:', 'https:'\].includes\(url.protocol\)/);
  assert.match(workspace, /获取时间：/); assert.match(workspace, /页面发布日期：/);
});
check('source cache scoped to current conversation and cleared on identity reset', () => {
  assert.match(workspace, /session !== callbacks.session\?\.\(\)/);
  assert.match(workspace, /webSourceSession === callbacks.session\?\.\(\)/);
  assert.match(workspace, /huhua-account-reset', \(\) => \{ webSourceCache.clear\(\); \}/);
});
const sourceContext = {window:{},document:{},URL};
vm.runInNewContext(workspace.replace('  window.HuhuaWorkspace =', `  window.__sourceTest = {
  accept: acceptWebSources, read: currentWebSources, normalize: normalizeSources, scope: sourceScope,
  select(session) { callbacks = {session: () => session}; webSourceSession = session; },
  clear() { webSourceCache.clear(); }
};
  window.HuhuaWorkspace =`), sourceContext);
const groups = sourceContext.window.__sourceTest;
const sourceA = {title:'A',url:'https://a.example.invalid/job'}, sourceB = {title:'B',url:'https://b.example.invalid/job'};
check('new SSE source group replaces older group without reordering', () => {
  groups.select('turn-a'); groups.accept([sourceA], 'turn-a'); groups.accept([sourceB,sourceA], 'turn-a', {pending:true});
  assert.equal(groups.read().length, 2); assert.equal(groups.read()[0].title, 'B'); assert.equal(groups.read()[1].title, 'A');
});
check('refresh with old metadata cannot replace pending source group', () => {
  assert.equal(groups.accept([sourceA], 'turn-a'), false); assert.equal(groups.read()[0].title, 'B');
  assert.equal(groups.accept([], 'turn-a'), false); assert.equal(groups.read().length, 2);
});
check('successful source commit unlocks subsequent authoritative metadata', () => {
  assert.equal(groups.accept([sourceB,sourceA], 'turn-a', {commit:true}), true);
  assert.equal(groups.accept([sourceA], 'turn-a'), true); assert.equal(groups.read().length, 1);
});
check('explicit committed empty source group clears prior cards', () => {
  groups.accept([sourceB], 'turn-a', {pending:true}); groups.accept([], 'turn-a', {commit:true});
  assert.equal(groups.read().length, 0);
});
check('another session cannot inherit source group numbering', () => {
  groups.accept([sourceA], 'turn-a'); groups.select('turn-b'); assert.equal(groups.read().length, 0);
  groups.accept([sourceB], 'turn-b'); assert.equal(groups.read()[0].title, 'B'); groups.select('turn-a'); assert.equal(groups.read()[0].title, 'A');
});
check('display numbers follow server sequence and commit only after successful stream', () => {
  assert.match(workspace, /sources.entries\(\)/); assert.match(workspace, /numberedTitle = `\[\$\{index \+ 1\}\]/);
  assert.match(page, /if \(completed\) window.HuhuaWorkspace\?\.commitWebSources\(lastWorkspaceMeta, submittedSession\)/);
  assert.match(workspace, /hasOwnProperty.call\(value, 'web_sources'\)/);
});
const noticeNodes = {'web-tool-usage-notice': {textContent:'',hidden:true}, 'web-direct-link-notice': {hidden:true}};
const noticeContext = {window:{},document:{getElementById:id => noticeNodes[id]},URL};
vm.runInNewContext(toolsCode.replace('  window.HuhuaWebResearch =', `  window.__usageTest = {
  update: syncUsageNotice,
  select(action, available, input = '', running = false) { active = action; capabilities = {read_url:available, search:available}; callbacks = {input: () => input}; busy = running; }
};
  window.HuhuaWebResearch =`), noticeContext);
const usage = noticeContext.window.__usageTest;
check('read entry explains JD replacement and attempts before execution', () => {
  usage.select('read_url', true); usage.update();
  assert.equal(noticeNodes['web-tool-usage-notice'].hidden, false);
  assert.match(noticeNodes['web-tool-usage-notice'].textContent, /替换当前目标 JD/);
  assert.match(noticeNodes['web-tool-usage-notice'].textContent, /开始执行后，即使失败也计入尝试次数/);
});
check('search scope is explicitly limited to snippets and preserves JD', () => {
  usage.select('search', true); usage.update();
  assert.match(noticeNodes['web-tool-usage-notice'].textContent, /仅基于搜索结果摘要/);
  assert.match(noticeNodes['web-tool-usage-notice'].textContent, /不替换当前目标 JD/);
});
check('pure link input shows replacement notice without opening tool panel', () => {
  usage.select('', true, 'https://example.invalid/job'); usage.update();
  assert.equal(noticeNodes['web-direct-link-notice'].hidden, false);
  usage.select('', true, '本人项目参考 https://example.invalid/job'); usage.update();
  assert.equal(noticeNodes['web-direct-link-notice'].hidden, true);
});
check('GitHub direct-link notice correctly preserves JD', () => {
  usage.select('', true, 'github.com/example'); usage.update();
  assert.equal(noticeNodes['web-direct-link-notice'].hidden, false);
  assert.match(noticeNodes['web-direct-link-notice'].textContent, /不会替换目标 JD/);
});
check('unavailable tool does not imply an attempt was consumed', () => {
  usage.select('search', false); usage.update(); assert.equal(noticeNodes['web-tool-usage-notice'].hidden, true);
});
check('source normalization preserves only strict truncation booleans', () => {
  const normalized = groups.normalize([{kind:'job_page',content_truncated:true}, {kind:'job_page',content_truncated:false}, {kind:'job_page',content_truncated:'true'}, {kind:'job_page',content_truncated:1}]);
  assert.equal(normalized[0].content_truncated, true); assert.equal(normalized[1].content_truncated, false);
  assert.equal(Object.hasOwn(normalized[2], 'content_truncated'), false); assert.equal(Object.hasOwn(normalized[3], 'content_truncated'), false);
});
check('source scope separates snippet analysis from extracted-body truncation', () => {
  assert.match(groups.scope({kind:'search_result',content_truncated:true}), /仅基于搜索返回的摘要/);
  assert.doesNotMatch(groups.scope({kind:'search_result',content_truncated:true}), /12,000/);
  assert.match(groups.scope({kind:'job_page',content_truncated:true}), /仅分析前 12,000/);
  assert.doesNotMatch(groups.scope({kind:'job_page',content_truncated:false}), /仅分析前 12,000/);
  assert.match(groups.scope({kind:'job_page',content_truncated:false}), /不代表已完整读取/);
});
check('card excerpt limit is presented separately from model input scope', () => {
  assert.match(workspace, /const excerpt = plain\(source.content\).slice\(0, 1800\)/);
  assert.match(workspace, /查看内容摘录（前 1,800 字）/);
  assert.match(workspace, /不改变本轮用于分析的已获取资料范围/);
  assert.match(workspace, /不对应更早回复/);
});
check('public page scope metadata is bounded without claiming repository completeness', () => {
  const normalized = groups.normalize([{kind:'public_page',read_scope:'github_profile_and_public_repositories',request_count:2}, {read_scope:'unexpected',request_count:true}]);
  assert.equal(normalized[0].kind, 'public_page'); assert.equal(normalized[0].request_count, 2);
  assert.equal(normalized[0].read_scope, 'github_profile_and_public_repositories');
  assert.equal(Object.hasOwn(normalized[1], 'read_scope'), false); assert.equal(Object.hasOwn(normalized[1], 'request_count'), false);
  assert.match(groups.scope(normalized[0]), /最多 5 条/);
  assert.match(groups.scope(normalized[0]), /不代表完整仓库列表/);
  assert.match(groups.scope({kind:'public_page',read_scope:'github_repository_metadata'}), /不代表已逐文件审阅代码/);
  assert.doesNotMatch(groups.scope({kind:'public_page',read_scope:'public_page_text'}), /搜索返回的摘要/);
});
// Tiny in-memory DOM covers panel text and per-turn option visibility. It does
// not exercise browser layout, API calls or actual event dispatch.
class DisplayNode {
  constructor(tag) { this.tagName = tag; this.children = []; this._text = ''; this.hidden = false; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  get childElementCount() { return this.children.length; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this._text = ''; }
  setAttribute() {}
  addEventListener() {}
}
const displayNodes = {'guidance-dock':new DisplayNode('div'), 'workspace-panel-experiences':new DisplayNode('section')};
const displayContext = {window:{},document:{getElementById:id => displayNodes[id],createElement:tag => new DisplayNode(tag)},URL};
vm.runInNewContext(workspace.replace('  window.HuhuaWorkspace =', `  window.__displayTest = {
  load(value) { workspace = value; callbacks = {session: () => 'display-fixture'}; },
  guidance: renderGuidance, experiences: renderExperiences,
  markAnswered() { answeredGuidance.add(guidanceKey()); }
};
  window.HuhuaWorkspace =`), displayContext);
const display = displayContext.window.__displayTest;
check('open questions render direct-input guidance without canned buttons', () => {
  display.load({guidance:{turn_id:'one',question:'具体负责哪一步？',options:[],allow_free_text:true}}); display.guidance();
  const dock = displayNodes['guidance-dock'];
  assert.equal(dock.hidden, false); assert.match(dock.textContent, /这题适合直接描述/);
  assert.equal(dock.children.some(child => child.className === 'guidance-options'), false);
});
check('answer visibility resets on a new turn but stays hidden on refresh', () => {
  const guidance = {turn_id:'one',kind:'next_action',question:'先生成草稿，还是继续补充？',options:[{label:'先生成草稿',value:'请生成草稿。'},{label:'继续补充',value:'我想继续补充。'}]};
  display.load({guidance}); display.guidance();
  assert.match(displayNodes['guidance-dock'].textContent, /点击即发送所选下一步/);
  display.markAnswered(); display.guidance(); assert.equal(displayNodes['guidance-dock'].hidden, true);
  display.load({guidance:{...guidance,turn_id:'two'}}); display.guidance();
  assert.equal(displayNodes['guidance-dock'].hidden, false);
  assert.equal(displayNodes['guidance-dock'].children.find(child => child.className === 'guidance-options').childElementCount, 2);
});
check('imported standalone skills awards and conflict notes remain visible as plain text', () => {
  display.load({experiences:{items:[],skills:['Python'],certificates:['测试奖项'],verification_notes:['日期待核对 <img src=x>']}}); display.experiences();
  const text = displayNodes['workspace-panel-experiences'].textContent;
  for (const value of ['已提供的技能','Python','已提供的奖项与证书','测试奖项','资料待核对','日期待核对 <img src=x>']) assert.ok(text.includes(value), value);
});
check('new JS and homepage inline scripts parse', () => {
  new vm.Script(toolsCode); new vm.Script(workspace);
  for (const match of page.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) if (match[1].trim()) new vm.Script(match[1]);
});
console.log(JSON.stringify({scope:'Static syntax and pure-input checks only; no runtime browser claim.',passed:checks.length,checks}, null, 2));
