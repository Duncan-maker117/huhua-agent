# 第十四批 c4：c3 真实回放后的离线修复

工作树 `huhua-b14` / `batch14`，接手 HEAD `b4bebd0`，保留已有 c3 未提交改动。本批未 commit、push、部署，未启动或调用 8833/8834，未调用真实模型。`runs/after-b14c2/` 和 `runs/after-b14c3/` 只读。

## 1. aipm_real 方向与收集阶段

**根因与证据**

- `_looks_like_role_direction` 对 `AI产品` 做大小写敏感的字面匹配；真实第 2 条的 `ai产品相关工作` 不命中。下游 `role_profile` 原本就能识别大小写/空格，问题在前面的分支入口。
- `intake_update` 在检查经历前先要求 `target_known`；即使第 4 条已抽到项目，仍留在 `target`，既不出经历卡，也不允许深挖问题卡。
- c3 的旧图回归在第 2 轮直接由分诊桩返回 `SKIP_JD_OK + AI产品`，掩盖了确定性入口缺口。本批新桩故意不提供这个帮助。
- 原产物第 4–10 轮为 `target`；第 11 轮“直接写”其实进入了 EVALUATING，但仍是待补名称项目，不是有效的命名成稿。不能表述为底层 writer 从未运行。

**修复**

- 岗位关键词忽略大小写与空格，支持“做AI产品”“想做ai产品”“AI 产品经理”等，映射 `ai_pm` / `ai-pm.md`。按本批要求，对话中“想投产品”这样的产品简称也选 AI 产品手册；保存的原方向仍为用户原话，不制造 JD 或本人事实。完整“产品经理”及招聘 JD 的既有通用岗位分类不变。
- 有经历即允许 `experiences → deepen`，未知方向不阻塞；预填卡保留 item_id 和项目简介，占位项目名显示为空待填。模型上下文仅允许在正文顺带问一次方向，已问过则不再追问。
- aipm/aipm_real 无卡轮次用 `latest_followup + question_dimension` 识别正文问题，从各自独立答案库返回自由文本；未知答“不知道”，不再无条件发“继续”。自由答案与 unknown 关闭记录也进入各自答案审计；原五人物检查不变。

**回归**

`tests/fixtures/batch14c4-replay.json` 的真实人物部分只取 c3 前四轮输入。`Batch14c4RealGraphTests` 运行真实图/流式/卡片/事实/writer 桩：第 2 轮识别 ai_pm，第 4 轮出现预填经历卡且名称为空，第 5 轮进入 deepen/ask_user，最终 11/11。另测未知方向且已有经历、问方向只一次、自由答题/unknown/独立答案库。

## 2. ops 原话清单

**根因与证据**

- `after-b14c3/ops/02-followup.json`、`03-polish.json` 的 `writer_diagnostic` 都是 `model_fallback / EmptyWriterDraft`，`schema_retry_count=0`，`ignored_extra_fields=[item_id, section, title, bullets]`，`fallback_action=preserved_existing_draft`；不是正常 writer 成稿。小巷咖啡四条正文与 initial 收集预览逐字相同，正文元数据 `bullets={}`，两轮 revision 相同。
- 宽容 schema 会把错误放在 WriterDraft 根层的 WrittenItem 字段全丢掉，产生合法的空 `items`，绕过结构重试。可见旧稿就保留的 fallback 又把收集预览当成已成稿，因此新数字和改写没进正文。
- `_serialize_to_resume_data._active_item` 只做缺失信息清洗，没有排除纯职责/数据约束，所以“不是账号负责人”从第一轮就进入预览。
- 对照桩给出上述四个根字段：旧 c3 schema → `items=[]`；c4 → ValidationError → 原有一次结构修复重试。产物没有原始模型响应，因此只能确认该响应形状与诊断完全一致，不能声称取回了那次原始响应，也不能证明是 c3 的新增标签说明导致模型输出错误形状。c3 新增的是 schema 描述，不是更严的字段枚举或校验。

**修复**

- 严格/宽容 WriterDraft 在丢弃额外字段之前检查这种层级错误；首次失败重试，连续失败沿用主写作错误路径，不把事实原文冒充写作成功。
- 明确 COLLECTING 且无 writer 正文元数据的预览，不进入“保留已有成稿”分支；空稿的确定性 fallback 使用当前事实并清洗正文。保留旧编辑器/导入稿的兼容路径，不能仅凭无引用就判断它们是预览。
- 预览和限定清理共用纯约束过滤；负责人/后台权限/数据缺失等不进入正文，事实层仍保留以约束所有权。带动作的“按店长给的文案制作4张海报”保留；测试环境/未做线上压测按用户明确要求继续保留。

**回归**

错误根结构→重试成功、连续错误→抛错且旧稿不变、空 writer 不恢复旧预览、真实 ops initial/followup/polish 输入经抽取/writer/局部润色后 13/13；核对 8/3/6/2/4 数量、约束不进入正文、事实未被过滤器修改、目标外栏目不变。

## 3. tech 指标删除与部署重复

**根因与证据**

