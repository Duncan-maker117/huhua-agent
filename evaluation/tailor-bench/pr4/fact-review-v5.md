# PR4 v5 公开用例事实与编辑质量预审

这是 **Codex 预审，不是 Claude 确认**。已检查全部 12 个公开合成用例的 turns、versions、scores，并复核两项失败补评。依据仅为截至该轮已披露用户原文、observed_facts、active source_quote；隐藏 truth 不作为候选人事实的证据。未改业务、harness 或任何 run 文件，未自行调用外部模型。`confirmed_new_facts` 与 `safe` 仍为 null，不能报告“零新增事实”或验收通过。

数据根：`evaluation/tailor-bench/runs/20261009-pr4-v5/`。源码冻结 `ada326e95524942db32efbd3575d1213db4a8eb1`，manifest `backend_unchanged=true`。

## 完成状态与失败边界

- 主 run：2026-10-09 02:52:11–03:16:47（Asia/Shanghai）。12 例、70 个用户轮次、69 版本，其中 68 可见、1 internal-only。
- 初评：57 版完成评分、11 no_draft、1 版本评分错误；编辑 20/24 执行、1 error、1 no_diff、2 not_followed。
- 只针对 algorithm/v003 版本评分、pm/turn5 编辑评分各补评一次，03:18:23 完成。两项均由 `JudgeSchemaError: ungrounded evidence quote` 恢复，`previous_attempts` 各保留 1 条旧失败，未重写候选稿。
- 最终：58 版完成评分、11 no_draft；编辑 **21/24（87.5%）** 执行，仍有 1 no_diff、2 not_followed；没有待补评分错误。此完成状态只表示运行和评分结束。
- 25 个版本含主 writer 诊断（24 model_completed、1 model_fallback；包括 algorithm/v005 在 followup 阶段触发的写稿），7 次 schema 重试，6 次恢复、1 次最终回退。不要把 24 次编辑请求写成全部 writer 调用数。
- 模型标记 4 个 semantic suspicions、5 个 unverifiable units；后者全是 direction 五版本重复的求职意向原句，不是 5 项新增经历。**人工发现的“有时→常”不在这 4 个模型疑点内。**

## 优先交 Claude 复核的事实问题

### 1. career-switch/v006 把“有时”加强为“常”，Guard 和 Judge 都漏检

实际 turn3：`我发现报名条件和活动安排有时被混在一起，于是改写分类说明后重新尝试。`

active fact `f_1c8fffce1ef6451c949842550d2f2810` 也保存“有时被混在一起”。v005 仍为“有时”，v006 精简后变为：`发现报名条件与活动安排常被混在一起后改写分类说明重试`。

这是可直接比对的频率加强。v006 writer schema_retry_count=0，Guard 只追加限制；逐版本 factuality 把该单元判 supported，编辑 Judge 也判 executed=true。不能用 21/24 编辑执行或 review-queue 的 4 件疑点代替本项审查。

同一 v006 的“逐条人工检查”也比本轮用户“再人工检查”更具体；v4 曾披露逐条不构成 v5 本轮证据。ai-pm 的“逐条记录”相对用户“错误记录”存在较弱的类似具体化疑点，列为低优先级措辞复核，不直接计作确认新增事实。

来源：`career-switch-01/turns.json` turn3、`versions.json` v005/v006 的正文与 committed_fact_snapshot、`scores.json` v006 和 turn6 编辑。

### 2. import/v004–v005 有两个 Judge 未标记的新增细节疑点

用户只披露“写笔记标题查询接口”“SQLite 保存笔记标题和正文”。改稿增加 `接收关键词并返回匹配的笔记标题与正文`。关键词有空关键词请求可支持，但存储正文不自动证明接口会返回正文。

用户限制为 `没有性能测试或用户数据`，active `f_1c5243fb8e484647a05eaa70c581f7f7` 保留原句；稿件变为 `未做性能测试或用户数据统计`，把“没有用户数据”转换成“未做用户数据统计”的工作状态。Guard 后面又追加原限制，但没有撤回前面新增的否定工作断言。两版本 factuality 均未标疑点；仍需 Claude 根据原文裁定。

