// U1: 聊天内「本次修改」卡片 + 撤销。接口与 SSE 全部为虚构数据的 mock，不依赖模型。
// playwright-cli -s=change-card run-code --filename=tests/change_card.browser.js （服务：本地兼容模式，端口 8765）
async (page) => {
  page.removeAllListeners('dialog');
  page.on('dialog', dialog => dialog.accept());
  page.removeAllListeners('pageerror');
  await page.unroute('**/api/**');
  const checks = [], errors = [], requests = [];
  const check = (id, condition, detail) => { checks.push({id, passed: !!condition, detail}); if (!condition) throw new Error(id + ': ' + detail); };
  page.on('pageerror', error => errors.push(error.message));
  const session = 'change-card-fixture';
  const rev = n => String(n).padStart(64, '0');
  const OLD = ['整理用户反馈并分类', '制作周报模板'];
  const KEPT = OLD[0], DROPPED = OLD[1], ADDED = '用 JD 里的「数据分析」口径重写周报指标';
  const resume = bullets => ({basic_info: {name: '虚构测试人'}, projects: [{item_id: 'p1', name: '反馈整理项目', polished_bullets: bullets}],
    work_experience: [{item_id: 'w1', company: '虚构科技', position: '运营实习', bullets: ['维护社群日报']}]});
  let current = {bullets: OLD, revision: rev(1), version: 'v1'}, undoMode = 'ok', turn = 0;
  const currentBody = () => ({has_data: true, has_jd: false, data: resume(current.bullets), revision: current.revision, stage: 'EVALUATING', can_save: true,
    version_id: current.version, workspace: {jd: {}, experiences: {items: []}, review: {items: []}, resume: {has_data: true, version: current.revision}}});
  const sse = events => events.map(event => 'data: ' + (typeof event === 'string' ? event : JSON.stringify(event)) + '\n\n').join('');
  const diffFor = (before, after) => [
    {section: 'projects', item_id: 'p1', before: {item_id: 'p1', name: '反馈整理项目', polished_bullets: before}, after: {item_id: 'p1', name: '反馈整理项目', polished_bullets: after}},
    {section: 'work_experience', item_id: 'w1', before: null, after: {item_id: 'w1', company: '虚构科技', position: '运营实习', bullets: ['维护社群日报'], hidden: false}},
    {section: 'skills', item_id: null, before: [], after: ['SQL']},
  ];
  await page.route('**/api/**', async route => {
    const path = '/' + route.request().url().split('/').slice(3).join('/').split('?')[0], method = route.request().method();
    requests.push({path, method, body: method === 'POST' ? route.request().postData() : null});
    if (path === '/api/account/me') return route.fulfill({json: {authenticated: false, require_account: false, login_available: false}});
    if (path === '/api/resume/templates') return route.fulfill({json: {templates: [{id: 't001-jianyue', name: '简约'}]}});
    if (path.startsWith('/api/resume/render/')) return route.fulfill({contentType: 'text/html', body: '<!doctype html><html><body>' + current.bullets.map(b => '<li>' + b + '</li>').join('') + '</body></html>'});
    if (path === '/api/resume/current') return route.fulfill({json: currentBody()});
    if (path === `/api/resume/session/${session}/versions/undo`) {
      if (undoMode === 'conflict') return route.fulfill({status: 409, json: {detail: '简历已变化，请载入最新版本'}});
      if (undoMode === 'down') return route.fulfill({status: 503, json: {detail: '撤销保存失败'}});
      current = {bullets: OLD, revision: rev(9), version: 'v1'};
      return route.fulfill({json: {saved: true, revision: current.revision, data: resume(OLD), version_id: 'v1', diff: [], change_summary: []}});
    }
    if (path === '/api/chat/stream') {
      turn += 1;
      const after = turn === 1 ? [KEPT, ADDED] : [KEPT, ADDED, '补充了跨团队对齐的说明'];
      const before = turn === 1 ? OLD : [KEPT, ADDED];
      current = {bullets: after, revision: rev(1 + turn), version: 'v' + (1 + turn)};
      const meta = {type: 'meta', session_id: session, stage: 'EVALUATING', has_data: true, version_id: current.version, can_undo: true,
        diff: diffFor(before, after), change_summary: ['✅ 已完成：重写「反馈整理项目」的周报指标', '⚠ 需要你确认：「学校写全称」缺少学校名称', '❌ 做不到：补充实习时长（资料里没有）'],
        resume_meta: {}, workspace: currentBody().workspace};
      return route.fulfill({contentType: 'text/event-stream', body: sse([{content: '已按「数据分析」更新第 ' + (1 + turn) + ' 版简历。'}, meta, '[DONE]'])});
    }
    if (path === '/api/chat/conversations' && method === 'POST') return route.fulfill({json: {session_id: session, title: '本次修改测试', messages: []}});
    if (path === '/api/chat/conversations') return route.fulfill({json: {conversations: [{session_id: session, title: '本次修改测试', updated_at: '2026-10-10T00:00:00Z'}], retention_days: 0}});
    if (path.startsWith('/api/chat/conversations/')) return route.fulfill({json: {session_id: session, title: '本次修改测试', messages: [], stage: 'EVALUATING'}});
    return route.fulfill({status: 503, json: {detail: '模拟接口'}});
  });
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto('http://127.0.0.1:8765/?session=' + session, {waitUntil: 'domcontentloaded'});
  await page.waitForFunction(() => window.HuhuaChangeCard && !document.getElementById('btn-send').disabled);
  await page.waitForFunction(() => document.getElementById('live-sheet')?.srcdoc?.includes('制作周报模板'));
  const send = async text => { await page.locator('#input').fill(text); await page.locator('#btn-send').click(); await page.waitForFunction(() => document.getElementById('btn-send').title === '发送'); };

  await send('把周报那条按数据分析口径重写，再加一条学校全称和实习时长');
  const card = page.locator('.bubble-ai .change-card').first();
  await card.waitFor();
  check('card-under-reply', await page.locator('.bubble-ai').last().locator('.change-card').count() === 1, '卡片出现在该条助手回复内');
  check('items-collapsed-per-experience', await card.locator('details.change-item').count() === 2, '按经历折叠：项目 + 新增的实习');
  check('first-item-open', await card.locator('details.change-item').first().evaluate(node => node.open), '第一段经历默认展开');
  check('removed-struck-through', await card.locator('.change-bullet-removed del').first().evaluate(node => getComputedStyle(node).textDecorationLine.includes('line-through')) && (await card.locator('.change-bullet-removed').first().textContent()).includes(DROPPED), '删除的 bullet 划线展示');
  check('added-highlighted', (await card.locator('.change-bullet-add').first().textContent()).includes(ADDED) && await card.locator('.change-bullet-add').first().evaluate(node => getComputedStyle(node).backgroundColor !== 'rgba(0, 0, 0, 0)'), '新增 bullet 高亮');
  check('unchanged-bullet-kept', (await card.locator('.change-bullet-same').first().textContent()).includes(KEPT), '未变化的 bullet 弱化显示');
  check('new-item-tag', (await card.locator('.change-item-tag').nth(1).textContent()) === '新增', '新增经历带「新增」标签');
  check('three-receipts', await card.locator('.change-receipt-ok').count() === 1 && await card.locator('.change-receipt-warn').count() === 1 && await card.locator('.change-receipt-fail').count() === 1, '逐条回执 ✅/⚠/❌');
  check('other-section-note', (await card.locator('.change-card-note').textContent()).includes('技能'), '非经历栏目的改动只提示一句');
  await page.screenshot({path: '/private/tmp/huhua-change-card-desktop.png'});

  // 409：简历在别处变化 -> 提示、刷新、按钮仍可重试；503：保留当前版本。
  undoMode = 'conflict';
  await card.getByRole('button', {name: '撤销这次修改'}).click();
  await page.waitForFunction(() => document.querySelector('.change-card-status')?.textContent.includes('已载入最新版本'));
  check('conflict-keeps-button', await card.getByRole('button', {name: '撤销这次修改'}).isEnabled(), '409 后按钮可再试');
  undoMode = 'down';
  await card.getByRole('button', {name: '撤销这次修改'}).click();
  await page.waitForFunction(() => document.querySelector('.change-card-status')?.textContent.includes('当前版本未更改'));
  check('unavailable-keeps-state', !(await card.evaluate(node => node.classList.contains('change-card-undone'))), '503 不标记已撤销');

  undoMode = 'ok';
  const before = requests.length;
  await card.getByRole('button', {name: '撤销这次修改'}).click();
  await page.waitForFunction(() => document.querySelector('.change-card.change-card-undone'));
  const undoCall = requests.slice(before).find(call => call.path.endsWith('/versions/undo'));
  check('undo-bound-to-revision', /^[0-9a-f]{64}$/.test(JSON.parse(undoCall.body).expected_revision), '撤销携带 64 位 revision');
  check('card-marked-undone', (await card.locator('.change-card-status').textContent()).includes('已撤销') && await card.getByRole('button', {name: '撤销这次修改'}).count() === 0, '卡片标为已撤销');
  await page.waitForFunction(() => document.getElementById('live-sheet').srcdoc.includes('制作周报模板'));
  check('preview-refreshed', !(await page.evaluate(() => document.getElementById('live-sheet').srcdoc)).includes('数据分析'), '右侧预览恢复为修改前');

  // 第二次修改：旧卡片只读，新卡片可撤销。
  await send('再补一条跨团队对齐');
  await page.waitForFunction(() => document.querySelectorAll('.change-card').length === 2);
  const cards = page.locator('.change-card');
  check('latest-card-has-undo', await cards.nth(1).getByRole('button', {name: '撤销这次修改'}).isEnabled(), '最新一张可撤销');
  check('no-card-for-unversioned-meta', await page.locator('.bubble-ai').count() === 2, '每条回复各一张卡');

  // 手机宽度：卡片不溢出。
  await page.setViewportSize({width: 390, height: 844});
  await page.waitForTimeout(200);
  const layout = await page.evaluate(() => {
    const box = document.querySelectorAll('.change-card')[1].getBoundingClientRect();
    return {page: document.documentElement.scrollWidth <= innerWidth, right: box.right <= innerWidth + 0.5, inner: [...document.querySelectorAll('.change-card *')].every(node => node.getBoundingClientRect().right <= innerWidth + 0.5)};
  });
  check('mobile-no-overflow', layout.page && layout.right && layout.inner, '390px 下卡片与内部元素不溢出：' + JSON.stringify(layout));
  await page.locator('.change-card').nth(1).scrollIntoViewIfNeeded();
  await page.screenshot({path: '/private/tmp/huhua-change-card-mobile.png'});
  check('no-page-errors', errors.length === 0, errors.join('|'));
  return {passed: checks.length, checks};
}
