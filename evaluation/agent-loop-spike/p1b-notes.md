# 第十七批第 1 期 P1b：编排节点与接线

仅负责 `batch17b` 的编排、配置、路由、流式事件及前端结构。已完整阅读本期规格、spike 源码、README、fix-notes 和六份 real-* Markdown 报告。真实模型记录只作为本期设计依据；本任务未调用真实模型。

## 根因与改动

- 原图只按阶段和确定性意图分流，spike 没有生产状态更新、checkpoint、SSE 或前端入口。新增 `backend/app/agents/orchestrator.py`，工具增量按 LangGraph 原有字段语义替换，`messages` 使用 `add_messages`；已记录事实沿用独立 intake 保存，节点结束仍走原 SQL/canonical 保存与 checkpoint 对账。
- 当前 LangChain 消息往返不保留思考扩展字段。生产节点直接使用 OpenAI SDK 的流式接口，复用 spike 的协议检查与开关函数，完整回传本轮 reasoning_content/tool ID。工具尝试最多 4 次，模型请求最多 5 次（失败及降级请求也计数）；每次模型/工具执行有超时，SDK 自动重试关闭。思考协议错误或 HTTP 400 只降级一次，不重做已执行工具；联系方式出现在必须原样回传的 reasoning/ID 时终止。最终公开文本已开始发送时不重试，追加中断说明。
- 旧路径结束时可能把收集材料直接投影成草稿。loop 自由输入关闭这项兜底，只有工具返回的稿件进入保存；防止记录事实后还没写稿就出现简历。
- `AGENT_MODE=off` 为默认，配置字段缺失也视为 off。`route_by_stage` 顶部仅把自由输入分到 orchestrator，intake/answers/plan_choice/requested_task 继续走旧路径；编辑器和导出 API 未修改。测试入口固定 off，独立 loop 测试显式启用。
- loop 的 `intake_guidance` 不再自动出表单，工作区不自动拼下一步问题卡；问题卡仍通过 `AskUser` 的参数、关闭记录及停止追问约束校验。移除的是 loop 的阶段门槛，不是字段/关闭记录校验；方案卡仍由 pending_plan 恢复。
- 新增只返回模式的 `GET /api/chat/agent-mode`，保持原 `/tools` 响应不变。首屏四个按钮发送引导文本，使用 auto、保留输入草稿和附件、防重复点击。工具状态通过独立 SSE 对象进入聊天进度行，使用 textContent；不混进正文。事件卡片沿用工作区组件。

## 文件范围

- 新增：`backend/app/agents/orchestrator.py`、`backend/app/agents/orchestrator_tools.py`（仅契约 stub）、`web/orchestrator-ui.js`。
- 小幅接线：`backend/app/config.py`、`backend/app/agents/resume_graph.py`、`backend/app/api/chat.py`、`backend/app/services/{intake,ask_user,resume_workspace}.py`、`web/index.html`、`web/resume-workspace.js`、`scripts/run_tests.py`。
- 新增测试：`tests/test_orchestrator.py`、`tests/test_orchestrator_ui.py`。未修改旧测试断言、spike cases、真实报告、人物回放脚本、业务工具实现或 dist。

## P1a 合并接口

`orchestrator_tools.py` 是可替换的最小 registry：十个工具只有参数模型和描述，所有 handler 都返回 `unavailable / adapter_not_installed`、空 update/events、stop=True，不模拟业务成功。合并时用 P1a 实现替换这个文件；本分支本身不具备写稿/事实抽取业务能力。

当前 `ToolSpec(args_model, description, handler)` 三个字段分别为 Pydantic 模型类、描述、async handler；handler 调用为 `handler(state, args, ctx)`，其中 args 为已验证的 Pydantic 实例。`ToolOutcome(result, update, events, stop=False)` 严格保持规格四字段。`result` 应为 JSON 可序列化字典；update 只能包含 ResumeState 字段，嵌套字段整体替换，不做深层拼接，空值/空列表也保留。

`ctx` 为本轮字典：`llm`（原业务模型）、`sources`（`id -> {text, kind}`，原始用户文本只供代码取证）、`source_id='current'`、`privacy`（本轮 ContactRedactor）、`reply_id`。current 与最新历史消息 ID 指向同一来源。record_facts/read_jd 参数只接收 source_id；编排先检查来源存在及非 JD/reference/review，再委托适配器做本人归属、事实验证、落库等。业务模型入口仍必须自行脱敏，不能直接发送 ctx.sources 原文。

工具返回结果及历史/状态统一序列化、ContactRedactor 脱敏、包入 untrusted_data；不向系统提示注入动态资料。每轮日志 `orchestrator_turn` 和最终 AIMessage.additional_kwargs.orchestrator 仅含调用次数、token、耗时、降级/错误类型/HTTP 状态，不含正文、参数、思考或凭证。此计数只涵盖编排 SDK 请求，不冒充适配器内部模型调用总成本。

界面事件格式：

```python
{"type": "tool_status", "tool": "record_facts", "status": "running", "message": "正在记录你的经历…"}
{"type": "guidance", "guidance": validated_card}
{"type": "workspace", "workspace": workspace_snapshot}
```

编排为每次工具尝试发 running/completed，另转发适配器 events；不传 reasoning 或 raw tool 参数。ask_user guidance 会经现有校验后附在最终 AIMessage，刷新仍可恢复；适配器也可在 update.messages 放已校验的卡片消息。方案卡需要 update.pending_plan 等原状态字段，不能只依赖一次性事件。业务适配器应返回事件和消息增量，避免在内部自行发布额外 public_reply 流。

