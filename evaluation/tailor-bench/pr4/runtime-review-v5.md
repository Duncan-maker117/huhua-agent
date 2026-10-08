# PR4 v5 公开运行机制复核（已完成，含一次错误补评）

冻结源码：`ada326e95524942db32efbd3575d1213db4a8eb1`。主跑于 2026-10-09T02:52:11.791368+08:00 开始，03:16:47.450055+08:00 结束时为partial；仅错误项补评于03:18:23.064082+08:00完成，最终manifest `status=completed`、`backend_unchanged=true`。这里completed表示运行/评分记录齐备，不表示PR4验收通过。

仅审阅 `evaluation/tailor-bench/runs/20261009-pr4-v5/`，对照公开v4。未读取私有材料，未修改MAIN、harness或任何run，未新增模型调用。主线程在冻结源码上只补评两个Judge错误，两项各保留1个previous_attempts及previous_review_calls；本报告保留初评口径，不把未经有效评分的解释当成功。

## 主跑量化证据

- 12/12例主跑结束，70轮、69个记录版本（68可见、1仅内部）。无graph turn错误或state读取错误；219个graph逻辑模型请求均记录completed。新安全异常链未被本轮runtime错误触发，不能拿“没有异常”证明其线上覆盖。
- Writer轮次诊断：24次model_completed、1次model_fallback。7次单次schema retry，6次恢复、1次仍失败。model_completed仍可能包含逐bullet的Guard fallback，不能等同全文通过事实核验。
- Guard记录28条：9条guard_repair_failed、19条missing_item_status_limit。它们是回退/补回记录，不是28项新增事实。
- 初评编辑 **20/24（83.3%）执行**：2条not_followed、1条no_diff、1条Judge error；没有not_run。初评时三条确定失败已将理论上限限定在21/24（87.5%），低于90%门槛；不能从分母移除这些失败。
- 初评版本评分：57 completed、11 no_draft、1 error。algorithm/v003是逐版本JudgeSchemaError，pm/T5是edit JudgeSchemaError，均为ungrounded evidence quote；graph对应轮次均完成。原始错误须保留，不据unvalidated_result认定执行成功。
- 一次仅错误项补评后：**最终编辑21/24（87.5%）执行、2 not_followed、1 no_diff、0 error**；版本评分58 completed、11 no_draft、0 error。PM T5获得有效executed=true，algorithm/v003获得有效逐版本评分，原先失败尝试各保留1次。三个确定失败及24分母未改变，仍未达到90%门槛。
- 69/69版本身份hash重新计算匹配；25/25 page-check的data_hash匹配实际resume_data。69/69实际PDF渲染为1页，无超页；公开样例未触发自动长稿压缩，compression_writer_diagnostics与compression_retention_checks均为0。
- 67对同时具备node和SQL快照的版本，完整collected_info、active_facts、active_skills逐值相同；这67对也与turn上SQL快照相同。68个可见版本均有同轮同hash的SQL commit记录；12个最终resume.json均等于最后可见版。
- 上述一致性利用harness分别记录的node/committed快照与commit hash独立核算，未读取在线用户数据库。PM初始空稿没有可用node/SQL双快照，另有一个未提交内部版本，不把这两者伪计入67对。

| Case | 轮数 | Writer完成/回退 | 最终编辑 |
|---|---:|---:|---|
| ai-pm-01 | 5 | 2/0 | T4:executed；T5:executed |
| algorithm-01 | 7 | 3/0 | T6:executed；T7:executed |
| backend-01 | 5 | 2/0 | T4:executed；T5:executed |
| career-switch-01 | 6 | 2/0 | T5:executed；T6:executed |
| data-01 | 7 | 2/0 | T6:executed；T7:executed |
| design-01 | 6 | 2/0 | T5:executed；T6:executed |
| direction-01 | 5 | 2/0 | T4:executed；T5:executed |
| frontend-01 | 5 | 2/0 | T4:executed；T5:executed |
| import-01 | 6 | 2/0 | T5:executed；T6:not_executed |
| minimal-01 | 7 | 2/0 | T6:executed；T7:not_executed |
| ops-01 | 5 | 1/1 | T4:executed；T5:not_executed |
| pm-01 | 6 | 2/0 | T5:executed（补评）；T6:executed |

## Schema恢复与旧稿回退

| Case / turn | 首次结构错误 | 一次恢复结果 |
|---|---|---|
| ai-pm T4 | writer.items[0].bullets[1/2].&lt;extra&gt; | model_completed |
| algorithm T6 | object_missing | model_completed |
| design T6 | match_plan.&lt;extra&gt; | model_completed |
| direction T4 | writer.items[0].&lt;extra&gt; | model_completed |
| frontend T4 | item.summary / item.summary_fact_ids | model_completed |
| import T6 | 两个item的summary / summary_fact_ids | model_completed |
| ops T5 | match_plan.&lt;extra&gt; | 重试后仍extra_forbidden，保留旧稿 |

