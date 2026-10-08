# PR4 v4 公开运行机制复核（已完成）

Run 于 2026-10-09T02:24:07.101941+08:00 结束，manifest status=partial、backend_unchanged=true，12/12 用例的 meta 已落盘。复核采用落盘后的最终结果（包含父任务已经完成并保留 previous_attempts 的 backend T5 judge 重评）。代码基线 37be26e51208c6780a544e04effa88b5cfcefae2。

关注 writer/schema/repair/压缩/页数绑定；新增事实语义裁定由事实复核 agent 负责，私有 real-01 不在本报告范围。未修改 MAIN、评分器、run 或旧产物，未新增模型请求。

## 当前量化诊断

- Writer 诊断：model_completed 21，model_fallback 3；有 schema retry 的轮次 5。无诊断的 intake 轮不推定为 writer 成功。
- Guard fallback 记录 7 条：{'guard_repair_failed': 6, 'missing_item_status_limit': 1}。记录不等于独立事实错误数。
- Page-check 24 个版本，hash 不匹配 0；benchmark 实际 render 58/58 版，超页 0。
- 记录到 compression_writer_diagnostics 0 次：公开样例均很短，不能据此声称长材料压缩通过。
- Graph turn error：[('design-01', 3, 'RuntimeError')]。
- 计划编辑完成率为 17/24（70.8%）：5 条未执行，design 另有 2 条因 graph error 未运行。实际执行轮诊断为 17/22 个进入评分的编辑通过，不作为计划完成率。22 个最终编辑评分均完成，backend T5 原 JudgeSchemaError 留在 previous_attempts。

| 用例 | Case 落盘 | 轮数 | writer 完成 | writer 回退 | 编辑评分 |
|---|---|---:|---:|---:|---|
| ai-pm-01 | 完成 | 4 | 1 | 1 | T3:未执行,T4:执行 |
| algorithm-01 | 完成 | 5 | 2 | 0 | T4:执行,T5:执行 |
| backend-01 | 完成 | 5 | 2 | 0 | T4:执行,T5:执行 |
| career-switch-01 | 完成 | 6 | 2 | 0 | T5:执行,T6:执行 |
| data-01 | 完成 | 5 | 1 | 1 | T4:未执行,T5:执行 |
| design-01 | graph_error | 3 | 0 | 0 | 未评分/未运行 |
| direction-01 | 完成 | 5 | 2 | 0 | T4:执行,T5:执行 |
| frontend-01 | 完成 | 6 | 2 | 1 | T5:未执行,T6:执行 |
| import-01 | 完成 | 5 | 2 | 0 | T4:执行,T5:未执行 |
| minimal-01 | 完成 | 5 | 2 | 0 | T4:执行,T5:执行 |
| ops-01 | 完成 | 6 | 3 | 0 | T5:执行,T6:执行 |
| pm-01 | 完成 | 4 | 2 | 0 | T3:执行,T4:未执行 |

## 已确认的问题与正常边界

1. **Schema 恢复仍有失败。** ai-pm T3、data T4、frontend T4：一重试后仍为 extra_forbidden；data 的首错为 object_missing，重试后仍有 item.summary 与 bullet.<extra>。三次都进入 preserved_existing_draft，前后可见 resume_data 逐字相同，历史版本数组没有新增假版本。ai-pm/data 对应编辑被评分为 no_diff；frontend 发生在事实不足控制回复的 followup，而非其两个显式 edit。旧稿保护工作正常，写作恢复不足仍降低编辑完成率。
2. **Design T3 原异常目前不可定位。** 四次逻辑模型调用均 completed，外层 RuntimeError 后未运行两条编辑；现有日志只有包装类名，不能断言是 provider、schema 或持久化问题。单独安全异常链候选可为未来重现提供 type + repo file/function/line，不回填本 run。
3. **安全 fallback 仍降低表达质量。** backend T4 的 b2、frontend T5 的 b1/b2、minimal T4 的 b1、import T4 的 b1/b2 都有 guard_repair_failed。最终 fallback 将引用事实逐条串接，出现与前面 bullet 重复的动作/工具，或同一条中重复原句片段。这与 writer 的重复生成不是同一已证实因果；当前记录未保留 repair 请求/输出全文，无法断言每个二次拒绝是否合理。
4. **Frontend 的关键工作遗漏发生在事实入库阶段。** Opening 已披露加载中、没结果、请求失败界面；从 v002 节点/SQL active facts 起均不含此工作，后续未补回。T5 编辑未突出此项被 Judge 判未执行，不能把它归因为新 repair 上下文丢失。
5. **V3 对比须注意披露与评分输入不同。** v3 全套 26 个 writer 诊断：25 完成/1 回退；6 次结构恢复，其中 5 次成功；26 个 page-check hash 均匹配。v4 有 5 次结构恢复，2 次成功、3 次失败，但问题出现在不同用例/轮次。模拟追问与披露不同，minimal v4 并未披露 v3 的队友接口分工，frontend v4 没有问到 v3 的键盘测试，不能把终稿中未出现这些信息直接记作 v4 压缩丢失，也不能以更少信息证明保留能力提高。v4 编辑评分只看已经披露的材料，其与 v3 评分输入有差异，不把执行率差值直接解释成代码因果。
6. **Import T5 没有完成有效压缩。** 已有一条描述基本照搬，只有“草图仅在”改为“草图仅用于”。这是完成 writer 调用但只产生微小措辞变化，区别于 schema 回退；没有新诊断证据支持扩写更多修复机制。
7. **PM T4 遗漏状态有上游证据，见下节。** v003 raw_notes 含明确原型限制，active_facts 却不含；v004 的写作与限制保留服务仅靠 active facts 无法补回这段状态。不能仅凭 T4 的精简指令把它定为此次压缩新丢失。

