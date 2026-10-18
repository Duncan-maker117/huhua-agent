# 第十七批第 2 期 · P2c 评测（batch17g）

## 范围与证据

只修改 `evaluation/`、评测测试，以及规格明确点名的 `scripts/compare_persona_runs.py`；根 `mmr.md` 仅追加。不改生产编排、工具、提示词、手册、前端或 dist。不调用真实模型、不访问 8833/8834、不 commit/push/部署。

已阅读第 1/2 期完整规格及 p1a/p1b/p1c/p1d 说明。本 worktree 没有两个忽略的回放目录，实际只读来源为 `../huhua-b17b/evaluation/persona-ux/runs/{p1-off-all-5,p1-loop-all-5}`。解析两份 run.json，逐一核对 20 个人物目录的 checks、78 轮 JSON 与 reply.txt，均与 run 内记录一致（共 178 份文件）。没有改写旧证据。

来源 run.json SHA-256：

- off：`2b5d5b90adaabe754fecdbe161c6b1f7298c6a0b2818ec619a6b0ab0fac43844`
- loop：`145a8300d387512f3c5a26f47ea48b2847d521e6dfc8bc6645e18b8b27f3d56b`

## 根因与修改

1. **首稿不等于问答已完成。** `aipm.replay` 原来一旦有 writer 成稿即退出，loop 的 aipm 在第 1 轮出稿后尚有纯文本追问，却只保存了 1 轮。现在 runner 显式把 agent_mode 交给 aipm/aipm_real；loop 有真实 ask_user、方案/表单或可识别纯文本追问时继续。卡片回答仍绑定服务返回的 turn_id/问题 id，使用原 VALUES；无卡使用既有自由回答函数，不伪造卡片，不把整个答案库塞给模型。未知维度仍回答不知道，深挖上限和越限失败保持。off/未指定模式保留原先成稿即停止的控制流；aipm_real 前四轮原文和顺序不变。
2. **同一来源兼容两种提问方式。** off 用经历表单收集的项目名称、开始/结束时间、角色已经存在于两人物各自 INTAKE。loop 改用 ask_user 询问这些字段时，现在从同一 INTAKE 取值；不能因为不用旧表单就误答不知道。仍只选原答案的精确归一选项或允许的其他答案，不能选近似但添事实的选项；联系方式、学校、专业没有答案来源，继续 unknown。未新增人物事实或修改 VALUES/FIRST/INTAKE 内容。
3. **returning 回执误判。** 旧检查必须含字面“导入”；实际 loop 已明确“选进了稿子”“选用了…并写入简历”，点名了两段，且同轮可见 projects 确有这两段。现在接受这些完成态表达，同时要求两段名称与同轮可见数据一致，拒绝将来计划、询问、失败、否定、只提一段或只有口头成功。证据改为实际回执轮，而不是末轮固定标题。
4. **contacts_once 不豁免真正重复。** 原检查已按用户轮去重，“成稿后一次问齐”、同轮卡片+回复都只算一次，保持不变。career 第 1/2/3 轮、design 第 1/2/3 轮均在实际索取，必须失败。修正逗号/转折分句：已收到邮箱不能遮住同句索要手机；补“还差”缺项表达。仅缺学校/专业的 basics 表单不算索要联系方式，缺少 missing_fields 的旧产物仍保守计入。
5. **旧 HTTP 计数遗漏当前 SDK。** 两份旧 run 的全部 model_calls 都是 0。现场核实当前 OpenAI SDK 的默认异步客户端继承 `httpx2.AsyncClient`，旧 serve 只 patch `httpx`，因此漏记 SDK 调用，也未通过该评测拦截器检查 SDK 请求。这不证明生产脱敏失败。现在评测外壳同时包装已安装的 httpx/httpx2 同步/异步 send，去重客户端类；JSON 出站联系方式仍在真正 send 前拒绝，测试用 SDK + MockTransport 验证，没有网络请求。
6. **编排指标独立采集。** 评测进程用 ContextVar 关联现有 `app.agents.orchestrator` 的 `orchestrator_turn` 日志，仅白名单投影数值，不保存正文、思考、工具参数或任意新增字段。SSE 的 evaluation_metrics 带 metrics_version=2 和 orchestrator；runner 原样保存投影到每轮 JSON/run.json。包含总调用数/秒、逐次 mode/秒及 prompt/completion/reasoning/prompt_cache_hit_tokens；未报告的 token 为 null。P2a 只需沿用现有日志名与 `usage`/`turns[].usage` 键，新增 cache 字段会被接收。off 与 loop 的结构化答卡/确认轮可能不经过编排，保留 N/A。新版 loop 自由输入缺少编排记录会使现有 loop.metrics 失败。若编排调用数大于 HTTP 观测数，HTTP/隐私计数标记未知，不用编排数冒充总调用成本。
7. **对比报告。** 新脚本输入两个目录或 run.json，离线重评并输出每人物/合计的通过率、共同断言、失败项、平均/最大每轮耗时、编排调用/耗时/token、单次 prompt 中位/最大及样本覆盖数。`report.py` 复用该表，并保留逐轮 HTTP/SSE/回读耗时及逐次编排请求明细。缺人物显示 MISSING，缺指标显示 N/A；不信任缓存 checks。两模式总断言数不同，不能直接把总百分比当同分母质量提升。