来源：`import-01/turns.json` turn2、`versions.json` v004/v005 知页索引 bullet1/bullet3 与上述 fact、对应 `scores.json`。

### 3. 模型的 4 项疑点也要独立裁定

| 位置 | 模型标记 | 已披露证据与预审判断 |
| --- | --- | --- |
| career-switch/v005 | unsupported：“作为后续答疑与活动说明的素材” | 用户说整理问题表，没有披露此用途。保留待确认。 |
| career-switch/v005 | unsupported：“验证大模型能否承担这一整理工作” | 用户说尝试 GPT 分类，未明确该验证目的；属于目的归纳边界，不能自动通过。 |
| design/v006 | truth_only：“本人负责流程梳理与交互原型” | 实际原话“我负责上述流程和交互原型”。“梳理”是否为允许的概括需判断，不能用隐藏 truth 背书，也不直接认定伪造经历。 |
| direction/v004 | truth_only：“明确分类汇总的统计标准” | 实际已说“SQL 汇总、图表和口径说明是我做的”。可能属于口径说明的正常概括；需基于这句已披露原文裁定，而非隐藏的取消订单情节。 |

## 上游漏抽取与完整性缺口

这些材料在真实用户轮次中存在，但没有完整进入本轮 active facts；Guard 无法仅靠已有 fact 引用完整弥补。不得通过把任意 raw_notes 自动提升为 writer 证据来修复。

| 用例 | 明确披露但遗漏的内容 | 可观察影响 |
| --- | --- | --- |
| frontend | turn2“我用 Vue 3 和 TypeScript 写书籍搜索列表” | 从 active_facts 到最终稿均无 Vue/TypeScript，skills 为空；虽已写出三类状态，核心技术栈丢失。 |
| career-switch | turn4“没有正式评测集或准确率统计”后半句 | active 只保留没有正式评测集；最终缺准确率统计限制。 |
| ops | turn2“报名和主持是别的同学做的，我没有统计阅读量和转化” | 整句没有 active fact，最终缺分工和统计边界。 |
| ops | turn3“根据反馈起草了后续活动的选题提纲” | active 只保留孤立的“提纲还没有用于下一场活动”，最终写成“反馈提纲”，后续选题这一岗位相关产出不清楚。 |
| pm | turn3“没有真实订单或线上转化数据” | active 与最终正文都未保留该限制。 |
| design | turn4观察并记录找不到进度入口、不理解必填项 | 抽取保留后续调整，未保存两类具体问题发现证据；最终只用“据观察”概括。 |

PM 的 JD 解析缺口也继续存在：turn1 assistant 明确返回“还没有解析出明确岗位信息”，后续一直为 `resume_strategy.mode=capability`、target_role 空、match_plan.requirements=[]。因此即使编辑 Judge 根据独立 job_context 判断方向符合，不能据此说系统成功完成了 JD 解析。原型/未开发上线本轮已保留。

以上均可在各用例 `turns.json` 对应轮次与最后一个 `versions.json` 的 active_facts/正文直接核对。PM 的“将问题整理成需求清单”虽然没有独立 active text，但 turn4 被保留 fact 的完整 source_quote 含该句，后续写回有已披露来源，不归入新增事实。

## 编辑失败、Guard 与表达质量

