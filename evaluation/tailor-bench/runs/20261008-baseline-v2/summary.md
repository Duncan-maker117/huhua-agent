# Tailor PR0 · 旧链路逐版本基线

运行：2026-10-08T20:31:14.202493+08:00；源码快照 `58ee7a6af4dab6ef23bc6de87c50a54210d5b0fe`。
写作模型 `deepseek-flash`；评审模型 `deepseek-v4-pro`。

本报告状态：**evaluated_pending_claude**。12 个合成用例，32 个变化版本（可见 31，仅内部 1）。
合成 truth 已获 Claude 审定；**本轮输出的确认新增经历事实仍为 null（未知）**，需 Claude 差异复核。模型评分不替代复核确认。

## 历史复核归属

[Claude 对 v1 的复核](../../claude-review-response.txt)确认：`20261008-baseline` 的新增经历事实为 0，另有 1 例未经支持的求职意向扩写。这个 0 只属于 v1；没有转移到本轮，也没有覆盖或重写 v1 的原始运行文件。

## 总体指标

| 指标 | 结果 | 解释 |
|---|---|---|
| coverage_of_disclosed · 要求覆盖 | 10/14 = 71.4% | 已评分观察下界；已知未覆盖 4，未知 0，N/A 10。 |
| coverage_of_disclosed · 证据事实覆盖 | 12/18 = 66.7% | 按该要求的证据事实计，不把出现任意一条证据称为覆盖全部事实；未知 0。 |
| coverage_of_truth · 要求覆盖 | 11/24 = 45.8% | 已评分观察下界；已知未覆盖 13，未知 0，N/A 0。 |
| coverage_of_truth · 证据事实覆盖 | 13/46 = 28.3% | 按该要求的证据事实计，不把出现任意一条证据称为覆盖全部事实；未知 0。 |
| 编辑执行 | 0/24 = 0.0% | 无 diff 22；错误 0；未运行 0；未评分 0；无稿 0；未遵循 2；不确定 0。 |
| 首稿 ≤ 2 个用户轮 | 8/12 | 首个用户可见且至少一段经历有 bullet/description 正文的版本；有首稿 10。JD 消息计入用户轮。 |
| 逐版本评分 | {'no_draft': 12, 'completed': 20} | 任一缺失/错误/未运行仍为评估不完整，no_draft 不代表质量或安全通过。 |
| 词法 / 语义事实疑点 | 0 / 0 | 分开计数，可能重叠；所有疑点待复核。 |
| unverifiable_unit | 7 | uncertain 单独统计，不计新增事实疑点。标题、技能等质量检查也单列。 |
| 平均轮延迟 | 10.246 秒 | 基于 58 个实际记录轮。 |
| Graph / Judge / 模拟器 tokens | 456,248 / 205,244 / 3,825 | 三类分开统计，合计费用包含模拟器；HTTP 重试次数未知。 |
| Pairwise 新版胜率 | N/A | 旧链路基线没有新版对手。 |
| Guard 回退 / 误杀 | 未观测 | 旧链路没有新语义 guard，不能记为零。 |

正向要求分母共 24 条；11 条 gap 要求不进正向覆盖分母。disclosed 只计截至该版已有证据的要求；全部证据未披露的要求记 N/A。truth 衡量追问加写作。
没有任何可见断言正文的已运行用例覆盖记 0；有断言正文但评分缺失记 unknown。覆盖不限经历栏，不能替代首稿指标：已披露行动句即使被放入自评栏仍可形成事实覆盖，但不满足经历栏首稿定义；只有标题或技能词不能充当覆盖证据。比例在评分不齐时仅为已观测下界，不用于宣称验收通过。

## 首稿口径与五维质量

首稿轮数与质量统一取首个用户可见、且至少一段经历的 bullet 或 description 非空的版本。只有项目名称不计首稿。stage 口径已废弃，仅保留在 aggregate.json 的 diagnostic_stage_first_draft_* 中作诊断；COLLECTING 的可见正文按同一规则评分。
五维顺序：JD 相关性 / 个人贡献 / 结果产出 / 专业表达 / 取舍篇幅（1–5 分）。原话粘贴即使满足可见首稿条件，也不等于写作质量合格。

