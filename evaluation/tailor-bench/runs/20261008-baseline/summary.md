# Tailor PR0 · 旧链路逐版本基线

运行：2026-10-08T18:41:45.846549+08:00；源码快照 `a74210030bede74b76f693d5eaa3258e87dbabc6`。
写作模型 `deepseek-flash`；评审模型 `deepseek-v4-pro`。

本报告状态：**evaluated_pending_claude**。12 个合成用例，31 个变化版本（可见 30，仅内部 1）。
所有 truth 与事实疑点均待 Claude 审定。确认新增事实为 **null（未知）**，事实安全门槛尚未通过；模型无疑点也不等于复核确认。

## 总体指标

| 指标 | 结果 | 解释 |
|---|---|---|
| 最终稿要求覆盖 | 14/24 = 58.3% | 已验证评审结果的 observed lower bound；已知未覆盖 10，未知 0。不是人工确认覆盖率。 |
| 编辑执行 | 0/24 = 0.0% | 使用全部计划编辑作为分母；无 diff 17，错误 0，未运行 0，未评分 0，无稿 6，未遵循 1，不确定 0。 |
| 首稿 ≤ 2 个用户轮（进入成稿 stage） | 0/12 | 有正式首稿 1；反映旧状态机，仅凭它不能断言用户此前看不到正文。JD 消息计入用户轮数。 |
| 首次可见经历正文 ≤ 2 轮 | 8/12 | 有可见经历正文 9；要求经历 bullet/description 有实文，只有名称不计。 |
| 逐版本评分 | {'no_draft': 12, 'completed': 19} | 任一缺失/错误/未运行仍为评估不完整；no_draft 不代表质量或安全通过。 |
| 词法疑点 | 5 | 可见 5，仅内部 0；独立于语义疑点计数，可能重叠。 |
| 语义疑点 | 39 | 可见 39，仅内部 0；19 个版本完成模型语义评分，仍待人工。 |
| 平均轮延迟 | 9.782 秒 | 基于 59 个实际记录轮，非按用例平均值二次平均。 |
| Graph / Judge tokens | 462,690 / 107,311 | 仅报告 SDK 已记录 token；HTTP 重试次数未知。 |
| Pairwise 新版胜率 | N/A | 旧链路基线没有新版对手，不计算胜率。 |
| Guard 回退 / 误杀 | 未观测 | 旧链路无新语义 guard，不能伪记为零。 |

无最终可见正文的已运行用例覆盖记 0；有正文但评分缺失的要求记 unknown。即使 first_draft_turn 尚为空，已可见的 COLLECTING 版本也保留逐版评分和终稿覆盖，另列未完成首稿。
覆盖和编辑比例在评分未齐时只是已观测下界，不得用于宣称通过门槛。

## 每例首稿与终稿

五维顺序：JD 相关性 / 个人贡献 / 结果产出 / 专业表达 / 取舍篇幅，各 1–5 分。首稿质量取首次可见经历正文版本；进入成稿 stage 的 first_draft_version 及其质量另存 aggregate.json，指向 COLLECTING 时也不丢失。

