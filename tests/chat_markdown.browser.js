// Run with playwright-cli in a new disposable session. Business API routes are
// blocked; the fixture loads only the local static renderer and pinned vendors.
async (page) => {
  const report = { checks: [], page_errors: [], business_requests: [], remote_requests: [] };
  page.on('pageerror', error => report.page_errors.push(error.message));
  page.on('request', request => {
    const url = request.url();
    if (url.includes('/api/')) report.business_requests.push(url);
    if (url.startsWith('http') && !url.startsWith('http://127.0.0.1:8765/')) report.remote_requests.push(url);
  });
  await page.route('**/api/**', route => route.abort());
  await page.route('**://attacker.invalid/**', route => route.abort());
  await page.route('http://127.0.0.1:8765/__markdown_test__', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><html><head><meta charset="utf-8"><title>Markdown fixture</title><link rel="icon" href="data:,"></head><body style="margin:16px;font:15px system-ui"><main style="width:340px;max-width:100%"><div id="answer"></div></main></body></html>'
  }));
  await page.route('**/api/account/me', route => route.fulfill({json:{authenticated:false, require_account:false, login_available:false}}));
  await page.goto('http://127.0.0.1:8765/__markdown_test__');
  await page.addStyleTag({ url: 'http://127.0.0.1:8765/static/chat-markdown.css' });
  for (const path of ['vendor/marked.umd.js', 'vendor/purify.min.js', 'chat-markdown.js']) {
    await page.addScriptTag({ url: `http://127.0.0.1:8765/static/${path}` });
  }
  function check(id, condition, detail) {
    report.checks.push({ id, passed: Boolean(condition), detail });
    if (!condition) throw new Error(`${id}: ${detail}`);
  }
  async function render(raw, streaming = false) {
    const mode = await page.evaluate(({ raw, streaming }) => {
      return window.HuhuaMarkdown.render(document.getElementById('answer'), raw, { streaming });
    }, { raw, streaming });
    check('markdown-mode', mode.mode === 'markdown', JSON.stringify(mode));
    return page.locator('#answer');
  }
  const documentMarkdown = '# 求职建议\n\n## 证据\n\n第一段 **真实贡献**，第二句。\n\n另一个段落。\n\n- Python 项目\n- Excel 课设\n\n1. 核实角色\n2. 核实状态\n\n> 保留真实范围\n\n`inline code`\n\n```python\nprint("hello")\n```\n\n| 要求 | 证据 |\n| --- | --- |\n| SQL | 待补 |\n\n[官方链接](https://example.com/jobs)';
  let answer = await render(documentMarkdown);
  check('class-added', await answer.getAttribute('class') === 'chat-markdown', '容器添加排版 class');
  check('headings', await answer.locator('h1').count() === 1 && await answer.locator('h2').count() === 1, '标题解析');
  check('strong', await answer.locator('strong').textContent() === '真实贡献', '加粗解析，无完整 **');
  check('paragraphs', await answer.locator('p').count() >= 3, '段落解析');
  check('lists', await answer.locator('ul li').count() === 2 && await answer.locator('ol li').count() === 2, '有序无序列表解析');
  check('blockquote', (await answer.locator('blockquote').textContent()).includes('保留真实范围'), '引用解析');
  check('code', await answer.locator('code').count() === 2 && (await answer.locator('pre code').textContent()).includes('print("hello")'), '行内/块代码解析');
  check('table', await answer.locator('table th').count() === 2 && await answer.locator('table td').count() === 2, 'GFM 表格解析');
  const link = answer.getByRole('link', { name: '官方链接' });
  check('safe-link', await link.getAttribute('href') === 'https://example.com/jobs' && await link.getAttribute('rel') === 'noopener noreferrer', 'HTTPS 链接可点击且无 opener');
  await page.evaluate(() => {
    document.getElementById('answer').addEventListener('click', event => {
      const link = event.target.closest('a');
      if (link) { event.preventDefault(); window.__clickedMarkdownLink = link.href; }
    });
  });
  await link.click();
  check('link-click', await page.evaluate(() => window.__clickedMarkdownLink) === 'https://example.com/jobs', '实际点击事件命中正常链接，测试阻止外部导航');

  answer = await render('**标题 **：真实内容');
  check('loose-closing-space', await answer.locator('strong').textContent() === '标题' && !(await answer.textContent()).includes('**'), '关闭前空格容错');
  answer = await render('正常 **标准粗体**。');
  check('standard-bold-preserved', await answer.locator('strong').textContent() === '标准粗体', '标准粗体未受容错影响');
  for (const chunk of ['**', '**标', '**标题 ', '**标题 *', '**标题 **', '**标题 **：正文']) {
    answer = await render(chunk, true);
    check('streaming-no-double-star', !(await answer.textContent()).includes('**'), `片段 ${JSON.stringify(chunk)}`);
  }
  answer = await render('**标题 **：正文', false);
  check('finalized-bold', await answer.locator('strong').textContent() === '标题', '最终完整文本稳定');
  answer = await render('**中断片段\n\n[已中断]', true);
  check('interrupted-bold', await answer.locator('strong').textContent() === '中断片段' && (await answer.textContent()).includes('[已中断]'), '中断保留已收片段并视觉补全');

  const codeLiteral = '`**标题 **`\n\n```txt\n**代码原文 **\n<script>literal</script>\n```';
  answer = await render(codeLiteral, true);
  check('inline-code-literal', await answer.locator('code').first().textContent() === '**标题 **', '行内代码星号原样保留');
  check('fenced-code-literal', await answer.locator('pre code').textContent() === '**代码原文 **\n<script>literal</script>\n', '块代码和 HTML 字面量原样保留');
  check('no-bold-in-code', await answer.locator('strong').count() === 0, '不在代码内做粗体修复');
  answer = await render('\\*\\*保留 \\*\\*', true);
  check('escaped-literal', await answer.textContent() === '**保留 **\n' && await answer.locator('strong').count() === 0, '转义 literal 保留');
  answer = await render('x**2', true);
  check('intraword-literal', (await answer.textContent()).trim() === 'x**2', 'ASCII 单词内 literal 保留');
  answer = await render('**故意未闭合', false);
  check('complete-literal', (await answer.textContent()).trim() === '**故意未闭合', '完整非流式的未闭合 literal 保守保留');

  const unsafe = '<img src="https://attacker.invalid/a" onerror="window.__xss=1"><script>window.__xss=2</script><svg onload="window.__xss=3"></svg>\n\n![外部图片](https://attacker.invalid/b)\n\n[脚本](javascript:alert(1)) [数据](data:text/html;base64,PHNjcmlwdD4=) [文件](file:///etc/passwd) [正常](https://example.com)\n\n<a href="javascript:alert(1)">raw link</a>';
  answer = await render(unsafe, true);
  check('no-active-html', await answer.locator('img,script,svg,iframe,object,embed,form,input,style').count() === 0, '危险/加载型 HTML 不进入 DOM');
  check('no-event-attributes', await answer.locator('[onerror],[onload],[onclick],[style]').count() === 0, '事件/内联样式不进入 DOM');
  check('no-script-execution', await page.evaluate(() => window.__xss) === undefined, '没有执行注入脚本');
  const hrefs = await answer.locator('a').evaluateAll(nodes => nodes.map(node => node.getAttribute('href')).filter(Boolean));
  check('safe-protocols-only', hrefs.length === 1 && hrefs[0] === 'https://example.com', 'javascript/data/file 链接不具备 href');
  check('image-alt-retained', (await answer.textContent()).includes('外部图片'), '禁自动图片时保留 alt 信息');
  answer = await render('[正常相对链接](/resume) [邮件](mailto:test@example.com)');
  check('relative-mailto', await answer.locator('a[href]').count() === 2, '正常相对/邮件链接保留');

  await page.setViewportSize({ width: 390, height: 844 });
  const headers = Array.from({ length: 8 }, (_, i) => `字段 ${i + 1}`).join(' | ');
  const table = `| ${headers} |\n| ${Array(8).fill('---').join(' | ')} |\n| ${Array(8).fill('Long-value').join(' | ')} |`;
  answer = await render(table + '\n\n```txt\n' + 'long-code-'.repeat(70) + '\n```');
  const sizing = await page.evaluate(() => ({
    viewport: innerWidth, pageWidth: document.documentElement.scrollWidth,
    tableWidth: document.querySelector('table').clientWidth, tableScroll: document.querySelector('table').scrollWidth,
    preWidth: document.querySelector('pre').clientWidth, preScroll: document.querySelector('pre').scrollWidth,
    minWidth: getComputedStyle(document.getElementById('answer')).minWidth
  }));
  check('mobile-contained', sizing.pageWidth <= sizing.viewport, JSON.stringify(sizing));
  check('table-local-scroll', sizing.tableScroll > sizing.tableWidth, '宽表格在消息内横向滚动');
  check('code-local-scroll', sizing.preScroll > sizing.preWidth, '长代码在消息内横向滚动');
  check('min-width-zero', sizing.minWidth === '0px', 'flex 内容可收缩');

  const fallback = await page.evaluate(() => {
    const purifier = window.DOMPurify;
    window.DOMPurify = undefined;
    const mode = window.HuhuaMarkdown.render(document.getElementById('answer'), '<img onerror="window.__xss=4"> **raw**', { streaming: true });
    window.DOMPurify = purifier;
    return { mode, text: document.getElementById('answer').textContent, imgCount: document.getElementById('answer').querySelectorAll('img').length };
  });
  check('safe-fallback', fallback.mode.mode === 'plain' && fallback.imgCount === 0 && fallback.text.includes('**raw**'), '依赖失败时只用 textContent');
  check('no-business-requests', report.business_requests.length === 0, JSON.stringify(report.business_requests));
  check('no-remote-requests', report.remote_requests.length === 0, JSON.stringify(report.remote_requests));
  check('no-page-errors', report.page_errors.length === 0, JSON.stringify(report.page_errors));
  await page.evaluate(report => { window.__huhuaMarkdownCheck = report; }, report);
  return report;
}
