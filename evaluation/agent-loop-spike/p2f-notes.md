# 第十七批第 2 期 P2b：写作对齐与行为

日期：2026-10-19。工作分支 `batch17f`，起始 HEAD `815d22f`。只负责 P2b；没有修改 P2a 的上下文/时延实现或 P2c 的 runner、检查器、人物答案。

## 阅读与根因

已阅读 `docs/development/2026-10-19-batch17-orchestrator-plan.md` 第 1、2 期、`p1a/p1b/p1c/p1d-notes.md`。本 worktree 没有被忽略的回放产物，实际只读检查的是 `../huhua-b17b/evaluation/persona-ux/runs/p1-loop-all-5/` 与 `p1-off-all-5/` 的 run.json、全部人物目录中的逐轮 JSON、回复与 checks；没有复制或改写冻结结果。

- 写稿：loop 的 `write_draft → _write` 直接调用 tailor，没有结构方案生成/选择步骤，`confirmed_plan` 为空，writer 未进入旧流程的 `phase=write`。回放中两类 AI 产品人物的 role_family 已是 ai_pm，不能把问题归因于岗位识别；旧 writer 本身也已有按岗位选择 labeled 的能力。缺失的是统一的方案、标题与写稿契约，此外实际答案缺失仍与 runner 有关。
- 更正：tech/career 的 loop 回复明确报告把更正当新事实抽取失败，随后普通改写没替换旧数字，还产生条目重排。off 使用 `correction_pairs → apply_literal_corrections` 的确定性事务，正文、事实引用与版本一同更新；适配器漏接了它。
- 联系方式：每次 write_draft 都回传缺失字段，没有记住已经问过；ask_user 也没有同一状态约束。连续写稿/改稿或用户回答“不知道”后仍会索要。
- 内部编号：工具回执原样包含事实、方案和 writer 诊断中的 ID；开场示例也没有假设/数字限制。returning 实际回复已点名部分导入经历，原检查可能有字面口径问题；这里仅补完整的导入名称回执，检查口径留给 P2c。

## 改动文件与行为

- `backend/app/agents/orchestrator_tools.py`：write_draft 通过既有 `run_resume_writer(phase=plan) → select_plan/accept_profile → run_tailor_pipeline(phase=write)` 自动采用推荐方案，无需先弹确认卡。已有 confirmed_plan（含 checkpoint 的 resume_meta）直接沿用；pending_plan 的明确备选选择及用户选择的 plain/labeled 写法保留。沿用 labeled writer、事实校验、页数检查及版本事务。
- 同文件：record_facts 识别原始用户消息的明确更正，调用共享事务并先保存已校验事实；edit_resume 直接收到更正时也委托同一 record_facts 入口。更正成功结束本轮工具执行，避免随后整稿重写破坏“其余不变”；同轮重复调用也不重写。无法唯一定位、正文找不到旧值、外部参考来源或保存失败均不返回成功/不改变稿件。模型改写的 instruction 不能替换用户给出的数值。
- 同文件：`session_constraints.contacts_requested` 跨轮保留，首次成功出稿才返回 contacts_missing；失败不消耗询问机会，之后不再重复返回。问题卡过滤重复联系方式问题，保留同卡中的其他有效问题。用户明确导出/下载且仍缺时允许再问；已有完整头部信息不再问。该字段是布尔值，不保存联系方式。
- 同文件：模型可见结果移除事实/信号/槽位引用字段和内部诊断映射，正文中的已知内部引用转换为经历名或信号含义；继续做联系方式脱敏。状态、引用、UI 卡片、版本及持久化 metadata 原样保留。read_profile 的目录选择 ID 是下一次工具调用必需的句柄，保留在目录 `items[].id`，不作为用户文案；原始 fact ID 不传出。
- `backend/app/agents/orchestrator.py`：**只改 SYSTEM_PROMPT 常量**。开场只允许标注“假设”的无编造数字示意；导入后逐段点名；明确更正、联系方式只问一次、自动方案及不展示内部编号的行为。
- `backend/app/agents/resume_graph.py`：仅把旧节点约 40 行字面更正事务提取成 `_literal_correction_update`，节点原分支调用该函数；原操作顺序、错误/成功回复、事实校验、去重、覆盖、测页和版本行为不变。
- `tests/test_orchestrator_writing.py`：新增 11 个测试方法（含多个人物、故障和跨轮组合）。没有修改旧测试、旧断言或人物检查器。

