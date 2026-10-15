# 第九批修复（基于 75716f4）

## 1. 结构化字段块与海报事实
根因：附件原文换行完整，确定性导入的 `candidate_sections.parse_labelled_items()` 将校园块整体建成一条 action，未解析职务/日期；正文清洗还把“按部长给的文案制作过 6 张海报”误判为纯限定并删除，问题发生在落库前。
改动：学生组织/公司块按行归属字段、正文按现有句号/分号规则拆事实，项目块同样识别职务/角色/岗位；日期复用 `experience_dates.parse_month_range()`，保留原文与文件出处、重复来源及字段冲突。实际制作动作不再被限定清洗吞掉，独立否定事实约束 writer，已填字段不再出现在 missing。
测试：`test_labelled_block_splits_fields_actions_and_limit_with_original_sources`、`test_attachment_and_paste_share_atomic_import_and_missing_projection`、`test_design_first_draft_keeps_six_posters_team_and_headers_with_sparse_writer`、`test_one_bullet_campus_plan_restores_poster_count_without_promoting_limit`、`test_writer_cannot_turn_separate_ownership_limit_into_activity_planning`；另覆盖公司别名、重复来源、字段冲突和缺失/倒序日期。

## 2. 日期与后续数字粘连
根因：`candidate_material` 将已识别的日期继续放进项目正文，`_append_wrapped()` 无分隔拼接下一行“3 人课程小组”，形成 `2025.063`；损坏正文又被当作来源，数量单位扫描也会先去除空白、合并原本分开的数字。
改动：已解析日期只作为起止字段；结构化项目逐行拆句，PDF 软换行保留相邻数字/标识符间分隔；数量单位校验保留原始空白，按原来源拦截粘连数。日期不进入 description/bullet，3 人团队信息保留。
测试：`test_structured_project_preserves_line_boundaries_and_excludes_date_bullets`、`test_soft_wrap_cannot_fuse_adjacent_numbers_or_break_chinese_words`、`test_numeric_guard_rejects_concatenated_date_and_new_063_quantity`、`test_spoken_ops_tech_and_single_line_course_keep_extraction_route`；首稿测试同时核对 description/polished_bullets 无日期范围、无“063 人”。

## 验证

新增 14 项合成数据、fake/stub 回归，不调用真实 LLM。在不含真实配置、私有样例和历史输出的源码副本 `/private/tmp/huhua-batch9-safe` 执行指定命令 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`：**1586 项，1584 通过、2 项原有私有样例跳过，0 失败，54.330 秒**；日志 `/private/tmp/huhua-batch9-full.log`。隔离副本避免原有私有测试向 `runs-private/` 写临时目录；全量包含 ops/tech 人物及第八批日期、技能回归。
6 份修改 Python 源码/测试 AST、Ruff、差异检查通过，SHA-256 与测试副本一致；`checks.py`、fixtures 与设计 TXT 均与 `75716f4` 一致。未修改原私有目录/输出，未重跑真实模型 71 项回放，未 commit、push 或部署。
