// Real local API/database roundtrip with synthetic text only; no model requests.
// playwright-cli -s=huhua-history-real run-code --filename=tests/conversation_history_live.browser.js
async (page) => {
  const checks = [];
  const check = (ok, name) => { if (!ok) throw new Error(name); checks.push(name); };
  const origin = 'http://127.0.0.1:8765';
  const saved = () => page.waitForFunction(() => document.getElementById('save-status')?.textContent.startsWith('已保存到当前会话'));
  const current = async (id) => (await page.request.get(`${origin}/api/resume/current?session_id=${id}`)).json();
  const catalog = async () => (await page.request.get(`${origin}/api/chat/conversations`)).json();
  const input = (path) => page.locator(`[data-input-path="${path}"]`);
  let modelRequests = 0;
  await page.route('**/api/chat/stream', route => { modelRequests++; return route.abort(); });
  const initial = await catalog();
  // This suite must be run in a fresh, isolated playwright-cli browser session.
  check(initial.conversations.length <= 1 && initial.conversations.every(c => !c.has_data), '独立浏览器仅含空白测试会话');
  try {
    if (!initial.conversations.length) await page.evaluate(() => localStorage.clear());
    await page.setViewportSize({width: 1440, height: 960});
    await page.goto(origin);
    await page.waitForFunction(() => document.getElementById('btn-send')?.disabled === false);
    const a = await page.evaluate(() => new URL(location.href).searchParams.get('session'));
    check(Boolean(a), '首页创建数据库会话并保留URL');
    await page.goto(`${origin}/resume?session=${a}`);
    await page.getByRole('button', {name: '新建空白草稿', exact: true}).click();
    await saved();
    await input('/basic_info/name').fill('历史测试候选人A');
    await input('/basic_info/email').fill('history-a@example.test');
    await saved();
    check((await current(a)).data.basic_info.name === '历史测试候选人A', '真实数据库保存A草稿');
    check(await page.locator('#back-to-chat').getAttribute('href') === `/?session=${a}`, '编辑页返回原聊天链接');
    await page.locator('#back-to-chat').click();
    await page.waitForFunction(() => document.getElementById('btn-send')?.disabled === false);
    await page.locator('#btn-new-chat').click();
    await page.waitForFunction(old => new URL(location.href).searchParams.get('session') !== old && document.getElementById('btn-send')?.disabled === false, a);
    const b = await page.evaluate(() => new URL(location.href).searchParams.get('session'));
    check(a !== b && (await catalog()).conversations.length === 2, '新建B保留A且两会话独立');
    await page.goto(`${origin}/resume?session=${b}`);
    await page.getByRole('button', {name: '新建空白草稿', exact: true}).click();
    await saved();
    await input('/basic_info/name').fill('历史测试候选人B');
    await saved();
    await page.locator('#back-to-chat').click();
    await page.waitForFunction(() => document.getElementById('btn-send')?.disabled === false);
    await page.locator('#btn-history').click();
    await page.locator(`.conversation-item[data-session-id="${a}"] .conversation-open`).click();
    await page.waitForFunction(id => new URL(location.href).searchParams.get('session') === id && document.getElementById('btn-send')?.disabled === false, a);
    check((await current(a)).data.basic_info.name === '历史测试候选人A', '从历史切回A取到原稿');
    await page.goto(`${origin}/resume?session=${a}`);
    await input('/basic_info/name').fill('历史测试候选人A最新稿');
    await page.getByRole('button', {name: '＋ 添加自定义栏目', exact: true}).click();
    const bodyField = page.locator('[data-input-path^="/sections/"][data-input-path$="/content"]').last();
    await bodyField.fill('根据目标岗位补充：参与课程原型设计，未上线。');
    await saved();
    await page.reload();
    await input('/basic_info/name').waitFor();
    check(await input('/basic_info/name').inputValue() === '历史测试候选人A最新稿', '刷新恢复最新编辑');
    check((await current(b)).data.basic_info.name === '历史测试候选人B', '编辑A不影响B');
    await page.locator('#back-to-chat').click();
    await page.waitForFunction(() => document.getElementById('btn-export-docx')?.disabled === false);
    const downloadReady = page.waitForEvent('download');
    await page.locator('#btn-export-docx').click();
    const download = await downloadReady;
    await download.saveAs('/tmp/huhua-history-latest.docx');
    check((await download.failure()) === null, '当前会话最新稿Word实际下载成功');
    await page.locator('#btn-history').click();
    await page.screenshot({path: '/tmp/huhua-history-desktop.png'});
    await page.setViewportSize({width: 390, height: 844});
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '手机历史列表无页面横向溢出');
    await page.screenshot({path: '/tmp/huhua-history-mobile.png'});
    await page.evaluate(() => { window.confirm = () => true; });
    await page.locator(`.conversation-item[data-session-id="${a}"] .conversation-delete`).click();
    await page.waitForFunction(id => new URL(location.href).searchParams.get('session') === id && document.getElementById('btn-send')?.disabled === false, b);
    check((await page.request.get(`${origin}/api/chat/conversations/${a}`)).status() === 404, '显式删除A后历史不可再恢复');
    check((await current(b)).data.basic_info.name === '历史测试候选人B', '删除A保留B完整草稿');
    check(modelRequests === 0, '全流程未发起模型请求');
    const report = {checks, docx: '/tmp/huhua-history-latest.docx', screenshots: ['/tmp/huhua-history-desktop.png', '/tmp/huhua-history-mobile.png']};
    await page.evaluate(value => { window.__historyLiveReport = value; }, report);
    console.log(JSON.stringify(report));
    return report;
  } finally {
    for (const item of (await catalog()).conversations) {
      await page.request.delete(`${origin}/api/chat/session/${item.session_id}`);
    }
  }
}
