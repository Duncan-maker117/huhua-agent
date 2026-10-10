// Frontend regression against local static assets; all session writes are mocked.
// playwright-cli -s=resume-persistence run-code --filename=tests/resume_persistence.browser.js
async (page) => {
  const checks = [];
  const check = (value, label) => { if (!value) throw new Error(label); checks.push(label); };
  const input = (path) => page.locator(`[data-input-path="${path}"]`);
  const section = (id) => page.locator(`.edit-section[data-section-id="${id}"]`);
  const saved = () => page.waitForFunction(() => document.getElementById('save-status').textContent.startsWith('已保存到当前会话'));
  const order = () => page.locator('.section-drag-handle').evaluateAll((nodes) => nodes.map((node) => node.closest('details').dataset.sectionId));
  const session = 'frontend-persistence-fake';
  const baseUrl = page.url().startsWith('http://127.0.0.1:8877/') ? 'http://127.0.0.1:8877' : 'http://127.0.0.1:8765';
  let canonical = null;
  let counter = 1;
  let revision = String(counter).padStart(64, '0');
  let writes = 0;
  let sampleReads = 0;
  let fail = false;
  let validSession = true;
  let slowStart;
  const slowStarted = new Promise((resolve) => { slowStart = resolve; });
  let activeWrites = 0;
  let peakWrites = 0;
  const writeBodies = [];
  await page.setViewportSize({width: 1440, height: 960});
  page.on('dialog', (dialog) => dialog.accept());
  await page.route('**/api/resume/sample', async (route) => { sampleReads += 1; await route.continue(); });
  await page.route('**/api/resume/current*', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({json: {has_data: validSession && Boolean(canonical), data: validSession ? canonical : null, revision: validSession ? revision : null, can_save: validSession, stage: 'EVALUATING', has_jd: false, match_enabled: false}});
      return;
    }
    const body = route.request().postDataJSON();
    writeBodies.push(body);
    activeWrites += 1;
    peakWrites = Math.max(peakWrites, activeWrites);
    try {
      if (!validSession) { await route.fulfill({status: 404, json: {detail: {code: 'invalid_session', message: '会话已清除，当前草稿未保存。'}}}); return; }
      if (body.resume_data.basic_info.name === '慢速稿') {
        slowStart();
        await page.waitForTimeout(350);
      }
      if (fail) { await route.fulfill({status: 503, json: {detail: {code: 'save_unavailable', message: '模拟保存失败，请重试或下载备份。'}}}); return; }
      if (body.expected_revision !== revision) { await route.fulfill({status: 409, json: {detail: {code: 'revision_conflict', message: '聊天或另一个编辑页已更新简历。', revision}}}); return; }
      canonical = body.resume_data;
      revision = String(++counter).padStart(64, '0');
      writes += 1;
      await route.fulfill({json: {saved: true, revision, data: canonical, stage: 'EVALUATING'}});
    } finally { activeWrites -= 1; }
  });

  await page.route('**/api/account/me', route => route.fulfill({json:{authenticated:false, require_account:false, login_available:false}}));
  await page.goto(`${baseUrl}/resume?session=${session}`);
  await page.getByRole('button', {name: '查看模板样例', exact: true}).waitFor();
  check(sampleReads === 0, '没有个人简历时不自动取样例');
  check(await page.locator('#btn-export').isDisabled(), '选择开始方式前不能导出占位样例');
  await page.getByRole('button', {name: '查看模板样例', exact: true}).click();
  await input('/basic_info/name').waitFor();
  check((await page.locator('#sample-notice').textContent()).includes('未保存到你的会话'), '明确展示样例来源和未保存状态');
  check((await page.locator('#btn-export').textContent()).includes('导出样例'), '样例导出有独立标签');
  await input('/basic_info/name').fill('只在样例中修改');
  await page.waitForTimeout(650);
  check(writes === 0, '样例编辑不会写入个人会话');
  await page.getByRole('button', {name: '新建我的空白草稿', exact: true}).click();
  await saved();
  await input('/basic_info/name').fill('初始稿');
  await saved();
  check(canonical.basic_info.name === '初始稿', '主动新建空白后保存个人内容');

  await input('/basic_info/name').fill('慢速稿');
  await slowStarted;
  await input('/basic_info/name').fill('连续输入的最新稿');
  await saved();
  check(peakWrites === 1, '输入期间保存请求始终串行');
  check(canonical.basic_info.name === '连续输入的最新稿', '较慢保存后继续保存最新输入');
  check(writeBodies.every((body) => body.session_id === session), '每次保存使用同一会话');

  await section('education').getByRole('button', {name: '删除栏目', exact: true}).click();
  await page.getByRole('button', {name: '＋ 添加自定义栏目', exact: true}).click();
  const customId = (await order()).at(-1);
  const customIndex = (await order()).length - 1;
  await input(`/sections/${customIndex}/title`).fill('竞赛记录');
  await input(`/sections/${customIndex}/content`).fill('课程竞赛成果\n本人参与原型设计');
  while ((await order())[0] !== customId) await section(customId).getByRole('button', {name: '上移栏目', exact: true}).click();
  await saved();
  await page.reload();
  await input('/basic_info/name').waitFor();
  check(await input('/basic_info/name').inputValue() === '连续输入的最新稿', '刷新保留已保存文字');
  check((await order())[0] === customId, '刷新保留自定义栏目顺序');
  check(await section('education').count() === 0, '刷新保留栏目删除状态');
  check(await input('/sections/0/content').inputValue() === '课程竞赛成果\n本人参与原型设计', '刷新保留自定义正文');

  canonical.verification_notes = ['项目时间需要核对'];
  revision = String(++counter).padStart(64, '0');
  await page.reload();
  await page.locator('#verification-card').waitFor();
  check((await page.locator('#verification-card').textContent()).includes('仍为待核对草稿'), '待核对草稿提示外显');
  await page.getByRole('button', {name: '已核对，移除此提示', exact: true}).click();
  await saved();
  check(canonical.verification_notes.length === 0, '用户显式逐项核对后才移除提示');

  fail = true;
  await input('/basic_info/name').fill('尚未保存的恢复稿');
  await page.locator('#btn-retry-save').waitFor();
  // 恢复稿刻意只放内存（见 resume-editor.js keepBackup）：不写 sessionStorage/localStorage，避免个人内容落在浏览器存储里。
  check(await page.evaluate(() => ![sessionStorage, localStorage].some((store) => Object.keys(store).some((key) => /draft|backup|recover/i.test(key) || String(store.getItem(key)).includes('尚未保存的恢复稿')))), '保存失败不把草稿写进浏览器存储');
  check(await input('/basic_info/name').inputValue() === '尚未保存的恢复稿', '保存失败后页面仍保留未保存内容');
  check(await page.locator('#btn-download-draft').isVisible(), '保存失败后可下载草稿备份');
  fail = false;
  await page.locator('#btn-retry-save').click();
  await saved();
  check(canonical.basic_info.name === '尚未保存的恢复稿', '重试保存后写入服务器');
  check(await page.locator('#btn-retry-save').isHidden(), '保存成功后隐藏重试入口');

  canonical.basic_info.name = '聊天产生的新版本';
  revision = String(++counter).padStart(64, '0');
  await input('/basic_info/name').fill('旧编辑页的修改');
  await page.locator('#btn-load-latest').waitFor();
  check(canonical.basic_info.name === '聊天产生的新版本', '版本冲突不会覆盖聊天新版本');
  const backupDownload = page.waitForEvent('download');
  await page.locator('#btn-load-latest').click();
  await backupDownload;
  await input('/basic_info/name').waitFor();
  check(await input('/basic_info/name').inputValue() === '聊天产生的新版本', '冲突后先备份再载入最新内容');

  // 导出现在绑定真实会话归属；这里的会话是 mock，所以只拦截 Word 响应，请求载荷仍按真实调用校验。
  await page.route('**/api/resume/export/docx/**', (route) => route.fulfill({
    status: 200, contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    headers: {'Content-Disposition': "attachment; filename*=UTF-8''%E7%AE%80%E5%8E%86.docx"}, body: 'PK\u0003\u0004fixture',
  }));
  await input('/basic_info/name').fill('导出前最后一次修改');
  await page.locator('#btn-export').click();
  const exportRequest = page.waitForRequest((request) => request.url().includes('/api/resume/export/docx/'));
  const exportDownload = page.waitForEvent('download');
  await page.getByRole('button', {name: '通用 Word', exact: true}).click();
  const outgoing = (await exportRequest).postDataJSON();
  await exportDownload;
  check(canonical.basic_info.name === '导出前最后一次修改', '导出先保存最后的输入');
  check(outgoing.basic_info.name === canonical.basic_info.name && outgoing.sections[0].id === customId, '导出和当前会话使用同份文字与栏目');
  validSession = false;
  await input('/basic_info/name').fill('会话删除后的本页草稿');
  await page.locator('#btn-download-draft').waitFor();
  await page.waitForFunction(() => document.getElementById('save-status').textContent.includes('会话已清除'));
  check(await page.evaluate((key) => sessionStorage.getItem(key) === null, 'huhua_editor_draft:' + session), '已删会话404清除自动恢复备份');
  check(await input('/basic_info/name').inputValue() === '会话删除后的本页草稿', '已删会话仍保留本页草稿可手动下载');
  await page.reload();
  await page.getByRole('button', {name: '查看模板样例', exact: true}).waitFor();
  check(await page.getByRole('button', {name: '新建空白草稿', exact: true}).isDisabled(), '已删会话刷新不能复活为空白草稿');
  check(await page.locator('#draft-recovery').isHidden(), '已删会话刷新不提供个人草稿恢复');
  const report = {passed: checks.length, checks, mocked_writes: writes, peak_writes: peakWrites, scope: '独立浏览器；GET/PUT current全部mock，render/sample/Word使用本地API，未访问真实用户会话或模型。'};
  await page.evaluate((value) => { window.__resumePersistenceCheck = value; }, report);
  await page.unroute('**/api/resume/current*');
  await page.unroute('**/api/resume/sample');
  await page.unroute('**/api/resume/export/docx/**');
  return report;
}
