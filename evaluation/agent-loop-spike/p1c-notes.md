# 第十七批第 1 期 · P1c 评测

本分支只改评测、离线回归和交接。未修改生产编排、工具适配器、路由、配置、前端或 dist；未调用真实模型、访问 8833/8834、commit、push 或部署。真实回放留给 Claude 在合并 P1a/P1b 后执行。

## 根因与改动

- 第 0 期 04/08 将所有 ask_user 列为禁止，误拒绝先写后问。cases v2 仅增加写稿后的合法序列，写稿前追问仍失败；增加 11/12/13（有档案且方向明确、自我介绍后立即出稿、中途换方向）。新增案例只在评测 JSON，不改系统提示或 schema。第 0 期真实报告全部保留。
- `evaluation/persona-ux/run_persona.py` 增加 `--agent-mode off|loop`、cold/upload 固定输入、每轮指标/工具进度/流中卡片快照；原 8 人物入口与旧断言保留。省略 mode 仍兼容旧服务，报告标记“未核对”；显式传 mode 时先检查服务端设置，不符合即在创建人物会话之前退出。
- `evaluation/persona-ux/serve.py` 是显式启动的隔离评测服务外壳：通过进程环境设置 `AGENT_MODE`，核对实际 Settings 后包装原应用。没有新增生产请求头或生产 API。仅评测外壳提供 `/_evaluation/config` 和 `evaluation_metrics` SSE 帧，原请求、工具参数和业务行为均由合并后的生产代码处理。
- 评测外壳统计 httpx 发往 Chat Completions/Responses 的 POST 尝试（同步/异步、含重试、嵌套调用；ContextVar 区分并行轮次）。在 `[DONE]` 前附加计数与服务端耗时；正常结束但缺 DONE 的失败流也记录指标，不伪造完成信号。中途断连、非 SSE HTTP 失败等拿不到指标时保留 null，不能推算为 0。
- 模型出站前对解码 JSON 做 ContactRedactor 检查，包括工具参数和思考扩展字段；发现未脱敏联系方式即阻止发送、记录 `privacy_blocks`，不偷偷代替生产代码脱敏。不会落盘请求体、原始思考、认证头或密钥。
- `loop-fixtures.json` 保存新增合成人物；`loop_checks.py` 复用 checks 的可见正文、隐藏栏目、成稿结构、否定语境及证据格式，增加首轮无 intake 表单、3 轮内已保存首稿、联系方式至多索要一次、逐轮指标与隐私检查。cold 另查成稿前后联系方式时点；upload 已有联系方式须零重复索取。新增人物还查任务/数量保留、范围、来源外数字/工具/经历和最终身份/联系方式投影。
- `report.py` 修复遗漏 returning 专用检查器的问题，支持全部 10 人物、off/loop 并列、逐轮请求数和耗时、首稿总轮次及从具体材料起的轮数；冻结结果重评不信任缓存 checks，不把 MISSING/N/A 当 PASS。新增 fixture 的哈希也进入比较。

指标口径：`model_calls` 是实际发出的模型 HTTP 尝试数，包含工具内部调用，所以**不是编排器的 ≤5 次预算计数**；不包含会话轮次外独立后台归档、非 httpx 传输或其他模型协议。`server_seconds` 是本轮 SSE 到完成/结束的耗时；另存客户端 `stream_seconds/current_seconds/elapsed_seconds`。这里不估 token 或费用。

## 工具接口与合并边界

生产回放只经已有聊天、卡片和 canonical current API，不自行实现 ToolOutcome/TOOLS，不给模型传事实正文参数。保留第 0 期 spike 的独立假工具约定；它的 `question/query` 参数不替换生产规格的 `card/name`。本评测外壳不要求 P1b 新增指标事件或请求头，P1b 只需按原规格提供真正生效的 `Settings.AGENT_MODE`。

## 旧断言变更逐条说明

