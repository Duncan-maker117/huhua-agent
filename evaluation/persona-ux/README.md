# 五人物 API 回放验收

固定输入来自 [`../persona-ux-2026-10-15/fixtures.json`](../persona-ux-2026-10-15/fixtures.json)，验收条件来自同目录的 [`反馈.md`](../persona-ux-2026-10-15/反馈.md)。全部人物与材料均为合成数据。工具不导入 backend，不读取配置或凭证，不调用登录、导出、邮件、私有样例或部署接口。

## 运行

先启动一个**隔离数据库的本地测试服务**。如果已有 `http://127.0.0.1:8833` 测试实例，可直接使用。需要启动时，在仓库根目录执行以下命令；服务端的模型配置按现有方式自行配置，回放工具只用游客 cookie：

```sh
replay_tmp=$(mktemp -d /tmp/huhua-persona-XXXXXX)
DATABASE_URL="sqlite:///$replay_tmp/application.sqlite3" \
CHECKPOINT_DB_PATH="$replay_tmp/checkpoints.sqlite3" \
APP_ENV=local \
.venv/bin/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8833
```

另开终端运行：

```sh
.venv/bin/python evaluation/persona-ux/run_persona.py \
  --base http://127.0.0.1:8833 \
  --output evaluation/persona-ux/runs/before

# 只重放选定人物，顺序与 --persona 相同
.venv/bin/python evaluation/persona-ux/run_persona.py \
  --persona tech,service --output evaluation/persona-ux/runs/after-small

# 旧版绕过流程的诊断；与默认回放分开比较
.venv/bin/python evaluation/persona-ux/run_persona.py \
  --with-recovery --output evaluation/persona-ux/runs/legacy-diagnostic
```

省略 `--output` 时使用 `runs/<北京时间时间戳>`。输出目录必须是 `evaluation/persona-ux/runs/` 的新子目录；拒绝覆盖。该目录由本目录 `.gitignore` 忽略。仅允许 loopback 服务地址，禁用代理和 HTTP 跳转。默认每个请求超时 300 秒，可用 `--timeout 600` 调整；超时/HTTP/SSE 错误停止该人物，保留证据后继续其他人物，不自动重试。全部断言通过退出 0，任一失败退出 1；参数/启动错误退出 2。

每人独立 `POST /api/chat/conversations` 获取游客 cookie 与 session。cookie 仅在内存 CookieJar 内使用，完成后清空；不保存请求头、响应头、cookie、session ID 或原始 SSE meta。游客仍可能在服务端留下临时记录，因此上面使用独立存储，服务停止后测试者可自行处理该临时目录。

设计先通过 `POST /api/chat/upload` 上传 `design-material.txt`，使用返回的文本，按前端格式拼接：`[文件: filename]\ntext\n\n---\n\n用户输入`。不是自己解析 TXT 后绕过上传接口。按照 fixtures 对象键的顺序发送，忽略 `role`，默认跳过 `recovery`；设计的 `paste` 仍保留。

### 方案确认的已核实契约

`web/index.html` 注册 `sendChoice: value => send(value, {quickReply: true})`；`web/resume-workspace.js` 的方案卡按钮把 `guidance.options` 的 `option.value` 传给这个回调。`backend/app/services/structure_plan.py:plan_guidance` 当前返回 `{"label":"按推荐写","value":"按推荐写"}`。

因此没有单独的确认 endpoint：同样 `POST /api/chat/stream`，请求为 `{"messages":[{"role":"user","content":"按推荐写"}],"session_id":"内存中的会话ID","task":"auto"}`。工具只在 API workspace 明确显示 `guidance.kind=structure_plan` 时，从 **实际返回的 options** 中选“按推荐写”的 value；不猜消息、不强制关掉服务端确认开关。缺少按钮值或确认后仍待确认会失败，每个 fixture 轮最多追加一次确认。

确认作为独立轮保存，`kind=confirmation`、`trigger_action=initial/followup/...`。首版断言检查 `initial` 及其确认后的最新稿；通用“直接生成”断言检查**确认前**的原始轮。因此确认能生成完整稿，也不能掩盖先给空稿的问题。附件首版不接受后面的 `paste` 或 `recovery` 补救。

## 输出和修复前后比较

```text
runs/<run>/run.json                 完整回放、输入哈希、耗时、汇总状态
runs/<run>/<persona>/01-initial.json
runs/<run>/<persona>/01-initial.reply.txt
runs/<run>/<persona>/02-initial_confirm.json  仅出现方案卡时有
runs/<run>/<persona>/checks.json    PASS/FAIL、稳定断言ID、字段与证据摘录
```

