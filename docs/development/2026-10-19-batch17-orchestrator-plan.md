# 第十七批 第 1 期：编排 agent（模型决定做什么，代码守底线）

> 起点：分支 `batch17s`（main 0a35e35 + 第 0 期 spike 9130a15）。第 0 期结论见 `evaluation/agent-loop-spike/`（真实 DeepSeek 3 轮×2 模式）。
> 用户目标：**一个很会做简历的 agent**。先展示价值，再引导用户自我介绍；联系方式到成稿前才要；先写后问。

## 第 0 期结论（决定本期设计）

- 思考模式 + 自行回传 `reasoning_content`（spike 用 openai SDK 直连流式接口）多步工具调用无 400。
- 思考模式在事实记录上明显更对：自我介绍 3/3 先 record_facts（关思考 0/3）；用户答「不知道」0/3 拿空信息出稿（关思考 2/3 出稿）。代价：中位 ~5.5s / 尾部 ~11s（关思考 ~3s / 5s）。
- **本期编排用思考模式**；用流式最终回复 + 工具进度事件缓解等待。
- 待调：有档案时「我的经历有什么能用」思考模式偏保守（2/3 先问不导入）——用系统提示原则调，不加规则。
- spike cases 04/08 把「写稿后 ask_user」列为禁止，与先写后问冲突——本期改为允许。

## 架构

```
用户自由输入 ──(AGENT_MODE=loop)──> orchestrator 节点
                                     思考模式，≤4 次工具执行 + 1 次最终回复（流式）
                                     工具 = 现有能力的适配器（返回: 给模型的结果, 状态更新, 界面事件）
界面结构化动作（表单提交 / 问题卡作答 / 方案选择 / requested_task 按钮 / 导出 / 编辑器保存）──> 原有确定性路径
AGENT_MODE=off（默认）──> 完全保持现有行为
```

### 工具接口（三个任务共同遵守，文件边界见分工）

`backend/app/agents/orchestrator_tools.py` 提供：

```python
@dataclass
class ToolOutcome:
    result: dict            # 给模型看的结构化结果（会经 ContactRedactor 脱敏、包在 untrusted_data 中）
    update: dict            # 合并进 ResumeState 的增量（collected_info / jd_info / resume_data / messages 以外的字段…）
    events: list[dict]      # 界面事件：{"type":"tool_status", "tool":..., "status":"running|completed", "message":...}
                            # 以及需要直接展示给用户的卡片（ask_user 卡、方案卡等，沿用现有 workspace/guidance 结构）
    stop: bool = False      # True 表示本轮应在此后直接给最终回复（例如 ask_user 已出卡、write_draft 已出稿）

TOOLS: dict[str, ToolSpec]  # name -> (pydantic 参数模型, 描述, async handler(state, args, ctx) -> ToolOutcome)
```

- 工具参数里**不接收模型生成的事实正文**：record_facts / read_jd 只接收 `source_id`（本轮或历史用户消息 id），原文由代码取（沿用 spike 约定）。
- 工具不足条件时返回结构化原因（如 write_draft → `{"status":"insufficient","missing":["至少一段经历的具体做法"]}`；`{"status":"need_contacts"}` 表示成稿前尚无手机/邮箱，提示模型此时再问），而不是由路由拦截。

| 工具 | 包装的现有能力 | 备注 |
|---|---|---|
| read_profile / use_profile_items | `services/profile_tools.py` | 已有，迁入统一接口 |
| read_jd(source_id) | jd_input_node 中的 JD 解析 + job_intel 链接读取 | 结果写 jd_info；JD 文本永远是数据 |
| search_company(name) | job_intel search_company | 每轮至多一次 |
| record_facts(source_id) | collecting_node 的事实抽取与落库（fact_extractor + 本人/他人来源判定 + provenance） | 唯一的事实写入口 |
| ask_user(card) | services/ask_user.py 的 AskUser 校验与问题卡 | stop=True |
| propose_plan() | structure_plan_node 的方案卡 | 需要方案确认时用；stop=True |
| write_draft(direction?, emphasis?) | building_node / tailor 写稿链路（含 fact_guard、槽位校验） | 最低信息不足返回 insufficient；stop=True |
| edit_resume(instruction) | evaluating_node 的编辑契约 | 生成新版本，可撤销 |
| check_layout() | 现有页数测量（不写 PDF） | |