| 用例 | 两次编辑最终结果 | 主要观察 |
| --- | --- | --- |
| ai-pm | 2/2 executed | 未上线、未承担页面接口、未任组长均保留，但同义原话再次追加；v004 有 guard_repair_failed。 |
| algorithm | 2/2 executed | 未重现 v4 的无依据“未做量化统计”；本轮多披露了队友训练参数分工，不能把全部改善归功于代码。 |
| backend | 2/2 executed | 已有“未部署”又追加“没部署”；v004 全流程与输入校验表述重复。 |
| career-switch | 2/2 executed | 执行成功不能消除上述用途、频率疑点；仍有未上线/没做成上线产品重复。 |
| data | 2/2 executed | 未删原数据、未供真实商家的限制保留又重复追加；turn3/4重复相同回答，7轮仅6版本。 |
| design | 2/2 executed | 未重现 v4 turn3 RuntimeError；v005 Guard 回退堆原事实，v006 恢复流畅，事实概括仍待确认。 |
| direction | 2/2 executed | 未测业务效果已保留，又追加“我没测业务效果”。 |
| frontend | 2/2 executed | UI 加载/空结果/请求失败均保留；“未上线；网站没上线”重复。追加“我只负责…”可能补足真正的责任范围，不应统称误杀。 |
| import | 第1次 executed；第2次 not_followed | 原本已一条，最后新增小组筹备背景且未清重复，整体更长；与“精简”不符。 |
| minimal | 第1次 executed；第2次 not_followed | 最后仍两条，未满足合为一条；guard_repair_failed 后保留旧句/原事实，限制重复严重。 |
| ops | 第1次 executed；第2次 no_diff | schema 重试1次后仍 `match_plan.<extra>`/ValidationError，明确 preserved_existing_draft，仍3条。 |
| pm | 2/2 executed（第1次补评后） | 不再添加无依据“课程小组”；保留原型/未开发上线，仍有前述 JD 和数据限制遗漏。 |

Guard 共 28 条 fallback 记录：19 条 missing_item_status_limit、9 条 guard_repair_failed。19 条不是 19 次事实风险，也不能全部视为误杀；多例已写同义限制而再次追加可以直接确认。9 条 repair_failed 只有原候选 hash，没有原文，不能猜测每一条是否应当通过。minimal 把“我不知道具体做了多久”堆入简历，虽原文属实，仍是表达和取舍问题。

按本次模型评分，首个可见经历到最终稿的专业表达均分 3.083→2.917；岗位相关性 3.000→3.917、本人贡献 2.917→3.917。它是模型的描述性评分，不是人类验收或因果实验；与人工观察到的限制重复一致地提示：执行率提升并不代表简历表达同步改善。

## 评分器与首稿口径

- algorithm/v003 初评把换行的多个句子拼成连续 coverage 引用；pm/turn5 初评把两个独立 bullet 拼成连续 after_quote。连续引用校验拒绝是正确的，本次仅补评错误项，旧失败完整保留。
- frontend/v005 明明有“加载中、没结果、请求失败三类状态界面”，coverage 却把 r1“列表组件与完整交互状态”判 false；是评分疑点，未手改成绩。
- direction 的 5 个 unverifiable units 是同一求职意向字段直接存入“我想找数据分析实习，手里还没有具体 JD。”；用户确实说过这句，属于字段规范化/表达问题，不能累加成 5 项事实伪造。
- 12/12 在 turn2 有早期可见经历描述。11例为 v002；pm 为 v003，v002 是 internal-only。**全部首个可见经历都还没有 polished_bullets，主要是事实母版逐行罗列，不能将 12/12 解读成两轮内已经完成岗位取舍的 polished 成稿。**首次正式 writer 诊断出现在 turn4–6；algorithm 在 turn5 的 followup 触发，其余多数到显式编辑才写。

## 压缩覆盖边界与私有汇总引用

公开 69 版本均渲染为一页，12 最终稿 page_check 均一页；所有公开版本 `compression_retention_checks` 和 `compression_writer_diagnostics` 为空。**公开短稿未覆盖压缩流程**，因此本 run 不能独自证明新增 keep/merge/shorten 保留校验在 live 情境下有效；离线回归应与公开实测分列。

根任务另报告私有 v5 实际触发 merge accepted→shorten rejected，以及第二轮 merge rejected；旧证据保留，并诚实报告仍为两页。本预审不读取或复制私人正文，仅引其安全汇总：[私有 v5 审查](../runs-private/20261009-pr4-real-01-v5/review-v5.md)。该信息由根任务复核，不是本公开合成数据预审的独立证据。

本次可交付的是完整运行证据和待修问题清单。Claude 仍需独立确认模型的4项疑点，以及本报告额外列出的频率加强、接口返回字段、否定统计动作等疑点；不能只处理 review-queue 中已有4件就结束事实验收。