每轮 JSON 包含 input、公开 reply 全文、`/api/resume/current` 返回的已保存 resume_data 与 workspace、stage/revision、SSE 是否 `[DONE]`、错误以及流式/读取/总耗时。SSE 读取到结束，支持多行 data、CRLF、心跳；缺 DONE 或 error 事件都失败。失败后仍尝试读 current，避免只看到“已更新”而漏掉保存失败。报告不依据模型自评或聊天里的数字判断正文。

```sh
# 一次或多次 run 的完整断言表；顺序是旧→新
.venv/bin/python evaluation/persona-ux/report.py \
  evaluation/persona-ux/runs/before evaluation/persona-ux/runs/after \
  --output evaluation/persona-ux/runs/comparison.md
```

report 对原始轮次使用当前 checks 重新计算，不信任历史缓存的 PASS。每条断言列出每次 run 的结果、首末改善/退化、证据摘要。不同人物标为 MISSING；fixtures 哈希或 recovery 设置不同会提示对比条件不同。没有旧 API run 时，浏览器 capture 只用于下述离线断言回归，不能冒充旧 API 全量回放。检查在 JSON 中留有全部摘录，Markdown 只取前两个摘要。

## 断言目录

稳定 ID 为 `<人物>.<下列后缀>`。每个人物包含 5 条通用断言，总计 **71 条**：tech 17、ops 13、career 13、service 14、design 14。

| 人物 | 专属断言 ID | 条件 |
| --- | --- | --- |
| 通用（每人5条） | `common.rounds_complete`、`common.one_question`、`common.direct_first_draft`、`common.public_language`、`common.first_draft` | 脚本顺序与完整 SSE/回复；成稿“需要你补充”至多一次；直接生成当轮确认前不空；无 internship/project/“当前排版为0档”；initial 后有经历成稿。没有直接生成措辞时该项显式标明不适用措辞，首稿仍独立验收。 |
| tech（12专属） | `initial_internship`、`initial_project`、`single_project`、`skills` | 云舟科技实习/校园二手交易系统正确进入栏目；项目一个条目；Java、Git、Redis（了解），无 Kubernetes。 |
| tech | `mentor`、`test_environment`、`no_online_load`、`team_scope` | 导师指导、测试环境、未做线上压测；同学负责登录、实验室演示/无真实用户。不能只在备用列表提及。 |
| tech | `polish_identity`、`polish_scope`、`correction_190`、`correction_other_numbers` | 润色前后教育 school/major/degree、姓名和 objective 完全相同；其他栏目不改；190ms 替170ms；420ms、12条和其余数字不变。 |
| ops（8专属） | `posters_ownership`、`no_placeholder_campus`、`no_raw_duplicates`、`association_dates` | 4张海报只归小巷咖啡；无占位校园项；无两句重复原话；协会日期2024.09—2025.06。 |
| ops | `no_readership_followup`、`numeric_outputs`、`no_invented_operations`、`polish_scope` | 已说明无数据后，公开问句或 guidance 不再追问阅读量；8/3篇、6/2条保留；无增长/独立运营断言；只改咖啡店。 |
| career（8专属） | `initial_named_work`、`no_instruction_body`、`correction_four`、`correction_other_numbers` | 首版为启明商贸工作；正文无杂项条目、姓名与生成指令；4场替6场；120人、30份及其他数字不变。 |
| career | `retained_duties`、`no_invented_customer_outcomes`、`transition_evidence_gaps`、`polish_scope` | 每版保留通讯录、培训、报销、接待，或同版核对的 fact_coverage 明确 omitted+reason / verification_notes 明确备用；不编造续费/客户培训/CRM/销售；回复区分迁移能力与证据缺口；其他栏目不改。 |
| service（9专属） | `single_education`、`school_clean`、`polish_identity`、`polish_education`、`no_instruction_major` | 教育一条；学校精确为新城职业学院；润色不改个人与教育字段，不出现“写得更”。 |
| service | `approval_limit`、`complaint_limit`、`volume_800`、`polish_scope` | 退款主管审批、复杂投诉转交主管、800次咨询保留；其他栏目不改。 |
| design（9专属） | `initial_project`、`initial_education_major`、`initial_volunteer_posters`、`attachment_not_jd` | 附件首版含借物App项目12页面/18组件、学校专业学历、独立志愿者6张海报；本人材料不进JD。 |
| design | `no_negative_skills`、`single_course_project`、`concept_limit`、`no_invented_design_results`、`polish_scope` | 技能无否定项；课程一个项目；保留概念/课程/未上线限定；无上线/增长/转化验证成果；只改课程项目。 |

