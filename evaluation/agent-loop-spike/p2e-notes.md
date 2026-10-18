# 第十七批第 2 期：P2a 时延与上下文

日期：2026-10-19。分支 `batch17e`。只改编排输入/调用层，不改 `SYSTEM_PROMPT`、工具适配器、路由、配置主文件、前端、评测 runner 或旧测试断言。

## 根因与第 1 期证据

已完整阅读 `docs/development/2026-10-19-batch17-orchestrator-plan.md` 两期及 p1a/b/c/d 说明。当前 worktree 没有被忽略的 `runs/p1-{loop,off}-all-5`，实际只读 `../huhua-b17b/evaluation/persona-ux/runs/` 下的对应 run.json、全部人物 JSON/回复/checks；没有写另一个 worktree。原文件哈希见 `p2e-context-sizes.json`。

- `_input_messages` 原先同时发送最近 16 条完整聊天、**所有**用户消息的 sources 原文、事实母版、当前简历、完整岗位画像和方案。sources 没有跟随历史窗口截断，且 current 再重复最新消息。只缩短 history 无法限制输入增长。
- 每个工具结果又原样加入本轮历史。record_facts 带事实与多份来源引用，use_profile_items 带全部 facts，write_draft/edit_resume 带整稿和诊断；后续每次决策/收尾都会重发。
- 隐私说明原先只在发现联系方式后追加到 system，同样代码的不同轮可能改变前缀。工具 schema 原先依赖 registry 的插入顺序。
- 决策和强制收尾都开思考；usage 只保留 prompt/completion/reasoning，不能比较缓存命中。现有每次调用计时保留并补充实际 phase/mode。
- 旧 loop 的 36 个请求快照平均 server_seconds 为 24.047s、最大 72.9425s；off 的 42 个为 11.123s、43.5834s。这是 SSE 服务端耗时，**不等于**规格中编排日志的 24.8s/72.8s。旧快照的 model_calls 全为 0，且没有逐次编排 usage，不能把它们当有效成本统计；13.7k/85k prompt token 仅引用规格汇总，没有伪造逐次旧基线。
- 人物失败项与规格一致：upload 拆项、returning 回执、数字修正、重复要联系方式、两类产品人物写法/问答流程。它们交给 P2b/P2c，本批不改行为断言来制造通过。

## 改动文件与决策

1. `backend/app/agents/orchestrator_context.py`：新增确定性投影与本模块设置。
   - 事实只投影基本资料、联系方式是否已存在、经历名/角色/时间、active 要点数、前三条首句和范围限制；不带原始来源、raw_notes 或事实 ID。稿件只投影条目、要点数/首句及技能。岗位只保留方向和筛选要求；结构方案只保留可读主线/定位/写法/栏目顺序。
   - 工具结果保留 status/code、缺失项、版本、页数/超页、导入名称、拒绝/遗漏说明等决策信息。read_profile 的可选择条目 ID 必须保留，否则后续 use_profile_items 无法执行；其内部 fact_ids 去掉。未知新增字段走有界投影，便于 P2b 增加回执字段。
   - 最多保留最近三个用户轮及其助手回复，短消息保持脱敏后的原文。本轮长文上限 3200 字符，其他单条 1200；历史总预算 5000。更早信息用已记录经历名、当前方向、已问维度、关闭记录、稿件版本作确定性摘要，不调用模型。
   - sources 改为 current + 最近 12 个原始来源 ID/类型；不在近期原文窗口内的来源最多附 100 字符预览，记录省略数量。**服务端 `_sources` 和传给 handler 的 state/messages 完整保留**，旧来源仍能由真实 source_id 取全文。摘要不会被当成 HumanMessage 或写入事实。
   - 状态投影预算 4800 JSON 字符，来源索引 1800，单工具结果 3200。长文本有“截断/原长”标记，省略字段/条目有计数。正文先脱敏再截断，防止留下被截断的半个邮箱/电话号码；伪装成媒体 JSON 或 data: 的文本也检查。
