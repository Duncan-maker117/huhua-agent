// Disposable browser fixture; synthetic SSE only, business API mocked.
async (page) => {
  page.removeAllListeners('dialog');
  page.on('dialog', dialog => dialog.accept());
  const checks = [];
  const errors = [];
  const requests = [];
  const initial = '**先给三个项目的判断**\n\n已有事实保留原口径。\n\n**建议的排序与侧重 （每项保留两条） **\n\n1. CodeWiz — Agent 设计\n2. Huhua Agent — 内容核对\n3. mtagent — 不确定性处理\n\n- **保留未上线状态**\n- 不补造数字\n\n> 修改建议需要本人核对。\n\n```txt\n**这是代码原文**\n```\n\n[示例来源](https://example.com/source)\n\n[打开模板](/resume)\n\n| 项目 | 状态 |\n| --- | --- |\n| 示例 | 未上线 |\n';
  function check(id, condition, detail) {
    checks.push({id, passed:!!condition, detail});
    if (!condition) throw new Error(id + ': ' + detail);
  }
  page.removeAllListeners('pageerror');
  await page.unroute('**/api/**');
  page.on('pageerror', error => errors.push(error.message));
  let simulatedSession = 'markdown-stream-fixture';
  let serverMessages = [];
  await page.route('**/api/**', async route => {
    requests.push(('/' + route.request().url().split('/').slice(3).join('/').split('?')[0]));
    const path = ('/' + route.request().url().split('/').slice(3).join('/').split('?')[0]);
    if (path === '/api/resume/templates') await route.fulfill({json:{templates:[]}});
    else if (path === '/api/resume/current') await route.fulfill({json:{has_data:false,stage:'JD_INPUT'}});
    else if (path === '/api/chat/conversations' && route.request().method() === 'POST') {
      simulatedSession = route.request().postDataJSON().session_id || simulatedSession;
      await route.fulfill({json:{session_id:simulatedSession,title:'Markdown 流式测试',messages:[]}});
    }
    else if (path === '/api/chat/conversations') await route.fulfill({json:{conversations:[{session_id:simulatedSession,title:'Markdown 流式测试',updated_at:'2026-10-02T00:00:00Z'}],retention_days:0}});
    else if (path.startsWith('/api/chat/conversations/')) {
      const savedMessages = serverMessages;
      await route.fulfill({json:{session_id:decodeURIComponent(path.split('/').at(-1)),title:'Markdown 流式测试',messages:savedMessages,stage:'JD_INPUT'}});
    }
    else if (path.startsWith('/api/chat/session/')) await route.fulfill({json:{deleted:true}});
    else await route.fulfill({status:503,json:{detail:'模拟接口'}});
  });
  await page.route('**/api/account/me', route => route.fulfill({json:{authenticated:false, require_account:false, login_available:false}}));
  await page.goto('http://127.0.0.1:8765/', {waitUntil:'domcontentloaded'});
  await page.waitForFunction(() => window.HuhuaMarkdown && window.marked && window.DOMPurify);
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled);
  await page.evaluate(() => {
    const realFetch = window.fetch.bind(window);
    window.__fakeRequests = [];
    window.__xssExecuted = 0;
    window.fetch = async (input, init) => {
      if (input !== '/api/chat/stream') return realFetch(input, init);
      window.__fakeRequests.push(JSON.parse(init.body));
      let closed = false;
      return new Response(new ReadableStream({start(controller) {
        window.__pushRaw = (bytes) => controller.enqueue(new Uint8Array(bytes));
        window.__pushFrame = (content, fragmented=false) => {
          const bytes = new TextEncoder().encode('data: '+JSON.stringify({content})+'\r\n\r\n');
          if (fragmented) for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
          else controller.enqueue(bytes);
        };
        window.__breakSse = () => { closed=true; controller.error(new TypeError('模拟网络中断')); };
        window.__finishSse = () => {
          controller.enqueue(new TextEncoder().encode('data: [DONE]\n\n'));
          closed = true;
          controller.close();
        };
        init.signal.addEventListener('abort', () => {
          if (!closed) { closed=true; controller.error(new DOMException('用户中断','AbortError')); }
        }, {once:true});
      }}), {headers:{'Content-Type':'text/event-stream'}});
    };
  });
  await page.locator('#input').fill('测试用户 **原文** <img src=x onerror=alert(1)>');
  await page.locator('#btn-send').click();
  await page.waitForFunction(() => typeof window.__pushFrame === 'function');
  await page.evaluate(() => window.__pushFrame('**先给三个', true));
  await page.waitForFunction(() => document.querySelector('.bubble-ai')?.textContent.includes('先给三个'));
  check('first-text-before-done', await page.locator('#btn-send').getAttribute('title') === '中断生成', '首段已显示，SSE仍未结束');
  check('partial-bold-no-stars', !(await page.locator('.bubble-ai').textContent()).includes('**'), '未闭合加粗在流式显示时不露星号');
  await page.evaluate(rest => window.__pushFrame(rest), initial.slice('**先给三个'.length));
  await page.waitForFunction(() => document.querySelectorAll('.bubble-ai ol li').length === 3);
  check('structured-before-done', await page.locator('.bubble-ai ol li').count() === 3 && await page.locator('#btn-send').getAttribute('title') === '中断生成', '流尚未结束，列表已渲染');
  await page.evaluate(() => window.__finishSse());
  await page.waitForFunction(() => document.getElementById('btn-send').title === '发送');
  check('final-bold', await page.locator('.bubble-ai strong').count() >= 3, '加粗与关闭前空格容错');
  check('final-no-stars', !(await page.locator('.bubble-ai p').allTextContents()).some(x=>x.includes('**')), '正文不露Markdown星号');
  check('list-structure', await page.locator('.bubble-ai ol li').count() === 3 && await page.locator('.bubble-ai ul li').count() === 2, '有序/无序列表');
  check('quote-code-table', await page.locator('.bubble-ai blockquote').count() === 1 && await page.locator('.bubble-ai pre code').textContent() === '**这是代码原文**\n' && await page.locator('.bubble-ai table tbody tr').count() === 1, '引用、代码和表格保持结构');
  check('safe-link', await page.locator('.bubble-ai a[href="https://example.com/source"]').getAttribute('href') === 'https://example.com/source' && (await page.locator('.bubble-ai a[href="https://example.com/source"]').getAttribute('rel')).includes('noopener'), '链接可用且带rel');
  check('template-link-session', (await page.locator('.bubble-ai a[href^="/resume?session="]').getAttribute('href')) === '/resume?session=' + encodeURIComponent(simulatedSession), 'AI模板链接绑定本会话而非其他标签页活动ID');
  check('user-text-only', await page.locator('.bubble-user').locator('strong,img').count() === 0 && (await page.locator('.bubble-user').textContent()).includes('**原文**'), '用户原文仍按纯文本显示');
  const saved = await page.evaluate(() => chatBackups.get(SESSION_ID));
  check('raw-markdown-in-memory', saved.at(-1).content === initial, '页面内存保留原始Markdown，不存入浏览器长期缓存');
  await page.locator('#input').fill('测试中断');
  await page.locator('#btn-send').click();
  await page.waitForFunction(() => window.__fakeRequests.length===2);
  await page.evaluate(() => window.__pushFrame('**未完成的中文'));
  await page.waitForFunction(() => document.querySelectorAll('.bubble-ai')[1]?.textContent.includes('未完成的中文'));
  await page.locator('#btn-send').click();
  await page.waitForFunction(() => document.getElementById('btn-send').title==='发送');
  const abortedText = await page.locator('.bubble-ai').nth(1).textContent();
  check('abort-retains-content', abortedText.includes('未完成的中文') && abortedText.includes('[已中断]') && !abortedText.includes('**'), '中断保留已收到内容并保持Markdown显示');
  check('abort-cleans-state', await page.locator('.bubble-ai').nth(1).locator('.streaming,[aria-busy="true"]').count()===0, '中断后恢复发送并清理光标');
  const abortSaved=await page.evaluate(() => chatBackups.get(SESSION_ID).at(-1));
  check('abort-saves-raw-and-state', abortSaved.interrupted===true && abortSaved.content==='**未完成的中文\n\n[已中断]', '历史保留中断状态和原始Markdown');
  await page.locator('#input').fill('测试网络中断');
  await page.locator('#btn-send').click();
  await page.waitForFunction(() => window.__fakeRequests.length===3);
  await page.evaluate(() => window.__pushFrame('**网络片段**'));
  await page.waitForFunction(() => document.querySelectorAll('.bubble-ai')[2]?.textContent.includes('网络片段'));
  await page.evaluate(() => window.__breakSse());
  await page.waitForFunction(() => document.getElementById('btn-send').title==='发送');
  const networkText=await page.locator('.bubble-ai').nth(2).textContent();
  check('network-error-retains-content', networkText.includes('网络片段') && networkText.includes('请求失败'), '网络断开不覆盖已收到正文');
  serverMessages = await page.evaluate(() => messages.map(message => ({...message})));
  await page.reload();
  await page.waitForFunction(() => !document.getElementById('btn-send').disabled && document.querySelectorAll('.bubble-ai').length === 3);
  check('abort-history-rendered', !(await page.locator('.bubble-ai').nth(1).textContent()).includes('**') && (await page.locator('.bubble-ai').nth(1).textContent()).includes('[已中断]'), '中断历史刷新后显示一致');
  check('history-rendered', await page.locator('.bubble-ai ol li').count() === 3 && await page.locator('.bubble-ai strong').count() >= 3, '刷新历史同样按Markdown显示');
  check('cursor-cleared', await page.locator('.bubble-ai .streaming').count() === 0 && await page.locator('.bubble-ai [aria-busy="true"]').count() === 0, '结束后无流式光标/忙状态');
  await page.evaluate(() => {
    const el=document.querySelector('.bubble-ai .chat-markdown');
    window.HuhuaMarkdown.render(el, '# 安全标题\n\n<script>window.__xssExecuted=1</script><img src="https://example.com/track.png" onerror="window.__xssExecuted=2">\n\n[坏链接](javascript:alert(1)) ![远程图片](https://example.com/track.png)\n\n**安全内容**');
  });
  check('no-executable-markup', await page.locator('.bubble-ai').locator('script,img,iframe,svg,form').count() === 0 && await page.evaluate(() => (window.__xssExecuted===undefined || window.__xssExecuted===0)), '危险标签/远程图片不可执行');
  check('no-dangerous-links', await page.locator('.bubble-ai a[href^="javascript:"],a[href^="data:"]').count() === 0, '危险链接协议不可点');
  check('heading-style', await page.locator('.bubble-ai h1').count() === 1, '标题形成语义节点');
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(() => window.HuhuaMarkdown.render(document.querySelector('.bubble-ai .chat-markdown'), '## 手机阅读\n\n| 长内容 | 状态 |\n| --- | --- |\n| '+ '很长内容'.repeat(30)+' | 未上线 |\n\n```\n'+ 'x'.repeat(300)+'\n```'));
  check('mobile-no-page-overflow', await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), '长表格/代码不撑出手机页面');
  await page.setViewportSize({width:1440,height:900});
  check('no-page-errors', errors.length===0, JSON.stringify(errors));
  const result = {scope:'独立浏览器：分片ReadableStream模拟SSE，业务API全部拦截；未调用真实LLM或用户会话。',checks,errors,intercepted_requests:requests};
  await page.evaluate(result => window.__mdFlowReport=result, result);
  return result;
}
