# 第十七批第 2 期第三轮：P2i

日期：2026-10-19。工作分支 `batch17i`。本次只修 loop 问题卡作答与编排衔接、结构字段、回执和对应评测；off 的入口、收集节点、答案默认处理与追问行为保持原样。

## 根因与冻结证据

已阅读规格及 P2e/f/g/h 说明；只读核对相邻 `huhua-b17b` 的 `p2-loop-all-2/run.json` 和 `p1-off-all-5/run.json`，没有改写相邻 worktree。

- loop 作答原来被 `_orchestrator_requested` 排除，进入 `collecting → _intake_form_turn → _collection_reply`。旧节点自行继续出卡，下一次自由输入又回编排；出稿后自动附卡也没有共享会话深度计数。aipm_real 第 4 轮已有 labeled 稿，后续 5 次答卡、一次自由回答和越限直接写仍继续追问。
- `apply_answers` 把名称等答案作为普通 action fact 保存，没有填入条目的 name/start_date/end_date/role。结构化标题仍由原字段生成；旧 live preview 也不能修复这些缺失。冻结 answers_3 的公开回复为空，名称答案没有替换最终占位标题。
- **ops 的 contacts_once 不是两轮真实索要。** 首轮正文已提电话/邮箱，确定性收尾又补问手机/邮箱，存在同轮重复；检查器原本按用户轮去重。真正使该检查失败的是第二轮的“手机拍摄…文案由店长提供”同时命中“手机”和“提供”。没有把这个误判解释成模型真的第二次索要。
- returning 最新回放使用“从档案里导入的…”并逐项列名；P2h 所述旧回放使用“直接采用了两段”等完成态。旧检查的正则漏掉这些表达，同时只要求任意一句有完成态，不能证明所有被点名的条目都已采用。

源 run.json SHA-256：

- off：`2b5d5b90adaabe754fecdbe161c6b1f7298c6a0b2818ec619a6b0ab0fac43844`
- loop：`366d4b0c06ff435f16414f521b7a518a08aca89c8b89df72deace5fde466a1ea`

## 实现与边界

1. **确定性记录后交给编排。** loop 的 answers 进入 orchestrator；普通 intake、方案选择和显式任务保留原路径。进入模型前调用既有 `apply_answers`、`close_answers`、`_persist_intake` 和保存回调，不把题干或未选选项重新送进自由抽取器。当前答案来源标为已记录；模型再调用 record_facts 会得到 unchanged。历史答案来源也只能走确定性答案处理。模型失败仍保留已经记录的事实和关闭记录。
2. **共用深度上限。** 核对源码后发现旧生产链没有全会话轮数常量，旧 aipm/off 回放的实际上限是 `MAX_ROUNDS = 6`，aipm_real 复用它。本次将同一个值移到 `intake.MAX_FOLLOWUP_ROUNDS`，旧回放仍以别名读取，未提高数值。loop 按历史用户轮统计已展示的问题卡和文字追问；同轮的卡片、正文以及 checkpoint 中重复的卡片只计一轮。工具、自动作答后附卡和公开文字共用预算，压缩上下文也提供剩余判断。上限检查在新问题出口，不放进 pending_card 恢复逻辑，因此最后一张合法卡仍可提交。若整轮全为不知道/跳过，则结束可选深挖，避免换维度继续盘问；后续主动补充仍可记录和写稿。原关闭维度记录不删除、不重新开放。
3. **标题字段回写。** 仅 loop 启用 `apply_answers(..., project_fields=True)`，复用 intake 字段事实写入方法，保留原题 ID、题干、答案、turn_id 和来源。明确的名称、开始/结束时间和角色分别填入相应字段；工作/实习角色对应 title。只有 `placeholder_name` 判定的名称可被替换，真实名称保留。归属不唯一、过期卡、未选且不允许自填的选项不写入；无法确定为字段的时间或已有真实名称的不同答案仍保留为回答事实，不猜结构值。多选不能用最后一项覆盖整个标题字段。开始/结束在 loop 使用不同关闭维度，off 维度规则不变。
4. **已生成稿的标题同步。** 答案记录后立即按 item_id 投影字段到当前稿，沿用版本事务、页数测量和正文引用/hash；即使收尾模型失败，也不会丢掉已确认的标题。后续 loop writer 前后再次投影，防止写稿回退重新带回占位字段。定位/性质继续由原结构方案负责，用户没提供的时间不会凭空补齐。
5. **公开回复非空且可核对。** 作答轮总有确定性回执：已记录的信息类别（或不知道/跳过/失效状态）、稿子实际是否变化、下一步。没有有效模型正文时仍有收尾文本。流式正文按句缓冲，在公开事件前过滤越限/已关闭追问与模型自行索要联系方式；不是等流完后只改 checkpoint。公开事件拼接和最终 AIMessage 用同一内容。
6. **联系方式全会话一次。** 模型正文里的索要由出口过滤，成功写稿时的缺项由代码一次补齐；问题卡仍以同一个 contacts_requested 状态去重。按本任务“全会话最多一次”取消 loop 的导出重问例外。已收到邮箱不能掩盖同句仍索要手机；“手机拍摄/拍照/剪辑/录制”在工具及检查器里作为设备用途处理，混合的真实联系方式请求仍计入。不改联系方式入模型前的脱敏边界。
7. **returning 判定纠错并收紧归属。** 允许“采用了”“导入的”“从档案选了”等完成态，但每个指定导入经历名称必须出现在自己的完成态语句，或紧随完成态标题的点名列表；仍要求同轮可见稿件含全部指定经历。只说“两段”、只点名一段、另一个名字只出现在档案介绍、否定、将来、询问、失败或无实际可见数据均失败。

