# 第八批修复（2026-10-15）

## 1. 经历日期（ops.association_dates）
根因：冻结回放的事实覆盖中没有两段经历日期；抽取入口仅教育有日期恢复，普通字段还会把 `2024.09` 对照中文年月判为新数字，日期句也不会被动作兜底补回，并非 writer 将已有日期清空。
修改：`experience_dates.py` 在抽取入口解析具名经历年月范围、继承省略的结束年份，按已有 item_id 回填字段事实；序列化和 writer 共用这些事实，歧义归属/倒序范围不猜。
测试：`test_ops_dates_recovered_before_projection_and_writer`、`test_date_only_followup_updates_same_named_items_without_model_fields`、`test_formatted_model_dates_recover_from_literal_range_validation`、`test_ambiguous_or_unowned_dates_do_not_attach_to_an_experience`。

## 2. 兼职类型
根因：`employment_type()` 只有全职/实习判断，schema 也只有 `internship/full_time`，因此含“兼职”的明确原话仍进入默认全职。
修改：`resume_sections.py` 从该条目有效事实识别兼职，`schemas/editor.py` 增加 `part_time`；未说明类型时保留原默认逻辑，占位公司改名后类型仍保留。
测试：`test_part_time_survives_placeholder_rename_writer_and_schema`，覆盖抽取、同条目改名、成稿和 schema 回读。

## 3. 局部润色与条目内去重
根因：ops 的“咖啡店”代称未命中公司/职位而扩大到全部经历；career 冻结回放走了 polish → polish_confirm，整稿方案确认丢失原局部范围；旧相似度去重不理解重排后的数字动作。
修改：`tailor_pipeline.py` 按唯一原话代称定位，正常/失败 writer 均恢复目标外原值；`resume_graph.py` 避免已有正文局部润色进入整稿方案确认，并在最终 SQL 保存前再次约束范围。`fact_coverage.py/resume_writer.py` 仅合并可绑定同一数字、动作及对象的文章排版/初稿重复句，保留较完整原句并合并引用；不同数字归属、主体和额外信息不误删。
测试：`test_named_polish_hard_boundary_in_pipeline_and_failure_path`、`test_final_save_protects_scope_even_if_graph_route_rewrites_other_fields`、`test_legacy_career_polish_does_not_enter_whole_document_plan_confirmation`、`test_named_rewrite_with_additional_facts_cannot_widen_writeback`；`test_numeric_action_duplicates_keep_fuller_bullet_and_merge_citations`、`test_numeric_dedup_does_not_drop_different_actions_counts_or_ownership`。

## 4. 技能熟练度（tech.skills）
根因：模型返回裸 `Redis` 时抽取校验允许接受，却未从原句恢复“了解”；确定性声明词表不含 Redis/了解，分组清洗又只保留“基础”括号。
修改：`candidate_skills.py/fact_extractor.py` 从本人原话恢复限定、按技能本体合并，沿用事实守卫拒绝否定技能；`skill_groups.py` 保留了解/熟悉/基础等限定，禁止裸名称覆盖限定。
测试：`test_tech_bare_model_skill_recovers_literal_level_and_rejects_denial`、`test_skill_levels_survive_grouping_and_followup_without_duplicates`，使用 fixtures 原文及故意只返回裸技能/否定技能的 stub。

## 5. 中断生成真取消
根因：停止按钮只 abort SSE，第七批后台生产者仍继续运行；必须增加独立于断线的取消信号。
修改：新增鉴权接口 `POST /api/chat/session/{session_id}/cancel?turn_id=…`；`chat_turns.py` 绑定会话/账号/轮次，取消生产任务及后续调用；`session_store.py` 在提交前与取消互斥检查，`resume_graph.py` 修复 checkpoint。`web/chat-cancel.js/index.html` 等待本轮被接受，再请求取消，收到回执后断流、提示“已中断，本轮未修改简历”，恢复输入。
事务边界：取消前已提交的独立事实事务保留；未提交事实和本轮成稿不再提交。普通刷新/关页/断网仍后台完成；成稿已经提交则返回 `cancelled:false`，不谎报未修改。沿用当前 Docker 的单 worker 和会话锁模型。
测试：`tests/test_chat_cancellation.py` 的 8 项真实隔离 SQLite/LangGraph 回归覆盖取消、提交竞态、断线继续、下一轮、轮次绑定和跨账号/会话鉴权；`test_cancel_ack_precedes_abort_early_click_and_failure_remains_retryable` 用 Node 执行实际前端模块。

## 验证与边界

- 新增测试只用合成人物、fake/stub，不调用真实 LLM；真实模型 71 项回放未重跑，不将单元测试计为产品回放通过率。
- 在无真实配置、私有样例和历史输出的源码副本 `/private/tmp/huhua-batch8-safe` 执行 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`：**1572 项，1570 通过、2 项原有私有样例跳过、0 失败，54.509 秒**；日志 `/private/tmp/huhua-batch8-full.log`。新增 22 项回归；19 份本批源码/测试与副本 SHA-256 一致。
- Python AST、前端内联脚本及取消模块 `node --check`、`git diff --check` 通过；本批文件 Ruff 仅有 `resume_graph.py:200` 原有 E402，无新增诊断。首轮隔离副本缺 `.env.example` 导致配置测试报错，补齐公开样例后最终全量通过。
- 未修改 `evaluation/persona-ux/checks.py`、fixtures、历史回放、`cases-private/`、`runs-private/`、`data/output/`，保留用户已有 `posters_ownership` 修改；没有 commit、push 或部署。
