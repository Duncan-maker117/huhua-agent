# 第十七批 P1a：工具适配器

## 范围与根因

只新增 `backend/app/agents/orchestrator_tools.py`、`tests/test_orchestrator_tools.py`、本说明，并在根 `mmr.md` 末尾追加交接。未修改路由、编排循环、配置、前端、第 0 期 cases/报告或 P1c 回放脚本。既有节点与测试断言不变。

已完整阅读本期规格、spike 源码、README、fix-notes 及六份 real 报告。第 0 期是“真实编排模型 + 假工具”；其序列和延迟不能证明生产工具可以保存、改稿或保护事实。本期只验证真实业务适配器的离线行为，不重新评价模型工具选择。

直接调用 collecting/building/evaluating 整个节点会同时触发分流、阶段门槛、历史事实恢复和公开回复，违反单一工具职责及“事实只经 record_facts”的边界。因此复用它们实际调用的抽取、持久化、写稿/编辑契约、版本及测页服务，没有复制阶段路由。

## 改动

- `ToolOutcome(result, update, events, stop=False)` 与规格一致。十个工具均有严格 Pydantic 参数，额外字段拒绝；只有 `source_id` 能选取原始 HumanMessage，工具参数不能提供事实正文。
- `record_facts`：本人/他人来源判定、明确混合材料拆分、旧简历确定性导入、`extract_facts_patch → apply_fact_patch`、教育字段恢复、原始消息 ID 与来源引用、未提取内容提示。通过既有 `_persist_intake` / `_intake_saver` 先存事实，不生成草稿或公开回复。保存失败返回错误，同一轮不会误标来源已处理。
- `read_profile/use_profile_items`：直接包装既有账号服务；采用前必须读取目录，服务端再验证当前账号和会话、条目状态，保留 profile_refs。游客返回 unavailable。
- `read_jd`：复用 decoder 和受限 job_intel 链接读取，失败保留旧岗位；只更新岗位、策略和来源，不写个人事实。混合消息保留本人段落供 record_facts 使用。
- `search_company(name)`：复用 job_intel；每轮一次，失败也消耗次数，与既有 current_turn 限制兼容。公司名含联系方式时不查询。结果只更新岗位参考。
- `ask_user(card)`：复用 AskUser/AskQuestion 校验和已关闭维度判断；不受旧 intake 自动表单门槛阻挡。每轮一张卡，尊重停止追问、已关闭维度和 pending_plan。卡片保存在 AIMessage.additional_kwargs，并返回 guidance 事件，stop=True。
- `propose_plan()`：调用现有 writer 的 plan 阶段和 plan_guidance，不写正文；已有待选方案直接复用，stop=True。
- `write_draft(direction?, emphasis?)`：只有已记录的具体行动/方法/交付物等可以出稿；单有教育、条目名称或状态限制返回 insufficient。缺姓名、手机或邮箱返回 need_contacts，并列出 missing。通过 tailor 的 fact_guard、槽位校验、测页和版本链出稿；不触发旧表单/方案门槛，成功返回 stop=True。新方向更新目标，不写入本人事实；相同方向保留原 JD。
- `edit_resume(instruction)`：复用范围定位、编辑契约和确定性操作服务；字段/删除的字面授权只取真实用户消息，不信任模型改写的参数。新事实修改返回 record_facts_first；局部写稿保留无关内容，版本快照支持撤销。上游失败保留旧稿，错误类型可见而错误正文不泄露。
- `check_layout()`：调用生产模板的 measure_resume_pdf_layout，只测当前排版，不自动选密度、不改正文、不写 PDF。测量绑定当前文稿 hash，失败保留旧测量。
- 模型可见 result 再经 ContactRedactor 和 JSON 文本脱敏（包括伪装媒体对象）。update 保留本地真实联系方式。实际 extractor/decoder/writer 仍沿用各自出站脱敏；电话、邮箱由代码从事实母版投影进文稿。写稿/方案序列化不从聊天历史补未记录字段。

## 合并接口（给 P1b / Claude）

```python
from app.agents.orchestrator_tools import TOOLS, ToolContext, execute_tool, tool_schemas

ctx = ToolContext(llm=business_llm, turn_id=user_turn_id, emit=stream_writer)
# 同一个用户轮内复用 ctx；下一用户轮重新创建。不要放进 checkpoint 或模型输入。
schemas = tool_schemas()  # OpenAI Chat Completions function schemas
spec = TOOLS[name]       # spec.args_model / spec.description / spec.handler
outcome = await spec.handler(state, parsed_arguments, ctx)
# 或：outcome = await execute_tool(name, state, parsed_arguments, ctx)
```

