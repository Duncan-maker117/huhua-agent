# Tailor PR4 · 逐版本评估

运行：2026-10-09T21:45:04.907065+08:00；源码快照 `851775a165eb85ba24e4e632c6cfd71a5be43138`。
写作模型 `deepseek-v4.1-flash`；评审模型 `deepseek-v4.1-flash`。
评审与写作同为 deepseek-v4.1-flash，质量分仅供参考，事实以确定性检查和 Claude 复核为准。

本报告状态：**incomplete**。1 个合成用例，6 个变化版本（可见 5，仅内部 1）。
合成 truth 仍待 Claude 审定；**本轮输出的确认新增经历事实仍为 null（未知）**，需 Claude 差异复核。模型评分不替代复核确认。

## 历史复核归属

[Claude 对 v1 的复核](../../claude-review-response.txt)确认：`20261008-baseline` 的新增经历事实为 0，另有 1 例未经支持的求职意向扩写。这个 0 只属于 v1；没有转移到本轮，也没有覆盖或重写 v1 的原始运行文件。

## 总体指标

| 指标 | 结果 | 解释 |
|---|---|---|
| coverage_of_disclosed · 要求覆盖 | 0/2 = 0.0% | 已评分观察下界；已知未覆盖 0，未知 2，N/A 0。 |
| coverage_of_disclosed · 证据事实覆盖 | 0/2 = 0.0% | 按该要求的证据事实计，不把出现任意一条证据称为覆盖全部事实；未知 2。 |
| coverage_of_truth · 要求覆盖 | 0/2 = 0.0% | 已评分观察下界；已知未覆盖 0，未知 2，N/A 0。 |
| coverage_of_truth · 证据事实覆盖 | 0/2 = 0.0% | 按该要求的证据事实计，不把出现任意一条证据称为覆盖全部事实；未知 2。 |
| 编辑执行 | 2/2 = 100.0% | 无 diff 0；错误 0；未运行 0；未评分 0；无稿 0；未遵循 0；不确定 0。 |
| 首稿 ≤ 2 个用户轮 | 1/1 | 首个用户可见且至少一段经历有 bullet/description 正文的版本；有首稿 1。JD 消息计入用户轮。 |
| 逐版本评分 | {'no_draft': 1, 'completed': 4, 'error': 1} | 任一缺失/错误/未运行仍为评估不完整，no_draft 不代表质量或安全通过。 |
| 词法 / 语义事实疑点 | 0 / 0 | 分开计数，可能重叠；所有疑点待复核。 |
| unverifiable_unit | 4 | uncertain 单独统计，不计新增事实疑点。标题、技能等质量检查也单列。 |
| 平均轮延迟 | 32.136 秒 | 基于 5 个实际记录轮。 |
| Graph / Judge / 模拟器 tokens | 94,919 / 28,141 / 0 | 三类分开统计，合计费用包含模拟器；HTTP 重试次数未知。 |
| Pairwise 新版胜率 | N/A | 本轮没有独立对手运行。 |
| Guard 回退 | 3 | 按逐版本证据统计；误杀需人工复核。 |
| Guard 回退版本占比 | 3/5 | 有任一 guard 回退的版本 / 有观测的版本；验收目标 ≤ 15%。 |
| negative_absence_printed | 0 | 简历正文印出「没有用户量/未上线/没有星数」等缺失型表述的单元数；验收目标 0。 |
| Writer 模型回退 | 0 | 主写作 0；压缩轮次 0；1 版未观测。模型回退不计为正常写作或 Guard 回退。 |
| 事实限制保护回退 | 0 | Guard reason=compression_preserved_status_limit 的逐版本观察数；不属于 Writer 模型回退。 |
| 页面实测 | 6/6 版合规 | 渲染缺失 0 版记未知。 |
| Writer flags | {'transferable': 11} | 仅统计可见条目元数据，不含 hidden backup。 |

正向要求分母共 2 条；1 条 gap 要求不进正向覆盖分母。disclosed 只计截至该版已有证据的要求；全部证据未披露的要求记 N/A。truth 衡量追问加写作。
没有任何可见断言正文的已运行用例覆盖记 0；有断言正文但评分缺失记 unknown。覆盖不限经历栏，不能替代首稿指标：已披露行动句即使被放入自评栏仍可形成事实覆盖，但不满足经历栏首稿定义；只有标题或技能词不能充当覆盖证据。比例在评分不齐时仅为已观测下界，不用于宣称验收通过。

## 首稿口径与五维质量

