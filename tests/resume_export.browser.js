// Run against the disposable fixture: .venv/bin/python tests/product_live_server.py --port 8765 (needs the /__test__/otp mailbox).
async (page) => {
  const origin = 'http://127.0.0.1:8765';
  const checks = [];
  const check = (ok, label) => { checks.push({label, passed: Boolean(ok)}); if (!ok) throw new Error(label); };
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin + '/chat');
  const email = 'export-' + Date.now() + '@huhua-fixture.invalid';
  check((await page.request.post(origin + '/api/account/login/start', {data: {email}})).ok(), 'fixture login starts');
  const {code} = await (await page.request.get(origin + '/__test__/otp?email=' + encodeURIComponent(email))).json();
  check((await page.request.post(origin + '/api/account/login/verify', {data: {email, code}})).ok(), 'fixture account authenticated');
  const sessions = [];
  for (let i = 0; i < 2; i++) {
    const {session_id} = await (await page.request.post(origin + '/api/chat/conversations', {data: {}})).json();
    sessions.push(session_id);
    const current = await (await page.request.get(origin + '/api/resume/current?session_id=' + session_id)).json();
    check((await page.request.put(origin + '/api/resume/current', {data: {session_id, expected_revision: current.revision, resume_data: {basic_info: {name: '虚构导出测试'}, projects: [{name: '课程项目', description: '完成了静态原型，尚未上线。'}]}}})).ok(), 'fixture resume saved ' + i);
  }
  const settled = () => page.waitForFunction(() => document.getElementById('render-status').textContent === '已实时更新');
  const go = async session => { await page.goto(origin + '/resume?session=' + session); await settled(); };
  await go(sessions[0]);
  await page.locator('.tpl-item').nth(3).click(); await settled();
  const selected = await page.locator('.tpl-item.active').getAttribute('data-template-id');
  await page.reload(); await settled();
  check(await page.locator('.tpl-item.active').getAttribute('data-template-id') === selected, 'selected template survives reload');
  await go(sessions[1]);
  check(await page.locator('.tpl-item.active').getAttribute('data-template-id') !== selected, 'another conversation has separate template preference');
  await page.locator('.tpl-item').nth(1).click(); await settled();
  await go(sessions[0]);
  check(await page.locator('.tpl-item.active').getAttribute('data-template-id') === selected, 'returning to a conversation restores its preference');

  const requests = [];
  page.on('request', request => { if (request.url().includes('/api/resume/current') && request.method() === 'PUT') requests.push('save'); if (request.url().includes('/api/resume/export/')) requests.push('export'); });
  await page.locator('[data-input-path="/basic_info/name"]').fill('最新保存导出');
  await page.locator('#btn-export').click();
  const pdfDownload = page.waitForEvent('download');
  await page.locator('.export-opt[data-format="pdf"]').click();
  const pdf = await pdfDownload;
  await pdf.saveAs('/private/tmp/huhua-browser-export.pdf');
  check(pdf.suggestedFilename().endsWith('.pdf') && pdf.suggestedFilename().includes('最新保存导出'), 'real PDF downloaded with current saved name');
  check(requests.indexOf('save') >= 0 && requests.indexOf('save') < requests.indexOf('export'), 'pending edits save before export');
  check(await page.locator('#export-download').isVisible(), 'download remains available after automatic attempt');
  await page.waitForTimeout(1200);
  const retryDownload = page.waitForEvent('download');
  await page.locator('#export-download').click();
  check((await retryDownload).suggestedFilename() === pdf.suggestedFilename(), 'explicit PDF download works after former blob expiry');
  await page.locator('#btn-export').click();
  const wordDownload = page.waitForEvent('download');
  await page.locator('.export-opt[data-format="docx"]').click();
  const word = await wordDownload; await word.saveAs('/private/tmp/huhua-browser-export.docx');
  check(word.suggestedFilename().endsWith('.docx'), 'real Word file downloaded');

  let failed = true;
  await page.route('**/api/resume/export/pdf/**', route => failed ? route.fulfill({status: 503, json: {detail: {message: 'PDF 生成暂时失败，稍后重试。'}}}) : route.continue());
  await page.locator('#btn-export').click(); await page.locator('.export-opt[data-format="pdf"]').click();
  await page.locator('#btn-retry-export').waitFor();
  check((await page.locator('#export-status').textContent()).includes('PDF 生成暂时失败'), 'backend failure remains visible separately from preview');
  check(await page.locator('[data-input-path="/basic_info/name"]').inputValue() === '最新保存导出', 'failed export preserves editor contents');
  failed = false;
  const retried = page.waitForEvent('download'); await page.locator('#btn-retry-export').click(); await retried;
  check(await page.locator('#btn-retry-export').isHidden(), 'retry produces downloadable PDF');

  // Simulate headers arriving while the file body stalls. Accelerating only
  // the export deadline makes this a regression for response-body timeouts.
  await page.evaluate(() => {
    window.__realExportFetch = window.fetch; window.__realExportTimer = window.setTimeout;
    window.setTimeout = (callback, delay, ...args) => window.__realExportTimer(callback, delay === 60000 ? 100 : delay, ...args);
    window.fetch = (url, options) => String(url).includes('/api/resume/export/')
      ? Promise.resolve({ok: true, headers: new Headers(), blob: () => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Request aborted', 'AbortError')), {once: true}))})
      : window.__realExportFetch(url, options);
  });
  await page.locator('#btn-export').click(); await page.locator('.export-opt[data-format="pdf"]').click();
  await page.locator('#btn-retry-export').waitFor();
  check((await page.locator('#export-status').textContent()).includes('等待超时'), 'stalled file response body reaches timeout and retry');
  check(await page.locator('#btn-export').isEnabled(), 'timeout releases export controls');
  await page.evaluate(() => { window.fetch = window.__realExportFetch; window.setTimeout = window.__realExportTimer; });

  await page.route('**/api/resume/current', route => route.request().method() === 'PUT' ? route.fulfill({status: 503, json: {detail: {message: '测试保存失败'}}}) : route.continue());
  await page.locator('[data-input-path="/basic_info/name"]').fill('未保存修改');
  await page.locator('#btn-export').click(); const before = requests.filter(x => x === 'export').length;
  await page.locator('.export-opt[data-format="pdf"]').click(); await page.locator('#btn-retry-export').waitFor();
  check(requests.filter(x => x === 'export').length === before, 'save failure prevents export of stale resume');
  check((await page.locator('#export-status').textContent()).includes('尚未保存'), 'save failure explains how to recover');
  check(errors.length === 0, 'no browser page errors');
  await page.evaluate(results => { window.__resumeExportChecks = results; }, checks);
  return {checks, pageErrors: errors};
}