| 用例 | Graph / 评估 | 首稿五维 | 终稿五维 | 最终覆盖 disclosed / truth | 编辑执行 | 首稿轮 | 可见/仅内部版本 |
|---|---|---|---|---|---|---|---|
| [ai-pm-01](ai-pm-01/transcript.md) | completed / completed | 2/2/1/2/2 | 3/3/1/2/2 | 1/1 / 1/2 | 0/2 | 2 | 3/0 |
| [algorithm-01](algorithm-01/transcript.md) | completed / completed | 3/3/2/3/3 | 3/3/2/2/2 | 1/1 / 1/2 | 0/2 | 2 | 3/0 |
| [backend-01](backend-01/transcript.md) | completed / completed | 3/3/2/3/2 | 5/5/3/3/4 | 2/2 / 2/2 | 0/2 | 2 | 3/0 |
| [career-switch-01](career-switch-01/transcript.md) | completed / completed | 3/3/2/3/3 | 3/3/2/3/3 | 1/1 / 2/2 | 0/2 | 2 | 2/0 |
| [data-01](data-01/transcript.md) | completed / completed | — (no_visible_experience) | 2/3/1/3/2 | 1/1 / 1/2 | 0/2 | 无稿 | 2/0 |
| [design-01](design-01/transcript.md) | completed / completed | 2/3/2/3/2 | 2/3/2/3/2 | 1/2 / 1/2 | 0/2 | 3 | 2/1 |
| [direction-01](direction-01/transcript.md) | completed / completed | 4/3/1/3/3 | 3/4/1/1/2 | 1/1 / 1/2 | 0/2 | 2 | 4/0 |
| [frontend-01](frontend-01/transcript.md) | completed / completed | 2/1/1/2/1 | 2/1/1/2/1 | 0/1 / 0/2 | 0/2 | 3 | 2/0 |
| [import-01](import-01/transcript.md) | completed / completed | — (no_visible_experience) | 2/1/1/2/1 | 0/2 / 0/2 | 0/2 | 无稿 | 2/0 |
| [minimal-01](minimal-01/transcript.md) | completed / completed | 1/1/1/2/1 | 1/1/1/2/1 | N/A / 0/2 | 0/2 | 2 | 2/0 |
| [ops-01](ops-01/transcript.md) | completed / completed | 3/3/2/3/2 | 4/4/3/2/2 | 1/1 / 1/2 | 0/2 | 2 | 4/0 |
| [pm-01](pm-01/transcript.md) | completed / completed | 2/2/1/2/2 | 2/2/1/2/2 | 1/1 / 1/2 | 0/2 | 2 | 2/0 |

质量均分仅针对成功评分的用例，不给缺失质量分填零；无稿/未评分不从覆盖和编辑分母消失。

| 位置 | 有效用例 / 全部 | 五维均分 |
|---|---|---|
| first | 10/12 | 2.5/2.4/1.5/2.6/2.1 |
| final | 12/12 | 2.667/2.75/1.583/2.25/2 |

## 产品发现（本轮实际结果）

**E1 编辑执行。** 本轮 0/24 条指令被评分为实质执行。无 diff 22、无稿 0、未遵循 2；未知或未完成不按成功计算。

**E2 标题与重复项目。** 10 个有稿例中，当前终稿已记录标题错误 10 例（ai-pm-01, algorithm-01, backend-01, career-switch-01, design-01, direction-01, frontend-01, minimal-01, ops-01, pm-01），重复项目 3 例（algorithm-01, direction-01, ops-01）。来源为确定性质量检查；这些是质量缺陷，不自动当作新增经历事实。

**E3 无稿与整份导入。** 本轮无可见经历正文 2/12 例：data-01, import-01。
data-01 的已披露行动事实被放入 self_evaluation（自评栏），经历栏仍没有正文；终稿已有事实覆盖 1/2，但首稿仍为无稿。这是内容放错栏目，不是仅靠标题或技能词获得覆盖。
整份本人旧简历导入例 import-01 本轮仍未出现经历正文，不能视为‘完整资料直接成稿’已验证。
[只读导入诊断](../../import-intake-diagnosis-v2.json)显示：原开场未被现有解析器识别；保持事实不变、仅规范教育/项目标签后可解析出 2 个项目和 1 条教育。此前完整资料测试采用受支持标签且包含显式生成指令，不能推广成‘任意完整材料都直接成稿’。这定位了格式分支差异，未证明先发 JD 是唯一原因；业务修复留待 PR4。

**E4 教育信息。** 有稿例中 10/10 的最终可见简历没有教育栏。已披露教育 1 例；其中确定性检查记录缺栏/缺字段 1 例（import-01）。没有询问到的隐藏教育不会被当作已披露漏写；导入例开场教育按已披露检查。

**E5 正文表达。** 有稿例中至少一条正文出现第一人称‘我’ 10 例，整条正文规范化后可在已披露用户文本中找到 6 例，重复正文单元 2 例、重复句 2 例。这是可复查的表达观察，不是自动质量分，也不说明其他文字一定经过了合格改写。

## 逐版本评分清单