`tests/test_orchestrator_spike.py` 仅三处维护性变更：案例总数 10→13；报告 matched 数 10→13；注入用例由“取最后一例”改为按 ID=10 定位，避免新增场景让原注入测试测错对象。所有原断言语义不变，来源/隐私/预算断言未放宽。cases 的 04/08 序列调整由本期规格明确要求，新增回归同时拒绝先问后写。其余原人物检查器未改。

## 验证

- 新增 `tests/test_persona_loop.py`：20 项离线回归，覆盖模式核验、真实字段投影、卡片中间态、首稿计数、重复索取/否定语境、编造变异、全部 8 个旧人物报告派发、指标缺失与非法值、嵌套/并行/重试计数、SDK 出站联系方式拦截、分片 DONE 和失败 SSE。全部使用内存数据、MockTransport/ASGI 或既有 socketpair 桩，不监听服务端口。
- 原 spike 17 项离线回归通过，内含 13 场景 × 2 模式。CLI 桩回放 off/thinking 各 13/13，报告在 `runs/p1c-stub-off/`、`runs/p1c-stub-thinking/`。它们是固定脚本，不能当作真实选择正确率。
- 最终完整命令：**2033 项，2031 通过、2 项原有跳过、0 失败，278.247 秒，退出码 0**。此前首轮 2031 项通过（93.378 秒），再补充事实变异与失败流指标回归；中间一次计时失败和处理过程保留在下节。
- Ruff、AST、CLI help、文档 Bash 语法与 `git diff --check` 通过。12 份旧真实报告逐字节未变；原 10 例中仅 04/08 预期调整，其余整例不变。日志 `p1c-{loop,persona,spike,full}-tests.log` 按仓库规则忽略。

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

## Claude 合并后的真实回放命令（本任务未执行）

前提：已合并 P1a/P1b；模型凭证通过当前 worktree 的 `backend/.env` 或进程环境配置；returning 所需 ACCOUNT_SECRET/加密配置对服务端和回放器相同。命令不包含凭证。外壳强制本地模式和新数据库目录，拒绝重用目录或监听 8833/8834。若尚无 `Settings.AGENT_MODE=loop`，启动 loop 会明确失败，不能改标签冒充回放。

从合并后的仓库根目录，在同一个 shell 执行以下初始化/启动；等待两个日志出现 `Application startup complete` 后再执行回放。两个服务各有独立数据库；串行运行人物，避免把并发负载混入延迟比较。

```bash
P1C_PYTHON="/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python"
P1C_DATA_ROOT="$(mktemp -d -t huhua-p1c)"
P1C_RUN="$(TZ=Asia/Shanghai date +%Y%m%d-%H%M%S)"
export APP_ENV=local ALLOW_INSECURE_LOCAL_STORAGE=true AUTH_COOKIE_SECURE=false
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
"$P1C_PYTHON" evaluation/persona-ux/serve.py --agent-mode off --port 8847 --data-dir "$P1C_DATA_ROOT/off" > "$P1C_DATA_ROOT/off.log" 2>&1 &
P1C_OFF_PID=$!
"$P1C_PYTHON" evaluation/persona-ux/serve.py --agent-mode loop --port 8848 --data-dir "$P1C_DATA_ROOT/loop" > "$P1C_DATA_ROOT/loop.log" 2>&1 &
P1C_LOOP_PID=$!
```

优先验收 cold/upload/returning，随后收集其余 7 人物对比。若检查失败，回放退出码 1 仍会留下完整证据；不要因此改旧断言或自动重试付费轮次。