首稿轮数与质量统一取首个用户可见、且至少一段可见经历的 bullet 或 description 非空的版本。只有项目名称或 hidden backup 不计首稿。stage 口径已废弃，仅保留在 aggregate.json 的 diagnostic_stage_first_draft_* 中作诊断；COLLECTING 的可见正文按同一规则评分。
五维顺序：JD 相关性 / 个人贡献 / 结果产出 / 专业表达 / 取舍篇幅（1–5 分）。原话粘贴即使满足可见首稿条件，也不等于写作质量合格。

| 用例 | Graph / 评估 | 首稿五维 | 终稿五维 | 最终覆盖 disclosed / truth | 编辑执行 | 首稿轮 | 可见/仅内部版本 |
|---|---|---|---|---|---|---|---|
| [handson-01](handson-01/transcript.md) | completed / incomplete | 4/3/3/3/3 | — (error) | unknown (2/2) / unknown (2/2) | 2/2 | 2 | 5/1 |

质量均分仅针对成功评分的用例，不给缺失质量分填零；无稿/未评分不从覆盖和编辑分母消失。

| 位置 | 有效用例 / 全部 | 五维均分 |
|---|---|---|
| first | 1/1 | 4/3/3/3/3 |
| final | 0/1 | unknown/unknown/unknown/unknown/unknown |

## 产品发现（本轮实际结果）

**E1 编辑执行。** 本轮 2/2 条指令被评分为实质执行。无 diff 0、无稿 0、未遵循 0；未知或未完成不按成功计算。

**E2 标题与重复项目。** 1 个有稿例中，当前终稿已记录标题错误 0 例（无已记录项），重复项目 0 例（无已记录项）。来源为确定性质量检查；这些是质量缺陷，不自动当作新增经历事实。

**E3 无稿与整份导入。** 本轮无可见经历正文 0/1 例：无。

**E4 教育信息。** 有稿例中 0/1 的最终可见简历没有教育栏。已披露教育 0 例；其中确定性检查记录缺栏/缺字段 0 例（无已记录项）。没有询问到的隐藏教育不会被当作已披露漏写；导入例开场教育按已披露检查。

**E5 正文表达。** 有稿例中至少一条正文出现第一人称‘我’ 0 例，整条正文规范化后可在已披露用户文本中找到 1 例，重复正文单元 0 例、重复句 0 例。这是可复查的表达观察，不是自动质量分，也不说明其他文字一定经过了合格改写。

## 逐版本评分清单

| 用例 / 版本 | 轮 / stage | 可见性 | 评分 | 词法 / 语义疑点 | 不可判定单元 | 质量检查 |
|---|---|---|---|---|---|---|
| [handson-01 / v001](handson-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [handson-01 / v002](handson-01/scores.json) | 2 / EVALUATING | 用户可见 | completed | 0 / 0 | 1 | 1 |
| [handson-01 / v003](handson-01/scores.json) | 3 / EVALUATING | 用户可见 | completed | 0 / 0 | 1 | 1 |
| [handson-01 / v004](handson-01/scores.json) | 4 / EVALUATING | 用户可见 | completed | 0 / 0 | 1 | 1 |
| [handson-01 / v005](handson-01/scores.json) | 5 / EVALUATING | 仅内部 | completed | 0 / 0 | 1 | 1 |
| [handson-01 / v006](handson-01/scores.json) | 5 / EVALUATING | 用户可见 | error | 0 / 0 | 0 | 1 |

## 失败与未知项

- [handson-01](handson-01/meta.json): evaluation_incomplete, coverage_unknown。编辑分类 {'executed': 2}。

## 用量与费用

费用区间只覆盖记录到 token 且有费率的调用，不是账单；缺价/缺量不填零。all_models 包含 Graph、Judge 与模拟器。

- graph: 费用 unknown；有用量记录 1，缺失记录 0。
- judge: 费用 unknown；有用量记录 1，缺失记录 0。
- simulator: 费用 unknown；有用量记录 1，缺失记录 0。
- all_models: 费用 unknown；有用量记录 3，缺失记录 0。

## Claude 复核入口

- [review-queue.json](review-queue.json)：16 项待审任务；事实疑点、不可判定单元、质量检查分别标注。
- [aggregate.json](aggregate.json)：双覆盖分母、unknown、编辑分类、逐版状态、stage 诊断和使用量。
- [manifest.json](manifest.json)：源码、模型与隔离配置；逐例 transcript / versions / scores 都是相对链接。
- v1 复核结论只归属 v1；本轮须逐版本复核事实疑点，终稿不能代替中间版本验收。