断言读取实际展示字段：隐藏条目和被移除栏目不算正文，项目优先 polished_bullets，技能优先 skill_groups；原始 facts、旧 description 或 workspace 经历栏不能冒充已经写入。缺证据通常判 FAIL。教育/姓名/意向按原值比较；数字按可见正文的数字多重集比较，忽略被点名更正的 ms/场数，不把措辞改变当数字改变。未请求的栏目按去生成ID后的内容精确比较。

边界：这是固定材料的词法/结构验收，不是通用语义评审。“方法提炼好不好”“转岗判断是否有说服力”无法完全确定性判断；第7项完成条件在这里验收已有迁移词与缺口提示，以及设计交付的具体证据。否定语境与同义词仅覆盖明确模式，新的同义表达可能需补规则；无虚构断言也不能保证抓住所有编造。API 验收不覆盖 iframe 当前可见版本、模板排版、手机操作、登录接续或正式导出。

## DeepSeek 调用量与费用提示

**真实回放会使用服务端已配置模型，预计全量一次约70次逻辑模型调用，预算范围约60–100次；不是14次模型调用。** 默认 fixtures 是14轮聊天（tech3、ops3、career3、service2、design3）；`--with-recovery` 为17轮，预计约75–120次。每次方案卡确认再增加一次聊天请求；假设5个首轮及2个补材料轮均出现方案卡，会额外增加5–7次请求（合计19–21次）。新版直接生成路径可能跳过卡片，实际数量记录在 `stream_requests`。

估算依据当前代码：`resume_graph.py` 的收集/编辑会经过 fact_extractor、可选 extract_verify、triage/router；`resume_writer.py` 默认 one_pass 一次计划+正文，确认流程则先 StructurePlan 再 WriterDraft，之后有 guard_semantic/guard_summary/定位核验；润色通常还需 router+writer+guard。粗算五个首轮和两个材料补充轮约35次、五轮润色约20次、两轮更正约4–6次，方案确认与定位核验补约10次，约70次。

这是从调用路径估计，API 没返回实际 LLM usage/call ledger。部分路由和更正能确定性短路；自动润色（`writer_polish` + `polish_semantic`）、schema/事实修复、writer重试、最多2轮容量压缩（`resume_capacity.py:MAX_COMPRESSION_ROUNDS`）、供应商HTTP重试会增加次数。上述范围不是硬上限，也不能直接换算金额：费用还依赖服务端模型、上下文长度与缓存。TXT上传、GET current、checks、report、下面的桩测试本身都不调用模型。本次实现只跑离线验证，**未启动真实模型回放**。

## 离线测试

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_persona_*.py' -q
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py
```

`test_persona_checks.py` 用明确 capture preview 索引及据此构造的数据检验旧失败，避免混用双 iframe 的新旧稿。完整合成稿验证全部断言的通过路径；变异数据检验字段污染、数值变更、责任丢失、隐藏栏目、备用解释、无关改稿与错误提示。`test_persona_runner.py` 用 stdlib HTTP handler + socketpair 桩服务覆盖 HTTP线协议、游客隔离、真实 multipart上传格式、完整 SSE、失败留证、方案确认和CLI；socketpair让禁用监听端口的沙箱也可执行。`test_persona_report.py` 覆盖完整表、修复/退化/MISSING、缓存不可信、Markdown转义与CLI。

若本轮禁止访问私有样例/配置，统一离线脚本仍不足以阻止现有私有测试读取实际文件；应像本次验收一样在排除 `cases-private/`、`runs-private/`、运行数据和凭证的临时源码副本里执行完整命令，保留未分发私有样例的skip状态。勿在原仓库主动跑那两项私有测试。

本次交付验证（2026-10-15）：新增人物检查/报告/桩HTTP测试 **43项全部通过**；上述完整命令在 `/private/tmp/huhua-persona-safe-zp85_9g4` 执行 **1523项，1521通过、2项未分发私有样例跳过、0失败，51.938秒**。摘要日志 `/private/tmp/huhua-persona-accepted.log`。公开 `data/sample_resume.json`、`data/tech_terms.txt` 和无凭证配置示例保留在验证副本中；原始 `.env`、私有材料和运行数据库排除。测试覆盖 API 协议与断言实现，未证明当前真实模型已通过这71条验收。
