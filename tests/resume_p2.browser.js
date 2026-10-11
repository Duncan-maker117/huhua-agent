// Run against the fictional P2 fixture prepared by the verification report.
async (page) => {
  const checks = [];
  const check = (condition, name) => { if (!condition) throw new Error(name); checks.push(name); };
  const input = path => page.locator(`[data-input-path="${path}"]`);
  const preview = path => page.frameLocator('#preview-frame').locator(`[data-field-path="${path}"]`);
  const settled = () => page.waitForFunction(() => document.getElementById('render-status').textContent === '已实时更新');
  await page.setViewportSize({width: 1440, height: 960});
  await page.goto('http://127.0.0.1:8765/resume');
  await settled();
  check(await input('/open_source/0/name').inputValue() === 'StarBoat 项目', '仓库名编辑字段');
  check(await input('/open_source/1/pr').inputValue() === 'PR #8', '第二条 PR 编辑字段');
  check(await input('/awards/2/level').inputValue() === '二等奖', '第三条荣誉编辑字段');
  check(await input('/education/0/major').inputValue() === '计算机科学与技术', '教育专业保留');
  check((await input('/education/0/highlights').inputValue()).includes('奖学金'), '教育荣誉保留');
  check(await input('/basic_info/links/1/url').inputValue() === 'example.test', '个人主页编辑字段');
  check((await preview('/open_source/1/bullets/0').textContent()).includes('等待审核'), '第二条贡献预览');
  await input('/open_source/1/bullets/0').fill('修复文件校验，已提交等待审核。');
  await settled();
  check(await preview('/open_source/1/bullets/0').textContent() === '修复文件校验，已提交等待审核。', '贡献正文实时同步');
  await input('/basic_info/availability').fill('每周5天，持续6个月');
  await settled();
  check(await preview('/basic_info/availability').textContent() === '每周5天，持续6个月', '实习时间实时同步');
  await input('/basic_info/links/1/url').fill('new.example.test');
  await settled();
  check(await preview('/basic_info/links/1/url').textContent() === 'new.example.test', '页头链接实时同步');
  await input('/awards/2/level').fill('省级二等奖');
  await settled();
  check(await preview('/awards/2/level').textContent() === '省级二等奖', '荣誉级别实时同步');
  for (let index = 0; index < 6; index += 1) {
    await page.locator('.tpl-item').nth(index).click();
    await settled();
    check(await preview('/open_source/1/pr').textContent() === 'PR #8', `模板 ${index + 1} 保留 PR`);
    check(await preview('/awards/2/level').textContent() === '省级二等奖', `模板 ${index + 1} 保留荣誉`);
  }
  await page.locator('[data-section-id="open_source"]').getByRole('button', {name: '＋ 添加开源贡献', exact: true}).click();
  await input('/open_source/2/name').fill('新仓库');
  await input('/open_source/2/pr').fill('PR #9');
  check(await input('/open_source/2/pr').inputValue() === 'PR #9', '开源贡献可新增');
  await page.locator('[data-section-id="awards"]').getByRole('button', {name: '＋ 添加竞赛荣誉', exact: true}).click();
  await input('/awards/3/name').fill('示例校创新赛');
  check(await input('/awards/3/name').inputValue() === '示例校创新赛', '竞赛荣誉可新增');
  return {passed: checks.length, checks};
}