2. `backend/app/agents/orchestrator.py`（不含 SYSTEM_PROMPT）：接入模型专用投影；原工具增量、持久化、事件、预算和超时不变。
   - system 固定为原 SYSTEM_PROMPT + 既有隐私说明，所有动态数据仍在后面的 untrusted_data 内。native tools schema 固定排序并复制，决策/收尾均携带相同 schema；不重复把 schema 写进 system。服务商如何序列化/缓存仍以实际 hit tokens 为准。
   - `AGENT_FINAL_MODE=thinking|off`：由 `OrchestratorSettings` 读取进程环境或本 worktree 的 `backend/.env`，无需越界改 config.py。暂保留 P1 的 thinking 默认，**最终默认值留 Claude 实测后决定**。直接离线调用可传 `run_orchestrator(..., final_mode="off")`。
   - off 只作用于已确定不能再调用工具的收尾轮（stop、预算用尽、DSML 纯文字重试）；所有正常决策轮继续 thinking。auto 直接返回正文的那次请求仍是决策请求，不额外增加一次模型调用。切换 off 仅移除发出副本里的 reasoning_content，工具 ID/结果配对保留；thinking 多步保持完整推理回传。既有一次协议降级仍可将后续请求降为 off，关闭收尾思考不计为 fallback。
   - 每轮 `orchestrator_turn` 日志及最终 AIMessage 的 `additional_kwargs.orchestrator` 保留 `turns[].seconds`，新增 `phase=decision|final`、实际 mode、配置 final_mode；每次/合计 usage 含 prompt_tokens、completion_tokens、reasoning_tokens、prompt_cache_hit_tokens、prompt_cache_miss_tokens。兼容 completion_tokens_details.reasoning_tokens 与 prompt_tokens_details.cached_tokens。
   - 只接受非负整数 token；未知或失败调用为 null，不填 0；有一次未知则该项合计仍为 null。日志没有正文、参数、原始思考、供应商错误正文。这仍只统计编排 SDK，不代表工具内 writer/extractor 的总成本。
3. `evaluation/agent-loop-spike/test_p2e_context.py`：15 项新增离线回归，独立目录避免改 P2c 文件。覆盖投影、来源全文/状态不变、active 事实与范围、版本/错误/缺失/页数、档案 ID、历史摘要、超长/转义字符预算、隐私与固定前缀、开关默认/非法值、thinking 回传和 off 工具配对、预算/降级/DSML、失败指标、真实 OpenAI SDK + MockTransport 流式 usage/请求体。
4. `evaluation/agent-loop-spike/p2e-context-sizes.json`：只含旧 run 哈希、数量/耗时和离线字符数，没有人物正文。`mmr.md` 仅在末尾追加本批交接。

## 验证与证据边界

