// Self-contained, synthetic fixture. No server, user database or model is used.
// playwright-cli -s=huhua-embedded run-code --filename=tests/resume_embedded.browser.js
async (page) => {
  const origin = 'http://huhua.fixture';
  const checks = [], errors = [], reads = [], exports = [];
  const check = (value, label) => { if (!value) throw new Error(label); checks.push(label); };
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  let current = {has_data: false, revision: 'r0', can_save: true, stage: 'COLLECTING', data: null};
  let session = 'embedded-a', historyReads = 0, failSave = false, failExport = false, releaseExport = null;
  const draft = name => ({basic_info: {name}, projects: [{name: '虚构项目', polished_bullets: ['完成本地原型验证']}], sections: [{id: 'projects', kind: 'projects', title: '项目经历'}]});
  const workspace = () => ({jd: {}, experiences: {items: []}, resume: {has_data: current.has_data, version: current.revision}, review: {items: []}, focus: 'resume'});
  await page.route(origin + '/**', async route => {
    const request = route.request(), rawUrl = request.url(), path = '/' + rawUrl.split('/').slice(3).join('/').split('?')[0];
    if (path === '/chat') return route.fulfill({path: 'web/index.html'});
    if (path === '/resume') return route.fulfill({path: 'web/resume.html'});
    if (/^\/static\/[\w.-]+$/.test(path)) return route.fulfill({path: 'web/' + path.slice(8)});
    if (/^\/static\/vendor\/[\w.-]+$/.test(path)) return route.fulfill({path: 'web/' + path.slice(8)});
    if (path === '/api/account/me') return route.fulfill({json: {authenticated: true, require_account: true, login_available: true}});
    if (path === '/api/resume/templates') return route.fulfill({json: {templates: [{id: 't001-jianyue', name: '简单单栏'}, {id: 't003-shenlan', name: '深蓝细线'}]}});
    if (path === '/api/resume/current' && request.method() === 'GET') {
      reads.push({frame: request.frame() === page.mainFrame() ? 'parent' : 'editor', session: rawUrl.match(/[?&]session_id=([^&]*)/)?.[1]});
      return route.fulfill({json: {...current, workspace: workspace()}});
    }
    if (path === '/api/resume/current' && request.method() === 'PUT') {
      if (failSave) return route.fulfill({status: 503, json: {detail: {message: '模拟保存失败'}}});
      const body = request.postDataJSON();
      current = {...current, data: body.resume_data, revision: 'saved-' + Date.now()};
      return route.fulfill({json: {saved: true, revision: current.revision, data: current.data}});
    }
    if (path.startsWith('/api/resume/render/')) {
      const name = request.postDataJSON().basic_info?.name || '';
      return route.fulfill({contentType: 'text/html', body: '<!doctype html><html><body><h1>' + name + '</h1><script>parent.postMessage({type:"resume-preview-ready",height:1123},"*")</script></body></html>'});
    }
    if (path.startsWith('/api/resume/export/')) {
      exports.push({path, session: rawUrl.match(/[?&]session_id=([^&]*)/)?.[1], data: request.postDataJSON()});
      if (failExport) return route.fulfill({status: 503, json: {detail: {message: 'PDF 生成暂时失败，请重试'}}});
      await new Promise(resolve => { releaseExport = resolve; });
      return route.fulfill({contentType: path.includes('/pdf/') ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        body: path.includes('/pdf/') ? '%PDF-1.7\nsynthetic fixture\n%%EOF' : 'PK\x03\x04',
        headers: {'Content-Disposition': "attachment; filename*=UTF-8''fixture." + (path.includes('/pdf/') ? 'pdf' : 'docx')}});
    }
    if (path === '/api/chat/conversations' && request.method() === 'POST') { session = 'embedded-b'; return route.fulfill({json: {session_id: session, messages: [], title: '会话乙'}}); }
    if (path === '/api/chat/conversations') return route.fulfill({json: {conversations: []}});
    if (path.startsWith('/api/chat/conversations/')) {
      historyReads++;
      return route.fulfill({json: {session_id: session, title: '虚构编辑测试', stage: current.stage, workspace: workspace(),
        messages: Array.from({length: 18}, (_, i) => ({role: i % 2 ? 'assistant' : 'user', content: '虚构消息 ' + i + '：验证聊天滚动和 DOM 不重建。'}))}});
    }
    // Any accidental API use fails closed, including model/SSE requests.
    return route.fulfill({status: 404, json: {detail: 'Unused fixture route'}});
  });
  await page.setViewportSize({width: 1440, height: 960});
  await page.goto(origin + '/chat?session=' + session);
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled);
  await page.locator('#workspace-tab-resume').click();
  check(await page.locator('#workspace-tab-export').count() === 0, 'four tabs; export tab removed');
  for (const id of ['btn-edit-resume', 'btn-export-pdf', 'btn-export-docx']) check(await page.locator('#' + id).isDisabled(), id + ' disabled without draft');
  check(await page.locator('#resume-actions-hint').textContent() === '先生成简历', 'empty hint');
  current = {...current, has_data: true, revision: 'r1', data: draft('虚构甲')};
  await page.evaluate(() => window.HuhuaWorkspace.refresh());
  await page.waitForFunction(() => document.querySelector('#resume-editor-frame')?.contentDocument?.querySelector('[data-input-path="/basic_info/name"]'));
  const frame = page.frames().find(frame => frame.url().includes('embedded=1'));
  check(frame.url().includes('session_id=' + session), 'idle preload carries current session and embedded=1');
  check(await page.locator('#resume-editor-overlay').isHidden(), 'preloaded editor stays hidden');
  const url = page.url(), historyBefore = historyReads;
  await page.locator('#input').fill('未发送输入留在这里');
  const scrollBefore = await page.evaluate(() => { const el = document.getElementById('messages'); el.scrollTop = 87; window.__messageNode = el.firstElementChild; return el.scrollTop; });
  await page.locator('#btn-edit-resume').click();
  await frame.locator('#btn-finish-edit').waitFor();
  check(page.url() === url && await frame.locator('#header').isHidden(), 'editing opens in-place and hides standalone navigation');
  const initialReads = reads.filter(read => read.frame === 'parent').length;
  await page.evaluate(() => {
    const source = document.getElementById('resume-editor-frame').contentWindow;
    window.dispatchEvent(new MessageEvent('message', {origin: 'https://evil.invalid', source, data: {type: 'resume-saved', revision: 'evil'}}));
    window.dispatchEvent(new MessageEvent('message', {origin: location.origin, source: window, data: {type: 'resume-saved', revision: 'evil'}}));
    window.dispatchEvent(new MessageEvent('message', {origin: 'https://evil.invalid', source, data: {type: 'resume-editor-close'}}));
  });
  await page.waitForTimeout(50);
  check(reads.filter(read => read.frame === 'parent').length === initialReads && await page.locator('#resume-editor-overlay').isVisible(), 'parent ignores wrong origin and wrong window');
  await frame.locator('[data-input-path="/basic_info/name"]').fill('精细编辑已保存');
  await page.waitForFunction(() => document.getElementById('live-sheet').srcdoc.includes('精细编辑已保存'));
  check(reads.filter(read => read.frame === 'parent').length > initialReads, 'resume-saved refreshes parent preview');
  await frame.locator('#btn-finish-edit').click();
  await page.locator('#resume-editor-overlay').waitFor({state: 'hidden'});
  check(page.url() === url && historyReads === historyBefore, 'closing does not reload chat history');
  check(await page.locator('#input').inputValue() === '未发送输入留在这里', 'chat input survives');
  check(await page.evaluate(scroll => document.getElementById('messages').scrollTop === scroll && document.getElementById('messages').firstElementChild === window.__messageNode, scrollBefore), 'chat DOM and scroll survive');
  await page.locator('#btn-edit-resume').click();
  check(page.frames().includes(frame), 'reopening reuses loaded iframe');
  current = {...current, revision: 'chat-r2', data: draft('对话新版本')};
  await page.evaluate(() => window.HuhuaWorkspace.refresh());
  await frame.waitForFunction(() => document.querySelector('[data-input-path="/basic_info/name"]').value === '对话新版本');
  check(true, 'clean editor refreshes when chat changes');
  failSave = true;
  await frame.locator('[data-input-path="/basic_info/name"]').fill('不能覆盖的手工修改');
  current = {...current, revision: 'chat-r3', data: draft('不应覆盖手工修改')};
  await page.evaluate(() => window.HuhuaWorkspace.refresh());
  await frame.locator('#chat-version-notice').waitFor();
  check(await frame.locator('[data-input-path="/basic_info/name"]').inputValue() === '不能覆盖的手工修改', 'dirty editor preserves input');
  check((await frame.locator('#chat-version-message').textContent()).includes('对话里有新版本，保存后可刷新') && await frame.locator('#btn-refresh-chat-version').isDisabled(), 'dirty version prompt and refresh guard');
  await frame.waitForFunction(() => document.getElementById('save-status').textContent.includes('模拟保存失败'));
  failSave = false;
  await frame.locator('#btn-retry-save').click();
  await frame.waitForFunction(() => !document.getElementById('btn-refresh-chat-version').disabled);
  await frame.locator('#btn-refresh-chat-version').click();
  await frame.locator('#chat-version-notice').waitFor({state: 'hidden'});
  await frame.locator('#btn-finish-edit').click();
  await page.evaluate(() => window.HuhuaWorkspace.update({resume: {has_data: true}, focus: 'resume', focus_download: true}, {focus: true}));
  await page.waitForFunction(() => document.getElementById('btn-export-pdf') === document.activeElement);
  check(true, 'export intent focuses PDF in write tab');
  await page.locator('#tpl-rail [data-id="t003-shenlan"]').click();
  await page.locator('#btn-export-pdf').click();
  await page.waitForFunction(() => document.getElementById('btn-export-pdf').textContent === '正在生成…');
  while (!releaseExport) await page.waitForTimeout(10);
  check(await page.locator('#btn-export-pdf').isDisabled(), 'PDF loading blocks duplicate click');
  await page.evaluate(() => document.getElementById('btn-export-pdf').click());
  check(exports.length === 1 && exports[0].path.endsWith('/pdf/t003-shenlan') && exports[0].session === session, 'PDF uses selected template and current session once');
  const downloaded = page.waitForEvent('download'); releaseExport(); releaseExport = null;
  check((await downloaded).suggestedFilename() === 'fixture.pdf', 'PDF download and filename');
  await page.waitForFunction(() => !document.getElementById('btn-export-pdf').disabled);
  check(await page.locator('#workspace-export-download').isVisible(), 'download fallback remains available');
  failExport = true;
  await page.locator('#btn-export-pdf').click();
  await page.waitForFunction(() => document.getElementById('workspace-export-status').textContent.includes('PDF 生成暂时失败'));
  check(await page.locator('#btn-export-pdf').isEnabled(), 'PDF failure shown and button restored');
  failExport = false;
  await page.setViewportSize({width: 390, height: 844});
  await page.locator('#btn-toggle-canvas').click();
  await page.locator('#workspace-tab-resume').click();
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'mobile workspace fits');
  await page.locator('#btn-edit-resume').click();
  await frame.locator('#btn-mobile-edit').click();
  check(await frame.locator('#data-panel').isVisible() && await frame.locator('#btn-finish-edit').isVisible(), 'embedded mobile edit controls retained');
  check(await frame.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'mobile embedded editor fits');
  await frame.locator('#btn-finish-edit').click();
  await page.locator('#btn-close-workspace').click();
  await page.locator('#input').fill('');
  await page.locator('#btn-new-chat').click();
  await page.waitForURL('**/chat?session=embedded-b');
  await page.waitForFunction(() => document.getElementById('resume-editor-frame')?.src.includes('embedded-b'));
  check(!page.frames().includes(frame), 'session switch destroys old iframe and preloads new one');
  await page.goto(origin + '/resume?session=embedded-b');
  await page.locator('[data-input-path="/basic_info/name"]').waitFor();
  check(await page.locator('#header').isVisible() && await page.locator('#embedded-toolbar').isHidden(), 'standalone legacy URL retains navigation');
  check((await page.locator('#back-to-chat').getAttribute('href')).includes('session=embedded-b'), 'legacy return link binds session');
  check(errors.length === 0, 'no browser errors');
  return {passed: checks.length, checks};
}