## 冻结产物重评（不是新模型回放）

报告：`evaluation/persona-ux/p2g-p1-comparison.md`。

| 模式 | 当前口径通过 | 共同断言 | 每轮总秒平均 / 最大 |
| --- | --- | --- | --- |
| off | 113/118 | 113/118 | 11.132 / 43.590 |
| loop | 147/168 | 101/118 | 24.066 / 72.959 |

唯一状态变化是 `returning.profile.import_receipt` FAIL→PASS（returning 10/11→11/11），属于判定纠错。career/design/aipm_real 的 contacts_once，tech/career 的数字更正，aipm/aipm_real 的写法/标题/事实等失败均保留。旧 run 未存编排 token/耗时，不能从 SSE 或工具步数反推，表中 N/A。aipm_real 的四轮开场与“从首条消息起 3 轮内成稿”的矛盾仍按原严格断言保留失败，不改为从材料起计数。

## 改动文件与新增测试

- `evaluation/persona-ux/{aipm,aipm_real,run_persona}.py`：loop 问答、既有答案来源与指标落盘。
- `evaluation/persona-ux/{loop_checks,returning}.py`：联系方式和选用回执核对。
- `evaluation/persona-ux/{serve,metrics}.py`：实际传输计量、出站阻断、编排数字白名单。
- `evaluation/persona-ux/report.py`、`scripts/compare_persona_runs.py`、冻结重评 Markdown：报告。
- `tests/test_persona_p2c.py`：18 项离线测试，含 loop 首稿后答卡/无卡纯文本、off 停止行为、真实人物四轮顺序、动态 turn_id、INTAKE 来源、未知答案/越限、runner 保存载荷；一次问齐和真正重复、已收邮箱与缺手机同句、回执否定/将来/缺项/隐藏；并发指标隔离、各 token/耗时、非法值/缺失、真实 SDK 实际传输出站计数与阻断、SSE→GuestClient→磁盘、指标矛盾、新版缺编排记录、两目录 CLI/共同分母/缓存不得遮掩失败。

旧测试文件与旧断言均未修改。评测判定的变更理由逐项见上文第 3/4/6 点；未放宽事实、首稿轮数、深挖上限、编造、数字更正或风格检查。

## 验证

最终指定全量：**2122 项，2120 通过、2 项原有跳过，0 失败/错误，85.412s，退出码 0**。日志 `evaluation/agent-loop-spike/p2g-full-tests.log`（忽略文件）。新增 18 项全部包含在该轮；旧测试断言原样通过。此前评测定向 107 项通过（随后新增 1 项新版编排缺证据测试，已在最终全量通过）。指定入口隔离配置、数据库和模型凭证；未启动应用服务。

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

Ruff、10 份 Python 文件 AST、3 段交接 shell 的 `bash -n`（含内嵌 Python AST）与 `git diff --check` 已通过。比较脚本已直接运行生成冻结报告；逐项与旧 checks 对照只有上述 1 项变动。真实回放尚未执行。

## 失败做法与边界

- 新测试初稿漏一个字典闭括号导致发现错误；已修正。联系方式分句首版漏“还差”，新增负例实际失败后补齐该触发词，未改失败预期。
- 首版仍沿用仅 httpx 的计数，并仅增加编排日志采样；全量 2119 项（2117 通过、2 跳过，91.627s）通过后，源码核实发现当前 SDK 实为 httpx2，故这轮不能作为最终验收。已补实际 SDK 传输测试和计量。SDK 新版直接抛出 ValueError，旧版会包装 APIConnectionError；新增阻断测试接受这两种已知外层类型，但仍严格断言 transport 未发送、计数不增加、隐私阻断增加。
- 既有自由追问识别与维度归类是词法机制，复杂复合问句仍可能回答 unknown 或选错维度；本任务不修改生产归类逻辑，也不把 unknown 强行补成有事实。问题卡不存在时不会人为生成问题卡。没有追问且已有可核对成稿时结束；持续追问/不能成稿仍按上限留下失败。
- 真实回放的质量、延迟、prefix cache、P2a/P2b 合并结果未实测。只有新回放才能验证 token 预算目标及当前生产提示/适配器行为；旧指标不回填估算。未留下应用服务或后台付费任务。