### 护栏（代码保证）
事实只经 record_facts；写稿/改稿结果过 fact_guard；联系方式不进模型（确定性投影进 resume_data.basic_info）；工具结果/JD/档案是数据；工具预算与超时；每轮模型调用数与 token 记录进日志（不含正文）；思考模式失败（协议错误/400）时本轮降级为关思考重试一次并记录。

### 系统提示原则（不得写入任何测试人物内容）
1. 开场：简短说明能做什么并给出一个具体价值示例；邀请用户「随便介绍下自己——在读什么、做过什么、想投什么」；不索要手机/邮箱/姓名。
2. 用户提供任何本人信息（自我介绍、粘贴材料、旧简历）→ 先 record_facts。
3. 有档案且本会话缺素材 → 先 read_profile，挑与方向相关的直接 use_profile_items 并说明理由（不要先问）。
4. 有一段带具体做法的经历即可 write_draft（先写后问）；成稿后针对最弱的条目用 ask_user 追问 1 个维度。
5. write_draft 返回 need_contacts 时，才请用户补姓名/手机/邮箱（一次问齐）。
6. 用户说「不知道/跳过」→ 不追同一维度，不拿空信息出稿。
7. 每次回复：做了什么 → 为什么（1–2 句判断依据）→ 下一步（一个明确选项）。

### 开场与界面
- loop 模式下新会话不自动弹基本信息/经历清单表单（intake_guidance 不出卡）；问题卡只由 ask_user 产生。
- 首屏入口按钮（前端）：「我有 JD」「我有旧简历」「先聊聊我的经历」「看看你能做什么」；点击即发送对应引导文本（走 orchestrator）。
- tool_status 事件在聊天流中显示轻量进度（「正在读岗位…」「正在记录你的经历…」「正在写第一稿…」）。

## 分工（三个 Codex 并行，worktree 各自从 batch17s 拉出）

- **P1a 工具适配器**（`../huhua-b17a`）：只写 `orchestrator_tools.py`（+ 必要的小幅抽取：把节点中可复用的纯函数提出来，节点行为不变）与其测试。不改路由、不改前端。
- **P1b 编排节点 + 接线**（`../huhua-b17b`）：`orchestrator.py`（以 spike 为基础，生产化：LangChain 外的 openai SDK 流式、思考回传、流式最终回复接入现有 public_reply 事件、tool_status 事件、状态增量合并与 checkpoint）；`AGENT_MODE` 设置；`route_by_stage` 顶部分流；loop 模式关闭 intake 自动出卡；首屏入口按钮与 tool_status 显示（前端 JS 结构，视觉由 Claude 做）。对 P1a 的依赖：先按上述接口写一个最小 stub registry，合并时替换。
- **P1c 评测**（`../huhua-b17c`）：spike cases 更新（04/08 允许写后 ask_user；新增「有档案+明确方向」「自我介绍后马上要求出稿」「中途换方向」）；`run_persona.py` 支持 `--agent-mode loop`（通过服务端设置或请求头，择一并说明）；新增人物 `cold`（只说「你好」→ 自我介绍 → 一段经历 → 补联系方式）与 `upload`（第一句粘贴整份旧简历文本），检查：首轮无表单卡、≤3 轮出第一稿、联系方式只被要一次、简历无编造（沿用 checks 的事实检查）、每轮模型调用数与耗时记录。现有 8 人物检查在 loop 模式下也要能跑（不要求本期全过，作为对比基线）。

## 验收（第 2 期回放调优的起点）
- AGENT_MODE=off：全量测试与现有回放基线不变。
- AGENT_MODE=loop：cold / upload / returning 真实回放通过上述检查；现有 7 人物给出对比报告。
- 不 commit 到 main、不部署；Claude 合并三支、跑真实回放后再定。

---

# 第 2 期：回放调优（起点 batch17b 41a8ec3）

## 第 1 期真实回放结果（runs/p1-loop-all-5 vs p1-off-all-5，同一提交、同一模型）

