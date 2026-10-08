# PR4 v4 公开合成用例事实与编辑预审

这是 **Codex 只读预审，不是 Claude 确认**。范围为 `runs/20261009-pr4-v4/`；事实判断仅依据截至该轮实际用户消息、`observed_facts`、引用事实及原始 `source_quote`，不使用隐藏 truth 为正文背书。`confirmed_new_facts` 仍为 `null`，不能写成确认零新增事实或验收通过。本次只写本报告，未修改源码或任何 run 文件，未自行调用模型。

源码候选为 `37be26e51208c6780a544e04effa88b5cfcefae2`。主跑从 02:04:14 至 02:23:12，随后根任务在冻结源码下补评唯一 error edit，02:24:07 结束；manifest 最终 `status=partial`、`backend_unchanged=true`。12 案、59 turn、58 版本；47 版本评分完成、11 no_draft，无最终逐版本评分 error。design 的 graph RuntimeError 使后续两次编辑未运行，故整体不能按成功完跑验收。

## 24 次编辑结果

以补评后的机器成绩为准：**17/24（70.83%）执行，2 no_diff、3 not_followed、2 not_run、0 最终 error**。这些是编辑执行评分，不代表逐条事实与所有限制已人工通过。

| Case | 第一次编辑 | 第二次编辑 | 必要说明 |
|---|---|---|---|
| ai-pm-01 | turn 3：no_diff | turn 4：executed | v003 一次 schema 重试后仍失败，保留 v002 正文。 |
| algorithm-01 | turn 4：executed | turn 5：executed | 两稿均有未披露“未做量化统计”，见下文。 |
| backend-01 | turn 4：executed | turn 5：executed（补评） | 首评连续引用校验失败；原失败保留在 previous_attempts。 |
| career-switch-01 | turn 5：executed | turn 6：executed | “未做准确率统计”在提取阶段已遗漏。 |
| data-01 | turn 4：no_diff | turn 5：executed | v004 一次 schema 重试后仍失败，保留 v003 正文。 |
| design-01 | not_run | not_run | turn 3 followup RuntimeError，仅 v001/v002；两条编辑仍计入24分母。 |
| direction-01 | turn 4：executed | turn 5：executed | v004 遗漏已入库“没测业务效果”，v005恢复。 |
| frontend-01 | turn 5：not_followed | turn 6：executed | 与 JD 直接相关的三类界面已披露但未入库/未写。 |
| import-01 | turn 4：executed | turn 5：not_followed | 后者只将“仅在”改为“仅用于”；两稿均漏报名效果统计限制。 |
| minimal-01 | turn 4：executed | turn 5：executed | 本轮未披露团队/API分工或未上线，不能套用 v3 的材料要求。 |
| ops-01 | turn 5：executed | turn 6：executed | 两稿遗漏已入库“未统计阅读量与转化”。 |
| pm-01 | turn 3：executed | turn 4：not_followed | 未保留已披露原型/未上线，另添“团队项目”。 |

证据为各 case 的 `turns.json`、`versions.json`、`scores.json`；最终总数与 [aggregate.json](../runs/20261009-pr4-v4/aggregate.json) 一致。Writer 共5版触发一次 schema retry：ops/v004、pm/v003恢复；ai-pm/v003、data/v004、frontend/v004仍回退。前两次失败占 edit no_diff；frontend/v004是 followup 轮，不重复占24条 edit 分母。失败字段分别为 bullet extra、bullet extra + item.summary、item.summary_fact_ids。

`design-01` 第3轮的4次模型调用均 recorded completed；只有 RuntimeError 类型，没有可定位的栈，不能归因为已观察到的供应方调用错误。具体异常需后续诊断。

## 新增事实疑点

独立模型共3条语义疑点（1 unsupported、2 truth_only），均仍待 Claude 复核。Codex依据实际披露的判断如下。

| 用例 / 版本 | 输出与已披露边界 | 诊断 |
|---|---|---|
| algorithm-01 / v004、v005 | 写成“定性观察，**未做量化统计**”。用户只说检查文件、查看错例、发现模糊/复杂背景易错，统一尺寸、重跑实验并记录变化；没有声明未做统计。 | v004所引 f_9f532b…、f_30cb5d…、f_c60621…均为查看/记录/观察；v005引用全部9条仍无该否定。Writer model_completed、Guard无回退。Judge分别标unsupported和truth_only；都没有本轮已披露证据。 |
| pm-01 / v004 | 新增“（**团队项目**）”；实际开场只说“我参加过…这个课程项目”。 | 已披露材料不能直接确证团队属性，Judge也标truth_only，edit判not_followed。只据实际材料列疑点，不借隐藏团队分工事实背书。 |
| backend-01 / v005 | “本地演示**通过**”，原话和事实为“本地演示过，没部署”。 | 低强度成功性强化，未直接认定编造；单列人工边界提醒。 |