## 文件与离线回归

- `backend/app/agents/resume_graph.py`：loop 答卡分流，仅一处入口条件。
- `backend/app/agents/{orchestrator,orchestrator_tools,orchestrator_context}.py` 与新增 `loop_followup.py`：确定性作答前置、共享预算、公开收尾、联系方式与 writer 字段投影。
- `backend/app/services/{answer_facts,ask_user,intake}.py`：字段事实/标题投影、loop 专用身份维度、共用原上限常量。
- `evaluation/persona-ux/{aipm,loop_checks,returning}.py`：上限别名、设备用途反例、完成态逐名称归属。
- 新增 `tests/test_orchestrator_p2i.py`：13 项测试，含多个子场景。覆盖失败前保存、名称保护、字段来源/幂等/选项/时间、off 默认不变、禁止二次抽取、空正文回执、unknown/skipped/文字未知、卡片与文字共享上限、最后一张卡仍可作答、重复联系方式/导出/逐字符流、检查器正反例。
- 同一文件的 aipm/aipm_real 离线桩回放使用现有 runner、真实 LangGraph 路由、问题工具、答案处理、结构方案/labeled writer/guard/version 链；仅抽取模型、编排模型、写作模型、候选题和页数测量用离线替身。保留两人物原输入与答案来源，校验最终标题、定位、正文引用/hash、没有越限、每轮非空和模型入参无手机/邮箱。该 runner 适配器的 SSE 标志是桩元数据；另一个真实 `stream_agent` + 内存 SQLite 测试核对流式输出、canonical 回读与 checkpoint 关闭记录，未启动 HTTP 服务。

旧测试只作两项明确的需求变更，未放宽事实、写法、深度或隐私断言：

1. `test_orchestrator.py`：loop answers 的路由期望由 collecting 改为 orchestrator，补充 off answers/intake 仍走 collecting 的断言。
2. `test_orchestrator_writing.py`：导出时允许再次返回 contacts_missing 改为不得再次返回，对应本轮“全会话最多一次”。其余跨轮、失败出稿、完整联系方式与问题卡断言保留。

## 冻结重评与验收

[p2i-frozen-comparison.md](p2i-frozen-comparison.md) 仅为已有产物重评，不是本次修改后的真实模型回放。与源 checks 逐项对照，off 无变化；loop 仅 `returning.profile.import_receipt` 和 `ops.loop.contacts_once` 从失败变为通过，总计 154/168。aipm 11/14、aipm_real 5/16 的旧失败仍保留，尤其不改首稿总轮数口径、标题、事实或深挖上限。

验证记录：

- P2i 定向：13 项全过，0.635s，`p2i-targeted-tests.log`。
- 原编排定向：113 项全过，1.038s，`p2i-orchestrator-tests.log`。
- 全量入口未发现的 P2e 上下文回归：15 项全过，0.449s，`p2i-context-tests.log`。
- 首次全量：2161 项，2159 通过、2 项原有跳过，0 失败/错误，87.089s。后续补充混合联系方式语句与文字未知选项回归，最终全量以完成记录为准。
- **最终指定全量：2162 项，2160 通过、2 项原有跳过，0 失败/错误，88.102s，退出码 0。** 日志 `p2i-full-tests-final.log`，包含全部 13 项 P2i 回归。
- 改动/新增 Python 文件的 Ruff、AST 与 `git diff --check` 通过。

指定入口：

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

日志按仓库规则忽略；测试数据库由临时目录或内存创建，不写死 `/private/tmp`。

## 失败做法与未完成

- 没把 ops 的失败直接归因于第二轮真实索要；逐句核对后，分别修同轮重复与设备用途误判。冻结结果没有冒充新的真实通过率。
- 首次按句缓冲只检查已发布片段，导致无句号结尾的模型回复被再次追加。原协议/流式测试实际失败后，补上尚未发布的缓冲判断；原断言没有放宽。显式停止的工具错误码也保持旧契约。
- 新预算测试一度把经过模型投影的结果卡当完整 UI 卡使用，其中 turn_id 已按原规则清除；改用实际 UI/状态卡验证最后一张卡可提交。一次补丁因测试上下文引号不一致未应用，重读局部后重新应用；没有部分生产改动遗留。
- 尚未进行新的真实模型回放，不能据此宣称真实质量、延迟或 aipm/aipm_real 全部检查已通过。自然语言字段识别和公开追问判定仍为保守词法规则；不确定的时间保留为事实、不猜日期，复杂措辞的真实效果仍需后续回放检验。
- 没有调用真实模型、访问 8833/8834、启动应用服务、改 dist、commit、push 或部署；相邻任务 worktree 未写入。
