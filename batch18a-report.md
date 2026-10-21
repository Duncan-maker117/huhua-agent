# 第十八批 a：输入框灰色提示与 edit_url 跨账号提示

日期：2026-10-21。分支 `batch18a`，基线 `627a06f`。仅本地修改，没有 commit / push / 部署，也没有调用真实模型。

## 已完成与设计取舍

### 输入框提示

- loop 沿用原有模型调用，在最终正文后附可选的 `<next_hint>…</next_hint>`。现有接口是流式正文与工具调用，并无结构化最终响应，因此增加小型结构化尾部；流式解析器跨 token 识别、剥离尾部，提示不会混入正文。不额外调用模型，不改原调用预算。
- 模型从 13 句通用用户意图中选择，例如「补充一下这段实习的具体成果」「帮我换成简约模板」。代码拒绝数字（含 Unicode 数字）、`@`、`http`、空值、非字符串、超过 30 字以及白名单外文本。白名单比简单黑名单严格，可同时阻止虚构公司、学校、职责或成果；代价是提示表达范围较窄，不支持具名定制。
- 问卡在场、无合法提示或编排失败时省略字段。完成保存后发送 SSE `{"type":"next_hint","next_hint":"…"}`；前端等 `[DONE]` 且无错误/取消才使用。历史消息接口不回放提示。
- 输入框为空才显示；桌面附「 · Tab 采用」，≤640px 只显示提示。空框 Tab 仅填入文本、光标置末尾，不发送；非空、Shift/修饰键及输入法组字保留默认行为。输入、新消息、切换/新建会话、退出及取消都会清掉提示。非 loop 保持字段缺省。

### edit_url 跨账号

- MCP save/export 的 `edit_url` 新增 `from=mcp`，保留原 session/template 参数。编辑页读取与返回聊天链接传递标记；聊天页只在读取初始链接会话时传递。
- 仅 `/api/resume/current` GET 和 `/api/chat/conversations/{id}` GET 的带标记、已登录请求可得到 `403 conversation_other_account`。判断复用归属查询，仅使用归属、有效期等元数据，不解密简历内容或标题。响应仅含固定错误码和说明，不含标题、内容、所属邮箱、账号 ID 或会话 ID，并设置 `Cache-Control: no-store`。
- 普通读取仍为原 404；无效来源、未登录、不存在/删除/过期会话，以及写入/删除等接口保留原鉴权行为。
- 编辑页与聊天页显示指定说明和「退出登录」。抽出并复用原退出操作、清缓存和重置事件，保留原确认提示；此按钮返回完整原链接，普通退出仍回 `/chat`。未登录时沿用登录流程，聊天 MCP 链接不再被游客新会话替换。
- `from=mcp` 是来源提示而非授权凭证，可由请求者自行添加。按要求允许已登录者探测已知 UUID 是否属于其他账号；它绝不赋予读取或修改权限。

## 文件清单

- 后端：新增 `backend/app/agents/next_hint.py`；修改 `agents/orchestrator.py`（同次回复解析与元数据）、`agents/resume_graph.py`（保存后的 SSE）、`api/conversations.py`、`api/resume.py`、`services/access_control.py`（受限错误说明）、`services/mcp_service.py`（链接标记）。上述相对路径均在 `backend/app/` 下。
- 前端：`web/index.html`（placeholder/Tab/SSE）、`web/conversation-history.js`（会话重置与跨账号提示）、`web/resume-editor.js`（编辑页提示）、`web/account-profile.js`（共享退出）。
- 资源版本：按 `15c24c9` 的范围更新 `web/index.html`、`web/resume.html`、`web/home.html`、`web/connect.html` 为 `20261021-1`；额外更新本次修改的 `conversation-history.js` 引用。
- 测试：新增 `tests/test_batch18a.py`、`tests/batch18a.dom.js`；更新 `tests/test_mcp_b17m.py` 的链接期望及 `tests/test_home_page.py`、`tests/test_mcp_ui.py` 的版本期望。所有新增 Node DOM 测试使用 `skipUnless(shutil.which('node'))`。
- 交接：本报告、精简 `mmr.md`，旧长交接完整归档到 `mmr-archive.md`。保留开场已有的未跟踪 `prompt-batch18a.md`，未修改它。

## 验证

新增 19 项离线测试，覆盖过滤、任意 token 分割、残缺协议、同次模型调用、问卡抑制、真实 LangGraph → 保存 → SSE、历史省略、两个真实隔离登录账号的读取隔离、删除/不存在/未登录/写操作边界及四组实际前端控制器 DOM 场景。模型用 HTTP MockTransport，账号用隔离 SQLite 与邮件桩。

- 相关回归：`scripts/run_tests.py -k test_batch18a -k test_resume_persistence`，32 项通过。
- 最终全量：**2240 项，2238 通过、2 项原有跳过，0 失败/错误，104.967s，退出码 0**。基线 2221 项，本批新增 19 项。最终日志结尾为 `Ran 2240 tests in 104.967s / OK (skipped=2)`。
- 修改的 11 个 Python 文件 Ruff 全通过；修改的 JS 与 index 内联脚本语法检查通过；`git diff --check` 通过。
- 首轮全量 2240 项中，旧浏览器身份 Request fixture 没有 query_string，新增逻辑过早读来源参数导致 3 个子场景错误。已把账号身份判断放在查询串读取之前，未改旧断言；相关 32 项复验通过。首次定向运行时 DOM 文件尚未写完导致 4 个缺文件错误，文件补齐后四组 DOM 与定向回归全部通过。

指定全量命令：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

日志：`/private/tmp/huhua-b18a-full-final.log`；定向日志：`/private/tmp/huhua-b18a-targeted-final.log`。

## 未做与风险

- 没有调用真实模型，因此尚未验证线上模型选择提示的频率与相关性；不合规/残缺提示会省略，保留默认 placeholder。
- 没有真实浏览器/移动设备人工验收、真实账号邮件联调或部署验证；前端已执行 Node DOM 和 JS 语法验证。
- 以前生成且没有 `from=mcp` 的旧链接仍按普通接口处理，不自动区分跨账号；新的 MCP edit_url 才带标记。
- 没有数据库迁移、依赖变更、部署配置变更或范围外业务重构。
