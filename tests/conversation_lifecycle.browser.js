// Synthetic APIs only. Run in a fresh Chromium or WebKit context:
// playwright-cli -s=huhua-lifecycle run-code --filename=tests/conversation_lifecycle.browser.js
async (page) => {
  const origin = 'https://huhua-lifecycle.fixture', checks = [], errors = [], requests = [];
  const check = (ok, label) => { if (!ok) throw new Error(label); checks.push(label); };
  let mode = 'account', sequence = 0;
  const sessions = new Map();
  const make = (id, messages = [], hasMessages = messages.length > 0) => ({
    session_id: id, title: id, messages, has_messages: hasMessages,
    has_data: false, resume_data: {}, stage: 'JD_INPUT', updated_at: '2026-10-23T00:00:00Z',
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.addInitScript(() => {
    if (window !== window.top) return;
    localStorage.setItem('huhua_session_id', 'recent');
    sessionStorage.setItem('huhua_guest_session_id', 'recent');
    window.lifecycleHistory = {length: history.length, pushes: 0, replaces: 0};
    const replace = history.replaceState.bind(history), push = history.pushState.bind(history);
    history.replaceState = (...args) => { lifecycleHistory.replaces++; return replace(...args); };
    history.pushState = (...args) => { lifecycleHistory.pushes++; return push(...args); };
  });
  await page.route('**/*', async route => {
    const req = route.request(), url = req.url(), path = url.slice(origin.length).split('?')[0];
    if (!url.startsWith(origin + '/')) return route.fulfill({body: '', contentType: 'text/css'});
    if (path === '/chat') return route.fulfill({path: 'web/index.html'});
    if (path.startsWith('/static/')) return route.fulfill({path: 'web/' + path.slice(8)});
    requests.push({mode, path, method: req.method()});
    if (path === '/api/account/me') return route.fulfill({json: {
      authenticated: mode === 'account', require_account: mode !== 'legacy',
      guest_allowed: mode === 'guest', guest_retention_hours: 24, login_available: true,
      account: mode === 'account' ? {email: 'fixture@example.invalid'} : null,
    }});
    if (path === '/api/chat/conversations') {
      if (req.method() === 'POST') {
        const empty = [...sessions.values()].find(item => !item.has_messages && !item.has_data);
        const body = empty || make('new-' + (++sequence));
        sessions.set(body.session_id, body);
        return route.fulfill({json: body});
      }
      if (mode === 'guest') return route.fulfill({status: 401, json: {detail: '请登录'}});
      return route.fulfill({json: {conversations: [...sessions.values()].filter(item => item.has_messages), retention_days: 0}});
    }
    if (path.startsWith('/api/chat/conversations/')) {
      const body = sessions.get(path.split('/').at(-1));
      return body ? route.fulfill({json: body}) : route.fulfill({status: 404, json: {detail: '对话已过期'}});
    }
    if (path === '/api/resume/current') return route.fulfill({json: {has_data: false, stage: 'JD_INPUT'}});
    if (path === '/api/resume/templates') return route.fulfill({json: {templates: []}});
    return route.fulfill({status: 404, json: {detail: 'Unused synthetic route'}});
  });
  const ready = () => page.waitForFunction(() => !document.getElementById('btn-send').disabled);
  const active = () => page.url().split('session=')[1]?.split('&')[0];
  const historyStable = async label => check(await page.evaluate(() =>
    history.length === lifecycleHistory.length && lifecycleHistory.pushes === 0 && lifecycleHistory.replaces > 0), label);
  const posts = () => requests.filter(row => row.path === '/api/chat/conversations' && row.method === 'POST').length;
  for (mode of ['account', 'legacy', 'guest']) {
    sessions.clear();
    sessions.set('recent', make('recent', [{role: 'user', content: '以前的真实消息'}]));
    sessions.set('failed', make('failed', [], true));
    await page.goto(origin + '/chat');
    await ready();
    const created = active();
    check(created?.startsWith('new-'), mode + ': 无 session 忽略最近历史和浏览器记忆，新建对话并写入 URL');
    if (mode !== 'guest') check(requests.some(row => row.mode === mode && row.path === '/api/chat/conversations' && row.method === 'GET'), mode + ': 已读取历史但未自动续聊');
    check(await page.locator('.bubble-user').count() === 0, mode + ': 新对话没有旧消息');
    await historyStable(mode + ': 初始化仅 replaceState，history.length 不增加');
    const before = posts();
    await page.locator('#input').fill('未发送的草稿');
    await page.locator('#btn-new-chat').click();
    check(posts() === before && active() === created, mode + ': 当前空对话不重复创建');
    check(await page.locator('#input').inputValue() === '未发送的草稿', mode + ': 空对话按钮保留输入');
    await page.locator('#input').fill('');
    await page.reload(); await ready();
    check(active() === created && posts() === before, mode + ': 刷新打开 URL 指定的空对话');
    await historyStable(mode + ': 刷新恢复不增加历史');
    await page.goto(origin + '/chat?session=recent' + (mode === 'account' ? '&from=mcp' : ''));
    await ready();
    check(active() === 'recent' && (await page.locator('#messages').textContent()).includes('以前的真实消息'), mode + ': 显式 session 链接恢复原对话');
    await page.locator('#btn-new-chat').click(); await ready();
    check(active() === created && posts() === before + 1, mode + ': 已有消息时请求新对话并复用服务端空对话');
    await historyStable(mode + ': 切换新对话不增加后退次数');
    await page.goto(origin + '/chat?session=failed'); await ready();
    const beforeFailed = posts();
    await page.locator('#btn-new-chat').click(); await ready();
    check(active() === created && posts() === beforeFailed + 1, mode + ': 提交过但无 checkpoint 的对话仍允许新建');
    if (mode === 'guest') {
      await page.goto(origin + '/chat?session=expired'); await ready();
      check(active() === created, 'guest: 失效链接回退到可用空对话');
      check(!requests.some(row => row.mode === 'guest' && row.path === '/api/chat/conversations' && row.method === 'GET'), 'guest: 不读取登录用户的历史列表');
    }
  }
  check(errors.length === 0, '无页面脚本错误：' + errors.join('; '));
  return {checks, errors};
}
