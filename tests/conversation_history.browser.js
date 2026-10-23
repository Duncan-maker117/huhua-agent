// Disposable fixture: every business API is mocked, no model or personal data.
// playwright-cli -s=huhua-history open about:blank
// playwright-cli -s=huhua-history run-code --filename=tests/conversation_history.browser.js
async (page) => {
  const checks = [];
  const errors = [];
  const requests = [];
  const check = (value, label) => { if (!value) throw new Error(label); checks.push(label); };
  const baseUrl = 'https://huhua-conversations.fixture';
  const fixtures = new Map([
    ['history-a', {session_id: 'history-a', title: 'A · 产品经理岗位', updated_at: '2026-10-02T06:00:00Z', stage: 'EVALUATING', has_data: true,
      jd_text: 'A 产品经理 JD', collected_info: {skills: ['A 能力']}, resume_data: {basic_info: {name: 'A 保存的简历'}},
      messages: [{role: 'user', content: 'A 的 JD 和真实经历'}, {role: 'assistant', content: '**A 已有简历**\n\n- 只属于 A 的事实'}]}],
    ['history-b', {session_id: 'history-b', title: 'B · 开发岗位', updated_at: '2026-10-02T05:00:00Z', stage: 'COLLECTING', has_data: true,
      jd_text: 'B 开发 JD', collected_info: {skills: ['B 能力']}, resume_data: {basic_info: {name: 'B 保存的简历'}},
      messages: [{role: 'user', content: 'B 的 JD 和项目'}, {role: 'assistant', content: '**B 的回复**'}]}],
  ]);
  let newCount = 0;
  let listFailed = false;
  let createFailed = false;
  let holdReadA = null;
  let readStarted;
  let holdDelete = null;
  let deleteStarted;
  let holdStream = null;
  let streamStarted;
  let lastSend = null;
  let streamMode = '';
  page.removeAllListeners('pageerror');
  page.removeAllListeners('dialog');
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.unroute('**/api/**');
  await page.route(baseUrl + '/chat**', route => route.fulfill({path: 'web/index.html'}));
  await page.route(baseUrl + '/resume**', route => route.fulfill({path: 'web/resume.html'}));
  await page.route(baseUrl + '/static/**', route => route.fulfill({path: 'web/' + route.request().url().split('/static/')[1].split('?')[0]}));
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({contentType: 'text/css', body: ''}));
  await page.addInitScript(() => {
    if (window !== window.top) return;
    if (!localStorage.getItem('history-test-seeded')) {
      localStorage.clear();
      localStorage.setItem('history-test-seeded', '1');
      localStorage.setItem('huhua_session_id', 'history-a');
      localStorage.setItem('huhua_saved_at', '1'); // Old histories must not be discarded by a seven-day browser TTL.
      localStorage.setItem('huhua_messages', JSON.stringify([{role: 'user', content: 'A 的 JD 和真实经历'}, {role: 'assistant', content: '**A 已有简历**\n\n- 只属于 A 的事实'}]));
    }
  });
  await page.route('**/api/**', async route => {
    const req = route.request();
    const path = '/' + req.url().split('/').slice(3).join('/').split('?')[0];
    requests.push({path, method: req.method()});
    if (path === '/api/chat/conversations') {
      if (req.method() === 'POST') {
        if (createFailed) { await route.fulfill({status: 503, json: {detail: '模拟数据库不可用'}}); return; }
        const claim = req.postDataJSON().session_id;
        if (claim) {
          if (!fixtures.has(claim)) { await route.fulfill({status: 404, json: {detail: '旧会话不存在'}}); return; }
          await route.fulfill({json: fixtures.get(claim)});
        } else {
          const empty = [...fixtures.values()].find(item => !item.has_data && !item.messages.length);
          if (empty) return route.fulfill({json: empty});
          const id = 'history-new-' + (++newCount);
          const data = {session_id: id, title: '新对话 ' + newCount, updated_at: '2026-10-02T07:00:00Z', stage: 'JD_INPUT', has_data: false, messages: [], resume_data: {}};
          fixtures.set(id, data);
          await route.fulfill({json: data});
        }
      } else {
        if (listFailed) { await route.fulfill({status: 503, json: {detail: '模拟历史读取失败'}}); return; }
        await route.fulfill({json: {conversations: [...fixtures.values()].filter(item => item.has_data || item.messages.length), retention_days: 0}});
      }
    } else if (path.startsWith('/api/chat/conversations/')) {
      const id = decodeURIComponent(path.split('/').at(-1));
      if (id === 'history-a' && holdReadA) { const wait = holdReadA; readStarted?.(); await wait; }
      if (!fixtures.has(id)) { await route.fulfill({status: 404, json: {detail: '该对话不可访问'}}); return; }
      await route.fulfill({json: fixtures.get(id)});
    } else if (path.startsWith('/api/chat/session/') && req.method() === 'DELETE') {
      if (holdDelete) { deleteStarted?.(); await holdDelete; }
      const id = decodeURIComponent(path.split('/').at(-1));
      fixtures.delete(id);
      await route.fulfill({json: {deleted: true}});
    } else if (path === '/api/chat/stream') {
      lastSend = req.postDataJSON();
      if (holdStream) { streamStarted?.(); await holdStream; }
      const fixture = fixtures.get(lastSend.session_id);
      const reply = streamMode === 'lost' ? '这条回复没有落库，所以服务端最后一条仍是上一轮的内容。' : streamMode ? '已按已有事实更新右侧待核对草稿，并保留未涉及的内容。' : '**已基于这个对话修改**';
      // prefix：流式文本多出一段进度前缀，落库只有最终回复；lost：服务端没有保存本轮回复。
      if (streamMode !== 'lost') fixture.messages.push(lastSend.messages.at(-1), {role: 'assistant', content: reply});
      fixture.updated_at = '2026-10-02T08:00:00Z';
      const streamed = streamMode === 'prefix' ? '正在根据你已经确认的经历写这一版…\n\n' + reply : reply;
      await route.fulfill({contentType: 'text/event-stream', body: 'data: ' + JSON.stringify({content: streamed}) + '\n\ndata: [DONE]\n\n'});
    } else if (path === '/api/resume/current') {
      const fixture = fixtures.get(decodeURIComponent(req.url().split('session_id=')[1] || ''));
      await route.fulfill({json: {data: fixture?.resume_data, has_data: fixture?.has_data || false, stage: fixture?.stage || 'JD_INPUT', has_jd: true, match_enabled: false}});
    } else if (path === '/api/resume/templates') {
      await route.fulfill({json: {templates: [{id: 'fixture', name: '测试模板'}]}});
    } else if (path.startsWith('/api/resume/render/')) {
      await route.fulfill({contentType: 'text/html', body: '<!doctype html><html><body>' + req.postDataJSON().basic_info.name + '</body></html>'});
    } else await route.fulfill({status: 503, json: {detail: '测试中未使用的接口'}});
  });
  const ready = () => page.waitForFunction(() => !document.getElementById('btn-send').disabled);
  const active = (id) => page.waitForFunction(value => new URL(location.href).searchParams.get('session') === value && !document.getElementById('btn-send').disabled, id);
  const openHistory = async () => { if (await page.locator('#conversation-overlay').isHidden()) await page.locator('#btn-history').click(); };
  const select = async (id) => { await openHistory(); await page.locator(`[data-session-id="${id}"] .conversation-open`).click(); await active(id); };

  await page.setViewportSize({width: 1440, height: 960});
  await page.route('**/api/account/me', route => route.fulfill({json:{authenticated:false, require_account:false, login_available:false}}));
  await page.goto(baseUrl + '/chat');
  await ready();
  check(page.url().split('session=')[1] === 'history-new-1', '无 session 时新建空对话，不自动打开本地记录或最近历史');
  check(await page.locator('.bubble-user').count() === 0, '新入口不恢复旧聊天消息');
  await openHistory();
  check(await page.locator('.conversation-item').count() === 2, '空对话不出现在历史列表');
  await select('history-a');
  check(await page.locator('.bubble-ai strong').textContent() === 'A 已有简历', '从数据库恢复原始 Markdown');
  check(!requests.some(r => r.path === '/api/account/claim-browser'), '账号认领必须由用户显式触发');
  check(await page.evaluate(() => localStorage.getItem('huhua_chat_backup:history-a') === null && localStorage.getItem('huhua_messages') === null), '启动清理旧明文全文缓存');
  await page.waitForFunction(() => document.getElementById('live-sheet').srcdoc.includes('A 保存的简历'));
  await openHistory();
  check(await page.locator('.conversation-item').first().getAttribute('data-session-id') === 'history-a', '历史按最近更新时间显示');
  check(await page.locator('[data-session-id="history-a"] .conversation-open').getAttribute('aria-current') === 'true', '活动对话高亮');
  await page.locator('#btn-close-history').click();
  await page.locator('#input').fill('A 未发送的补充');
  await select('history-b');
  check(await page.locator('#input').inputValue() === '', '切换对话不带入另一对话的输入草稿');
  check(await page.locator('.bubble-user').textContent() === 'B 的 JD 和项目', '切换恢复 B 的消息');
  await page.waitForFunction(() => document.getElementById('live-sheet').srcdoc.includes('B 保存的简历'));
  check(!(await page.locator('#messages').textContent()).includes('A 的 JD'), 'B 不混入 A 消息');
  await page.waitForFunction(() => document.getElementById('resume-editor-frame')?.src.includes('history-b'));
  check((await page.locator('#resume-editor-frame').getAttribute('src')).includes('session_id=history-b'), '编辑入口带当前对话 ID');
  check((await page.locator('header nav a').nth(1).getAttribute('href')).includes('history-b'), '顶部模板入口随切换同步');
  await select('history-a');
  check(await page.locator('#input').inputValue() === 'A 未发送的补充', '返回 A 恢复未发送草稿');

  const deleteCount = requests.filter(r => r.method === 'DELETE').length;
  await page.locator('#btn-new-chat').click();
  await active('history-new-1');
  check(requests.filter(r => r.method === 'DELETE').length === deleteCount && fixtures.has('history-a'), '新建对话绝不删除旧会话');
  check(await page.locator('.bubble-user').count() === 0 && await page.locator('#workspace-panel-jd').isVisible() && await page.locator('#live-sheet').evaluate(el => el.srcdoc === ''), '新对话清空消息和简历画布，默认显示岗位入口');
  check(!(await page.locator('#workspace-body').textContent()).includes('B 保存的简历') && !(await page.locator('#guidance-dock').isVisible()) && await page.locator('#btn-export-docx').isDisabled(), '新对话不残留旧工作区、追问或可导出状态');
  const postsBefore = requests.filter(r => r.method === 'POST' && r.path === '/api/chat/conversations').length;
  await page.locator('#input').fill('尚未发送的草稿');
  await page.locator('#btn-new-chat').click();
  check(requests.filter(r => r.method === 'POST' && r.path === '/api/chat/conversations').length === postsBefore, '当前空对话点击新对话不请求创建');
  check(await page.locator('#input').inputValue() === '尚未发送的草稿', '复用当前空对话保留输入草稿');
  await select('history-a');
  createFailed = true;
  await page.locator('#btn-new-chat').click();
  await page.waitForFunction(() => document.getElementById('conversation-status').textContent.includes('模拟数据库不可用'));
  check(page.url().split('session=')[1] === 'history-a', '新建失败不伪造已创建或丢失当前会话');
  createFailed = false;
  await select('history-a');
  await page.reload();
  await ready();
  check(page.url().split('session=')[1] === 'history-a' && (await page.locator('#messages').textContent()).includes('A 已有简历'), '刷新从服务器恢复指定聊天');
  await page.goto(baseUrl + '/chat?session=history-b');
  await ready();
  check((await page.locator('#messages').textContent()).includes('B 的回复'), '编辑页返回的 URL 会话优先于本地活动 ID');

  let releaseRead;
  holdReadA = new Promise(resolve => { releaseRead = resolve; });
  const didStartRead = new Promise(resolve => { readStarted = resolve; });
  await openHistory();
  await page.locator('[data-session-id="history-a"] .conversation-open').click();
  await didStartRead;
  await page.locator('[data-session-id="history-b"] .conversation-open').click();
  await active('history-b');
  holdReadA = null;
  const readFinished = page.waitForResponse(response => response.url().endsWith('/api/chat/conversations/history-a'));
  releaseRead();
  await readFinished;
  check(page.url().split('session=')[1] === 'history-b' && !(await page.locator('#messages').textContent()).includes('A 已有简历'), '迟到的历史请求不覆盖已切换会话');

  await select('history-a');
  let releaseStream;
  holdStream = new Promise(resolve => { releaseStream = resolve; });
  const didStartStream = new Promise(resolve => { streamStarted = resolve; });
  await page.locator('#input').fill('只调整 A 的项目表达');
  await page.locator('#btn-send').click();
  await didStartStream;
  await openHistory();
  await page.locator('[data-session-id="history-b"] .conversation-open').click();
  check(page.url().split('session=')[1] === 'history-a', '生成中禁止切换会话');
  check((await page.locator('#conversation-status').textContent()).includes('先点击停止'), '提示停止后再切换');
  await page.locator('#btn-close-history').click();
  holdStream = null; releaseStream();
  await page.waitForFunction(() => document.getElementById('btn-send').title === '发送');
  check(lastSend.session_id === 'history-a' && lastSend.messages.length === 1 && lastSend.messages[0].content === '只调整 A 的项目表达', '续聊使用原会话且只发送本轮消息');
  check(fixtures.get('history-b').messages.length === 2, '续聊不会改写其他会话记录');

  streamMode = 'prefix';
  const afterPrefixTurn = page.waitForResponse(response => response.url().endsWith('/api/chat/conversations/history-a'));
  await page.locator('#input').fill('再微调一次');
  await page.locator('#btn-send').click();
  await afterPrefixTurn;
  await page.waitForTimeout(400);
  check(!(await page.locator('#conversation-status').textContent()).includes('可能未完整保存'), '流式文本比落库回复多出进度前缀时仍判为已保存');
  streamMode = 'lost';
  await page.locator('#input').fill('这一轮服务端没保存');
  await page.locator('#btn-send').click();
  await page.waitForFunction(() => document.getElementById('conversation-status').textContent.includes('可能未完整保存'));
  check(true, '服务端确实没有保存本轮回复时仍提示可能未完整保存');
  streamMode = '';

  fixtures.get('history-a').messages.push({role: 'user', content: '中断测试的同一用户消息'});
  const incomplete = [...fixtures.get('history-a').messages, {role: 'assistant', content: '**本地未完成片段\n\n[已中断]', interrupted: true}];
  await page.evaluate(value => {
    chatBackups.set('history-a', value);
  }, incomplete);
  await select('history-b'); await select('history-a');
  check((await page.locator('.bubble-ai').last().textContent()).includes('本地未完成片段'), '同一页面切回对话保留内存中断片段');
  check((await page.locator('#conversation-status').textContent()).includes('尚未保存到数据库'), '本地中断片段明确区别于数据库保存');
  check(await page.locator('#btn-chat-backup').isVisible(), '恢复稿有可用下载入口');
  const download = page.waitForEvent('download');
  await page.locator('#btn-chat-backup').click();
  check((await download).suggestedFilename() === '对话-本页恢复稿.json', '恢复稿可下载');

  let releaseDelete;
  holdDelete = new Promise(resolve => { releaseDelete = resolve; });
  const didStartDelete = new Promise(resolve => { deleteStarted = resolve; });
  await openHistory();
  await page.locator('[data-session-id="history-a"] .conversation-delete').click();
  await didStartDelete;
  await page.locator('[data-session-id="history-b"] .conversation-open').click();
  check(page.url().split('session=')[1] === 'history-a' && await page.locator('#btn-send').isDisabled(), '删除请求期间锁定切换与发送，避免误清另一对话');
  holdDelete = null; releaseDelete();
  await page.waitForFunction(() => new URL(location.href).searchParams.get('session') !== 'history-a' && !document.getElementById('btn-send').disabled);
  check(!fixtures.has('history-a') && fixtures.has('history-b'), '明确删除仅移除指定会话');
  check(await page.evaluate(() => !localStorage.getItem('huhua_chat_backup:history-a') && !localStorage.getItem('huhua_chat_recovery:history-a')), '显式删除同步移除本地个人备份');
  await select('history-b');
  await page.setViewportSize({width: 390, height: 844});
  await openHistory();
  check(await page.locator('#conversation-drawer').isVisible(), '手机可打开历史抽屉');
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '手机历史与顶部入口不撑宽页面');
  await page.keyboard.press('Escape');
  check(await page.locator('#conversation-overlay').isHidden(), '历史抽屉可键盘关闭');

  listFailed = true;
  await page.reload();
  await page.waitForFunction(() => document.getElementById('conversation-status').textContent.includes('模拟历史读取失败'));
  check(!(await page.locator('#messages').textContent()).includes('B 的回复') && await page.locator('#btn-send').isDisabled(), '刷新后服务器失败不从明文浏览器缓存恢复或冒充连接');
  check(await page.locator('#btn-chat-backup').isHidden(), '新页面没有内存恢复稿时不提供空备份');
  listFailed = false;
  await page.locator('#btn-history-retry').click(); await ready();
  check(page.url().split('session=')[1] === 'history-b', '失败后重试回到原会话');
  check(errors.length === 0, '无浏览器脚本异常：' + JSON.stringify(errors));
  const result = {scope: '独立浏览器，历史/聊天/简历 API 全部模拟；无模型调用或真实用户资料。', checks, errors, requests: requests.length};
  await page.evaluate(value => { window.__conversationHistoryReport = value; }, result);
  return result;
}
