// Run from the repo root after tests/prepare_batch19a_browser.py:
// playwright-cli -s=huhua-19a run-code --filename=tests/batch19a.browser.js
// All requests are fulfilled from local files/synthetic data. No server or model.
async (page) => {
  // run-code has no URL global.
  const URL = function (u) { const m = String(u).match(/^[a-z]+:\/\/([^\/?#]+)([^?#]*)/i); return {hostname: m ? m[1] : '', pathname: (m && m[2]) || '/'}; };
  const checks = [], errors = [], requests = [];
  const check = (name, passed, detail = '') => {
    checks.push({name, passed: Boolean(passed), detail});
    if (!passed) throw new Error(name + ': ' + detail);
  };
  page.on('pageerror', error => errors.push(error.message));
  await page.context().route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.hostname !== 'huhua-19a.test') return route.abort();
    if (url.pathname === '/fixture.json') return route.fulfill({contentType: 'application/json', path: '/private/tmp/huhua-19a-browser-fixture.json'});
    if (url.pathname.startsWith('/static/') && !url.pathname.includes('..')) return route.fulfill({path: 'web/' + decodeURIComponent(url.pathname.slice(8))});
    if (url.pathname === '/chat') return route.fulfill({contentType: 'text/html', path: 'web/index.html'});
    return route.fulfill({status: 404, body: 'fixture route not defined'});
  });
  await page.goto('http://huhua-19a.test/fixture.json');
  const fixture = JSON.parse(await page.locator('body').textContent());
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    requests.push({path, method: route.request().method()});
    if (path === '/api/account/me') return route.fulfill({json: {authenticated: false, require_account: false, login_available: false}});
    if (path === '/api/resume/templates') return route.fulfill({json: {templates: fixture.templates}});
    if (path === '/api/resume/current') return route.fulfill({json: {has_data: true, can_save: true, stage: 'EVALUATING', ...fixture}});
    if (path.startsWith('/api/resume/render/')) return route.fulfill({contentType: 'text/html', body: fixture.html[path.split('/').at(-1)]});
    if (path === '/api/chat/conversations') return route.fulfill({json: {conversations: [{session_id: 'batch19a-fixture', title: '依据演示'}]}});
    if (path.startsWith('/api/chat/conversations/')) return route.fulfill({json: {session_id: 'batch19a-fixture', messages: [], stage: 'EVALUATING', workspace: fixture.workspace}});
    return route.fulfill({status: 503, json: {detail: '未使用的合成接口'}});
  });
  await page.setViewportSize({width: 1440, height: 960});
  await page.goto('http://huhua-19a.test/chat?session=batch19a-fixture');
  const card = page.locator('#evidence-card');
  const field = index => page.frameLocator('#live-sheet').locator(`[data-field-path="/projects/0/polished_bullets/${index}"]`);
  const sheet = () => page.locator('#live-sheet').evaluate(el => { const b = el.getBoundingClientRect(); return {x: b.left, y: b.top, scale: b.width / el.clientWidth}; });
  // The sheet iframe is CSS-scaled and Playwright mis-hit-tests inside it. Map the span's rect to the
  // screen and use a real mouse click, which also exercises the iframe -> parent focus change.
  const tap = async index => {
    // The bridge marks a field clickable only after describe -> ready -> state.
    await field(index).and(page.frameLocator('#live-sheet').locator('[data-evidence-state]')).waitFor();
    const r = await field(index).evaluate(el => { const b = el.getBoundingClientRect(); return {x: b.left + 4, y: (b.top + b.bottom) / 2}; });
    const frame = await sheet();
    await page.mouse.click(frame.x + r.x * frame.scale, frame.y + r.y * frame.scale);
  };
  await page.waitForFunction(() => document.getElementById('evidence-toggle').getAttribute('aria-pressed') === 'true');
  await tap(0);
  await card.waitFor({state: 'visible'});
  check('original-quote', (await card.textContent()).includes('我整理了反馈'));
  await page.waitForTimeout(300);
  check('card-survives-focus-return', await card.isVisible());
  const bounds = await card.boundingBox(), frame = await sheet();
  const r = await field(0).evaluate(el => el.getBoundingClientRect().toJSON());
  const anchor = {x: frame.x + r.left * frame.scale, y: frame.y + r.top * frame.scale, width: r.width * frame.scale, height: r.height * frame.scale};
  check('desktop-card-inside-viewport', bounds.x >= 0 && bounds.x + bounds.width <= 1440 && bounds.y >= 0 && bounds.y + bounds.height <= 960);
  check('desktop-card-does-not-cover-bullet', bounds.y >= anchor.y + anchor.height || bounds.y + bounds.height <= anchor.y || bounds.x >= anchor.x + anchor.width);
  await page.screenshot({path: '/private/tmp/huhua-19a-1440.png', fullPage: true});
  await page.keyboard.press('Escape');
  check('escape-focus', await card.isHidden() && await page.locator('#live-sheet').evaluate(el => el === document.activeElement));
  await page.locator('#input').fill('保留草稿');
  await tap(1); await card.getByText('你后来更正过这里的说法').waitFor({timeout: 5000}).catch(() => {});
  check('pending-explanation', (await card.textContent()).includes('你后来更正过这里的说法'));
  await card.getByRole('button', {name: '回答这个问题'}).click();
  check('prefill-preserves-draft', (await page.locator('#input').inputValue()).startsWith('保留草稿\n'));
  check('no-message-sent', !requests.some(row => row.path === '/api/chat/stream'));
  const previousFrame = await page.locator('#live-sheet').elementHandle();
  await page.locator('#tpl-rail button').nth(1).click();
  await page.waitForFunction(previous => previous.id === 'live-sheet-back', previousFrame);
  await field(1).waitFor();
  await tap(1); await card.waitFor({state: 'visible'});
  check('template-switch-keeps-evidence', (await card.textContent()).includes('一共验证了多少种情况'));
  await page.keyboard.press('Escape');
  await page.locator('#evidence-toggle').click();
  await tap(1); check('disabled-click', await card.isHidden());
  await page.locator('#evidence-toggle').click();
  await page.setViewportSize({width: 390, height: 844});
  await page.locator('#btn-toggle-canvas').click();
  await page.locator('#workspace-tab-resume').click();
  await tap(1); await card.waitFor({state: 'visible'});
  const mobile = await card.boundingBox();
  check('mobile-bottom-sheet', Math.abs(mobile.y + mobile.height - 844) < 2 && mobile.height <= 844 * .7 + 1 && mobile.width <= 390);
  check('no-horizontal-overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({path: '/private/tmp/huhua-19a-390.png', fullPage: true});
  await page.keyboard.press('Escape');
  check('mobile-escape-keeps-workspace', await page.locator('#canvas-pane').isVisible());
  await page.emulateMedia({media: 'print'});
  check('print-no-marker', await field(1).evaluate(el => getComputedStyle(el).textDecorationLine === 'none'));
  check('print-no-toolbar', await page.locator('#evidence-bar').isHidden());
  await page.emulateMedia({media: 'screen'});
  check('no-page-errors', errors.length === 0, JSON.stringify(errors));
  return {scope: '合成会话与真实模板；没有调用模型或后端服务', checks, errors};
}
