# 第十七批第 2 期第五轮：P2k

日期：2026-10-19。工作分支 `batch17k`，起点 `e51b15e`。已读 P2h/P2i/P2j 和根目录交接，初始工作树干净。仅修 loop 的标题维度、答卡后的定向写作和深挖接续；不改 writer/guard、手册、评测质量断言或 dist。

## 根因与只读证据

只读核对 `../huhua-b17b/evaluation/persona-ux/runs/{p2-loop-all-4,p2-loop-var-1}/aipm/`，两次均为首轮 `start_date` / `end_date` 两题、`answers_1` 无后续 guidance，原检查失败项均为 `labels`、`answers_used`、`no_repeated_dimension`。

- P2j 标题生成按字段出题，P2i 又将 loop 的起止时间分别映射为两个关闭维度；同一时间维度被问两次。
- 自动 followup 只挂在 `write_draft` 成功结果上。答案已确定性保存，但后续是否写稿/改稿/提问仍由编排模型决定；模型直接收尾或调用 `edit_resume` 后不会接上下一张卡。
- `question_candidates` 的词法线索会跳过已有相关词的维度；稀疏事实不等于已有足够的岗位深度。单靠候选题可能提早耗尽，且原 intake 的 `deepen_context` 在已成稿阶段直接返回 ready，不能直接调用整个旧收集节点续问。
- 原“整卡未知/跳过”设置 `questions_finished=True`，会提前终止其他未关闭维度；与本轮“预算用尽或维度全关才停”冲突。

源文件 SHA-256（未改写原回放）：

| 来源 | initial | answers_1 |
| --- | --- | --- |
| all-4 | `aadcbcc17861d6d5293eac96e58f37d6af7fc579770b0fda756244df93be0745` | `22fb24c195e219e12c15b724194b600a9d898c82723de2ebf0fe6522e2afbd66` |
| var-1 | `a854aa733ea89a0b555a770de0b9d89f6a7feed8682ae6bf53c08b23a516ad33` | `07a127b576eb884e7044ba01d799cb66269c0f69749d5b8ecbbbd663f6b975ba` |

## 修改文件与行为

- `backend/app/agents/orchestrator_tools.py`：标题卡的起止日期合并为 `dates` 一题；只缺一端时仅问缺项，名称与角色各一题。继续使用原主经历选择、隐藏/backup/零行排除及唯一归属规则。深挖复用共享的岗位维度表与 `question_candidates`；AI 产品按原 deepen 的问题/分工/决策/迭代等顺序取未关闭维度，优先使用匹配候选的具体题干，缺候选时使用该维度问题。其他岗位保留原候选优先级，再补手册维度。档案已覆盖或用户已关闭的维度不重问。
- 同文件 `rewrite_answer_items`：只有本轮新增加、有效且属于可见条目的深挖事实才调用既有 `_write`；通过 `scope=item` 与稳定 item_id 限定条目，沿用确认方案与原写法。标题日期/名称/角色、未知、跳过和同消息重试不触发正文重写。既有 AI 产品 labeled 写法、事实核验、来源引用、版本与测页路径保持不变，不由编排代码拼接简历标签。
- `backend/app/agents/orchestrator.py`：有效答卡轮固定为“记录/标题投影 → 按需定向 writer → 确定性一张后续卡 → 文字收尾”。writer 使用工作状态副本，异常不污染原稿，答案和关闭记录已先保存；写作失败或收尾模型异常仍可接续卡。编排模型此轮只收尾，不能再调用第二张卡或额外改稿；公开文本也过滤额外追问。自动写作/附卡分别记录耗时及状态，结果脱敏后送给收尾模型。
- `backend/app/services/intake.py`：只把原有岗位维度表提取为 `deepen_dimensions`，由 off 的原 `deepen_context` 与 loop 共用。旧 intake 的阶段和完成条件未改；loop 不调用整个旧节点，也不重开收集表单。
- `backend/app/services/{answer_facts,ask_user}.py`：loop 时间统一为 dates，兼容旧 start_date/end_date 关闭记录。一个答案可确定性解析年/月区间或“至今”，分别投影两个标题字段，同时保留原答案、题 ID、turn_id、来源；不确定文本仍仅保存为事实、不猜日期。未知/跳过仍永久关闭本维度，移除其对整场深挖的提前终止。显式停止、pending plan 和原 `MAX_FOLLOWUP_ROUNDS=6` 保护保留，最后一张卡的答案仍会保存/写稿。
- `evaluation/persona-ux/aipm.py`：仅补合并日期问题的答案装配，读取既有 INTAKE 的 start/end；aipm_real 复用。VALUES、输入事实、交付/标签/答案使用/改写/深度/隐私检查均未改。

## 新增测试与离线回放

新增 `tests/test_orchestrator_p2k.py` 共 8 项测试（含多个子场景）：

1. 合并日期的多种分隔格式、单边缺项、非法/未知日期不猜测、原答案来源与重试幂等。
2. 模型尝试拆日期/名称/角色时同维度只保留一题，旧日期关闭记录仍有效。
3. 标题答案直接回写，不调用正文 writer；收尾模型失败仍接问题维度卡。
4. 未知/跳过只关当前维度，直到全关；每轮一张卡，全关后的文字追问也被抑制。
5. 达到六轮上限时仍记录最后一张卡答案并只重写对应条目，保护另一条目，不再附卡。
6. writer 异常保留新事实与旧正文，仍接续一张卡。
7. 失效卡和明确停止不附卡，不触发额外写作。
8. 使用现有 aipm runner、真实 LangGraph 路由、答案服务、writer/guard/version 链，从仅含本人分工、产品用途和已上线事实的稀疏初稿开始重放。抽取、编排、写作/语义模型及测页为离线桩；没有预载后续答案，也没有替换生产 question_candidates。逐标签核对引用确实来自相应问题/决策/迭代答案，检查正文 hash 和全部出站请求无手机/邮箱。