`ctx.llm` 是现有业务 ChatOpenAI，不是编排 SDK client；可用 `structured_llm` 单独传抽取/解码模型。handler 同时接受参数字典或相应 Pydantic 对象。`source_id="current"` 指最近用户消息；历史来源必须是本会话 HumanMessage.id，不能取 AIMessage、摘要或模型生成文本。

工具不自行合并状态。调用方按 ResumeState 合并 outcome.update：messages 使用 add_messages，其余增量覆盖相应字段，然后将最新状态交给下一工具。只有 outcome.result 给模型，并按规格包入 untrusted_data；update/events 不能作为完整模型上下文直接发送。

`ctx.emit` 立即发送 running/completed 两条 tool_status；同样两条也保留在 outcome.events。设置 emit 的调用方应跳过 events 中重复的 tool_status，只发送其余 guidance 事件；未设置 emit 时可统一发送 events。completed 表示本次尝试结束，业务是否成功以 result.status 为准。工具取消继续抛 CancelledError，错误只返回类型，不返回供应商正文。

ask_user 的事件为 `{"type":"guidance","guidance":<既有 ask_user 卡>}`；方案卡同型、kind=structure_plan。P1b 需将问题卡 metadata 保留在最终助手消息，或让卡片消息与最终回复一起参与状态 reducer；跨轮恢复/答卡时须配合 loop 模式关闭旧 intake 的卡片优先级。此文件没有修改 workspace 或 answer 路由。工具 stop 严格按规格：ask_user/propose_plan/成功 write_draft 后直接最终回复；第 0 期允许的“写后再调用 ask_user”序列与这里的 stop 由编排集成方统一处理，本适配器不私改协议。

生产 stream_agent 已设置 `_intake_saver`；应保留该上下文，让 record_facts 和档案采用先存事实。直接调用 handler 而未设置 saver 时，仅返回本地状态增量，不能称 SQL 已落库。事实中的历史 source_id/provenance 保留；既有后台归档回调仍按当前用户消息入队，不把历史工具选择伪装成新的用户原话。

总体 ≤4 次工具、工具/模型超时、思考协议降级、编排 token/调用数日志、checkpoint/SQL 文稿最终保存由 P1b 承担。现有业务调用保留 label_run 标记；不能只用编排 SDK usage 代表包含嵌套写稿/校验的总成本。

## 验证

新增 36 个离线测试，定向运行全部通过。覆盖原始来源/历史消息 ID、JD 和他人材料隔离、混合材料拆分、真实抽取器出站脱敏、先存事实及保存失败、真实隔离 SQL/账号档案与 provenance、问题卡约束、最低出稿条件、真实 writer/fact_guard 拒绝虚构数字、局部编辑/撤销、当前密度测页且禁止 PDF 序列化、事件顺序和取消传播，以及未记录历史不能进入写稿。

最终按指定命令运行全量：`Ran 2049 tests in 92.964s`，`OK (skipped=2)`，退出码 0，即 2047 通过、2 跳过、0 失败。新增测试在全量发现环境下定向复验：36/36 通过（0.280s）。最终日志为 `evaluation/agent-loop-spike/p1a-full-tests-final.log`，定向日志为 `p1a-tests.log`（日志按仓库规则忽略，不作为提交文件）。

Ruff、Python 语法、新增文件空白检查和真实 smoke 命令语法/案例路径已通过。没有放宽或修改任何旧测试断言。