## 验证

新增回归实际执行生产工具适配器、结构方案/选择、labeled writer、fact guard 和确定性更正事务；只有模型、测页耗时及保存回调使用离线替身。

覆盖：aipm/aipm_real 既有证据的 plan→WriterDraft/FactSlots 顺序、标题字段/定位、标签/真实痛点/MCP/引用 hash、拒绝编造数字；用户 plain 选择及备选保留；tech/career 更正文稿与旧节点逐字段一致、无关经历不变、先存事实、版本与引用一致、不调用 writer；失败/歧义/参考来源/保存异常不报成功；联系方式跨多轮、导出例外、完整头部、失败出稿及混合问题卡；内部编号过滤、状态不变与档案句柄仍可使用。联系方式不出现在捕获的业务模型入参或工具回执中。

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

- 原适配器回归：37/37，0.614s，`p2f-tools-tests.log`。
- 新增定向回归：11/11，0.215s；复查内部引用过滤后再次通过，`p2f-writing-tests.log`。
- 首次全量：2115 项，2113 通过、2 项原有跳过，0 失败/错误，87.555s，退出码 0（`p2f-full-tests.log`）。之后收紧了内部引用过滤和更正后的 stop，最终结果见下行。
- **最终全量：2115 项，2113 通过、2 项原有跳过，0 失败/错误，91.102s，退出码 0**（`p2f-full-tests-final.log`）。
- Ruff、4 个改动/新增 Python 文件 AST、`git diff --check` 通过；AST 对比确认 orchestrator.py 除 SYSTEM_PROMPT 外与 HEAD 完全一致。旧断言没有修改、放宽或删除。

日志遵循仓库忽略规则，只在本地留存。测试没有写死 `/private/tmp`。

## 失败做法与限制

- 没有采用“重新调用抽取器再普通重写”修数值；第 1 期已证明它会保留旧值并改动其他文案。复用旧确定性事务，歧义失败仍保守退出。
- 没有直接调用整个 building/evaluating 节点，避免带入旧表单门槛、历史抽取和另一轮公开回复；只抽取旧更正事务，结构方案使用同一 writer 服务。
- 复查发现单纯删 JSON 的 ID 字段仍可能在诊断的键、正文或槽位引用里残留，已覆盖这些位置，并保留目录选择句柄；这些修正在最终全量前完成。本轮没有需要放宽断言的测试失败。
- 这里验证的是离线链路和既有证据下的成稿，不是新的真实模型通过率。首稿规划增加一次既有 planner 请求；后续复用确认方案。真实延迟与实际语言行为需合并 P2a 后测量。
- 联系方式普通回复由 SYSTEM_PROMPT 约束，工具层控制缺失回执及问题卡；不声称已经通过真实模型 `loop.contacts_once`。P2a 压缩状态时必须保留 session_constraints 中的 contacts_requested 或等价的“已问过”摘要。
- aipm/aipm_real 缺少答案、项目名/日期和深挖终止时点的问题需要 P2c 的 runner 接续；本任务不伪造未知事实，不改问题答案或通过口径。检查 first_draft_by_turn3 的既有总轮数定义仍由 P2c 负责。

## Claude 合并后的真实回放命令（本任务未执行）