| 用例 | Graph / 评估 | 首次可见正文五维 | 终稿五维 | 最终覆盖 | 编辑执行 | 首次正文轮 / 正式成稿轮 | 版本：可见/仅内部 |
|---|---|---|---|---|---|---|---|
| [ai-pm-01](ai-pm-01/transcript.md) | completed / completed | 2/3/2/3/2 | 4/4/2/3/3 | 2/2 | 0/2 | 2 / 未成稿 | 3/0 |
| [algorithm-01](algorithm-01/transcript.md) | completed / completed | 4/3/1/2/2 | 4/3/3/4/3 | 2/2 | 0/2 | 2 / 未成稿 | 3/0 |
| [backend-01](backend-01/transcript.md) | completed / completed | 3/2/1/2/1 | 4/4/2/2/3 | 2/2 | 0/2 | 2 / 未成稿 | 4/0 |
| [career-switch-01](career-switch-01/transcript.md) | completed / completed | 2/2/1/2/1 | 2/2/1/2/1 | 1/2 | 0/2 | 2 / 未成稿 | 2/0 |
| [data-01](data-01/transcript.md) | completed / completed | — (no_visible_experience) | — (no_draft) | 0/2 | 0/2 | 无正文 / 未成稿 | 1/0 |
| [design-01](design-01/transcript.md) | completed / completed | 5/4/3/4/2 | 5/4/3/4/2 | 1/2 | 0/2 | 3 / 未成稿 | 2/1 |
| [direction-01](direction-01/transcript.md) | completed / completed | 3/2/1/2/2 | 3/2/1/1/1 | 1/2 | 0/2 | 2 / 3 | 3/0 |
| [frontend-01](frontend-01/transcript.md) | completed / completed | — (no_visible_experience) | — (no_draft) | 0/2 | 0/2 | 无正文 / 未成稿 | 1/0 |
| [import-01](import-01/transcript.md) | completed / completed | — (no_visible_experience) | — (no_draft) | 0/2 | 0/2 | 无正文 / 未成稿 | 1/0 |
| [minimal-01](minimal-01/transcript.md) | completed / completed | 1/1/1/1/1 | 4/5/2/3/4 | 2/2 | 0/2 | 2 / 未成稿 | 4/0 |
| [ops-01](ops-01/transcript.md) | completed / completed | 3/3/2/2/1 | 3/3/2/2/1 | 1/2 | 0/2 | 2 / 未成稿 | 2/0 |
| [pm-01](pm-01/transcript.md) | completed / completed | 2/2/1/2/1 | 4/3/2/2/2 | 2/2 | 0/2 | 2 / 未成稿 | 4/0 |

五维均分仅针对成功评分用例，不给未评分/无稿填零，也不删除它们在覆盖与编辑指标中的分母。

| 质量位置 | 有效用例 / 全部 | 五维均分 |
|---|---|---|
| first | 9/12 | 2.778/2.444/1.444/2.222/1.444 |
| final | 9/12 | 3.667/3.333/2/2.556/2.222 |

## 逐版本评分清单