离线复验（仓库根目录）：

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py -k OrchestratorTools
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
ruff check backend/app/agents/orchestrator_tools.py tests/test_orchestrator_tools.py
git diff --check
```

## 留给 Claude 的真实业务工具 smoke

以下命令本任务**没有执行**。它直接调用真实 decoder/writer/guard 和本地测页，不启动 HTTP 服务，不访问 8833/8834，不测编排模型的工具选择，也不代表 cold/upload/returning 端到端验收。读取现有合成案例文件，不将人物内容写入系统提示或手册；输出仅含状态、耗时和页数。需使用有真实配置的环境；状态增量只在本进程内存，临时数据库随后清理。

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib PYTHONPATH=backend "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" - <<'PY'
import asyncio
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter
from dotenv import dotenv_values

async def main():
    env_file = Path(os.environ.get("P1A_ENV_FILE", "../huhua agent/backend/.env"))
    config = {**dotenv_values(env_file), **os.environ}
    required = ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL")
    if not all(config.get(key) for key in required):
        raise SystemExit("缺少显式 LLM 配置；未调用模型")
    with tempfile.TemporaryDirectory(prefix="huhua-p1a-real-") as directory:
        root = Path(directory)
        os.environ.update({key: config[key] for key in required})
        os.environ.update(DATABASE_URL=f"sqlite:///{root / 'app.sqlite3'}",
            CHECKPOINT_DB_PATH=str(root / "checkpoints.sqlite3"), ENABLE_RAG="false",
            APP_ENV="local", ALLOW_INSECURE_LOCAL_STORAGE="true", LLM_WRITER_MODE="one_pass")
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        from app.agents.orchestrator_tools import ToolContext, execute_tool
        from app.agents.resume_graph import _init_state
        llm = ChatOpenAI(model=config["LLM_MODEL"], api_key=config["LLM_API_KEY"],
            base_url=config["LLM_BASE_URL"], streaming=False, max_retries=0, timeout=120)
        cases = json.loads(Path("evaluation/agent-loop-spike/cases.json").read_text())["cases"]
        state = _init_state()
        state["messages"] = [HumanMessage(content=next(c for c in cases if c["id"] == "03")["user_message"], id="jd-smoke"),
                             HumanMessage(content=next(c for c in cases if c["id"] == "08")["user_message"], id="upload-smoke")]
        ctx = ToolContext(llm=llm, turn_id="p1a-smoke")
        for name, args in [("read_jd", {"source_id": "jd-smoke"}), ("record_facts", {"source_id": "upload-smoke"}),
                           ("write_draft", {}), ("check_layout", {})]:
            began = perf_counter()
            outcome = await asyncio.wait_for(execute_tool(name, state, args, ctx), 180)
            state.update(outcome.update)
            print(json.dumps({"tool": name, "status": outcome.result.get("status"),
                "code": outcome.result.get("code"), "missing": outcome.result.get("missing"),
                "seconds": round(perf_counter() - began, 3),
                "pages": (outcome.result.get("page_check") or {}).get("pages")}, ensure_ascii=False))
            if outcome.result.get("status") not in {"ok", "partial", "unchanged"}:
                raise SystemExit("该步未完成；先复核原因，再继续端到端回放")
asyncio.run(main())
PY
```

## 失败做法与未完成

- 不直接调用整节点：否则引入阶段门槛、自动追问和第二个事实入口。改为服务适配，无须改节点。
- 初轮测试暴露旧 split_mixed_material 对“明确本人标签在前、JD 在后”仍要求教育前缀；只在适配器补充明确标签边界，保持未标记招聘材料的保守策略。
- 初写测试误以为现有 writer 对任意失败都会返回 fallback；实际不可用响应抛 ChatTurnError。新回归按真实契约检查结构化错误、空增量和旧稿不变，没有修改任何旧断言。
- 纯确定性删条目测试最初使用“隐藏”，旧规则解析未命中；改用已有确定性操作支持的“删除”验证同一隐藏/撤销语义，未扩写旧规则。其他自由编辑沿用写稿链路；本期没有新建通用编辑路由。
- 全量期间复核发现旧 serializer 会从聊天历史补可选基本信息；适配器序列化时清空仅用于兜底的历史视图，保证未 record_facts 的消息不能出现在稿中。
- 首轮全量唯一失败来自新测试的环境隔离：测试发现过程导入 tailor-bench，设置 `HUHUA_RECORD_REJECTED_TEXT=1`，使已被拒绝的数字保留在诊断 metadata（简历正文已正确拒绝）。定向运行未加载该 benchmark，因而先前通过。新测试显式临时设置生产值 `0`，测试后恢复环境，保留“整个 update 不含该虚构数字”的原断言；不改业务开关或旧测试。
- 未执行真实模型、线上服务或部署。真实工具效果、延迟、跨轮 loop 问题卡恢复、最终持久化及 P1b/P1c 合并后的真实回放由 Claude 验证。未 commit、push；未改 dist。
