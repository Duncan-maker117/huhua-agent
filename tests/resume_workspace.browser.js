// Disposable browser fixture. All business APIs and SSE use synthetic data.
async (page) => {
  page.removeAllListeners('dialog');
  page.on('dialog', dialog => dialog.accept());
  const checks = [], errors = [];
  const check = (id, value, detail) => {
    checks.push({id, passed: Boolean(value), detail});
    if (!value) throw new Error(id + ': ' + detail);
  };
  const checkChatLayout = async label => {
    const layout = await page.evaluate(() => {
      const pane = document.getElementById('chat-pane').getBoundingClientRect();
      const body = document.getElementById('chat-body');
      const children = ['messages', 'guidance-dock', 'composer-wrap'].map(id => {
        const element = document.getElementById(id), rect = element.getBoundingClientRect();
        return {id, visible: !!element.getClientRects().length, left: rect.left, right: rect.right};
      });
      return {left: pane.left, right: pane.right, clientWidth: body.clientWidth, scrollWidth: body.scrollWidth, scrollLeft: body.scrollLeft, children};
    });
    check('chat-bounds-' + label, layout.scrollLeft === 0 && layout.scrollWidth <= layout.clientWidth + 1 && layout.children.every(rect => !rect.visible || (rect.left >= layout.left - 1 && rect.right <= layout.right + 1)), JSON.stringify(layout));
  };
  let session = 'workspace-fixture', renderFails = false, initialHistory = true;
  const jdWorkspace = {
    jd: {info: {job_title: 'AI 产品实习生', company: '虚构测试公司', hard_requirements: ['2027 届毕业生'], required_skills: ['需求分析'], preferred_qualities: ['有作品更佳'], summary: '岗位重点是把需求转成可验证的方案。', decoded_items: [{keyword:'需求分析',surface_meaning:'梳理用户需求',real_meaning:'需要说明问题来源、判断过程和交付结果'}], requirement_evidence: [{text: '独立完成需求文档', source_quote: '负责需求梳理和文档编写'}]}, keywords: ['Agent'], raw_text: '虚构 JD：负责需求梳理和文档编写'},
    experiences: {items: []}, resume: {has_data: false, version: 'empty'}, review: {items: []},
    guidance: {title: '待你补充', question: '你想先整理哪段经历？', why: '先选一段最能说明实际工作的经历。', options: [{label: '项目经历', value: '我想先整理一段项目经历。'}, {label: '实习经历', value: '我想先整理一段实习经历。'}], allow_free_text: true},
    suggestions: [{title: '先说明个人贡献', detail: '项目经历中先写你实际负责的动作。'}], focus: 'jd',
  };
  let workspace = jdWorkspace;
  let current = {has_data: false, stage: 'COLLECTING', workspace};
  page.removeAllListeners('pageerror');
  page.on('pageerror', error => errors.push(error.message));
  await page.unroute('**/api/**');
  await page.unroute('**/fonts.googleapis.com/**');
  await page.unroute('**/fonts.gstatic.com/**');
  await page.route('**/fonts.googleapis.com/**', route => route.abort());
  await page.route('**/fonts.gstatic.com/**', route => route.abort());
  await page.route('**/api/**', async route => {
    const path = '/' + route.request().url().split('/').slice(3).join('/').split('?')[0], method = route.request().method();
    if (path === '/api/resume/templates') return route.fulfill({json:{templates:[{id:'t001-jianyue',name:'简单单栏'}]}});
    if (path === '/api/resume/current') return route.fulfill({json: current});
    if (path.startsWith('/api/resume/render/')) {
      if (renderFails) return route.fulfill({status:503, body:'模拟渲染失败'});
      const data = route.request().postDataJSON();
      return route.fulfill({contentType:'text/html',body:'<!doctype html><html><body><h1>虚构测试简历</h1><p>' + data.projects[0].bullets[0] + '</p></body></html>'});
    }
    if (path === '/api/chat/conversations' && method === 'POST') {
      const migrating = route.request().postDataJSON().session_id;
      if (migrating) return route.fulfill({json:{session_id:migrating,title:'迁移测试',messages:[]}});
      session = 'workspace-empty-fixture';
      workspace = {jd:{}, experiences:{items:[]}, resume:{has_data:false}, guidance:null, suggestions:[], review:{items:[]}, focus:'jd'};
      current = {has_data:false, stage:'JD_INPUT', workspace};
      return route.fulfill({json:{session_id:session,title:'新对话',messages:[],workspace}});
    }
    if (path === '/api/chat/conversations') return route.fulfill({json:{conversations:[{session_id:session,title:'工作区测试',updated_at:'2026-10-04T00:00:00Z'}]}});
    if (path.startsWith('/api/chat/conversations/')) {
      const messages = initialHistory ? [] : await page.evaluate(id => chatBackups.get(id) || [], session);
      initialHistory = false;
      return route.fulfill({json:{session_id:session,title:'工作区测试',messages,stage:current.stage,workspace}});
    }
    return route.fulfill({status:503,json:{detail:'未使用的模拟接口'}});
  });
  await page.setViewportSize({width:1440,height:960});
  await page.route('**/api/account/me', route => route.fulfill({json:{authenticated:false, require_account:false, login_available:false}}));
  await page.goto('http://127.0.0.1:8765/chat?session=workspace-fixture', {waitUntil:'domcontentloaded'});
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled);
  await page.waitForFunction(() => document.getElementById('workspace-panel-jd').textContent.includes('AI 产品实习生'));
  check('jd-without-resume', await page.locator('#workspace-panel-jd').isVisible(), '尚无简历时，JD 解析直接展示在工作区');
  check('jd-evidence', (await page.locator('#workspace-panel-jd').textContent()).includes('负责需求梳理和文档编写'), '岗位保留原句依据');
  check('jd-interpretation', (await page.locator('#workspace-panel-jd').textContent()).includes('问题来源、判断过程和交付结果'), '原长解读迁移到右侧岗位解读');
  check('tabs-are-buttons', await page.locator('#stage-rail button[role="tab"]').count() === 5, '五个阶段可点击且具备 tab 语义');
  check('guidance-visible', await page.locator('#guidance-dock').isVisible() && await page.locator('.guidance-option').count() === 2, '追问与选项显示在输入框上方');
  check('advice-separate', (await page.locator('#workspace-suggestions').textContent()).includes('尚未作为本人事实'), '建议和待补事实明确分开');
  await checkChatLayout('initial');
  check('icons-offline', await page.evaluate(() => !document.querySelector('.material-symbols-outlined') && [...document.querySelectorAll('.ui-icon')].every(el => !el.textContent.trim() && getComputedStyle(el).maskImage.includes('data:image/svg+xml'))), '断开外网字体后首页所有图标仍由本地 SVG 渲染，不显示英文 token');
  await page.evaluate(() => {
    const realFetch = window.fetch.bind(window);
    window.__workspaceRequests = [];
    window.fetch = async (input, init) => {
      if (input !== '/api/chat/stream') return realFetch(input, init);
      window.__workspaceRequests.push(JSON.parse(init.body));
      if (window.__workspaceReject) return new Response(JSON.stringify({detail:'模拟发送失败'}), {status:503,headers:{'Content-Type':'application/json'}});
      return new Response(new ReadableStream({start(controller) {
        window.__workspaceEmit = value => controller.enqueue(new TextEncoder().encode('data: ' + JSON.stringify(value) + '\n\n'));
        window.__workspaceFinish = () => { controller.enqueue(new TextEncoder().encode('data: [DONE]\n\n')); controller.close(); };
      }}), {headers:{'Content-Type':'text/event-stream'}});
    };
  });
  await page.locator('#input').fill('这是我已经写的补充');
  await page.evaluate(() => {
    attachments.push({filename:'未发送的草稿.txt',text:'附件里的草稿也不应发送'});
    renderAttachments();
    selectedTask = 'decode_jd';
    const choices = [...document.querySelectorAll('.guidance-option')];
    for (let count = 0; count < 20; count++) choices.forEach(choice => choice.click());
  });
  check('choice-sends-once', await page.evaluate(() => window.__workspaceRequests.length === 1), '快速连续点击同组两个选项共40次，只提交一轮');
  check('choice-complete-answer', await page.evaluate(() => window.__workspaceRequests[0].messages[0].content === '我想先整理一段项目经历。' && window.__workspaceRequests[0].task === 'auto'), '完整回答直接发送，不夹带草稿、附件或另选的任务');
  check('choice-user-bubble', (await page.locator('.bubble-user').last().textContent()).trim() === '我想先整理一段项目经历。', '选项直接作为用户消息显示');
  check('choice-preserves-input', await page.locator('#input').inputValue() === '这是我已经写的补充', '已有草稿原样保留，不追加选项文字');
  check('choice-preserves-attachments', await page.evaluate(() => attachments.length === 1 && selectedTask === 'decode_jd'), '未发送附件和对应任务留给原草稿');
  check('choice-hides-group', !(await page.locator('#guidance-dock').isVisible()), '点选后这组立即收起');
  await page.evaluate(value => { window.__workspaceEmit({type:'meta',stage:'COLLECTING',workspace:value}); window.__workspaceFinish(); }, workspace);
  await page.waitForFunction(() => document.getElementById('btn-send').title === '发送');
  await page.evaluate(() => refreshCanvas());
  check('answered-group-stays-hidden', !(await page.locator('#guidance-dock').isVisible()), '流结束与画布刷新后，已回答的同组不会再出现');
  await page.evaluate(() => { clearAttachments(); resetSelectedTask(); });
  await checkChatLayout('choice-focus');
  await page.locator('#input').fill('我做了一个 PDF 工具，目前完成本地合并功能。');
  await page.locator('#btn-send').click();
  await page.waitForFunction(() => window.__workspaceRequests.length === 2);
  check('busy-status', (await page.locator('#workspace-status').textContent()).includes('本轮资料') && !(await page.locator('#guidance-dock').isVisible()), '流式时清楚提示同步中，并隐藏旧追问');
  workspace = {...jdWorkspace, experiences:{items:[{name:'PDF 工具',kind:'项目',role:'个人开发',period:'2026.09',bullets:['完成本地 PDF 合并功能'],missing:['使用的具体工具']}],education:[{school:'虚构大学',major:'计算机',degree:'本科'}]}, guidance:{question:'PDF 工具目前处于什么状态？',options:[{label:'本地运行',value:'PDF 工具目前只在本地运行。'},{label:'已经上线',value:'PDF 工具已经上线。'}]}, focus:'experiences'};
  current = {has_data:false, stage:'COLLECTING', workspace};
  await page.evaluate(value => window.__workspaceEmit({type:'meta',stage:'COLLECTING',has_data:false,workspace:value}), workspace);
  await page.waitForFunction(() => document.getElementById('workspace-panel-experiences').textContent.includes('PDF 工具'));
  check('experiences-before-done', await page.locator('#workspace-panel-experiences').isVisible() && await page.locator('#btn-send').getAttribute('title') === '中断生成', '元数据到达即更新右侧经历，无需等流结束');
  check('experience-missing', (await page.locator('#workspace-panel-experiences').textContent()).includes('还需要你补充') && (await page.locator('#workspace-panel-experiences').textContent()).includes('虚构大学'), '经历缺口与教育分别可见');
  await page.evaluate(() => { window.__workspaceEmit({content:'经历已整理到右侧。'}); window.__workspaceFinish(); });
  await page.waitForFunction(() => document.getElementById('btn-send').title === '发送');
  check('new-question-available', await page.locator('#guidance-dock').isVisible() && (await page.locator('#guidance-question').textContent()).includes('什么状态'), '下一轮的新问题正常出现');
  check('short-chat', (await page.locator('.bubble-ai .chat-markdown').last().textContent()).trim() === '经历已整理到右侧。', '聊天不复制工作区的长资料');
  // A canonical revision is rendered while the reply is still streaming.
  await page.locator('#input').fill('补充：我使用 Python 实现合并，并增加页面选择。');
  await page.locator('#btn-send').click();
  await page.waitForFunction(() => window.__workspaceRequests.length === 3);
  const resume = {basic_info:{name:'虚构测试用户'},projects:[{name:'PDF 工具',bullets:['使用 Python 实现 PDF 合并与页面选择']}],verification_notes:['请核对经历时间']};
  workspace = {...workspace, resume:{has_data:true,version:'opaque-version-a'}, focus:'resume',review:{items:['请核对经历时间']}};
  current = {has_data:true,stage:'EVALUATING',revision:'opaque-version-a',data:resume,workspace};
  await page.evaluate(value => window.__workspaceEmit({type:'meta',has_data:true,stage:'EVALUATING',workspace:value}), workspace);
  await page.waitForFunction(() => document.getElementById('live-sheet').srcdoc.includes('页面选择'));
  check('resume-before-done', await page.locator('#workspace-panel-resume').isVisible() && await page.locator('#btn-send').getAttribute('title') === '中断生成', '本轮事实触发新画布，回复结束前即可看到');
  await page.evaluate(() => { window.__workspaceEmit({content:'已将补充同步到简历。'}); window.__workspaceFinish(); });
  await page.waitForFunction(() => document.getElementById('btn-send').title === '发送');
  await page.waitForFunction(() => document.getElementById('workspace-status').textContent.includes('同步'));
  await page.waitForTimeout(80);
  check('latest-reply-visible', await page.evaluate(() => { const el=document.getElementById('messages'); return el.scrollTop + el.clientHeight >= el.scrollHeight - 1; }), '追问展开改变布局后，消息区仍显示最新回复');
  check('no-version-hash', !(await page.locator('#workspace-status').textContent()).includes('opaque-version'), '版本只用于变化检测，不显示技术 hash');
  await checkChatLayout('conversation');
  await page.locator('#workspace-tab-experiences').click();
  await page.screenshot({path:'evaluation/live-workspace-2026-10-04/workspace-desktop.png',fullPage:true});
  await page.locator('#workspace-tab-resume').click();
  await page.waitForTimeout(80);
  await page.screenshot({path:'evaluation/live-workspace-2026-10-04/workspace-resume.png',fullPage:true});
  for (const [index, width] of [1440,1024,768,390,768,1024,1440].entries()) {
    await page.setViewportSize({width,height:900});
    await page.locator('#input').focus();
    await page.waitForTimeout(80);
    check('no-overflow-' + index + '-' + width, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1 && document.getElementById('canvas-sheet-wrap').scrollWidth <= document.getElementById('canvas-sheet-wrap').clientWidth + 1), 'A4 缩放后的真实占位不撑宽页面');
    await checkChatLayout('resize-' + index + '-' + width);
  }
  await page.locator('#workspace-tab-jd').click();
  await page.locator('#workspace-tab-jd').press('ArrowRight');
  check('keyboard-tabs', await page.locator('#workspace-tab-experiences').getAttribute('aria-selected') === 'true' && await page.locator('#workspace-tab-experiences').evaluate(el => el === document.activeElement), '方向键切换工作区并移动焦点');
  await page.locator('#workspace-tab-review').click();
  check('review-items', (await page.locator('#workspace-panel-review').textContent()).includes('请核对经历时间'), '核对 tab 展示当前问题');
  await page.evaluate(() => window.HuhuaWorkspace.openTab('export'));
  check('export-in-write-tab', await page.locator('#workspace-panel-resume').isVisible() && await page.locator('#btn-export-pdf').isEnabled() && await page.locator('#workspace-tab-export').count() === 0, '旧导出入口指向写简历中的下载按钮');
  await page.setViewportSize({width:390,height:844});
  await page.locator('#btn-toggle-canvas').click();
  await page.locator('#workspace-tab-resume').click();
  await page.waitForTimeout(80);
  check('mobile-workspace', await page.locator('#canvas-pane').isVisible() && await page.locator('#canvas-pane').getAttribute('aria-modal') === 'true', '手机单独打开可关闭的工作区');
  check('mobile-no-overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1 && document.getElementById('canvas-sheet-wrap').scrollWidth <= document.getElementById('canvas-sheet-wrap').clientWidth + 1), '390px 页面与画布均无横向溢出');
  await page.locator('#workspace-tab-experiences').click();
  await page.screenshot({path:'evaluation/live-workspace-2026-10-04/workspace-mobile.png',fullPage:true});
  await page.locator('#btn-close-workspace').click();
  check('mobile-return-chat', !(await page.locator('#canvas-pane').isVisible()) && await page.evaluate(() => !document.getElementById('chat-pane').inert), '手机可返回对话且恢复输入');
  await page.setViewportSize({width:1440,height:960});
  await page.evaluate(() => { window.__workspaceReject = true; });
  await page.locator('.guidance-option').first().click();
  await page.waitForFunction(() => document.getElementById('btn-send').title === '发送' && !document.getElementById('guidance-dock').hidden);
  check('failed-choice-can-retry', (await page.locator('.bubble-ai .chat-markdown').last().textContent()).includes('模拟发送失败'), '请求未被服务端接受时显示失败，并重新提供选项');
  await page.evaluate(() => { window.__workspaceReject = false; });
  await page.locator('.guidance-option').first().press('Enter');
  await page.waitForFunction(() => window.__workspaceRequests.length === 5);
  check('choice-keyboard-sends', await page.evaluate(() => window.__workspaceRequests.at(-1).messages[0].content === 'PDF 工具目前只在本地运行。'), '键盘回车可重试，仍直接发送完整回答');
  await page.evaluate(() => { window.__workspaceEmit({error:'模拟模型暂时不可用'}); window.__workspaceFinish(); });
  await page.waitForFunction(() => document.getElementById('btn-send').title === '发送' && !document.getElementById('guidance-dock').hidden);
  check('sse-error-choice-can-retry', (await page.locator('.bubble-ai .chat-markdown').last().textContent()).includes('模拟模型暂时不可用'), 'HTTP 200 内的 SSE 错误也恢复选项，不能误认为回答完成');
  await page.locator('.guidance-option').first().click();
  await page.waitForFunction(() => window.__workspaceRequests.length === 6);
  await page.evaluate(() => window.__workspaceFinish());
  await page.waitForFunction(() => document.getElementById('btn-send').title === '发送');
  await page.reload();
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled && document.getElementById('live-sheet').srcdoc.includes('页面选择'));
  check('history-restores-workspace', (await page.locator('#workspace-panel-jd').textContent()).includes('AI 产品实习生') && (await page.locator('#workspace-panel-experiences').textContent()).includes('PDF 工具'), '刷新历史恢复 JD、经历和简历');
  renderFails = true;
  await page.evaluate(() => refreshCanvas());
  check('paint-error-preserves-preview', (await page.locator('#workspace-status').textContent()).includes('同步失败') && await page.locator('#live-sheet').evaluate(el => el.srcdoc.includes('页面选择')), '渲染失败明确提示并保留已有预览');
  renderFails = false;
  await page.locator('#btn-new-chat').click();
  await page.waitForFunction(() => new URLSearchParams(location.search).get('session') === 'workspace-empty-fixture');
  check('new-chat-clears-workspace', !(await page.locator('#workspace-body').textContent()).includes('PDF 工具') && !(await page.locator('#guidance-dock').isVisible()) && await page.locator('#live-sheet').evaluate(el => el.srcdoc === ''), '切换新会话不残留旧 JD、经历、追问或简历');
  await checkChatLayout('new-chat');
  await page.evaluate(() => window.HuhuaWorkspace.update({jd:{info:{job_title:'<img src=x onerror=alert(1)>'},raw_text:'<script>alert(1)</script>'},guidance:{question:'<img src=x>',options:[{label:'<svg onload=alert(1)>',value:'正常填写'}]},suggestions:[{title:'<script>',detail:'<iframe>'}],focus:'jd'}));
  check('workspace-text-safe', await page.locator('#workspace-body script,#workspace-body img,#workspace-body svg,#guidance-dock svg,#guidance-dock img').count() === 0, '所有岗位、选项和建议按文本呈现，不能注入 HTML');
  check('no-page-errors', errors.length === 0, JSON.stringify(errors));
  return {scope:'合成 API/SSE 浏览器工作区回归；未调用真实模型、用户会话或导出服务。',checks,errors};
}
