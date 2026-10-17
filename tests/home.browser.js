// Synthetic public page fixture; no server, user store or model is contacted.
// playwright-cli -s=huhua-home run-code --filename=tests/home.browser.js
async (page) => {
  const origin = 'https://huhua.fixture';
  const errors = [], requests = [], checks = [];
  let authenticated = false;
  const check = (value, label) => { if (!value) throw new Error(label); checks.push(label); };
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const url = route.request().url(); requests.push(url);
    if (!url.startsWith(origin + '/')) throw new Error('External resource: ' + url);
    const path = url.slice(origin.length).split('?')[0];
    if (path === '/') return route.fulfill({path: 'web/home.html'});
    if (path.startsWith('/static/')) return route.fulfill({path: 'web/' + path.slice(8)});
    if (path === '/api/account/me') return route.fulfill({json: {authenticated, login_available: true}});
    return route.fulfill({status: 404, body: ''});
  });
  await page.addInitScript(() => {
    window.copiedCommand = '';
    Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async value => { window.copiedCommand = value; }}});
  });
  const loadPictures = async () => {
    for (const img of await page.locator('img').all()) {
      if (!await img.isVisible()) continue;
      await img.scrollIntoViewIfNeeded();
      await img.evaluate(node => node.decode());
    }
    await page.locator('.template-strip').evaluate(node => { node.scrollLeft = 0; });
    await page.evaluate(() => scrollTo({top: 0, behavior: 'instant'}));
  };
  await page.setViewportSize({width: 1440, height: 1000});
  await page.goto(origin);
  await page.locator('#nav-account').filter({hasText: '登录'}).waitFor();
  await page.evaluate(() => Promise.all([...document.images].filter(img => img.loading !== 'lazy').map(img => img.decode())));
  check(await page.locator('h1').innerText() === '把聊过的经历，\n写成一页真实的简历。', '方案 A 标题');
  check(await page.locator('#nav-mcp').isVisible(), '桌面 MCP 入口可见');
  check(await page.locator('#nav-mcp').getAttribute('href') === '/connect', 'MCP 入口链接');
  check(await page.locator('#preview-panel-chat').isVisible(), '默认对话展示');
  await page.locator('#preview-tab-editor').click();
  check(await page.locator('#preview-panel-editor').isVisible(), '点击编辑标签切换图片');
  check((await page.locator('#preview-caption').innerText()).startsWith('从聊过的经历'), '编辑说明');
  await page.keyboard.press('ArrowRight');
  check(await page.locator('#preview-tab-chat').getAttribute('aria-selected') === 'true', '向右循环切换');
  check(await page.locator('#preview-tab-chat').evaluate(n => n === document.activeElement), '键盘切换焦点');
  await page.keyboard.press('ArrowLeft');
  check(await page.locator('#preview-panel-editor').isVisible(), '向左循环切换');
  await page.locator('#preview-tab-chat').click();
  await loadPictures();
  await page.screenshot({path: '/private/tmp/huhua-home-desktop-hero.png'});
  await page.screenshot({path: '/private/tmp/huhua-home-desktop.png', fullPage: true});
  await page.locator('#copy-command').click();
  check(await page.locator('#copy-command').innerText() === '已复制', '复制反馈');
  check(await page.evaluate(() => copiedCommand.includes('https://huhua.fixture/mcp')), '命令使用当前站点');
  check(await page.locator('.mcp-steps > li').count() === 3, 'MCP 三步接入');
  check(await page.locator('.mcp-task').count() === 3, 'MCP 三个任务');
  for (const task of ['tailor', 'project', 'check']) {
    const example = await page.locator('#mcp-task-' + task).innerText();
    await page.locator('#copy-task-' + task).click();
    check(await page.evaluate(() => copiedCommand) === example, task + ' 示例复制内容');
    check(await page.locator('#copy-task-' + task).innerText() === '已复制', task + ' 示例复制反馈');
  }
  await page.locator('#privacy summary').click();
  check(await page.locator('#privacy').evaluate(node => node.open), 'FAQ 可展开');
  await page.setViewportSize({width: 390, height: 844});
  await page.goto(origin);
  await loadPictures();
  await page.screenshot({path: '/private/tmp/huhua-home-mobile-hero.png'});
  await page.screenshot({path: '/private/tmp/huhua-home-mobile.png', fullPage: true});
  check(await page.evaluate(() => document.documentElement.scrollWidth === innerWidth), '390px 无页面横向溢出');
  check(await page.locator('#mcp').evaluate(node => node.scrollWidth <= node.clientWidth), '390px MCP 卡片无横向溢出');
  await page.locator('#mcp').screenshot({path: '/private/tmp/huhua-ui2-mcp-mobile.png'});
  await page.locator('#menu-toggle').click();
  check(await page.locator('#menu-toggle').getAttribute('aria-expanded') === 'true', '移动导航展开');
  check(await page.locator('#nav-mcp').isVisible(), '移动端 MCP 入口可达');
  await page.keyboard.press('Escape');
  check(await page.locator('#menu-toggle').getAttribute('aria-expanded') === 'false', 'Escape 关闭菜单');
  const crops = await page.locator('.template-image').evaluateAll(nodes => nodes.map(node => ({
    ratio: node.clientWidth / node.clientHeight,
    fit: getComputedStyle(node.querySelector('img')).objectFit,
    position: getComputedStyle(node.querySelector('img')).objectPosition,
  })));
  check(crops.length === 7 && crops.every(crop => crop.ratio > 1.10 && crop.fit === 'cover' && crop.position.includes('0%')), '7 张模板裁掉底部提示条');
  authenticated = true;
  await page.setViewportSize({width: 1440, height: 1000});
  await page.goto(origin);
  await page.locator('#nav-account').filter({hasText: '我的档案'}).waitFor();
  check(await page.locator('#nav-workspace-label').innerText() === '进入工作台', '登录态导航');
  check(await page.locator('#nav-account').getAttribute('href') === '/chat?panel=profile', '档案链接');
  await page.emulateMedia({reducedMotion: 'reduce'});
  check(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior) === 'auto', '减少动态效果偏好');
  check(errors.length === 0, '无浏览器脚本异常');
  check(requests.every(url => url.startsWith(origin)), '页面无外部资源请求');
  console.log(JSON.stringify({checks, errors}));
  return {checks, errors};
}
