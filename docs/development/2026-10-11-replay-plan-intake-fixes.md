# Flash 回放 fix2：方案、资料路由与技能保留

本轮在 `overhaul/tailor`、HEAD `4e30f42` 上做增量修复，保留已有 P1–P3 与 fix1。没有真实模型调用、commit、push、部署或真实库迁移；未查看凭证文件。所有新增样本为虚构候选人，模型为本地 fake。

| 项目 | 根因 | 改动文件 | 修复后的行为及回归 |
| --- | --- | --- | --- |
| 1. 方案回退 | 定位句的 schema 30 字硬限制与 StructurePlan 缺少宽容版本，让可用输出进入重试/回退。 | `backend/app/schemas/writer.py`、`backend/app/services/structure_plan.py` | 推荐/备选 positioning 均取消 max_length；合同继续引导不超过30字；开启现有忽略额外字段开关时，方案及全部嵌套层丢弃未知字段；31–40 字完整保留，超过40字整句丢弃，不截断、不触发 schema 回退。 |
| 2. 主线与定位被清空 | 卡片叙事和投递正文共用词面规则，且定位句未获得语义核验。 | `backend/app/services/structure_plan.py`、`backend/app/services/fact_guard.py`、`backend/app/agents/resume_writer.py` | thesis 只作为方案叙事：检查数字、计量单位与已知具体技术词，不要求词面覆盖，也不写入简历；定位句数字/单位保留硬校验，综合措辞由 verify_semantics 判定，推荐/备选一起核验，确认写稿时与正文 guard 同一批次，失败/缺失/异常均清空；被定位句覆盖的 writer summary 不再单独调用 guard。 |
| 3. 个人资料覆盖 JD | triage 的 DECODE_JD 猜测与“长文本就是 JD”的判断未经确定性资料类型检查就进入 decoder。 | `backend/app/agents/resume_graph.py` | 统一检查 JD/个人特征，所有 decoder 入口先检查；已有 JD 时只有带 JD 特征的消息可替换；无 JD 时个人资料同样不能解码；姓名、联系方式、教育、开源/竞赛/技能列表保留为候选资料；长个人资料不再变成纯岗位方向；显式 decode_jd 的 stream 标签也保留 candidate 来源。 |
| 4. 待确认时补料不重出方案 | 补料后只在 collecting 返回 BUILDING 时重出方案，否则会直接丢掉待确认卡片。 | `backend/app/agents/resume_graph.py` | 提取/导入完成后，只要事实发生变化就清旧方案、基于新事实返回新卡；无变化保留待确认卡；不写正文、不创建版本；graph checkpoint 与 session 保存都保留新增资料和来源，原 JD 不被覆盖。 |
| 5. 重复确认重写并丢技能 | 没有 pending_plan 时确认语落入写稿，writer 非空 skill_groups 又整体替换了原分组。 | `backend/app/agents/resume_graph.py`、`backend/app/agents/resume_writer.py` | 已有稿且无待确认方案时仅说明当前稿已按方案写好、可说“重新定方案”；各阶段均不改稿、不建版本；首次确认有 intake 预览时仍正常写稿；整稿 writer 合并仍有事实支持的旧分组、模型分组及全部 active 用户技能，保留既有固定分类/去重/容量规则，已删除或虚构技能不恢复。 |
| 6. 收集话术限制用户逐段输入 | 提示词把每轮一个问题混成了只允许用户给一段经历。 | `backend/app/agents/resume_graph.py` | JD_INPUT、COLLECTING_ASK_EXP、COLLECTING_WRAP 与岗位方向开场鼓励一次给全经历和材料，支持旧简历、截图、列表；每轮最多问一个会改变简历的问题。 |

新增回归集中在 `tests/test_replay_plan_intake_regressions.py`：23 项测试，包含长度边界、深层额外字段、综合 thesis、数字/单位、语义拒绝/缺结果/异常、同批次调用、各阶段误路由、补料导入/抽取与持久化、重复确认、首次确认、技能保留及删除技能不复活。

调整旧测试以对应新约束：`tests/test_structure_plan.py`、`tests/test_replay_bug_regressions.py`、`tests/test_parallel_calls.py`、`tests/test_career_skills.py`、`tests/test_conversation_rebuild.py`。保留无当前 JD 时的 prose JD 解码/抽取取消回归与真实解码失败兜底；个人资料现在断言 decoder 根本未调用。旧纯字段/栏目调整仍走确定性操作，已由原 P2/PR5 回归验证。

验证命令：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py
```

结果：**1182/1182 通过，22.500 秒**，原1159项加23项。修改文件 Ruff 通过（忽略仓库既有 E402 导入布局），`git diff --check` 通过。未重跑真实 DeepSeek 回放，因此本轮证明的是离线逻辑/状态/合同回归通过，不把 fake 语义判定当成真实模型质量证据。
