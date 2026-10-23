// Real encrypted HTTP/SQLite, OTP fixture, and actual MCP proposals; fictional data only.
// .venv/bin/python tests/product_live_server.py --port 8894
// playwright-cli -s=huhua-memory-batch open http://127.0.0.1:8894/chat
// playwright-cli -s=huhua-memory-batch run-code --filename=tests/profile_memory_batch.browser.js
async (page) => {
  const base = page.url().split('/').slice(0, 3).join('/'), checks = [], errors = [], writes = [];
  const check = (ok, name) => { if (!ok) throw new Error(name); checks.push(name); };
  const candidate = (index, changes = {}) => ({category:'project', subject:'批量虚构项目' + index, field:'description', value:'本地合成工作' + index + '，未上线', evidence:'合成对话原文' + index, ...changes});
  const request = async (path, data, method = data === undefined ? 'GET' : 'POST') => {
    const response = await page.request.fetch(base + path, {method, headers:{Origin:base}, ...(data === undefined ? {} : {data})});
    if (!response.ok()) throw new Error(path + ' returned ' + response.status() + ': ' + await response.text());
    return response.json();
  };
  const idle = () => page.waitForFunction(() => document.getElementById('profile-content')?.getAttribute('aria-busy') !== 'true');
  const badge = async count => {
    check(await page.locator('.profile-confirm-badge').count() === (count ? 1 : 0), '红点显隐 ' + count);
    if (count) check(await page.locator('.profile-confirm-badge').textContent() === String(count), '红点数量 ' + count);
  };
  const mobile = async label => {
    await page.setViewportSize({width:390, height:844});
    check(await page.evaluate(() => { const drawer = document.getElementById('profile-drawer'); return document.documentElement.scrollWidth <= innerWidth && drawer.scrollWidth <= drawer.clientWidth && drawer.getBoundingClientRect().width <= innerWidth; }), '390px 无横向滚动：' + label);
  };
  const importUI = async rows => {
    await page.getByRole('button', {name:'从其他 AI 导入', exact:true}).click();
    await idle();
    await page.getByLabel('粘贴 AI 的回答', {exact:true}).fill(JSON.stringify(rows));
    await page.getByRole('button', {name:'导入档案', exact:true}).click();
    await page.waitForFunction(() => document.querySelector('.profile-memory-result')?.textContent.includes('已加入档案'));
    await idle();
    return page.locator('.profile-memory-result').textContent();
  };
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.method() === 'POST' && /confirmations\/batch|\/inbox\/.*\/(accept|reject)$/.test(request.url())) writes.push({url:request.url(), body:request.postDataJSON()}); });
  const email = 'batch-' + Date.now() + '@huhua-fixture.invalid';
  await request('/api/account/login/start', {email});
  const {code} = await request('/__test__/otp?email=' + encodeURIComponent(email));
  await request('/api/account/login/verify', {email, code});
  await page.setViewportSize({width:1280, height:960});
  await page.goto(base + '/chat');
  await page.getByRole('button', {name:'我的档案', exact:true}).click();
  await page.getByRole('button', {name:'从其他 AI 导入', exact:true}).waitFor();

  const result = await importUI(Array.from({length:99}, (_, index) => candidate(index, {evidence:'uncertain：合成记录待确认'})));
  check(result.includes('已加入档案 0 条') && result.includes('99 条不确定'), '导入结果区分直接生效和不确定项');
  await badge(99);
  await page.getByRole('button', {name:'查看待确认信息', exact:true}).click();
  await page.getByLabel('全选待确认信息', {exact:true}).waitFor();
  check(await page.locator('.profile-inbox-item').count() === 99, '99 条导入待确认项可见');
  await mobile('99 条待确认');
  await page.getByLabel('选择整组：来自其他 AI 导入', {exact:true}).check();
  check(await page.getByLabel('全选待确认信息', {exact:true}).isChecked(), '整组选中同步全选');
  await page.locator('.profile-inbox-item input[type=checkbox]').first().uncheck();
  check(await page.getByLabel('全选待确认信息', {exact:true}).evaluate(node => node.indeterminate), '部分选中显示中间状态');
  await page.getByLabel('全选待确认信息', {exact:true}).check();
  await page.getByRole('button', {name:'确认所选（99）', exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.profile-status')?.textContent.includes('已确认 99 条'));
  await idle();
  check(writes.length === 1 && writes[0].body.items.length === 99 && writes[0].body.items.every(item => item.expected_revision), '99 条确认只发一次带逐条修订保护的批量请求');
  check(await page.locator('.profile-inbox-item').count() === 0, '确认后列表清空');
  await badge(0);
  check((await request('/api/account/mcp/inbox')).pending_count === 0, '真实 API 待确认数归零');
  check((await request('/api/profile')).facts.length === 99, '真实数据库 99 条确认生效');

  await page.getByRole('button', {name:'返回已有信息', exact:true}).click();
  check((await page.locator('#profile-content').textContent()).includes('来自其他 AI 导入'), '档案保留可见导入来源');
  await page.locator('.profile-fact-row').first().getByText('查看来源与时间', {exact:true}).click();
  check((await page.locator('.profile-fact-row').first().textContent()).includes('uncertain：合成记录待确认'), '保留 evidence 原文和批次');
  await request('/api/profile/facts', {category:'project', subject:'批量冲突基线', field:'role', value:'原角色'});
  const mixedResult = await importUI([
    candidate('新甲'), candidate('新乙'), candidate(1),
    candidate('冲突', {subject:'批量冲突基线', field:'role', value:'新角色'}),
    candidate('不确定', {evidence:'【不确定】需本人核对'}), candidate('空值', {value:''}),
  ]);
  check(mixedResult.includes('已加入档案 2 条，1 条重复已跳过。1 条冲突、2 条不确定'), '混合导入实时结果数量正确');
  const batchId = (await request('/api/profile')).memory_imports[0].id;
  await badge(3);
  await page.getByRole('button', {name:'查看待确认信息', exact:true}).click();
  await page.getByLabel('全选待确认信息', {exact:true}).check();
  await page.getByRole('button', {name:'确认所选（3）', exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.profile-status')?.textContent.includes('已确认 2 条'));
  await idle();
  check((await page.locator('.profile-batch-failures').textContent()).includes('批量虚构项目空值'), '部分失败明确指出空值条目');
  await badge(1);
  await mobile('部分失败与冲突结果');
  await page.screenshot({path:'/tmp/huhua-memory-batch-mobile.png'});
  await page.getByRole('button', {name:'返回已有信息', exact:true}).click();
  await page.getByText('其他 AI 导入记录', {exact:true}).click();
  await page.locator(`[data-import-batch-id="${batchId}"]`).getByRole('button', {name:'撤销这次导入', exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.profile-status')?.textContent.includes('已撤销 3 条'));
  await idle();
  await badge(0);
  const afterUndo = await request('/api/profile');
  check(afterUndo.facts.length === 100 && afterUndo.facts.some(row => row.subject === '批量冲突基线' && row.value === '新角色'), '撤销只删本批新增，不删除之前已有冲突目标');

  // Exercise the real MCP entry too. Keep the disposable token in memory only.
  const token = await request('/api/account/mcp/tokens', {name:'虚构批量测试', scopes:['profile:propose']});
  const mcpRows = Array.from({length:5}, (_, index) => candidate('MCP' + index));
  const mcpResponse = await page.request.post(base + '/mcp', {
    headers:{Origin:base, Authorization:'Bearer ' + token.token, Accept:'application/json, text/event-stream', 'MCP-Protocol-Version':'2025-03-26'},
    data:{jsonrpc:'2.0', id:1, method:'tools/call', params:{name:'huhua_facts_propose', arguments:{candidates:mcpRows}}},
  });
  const mcp = await mcpResponse.json();
  check(mcpResponse.ok() && !mcp.error && !mcp.result?.isError, '真实 MCP 工具产生建议');
  await request('/api/account/mcp/tokens/' + token.id, undefined, 'DELETE');
  await page.getByRole('button', {name:'刷新档案', exact:true}).click();
  await idle();
  await page.locator('.profile-confirm-button').click();
  await page.getByLabel('选择整组：来自 AI 助手的建议', {exact:true}).check();
  check(await page.getByRole('button', {name:'确认所选（5）', exact:true}).isEnabled(), 'MCP 建议支持整组选');
  for (const row of mcpRows.slice(0, 2)) await request('/api/profile/facts', {category:row.category, subject:row.subject, field:row.field, value:'另一个窗口的新信息'});
  await page.getByRole('button', {name:'确认所选（5）', exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.profile-status')?.textContent.includes('已确认 3 条，2 条因档案已更新需重新查看'));
  await idle();
  await badge(2);
  check(await page.locator('.profile-batch-failures li').count() === 2, '过期条目逐条可见，其余已生效');
  await page.getByLabel('全选待确认信息', {exact:true}).check();
  await page.getByRole('button', {name:'不要所选（2）', exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.profile-status')?.textContent.includes('已拒绝 2 条'));
  await idle();
  await badge(0);
  check((await request('/api/account/mcp/inbox')).pending_count === 0, '批量不要后真实队列清空');
  check(writes.length === 4 && writes.every(row => row.url.endsWith('/confirmations/batch')), '所有批量操作均只用批量接口');
  await mobile('列表清空');
  await page.getByRole('button', {name:'返回已有信息', exact:true}).click();
  await importUI([candidate('可更正')]);
  await page.getByRole('button', {name:'刷新档案', exact:true}).click();
  await idle();
  const editable = (await request('/api/profile')).facts.find(row => row.subject === '批量虚构项目可更正');
  const card = page.locator(`[data-fact-id="${editable.id}"]`);
  await card.getByRole('button', {name:'更正', exact:true}).click();
  await page.getByLabel('更正本人事实', {exact:true}).fill('用户单条更正的合成信息');
  await page.getByRole('button', {name:'保存更正', exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.profile-status')?.textContent.includes('已更正个人档案'));
  check((await request('/api/profile')).facts.find(row => row.id === editable.id).value === '用户单条更正的合成信息', '导入事实支持单条更正');
  await card.getByRole('button', {name:'删除', exact:true}).click();
  await card.getByRole('button', {name:'确认删除这条事实', exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.profile-status')?.textContent.includes('已删除'));
  check(!(await request('/api/profile')).facts.some(row => row.id === editable.id), '导入事实支持单条删除');
  check(errors.length === 0, '无浏览器脚本错误');
  return {passed:true, count:checks.length, checks, screenshot:'/tmp/huhua-memory-batch-mobile.png'};
}
