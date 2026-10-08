# Tailor PR4 · 逐版本评估

运行：2026-10-09T02:52:11.791368+08:00；源码快照 `ada326e95524942db32efbd3575d1213db4a8eb1`。
写作模型 `deepseek-flash`；评审模型 `deepseek-v4-pro`。

本报告状态：**evaluated_pending_claude**。12 个合成用例，69 个变化版本（可见 68，仅内部 1）。
合成 truth 已获 Claude 审定；**本轮输出的确认新增经历事实仍为 null（未知）**，需 Claude 差异复核。模型评分不替代复核确认。

## 历史复核归属

[Claude 对 v1 的复核](../../claude-review-response.txt)确认：`20261008-baseline` 的新增经历事实为 0，另有 1 例未经支持的求职意向扩写。这个 0 只属于 v1；没有转移到本轮，也没有覆盖或重写 v1 的原始运行文件。

## 总体指标

| 指标 | 结果 | 解释 |
|---|---|---|
| coverage_of_disclosed · 要求覆盖 | 17/20 = 85.0% | 已评分观察下界；已知未覆盖 3，未知 0，N/A 4。 |
| coverage_of_disclosed · 证据事实覆盖 | 21/28 = 75.0% | 按该要求的证据事实计，不把出现任意一条证据称为覆盖全部事实；未知 0。 |
| coverage_of_truth · 要求覆盖 | 19/24 = 79.2% | 已评分观察下界；已知未覆盖 5，未知 0，N/A 0。 |
| coverage_of_truth · 证据事实覆盖 | 23/46 = 50.0% | 按该要求的证据事实计，不把出现任意一条证据称为覆盖全部事实；未知 0。 |
| 编辑执行 | 21/24 = 87.5% | 无 diff 1；错误 0；未运行 0；未评分 0；无稿 0；未遵循 2；不确定 0。 |
| 首稿 ≤ 2 个用户轮 | 12/12 | 首个用户可见且至少一段经历有 bullet/description 正文的版本；有首稿 12。JD 消息计入用户轮。 |
| 逐版本评分 | {'no_draft': 11, 'completed': 58} | 任一缺失/错误/未运行仍为评估不完整，no_draft 不代表质量或安全通过。 |
| 词法 / 语义事实疑点 | 0 / 4 | 分开计数，可能重叠；所有疑点待复核。 |
| unverifiable_unit | 5 | uncertain 单独统计，不计新增事实疑点。标题、技能等质量检查也单列。 |
| 平均轮延迟 | 12.122 秒 | 基于 70 个实际记录轮。 |
| Graph / Judge / 模拟器 tokens | 865,263 / 538,613 / 8,140 | 三类分开统计，合计费用包含模拟器；HTTP 重试次数未知。 |
| Pairwise 新版胜率 | N/A | 本轮没有独立对手运行。 |
| Guard 回退 | 28 | 按逐版本证据统计；误杀需人工复核。 |
| Writer 模型回退 | 1 | 主写作 1；压缩轮次 0；44 版未观测。模型回退不计为正常写作或 Guard 回退。 |
| 事实限制保护回退 | 0 | Guard reason=compression_preserved_status_limit 的逐版本观察数；不属于 Writer 模型回退。 |
| 页面实测 | 69/69 版合规 | 渲染缺失 0 版记未知。 |
| Writer flags | {'transferable': 17} | 仅统计可见条目元数据，不含 hidden backup。 |

正向要求分母共 24 条；11 条 gap 要求不进正向覆盖分母。disclosed 只计截至该版已有证据的要求；全部证据未披露的要求记 N/A。truth 衡量追问加写作。
没有任何可见断言正文的已运行用例覆盖记 0；有断言正文但评分缺失记 unknown。覆盖不限经历栏，不能替代首稿指标：已披露行动句即使被放入自评栏仍可形成事实覆盖，但不满足经历栏首稿定义；只有标题或技能词不能充当覆盖证据。比例在评分不齐时仅为已观测下界，不用于宣称验收通过。

## 首稿口径与五维质量