## PM：JD 解码失败与本人资料未进入可写事实的有界定位

观察：T1 请求明确 decode_jd，唯一逻辑模型请求 completed，固定回复“这段材料还没有解析出明确岗位信息”，stage 仍为 JD_INPUT。T2 的普通本人叙述包含项目、询问同学、绘制流程和“是个没开发上线的原型”；助手口头说“记下了”，仍为 JD_INPUT，v002 节点与 SQL 的 active facts 为空。到 T3 历史恢复后，v003 raw_notes 保留原型状态，但 active_facts 只包含参与、目标、询问、绘制四条。

源码能支持的最小根因：

- `backend/app/agents/decoder_chain.py:201–228` 将 JSON 解析失败转为空 JdInfo，`:115–130` 将结构/role_profile 验证异常也转成空 JdInfo，没有返回安全的失败分类。`:150–168` 还会先按任意位置首个 `---` 截断；离线合成输入证明 JSON 字符串内部的分隔符也会丢岗位信息。`resume_graph.py:1149–1160` 把这些空值与真正“未提取出岗位”统一成观察到的固定回复。没有该次原始响应，不能断言实际发生了 JSON、分隔符、结构异常中的哪一种，也不能排除模型本身返回空字段。
- `resume_graph.py:1195–1201` 只让已有简历格式/明确生成请求绕过 JD_INPUT 进入收集。普通本人叙述即使被 triage 识别为 WRAP_EXPERIENCE，JD_INPUT 后续也没有接收该动作的收集分支，最终 `:1297–1302` 只返回聊天消息。这里没有事实更新，因此“记下了”不能证明保存。离线模拟强制 WRAP_EXPERIENCE，得到仅 messages、无 collected_info，验证了确定的控制流缺口。
- `resume_graph.py:727–755` 后来可重放候选人历史，但 `_keep_unextracted_experience:650–656` 只要发现该消息有任意新 chat fact 就停止原文兜底，不检查未覆盖片段。它是完全失败兜底，无法补齐“已有四条事实、原型只在 raw_notes”的部分提取缺口。这解释现有机制的能力边界，并不证明该次提取为何遗漏状态。

最小可验证改进建议（仅建议，未动 MAIN；不扩 PR5 追问设计）：

1. 解码保留 `json_parse_failed` / `schema_invalid` / `empty_result` 等安全诊断，只记录固定分类与安全 schema 路径，不记录响应全文。先定位后调整解析；如修分隔，优先完整 JSON 边界，再消费其后的独立分隔行。保留失败时旧岗位信息，不把结构失败描述成用户材料缺少岗位。
2. JD_INPUT 若收到明确本人经历，复用收集/持久化流程，在返回“已记录”前完成事实更新；不能仅因为“当前无可用 JD”而跳过保存。仍保留 `_candidate_source_allowed` 的 JD/参考/他人材料排除边界。可以只处理 WRAP_EXPERIENCE + 非空本人片段，不用重写全路由。
3. 对“原始已归属 item 的 raw_notes 有状态限制，但 active facts 缺失”的覆盖缺口增加明确检查和定向恢复，避免把所有 raw_notes 无条件复制为 fact。验收应覆盖否定、计划和对象归属，不能只用关键词兜底。该建议涉及提取边界，需独立补丁而非 writer 加字。

离线回归入口：mock decoder 返回语法坏 JSON / 类型错误，验证诊断区分；mock triage=WRAP_EXPERIENCE、材料为一段非简历格式的本人叙述，断言当轮写入 source_quote/raw_notes 后才能确认保存；mock 部分提取只给 action、raw_notes 保留否定状态，断言状态恢复同 item 且拒绝 JD/参考材料。此次仅运行无网络探针，7 个观测条件均符合源码，包括现有缺陷的复现；没有调用外部模型，也没有把合成异常等同于这次实际模型响应。

## 已准备但未合入的独立候选

- `/tmp/huhua-pr4-schema-structure-v5/`：仅增强现有单次 schema retry 的安全层级结构提示，20/20 离线通过。没有增加次数、延时、放松 extra=forbid。
- `/tmp/huhua-pr4-harness-errors-v5/`：仅给失败 turn 添加安全类型/代码位置链，40/40 离线通过。不能恢复既往已丢失的异常。

## 证据入口

当前 run：`evaluation/tailor-bench/runs/20261009-pr4-v4/`；对照：`evaluation/tailor-bench/runs/20261009-pr4-v3/`。机制证据来自各 case 的 turns.json、versions.json、scores.json、meta.json；页数绑定按 resume_data 的生产同构 SHA-256（sort_keys/compact separators）独立计算。