| 用例 / 版本 | 轮 / stage | 可见性 | 评分 | 词法 / 语义疑点 | 不可判定单元 | 质量检查 |
|---|---|---|---|---|---|---|
| [ai-pm-01 / v001](ai-pm-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [ai-pm-01 / v002](ai-pm-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 1 | 2 |
| [ai-pm-01 / v003](ai-pm-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 1 | 2 |
| [algorithm-01 / v001](algorithm-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [algorithm-01 / v002](algorithm-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [algorithm-01 / v003](algorithm-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 3 |
| [backend-01 / v001](backend-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [backend-01 / v002](backend-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [backend-01 / v003](backend-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [career-switch-01 / v001](career-switch-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [career-switch-01 / v002](career-switch-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [data-01 / v001](data-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [data-01 / v002](data-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 0 |
| [design-01 / v001](design-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [design-01 / v002](design-01/scores.json) | 2 / COLLECTING | 仅内部 | no_draft | 0 / 0 | 0 | 0 |
| [design-01 / v003](design-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [direction-01 / v001](direction-01/scores.json) | 1 / COLLECTING | 用户可见 | completed | 0 / 0 | 1 | 1 |
| [direction-01 / v002](direction-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 1 | 2 |
| [direction-01 / v003](direction-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 1 | 2 |
| [direction-01 / v004](direction-01/scores.json) | 4 / COLLECTING | 用户可见 | completed | 0 / 0 | 1 | 3 |
| [frontend-01 / v001](frontend-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [frontend-01 / v002](frontend-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [import-01 / v001](import-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [import-01 / v002](import-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [minimal-01 / v001](minimal-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [minimal-01 / v002](minimal-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [ops-01 / v001](ops-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [ops-01 / v002](ops-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [ops-01 / v003](ops-01/scores.json) | 3 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 1 |
| [ops-01 / v004](ops-01/scores.json) | 4 / COLLECTING | 用户可见 | completed | 0 / 0 | 0 | 2 |
| [pm-01 / v001](pm-01/scores.json) | 1 / COLLECTING | 用户可见 | no_draft | 0 / 0 | 0 | 0 |
| [pm-01 / v002](pm-01/scores.json) | 2 / COLLECTING | 用户可见 | completed | 0 / 0 | 1 | 2 |

## 失败与未知项

- [ai-pm-01](ai-pm-01/meta.json): edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [algorithm-01](algorithm-01/meta.json): edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [backend-01](backend-01/meta.json): edit_not_executed。编辑分类 {'no_diff': 2}。
- [career-switch-01](career-switch-01/meta.json): edit_not_executed。编辑分类 {'no_diff': 2}。
- [data-01](data-01/meta.json): no_visible_experience_body, no_first_draft, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [design-01](design-01/meta.json): first_draft_over_2_turns, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [direction-01](direction-01/meta.json): edit_not_executed, coverage_below_80_percent。编辑分类 {'not_followed': 1, 'no_diff': 1}。
- [frontend-01](frontend-01/meta.json): first_draft_over_2_turns, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [import-01](import-01/meta.json): no_visible_experience_body, no_first_draft, edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [minimal-01](minimal-01/meta.json): edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。
- [ops-01](ops-01/meta.json): edit_not_executed, coverage_below_80_percent。编辑分类 {'not_followed': 1, 'no_diff': 1}。
- [pm-01](pm-01/meta.json): edit_not_executed, coverage_below_80_percent。编辑分类 {'no_diff': 2}。

## 用量与费用

费用区间只覆盖记录到 token 且有费率的调用，不是账单；缺价/缺量不填零。all_models 包含 Graph、Judge 与模拟器。

- graph: 已记录 token 估算 USD 0.068810–0.238543；有价格调用 150，区间内未定价调用 0，无费用区间记录 0。来源见 [aggregate.json](aggregate.json)。
- judge: 已记录 token 估算 USD 0.270347–0.629348；有价格调用 40，区间内未定价调用 5，无费用区间记录 0。来源见 [aggregate.json](aggregate.json)。
- simulator: 已记录 token 估算 USD 0.000054–0.001213；有价格调用 10，区间内未定价调用 0，无费用区间记录 2。来源见 [aggregate.json](aggregate.json)。
- all_models: 已记录 token 估算 USD 0.339211–0.869104；有价格调用 200，区间内未定价调用 5，无费用区间记录 2。来源见 [aggregate.json](aggregate.json)。

## 本次运行的已知限制

- v2业务源码与a742100及v1相同；相对v1的结果变化包含模拟器、评测口径修订和模型采样差异，不代表产品改版收益或退步。
- 首轮评分保留了连接/引用结构失败；澄清完整事实覆盖后全部20个非空版本统一重评，最终judge代码哈希一致。先前尝试与45次评审调用均保留，详情见verification.json与逐例scores/meta。
- 事实覆盖仍是模型语义判断，复合truth的完整覆盖尺度需Claude抽检；例如career-switch-01的人工检查表述，见../../checker-v2-review.md。
- 评审和被测模型来自同一服务商；新输出尚未获得Claude差异复核，自动疑点为0不等于确认新增经历事实为0。
- import-01 T6未声明没有排查记录；模拟器不会编造该否定，只能返回已有本地手测及没有性能测试/用户数据事实。
- 两条原问题的selector真实预检调用独立于正式基线计量；正式基线包含150次图调用、10次模拟器调用和全部45次评分调用，SDK内部重试与未报告token未知。

## Claude 复核入口

- [review-queue.json](review-queue.json)：56 项待审任务；事实疑点、不可判定单元、质量检查分别标注。
- [aggregate.json](aggregate.json)：双覆盖分母、unknown、编辑分类、逐版状态、stage 诊断和使用量。
- [manifest.json](manifest.json)：源码、模型与隔离配置；逐例 transcript / versions / scores 都是相对链接。
- v1 复核结论只归属 v1，本轮待差异复核。PR1 进度另见项目 mmr，不属于本次旧链路基线。
