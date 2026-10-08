// Real UI → graph → SSE → encrypted persistence → reload. Polishing alone is identity.
// Run against tests/complete_task_live_server.py; never target production.
async (page) => {
  const base = 'http://127.0.0.1:8901';
  const checks = [], errors = [], browserRequests = [];
  let stage = 'open', sessionId, before, after, conversation, restored, events, audit, baselineAudit;
  const check = (condition, name) => { checks.push({name, passed: Boolean(condition)}); if (!condition) throw new Error(name); };
  const read = async path => {
    const response = await page.request.get(base + path);
    check(response.ok(), 'API success: ' + path.split('?')[0]);
    return response.json();
  };
  const counts = data => Object.fromEntries(['projects','education','skills','certificates'].map(key => [key, (data[key] || []).length]));
  const factChecks = (data, label) => {
    check(JSON.stringify(counts(data)) === JSON.stringify({projects:3, education:1, skills:2, certificates:3}), label + ': every factual section retained');
    check(JSON.stringify(data.projects.map(project => project.name)) === JSON.stringify(['ResumeLab','CodeLab','RouteFlow']), label + ': project order and names retained');
    check(data.basic_info.name === '林同学' && data.education[0].school === '示例大学', label + ': identity and education retained');
    check(!data.education[0].start_date, label + ': missing education start date stays blank');
    check(data.projects[0].start_date === '2025.9' && data.projects[2].end_date === '2026.7', label + ': explicit project dates retained');
    check(data.projects[0].description.includes('尚未上线') && data.projects[2].description.includes('真实旅行效果尚未验证'), label + ': limitations retained');
    check(!JSON.stringify(data).includes('不需要自我评价') && !JSON.stringify(data).includes('请现在生成'), label + ': generation instructions excluded');
  };
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => browserRequests.push({url:request.url(), method:request.method()}));
  try {
    await page.setViewportSize({width:1440, height:1000});
    await page.goto(base + '/');
    await page.waitForFunction(() => document.getElementById('btn-send')?.disabled === false);
    sessionId = await page.evaluate(() => new URL(location.href).searchParams.get('session'));
    const initial = await read('/api/resume/current?session_id=' + sessionId);
    if (initial.has_data) {
      await page.locator('#btn-new-chat').click();
      await page.waitForFunction(previous => new URL(location.href).searchParams.get('session') !== previous && document.getElementById('btn-send')?.disabled === false, sessionId);
      sessionId = await page.evaluate(() => new URL(location.href).searchParams.get('session'));
    }
    check(Boolean(sessionId), 'fresh guest conversation created through UI');
    const source = await read('/__test__/complete-task-input');
    check(source.synthetic === true, 'fixture uses synthetic material');
    baselineAudit = await read('/__test__/complete-task-audit');
    // Chromium does not always retain SSE bodies for response.text(). A cloned
    // browser response observes the real stream without changing either flow.
    await page.evaluate(() => {
      window.__completeTaskStreams = [];
      const originalFetch = window.fetch;
      window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        if (response.url.endsWith('/api/chat/stream')) {
          response.clone().text().then(text => window.__completeTaskStreams.push(text));
        }
        return response;
      };
    });

    stage = 'submit-complete-material';
    const streamResponse = page.waitForResponse(response => response.url() === base + '/api/chat/stream');
    await page.locator('#input').fill(source.text);
    await page.locator('#btn-send').click();
    const stream = await streamResponse;
    check(stream.status() === 200, 'real chat stream returns HTTP 200');
    await page.waitForFunction(() => window.__completeTaskStreams.length === 1);
    const sse = await page.evaluate(() => window.__completeTaskStreams[0]);
    check(sse.includes('data: [DONE]'), 'SSE reaches DONE');
    events = sse.split('\n\n').filter(block => block.startsWith('data: ') && block !== 'data: [DONE]').map(block => JSON.parse(block.slice(6)));
    check(!events.some(event => event.error), 'SSE contains no error');
    const meta = events.find(event => event.type === 'meta');
    check(meta?.stage === 'EVALUATING' && meta?.has_data === true, 'first turn reaches EVALUATING with real draft');
    const reply = events.filter(event => event.content).map(event => event.content).join('');
    check(reply.includes('3 段项目') && reply.includes('2 条技能') && reply.includes('3 条奖项/活动'), 'success reply reports actual draft counts');
    check(!/先说一段|先从哪一段|是否先生成|还是先补充/.test(reply), 'complete submission does not restart interview');
    await page.waitForFunction(() => document.getElementById('btn-send')?.disabled === false && document.getElementById('live-sheet')?.srcdoc.includes('RouteFlow'));

    stage = 'verify-persisted-result';
    before = await read('/api/resume/current?session_id=' + sessionId);
    factChecks(before.data, 'saved draft');
    conversation = await read('/api/chat/conversations/' + sessionId);
    check(conversation.stage === 'EVALUATING', 'conversation stores EVALUATING');
    check(conversation.messages.length === 2 && conversation.messages[0].role === 'user' && conversation.messages[1].role === 'assistant', 'exactly one user and one assistant message persisted');
    check(conversation.messages[0].content === source.text.trim() && conversation.messages[1].content === reply, 'persisted messages match submitted input and SSE reply');
    check((await page.locator('#messages').textContent()).includes('3 段项目'), 'actual chat UI displays factual success reply');
    const preview = await page.locator('#live-sheet').getAttribute('srcdoc');
    check(['ResumeLab','CodeLab','RouteFlow','示例大学','结营证书'].every(value => preview.includes(value)), 'actual preview contains projects, education and award');
    await page.screenshot({path:'evaluation/complete-resume-task-2026-10-08/chat-complete-before-refresh.png'});

    stage = 'reload';
    await page.reload();
    await page.waitForFunction(() => document.getElementById('btn-send')?.disabled === false && document.getElementById('live-sheet')?.srcdoc.includes('RouteFlow'));
    check(await page.evaluate(() => new URL(location.href).searchParams.get('session')) === sessionId, 'reload keeps same conversation');
    after = await read('/api/resume/current?session_id=' + sessionId);
    factChecks(after.data, 'restored draft');
    check(JSON.stringify(before.data) === JSON.stringify(after.data), 'entire canonical draft unchanged after reload');
    restored = await read('/api/chat/conversations/' + sessionId);
    check(restored.stage === 'EVALUATING' && JSON.stringify(restored.messages) === JSON.stringify(conversation.messages), 'reload restores stage and exact messages without duplication');
    check((await page.locator('#messages').textContent()).includes('3 段项目'), 'reloaded chat displays saved success reply');
    audit = await read('/__test__/complete-task-audit');
    check(audit.editor_calls - baselineAudit.editor_calls === 1 && audit.external_model_allowed === false, 'only one identity polishing pass; no provider configured');
    check(browserRequests.filter(request => request.url === base + '/api/chat/stream').length === 1, 'reload never repeats generation request');
    check(errors.length === 0, 'no page JavaScript exceptions');
    await page.screenshot({path:'evaluation/complete-resume-task-2026-10-08/chat-complete-after-refresh.png'});
    return {passed:true, scope:'Local encrypted main.app; real graph, parser, SSE, database and browser UI. Only editor polishing returns unchanged data. Synthetic input, no external models or email; no export or template checks.', checks, errors, sessionId, counts:counts(after.data), stage:restored.stage, messageCount:restored.messages.length, audit, baselineAudit};
  } catch (error) {
    return {passed:false, stage, error:String(error), checks, errors, sessionId, counts:before?.data ? counts(before.data) : undefined, events, audit};
  }
}
