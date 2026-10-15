# 第十批：同一段经历拆分与合并更正

范围：仅修复本批 A/B 的主体归属、日期归属和合并更正；未改 `evaluation/` 下的 `checks.py`、fixtures 或检查口径。没有 commit、部署或真实 LLM 调用。

## 根因

1. `fact_extractor._subject_hint` 把没有个人练习语义的“日常更新”判为 personal；后面的“店长”又触发 work。`_nearest_named_owner` 的普通续接范围会在句号处截断，并且归属阶段原先只预载旧事实库，新建命名条目尚不可见。于是同一行的实习正文变成多个占位条目；名称追问只是这些错误占位的后续表现。
2. 自由文本中 `parse_education_fields` 识别到学校后，在整段 `education_text` 上取首个日期范围，没有确认日期所在的句子或条目；B 的实习日期因此被写成教育日期。日期恢复也缺少“教育时间是……”这种不重复校名的唯一教育目标定位。
3. 原来的 `corrections` / `removals` 操作只替换、删除单条事实。第五至七批的 `fact_corrections` 校验针对旧值/新值的正文替换，没有条目合并、事实迁移和旧条目删除操作。
4. `non_fact` 没有识别“属于同一段实习”“不是个人练习/不是项目”，允许更正意图被模型抽成经历事实；只更新公司名不能清掉已有的错误条目。

## 改动

| 文件 | 改动 |
| --- | --- |
| `backend/app/services/experience_subjects.py`（新增） | 从有明确名称的行首标签、编号经历提取有边界的主体范围。行内句号不切断归属，下一个编号/换行结束范围；匿名雇主使用用户给出的“本地连锁烘焙品牌”，不虚构公司名。 |
| `backend/app/agents/fact_extractor.py` | 移除单独“日常”的 personal 判定；在模型事实分配前注册本轮明确主体；抽取与遗漏补回优先使用该范围，同源命名条目共用 ID；执行确定性合并补丁，日期替换不重复插入同一事实 ID。 |
| `backend/app/agents/turn_actions.py` | 教育日期只从教育段落/句子提取，并拒绝其他明确主体中的日期，避免后续 `absorb_education` 再次污染数据。 |
| `backend/app/services/experience_dates.py` | 日期按所在句和明确主体恢复；唯一教育条目接受明确教育时间更正；撤销同轮可定位的错误日期映射，旧日期事实 superseded；同月/相同时间范围不相互删除，多主体歧义仍拒绝猜测。 |
| `backend/app/services/candidate_language.py` | 将同段归属、非个人练习/项目等元陈述判为 non_fact，也覆盖从这类原句截出的片段。 |
| `backend/app/services/fact_corrections.py` | 新增由原文验证的 `merges` 操作：明确公司 + 同段/非个人项目声明 + 每个主题唯一匹配旧事实，才合并。保留事实 ID、来源、链接和 `merged_from` 记录，删除来源占位条目、清理过时追问目标；新公司/岗位优先，历史误存的元事实退出 active 集合。 |
| `tests/test_batch10_regressions.py`（新增） | 使用固定抽取结果和桩 LLM 驱动真实抽取、补丁应用、收集与投影路径。 |
| `mmr.md` | 追加本批交接与验证结果。 |

合并不由模型直接指定 ID：否定/条件/疑问指令、多目标匹配、没有明确公司或主题无法定位时，不删除旧条目。本批覆盖首轮/收集态更正，不改变原来的数字正文替换事务。

## 测试

新增 15 项：

- A：模型刻意拆成教育、实习、个人练习、工作、校园，验证最终实习唯一、四类事实归属、公司/岗位/时间、无占位条目；模型条目倒序同样成立。
- B：编号自由文本中的实习与校园独立，实习日期不进入教育；第二轮补公司、岗位、教育时间后保留实习事实与日期。
- 历史拆分：分别验证有/无既有命名实习，模型给错误项目 ID、完全遗漏操作，以及同轮返回命名实习的情况；占位条目消失，事实 ID、原始来源和链接不丢失。
- 收集与工作区投影：旧草稿中的占位项目消失，教育日期更新，不再触发占位名称追问。
- 安全边界：否定合并、主题歧义不删除条目；不同结构化行不串事实；共用年月/日期范围不相互擦除。
- 非事实：完整、截断和历史误存的归属元陈述不进入 active 经历事实；“不是个人练习/不是项目”类更正可执行；不误伤“不是项目负责人”及“在同一段实习中负责账号更新”。
- 分类回归：“周末自己练手做的个人项目”仍属个人项目；“日常行政工作”仍属工作。

定向命令：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py -k Batch10`，**15/15 通过**。

最终全量命令：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`，**1603/1603 通过，0 失败、0 跳过，53.440s，退出码 0**。完整日志：`/private/tmp/huhua-batch10-verified.log`。