- 原编排相关 82 项通过（1.046s）。
- 新增 15 项通过（0.544s）；真实 SDK 使用 MockTransport，不联网、不监听端口。
- 用户指定全量：**2104 项，2102 通过、2 项原有跳过、0 失败/错误，89.107s，退出码 0**。新回归在 evaluation 目录，需用下一节独立命令运行，不虚报成全量发现的一部分。旧断言无修改/放宽。
- Ruff、AST、SYSTEM_PROMPT 与 HEAD 的 AST 字面量一致、diff 空白检查通过；回放命令只做语法检查。
- 冻结 loop 的 31 份非空成稿快照，以 resume_data/version_id/page_check 构造同形工具结果，JSON 字符数中位 **2413→739**，最大 **2722→942**；off 的 36 份是 **1943.5→667.5**、**2853→927**。合成的大事实/重复来源样本 **557247→373** 字符。这不是完整旧请求复原，也不是 tokenizer 计数或模型质量指标。
- 日志：`p2e-existing-tests.log`、`p2e-context-tests.log`、`p2e-full-tests.log`（仓库忽略文件）。

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py -s evaluation/agent-loop-spike -p test_p2e_context.py
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
ruff check backend/app/agents/orchestrator.py backend/app/agents/orchestrator_context.py evaluation/agent-loop-spike/test_p2e_context.py
git diff --check
```

## 失败做法与修正

- 首个新增压力测试组合出了约 1.5 亿字符的媒体形 JSON，时间耗在现有联系方式正则；已中断该次离线测试，改为仍显著超预算的有限样本（约 24 万字符），完整保留脱敏/预算断言。没有修改隐私服务或放宽旧断言。
- 新测试最初把连续的 a 与邮箱无分隔地连接，整个字符串被正确识别为邮箱；断言却要求出现截断标记而失败。改成有空格分隔的长正文 + 邮箱，检查真正的截断边界，仍严格禁止原始/半截邮箱出现。
- 不用额外摘要模型，不压缩当前 thinking 回传，不把没有 usage 的旧快照计数当作有效模型成本。没有真实失败轮次自动重试。

## Claude 的真实回放命令（本批未运行）

在合并 P2a/P2b/P2c 后的仓库根执行。该命令串行比较同一代码下 loop 的收尾 thinking/off；每组用独立 SQLite、同一个专用端口 8849，保存全部人物及 server.log，结束只清理本命令创建的进程。需要已有模型凭证；优先当前 backend/.env，否则读取主工作区的 .env，已有进程环境优先。不会输出凭证。ACCOUNT_SECRET/加密配置由父进程同时传给服务端和 returning 回放器。

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" - <<'PY'
import json, os, socket, subprocess, sys, tempfile, time, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import dotenv_values

root = Path.cwd()
env_file = root / "backend/.env"
if not env_file.exists():
    env_file = root.parent / "huhua agent/backend/.env"
for key, value in dotenv_values(env_file).items():
    if value is not None:
        os.environ.setdefault(key, value)
if not all(os.environ.get(key) for key in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL")):
    raise SystemExit("缺少模型配置，未启动回放")
os.environ.update(APP_ENV="local", ALLOW_INSECURE_LOCAL_STORAGE="true", AUTH_COOKIE_SECURE="false", ENABLE_RAG="false")
data_root = Path(tempfile.mkdtemp(prefix="huhua-p2e-"))
stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S") + "-" + data_root.name.rsplit("-", 1)[-1]
outputs = []
for final_mode in ("thinking", "off"):
    output = root / "evaluation/persona-ux/runs" / f"p2e-{stamp}-{final_mode}"
    log_path = data_root / f"{final_mode}.log"
    data_dir = data_root / final_mode
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8849))
    env = {**os.environ, "AGENT_FINAL_MODE": final_mode}
    with log_path.open("w") as log:
        server = subprocess.Popen([sys.executable, "evaluation/persona-ux/serve.py", "--agent-mode", "loop",
            "--port", "8849", "--data-dir", str(data_dir)], env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for attempt in range(120):
                if server.poll() is not None:
                    raise SystemExit(f"服务未启动，检查 {log_path}")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8849/_evaluation/config", timeout=1) as response:
                        assert json.load(response)["agent_mode"] == "loop"
                    break
                except OSError:
                    time.sleep(.5)
            else:
                raise SystemExit(f"服务未就绪，检查 {log_path}")
            completed = subprocess.run([sys.executable, "evaluation/persona-ux/run_persona.py",
                "--base", "http://127.0.0.1:8849", "--agent-mode", "loop",
                "--persona", "cold,upload,returning,tech,ops,career,service,design,aipm,aipm_real",
                "--returning-db", str(data_dir / "application.sqlite3"), "--timeout", "600",
                "--output", str(output)], env=env)
            print(final_mode, "exit", completed.returncode, "run", output, "log", log_path)
            if completed.returncode not in (0, 1):
                raise SystemExit(completed.returncode)
            outputs.append(output)
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
subprocess.run([sys.executable, "evaluation/persona-ux/report.py", *(str(p) for p in outputs),
    "--output", str(data_root / "comparison.md")], check=True)
print("结果目录", data_root)

# Provider token metrics, not character estimates; unknown values remain unknown.
for final_mode in ("thinking", "off"):
    import statistics
    turns = []
    for line in (data_root / f"{final_mode}.log").read_text().splitlines():
        if "orchestrator_turn " in line:
            turns.append(json.loads(line.split("orchestrator_turn ", 1)[1]))
    calls = [call for turn in turns for call in turn["turns"]]
    prompts = [call["usage"]["prompt_tokens"] for call in calls if call["usage"]["prompt_tokens"] is not None]
    finals = [call["seconds"] for call in calls if call.get("phase") == "final"]
    result = {"final_mode": final_mode, "orchestrator_turns": len(turns), "calls": len(calls),
        "prompt_samples": len(prompts), "prompt_median": statistics.median(prompts) if prompts else None,
        "prompt_max": max(prompts) if prompts else None,
        "prompt_target_met": (statistics.median(prompts) <= 6000 and max(prompts) <= 20000)
                             if prompts and len(prompts) == len(calls) else None,
        "final_seconds_median": statistics.median(finals) if finals else None}
    for key in ("completion_tokens", "reasoning_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        values = [call["usage"].get(key) for call in calls]
        result[key] = sum(values) if values and all(v is not None for v in values) else None
    print(json.dumps(result, ensure_ascii=False))
PY
```

每组人物校验退出 1 仍保留证据并继续另一个配置，不自动补跑付费请求。report.py 的旧标题可能都标为 loop，目录名和 `final_mode` 日志区分 A/B；不要把这次比较误当成 AGENT_MODE=off 基线。若要重新跑旧流程，另按 p1c-notes 的 off 服务命令执行；P2c 的 compare 脚本合并后也可用于目录对比。

## 未完成

真实 token 的中位 ≤6000/最大 ≤20000、缓存命中率、首字/总时延、off 收尾语言质量与 DSML 概率、压缩后人物通过率尚未验证。字符预算不含固定 system/tools、当前轮必须回传的完整思考及模型自产工具参数，因此不能充当 provider token 硬上限。长历史/超长原文的摘要可能丢失决策细节，回放需检查方向、关闭维度、导入选择和修正结果；工具取证与写稿仍读取完整事实。

未调用真实模型、未访问 8833/8834、未启动服务、未改 dist、未 commit/push/部署。P2b 内部 ID/写法/修正/联系方式状态和 P2c 卡片作答/检查器仍由各自分支交付。
