# 回放 bug 修复与离线验证

分支 `overhaul/tailor`；P1 `ce59714`、P2 `3ab19bd`、P3 `4710385` 保留，HEAD 未变。本轮修改仅在工作区，没有 commit/push、部署、真实模型调用或读取/打印 key；未操作既有 benchmark run 目录。

## 1. 个人资料被误判为 JD 后丢失

根因：DECODE_JD 直接绕过抽取后处理，解码为空仍排除原消息，导致已完成的并行抽取被丢弃。

收集节点先检查解码结果，空结果且允许作为候选来源时转 WRAP，复用已启动抽取，再走 absorb_education、bind_role_followup、正常回复/草稿更新；初始 JD 节点复用同一收集流程，局部指定 rewrite_experience，避免再次 triage。成功的 JD 或明确外部材料仍排除来源，保留现有岗位状态。

改动文件：

- `backend/app/agents/resume_graph.py`
- `backend/app/agents/triage_chain.py`

回归：初始/已有 JD 两条路径，已完成并行任务只抽取一次，无并行任务时正常抽取，教育与角色后处理，联系方式/链接/实习时间/奖学金保全；成功 JD 和明确外部来源保持排除；fake 图保存与 checkpoint 保留档案来源。

## 2. 项目状态进入 role

根因：抽取字段、项目元数据和档案映射均信任 role 标签，writer 与渲染沿用它，没有区分纯状态和本人职责。

纯状态词转 status_limit / project.status 或资料正文，保留原始依据与档案来源；writer 不续写错误角色，旧数据在共享显示层隐藏纯状态 role。「原型设计负责人」等真实职责继续显示。

改动文件：

- `backend/app/services/resume_field_hygiene.py`（与 bug 3 共用）
- `backend/app/agents/fact_extractor.py`
- `backend/app/agents/profile_archivist.py`
- `backend/app/agents/resume_writer.py`
- `backend/app/services/candidate_material.py`
- `backend/app/services/profile_service.py`
- `backend/app/services/resume_facts.py`
- `backend/app/services/resume_sections.py`

回归：fake 抽取的三种错误字段标注、文档元数据、fake archivist、档案来源映射、旧事实母版和 writer 旧页头、六款 HTML 与 Word/文本旧稿防护，以及含「原型/上线」的有效职责。

## 3. 荣誉名称标点与标题重复

根因：列表解析将句末标点保留在名称，并将完整原句同时作为正文，HTML/Word 未检查正文是否重复标题。

名称在解析/事实归一化/显示时去首尾标点，原 quote/raw_notes 不变；共享规则忽略仅重复 name、level 或 name+level 的 bullet，保留有新增信息的补充说明。HTML 使用 canonical 原 bullet 索引，不因去重把编辑路径指向另一条。

改动文件：

- `backend/app/services/resume_field_hygiene.py`
- `backend/app/services/candidate_sections.py`
- `backend/app/services/profile_service.py`
- `backend/app/services/resume_facts.py`
- `backend/app/services/resume_sections.py`
- `backend/app/services/resume_review.py`
- `backend/app/tools/resume_data_docx.py`
- `data/jianlimoban/html-template/_macros.html.j2`

回归：空 fake 模型/带标点 fake 模型输出均保留来源，六款 HTML 和生成 Word/文本只显示一次，level 重复、中文全角分隔符、补充正文及编辑路径保留，渲染不改原数据。

## 4. advice 近似选项

根因：旧代码仅按完全相同文字去重，提示词没有要求信息焦点与结构差异，失败兜底还用项目前缀凑第二个选项。

合同明确本人分工/决策、机制/产出、最短表达的差异；NFKC、大小写、空白/标点归一化后计算 Levenshtein 距离 / 最大长度，比例 <20% 去重。不足两项时只补一次未用 style，补充仍通过 active fact 引用、词法和语义核验；仍不足时保留一个核验通过的选项或原句并说明。

改动文件：

- `backend/app/agents/wording_advice.py`
- `tests/test_p1_dialogue.py`（两项旧断言按单选项合同更新）

回归：负责/规划与标点差异去重，换 style 补齐，两个合格选项不多调用，补充仍相似/同 style/不支持数字或工具/无效引用时只给一个，语义失败与模型异常不凑数量，20% 阈值边界，状态不变。

## 验证

新增集中回归：`tests/test_replay_bug_regressions.py`，25 项，全部使用虚构资料和 fake 模型。没有真实模型回放；本轮验证的是修复逻辑与离线集成。

指定全量命令：`.venv/bin/python scripts/run_tests.py`，**1159/1159 通过，22.373 秒**。日志：`/private/tmp/huhua-replay-full-tests.log`。`git diff --check` 通过；所有修改 Python 文件 Ruff `--ignore E402` 通过（测试的 sys.path 前置导入沿用仓库方式）。

交接记录另更新 `mmr.md`。没有数据库迁移；旧稿的显示修复不会改写其持久化原文或丢弃已知状态事实。
