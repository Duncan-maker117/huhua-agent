# 五人物剩余问题修复记录（2026-10-15）

基于 `overhaul/tailor` / `03a5c70`，未提交、推送或部署。先读取 after-batch6/run.json、人物逐轮 JSON/reply、before-20261014-1 与 before-20261014-1-rest。冻结证据未修改。

## 逐项根因与修法

位置为本批最终文件的行号；根因描述对应修改前行为。

| 项 | 根因与位置 | 修法及验证 |
| --- | --- | --- |
| 1 首轮不抽取 | `backend/app/agents/resume_graph.py:1658` 的方向快速返回和 SKIP_JD_OK 可以早于收集。ops initial 0.328s、无稿；career initial 无工作条目。 | 有本人陈述的首轮进入原收集链；整条候选材料抽取，排除明确 JD；已抽取事实进入回复上下文，已有直接生成和方案确认机制继续工作。四人物抽取桩 + 既有设计导入测试覆盖。 |
| 2 异常/断连丢事实 | `resume_graph.py:3079` 原先只在图完成后保存；节点抛错无更新，API 关闭直接取消迭代。 | `services/session_store.py:253` 独立事实事务先落 SQL，不覆盖旧稿/版本；失败回填 checkpoint。`api/chat.py:56` SSE 与生产任务分离，生产任务持锁至完成；断连后停止排队发送内容。新增隔离 SQLite 回读、回复抛错、抽取等待期间断连后继续保存测试。 |
| 3 杂项与指令污染 | `resume_graph.py:495` 的原话收割器给未命名材料自动造杂项项目；原非事实规则未挡润色/生成指令。 | 删除泛化项目兜底，未知归属保留顶层 raw_notes/unrecorded；`services/candidate_language.py:35`、`agents/fact_extractor.py:502` 过滤个人字段与指令，原始经历 notes 同样过滤；写作规则进入 session_constraints，元信息进 metadata_context。代码生成处全仓检索已无两段旧文案。 |
| 4 无公司后缀 | `services/candidate_language.py:105` 只认命名句或公司/事务所等后缀。 | `literal_employment:23` 识别2–12字专名和职位，`fact_extractor.py:587` 补公司/职位字段；覆盖云舟科技、启明商贸以及做/当/任，拒绝大学/学校/家和动词开头候选。 |
| 5 限定被删 | `services/resume_limits.py:143` 将限定仅当禁止条件，清掉缺失状态；同学分工也未参与强制保留。 | `:205` 在相关动作 bullet 中恢复有来源的限定，不另造限定 bullet；按同经历引用/词语关联，数字成果同源限定自动保留，明确“保留限制”会话持久化。覆盖未做线上压测、导师/测试环境、登录分工、演示无真实用户。 |
| 6 12条丢失 | after-batch6 的 fact_coverage 明确将“编写了12条接口测试用例”列为“按已确认方案或指定条数…备用”，非抽取丢失；`resume_writer.py:108` 原只检查 result_metric 引用，`:1548` 将事实“12条”也当条数要求，默认cap阻止补回。 | 数字动作/交付也优先；检查正文包含事实而非只检查 ID；满额优先保留数字，多个数字需要时合并；条数要求只认最多/只写/控制在等指令。桩验证数字事实被省略、过度引用、仅一条预算时仍保留12/8/4。冻结API未暴露该事实原始kind，不能断言历史抽取分类具体值。 |
| 7 career更正 | `resume_graph.py:2773` 旧 COLLECTING 的可见稿路由未覆盖“润色/更正”，career仍走收集自由回复；tech在编辑阶段走字面更正成功。 | 路由识别润色、纠正对与更正指令，复用 `services/fact_corrections.py:62` 全引用事务；`:16` 补无旧值但能唯一定位的“培训次数改成4场”。保留先校验新旧正文再保存/成功回执，多归属歧义不猜。 |
| 8 公开文案 | `resume_graph.py:2260` 正常writer回执每次输出内部density和页数。 | 一页成功时不输出；超页继续解释溢出及可选压缩/删减；保存时回执修正不再提不存在的“上述页数”。 |
| 9 检查口径 | `checks.py:320`、`:354` 的service/design全程正文检查遍历原始initial，方案卡也被当交付稿。 | 仅这些检查改用 `document_turns:169`：本轮及其trigger_action相同的确认稿，仍逐轮验证；缺确认稿、晚期退化仍失败。common.first_draft原已按initial及确认，不改；ops无需改。直接生成仍检查原始当轮，确认稿不能补救。 |