algorithm/v004的“逐张查看”也被Judge标出。用户说“把预测错的图片挑出来看”，逐张逐一的强度不是原话；比“未做统计”争议更大，保留为人工核查，不把整条自动判决等同事实确认。

## 已披露限制遗漏：不能被3条语义疑点总数掩盖

- **direction/v004：写作保留缺口。** Active事实 `f_17848c114e814de0adf998030d417dcf` 的 text为“未测试业务效果。”、quote为“我没测业务效果”。Match plan 明写要保留，三条正文均遗漏，三个 bullet 也未引用此事实，Guard无回退；v005恢复。旧 `_ASSERTED_LIMIT` 对“没测”漏检，与引用复合事实的问题不同。
- **import/v004–v005：复合限制只保留部分。** `f_ca155bdd3dee4a43ac10b0b6dd076882` 的原 quote是“草图只在社团内部讨论，没有开发上线，也没统计报名效果。”；单条保留前两项，却遗漏统计限制。bullet已引用该事实ID，v005无Guard回退，因此需要校验“引用来源”与“逐项显示限制”的差异。
- **ops/v005–v006：已引用整段来源仍遗漏。** `f_784a98a41d134d1c80729d513eed96f0`为整段opening的action，明确含“我没有统计阅读量和转化”；v004原本已写该限制，后两版均引用来源却删除，Guard无回退。v005还把全流程塞进首条而保留第2/3条重复动作；v006完成去重但没恢复统计限制。
- **career-switch/v005–v006：上游提取遗漏。** 第4轮说“没有正式评测集或准确率统计”，只抽出“没有正式评测集”的事实，后续正文也只保留这一半。不能把它与已有完整限制却没显示混为同一个PR4根因。
- **pm/v003–v004：上游解析/提取退化。** turn1 decode_jd调用completed，但assistant称“未解析出明确岗位信息”，stage仍JD_INPUT；turn2又索要已经发送的JD，active facts为空。turn3仅抽4条事实，漏开场“没开发上线的原型”，两稿均无原型/未上线。它在before/observed中存在，因此edit Judge可以发现，但writer没有完整事实输入。

## 其他质量与评分边界

frontend开场就披露“补了加载中、没结果和请求失败的界面”，但v002至最终v006的active facts均无该动作，稿中也缺失；第5轮edit正确判not_followed。根任务在独立候选复现了一个可能机制：旧lexical把“没结果”界面标签当成工作状态否定，可能拒绝“空结果”同义改写；**v4未保存原始提取候选，不能断言实跑确由此路径导致**。本轮未披露键盘检查，不应要求输出v3中曾披露的检查动作。

career-switch本轮未复现v3的未披露原因“分类说明不清楚”或“有时→常”扩写；本轮“逐条人工检查”确在第3轮披露，可使用。工作经历栏仍含“现在想转AI产品”，是字段组织质量问题。minimal最终单条可回溯本轮项目名/工具/页面/表单材料；第4轮有原事实拼接重复，第5轮已去重。ops项目名已为“读书角”，未复现v3的“的”。

编辑评分仍有边界漏检：algorithm两次edit=true，第一条理由甚至将新增“未做量化统计”称为合理区分观察与量化；direction第4轮edit=true，理由把删掉“未测试业务效果”当作移除无关内容；ops第6轮edit=true但仍缺统计限制。因此17/24只可表述为机器判定的编辑执行率。

backend第5轮首评报 `JudgeSchemaError: ungrounded evidence quote`，原因是把3条before bullet拼作单条连续引用；根任务在冻结源码下只补评该error一次，新的证据按单条引用通过，机器executed由16变17。原score与model call保留在 `previous_attempts` / `previous_review_calls`；没有手改失败成绩，也没有重跑writer。仍保留上文“本地演示通过”的人工边界提醒。

确定性质量信号也需解释：frontend的“‘书架角’网页 Demo”被严格标题相等规则标为project_title_mismatch，但名字和Demo性质均来自opening，不等于造假；direction把整句求职方向放进objective确实不够像简历字段，但这句话是用户实际开场，`objective_unsupported`不能解读成新增求职事实。pm/v002的“对话中描述的经历”则确为generic标题退化。

v4编辑Judge采用独立job_context与observed_facts，不发送truth池；逐版本事实/coverage仍保持原双口径。故不重写v3成绩，也不能把v3/v4差值全归产品代码变化。本轮58版少于v3的70版，追问与披露内容不同；未跑pairwise比较。最终来源事实、安全确认均仍待Claude复核。