```bash
"$P1C_PYTHON" evaluation/persona-ux/run_persona.py --base http://127.0.0.1:8847 --agent-mode off --persona cold,upload,returning --returning-db "$P1C_DATA_ROOT/off/application.sqlite3" --output "evaluation/persona-ux/runs/$P1C_RUN-off-core"
"$P1C_PYTHON" evaluation/persona-ux/run_persona.py --base http://127.0.0.1:8848 --agent-mode loop --persona cold,upload,returning --returning-db "$P1C_DATA_ROOT/loop/application.sqlite3" --output "evaluation/persona-ux/runs/$P1C_RUN-loop-core"
"$P1C_PYTHON" evaluation/persona-ux/run_persona.py --base http://127.0.0.1:8847 --agent-mode off --persona tech,ops,career,service,design,aipm,aipm_real --output "evaluation/persona-ux/runs/$P1C_RUN-off-baseline"
"$P1C_PYTHON" evaluation/persona-ux/run_persona.py --base http://127.0.0.1:8848 --agent-mode loop --persona tech,ops,career,service,design,aipm,aipm_real --output "evaluation/persona-ux/runs/$P1C_RUN-loop-baseline"
"$P1C_PYTHON" evaluation/persona-ux/report.py "evaluation/persona-ux/runs/$P1C_RUN-off-core" "evaluation/persona-ux/runs/$P1C_RUN-loop-core" --output "evaluation/persona-ux/$P1C_RUN-core-comparison.md"
"$P1C_PYTHON" evaluation/persona-ux/report.py "evaluation/persona-ux/runs/$P1C_RUN-off-baseline" "evaluation/persona-ux/runs/$P1C_RUN-loop-baseline" --output "evaluation/persona-ux/$P1C_RUN-baseline-comparison.md"
kill "$P1C_OFF_PID" "$P1C_LOOP_PID"
wait "$P1C_OFF_PID" "$P1C_LOOP_PID"
```

独立 spike 真实回放仍使用假工具；和上面的生产工具回放分开解读。两模式各重复 3 轮，自动使用唯一输出目录：

```bash
for P1C_REPEAT in 1 2 3; do
  "$P1C_PYTHON" scripts/run_agent_spike.py --mode off --real --cases evaluation/agent-loop-spike/cases.json
  "$P1C_PYTHON" scripts/run_agent_spike.py --mode thinking --real --cases evaluation/agent-loop-spike/cases.json
done
```

## 失败做法与未完成

- 首次新增检查用了 Unicode `\w` 提取邮箱，会把前面的中文标签也算入地址，造成两个假失败；改为 ASCII 邮箱边界，保留精确投影断言。日期数字检查也归一化常见日期分隔符，避免把月份格式变化误报成新成果数字。
- 第二次全量 2033 项耗时 455.402 秒，仅旧 `test_validation_retry_shares_one_timeout` 的墙钟阈值失败（170ms ≥ 85ms），日志另存 `p1c-full-tests-timing-failure.log`。未修改该测试或 writer；其文件单独复核 17/17 通过（0.805 秒），随后原命令重跑全量。较首轮的显著减速提示运行负载影响，但没有把这一推断当作通过结果。
- 不能从工具步数/SSE 次数推算模型调用数；采用仅评测进程启用的 httpx 出站计数。尚未合并生产 loop 的本分支无法证明真实工具接线、思考回传、速度或语言质量。
- cold 的规格同时要求四条消息顺序（最后才给联系方式）与 ≤3 总轮首稿，而 write_draft 可能先返回 need_contacts。**不改验收为“从经历起算”或跳过问候/确认轮**：严格总轮数仍验收 ≤3，同时报告从材料起算的辅助值。若实际第 4 轮才交付，应保留 FAIL，由 Claude 在第 2 期明确产品取舍。
- 本期仅授权调整 spike 04/08。第 0 期 case 05 仍禁止 ask_user（其文字“直接出稿、不再先问”与先写后问也可能冲突）；原规则和真实报告保留，未顺手扩大预期调整范围。
- 无编造检查是固定材料的词法/结构检查，不能证明通用语义事实保真；全部真实产物仍需人工核对。其他 8 人物沿用原检查，其中 returning 原有事实检查较窄，报告不声称新增了通用语义评判。
- 本任务没有真实模型回放结果、真实对比胜率、生产联调或部署证据。旧真实报告没有重写为新口径通过率。
