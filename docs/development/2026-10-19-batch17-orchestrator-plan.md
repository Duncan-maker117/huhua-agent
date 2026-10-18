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
