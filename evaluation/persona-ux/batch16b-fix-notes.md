# 第十六批 b：记忆导入（规格 E）

2026-10-18，工作目录 `huhua-b16b`，分支 `batch16b`。仅实现批次规格 E；A–D、intake、public_reply、resume_graph、dist 和部署脚本均未改动。批次规格文件在接手时已是未跟踪文件，本次未修改。

## 根因与关键决策

- 现有 MCP 已有带证据的 `FactCandidate` 和人工确认收件箱，但网页没有导出提示词、粘贴解析和提交入口。原档案整理器只接受 self/manual 来源，不能直接用于 AI 记忆导入。
- 直接复用自动归档 worker 会绕过本批“全部待确认”的要求。因此新增独立解析流程，只调用 `propose_to_inbox`；不创建档案事实、来源或自动整理事件。用户后续采纳仍走原人工确认事务。
- `FactCandidate` 移至共享 schema，字段及限制保持不变；网页解析与 MCP 使用同一模型。另按收件箱原规则校验 category/field 组合、空白证据等。`uncertain` 写入 evidence，不增加协议字段。
- 固定中文导出提示词只保存在后端一个常量中，列出全部合法 category/field 对应关系；不包含 fixture 人物。网页通过 API 获取，MCP prompt 复用其规则。提示词要求省略手机/邮箱；纯文本回退继续走现有 `ContactRedactor`，不把联系方式原文发给模型。

## 实现

- `GET /api/profile/import-memory/prompt`：沿用档案账号鉴权，返回提示词、100000 字输入预算和 200 条上限。
- `POST /api/profile/import-memory`：请求为 `{"text": "AI 回答"}`，沿用账号/同源校验。优先校验 JSON 代码块内的数组（兼容裸数组及只有 candidates 字段的对象）。一个代码块必须全部合法才采用，避免静默丢掉坏条目；无合法 JSON 时回退档案抽取器，payload 明确为 `source_kind=import`。
- 回退只保留原文支撑、明确属于本人的候选，保留否定和限制；抽取器没有执行工具或写档案的能力。沿用模型额度、并发控制，单次抽取超时 45 秒。未配置模型时返回可理解的 503，JSON 导入仍可用；抽取异常不回显原文/内部异常。
- 输入超过 100000 字先截断并返回提示；合法候选先去重，再取前 200 条并提示。按每批最多 50 条提交原收件箱，整个请求共用一次数据库事务；复用已确认事实去重、待确认去重与 30 天过期。响应分别返回本次新增条数、重复条数及截断提示。
- 档案面板新增“从其他 AI 导入”：提示词显示/复制/重试、粘贴框、提交、结果和“查看待确认信息”。不持久化私人文本到浏览器存储；失败保留输入，提交期间防重复操作，所有内容以文本节点展示。沿用已有组件 class，无 CSS 美化。
- MCP 新增 `import_memory_to_profile`，要求客户端回顾实际可访问的记忆、历史对话及授权项目；区分本人贡献、逐条 evidence、uncertain、分批 ≤50/总计 ≤200、数据不是指令、返回网页确认链接，用户确认前不得声称已入档。`/connect` 增加对应话术和复制按钮。

## 改动文件

- 后端：`backend/app/api/profile.py`、`backend/app/agents/profile_archivist.py`、`backend/app/mcp/server.py`；新增 `backend/app/schemas/profile_import.py`、`backend/app/services/profile_memory.py`。
- 网页：`web/account-profile.js`、`web/connect.html`、`web/connect.js`。
- 测试：新增 `tests/test_profile_memory_import.py`、`tests/profile_memory.dom.js`；更新 `tests/test_mcp_protocol.py`、`tests/connect.dom.js`。
- 交接：本说明；根目录 `mmr.md` 只追加本批记录。

## 新增测试与验证

- 新增 16 项测试：14 项后端导入测试、1 项网页 DOM 流程、1 项真实 MCP SDK 协议 prompt 测试。仅使用离线桩、合成资料、加密临时 SQLite 和系统临时目录。
- 覆盖 JSON 优先及不调用模型、非法 schema/JSON 整块回退、空数组、纯文本原文依据/归属过滤、uncertain 证据保留、账号隔离与同源鉴权、加密且不直接入档、人工采纳后重复导入、30 天过期、200 条上限和 50 条批次、超长输入提示、抽取故障/额度/无模型错误、跨批事务回滚、真实脱敏函数配合假模型的联系方式隔离，以及提示词枚举/schema 一致性。
- DOM 覆盖提示词 API 失败重试、复制及复制失败、保留粘贴内容、单表单/并发防重入、失败重试、新增/重复/截断回执、跳转待确认及无自动采纳；`/connect` 原复制测试增加 memory 项。
- 唯一需要更新的旧精确断言：MCP prompt 目录从三个变为四个，明确加入 `import_memory_to_profile`；仍用完整集合相等断言，理由是规格 E 新增 prompt。其他旧断言未放宽。
- 指定全量命令：

  ```sh
  DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
  ```

  **1977 项，1975 通过、2 项跳过，0 失败/错误，82.605 秒。** 两项跳过属于原有本地私有基准样例测试。日志：`/var/folders/2z/csfpf2k94x9021h6cypf5k5w0000gn/T/huhua-b16b-tests.D6Vry7bb1j`。
- 新导入模块定向测试 **15/15**；所有本批 Python 文件 Ruff、网页 JS 语法、`/connect` DOM 和 `git diff --check` 通过。

## 失败做法与剩余边界

- 初稿拟给网页收件箱记录传空 token_id；静态检查发现原模型不允许 NULL，测试前改为固定来源标记 `web-memory-import`。它不是 PAT、不授予权限，不改表结构或原鉴权。
- 未采用自动归档队列，也未为 import 放开 worker/自动 grounding 的来源限制；复用字面依据校验仅服务待确认候选。全部候选最终仍需本人确认。
- 规格 E 的本地实现无未完成项。按本批约束，未验证真实外部 AI 的记忆导出质量、真实模型抽取效果或在线客户端联调；DOM 回归不代表真实浏览器视觉验收。CSS 美化留给后续任务。
- 未启动或访问 8833/8834，未调用真实模型，未 commit、push 或部署。