- c3 `02-polish.json` 的指标仍为完整的“在测试环境…420ms…170ms…没做线上压测”。到 `03-correction.json` 才整句消失，该轮诊断是 `not_called / literal_correction`，没有 writer 调用。`fact_coverage` 仍有更正后的 190ms 事实。
- `profile_bridge.sanitize_fact_history` 对 inactive 事实的 text/source_quote 使用 ≥0.85 的整句相似度删除旧正文。它只豁免与 replacement.text **整句相等**的正文；正确的 190ms 事实作为长句中的一个子句时，仍可能被旧的 170ms 引文近似命中而删除。
- 对照桩使用 c3 的精确 polish 正文/引用/coverage、真实 correction 输入；由于原始 extractor 引文没有保存，source_quote 仅按已提供 initial 输入中的指标原句重建。修复前稳定复现三条→两条，修复后保留三条及新的 hash/引用。这个函数在 c3 没有改过，c2/HEAD 的同一函数也能复现。故不能归因于 c3 的标签分类、选材优先级或 labeled 合并逻辑；该轮计划本身也是 `plain`。
- c2 指标与“编写12条接口测试”合在一行，c3 指标单独成行，覆盖记录中的指标事实文本也不同；这说明触发形状不同，但没有完整中间状态时不能断言真实模型为何改变形状。
- `preserve_item_limits` 把“部署在实验室服务器，只给班里演示”作为一个限定整体检查；已有“部署于实验室服务器并面向班级演示”没被认为覆盖，因缺少“只”而把完整地点+对象重复追加。旧函数对照桩精确复现该重复，函数也未在 c3 修改。
- `other_numbers` 中 polish 的 420 是合法的优化前基线，应该保留；失败原因是 correction 把它随整句删除，并非 polish 多出了未经授权的“420残留”。

**修复**

- 清理旧事实时，允许正文包含完整的 active replacement 子句；同时要求旧值不在该子句之外残留。数字按完整数值比较，避免把 170→190 的差异当成单个“7”，误删同句独立的 17/1700 条测试。只换引用仍留170、同句同时存在170和190、撤回的历史版本，仍继续清理。
- 限定按地点/对象分别判定已覆盖，缺少“仅”时在已有班级演示短语上补足边界，不追加已表达的地点和对象。重复调用保持幂等，更新引用/hash。

**回归**

精确 c3 polish → correction → 持久化 sanitizer、旧值/新旧并存的负例、图节点成功回执与实际正文一致、目标外项目不变；原 tech 17 条检查全过。部署补回单独验证地点一次、演示一次、“仅”保留、第二次调用不变及 hash 一致。

## 4. aipm 孤立冒号

**根因边界与证据**

`05-plan_confirm.json` 的第一条 `polished_bullets` 确实以 `：面向学生的 AI 简历助手` 开头。`format_rows` 本来只有 label 非空才拼接冒号，但不会清掉上游已存在的孤立冒号。没有原始 writer/repair 分阶段响应，无法确认标签最早在哪一步丢失，不能说“空 row_label 被直接拼成冒号”已获证明。对照桩将该形状送入旧格式化器，孤立冒号原样通过；新格式化器移除它。

**修复与回归**

先剥离已识别标签及前导孤立冒号，再根据事实分类。有明确痛点则补“问题”，只有产品定位则无标签输出，不凭空补痛点。覆盖中文/英文冒号、前导空格、原标签与事实不匹配、plain/labeled，引用不变；writer 后续生成正文 hash，保留既有端到端 hash 回归。

## 验证与交接

最终代码验证结果（2026-10-17）：

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 指定 Python / 指定全量命令 | **1808 项：1806 通过 + 2 原有跳过；0 失败**，64.518 秒 | `full-final-verified.log` |
| 第十四批定向 | **110/110**，含本批 17 项 | `b14-final-code.log` |
| 五人物离线回放 | **71/71**，14 请求 | `five-persona/run.json` |
| ops / tech 针对性桩 | **13/13、17/17** | `ops-stub.json`、`tech-correction-stub.json` |
| aipm / aipm_real 图与 writer 桩 | **9/9、11/11** | `/private/tmp/huhua-b14c-aipm-stub.json`、`aipm-real-stub.json` |
| 静态与完整性 | 22 个 Python 文件 AST/Ruff 通过；`git diff --check` 通过；244 个受保护文件 SHA 不变；aipm 原答案常量不变 | `ruff-final.log`、`integrity.json` |

以上未写绝对路径的日志/产物均在 `/private/tmp/huhua-b14c4/`。最终 HEAD 仍为 `b4bebd0`，分支仍为 `batch14`。复现命令：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py -k batch14
```

- 本批新增 `tests/test_batch14c4_replay.py` 17 项；fixture 记录来源与重建边界。独立数字边界使用单独的合成反例，不改写冻结的真实人物输入。
- 旧断言仅两处因明确行为变化调整：`test_batch11_comparison_case` 不再要求“不是负责人”留在预览，而要求事实保留、正文没有；`test_followup_answer_binding` 允许已有经历时出现 intake_experiences，仍禁止从正文自动制造问题卡。其他旧断言不放宽。
- 首次全量发现过滤器误删句末标点，已修为未命中时逐字保留；后续全量发现过宽预览判断影响旧编辑器技能分组，已收紧为明确 COLLECTING。未通过改旧业务断言掩盖这两项实现问题。
- 五人物 **71/71** 为原有 socketpair HTTP/SSE golden 响应回放，14 请求、无 TCP；它验证传输/检查器，不证明真实模型质量。本批另补 ops 13/13 抽取/writer/局部润色链路、tech 17/17 冻结状态更正链路，以及 aipm/aipm_real 图与 writer 桩检查。它们各自的证据范围见测试及产物 `evidence` 字段。
- 本地证据目录：`/private/tmp/huhua-b14c4/`，包括 `root-cause.json`、`root-cause.log`、`ops-stub.json`、`tech-correction-stub.json`、`aipm-real-stub.json`、`five-persona/run.json` 和测试日志。真实模型、正式服务、浏览器视觉、线上结果未重测。