Ruff（本批 7 份 Python 源码/测试）与 `git diff --check` 通过。全量首跑发现的多主体日期歧义回归已修复，原有第八批用例保持通过；最终结果对应收紧元陈述边界后的源码。

验证边界：均为离线桩模型与本地测试；未复跑 8833 的真实 deepseek-flash 对话，也未重评既有线上人物回放。其他任务的 `web/comparison*` 改动未覆盖。

## 10b：经历时间落字段与公司描述清理

承接第十批未提交改动，仅补修本批 A/B，不改 `evaluation/` 下的 checks.py、fixtures，也不 commit。

### 根因

- 当前源码的固定输出复现中，A/B 的日期已经恢复为 `field=start_date/end_date` 的事实，但 `apply_fact_patch` 只追加事实，没有同步经历条目的同名字段。简历投影会读取字段事实，右侧 `build_workspace` 却直接读取条目字段，因此仍显示「经历时间」缺失。此前测试只断言事实中的日期，未覆盖条目字段和工作区缺口。
- 日期回填只新增结构化事实，没有清掉模型返回的独立日期要点。公司括号描述同样会通过普通事实校验；第二轮「实习公司叫……」及其规范化输出「麦穗烘焙，连锁烘焙品牌」也会保留，合并时原样迁移。
- 日期恢复原来按句子扫描。编号段与个人介绍连在同一句，或一句内包含多个编号和日期时，会被整句非事实/多日期检查跳过；仅靠文本第一次匹配也不足以表达明确编号边界。

### 改动

- `experience_dates.py`：先按明确主体范围定位月份区间，再对其余文本执行原自由文本回填；同句的不同编号分别归属。回填时移除独立日期区间/端点要点，保留带日期的实际动作。
- `fact_extractor.py`：补丁应用、日期更正/删除、经历合并完成后，只对本轮涉及的条目从有效日期事实同步 `start_date/end_date`；删除最后一个有效日期时清空字段，不复活旧日期。未涉及条目不改动。
- `experience_subjects.py` / `fact_extractor.py`：根据原文中的公司括号描述或明确公司命名句，过滤纯描述及「公司名，描述」式普通事实；不靠“品牌”关键词泛化删除动作，括号内的实际职责仍保留。
- `fact_corrections.py`：合并时清理历史误存的公司描述，保留原事实 ID、来源和内容，仅将其标为 deleted；有效日期事实继续迁移，再写入目标条目字段。

### 测试结果

`tests/test_batch10_regressions.py` 新增 6 项回归：

- A：模型把日期和公司描述返回为普通事实；检查日期事实、条目字段、工作区 period/缺口、简历投影和桩 writer 输出，均无日期/公司描述 bullet。
- B：模型完全省略日期字段时，首轮仍写入起止时间；第二轮返回「麦穗烘焙，连锁烘焙品牌」及截断描述时，合并保留日期并排除这些要点，教育日期保持独立。
- 历史合并：误存描述退出 active 集合，事实 ID、来源和原文仍可审计。
- 同句连续编号：两段经历分别获得自己的日期，不受前面的自我介绍干扰。
- 保护真实动作：含日期的职责、括号中的职责不被元信息过滤误删。
- 自由文本日期更正与删除：更新同一条目，清空已删除日期，其他教育/校园条目不变。

定向命令 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py -k Batch10`：**21/21 通过，0.133s**；日志 `/private/tmp/huhua-10b-targeted.log`。

指定全量命令 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`：**1609/1609 通过，0 失败、0 跳过，50.890s，退出码 0**；日志 `/private/tmp/huhua-10b-full.log`。包含第八批自由文本日期回填及第十批教育日期归属回归。

本次 5 份 Python 源码/测试 Ruff 与 `git diff --check` 通过；checks.py、fixtures、已有 `web/comparison*`、`turn_actions.py` 和 `candidate_language.py` 的前后 SHA-256 一致。原第十批改动保留。

验证边界：离线固定抽取结果、桩 writer 和真实本地处理链路；本轮未重新调用 8833 的 deepseek-flash，未部署或提交，不将离线结果描述为真实模型复测通过。

## 10c：tech 首稿接口职责与复合日期残片

### 根因与第十批改动的因果核对

对照 `runs/after-batch9/tech/01-initial.json`、`runs/after-batch10/tech/01-initial.json` 和 `runs/after-batch10-tech1/tech/01-initial.json`（内容也收录在各自 `run.json`）：