| 用例 / 版本 | 轮 / stage | 可见性 | 评分 | 词法状态 / 疑点 | 语义状态 / 疑点 |
|---|---|---|---|---|---|
| [ai-pm-01 / v001](ai-pm-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [ai-pm-01 / v002](ai-pm-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | completed / 1 | completed_pending_claude / 1 |
| [ai-pm-01 / v003](ai-pm-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | completed / 1 | completed_pending_claude / 1 |
| [algorithm-01 / v001](algorithm-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [algorithm-01 / v002](algorithm-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 1 |
| [algorithm-01 / v003](algorithm-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 2 |
| [backend-01 / v001](backend-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [backend-01 / v002](backend-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 1 |
| [backend-01 / v003](backend-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 4 |
| [backend-01 / v004](backend-01/scores.json) | 5 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 5 |
| [career-switch-01 / v001](career-switch-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [career-switch-01 / v002](career-switch-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 1 |
| [data-01 / v001](data-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [design-01 / v001](design-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [design-01 / v002](design-01/scores.json) | 2 / COLLECTING | 仅内部 | no_draft | no_draft / 0 | not_run / 0 |
| [design-01 / v003](design-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 0 |
| [direction-01 / v001](direction-01/scores.json) | 1 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 1 |
| [direction-01 / v002](direction-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 2 |
| [direction-01 / v003](direction-01/scores.json) | 3 / EVALUATING | 用户可见 | completed | completed / 0 | completed_pending_claude / 3 |
| [frontend-01 / v001](frontend-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [import-01 / v001](import-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [minimal-01 / v001](minimal-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [minimal-01 / v002](minimal-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | completed / 1 | completed_pending_claude / 1 |
| [minimal-01 / v003](minimal-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | completed / 1 | completed_pending_claude / 5 |
| [minimal-01 / v004](minimal-01/scores.json) | 4 / COLLECTING | 用户可见 | completed | completed / 1 | completed_pending_claude / 5 |
| [ops-01 / v001](ops-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [ops-01 / v002](ops-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 1 |
| [pm-01 / v001](pm-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | no_draft / 0 | not_run / 0 |
| [pm-01 / v002](pm-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 1 |
| [pm-01 / v003](pm-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 2 |
| [pm-01 / v004](pm-01/scores.json) | 4 / COLLECTING | 用户可见 | completed | completed / 0 | completed_pending_claude / 2 |

## 失败与未知项

- [ai-pm-01](ai-pm-01/meta.json): no_completed_first_draft, edit_not_executed。编辑分类 {'no_diff': 2}。
- [algorithm-01](algorithm-01/meta.json): no_completed_first_draft, edit_not_executed。编辑分类 {'no_diff': 2}。
- [backend-01](backend-01/meta.json): no_completed_first_draft, edit_not_executed。编辑分类 {'no_diff': 1, 'not_followed': 1}。
- [career-switch-01](career-switch-01/meta.json): no_completed_first_draft, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [data-01](data-01/meta.json): no_visible_draft, no_completed_first_draft, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_draft': 2}。
- [design-01](design-01/meta.json): no_completed_first_draft, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [direction-01](direction-01/meta.json): first_draft_over_2_turns, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [frontend-01](frontend-01/meta.json): no_visible_draft, no_completed_first_draft, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_draft': 2}。
- [import-01](import-01/meta.json): no_visible_draft, no_completed_first_draft, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_draft': 2}。
- [minimal-01](minimal-01/meta.json): no_completed_first_draft, edit_not_executed。编辑分类 {'no_diff': 2}。
- [ops-01](ops-01/meta.json): no_completed_first_draft, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [pm-01](pm-01/meta.json): no_completed_first_draft, edit_not_executed。编辑分类 {'no_diff': 2}。

## 用量与费用

费用区间只覆盖记录到 token 且有费率的调用，不是账单；缺少价格或使用量不填零。

- graph: 已记录 token 估算 USD 0.070354–0.242775；有价格调用 149，区间记录内未定价调用 0，无费用区间用例 0。费率来源保存在 [aggregate.json](aggregate.json)。
- judge: 已记录 token 估算 USD 0.168190–0.365241；有价格调用 20，区间记录内未定价调用 0，无费用区间用例 3。费率来源保存在 [aggregate.json](aggregate.json)。

## 本次运行的已知限制

- direction-01 第2–3轮存在规则模拟器漏答：Agent 问本人负责部分，但关键词表未匹配“负责/小组”，尽管 truth[6] 有分工事实却回答无更多信息。保留本次原始记录；此例轮数与覆盖受模拟协议影响，不能直接归因于产品。后续修模拟器应新开 run。
- 39条语义疑点包含“课程”“对话中描述的经历”、项目名和独立技能词等被判 uncertain 的条目；5条词法疑点含“做过一个”这类泛指数词。44条疑点不是44条编造，必须结合原句逐项复核。
- 旧链路用 deepseek-flash；当前凭证只列出两个模型，deepseek-v4-pro 是唯一不同于主模型和结构化模型的可用评审候选。本次未比较其他服务商，也未证明评审模型绝对最强。
- 12个用例均为一次运行的合成草案，truth尚待Claude审定，没有留出集或真人体验结果；PR0指标不构成跨岗位能力证明。
- 20261008-pilot 仅为评测器开发小样，包含旧编辑指令和初版校验错误，未并入这里的分母、token或费用。

## Claude 复核入口

- [review-queue.json](review-queue.json)：75 项待审任务，包含 truth、每版人工复核、词法和语义疑点及评估未完成项。
- [aggregate.json](aggregate.json)：完整分母、unknown、编辑分类、逐版状态和使用量汇总。
- [manifest.json](manifest.json)：源码、模型与隔离配置。先审 truth，再阅读每例 transcript / versions / scores。
- AI 标注没有转成确认新增事实；不允许把 reviewed/passed 的模型状态充当 Claude 人工确认。PR1 未开始。
