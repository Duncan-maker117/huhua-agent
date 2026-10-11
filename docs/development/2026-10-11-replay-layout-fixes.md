# 游客回放版式与成稿回复修复

分支 `overhaul/tailor`，保留 HEAD `b06e7ed` 和既有回放目录；仅修改本地文件，无 commit/push/部署。

## 逐项根因与结果

1. 竞赛荣誉复用了带逐项底边距的经历块，五项奖项因此占用五个大块。六款 HTML 模板和 Word 改为「名称 级别」的分号段落；保留日期、链接和非标题回显的实质说明，预览沿用原 bullet 索引。
2. 定位句合同称其为 summary，但赋值和导出实际复用了 self_evaluation，因而出现在页尾。新增独立 ResumeData.summary，confirmed positioning 和经过核验的 writer summary 放在页头联系方式下面；自我评价只保留 collected_info 中用户真正提供的自评。同步页头编辑入口、版本差异、失效清洗和保存后正文保留。
3. 开源标题、独立简介行和 bullet 使用各自的输出规则，没有共同去重。HTML/Word/文本标题统一为「仓库名（summary）｜ PR 号」，渲染与 writer 后处理只删除开头重复的同一 PR 号；其他 PR 和句中的 PR 引用保留，写回后同步正文来源 hash，合同明确 PR 号在标题行、bullet 不重复。
4. 专业补救拆出了正确专业，但旧事实清洗将它与已 superseded 的「专业+本科」近似匹配，又清为空值。清洗时以同一条目、同一字段的精确 active 事实为准，过时专业和真正已删除的专业仍会清除。
5. 模型的 reason/thesis 等叙事原样传递到了方案卡和成稿说明，内部 requirement/signal id 因而泄漏。按当前岗位画像将其替换为不超过 40 字的要求/信号原文，找不到则删除编号；只处理 prose 字段，结构化 req_id/item_id/fact_id 保留。替换后的定位句仍须通过原有事实核验。
6. 直接写稿另附 plan_summary，而 interviewer 又生成相同思路，且 lead 理由没有字数预算。去掉「方案摘要」输出，只留一处「这版的思路」；思路段含 thesis 和 lead 名称，每个理由不超过 20 字，连同标记不超过 150 字。
7. 隐私提示只说明联系方式是占位，没有明确区分系统已保存的原值与模型看到的脱敏文本。共用提示明确此区别，用户回复只确认「电话、邮箱已记下」，且仅确认实际提供的项，不提占位符。

## 回归与验证

- 新增 `tests/test_replay_layout_regressions.py` 的 **18 项**回归，均使用虚构候选人、fake 抽取/写作/语义模型和隔离 SQLite；未调用真实模型或真实用户存储。
- 教育端到端测试以游客前两轮的上下文为起点，第三轮送入指定教育句，fake 抽取模拟错误的专业+学历字段；实际执行 collecting → 方案卡 →「先出一版看看」→ writer → SSE → SQL 保存，再回读最终 education、confirmed_plan 和版本。
- 同一虚构版式输入含三个项目、两条开源 PR、五项荣誉；原实现 `t001-jianyue` 为 **2 页**，修复后以 `count_resume_pdf_pages` 断言 **1 页**。六款模板还分别实际测量了带独立页头定位和真实自评的虚构输入，均为 1 页。
- HTML 核对页头位置、奖项段落、隐藏条目、非回显说明和原字段路径；Word 用现有导出方法生成并回读段落，核对相同规则。
- 额外检查不同 PR 不被误删、writer 单轮/确认写两条路径、正文 hash、专业纠错和删除、旧版本失效、定位失效、结构化编号不变及三个 lead 的字数预算。
- 六个既有测试文件更新了预期：定位句从 self_evaluation 移至 summary，重复思路改为一处简短思路；保留其原有语义、并行和保存断言。
- 指定全量命令：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`，**1228/1228 通过，22.638 秒**。
- 修改的 Python 文件 Ruff（忽略项目既有 E402 导入布局）、`node --check web/resume-editor.js`、`git diff --check` 通过。
- 本轮未读取/打印凭证，未调用真实模型，未重跑真实模型回放；PDF 页数结论来自虚构回归的真实本地排版。

## 完整修改文件

业务与显示：

- `backend/app/agents/interviewer.py`
- `backend/app/agents/resume_graph.py`
- `backend/app/agents/resume_writer.py`
- `backend/app/agents/tailor_pipeline.py`
- `backend/app/schemas/editor.py`
- `backend/app/services/model_privacy.py`
- `backend/app/services/profile_bridge.py`
- `backend/app/services/resume_field_hygiene.py`
- `backend/app/services/resume_review.py`
- `backend/app/services/resume_versions.py`
- `backend/app/services/resume_workspace.py`
- `backend/app/services/session_store.py`
- `backend/app/services/structure_plan.py`
- `backend/app/tools/resume_data_docx.py`
- `web/resume-editor.js`
- `data/jianlimoban/html-template/_macros.html.j2`
- `data/jianlimoban/html-template/t001-jianyue.html.j2`
- `data/jianlimoban/html-template/t002-jianyue.html.j2`
- `data/jianlimoban/html-template/t004-jianyue.html.j2`
- `data/jianlimoban/html-template/t1000.html.j2`
- `data/jianlimoban/html-template/t1001.html.j2`
- `data/jianlimoban/html-template/t1002-jianyue.html.j2`

测试与交接：

- `tests/test_replay_layout_regressions.py`（新增）
- `tests/test_p1_fixes.py`
- `tests/test_parallel_calls.py`
- `tests/test_replay_guest_fidelity_regressions.py`
- `tests/test_replay_plan_intake_regressions.py`
- `tests/test_resume_writer.py`
- `tests/test_structure_plan.py`
- `mmr.md`
- `docs/development/2026-10-11-replay-layout-fixes.md`（本文件）