## Claude 合并后的真实回放命令（本任务没有执行）

前提：在合并 P2a/P2b/P2c 的仓库根执行，模型配置已通过该 worktree 的 backend/.env 或环境变量提供。两个服务与 runner 继承同一账号/加密配置；以下创建独立临时数据库、两个新输出目录，不重用 8833/8834。断言失败退出码 1 会保留证据并继续另一模式，不自动重试付费轮次；其他启动/CLI 错误停止。子 shell 退出时清理两个服务。

```bash
(
  set -eu
  P2G_PYTHON="/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python"
  P2G_DATA_ROOT="$(mktemp -d -t huhua-p2g)"
  P2G_RUN="$(TZ=Asia/Shanghai date +%Y%m%d-%H%M%S)"
  P2G_OFF_PID=""
  P2G_LOOP_PID=""
  cleanup() {
    for P2G_PID in "$P2G_OFF_PID" "$P2G_LOOP_PID"; do
      if [ -n "$P2G_PID" ]; then
        kill "$P2G_PID" 2>/dev/null || true
        wait "$P2G_PID" 2>/dev/null || true
      fi
    done
  }
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  export APP_ENV=local ALLOW_INSECURE_LOCAL_STORAGE=true AUTH_COOKIE_SECURE=false
  export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
  export ACCOUNT_SECRET="${ACCOUNT_SECRET:-$("$P2G_PYTHON" -c 'import secrets; print(secrets.token_hex(32))')}"
  "$P2G_PYTHON" - <<'PY'
import socket
for port in (8847, 8848):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
PY
  "$P2G_PYTHON" evaluation/persona-ux/serve.py --agent-mode off --port 8847 --data-dir "$P2G_DATA_ROOT/off" > "$P2G_DATA_ROOT/off.log" 2>&1 &
  P2G_OFF_PID=$!
  "$P2G_PYTHON" evaluation/persona-ux/serve.py --agent-mode loop --port 8848 --data-dir "$P2G_DATA_ROOT/loop" > "$P2G_DATA_ROOT/loop.log" 2>&1 &
  P2G_LOOP_PID=$!
  "$P2G_PYTHON" - <<'PY'
import json
import time
from urllib.request import urlopen
for port, mode in ((8847, 'off'), (8848, 'loop')):
    for _ in range(60):
        try:
            with urlopen(f'http://127.0.0.1:{port}/_evaluation/config', timeout=1) as response:
                assert json.load(response)['agent_mode'] == mode
            break
        except OSError:
            time.sleep(.5)
    else:
        raise SystemExit(f'{mode} 服务未就绪，请检查临时目录日志')
PY
  kill -0 "$P2G_OFF_PID" "$P2G_LOOP_PID"
  for P2G_MODE in off loop; do
    if [ "$P2G_MODE" = off ]; then P2G_PORT=8847; else P2G_PORT=8848; fi
    "$P2G_PYTHON" evaluation/persona-ux/run_persona.py \
      --base "http://127.0.0.1:$P2G_PORT" --agent-mode "$P2G_MODE" \
      --persona cold,upload,returning,tech,ops,career,service,design,aipm,aipm_real \
      --returning-db "$P2G_DATA_ROOT/$P2G_MODE/application.sqlite3" --timeout 600 \
      --output "evaluation/persona-ux/runs/$P2G_RUN-$P2G_MODE-all" || test "$?" -eq 1
  done
  "$P2G_PYTHON" scripts/compare_persona_runs.py \
    "evaluation/persona-ux/runs/$P2G_RUN-off-all" "evaluation/persona-ux/runs/$P2G_RUN-loop-all" \
    --output "evaluation/persona-ux/$P2G_RUN-p2-comparison.md"
  "$P2G_PYTHON" evaluation/persona-ux/report.py \
    "evaluation/persona-ux/runs/$P2G_RUN-off-all" "evaluation/persona-ux/runs/$P2G_RUN-loop-all" \
    --output "evaluation/persona-ux/$P2G_RUN-p2-detail.md"
  printf '隔离数据和服务日志：%s\n' "$P2G_DATA_ROOT"
)
```

只重评既有产物、不调用模型：

```bash
"/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/compare_persona_runs.py \
  ../huhua-b17b/evaluation/persona-ux/runs/p1-off-all-5 \
  ../huhua-b17b/evaluation/persona-ux/runs/p1-loop-all-5 \
  --output evaluation/persona-ux/p2g-p1-comparison.md
```
