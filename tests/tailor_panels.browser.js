// U2/U3/U5: 读岗位匹配表、核对页（可迁移 / 缺数字）、追问快捷回复。接口为虚构数据 mock，不依赖模型。
// playwright-cli -s=tailor-panels run-code --filename=tests/tailor_panels.browser.js （服务：本地兼容模式，端口 8765）
async (page) => {
  page.removeAllListeners('dialog');
  page.on('dialog', dialog => dialog.accept());
  page.removeAllListeners('pageerror');
  await page.unroute('**/api/**');
  const checks = [], errors = [], streamBodies = [];
  const check = (id, condition, detail) => { checks.push({id, passed: !!condition, detail}); if (!condition) throw new Error(id + ': ' + detail); };
  page.on('pageerror', error => errors.push(error.message));
  const session = 'tailor-panels-fixture';
  const B1 = '搭建反馈分类表并每周同步给产品同学', B2 = '用 Python 脚本清洗 2000 条问卷数据', B3 = '负责社群日报与活动复盘';
  const data = {basic_info: {name: '虚构测试人'}, projects: [
    {item_id: 'p1', name: '反馈整理项目', polished_bullets: [B1, B2]},
    {item_id: 'p2', name: '备用项目', hidden: true, polished_bullets: ['被隐藏的一条']}],
    work_experience: [{item_id: 'w1', company: '虚构科技', position: '运营实习', bullets: [B3]}]};
  const questions = [
    {question_id: 'q-owner', q: '反馈分类表是你自己搭建的吗？', why: '澄清本人贡献', location_label: '反馈整理项目 第 1 条', improves: {item_id: 'p1', req_id: 'r1'},
     options: [{label: '是，我独立完成', value: '是，我独立完成'}, {label: '不知道 / 没有', value: '不知道 / 没有'}], value: 5},
    {question_id: 'q-metric', q: '问卷数据清洗后准确率提升了多少？', why: '可选指标', location_label: '反馈整理项目 第 2 条', improves: {item_id: 'p1', req_id: 'r2'},
     options: [{label: '提升约 10%', value: '提升约 10%'}], value: 3}];
  const workspace = {
    jd: {info: {job_title: '产品运营实习生', role_profile: {requirements: [
      {id: 'r1', text: '能与研发、产品协作推进需求'}, {id: 'r2', text: '有数据分析与清洗经验'}, {id: 'r3', text: '熟悉增长实验与 A/B 测试'}]}}, keywords: [], raw_text: '岗位要求（虚构）'},
    experiences: {items: []}, review: {items: []}, resume: {has_data: true, version: 'rev-1'},
    tailor: {version_id: 'v1', diff: [], change_summary: [], can_undo: false, questions,
      match_plan: {requirements: [
        {req_id: 'r1', status: 'direct', fact_ids: ['f1'], angle: '每周同步体现跨角色协作'},
        {req_id: 'r2', status: 'transferable', fact_ids: ['f2'], angle: '问卷清洗迁移到数据分析'},
        {req_id: 'r3', status: 'gap', fact_ids: [], angle: ''}]},
      resume_meta: {bullets: {
        p1: [{fact_ids: ['f1'], req_ids: ['r1'], flags: [], needs_metric: false}, {fact_ids: ['f2'], req_ids: ['r2'], flags: ['transferable'], needs_metric: true, metric_question: '问卷数据清洗后准确率或耗时有什么变化？没有可以不填。'}],
        w1: [{fact_ids: ['f3'], req_ids: [], flags: [], needs_metric: false}]}}},
    guidance: null, suggestions: [], focus: 'jd'};
  await page.route('**/api/**', async route => {
    const path = '/' + route.request().url().split('/').slice(3).join('/').split('?')[0], method = route.request().method();
    if (path === '/api/account/me') return route.fulfill({json: {authenticated: false, require_account: false, login_available: false}});
    if (path === '/api/resume/templates') return route.fulfill({json: {templates: [{id: 't001-jianyue', name: '简约'}]}});
    if (path.startsWith('/api/resume/render/')) {
      const body = route.request().postDataJSON();
      const items = [...body.projects.filter(p => !p.hidden).flatMap(p => p.polished_bullets), ...body.work_experience.flatMap(w => w.bullets)];
      return route.fulfill({contentType: 'text/html', body: '<!doctype html><html><body><ul>' + items.map(b => '<li>' + b + '</li>').join('') + '</ul></body></html>'});
    }
    if (path === '/api/resume/current') return route.fulfill({json: {has_data: true, has_jd: true, data, revision: '0'.repeat(63) + '1', stage: 'EVALUATING', can_save: true, version_id: 'v1', workspace, ...workspace.tailor}});
    if (path === '/api/chat/stream') {
      streamBodies.push(route.request().postDataJSON());
      return route.fulfill({contentType: 'text/event-stream', body: 'data: {"content":"收到。"}\n\ndata: [DONE]\n\n'});
    }
    if (path === '/api/chat/conversations' && method === 'POST') return route.fulfill({json: {session_id: session, title: '面板测试', messages: []}});
    if (path === '/api/chat/conversations') return route.fulfill({json: {conversations: [{session_id: session, title: '面板测试', updated_at: '2026-10-10T00:00:00Z'}], retention_days: 0}});
    if (path.startsWith('/api/chat/conversations/')) return route.fulfill({json: {session_id: session, title: '面板测试', messages: [], stage: 'EVALUATING'}});
    return route.fulfill({status: 503, json: {detail: '模拟接口'}});
  });
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto('http://127.0.0.1:8765/?session=' + session, {waitUntil: 'domcontentloaded'});
  await page.evaluate(session => { try { localStorage.removeItem('huhua_closed_questions:' + session); } catch (_) {} }, session);
  await page.reload({waitUntil: 'domcontentloaded'});
  await page.waitForFunction(() => window.HuhuaWorkspace && !document.getElementById('btn-send').disabled);
  await page.waitForFunction(() => document.getElementById('live-sheet')?.srcdoc?.includes('反馈分类表'));

  // U2 读岗位：匹配表
  await page.locator('#workspace-tab-jd').click();
  const rows = page.locator('#workspace-panel-jd .match-row');
  check('three-requirements', await rows.count() === 3, '三条 JD 要求');
  check('badges', JSON.stringify(await rows.locator('.match-badge').allTextContents()) === JSON.stringify(['直接证据', '可迁移', '缺口']), '直接证据 / 可迁移 / 缺口');
  check('direct-lists-bullet', (await rows.nth(0).locator('.match-bullet').allTextContents()).join('') === B1, '直接项列出对应 bullet 原文');
  check('transferable-lists-bullet', (await rows.nth(1).locator('.match-bullet').allTextContents()).join('') === B2, '可迁移项列出对应 bullet 原文');
  check('gap-no-evidence', (await rows.nth(2).textContent()).includes('暂无经历支持') && await rows.nth(2).locator('.match-bullet').count() === 0, '缺口项显示暂无经历支持');
  check('no-score-claim', (await page.locator('#workspace-panel-jd .match-table').textContent()).includes('不是 ATS 评分'), '不把覆盖写成 ATS 分数');
  await page.screenshot({path: '/private/tmp/huhua-match-table.png'});
  await rows.nth(1).locator('.match-bullet').click();
  check('click-opens-resume-tab', await page.locator('#workspace-tab-resume').getAttribute('aria-selected') === 'true', '点击后切到写简历');
  await page.waitForFunction(b => document.getElementById('live-sheet').srcdoc.includes('data-located') && document.getElementById('live-sheet').srcdoc.includes('>' + b + '</mark>'), B2);
  check('bullet-highlighted-in-preview', (await page.evaluate(() => document.getElementById('live-sheet').srcdoc.match(/<mark[^>]*>([^<]*)<\/mark>/)[1])) === B2, '预览中只高亮对应那一条');

  // U3 核对页
  await page.locator('#workspace-tab-review').click();
  const review = page.locator('#workspace-panel-review');
  const transferable = review.locator('.review-transferable .review-check');
  check('transferable-listed', await transferable.count() === 1 && (await transferable.textContent()).includes('由「反馈整理项目」经历迁移表达「有数据分析与清洗经验」要求') && (await transferable.textContent()).includes(B2), '可迁移条目说明由 X 经历迁移表达 Y 要求');
  const metric = review.locator('.review-metrics .review-ask');
  check('metric-listed', await metric.count() === 1, '缺数字条目附追问');
  await page.screenshot({path: '/private/tmp/huhua-review-checks.png'});
  await metric.click();
  check('metric-fills-input', (await page.locator('#input').inputValue()).includes('准确率或耗时有什么变化'), '点击把问题填进输入框');
  check('metric-not-sent', streamBodies.length === 0, '填入不自动发送');
  await page.locator('#input').fill('');
  check('hidden-item-not-listed', !(await review.textContent()).includes('被隐藏的一条'), '备用（隐藏）项不进核对列表');

  // U5 追问快捷回复
  const dock = page.locator('#guidance-dock');
  check('questions-above-input', await dock.isVisible() && await dock.locator('.guidance-question-block').count() === 2, '两条未回答追问显示在输入框上方');
  check('options-as-chips', await dock.locator('.guidance-option').count() === 3, '每个选项一个快捷回复');
  const first = await dock.locator('.guidance-option').first();
  await first.click();
  await page.waitForFunction(() => document.getElementById('btn-send').title === '发送');
  check('sends-full-sentence', streamBodies.length === 1 && streamBodies[0].messages[0].content === '关于「反馈分类表是你自己搭建的吗？」：是，我独立完成', '点击后发送带问题的完整句：' + JSON.stringify(streamBodies.map(b => b.messages[0].content)));
  await page.waitForFunction(() => !document.querySelector('#guidance-dock .guidance-question-block'));
  check('answered-questions-gone', await dock.isHidden(), '已发送后追问不再出现');
  await page.reload({waitUntil: 'domcontentloaded'});
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled && document.getElementById('live-sheet').srcdoc.includes('反馈分类表'));
  check('closed-stays-closed-after-reload', await dock.isHidden(), '刷新后已关闭的追问不复现');
  check('no-page-errors', errors.length === 0, errors.join('|'));
  return {passed: checks.length, checks};
}
