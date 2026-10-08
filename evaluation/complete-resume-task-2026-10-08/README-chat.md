# 完整资料对话与刷新恢复验收

2026-10-08，本机 `127.0.0.1:8901`，独立 Playwright 会话 `huhua-complete-local`。

最终结果：`chat-complete-browser-result.json` 中 **42/42 检查通过**，页面 JavaScript 异常为 0。截图 `chat-complete-before-refresh.png`、`chat-complete-after-refresh.png` 展示真实首页和预览。

## 范围

- 使用 `tests/test_candidate_material_chat.py` 的合成资料 `CHAT_MATERIAL`，保留实际问题中的输入结构：首尾生成指令、显式姓名/联系方式、同行教育信息、没有独立项目栏目标题、三个连续项目、带冒号技能与奖项标题。
- 首页真实填入和发送；真实 `main.app`、LangGraph、确定性解析、SSE、加密 SQLite/检查点、预览渲染、读取和刷新恢复。
- `tests/complete_task_live_server.py` 复用 `product_live_server.run`：随机进程密钥和临时数据库，仅内存邮件运输，不使用真实账号或个人数据。
- 仅 `editor_chain.run_editor` 的可选润色结果使用原样返回替身；不替换 graph、`stream_agent` 或业务 API。LLM 客户端指向本机不可用端口，未配置外部模型凭证，不调用外部模型，不发邮件。
- 本次不验证模板保存、PDF、Word 或生产站点；对应验收由其他脚本负责。

## 已验证行为

首轮生成保存 3 个项目、1 条教育、2 条技能、3 条奖项，项目顺序/职责/日期及“尚未上线”“真实旅行效果尚未验证”等限定保留，教育起始时间保持空白，生成指令不进入资料。

真实 SSE 以 `[DONE]` 完成且没有 error；meta 为 `EVALUATING`、`has_data=true`，回复报告的段数与实际稿件一致，不重新采访。数据库保存恰好一条用户消息和一条助手消息；助手正文与 SSE 一致，用户消息与提交的正文一致（前端会去掉首尾空白）。

刷新后会话 ID、阶段、完整稿件和两条消息一致，预览仍有项目、教育、奖项；未重新发起生成，最终验收仅调用一次原样润色替身。

控制台另有既有的 `favicon.ico` 404 与打包 Tailwind 提示，见 `chat-complete-browser-console.log`；这些不属于页面 JavaScript 异常，因此没有宣称控制台完全无错误。

## 复跑

```sh
.venv/bin/python tests/complete_task_live_server.py --port 8901
playwright-cli -s=huhua-complete-local open http://127.0.0.1:8901
playwright-cli -s=huhua-complete-local run-code --filename=tests/complete_task_live.browser.js --raw
playwright-cli -s=huhua-complete-local close
```

服务与浏览器需要本机监听/进程启动权限。结束时停止该 fixture 进程，临时数据库随上下文退出清理，不操作其他浏览器会话。

本次清理已完成：fixture 收到 SIGINT 后正常退出（exit 0），已确认 8901 没有监听进程；专用浏览器会话查询为未打开。没有关闭其他会话。

## 初次脚本调整

保留两次未完成验收的结果，避免与最终通过结果混淆：

- `chat-complete-browser-cdp-attempt.json`：业务请求已成功，但 Chromium 未保留 SSE response body，`response.text()` 失败。脚本改成对真实浏览器 fetch response 做 `clone().text()` 旁观采集，不拦截/替换请求或响应。
- `chat-complete-browser-whitespace-attempt.json`：业务内容已正确保存，脚本错误地要求保留末尾换行；按真实前端的首尾空白规范修正比较。

最终 audit 中的 editor 总调用数为 3，baseline 为 2，差值为本次成功验收的 1 次；前两次业务生成也成功，但未通过完整脚本检查，不计入最终 42 项。