| 人物 | off | loop | loop 未过 |
|---|---|---|---|
| cold | 9/11 | 16/16 | — |
| upload | 8/10 | 14/15 | facts.no_extra_experience（「不是」，已由 d 修，待复测） |
| returning | 6/6 | 10/11 | profile.import_receipt |
| tech | 17/17 | 21/22 | correction_190 |
| ops / service | 全过 | 全过 | — |
| career | 13/13 | 16/18 | correction_four, loop.contacts_once |
| design | 14/14 | 18/19 | loop.contacts_once |
| aipm | 8/9 | 10/14 | heading, labels, answers_used, no_repeated_dimension |
| aipm_real | 11/11 | 4/16 | 结构化写法整体缺失、未在 3 轮内出稿、联系方式重复问等 |

其它观察：编排层每轮平均 24.8s（最长 72.8s），平均 3.7 次模型调用；单次调用 prompt 平均 13.7k、最大 85k token（工具结果含整份 resume_data / 事实 JSON、历史 16 条全文）。回复中出现内部标识（「对应信号 s1」）。开场价值示例出现编造数字（示例写了具体涨粉数）。

## 分工（三个 Codex 并行，按文件边界，不得越界）

### P2a 时延与上下文（只改 `backend/app/agents/orchestrator.py` 中除 `SYSTEM_PROMPT` 以外的部分；可新增 `backend/app/agents/orchestrator_context.py`）
- 发给编排模型的工具结果做压缩投影：不发整份 resume_data/事实全集，改为摘要（条目名、每条要点首句/数量、版本号、页数、缺失项、错误码），保留模型决策所需字段；长文本截断并标注。
- 历史压缩：保留最近若干轮原文，更早的用一段确定性摘要（已记录的经历名、方向、已问维度、已有稿版本），不调用额外模型。
- 稳定前缀：system + tools schema 放在最前且逐轮不变，便于 DeepSeek 前缀缓存（记录 `prompt_cache_hit_tokens` 若接口返回）。
- 评估「收尾回复轮关闭思考」：决策轮保持思考，纯文字收尾轮用 off；给出离线可测的开关（设置项），默认值由 Claude 实测后定。
- 指标：每轮日志增加各次调用 prompt/completion/reasoning/cache 命中 token 与耗时（不含正文）。目标：单次调用 prompt 中位 ≤ 6k、最大 ≤ 20k。

### P2b 写作对齐与行为（只改 `backend/app/agents/orchestrator_tools.py` 与 `orchestrator.py` 的 `SYSTEM_PROMPT` 常量；必要时小幅抽取 resume_graph 内可复用函数，节点行为不变）
- write_draft 与旧流程成稿质量对齐：旧流程成稿前有结构方案（structure_plan，含岗位手册 labeled 写法、问题/决策/迭代标签、标题行「名称｜定位｜性质｜时间」）。loop 下 write_draft 必须走同一结构方案与 labeled writer（自动采用推荐方案；用户已明确选过写法则沿用），而不是直接 tailor。以 aipm / aipm_real 的 heading、labels、answers_used、real_pains 等检查为准。
- 用户修正（「改成 190」「改成四条」等数字/条数修正）走旧流程同一编辑契约，确认 tech correction_190、career correction_four 场景通过。
- 联系方式只问一次：状态里记录已请求联系方式；用户未回答也不再重复问（除非用户要导出且仍缺）。
- 工具结果中的内部标识（信号 id s1/s2、slot id、fact id、内部字段名）不进入模型可见文本；系统提示要求不向用户提内部编号。
- 系统提示：开场价值示例只能用明确标注为「假设」的示意，且不得出现具体编造数字；导入经历后回复必须点名导入了哪几段（returning import_receipt）。

### P2c 评测（只改 `evaluation/`、`tests/` 中评测相关文件）
- loop 模式下 aipm / aipm_real 等依赖问题卡的人物：runner 对 ask_user 卡按既有答案契约作答（与 off 模式相同的答案来源），不能因 loop 不出卡就提前结束；记录每轮 orchestrator 指标（调用数、token、耗时）并在报告中给出两模式对比表。
- 检查项复核：`loop.contacts_once` 的判定是否会把「出稿后一次问齐」误判；returning `import_receipt` 判定是否过度依赖字面「导入」。如判定本身有误，修判定并在说明中写理由；不得为通过而放宽真实缺陷。
- 新增 `scripts/compare_persona_runs.py`：输入两个 run 目录，输出 markdown 对比表（通过率、未过项、平均/最大每轮耗时）。
