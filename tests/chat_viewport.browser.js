// WebKit/iPhone layout regression. APIs are synthetic; no server or model.
// Toolbar/keyboard geometry is simulated: this is not a physical iOS keyboard test.
// playwright-cli -s=huhua-mobile-fix open about:blank --browser=webkit --device='iPhone 13'
// playwright-cli -s=huhua-mobile-fix run-code --filename=tests/chat_viewport.browser.js
async (page) => {
  const origin = 'https://huhua-mobile.fixture', checks = [], errors = [], requests = [];
  let longWelcome = false;
  const check = (value, label) => { if (!value) throw new Error(label); checks.push(label); };
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.route('**/*', async route => {
    const request = route.request(), path = request.url().slice(origin.length).split('?')[0];
    if (!request.url().startsWith(origin + '/')) throw new Error('Unexpected external request: ' + request.url());
    if (path === '/chat') return route.fulfill({path: 'web/index.html'});
    if (path.startsWith('/static/')) return route.fulfill({path: 'web/' + path.slice(8)});
    requests.push(path);
    const current = {has_data: false, data: null, stage: 'COLLECTING', revision: '0'};
    if (path === '/api/account/me') return route.fulfill({json: {authenticated: false, require_account: true,
      guest_allowed: true, guest_retention_hours: 24, login_available: true}});
    if (path === '/api/chat/agent-mode') return route.fulfill({json: {agent_mode: 'loop'}});
    if (path === '/api/resume/templates') return route.fulfill({json: {templates: []}});
    if (path === '/api/resume/current') return route.fulfill({json: current});
    if (path.startsWith('/api/chat/conversations')) return route.fulfill({json: {
      ...current, session_id: 'mobile-fixture', title: '新对话', messages: longWelcome ? [
        {role: 'assistant', content: ('你的原话决定能写什么。\n\n- 说说你做过的项目和真实分工。\n- 没有上线就不写成上线。\n\n').repeat(12)},
      ] : [],
    }});
    return route.fulfill({status: 404, json: {detail: 'Unused fixture API'}});
  });
  await page.addInitScript(() => {
    if (window !== window.top) return;
    const viewport = window.visualViewport;
    const geometry = {height: 660, offsetTop: 0, scale: 1};
    for (const key of Object.keys(geometry)) Object.defineProperty(viewport, key, {configurable: true, get: () => geometry[key]});
    window.setTestViewport = values => {
      Object.assign(geometry, values);
      viewport.dispatchEvent(new Event('resize'));
      viewport.dispatchEvent(new Event('scroll'));
    };
  });
  const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const visibleComposer = async label => {
    await settle();
    const result = await page.evaluate(() => {
      const viewport = visualViewport, top = viewport.offsetTop, bottom = top + viewport.height;
      const boxes = ['input', 'btn-send'].map(id => {
        const node = document.getElementById(id), rect = node.getBoundingClientRect();
        const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
        return {id, top: rect.top, bottom: rect.bottom, height: rect.height,
          visible: rect.top >= top && rect.bottom <= bottom + 1 && rect.height >= 36,
          clickable: hit === node || node.contains(hit)};
      });
      return {top, bottom, boxes, bodyHeight: document.body.getBoundingClientRect().height,
        horizontal: document.documentElement.scrollWidth <= innerWidth + 1};
    });
    check(result.boxes.every(box => box.visible && box.clickable) && result.horizontal, label + ': ' + JSON.stringify(result));
  };
  await page.setViewportSize({width: 390, height: 844});
  await page.goto(origin + '/chat');
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled);
  await visibleComposer('首次空态：工具栏展开时输入和发送可见可点');
  await page.screenshot({path: '/tmp/huhua-mobile-first-use.png', clip: {x: 0, y: 0, width: 390, height: 660}});
  check(await page.locator('#input').evaluate(node => parseFloat(getComputedStyle(node).fontSize) >= 16), '输入字号避免 iOS 聚焦自动缩放');
  longWelcome = true;
  await page.reload();
  await page.waitForFunction(() => document.querySelectorAll('#messages .bubble-ai').length > 0);
  await visibleComposer('长欢迎消息：输入仍常驻底部');
  await page.locator('#input').tap();
  check(await page.locator('#input').evaluate(node => node === document.activeElement), '直接点击可聚焦输入');
  await page.locator('#input').fill('尚未发送的经历补充');
  await page.evaluate(() => setTestViewport({height: 350, offsetTop: 96}));
  await visibleComposer('键盘弹出及视口平移：输入和发送仍可点');
  await page.locator('#input').fill('多行经历补充\n'.repeat(24));
  await visibleComposer('多行输入不会挤掉发送按钮');
  await page.evaluate(() => {
    const dock = document.getElementById('guidance-dock');
    dock.hidden = false;
    dock.innerHTML = '<h2>补充真实分工</h2><textarea class="ask-text" aria-label="分工补充"></textarea>' + '<p>待核对的事实和问题</p>'.repeat(60);
  });
  await visibleComposer('长问题卡与键盘共存：问题卡内部滚动，输入不被挤走');
  check(await page.locator('#guidance-dock').evaluate(node => node.scrollHeight > node.clientHeight && node.clientHeight > 0), '问题卡可内部滚动');
  check(await page.locator('.ask-text').evaluate(node => parseFloat(getComputedStyle(node).fontSize) >= 16), '问题卡输入字号同样避免聚焦缩放');
  await page.evaluate(() => { document.getElementById('guidance-dock').hidden = true; document.getElementById('messages').scrollTop = 180; });
  await page.locator('#input').fill('保留草稿');
  await settle();
  const readingPosition = await page.locator('#messages').evaluate(node => node.scrollTop);
  await page.evaluate(() => setTestViewport({height: 660, offsetTop: 0}));
  await visibleComposer('键盘收起恢复底部输入');
  check(await page.locator('#input').inputValue() === '保留草稿', '视口变化保留输入草稿');
  check(await page.locator('#messages').evaluate(node => node.scrollTop) === readingPosition, '收起键盘不强制跳到聊天底部');
  await page.screenshot({path: '/tmp/huhua-mobile-long-welcome.png', clip: {x: 0, y: 0, width: 390, height: 660}});
  await page.evaluate(() => setTestViewport({height: 550, offsetTop: 0}));
  await visibleComposer('浏览器工具栏变化后仍常驻底部');
  const previousHeight = await page.locator('body').evaluate(node => node.getBoundingClientRect().height);
  await page.evaluate(() => setTestViewport({height: 260, offsetTop: 30, scale: 2}));
  await settle();
  check(await page.locator('body').evaluate(node => node.getBoundingClientRect().height) === previousHeight, '手动双指缩放不触发工作台重排');
  await page.setViewportSize({width: 844, height: 390});
  await page.evaluate(() => setTestViewport({height: 350, offsetTop: 0, scale: 1}));
  await visibleComposer('手机横屏输入与发送可达');
  await page.setViewportSize({width: 1440, height: 960});
  await page.evaluate(() => setTestViewport({height: 960, offsetTop: 0}));
  await visibleComposer('桌面输入位置正常');
  check(await page.locator('#canvas-pane').isVisible(), '桌面双栏预览保留');
  check(errors.length === 0, '无页面脚本异常：' + errors.join('; '));
  check(!requests.includes('/api/chat/stream'), '未调用生成模型或发送真实聊天');
  await page.locator('#input').fill('');
  return {scope: 'All APIs mocked; toolbar/keyboard geometry simulated.', checks, errors};
}