回放记录：[p2k-offline-replay.json](p2k-offline-replay.json)。

| 用户轮 | 当轮卡片 | 正文变化 |
| --- | --- | --- |
| initial | dates（一题） | 仅“现状：已上线” |
| answers_1 | problem | 只更新日期标题 |
| answers_2 | my_work | 加入问题行 |
| answers_3 | decision | 分工不冒充产品决策 |
| answers_4 | iteration | 加入决策行 |
| answers_5 | evaluation | 加入迭代行 |
| answers_6 | 无 | 纳入评测事实；六轮共享预算用尽 |

最终四行标签为问题、决策、迭代、现状。该离线回放的 9 项原人物检查全部通过，包括本轮三个目标失败项；每轮最多一张卡，未触发越限直接写。**这不是新的真实模型 14/14 验收**，旧真实 11/14 产物保持原样。

## 旧测试调整逐条说明

没有删除或放宽事实保真、交付、出处、hash、写法、隐私及深度上限断言。

1. `test_orchestrator_p2j.py` 的 `test_missing_heading_precedes_depth_and_only_missing_fields_are_asked`：首卡四字段题改为 name/dates/role 三个维度；单边缺失题 ID 改为 dates，仍检查仅问缺项及标题齐全后原 evaluation 候选。
2. 同文件 `test_main_written_experience_uses_plan_and_excludes_hidden_empty_backup`：五个排除场景的日期题 ID 从 start_date 改为 dates；主经历及排除条件断言不动。
3. 同文件 `test_identity_binding_closed_dimensions_and_budget_are_preserved`：关闭名称后期待 dates/role 两题，保留稳定 item_id 归属、停止/预算条件。
4. 同文件 `test_model_cannot_replace_heading_card_and_budget_fallback_keeps_all_fields`：首卡期待 name/dates/role；模型不可换卡、预算失败仍附卡、仅一次 guidance 原断言保留。
5. `test_orchestrator_p2i.py` 的两个 unknown/skipped 测试：由关闭整场改为只关闭已答维度并继续，新增“不再问已关闭 evaluation”断言；未知不产事实、非空回执和公开文本过滤仍保留。
6. 同文件身份维度测试：loop 开始/结束的维度均期待 dates；off 原 dates 断言不变。
7. 同文件 stream/checkpoint 测试：两日期共享关闭记录，因此记录数从 4 改为 3；名称、日期持久化及流式输出一致性原断言不变。
8. 同文件两人物离线 runner：标题题改为合并 dates，随后第一深挖题从桩安排的 evaluation 改为共用岗位表的 problem；答卡轮的模型桩仅收尾，不再主动调用 write_draft，使接续与写稿必须由生产代码完成。原 aipm/aipm_real 最终标题/定位、交付、引用/hash、路由、六轮上限和联系方式不进模型的断言保留。

## 验证

- 首次指定全量：2177 项，2175 通过、2 项原有跳过，0 失败/错误，84.494s，退出码 0（`p2k-full-tests.log`）。
- **最终指定全量：2177 项，2175 通过、2 项原有跳过，0 失败/错误，83.399s，退出码 0**（`p2k-full-tests-final.log`）。aipm_real、cold、design 等既有离线回归均包含在本次全量中。
- 新增定向回归：8 项通过；额外 P2e 上下文回归：15 项通过，0.464s（全量入口不发现该 evaluation 测试）。
- 修改/新增的 9 份 Python 文件 Ruff、AST 与 `git diff --check` 全部通过。

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

日志按仓库规则忽略；测试环境使用原隔离入口、内存检查点与临时目录，未写死临时路径。

## 失败做法、未完成与边界

- 没有通过放松 no_repeated_dimension 或将日期硬塞正文解决失败；先合并问题，再接续真实深挖答案。
- 第一轮编排定向有 14 个失败断言、2 个错误：大部分来自日期合题/未知继续的新契约；另发现把维度表整体置前会破坏普通岗位原候选优先级，已恢复该顺序，P2h 原断言原样通过。未用修改 P2h 断言掩盖回退。
- 新写作桩最初直接复述问题事实，导出的 rewritten 检查失败。仅在测试桩加入通用语体替换后加强为全部 9 项人物检查通过；生产 writer/提示词未为测试改写。桩验证的是编排、事实流与现有核验链，不证明真实模型自然语言质量。
- 收尾审查补上自动 writer 的状态副本隔离及逐标签答案出处断言，因此首轮全量通过后再跑最终全量。
- 未进行新真实模型回放；真实语义质量、耗时和 aipm 14/14 仍待后续授权回放。模糊日期不猜值；writer 核验失败时可保留旧稿和已保存答案，不能保证该次生成必然采用全部答案。
- 未访问 8833/8834、调用真实模型、启动应用服务、修改其他 worktree 或 dist；未 commit/push/部署。仅本 worktree 修改和根 mmr 追加交接。