首稿轮数与质量统一取首个用户可见、且至少一段可见经历的 bullet 或 description 非空的版本。只有项目名称或 hidden backup 不计首稿。stage 口径已废弃，仅保留在 aggregate.json 的 diagnostic_stage_first_draft_* 中作诊断；COLLECTING 的可见正文按同一规则评分。
五维顺序：JD 相关性 / 个人贡献 / 结果产出 / 专业表达 / 取舍篇幅（1–5 分）。原话粘贴即使满足可见首稿条件，也不等于写作质量合格。

| 用例 | Graph / 评估 | 首稿五维 | 终稿五维 | 最终覆盖 disclosed / truth | 编辑执行 | 首稿轮 | 可见/仅内部版本 |
|---|---|---|---|---|---|---|---|
| [ai-pm-01](ai-pm-01/transcript.md) | completed / completed | 3/4/2/3/3 | 2/5/3/3/3 | 1/1 / 1/2 | 2/2 | 2 | 5/0 |
| [algorithm-01](algorithm-01/transcript.md) | completed / completed | 3/3/2/3/2 | 4/4/3/4/4 | 1/1 / 1/2 | 2/2 | 2 | 7/0 |
| [backend-01](backend-01/transcript.md) | completed / completed | 3/4/3/4/3 | 4/4/2/3/4 | 2/2 / 2/2 | 2/2 | 2 | 5/0 |
| [career-switch-01](career-switch-01/transcript.md) | completed / completed | 2/3/2/2/2 | 3/3/2/2/2 | 2/2 / 2/2 | 2/2 | 2 | 6/0 |
| [data-01](data-01/transcript.md) | completed / completed | 2/2/1/3/2 | 4/4/1/3/4 | 2/2 / 2/2 | 2/2 | 2 | 6/0 |
| [design-01](design-01/transcript.md) | completed / completed | 3/2/2/3/3 | 4/4/3/4/5 | 0/2 / 2/2 | 2/2 | 2 | 6/0 |
| [direction-01](direction-01/transcript.md) | completed / completed | 4/2/2/3/3 | 4/4/2/3/4 | 1/1 / 1/2 | 2/2 | 2 | 5/0 |
| [frontend-01](frontend-01/transcript.md) | completed / completed | 2/2/2/3/2 | 4/3/2/2/2 | 1/2 / 1/2 | 2/2 | 2 | 5/0 |
| [import-01](import-01/transcript.md) | completed / completed | 5/5/3/4/5 | 5/5/4/3/5 | 2/2 / 2/2 | 1/2 | 2 | 5/0 |
| [minimal-01](minimal-01/transcript.md) | completed / completed | 2/1/1/2/1 | 4/3/1/1/2 | 2/2 / 2/2 | 1/2 | 2 | 7/0 |
| [ops-01](ops-01/transcript.md) | completed / completed | 4/4/3/4/5 | 4/4/2/2/3 | 1/1 / 1/2 | 1/2 | 2 | 5/0 |
| [pm-01](pm-01/transcript.md) | completed / completed | 3/3/2/3/2 | 5/4/3/5/4 | 2/2 / 2/2 | 2/2 | 2 | 6/1 |

质量均分仅针对成功评分的用例，不给缺失质量分填零；无稿/未评分不从覆盖和编辑分母消失。

| 位置 | 有效用例 / 全部 | 五维均分 |
|---|---|---|
| first | 12/12 | 3/2.917/2.083/3.083/2.75 |
| final | 12/12 | 3.917/3.917/2.333/2.917/3.5 |

## 产品发现（本轮实际结果）

**E1 编辑执行。** 本轮 21/24 条指令被评分为实质执行。无 diff 1、无稿 0、未遵循 2；未知或未完成不按成功计算。

**E2 标题与重复项目。** 12 个有稿例中，当前终稿已记录标题错误 1 例（ops-01），重复项目 0 例（无已记录项）。来源为确定性质量检查；这些是质量缺陷，不自动当作新增经历事实。