stop=True 严格表示下一次只能最终回复，同批后续工具也不执行。规格中写稿 stop 与写后补问同时存在，本分支按 stop 契约收束；未执行的 ask_user 留后续轮，不擅自忽略 stop。达到预算同样强制最终回复。

`tool_choice=none` 的最终回复实时发布 `public_reply_delta`，只存一条完整最终消息；auto 响应可能混合正文与迟到工具调用，因此先缓冲，确认没有工具后才发布文字，不另加一次模型请求。不能把这类无工具回复的缓冲延迟说成已经消除；真实首字耗时待回放。

## 本地验证

新增测试覆盖：默认/非法模式、所有阶段自由输入路由、结构化动作、关闭自动表单与保留合法问题卡、stub 明确不可用、字段替换与消息合并、事实先保存和最终模型失败、工具预算/批量超额/stop、每轮一次公司查询、历史来源/参数边界、单次降级及不重复工具、隐私全边界、reasoning 联系方式终止、工具超时、取消、卡片恢复、真实 SDK MockTransport 分片/usage、真实 LangGraph + 隔离 SQLite 跨轮保存、HTTP SSE 对象透传、前端模式/点击/文本安全。全部使用假模型或内存 transport。

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py -p 'test_orchestrator*.py'
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

最终指定全量：**2036 项，2034 通过、2 项原有私有样例跳过，0 失败、0 错误，407.757 秒，退出码 0**。包含新增 23 项测试和原有 17 项 spike 测试。最终日志为本目录 `p1b-full-tests.log`；`p1b-targeted-tests.log` 保留中间排查记录（含下述测试初始化错误），不作为最终验收依据，两者均按仓库规则忽略。新增 Python 文件 Ruff 通过，独立与 HTML 内联 JS 语法检查通过，交接 shell 片段仅做 zsh 语法检查、未执行；diff 空白检查通过。

## 失败做法与修正

- 首轮全量 2032 项出现 12 个配置兼容错误：旧精简配置对象没有 AGENT_MODE。代码改为缺字段默认 off，未改旧断言；保存时仅检查编排选择条件，不重新执行整套旧路由。
- 新增测试辅助函数原以 name 为位置参数，与 search_company(name) 冲突；改名为 tool。HTTP 测试首次未初始化额度表，已将 runtime_limits 模型注册前移到隔离库建表前，未绕开额度实现。
- 虚拟环境未安装 Ruff Python 模块，改用已有 `/opt/homebrew/bin/ruff`，未安装依赖。
- 不直接把 auto 响应 token 当最终正文：工具选择可能在后续分片出现。保留缓冲，强制最终阶段才实时发布，避免工具旁白重复显示。

## Claude 接手与未完成

P1b 本地实现及离线验证不代表真实模型验收。仍待合并 P1a/P1c，核对 ToolSpec/ctx 字段和业务结果、fact_guard/联系方式投影/版本撤销、真实回放及视觉调整。未运行任何服务、未访问 8833/8834、未调用真实模型、未 commit/push/部署。

以下命令仅留给 Claude，在合并三支后的仓库根目录运行；需已配置有效模型与本地存储/账号设置，P1c 已加入 cold/upload/returning 人物。端口使用 8847，数据库独立创建；不会连接旧测试实例：

```sh
(
  set -eu
  P1B_PYTHON="/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python"
  P1B_REPLAY_DIR=$(mktemp -d "${TMPDIR:-/tmp}/huhua-p1b.XXXXXX")
  export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib AGENT_MODE=loop APP_ENV=local
  export DATABASE_URL="sqlite:///$P1B_REPLAY_DIR/application.sqlite3"
  export CHECKPOINT_DB_PATH="$P1B_REPLAY_DIR/checkpoints.sqlite3"
  "$P1B_PYTHON" - <<'PY'
import socket
with socket.socket() as probe:
    probe.bind(('127.0.0.1', 8847))  # 已占用则停止，避免误连其他实例。
PY
  "$P1B_PYTHON" -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8847 > "$P1B_REPLAY_DIR/server.log" 2>&1 &
  P1B_SERVER_PID=$!
  trap 'kill "$P1B_SERVER_PID" 2>/dev/null || true; wait "$P1B_SERVER_PID" 2>/dev/null || true' EXIT INT TERM
  "$P1B_PYTHON" - <<'PY'
import json, time, urllib.request
for attempt in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8847/api/chat/agent-mode', timeout=1) as response:
            assert json.load(response)['agent_mode'] == 'loop'
        break
    except OSError:
        time.sleep(.5)
else:
    raise SystemExit('隔离服务未就绪，请检查临时目录中的 server.log')
PY
  kill -0 "$P1B_SERVER_PID"
  "$P1B_PYTHON" evaluation/persona-ux/run_persona.py --base http://127.0.0.1:8847 --agent-mode loop \
    --persona cold,upload,returning --returning-db "$P1B_REPLAY_DIR/application.sqlite3" --timeout 600
  # 对比基线：按 P1c 的默认人物集合再跑一遍，使用新的输出目录。
  "$P1B_PYTHON" evaluation/persona-ux/run_persona.py --base http://127.0.0.1:8847 --agent-mode loop \
    --returning-db "$P1B_REPLAY_DIR/application.sqlite3" --timeout 600
)
```

服务日志中的 orchestrator_turn 可核对每轮编排请求数/耗时/token/fallback；供应商未报告的 token 保留 null。真实模型质量、人物通过率、业务工具联调与首字延迟由 Claude 回放后记录，不能用本轮桩指标替代。