在合并 P2a/P2b/P2c 后的仓库根目录执行。下面串行跑 off/loop 全 10 人物，每个模式使用独立新数据库，端口 8857/8858，退出时关闭自己启动的服务。模型配置读取当前 worktree 的 backend/.env；缺失时读取相邻主 worktree，进程已有环境优先。只复制 LLM 配置，不复用真实账号/数据；为隔离服务生成临时账号密钥，不输出凭证。runner 检查失败（退出码 1）仍保留产物并继续另一模式，不自动重跑付费轮次。

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" - <<'PY'
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import dotenv_values

env_file = Path(os.environ.get("P2F_ENV_FILE", "backend/.env"))
if not env_file.is_file():
    env_file = Path("../huhua agent/backend/.env")
config = dotenv_values(env_file)
env = {**{k: v for k, v in config.items() if k.startswith("LLM_") and v is not None}, **os.environ}
if not all(env.get(k) for k in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL")):
    raise SystemExit("缺少模型配置；尚未启动服务或调用模型")
env.update(APP_ENV="local", ALLOW_INSECURE_LOCAL_STORAGE="true", AUTH_COOKIE_SECURE="false",
           ACCOUNT_SECRET=secrets.token_urlsafe(48), DATA_ENCRYPTION_KEYS="{}", DATA_ENCRYPTION_ACTIVE_KEY="",
           ENABLE_RAG="false", LLM_PLAN_CONFIRM="true", TAVILY_API_KEY="", DEEPSEEK_TOOLS_API_KEY="",
           SMTP_HOST="", SMTP_PASSWORD="", SMTP_FROM="", EMAIL_PROVIDER="smtp", RESEND_API_KEY="", RESEND_FROM="")
data_root = Path(tempfile.mkdtemp(prefix="huhua-p2f-replay-"))
stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S-%f")
runs = []
print("隔离日志与数据库：", data_root)
for mode, port in (("off", 8857), ("loop", 8858)):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))  # 已占用则停止，避免误连其他实例。
    base = f"http://127.0.0.1:{port}"
    output = Path("evaluation/persona-ux/runs") / f"p2f-{stamp}-{mode}"
    mode_env = {**env, "AGENT_MODE": mode}
    with (data_root / f"{mode}.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "evaluation/persona-ux/serve.py", "--agent-mode", mode,
                                   "--port", str(port), "--data-dir", str(data_root / mode)],
                                  env=mode_env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for attempt in range(120):
                if server.poll() is not None:
                    raise SystemExit(f"{mode} 服务已退出，请检查 {data_root / (mode + '.log')}")
                try:
                    with urllib.request.urlopen(base + "/_evaluation/config", timeout=1) as response:
                        assert json.load(response)["agent_mode"] == mode
                    break
                except OSError:
                    time.sleep(.5)
            else:
                raise SystemExit("隔离服务未就绪")
            replay = subprocess.run([sys.executable, "evaluation/persona-ux/run_persona.py", "--base", base,
                "--agent-mode", mode, "--persona", "cold,upload,returning,tech,ops,career,service,design,aipm,aipm_real",
                "--returning-db", str(data_root / mode / "application.sqlite3"), "--timeout", "600",
                "--output", str(output)], env=mode_env)
            if replay.returncode not in (0, 1):
                raise SystemExit(replay.returncode)
            runs.append(str(output))
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
subprocess.run([sys.executable, "evaluation/persona-ux/report.py", *runs, "--output",
                f"evaluation/persona-ux/p2f-{stamp}-comparison.md"], env=env, check=True)
print("回放目录：", *runs, sep="\n")
PY
```

优先核对 heading/labels/answers_used/real_pains、tech correction_190、career correction_four、contacts_once、returning import_receipt；同时人工检查正文、引用与 canonical 已保存版本。不得用桩测试结果替代真实通过率，也不能只凭助手说“已修改”判定成功。

本任务未启动应用服务、未访问 8833/8834、未调用真实模型、未改 dist、未 commit/push/部署。