ops T5的2个逻辑模型请求均完成，耗时12.821秒，不是已观察到的超时或供应方调用失败。v005与v004的resume_data完全相同，业务撤销历史长度1→1；benchmark因诊断元数据变化记录v005，不代表正文编辑完成。fallback_action=preserved_existing_draft、deterministic_updates_applied=false，回执明确本轮改写未完成并保留旧稿，最终edit=no_diff。旧稿保护正常，结构恢复仍有边界。

相较v4的5次重试2成3败，本轮7次重试6成1败，能证明本轮多种已知层级错误成功恢复；模拟追问、披露与模型随机性不同，不能把比率差异全部归因于某一句提示改动。

## 三条确定未执行编辑的机制

1. **Import T6：精简后更长。** Schema恢复成功，随后目标bullet的guard修复失败，回退到来源事实串接，再补限制。最终增加项目背景且保留“没统计报名效果；也没统计报名效果”重复，Judge判not_followed。事实引用合法或只剩一条，并不等于完成有效精简。原始repair输入/输出未保存，不推断二次拒绝是否正确。
2. **Minimal T7：模型计划本身违背一条要求。** 用户明确“精简成一条”，match_plan却给target_bullets=2，理由明确说另保留独立动作为第二条；最终确为2条，第二条还发生guard_repair_failed事实拼接。v5 cap正确执行模型计划的2，却未保证计划服从用户的1。此轮没有自动页面压缩调用，不能归因于keep自动压缩。后续应校验计划与明确指令的一致性，不能用硬编码case或简单前缀截断修分。
3. **Ops T5：结构恢复仍失败。** 见上一节；没有正文变化且如实回执，不能记为成功。

## 已证实的表达与事实边界问题

**同义限制重复。** backend T5已写“仅在本地演示，未部署”，末尾又追加“没部署”；ai-pm T5已写未上线、本人未承担相关开发、未任组长，末尾又追加同义限制。career、data、direction、frontend也有类似重复；import出现“没统计报名效果；也没统计报名效果”。

确定定位为`resume_limits._limit_key`（v5源码86–94行）仅归一尚未/并未/还未/没有，再要求整段包含；没/还没、主语省略、词序或同义表达不能去重。v5不再把“引用fact”当作“表达其全部限制”，避免复合限制漏写，但更容易显露此类重复。不能为了去重恢复fact_id整体豁免；有后续候选时，应仅在同对象、同动作与同否定范围内保守判断。

**频率升级。** 事实预审与主线程已定位career v006把原文“有时”提升为“常”，同时改写主语和连接词。`fact_guard._explicit_frequency_upgrade`（153–162行）的触发前提是去频率词后两整句完全相同，因此词法门没有拦截，语义guard也未拒绝。该版writer为model_completed，仅有限制补回，无guard_repair_failed。不能以edit=true或模型请求completed代替事实安全；不得全局禁“常”或粗扩词袋。后续仅建议使用同义重写反例与原文明确高频正例成对验证，绑定主体、动作及频率证据。

**Guard fallback仍容易冗长。** 9条repair_failed分布为ai-pm T4（1）、design T5（1）、direction T4（1）、frontend T4（1）、import T5/T6（各1）、minimal T6（2）/T7（1）。引用事实逐条串接可重复既有动作和工具，并混入与岗位表达无关的已知缺项。它保留来源不等于产出可投递文案；不得从这些诊断反推每个二次guard裁决是否正确。

## 未重现的旧缺陷及边界

- design本轮所有轮次及两条编辑完成，没有重现v4的RuntimeError。**无runtime error不代表修复了v4未知根因。** 本次没有新的安全stack定位，也没有据此提出猜测性runtime补丁；v4原异常仍不能从这次成功反推原因。
- frontend在v002就有加载中/没结果/请求失败界面的active fact，后续稿件包含该工作；v4的这项入库遗漏本轮未重现。无法单凭一次随机实测确定究竟哪项候选改动造成改善。
- PM T1仍返回decoder空结果固定回复、留在JD_INPUT，不能断言实际是JSON、schema或语义空提取。T2的新WRAP转接进入COLLECTING，当轮4条SQL active facts包含未开发上线的原型状态，不再只留在raw_notes。最终正文仍保留原型限制。JD解码问题没有被窄转接修复，也没有假装成功。
- PM T2的v002仅内部、v003可见，两者resume_data和完整事实相同，差异只有空resume_meta/resume_versions/session_constraints规范化；没有SQL另行删正文的证据。
- 公开页数全部通过，不验证私有一页或新keep合并压缩行为。本轮未运行该分支，无法据此声称证据保留语义检查通过；私有审阅由另一agent负责。

## 结论与补评边界

v5公开机制比v4更少结构回退、未见运行崩溃，但仍未满足编辑≥90%，事实边界与表达重复也未通过。确认新增经历事实仍需指定复核，不能填0。

主线程的一次仅errored两项补评已完成，最终21/24、58/11/0；初评20/24、57/11/1与上述三条确定失败保持留痕。源码、harness、原始run均未由本审计修改。最终核查时间为2026-10-09T03:19:35+08:00。
