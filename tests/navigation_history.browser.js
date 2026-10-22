// Run in a fresh Playwright context. All APIs are synthetic; no live server,
// account store, model, or external service is contacted. Works in WebKit too.
// playwright-cli -s=huhua-navigation open about:blank --browser=webkit
// playwright-cli -s=huhua-navigation run-code --filename=tests/navigation_history.browser.js
async (page) => {
  const origin = 'https://huhua-history.fixture', checks = [], errors = [];
  const check = (value, label) => { if (!value) throw new Error(label); checks.push(label); };
  let number = 1, current = {has_data:false,stage:'JD_INPUT'};
  const conversation = () => ({session_id:'synthetic-history-' + number,title:'导航测试',messages:[],stage:current.stage});
  const templates = [{id:'fixture-a',name:'模板 A'}, {id:'fixture-b',name:'模板 B'}];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.route('**/*', async route => {
    const url = route.request().url(), path = url.slice(origin.length).split('?')[0];
    if (!url.startsWith(origin + '/')) return route.fulfill({body:'',contentType:'text/css'});
    if (path === '/') return route.fulfill({path:'web/home.html'});
    if (path === '/chat') return route.fulfill({path:'web/index.html'});
    if (path === '/resume') return route.fulfill({path:'web/resume.html'});
    if (path.startsWith('/static/')) return route.fulfill({path:'web/' + path.slice(8)});
    if (path === '/api/account/me') return route.fulfill({json:{authenticated:false,require_account:false,login_available:false}});
    if (path === '/api/chat/conversations') {
      if (route.request().method() === 'POST') {
        if (!route.request().postDataJSON()?.session_id) number++;
        return route.fulfill({json:conversation()});
      }
      return route.fulfill({json:{conversations:[conversation()]}});
    }
    if (path.startsWith('/api/chat/conversations/')) return route.fulfill({json:conversation()});
    if (path === '/api/resume/templates') return route.fulfill({json:{templates}});
    if (path === '/api/resume/current') return route.fulfill({json:current});
    if (path.startsWith('/api/resume/render/')) return route.fulfill({contentType:'text/html',body:`<!doctype html><html><body><p>${current.revision} ${path.split('/').at(-1)}</p></body></html>`});
    return route.fulfill({status:404,json:{detail:'Unused synthetic route'}});
  });
  await page.setViewportSize({width:390,height:844});
  await page.goto(origin + '/');
  await page.locator('a[href="/chat"]:visible').first().click();
  await page.waitForURL(url => url.pathname === '/chat');
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled);
  const historyAtEntry = await page.evaluate(() => history.length);
  for (let i = 0; i < 4; i++) await page.evaluate(() => refreshCanvas());
  check(await page.evaluate(() => history.length) === historyAtEntry, 'first-use empty preview refreshes do not add Back steps');

  for (let revision = 1; revision <= 3; revision++) {
    current = {has_data:true,stage:'EVALUATING',revision:'revision-' + revision,
      data:{basic_info:{name:'虚构导航测试'},education:[],work_experience:[],projects:[],skills:[],sections:[]}};
    await page.evaluate(() => refreshCanvas());
    await page.waitForFunction(value => document.getElementById('live-sheet').srcdoc.includes(value), current.revision);
  }
  await page.waitForFunction(() => document.getElementById('resume-editor-frame'));
  const editor = page.frameLocator('#resume-editor-frame');
  await editor.locator('#template-list .tpl-item').first().waitFor({state:'attached'});
  for (const id of ['fixture-b', 'fixture-a', 'fixture-b']) {
    await page.locator('#tpl-rail .tpl-chip[data-id="' + id + '"]').evaluate(button => button.click());
    await page.waitForFunction(value => document.getElementById('live-sheet').srcdoc.includes(value), id);
  }
  // The editor is preloaded while hidden. Its own double-buffered frames must
  // not add invisible history either, including after switching templates.
  for (const index of [1, 0, 1]) {
    await editor.locator('#template-list .tpl-item').nth(index).evaluate(button => button.click());
    await editor.locator('#preview-frame').evaluate((frame, value) => new Promise((resolve, reject) => {
      const expires = performance.now() + 10000;
      const poll = () => {
        const active = document.getElementById('preview-frame');
        if (active.srcdoc.includes(value)) resolve();
        else if (performance.now() > expires) reject(new Error('Nested preview did not refresh'));
        else setTimeout(poll, 20);
      };
      poll();
    }), templates[index].id);
  }
  check(await page.evaluate(() => history.length) === historyAtEntry, 'revisions and both main/embedded template buffers preserve history length');
  current = {has_data:false,stage:'JD_INPUT'};
  await page.locator('#btn-new-chat').click();
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled && !document.getElementById('live-sheet').srcdoc);
  check(await page.evaluate(() => history.length) === historyAtEntry, 'starting a new conversation clears previews without extra history');
  await page.evaluate(() => history.back());
  await page.waitForURL(origin + '/');
  check(page.url() === origin + '/', 'one browser Back returns to the home page');
  check(errors.length === 0, 'no page script errors: ' + errors.join('; '));
  return {checks,errors,historyAtEntry};
}