- 第九批的工作区 `role` 为空，「负责商品发布和搜索接口」位于 `bullets`；两个失败快照的工作区 `role` 都变成这段职责，`bullets` 不再包含它。职责仍在原始 `description` 中，因此不是被抽取过滤器删除，而是被当成结构化角色，退出了正文事实集合。
- 抽取器接受模型给出的 `field=role`。writer 的 `_body_fact` 排除标题字段，覆盖补回也不补结构字段；已有成稿的空 role 又不会由 writer 覆盖。接口职责因此可能既不出现在最终标题，也不出现在 `polished_bullets`。Spring Boot/MySQL 在失败快照的工作区和 description 中仍存在，遗漏发生在成稿选句阶段。
- 「2025.03—2025.06，3 人组队」在第九批 description 和成稿里已经存在。10b 的 `MONTH_RANGE.fullmatch` / 单端点过滤仅处理整个事实都是日期的情况，漏过“日期 + 团队规模”的复合事实。writer 的数字覆盖兜底将其中的「3 人」当作需保留的数量事实，可能把带日期的整句补成独立 bullet。

为避免把回放先后关系当成代码因果，使用完全相同的 tech 原文、固定抽取结果和 writer 桩，在进程内分别加载修复前源码与 HEAD `e19c18c` 的相关后端模块（`candidate_language`、`turn_actions`、`experience_dates`、`fact_extractor`；其后端为第九批版本）。未回退或替换工作区文件。

| 固定抽取结果 | 第九批后端 | 第十批 + 10b 修复前 | 10c |
| --- | --- | --- | --- |
| 职责为普通 action | 正文有接口，仍带日期残片 | 同左 | 正文有接口，无日期残片 |
| 职责误标 field=role | 正文丢接口，仍带日期残片 | 同左 | 职责归正文，无日期残片 |
| field=role + writer 只写团队/演示背景 | 正文丢接口 | 同左 | 覆盖补回接口及 Spring Boot/MySQL，保留分工限制 |

因此，**现有证据不支持把职责丢失归因于第十批某一条确定性改动**：同样的误标在第九批源码也会失败。这次回放暴露的是既有 role/正文分类漏洞，加上 10b 尚未覆盖的复合日期清理缺口。冻结产物没有模型原始响应，不能进一步断言模型为何在这一批选择 role 或省略工具。

逐项排除用户列出的候选点：`_cover_dropped_clauses` 的职责原句已被接受事实引用，不会因 nearest-owner 优先级变成 role；`company_description_fact` 只在工作/实习调用，不处理这个项目；该口述项目没有标签/编号 span，日期继续走自由文本分支；日期恢复和端点过滤只处理日期，不会删除接口职责。四个相关模块回到 HEAD 后仍复现同样失效，故保留本批 A/B 的主体、合并和日期修复。

### 外科手术式修改

- `backend/app/agents/fact_extractor.py`：仅对项目中误标 `field=role`、以「（我/本人）（主要/仅/只）负责……」开头的具体职责，清掉 field 并改为 action。保留内容、原引文、来源和 ID；「后端开发负责人」「接口开发成员」等职务仍是 role。
- `backend/app/services/experience_dates.py`：日期已唯一归属并恢复到字段后，从普通事实中移走与本条起止时间一致的独立日期子句；「日期，3 人组队」保留为「3 人组队」，带课程前缀的版本保留「课程项目，3 人组队」。原 source_quote/来源不改；内嵌日期的实际动作仍保留，其他日期与多日期歧义不扩大处理。
- 不改 writer、检查口径、fixtures、历史回放或第十批其他归属/合并逻辑。

### 验证

`tests/test_batch10_regressions.py` 新增 4 项测试：误标职责恢复正文及项目/实习隔离；两种复合日期事实保留团队和原引文；完整 tech 首轮原文经抽取、事实应用、初稿投影、writer 后含接口、工具和团队/登录/演示限制；真正职务仍保留 role。writer 测试同时覆盖普通 action、误标 role 和只写背景的稀疏输出。原 A/B、10b 日期动作保护及公司描述断言全部保留。

- 修复前先运行新增测试，4 项中 3 项失败（含子用例共 5 个失败），复现接口丢失和日期残片；职务保护用例通过。日志 `/private/tmp/huhua-10c-red.log`。
- 最终定向：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py -k Batch10`，**25/25 通过，0.222s**；日志 `/private/tmp/huhua-10c-targeted.log`。
- 指定全量：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`，**1613/1613 通过，0 失败、0 跳过，60.913s，退出码 0**；日志 `/private/tmp/huhua-10c-full.log`。
- 三版本离线对照：`/private/tmp/huhua-10c-compare.py`，结果 `/private/tmp/huhua-10c-causality.log`。使用桩 LLM，未接触真实服务。
- 本次 3 份 Python 文件 Ruff、`git diff --check` 通过；107 份受保护文件（checks.py、fixtures、上述历史回放和既有网页改动）SHA-256 未变。

保留第十批 + 10b 及其他未提交改动；只新增两处运行时代码修复、4 项测试和本次文档。未启动或调用 8833，未调用真实 LLM，未 commit、部署；真实模型回放的 3/3 失败是否已恢复，仍待后续真实复测，本次不将桩测试表述为真实回放通过。