**E3 无稿与整份导入。** 本轮无可见经历正文 0/12 例：无。
整份本人旧简历导入例 import-01 本轮在第 2 轮出现经历正文；v1 无正文是历史结果，不套用到本轮。
[只读导入诊断](../../import-intake-diagnosis-v2.json)显示：原开场未被现有解析器识别；保持事实不变、仅规范教育/项目标签后可解析出 2 个项目和 1 条教育。此前完整资料测试采用受支持标签且包含显式生成指令，不能推广成‘任意完整材料都直接成稿’。这定位了格式分支差异，未证明先发 JD 是唯一原因；业务修复留待 PR4。

**E4 教育信息。** 有稿例中 11/12 的最终可见简历没有教育栏。已披露教育 1 例；其中确定性检查记录缺栏/缺字段 0 例（无已记录项）。没有询问到的隐藏教育不会被当作已披露漏写；导入例开场教育按已披露检查。

**E5 正文表达。** 有稿例中至少一条正文出现第一人称‘我’ 5 例，整条正文规范化后可在已披露用户文本中找到 1 例，重复正文单元 0 例、重复句 0 例。这是可复查的表达观察，不是自动质量分，也不说明其他文字一定经过了合格改写。

## 逐版本评分清单

| 用例 / 版本 | 轮 / stage | 可见性 | 评分 | 词法 / 语义疑点 | 不可判定单元 | 质量检查 |
|---|---|---|---|---|---|---|
| [ai-pm-01 / v001](ai-pm-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [ai-pm-01 / v002](ai-pm-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [ai-pm-01 / v003](ai-pm-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [ai-pm-01 / v004](ai-pm-01/scores.json) | 4 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [ai-pm-01 / v005](ai-pm-01/scores.json) | 5 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [algorithm-01 / v001](algorithm-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [algorithm-01 / v002](algorithm-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [algorithm-01 / v003](algorithm-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [algorithm-01 / v004](algorithm-01/scores.json) | 4 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [algorithm-01 / v005](algorithm-01/scores.json) | 5 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [algorithm-01 / v006](algorithm-01/scores.json) | 6 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [algorithm-01 / v007](algorithm-01/scores.json) | 7 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [backend-01 / v001](backend-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [backend-01 / v002](backend-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [backend-01 / v003](backend-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [backend-01 / v004](backend-01/scores.json) | 4 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [backend-01 / v005](backend-01/scores.json) | 5 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [career-switch-01 / v001](career-switch-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [career-switch-01 / v002](career-switch-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [career-switch-01 / v003](career-switch-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [career-switch-01 / v004](career-switch-01/scores.json) | 4 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [career-switch-01 / v005](career-switch-01/scores.json) | 5 / EVALUATING | 用户可见 | completed | 0 / 2 | 0 | 0 |
| [career-switch-01 / v006](career-switch-01/scores.json) | 6 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [data-01 / v001](data-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [data-01 / v002](data-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [data-01 / v003](data-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [data-01 / v004](data-01/scores.json) | 5 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [data-01 / v005](data-01/scores.json) | 6 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [data-01 / v006](data-01/scores.json) | 7 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [design-01 / v001](design-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [design-01 / v002](design-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [design-01 / v003](design-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [design-01 / v004](design-01/scores.json) | 4 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [design-01 / v005](design-01/scores.json) | 5 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [design-01 / v006](design-01/scores.json) | 6 / EVALUATING | 用户可见 | completed | 0 / 1 | 0 | 0 |
| [direction-01 / v001](direction-01/scores.json) | 1 / COLLECTING | 用户可见 | completed | 0 / 0 | 1 | 1 |
| [direction-01 / v002](direction-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 1 | 1 |
| [direction-01 / v003](direction-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 1 | 1 |
| [direction-01 / v004](direction-01/scores.json) | 4 / EVALUATING | 用户可见 | completed | 0 / 1 | 1 | 1 |
| [direction-01 / v005](direction-01/scores.json) | 5 / EVALUATING | 用户可见 | completed | 0 / 0 | 1 | 1 |
| [frontend-01 / v001](frontend-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [frontend-01 / v002](frontend-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [frontend-01 / v003](frontend-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [frontend-01 / v004](frontend-01/scores.json) | 4 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [frontend-01 / v005](frontend-01/scores.json) | 5 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [import-01 / v001](import-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [import-01 / v002](import-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [import-01 / v003](import-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [import-01 / v004](import-01/scores.json) | 5 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [import-01 / v005](import-01/scores.json) | 6 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [minimal-01 / v001](minimal-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [minimal-01 / v002](minimal-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [minimal-01 / v003](minimal-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [minimal-01 / v004](minimal-01/scores.json) | 4 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [minimal-01 / v005](minimal-01/scores.json) | 5 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [minimal-01 / v006](minimal-01/scores.json) | 6 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [minimal-01 / v007](minimal-01/scores.json) | 7 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [ops-01 / v001](ops-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [ops-01 / v002](ops-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [ops-01 / v003](ops-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [ops-01 / v004](ops-01/scores.json) | 4 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [ops-01 / v005](ops-01/scores.json) | 5 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [pm-01 / v001](pm-01/scores.json) | 1 / JD_INPUT | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [pm-01 / v002](pm-01/scores.json) | 2 / COLLECTING | 仅内部 | completed | 0 / 0 | 0 | 0 |
| [pm-01 / v003](pm-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [pm-01 / v004](pm-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [pm-01 / v005](pm-01/scores.json) | 4 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [pm-01 / v006](pm-01/scores.json) | 5 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [pm-01 / v007](pm-01/scores.json) | 6 / EVALUATING | 用户可见 | completed | 0 / 0 | 0 | 0 |

## 失败与未知项

- [ai-pm-01](ai-pm-01/meta.json): coverage_below_80_percent。编辑分类 {'executed': 2}。
- [algorithm-01](algorithm-01/meta.json): coverage_below_80_percent。编辑分类 {'executed': 2}。
- [direction-01](direction-01/meta.json): coverage_below_80_percent。编辑分类 {'executed': 2}。
- [frontend-01](frontend-01/meta.json): coverage_below_80_percent。编辑分类 {'executed': 2}。
- [import-01](import-01/meta.json): edit_not_executed。编辑分类 {'executed': 1, 'not_followed': 1}。
- [minimal-01](minimal-01/meta.json): edit_not_executed。编辑分类 {'executed': 1, 'not_followed': 1}。
- [ops-01](ops-01/meta.json): edit_not_executed, coverage_below_80_percent。编辑分类 {'executed': 1, 'no_diff': 1}。

## 用量与费用

费用区间只覆盖记录到 token 且有费率的调用，不是账单；缺价/缺量不填零。all_models 包含 Graph、Judge 与模拟器。

- graph: 已记录 token 估算 USD 0.115557–0.429871；有价格调用 219，区间内未定价调用 0，无费用区间记录 0。来源见 [aggregate.json](aggregate.json)。
- judge: 已记录 token 估算 USD 0.788159–1.757678；有价格调用 83，区间内未定价调用 0，无费用区间记录 0。来源见 [aggregate.json](aggregate.json)。
- simulator: 已记录 token 估算 USD 0.000129–0.002598；有价格调用 22，区间内未定价调用 0，无费用区间记录 0。来源见 [aggregate.json](aggregate.json)。
- all_models: 已记录 token 估算 USD 0.903845–2.190147；有价格调用 324，区间内未定价调用 0，无费用区间记录 0。来源见 [aggregate.json](aggregate.json)。

## Claude 复核入口

- [review-queue.json](review-queue.json)：76 项待审任务；事实疑点、不可判定单元、质量检查分别标注。
- [aggregate.json](aggregate.json)：双覆盖分母、unknown、编辑分类、逐版状态、stage 诊断和使用量。
- [manifest.json](manifest.json)：源码、模型与隔离配置；逐例 transcript / versions / scores 都是相对链接。
- v1 复核结论只归属 v1；本轮须逐版本复核事实疑点，终稿不能代替中间版本验收。