## 冻结重评

运行 `python3 evaluation/persona-ux/report.py evaluation/persona-ux/runs/after-batch6` 成功；报告另存 `after-batch6-rechecked.md`，不改 run.json/人物材料。

**47 → 53 / 71 仅为检查取样修正**。变化的6项：service.single_education、school_clean、complaint_limit、volume_800；design.single_course_project、concept_limit。service.approval_limit仍失败，因为polish实际删掉了“审批”；ops首稿/日期、tech限定/数字等历史失败没有被掩盖。

`tests/test_persona_checks.py` 新增方案卡→确认稿、确认稿缺失、直接生成不可借确认、后续稿退化测试；无语义放宽。

## 验证与边界

- 全量：在 `/private/tmp/huhua-persona-batch7-safe`（无实际配置、私有样例或历史输出的源码副本）执行 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`，**1550项、1548通过、2项原有私有样例跳过、0失败，49.464s**。日志 `/private/tmp/huhua-persona-batch7-final.log`。
- 26份变更Python文件和测试副本SHA-256一致；AST、git diff --check通过。Ruff与HEAD同为22项已有诊断，没有新增。
- 本批测试只用合成fixtures和桩，不调用真实LLM。53/71不代表本批代码真实回放成绩；旧产物不能验证新代码的模型质量与延迟。
- 无法唯一定位的更正（含跨多经历的相同数值）仍返回未完成；不以口头成功替代正文验证。无后缀公司仍用保守专名/职位结构，复杂代称未承诺通用识别。
- 断连后台任务只在当前服务进程存活时继续；事实事务提交后可以恢复，进程在抽取完成前被终止不保证自动续跑。既有model_slot超时仍有效。
- 未做提交、推送、部署。本批没有改冻结输入和历史run.json；已存在的未跟踪tailor-bench运行目录未处理。

## 改动文件

- `backend/app/agents/fact_extractor.py`
- `backend/app/agents/resume_graph.py`
- `backend/app/agents/resume_writer.py`
- `backend/app/agents/tailor_pipeline.py`
- `backend/app/api/chat.py`
- `backend/app/services/candidate_language.py`
- `backend/app/services/fact_corrections.py`
- `backend/app/services/resume_limits.py`
- `backend/app/services/session_store.py`
- `evaluation/persona-ux/checks.py`
- `mmr.md`
- `tests/test_career_skills.py`
- `tests/test_committed_resume_receipts.py`
- `tests/test_complete_resume_task.py`
- `tests/test_editor_source_coverage.py`
- `tests/test_followup_fact_ownership.py`
- `tests/test_jd_input_candidate_intake.py`
- `tests/test_p1_dialogue.py`
- `tests/test_persona_checks.py`
- `tests/test_persona_regressions.py`
- `tests/test_public_streaming.py`
- `tests/test_replay_bug_regressions.py`
- `tests/test_replay_plan_intake_regressions.py`
- `tests/test_resume_density.py`
- `tests/test_resume_flow.py`
- `tests/test_writer_graph.py`
- `tests/test_writer_metric_priority.py`
- `evaluation/persona-ux/after-batch6-rechecked.md`（新重评报告）
- `evaluation/persona-ux/batch7-fix-notes.md`（本记录）
