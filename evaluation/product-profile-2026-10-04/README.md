# 前端产品化本地验收

日期：2026-10-04。所有浏览器业务 API 与模型流均使用虚构数据拦截；只读取本地静态资源，不访问真实用户数据库或模型服务。

- 账号、个人档案、建议采用：29 项通过，见 `product-ui-result.json`。
- 档案到简历编辑页：6 项通过，见 `editor-profile-regression.json`。先保存已有改动；保存失败阻止采用；成功后刷新当前稿。
- 现有右侧工作区：54 项通过，见 `workspace-regression.json`。
- 流式对话：23 项通过，见 `stream-regression.json`。
- 历史对话：37 项通过，见 `history-regression.json`。

这些是不同场景的检查数量，不代表产品覆盖率或线上用户验收。编辑器、服务端账号、加密、档案Agent、真实模型与导出的一体化验收由主任务另行记录。

界面已加入账号与唯一档案抽屉；手工事实、来源、冲突、更正、删除、整理失败重试、岗位版本与档案采用。建议原句必须从当前简历可唯一定位的字段选择，采用前展示依据，绑定服务端修订，支持撤销。

浏览器不再把聊天全文或简历 JSON 长期存入 localStorage/sessionStorage；启动清除旧敏感缓存。当前页面保留内存恢复稿，未保存内容离页时提醒，刷新从服务端恢复。退出后清空本页状态。邮件服务未配置时明确告知，账号要求未知时默认需要登录。

手机 390px 档案截图：`../product-profile-mobile.png`，已目视检查。

测试源码：`tests/product_profile.browser.js`、`tests/profile_editor_integration.browser.js`、`tests/resume_workspace.browser.js`、`tests/chat_stream.browser.js`、`tests/conversation_history.browser.js`。使用专用 8893 静态服务，其中 `/static/*` 映射到 `web/*`，`/resume` 映射到 `web/resume.html`。旧脚本本次仅在临时副本将 8765 换为 8893，测试逻辑与库内相同。

另定向更新旧服务端集成测试：`test_conversations.py` 的 11 项、`test_public_beta.py` 的 3 项分别通过。均使用临时 SQLite、临时 checkpoint 和明确的 local/匿名测试设置；验证裸会话 ID 无法认领、SQL 已提交简历优先、实际浏览器 Cookie 归属，以及持有归属凭证后读取/导出/删除。
