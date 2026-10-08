// Run with a disposable static server on :8893. Every business API is mocked;
// this fixture uses synthetic text and never reads accounts or calls a model.
async (page) => {
  const checks = [], errors = [], requests = [];
  const check = (id, passed) => { checks.push({id, passed: Boolean(passed)}); if (!passed) throw new Error(id); };
  await page.unroute('**/api/**'); page.removeAllListeners('pageerror'); page.removeAllListeners('dialog');
  page.on('pageerror', error => errors.push(error.message)); page.on('dialog', dialog => dialog.accept());
  let revisionNumber = 1, bullet = '完成本地 PDF 合并功能', mode = 'ok', generated = 0, previewed = 0;
  const original = bullet;
  const revision = () => String(revisionNumber).padStart(64, '0');
  const workspace = () => ({jd:{}, experiences:{items:[]}, review:{items:[]}, resume:{has_data:true,version:revision()}, suggestions:[{title:'精简表达',detail:'保留本地实现的事实边界。'}], focus:'resume'});
  const current = () => ({has_data:true,data:{basic_info:{name:'虚构测试人'},projects:[{name:'虚构 PDF 工具',description:bullet}]},revision:revision(),stage:'EVALUATING',workspace:workspace()});
  const proposal = (body, id, suggested) => ({suggestion_id:id,revision:revision(),source_text:body.source_text,suggested_text:suggested,reason:'保留个人动作与本地范围',evidence:[{excerpt:body.source_text}],can_apply:true});
  await page.route('**/api/**', async route => {
    const path = '/' + route.request().url().split('/').slice(3).join('/').split('?')[0], method = route.request().method();
    const body = ['POST','PATCH'].includes(method) ? route.request().postDataJSON() : null;
    requests.push({path,method,body});
    if (path === '/api/account/me') return route.fulfill({json:{authenticated:true,account:{id:'fixture',email:'fixture@example.com'},require_account:true,login_available:true}});
    if (path === '/api/resume/current') return route.fulfill({json:current()});
    if (path === '/api/resume/templates') return route.fulfill({json:{templates:[{id:'fixture',name:'测试模板'}]}});
    if (path.startsWith('/api/resume/render/')) return route.fulfill({contentType:'text/html',body:'<!doctype html><html><body>'+bullet+'</body></html>'});
    if (path === '/api/chat/conversations') return route.fulfill({json:{conversations:[{session_id:'generation-fixture',title:'虚构测试',updated_at:'2026-10-05'}]}});
    if (path === '/api/chat/conversations/generation-fixture') return route.fulfill({json:{session_id:'generation-fixture',messages:[],stage:'EVALUATING',workspace:workspace()}});
    if (path.endsWith('/suggestions/generate')) {
      generated++;
      if (mode === 'fail') return route.fulfill({status:503,json:{detail:'改写服务暂时不可用，请稍后重试。'}});
      if (mode === 'conflict') return route.fulfill({status:409,json:{detail:'简历已变化，请载入最新版本'}});
      return route.fulfill({json:proposal(body,'generated-'+generated,'实现本地 PDF 合并功能')});
    }
    if (path.endsWith('/suggestions/preview')) { previewed++; return route.fulfill({json:proposal(body,'preview-'+previewed,body.suggested_text)}); }
    if (path.endsWith('/suggestions/apply')) { revisionNumber++; bullet = body.suggestion_id.startsWith('preview-') ? '开发本地 PDF 合并功能' : '实现本地 PDF 合并功能'; return route.fulfill({json:{change_id:'change-'+revisionNumber,revision:revision()}}); }
    if (path.endsWith('/suggestions/undo')) { revisionNumber++; bullet=original; return route.fulfill({json:{revision:revision()}}); }
    return route.fulfill({status:404,json:{detail:'未使用的模拟接口'}});
  });
  await page.setViewportSize({width:1440,height:960});
  await page.goto('http://127.0.0.1:8893/?session=generation-fixture');
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled && /简历已更新|当前简历已同步/.test(document.getElementById('workspace-status').textContent));
  const open = () => page.getByRole('button',{name:'核对并采用措辞',exact:true}).click();
  const generate = () => page.getByRole('button',{name:'生成改写建议',exact:true});
  const proposed = () => page.getByLabel('拟采用的建议句',{exact:true});
  const apply = () => page.getByRole('button',{name:'采用这句',exact:true});
  const waitForComparison = () => page.locator('.suggestion-comparison:not([hidden])').waitFor();
  await open();
  check('one-unique-source-auto-selected',await page.getByRole('combobox',{name:'当前简历原句',exact:true}).inputValue()===original);
  check('generic-advice-needs-no-user-written-first-draft',await proposed().inputValue()==='');
  await page.getByLabel('改写要求（选填）',{exact:true}).fill('保留本地范围，简化表达');
  await page.evaluate(() => { const b=[...document.querySelectorAll('button')].find(b=>b.textContent==='生成改写建议'); for(let n=0;n<20;n++) b.click(); });
  await waitForComparison();
  check('generate-double-click-once',generated===1);
  const firstGenerate = requests.find(r=>r.path.endsWith('/suggestions/generate'));
  check('generate-bound-to-source-and-revision',firstGenerate.body.source_text===original && firstGenerate.body.expected_revision==='1'.padStart(64,'0') && firstGenerate.body.instruction==='保留本地范围，简化表达');
  check('generated-text-and-evidence-visible',await proposed().inputValue()==='实现本地 PDF 合并功能' && (await page.locator('.suggestion-comparison').textContent()).includes('依据：'+original));
  check('generation-does-not-apply',!requests.some(r=>r.path.endsWith('/suggestions/apply')) && bullet===original);
  await page.locator('.suggestion-comparison').scrollIntoViewIfNeeded();
  await page.screenshot({path:'evaluation/project-review-2026-10-05/suggestion-desktop.png'});
  await page.evaluate(() => refreshCanvas());
  check('same-revision-keeps-generated-candidate',await proposed().inputValue()==='实现本地 PDF 合并功能' && await apply().isEnabled());
  await page.evaluate(() => { const b=[...document.querySelectorAll('button')].find(b=>b.textContent==='采用这句'); for(let n=0;n<20;n++) b.click(); });
  await page.getByRole('button',{name:'撤销本次采用',exact:true}).waitFor();
  check('explicit-adoption-once',requests.filter(r=>r.path.endsWith('/suggestions/apply')).length===1 && bullet==='实现本地 PDF 合并功能');
  await page.getByRole('button',{name:'撤销本次采用',exact:true}).click();
  await page.waitForFunction(() => document.getElementById('live-sheet').srcdoc.includes('完成本地 PDF'));
  check('undo-uses-adopted-revision',requests.find(r=>r.path.endsWith('/suggestions/undo')).body.expected_revision==='2'.padStart(64,'0'));
  await open(); await generate().click(); await waitForComparison();
  await proposed().fill('开发本地 PDF 合并功能');
  check('editing-invalidates-generated-id',await apply().count()===0 && (await page.locator('.suggestion-form [role="status"]').textContent()).includes('核对依据后再采用'));
  await page.evaluate(() => { window.HuhuaWorkspace.setStreaming(true); window.HuhuaWorkspace.setStreaming(false); });
  await page.evaluate(() => refreshCanvas());
  check('same-revision-keeps-manual-draft',await proposed().inputValue()==='开发本地 PDF 合并功能');
  await page.getByRole('button',{name:'核对依据与改动',exact:true}).click(); await waitForComparison(); await apply().click();
  await page.getByRole('button',{name:'撤销本次采用',exact:true}).waitFor();
  check('edited-candidate-rechecked-before-apply',requests.filter(r=>r.path.endsWith('/suggestions/apply')).at(-1).body.suggestion_id==='preview-1' && previewed===1);
  await page.getByRole('button',{name:'撤销本次采用',exact:true}).click();
  await page.waitForFunction(() => document.getElementById('live-sheet').srcdoc.includes('完成本地 PDF'));
  await open(); await generate().click(); await waitForComparison();
  revisionNumber++; bullet='完成本地 PDF 合并功能并运行合成样例';
  await page.evaluate(() => refreshCanvas());
  check('new-revision-preserves-input-but-blocks-old-approval',await proposed().inputValue()==='实现本地 PDF 合并功能' && await generate().isDisabled() && await apply().count()===0);
  await page.getByRole('button',{name:'读取最新原句',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.suggestion-form select')?.value.includes('合成样例'));
  check('reload-latest-source-keeps-draft',await proposed().inputValue()==='实现本地 PDF 合并功能' && await generate().isEnabled());
  mode='fail'; await generate().click();
  await page.getByText('改写服务暂时不可用，请稍后重试。',{exact:true}).waitFor();
  check('failed-generation-preserves-input-and-retry',await proposed().inputValue()==='实现本地 PDF 合并功能' && await generate().isEnabled() && await apply().count()===0);
  mode='conflict'; await generate().click();
  await page.getByRole('button',{name:'读取最新原句',exact:true}).waitFor();
  check('server-conflict-requires-fresh-source',await generate().isDisabled());
  mode='ok'; await page.getByRole('button',{name:'读取最新原句',exact:true}).click();
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b=>b.textContent==='生成改写建议')?.disabled);
  await page.evaluate(() => {
    window.__generationFetch=window.fetch; window.__generationTimeout=window.setTimeout;
    window.setTimeout=(callback,delay,...args)=>window.__generationTimeout(callback,delay===75000?10:delay,...args);
    window.fetch=(url,options)=>String(url).endsWith('/suggestions/generate')
      ? new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}))
      : window.__generationFetch(url,options);
  });
  await generate().click();
  await page.getByText('生成或核对超时，输入内容已保留，请重试。',{exact:true}).waitFor();
  check('timeout-retains-draft-and-enables-retry',await proposed().inputValue()==='实现本地 PDF 合并功能' && await generate().isEnabled());
  await page.evaluate(() => { window.fetch=window.__generationFetch; window.setTimeout=window.__generationTimeout; });
  await page.setViewportSize({width:390,height:844});
  await page.locator('#btn-toggle-canvas').click();
  await proposed().scrollIntoViewIfNeeded();
  check('mobile-form-fits-workspace',await page.evaluate(()=>{const pane=document.getElementById('canvas-pane').getBoundingClientRect();return [...document.querySelectorAll('.suggestion-form select,.suggestion-form textarea,.suggestion-form button')].filter(el=>el.getClientRects().length).every(el=>{const r=el.getBoundingClientRect();return r.left>=pane.left-1&&r.right<=pane.right+1;})&&document.documentElement.scrollWidth<=innerWidth;}));
  await page.screenshot({path:'evaluation/project-review-2026-10-05/suggestion-mobile.png'});
  check('private-suggestion-not-cached',await page.evaluate(()=>![localStorage,sessionStorage].some(storage=>Object.values(storage).some(value=>String(value).includes('实现本地 PDF 合并功能')))));
  await page.evaluate(() => {
    window.__generationFetch=window.fetch;
    window.fetch=(url,options)=>String(url).endsWith('/suggestions/generate')
      ? new Promise(resolve=>{window.__lateGeneration=()=>resolve(new Response(JSON.stringify({suggestion_id:'late-old-session',revision:'6'.padStart(64,'0'),source_text:'完成本地 PDF 合并功能并运行合成样例',suggested_text:'旧对话迟到的候选句',can_apply:true}),{headers:{'Content-Type':'application/json'}}));})
      : window.__generationFetch(url,options);
  });
  await generate().click(); await page.waitForFunction(()=>typeof window.__lateGeneration==='function');
  await page.evaluate(() => { SESSION_ID='other-generation-fixture'; window.HuhuaWorkspace.reset(); window.__lateGeneration(); });
  await page.waitForFunction(()=>!document.querySelector('.suggestion-form'));
  check('late-old-session-response-cannot-leak-candidate',!(await page.locator('#workspace-suggestions').textContent()).includes('旧对话迟到的候选句'));
  await page.evaluate(() => { window.fetch=window.__generationFetch; });
  check('no-browser-errors '+JSON.stringify(errors),errors.length===0);
  return {scope:'Synthetic data; all business APIs mocked; no real model, email, or private database.',checks,errors};
}
