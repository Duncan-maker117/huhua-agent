# 胡话简历交接

## North star

让秋招求职者把真实经历快速变成一份针对目标岗位、可以核对并直接投递的简历。

## 当前决策

- **2026-10-08 最新授权：按规格 §8/§10 顺序继续 Tailor overhaul。PR1 已合入 `fcfef05`；PR2 岗位画像与方向识别已提交 `066e0ba`（601/601）。real-01 私有基准支持已提交 `d0ef0b6`，真实材料/结果只在 cases-private、runs-private；旧 218 份 run 文件哈希未变。PR3 事实母版、存储边界、导入与隐藏输出已完成，全量677/677（含9项PR4独立组件）；PR4/5 随后推进，PR6 按规格交 Cursor。使用 DeepSeek V4.1 Flash 实测授权保留。未 push、未部署、未迁移真实库。**

- **2026-10-08 Banz 根据「制作个人简历网站」实测反馈授权优化核心流程。已完成本地完整资料直接成稿、生成指令/新事实不丢失、保存后确认及失败历史提示、自动分条不漏原句、模板偏好恢复和真实 PDF 下载。当前优先验收/发布这条流程；专业能力研究仍未另行接入。**

- **2026-10-06 旧功能清理：Banz 明确要求删除不再使用的功能和文件。已按运行时引用清理旧 Orchestrator/Wrapper/Evaluator、对应 schema/提示词、无引用的旧 User schema 及 golden_resumes 示例库，同时移除启动和打包引用。现用 LangGraph、三项 Skill、联网工具、档案归档及可选 JD 术语检索保留；专业能力研究方案仍未接入运行时。**
- **2026-10-06 研究范围补充：Banz 明确要求研究整份简历的直观呈现、内容重要性/删减，以及项目异常和特殊情况。已补充 `research/resume-expertise-2026-10-06/content-priority.md` 和 `failure-recovery.md`，含 10 类求职情况与 18 类异常矩阵。只读代码审计识别空文本 PDF 误报成功、多附件长度预算不一致/失败不恢复附件、未知采用结果、401 接续和保存悬挂等缺口；未执行测试、未改业务代码或部署。固定栏目权重不作为默认方案，采用岗位/阶段/证据条件化取舍的研究方向。**
- **2026-10-06 新一轮讨论：Banz 指出建议过长、价值不足、采用时找不到依据，要求先探讨；随后提出收集可信求职资料并蒸馏成 Agent 内置能力。已完成只读诊断和首批资料研究，见 `research/resume-expertise-2026-10-06/README.md` 与 8 张草案规则卡。拟用现有 Skill、按场景选卡、整稿编辑计划及盲评；尚未确认最终方案、接入运行时或部署。不得把资料来源可靠等同于方法已验证。**
- **最新反馈 2026-10-06：修复多附件导入遗漏、僵硬快捷追问及公开仓库链接不能读取。用户明确要求查看公开主页/仓库，范围扩为“本轮明确查看意图 + 单个公开URL”自动选择一次受限读取，仍不引入自主浏览循环。多附件逐份解析、同名去重，冲突保留原来源；当前问题优先，开放问题不强套选项。已发布为 `20261006-4`，见当前状态及工具说明。**
- **最新工作边界 2026-10-06：Banz 审阅开发文档后以“你开始吧”授权实施推荐的首期方案。继续显式单次工具调用、读链接更新当前 JD、搜索只做参考、游客共享尝试次数；不扩展自动工具选择或预览采用。本轮已补齐材料范围/额度/来源归属提示与受控验收，必要增量已发布。Tavily 已于本日按用户授权写入受限运行配置，真实搜索已开通；任何文档/记忆均不保存其值。方案为 `docs/development/2026-10-06-agent-tools-development-plan.md`。**
- Banz 于 2026-10-06 确认增加联网工具：单个招聘链接读取后解码 JD，独立公司/岗位词按需搜索并对照当前经历。首期每轮一次显式工具调用；外部网页始终是 JD/reference，不归档为本人事实，搜索分析不自动改稿。搜索凭证只放服务端。
- Banz 于 2026-10-05 明确改为“先体验、后登录”：首次进入即可聊天、上传、生成/修改当前简历、浏览模板；导出、长期历史与 Agent 跨对话记忆才要求登录。登录必须接续刚聊好的当前会话，不刷新丢失输入。游客用独立临时凭证，默认闲置 24 小时清理；没有长期档案，历史目录需账号。
- Banz 于 2026-10-05 要求先写审视报告再编写代码，随后明确授权部署到 `resume.yikuaibanz.cn` 供朋友测试。源码修复已部署为服务器全新加密安装；未迁移本机旧数据，也未发送测试邮件。站点、HTTPS 与正式发信域配置完成，朋友登录仍需真实收件与端到端验收。
- 一号一人，一个账号维护本人唯一主档案。个人事实、长期偏好、岗位/简历版本分开；姓名及联系方式是个人事实，不是独立记忆 Agent。
- 明确、无冲突的本人信息自动归档；保留来源和时间，重复提及不提高真实性。明确更正替代旧值，无法判断的冲突交给用户；不把 JD、参考简历、AI 建议变成本人事实。
- 事实可信和导出一致优先，不补估算数字、职责或成果。建议先核对再采用；改当前稿措辞不自动改全局档案。
- 右侧四页分别呈现 JD、经历、简历、核对，编辑与下载集中在「写简历」；左侧简短反馈、建议和具体补问。点选快捷回答即发送完整句，同组防连点，保留输入草稿与附件。
- 服务端需要处理明文，因此是加密存储与受控解密，不是端到端加密。姓名/经历按任务需要发模型，常规文本邮箱/电话先脱敏；图片识别仍发原图。
- 登录后资料默认保留至手动删除；游客按上述临时保留期处理。档案删除阻止未来使用，原聊天删除独立处理；最小旧值排除资料加密保留以阻止旧副本复活。恢复需独立最新隐私状态与可信摘要。

## 当前状态

2026-10-14 追问目标范围修复（基于 `overhaul/tailor` / `208bd45`，未提交）：

- `fact_extractor.py` 原名称追问仅看上一轮问句，普通追问主要排除显式换题，课程隔离又只覆盖 campus/open_source。改为校验名称答案、逐条原文判别主体，课程/校园/个人练习先独立归属，拒绝模型的错误 section/ID；无法确定的答非所问内容留 raw_notes。原有歧义名称、失效目标、数字与语义校验保留。课程作业保留独立项目和状态；明确「公司里用 PS 做产品图」仍可归工作。
- 工具能力声明复用 `candidate_skills.py` 别名与使用级别，只入 skills；具体工具交付同时保留经历事实。`candidate_language._NON_FACT` 在抽取、逐句补漏和收集兜底中生效，裁掉自评前缀的模型引用也不能冒充完成事实。
- `resume_graph.py` 原收集末尾无条件追加占位名问题，并可能再追加教育问题。现在内容追问优先，新事实轮次延后命名，名称每条只问一次，按学校名称/公司名称和岗位/组织名称区分。公开回复保留实时输出，第一个问题之后剔除多余问题；末尾追加也不叠问且保留消息 ID。
- **ValueError 证据边界**：用自编第四轮状态在原 HEAD 复现：普通公开回复时海报错挂工作；公开模型桩返回空内容时，`collecting_node → _collection_reply → public_reply.py:98` 明确抛 `ValueError("Empty public reply")`，日志顺序与描述一致。改为专用异常，仅收集引导空回复走保留已抽取事实的兜底，不吞其他 ValueError。`APP_ENV=local` 的 stream error 额外 debug 堆栈；生产维持错误码/类型日志。原线上无堆栈，不能据此唯一确认那一次异常；未查私有材料、未跑真实模型。

验证：新增 `tests/test_followup_target_scope.py` 15 项，包括无 ID/错 section/强绑目标、多轮归属、技能双归、自评裁剪、名称拒答、明确公司设计、课程否定、漏抽课程/海报、第四轮空回复和 local/production 日志。既有测试只调整一条分栏命名文案断言、一处公开回复桩参数。安全源码副本执行 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`：**1462 项，1460 通过、2 项私有样例跳过、0 失败，48.981s**；日志 `/private/tmp/huhua-scope-accepted.log`。8 份改动 Python 源码与测试副本 SHA-256 一致，AST/差异检查通过，Ruff 仅有 HEAD 已存在的 `resume_graph.py:188 E402`。

改动：`backend/app/agents/{fact_extractor,public_reply,resume_graph}.py`、`backend/app/services/{candidate_language,candidate_skills}.py`、`tests/{test_followup_target_scope,test_campus_and_naming,test_replay_polish_regressions}.py`、本交接。测试在排除私有目录、实际配置/凭证及运行数据的源码副本 `/private/tmp/huhua-scope-safe-7i659kz6` 执行；原 HEAD 复现日志 `/private/tmp/huhua-scope-baseline.log`。未 commit/push/部署，未改已有真实事实数据；词法主体判断对隐含换题仍保守留待确认。

2026-10-14 六项成稿保真修复（基于 `overhaul/tailor` / `8cf646c`，未提交）：

- **事实覆盖**：原 `resume_writer.py` 的默认 2 条、按 fact_id 相同/子集去重、0.6 n-gram 去重及单事实回退，会丢掉不同职责；原补漏只针对量化事实。改为按实际文字覆盖判断重复，完整表述可合并较短同义表述并保留引用；新增 `services/fact_coverage.py` 对每条 active 事实记录 covered/omitted、原文与原因。缺少明确方案限制时确定性补回，明确方案/条数限制时保留备用并在回复逐项说明。`tailor_pipeline.py` 对最终压缩稿和失败保留稿再次审计，覆盖结果存入 resume_meta.fact_coverage；advisor 是只读检查，不是删改入口。
- **课程归属**：`fact_extractor.py` 的追问、模型显式校园 ID 与同句归属原本都没有课程主体隔离。现在无协会信号的课程/作业转入独立 projects，名称取原文；同时覆盖错 ID、无 ID、片段事实及模型完全漏项，保留已有协会事实。
- **教育字段**：原 field 直接保存模型 text，结构 schema/渲染不剥前后缀。新增 `education_fields.py`，抽取、旧事实规范化、canonical 读取、ResumeData 校验与共用渲染均幂等清洗学校/专业/学历/起止日期，原始 source_quote 保留。
- **工作标题**：原共享默认标题固定为实习经历，internship 合并时没有类型。现在保留 employment_type，结合毕业后正式工作/全职信号判定；仅实习用实习经历，全职或混合用工作经历，其他自定义标题保留。
- **技能**：原精确名称检查不认别名，writer 补录词表偏技术，其他类上限 3 项会截断明确技能。新增确定性工具声明与别名表；PS/设计同句的 AI 映射 Illustrator，单独 AI 不映射；Exce/pptl 纠正，保留会用/用过等原级别；设计工具/AI 工具/办公软件/其他分组，所有来源明确的技能不受展示数量上限截断。编造技能与升级熟练度仍拒绝，已收录技能声明不误报成丢失经历。
- **登录样例 409**：`api/resume.py` 两边原本已有 ResumeData 校验，实际差异是前端生成 sections。双方同样忽略该派生字段比较，匹配后只渲染服务端样例；修改个人正文或任意无会话内容仍 409。

验证：新增 `test_fidelity_followup.py` 12 项虚构同构回归及登录样例 1 项；桩模型覆盖漏行政、过度引用全部 ID、错挂协会、漏工具、虚构技能/熟练度等。按新的事实保留/分组规则调整 4 份旧断言。安全源码副本 `/private/tmp/huhua-fidelity-safe-3vjkphgz` 执行 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`：**1447 项，1445 通过、2 项私有样例跳过、0 失败，103.015s**；日志 `/private/tmp/huhua-fidelity-final.log`。22 份 Python 源码 AST 与差异检查通过；Ruff 对比 HEAD 相同的 4 项既有问题、无新增。未调用真实 LLM，未读取实际凭证或访问实际 cases-private/、runs-private/、data/output/；未 commit/push/部署。

本轮改动文件（新增以“新”标注）：
- `backend/app/agents/`：fact_extractor.py、resume_graph.py、resume_writer.py、tailor_pipeline.py、turn_actions.py。
- `backend/app/api/resume.py`；`backend/app/schemas/editor.py`。
- `backend/app/services/`：candidate_language.py、candidate_skills.py（新）、canonical_resume.py、education_fields.py（新）、fact_coverage.py（新）、fact_guard.py、resume_facts.py、resume_sections.py、skill_groups.py。
- `tests/`：test_fidelity_followup.py（新）、test_conversation_rebuild.py、test_resume_live_updates.py、test_resume_provenance.py、test_tailor_pr5_gate.py、test_writer_repair_context.py；交接 `mmr.md`。

边界：本轮依据公开源码与自编虚构数据定位，没有读取真实 19 轮材料，不能判定原回放中究竟哪次模型输出先触发了丢失。词法覆盖对跨度较大的同义改写可能保守补回原文或列为备用；明确方案/篇幅约束下仍可能不展示全部事实，但必须逐项回执。真实模型润色与真实浏览器样例体验未实测，API/模板与离线桩验证已通过。

2026-10-14 校园经历、名称与非技术用户成稿修复（未提交）：在 `overhaul/tailor` 保留上一轮追问归属与编辑器预览改动。新经历名称不在原文时仅降级名称，已校验事实保留；明确组织名称按原文提取，否则分栏待补。复用 followup_target 追问一次名称，后续无 item_id 的命名回答更新原条目；投递渲染只在名称处显示 `[待补]`，描述性占位不进入正文。

根因与修复：`fact_extractor.py:349` 分离名称/事实准入；`resume_graph.py:406` 原宽泛项目名截取改为明确命名结构；`turn_actions.py:60` 关闭社团句教育解析及「读者」误命中；`candidate_language.py:25` 统一求职意向短岗位名约束，迷茫原话可存 metadata_context，明确逐字改意向逻辑保留；`resume_graph.py:1082` 修复「部分这轮」组合；`turn_actions.py:247` 无团队语义时不产生 pending_ownership；`resume_writer.py:33/82/1360` 增加校园和奖项正文改写，实习继续归并 work_experience，生成/兜底去第一人称与口语、去重、过滤自评/提问/计划，角色归标题，保留事实及语义核验。

`campus` 已贯通 FACT_SECTIONS/FACT_FIELDS、抽取与归档 prompt、ResumeData/WriterDraft、writer/section_order、7 款 HTML 模板共用 macro、Word/纯文本/PDF 渲染入口、编辑器/工作区/档案 UI、canonical 存取、档案投影与撤销屏障、MCP schema/输出、版本/容量/路由/编辑与追问。旧数据缺字段按空处理；不迁移既有真实用户数据。web 仅栏目配置/字段入口，没有新增 Tailwind 类，未动预览机制。

验证：新 `tests/test_campus_and_naming.py` 17 项（含 `campus_editor.dom.js`），使用虚构逐轮状态、错名/缺 ID/错 open_source 栏/原话回贴/异常 writer 桩；包括数字短答归属、改名不新建、技术项目不因服务协会而误归校园、虚构数字/独立设计拒绝、HTML/Word、档案投影、回执及 DOM。排除私有目录、运行数据与配置的源码副本 `/private/tmp/huhua-campus-safe-24ml1ey7` 执行 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`：**1434 项，1432 通过、2 项私有样例自动跳过、0 失败（135.146s）**；日志 `/private/tmp/huhua-campus-final.log`。57 份已测源码与工作区哈希一致；JS 语法、差异检查通过，Ruff 无新增问题（8 项既有问题原样保留）。未调用真实 LLM，未访问实际私有目录或凭证，未 commit/push/部署；真实模型润色质量未实测。名称提取保持保守，无法确定的名称仍待用户补充。

本轮改动文件清单（相对仓库根，上一轮 `public_reply.py` 与 `test_followup_answer_binding.py` 保持）：
- `backend/app/agents/`：advisor.py、fact_extractor.py、interviewer.py、profile_archivist.py、resume_graph.py、resume_writer.py、router.py、tailor_pipeline.py、turn_actions.py、wording_advice.py。
- `backend/app/schemas/`：editor.py、facts.py、writer.py。
- `backend/app/services/`：新增 candidate_language.py；candidate_material.py、candidate_sections.py、canonical_resume.py、conversation_store.py、edit_plan.py、mcp_service.py、named_content.py、profile_bridge.py、profile_service.py、renderer.py、resume_capacity.py、resume_facts.py、resume_limits.py、resume_provenance.py、resume_review.py、resume_sections.py、resume_versions.py、resume_workspace.py、session_store.py、structure_plan.py。
- `backend/app/tools/resume_data_docx.py`；`data/jianlimoban/html-template/`：_macros.html.j2、t001-jianyue.html.j2、t002-jianyue.html.j2、t003-shenlan.html.j2、t004-jianyue.html.j2、t1000.html.j2、t1001.html.j2、t1002-jianyue.html.j2。
- `web/`：resume-editor.js、resume-workspace.js、account-profile.js、change-card.js。
- `tests/`：新增 test_campus_and_naming.py、campus_editor.dom.js；更新 test_complete_resume_task.py、test_resume_sections.py、test_structure_plan.py、test_tailor_pr5_gate.py、test_writer_repair_context.py、test_writer_schema_structure.py 中因新增栏目/去第一人称而变化的断言。交接：本 mmr.md。

2026-10-14 追问短答归属修复（未提交）：核实无 item_id 且经历名未出现在本轮原话时会整条拒收、逐句兜底只看同句归属、拒收回执被当作当前问题、旧核对提示不会清理，均在后端链路，与登录无关。收集回复没有通用 focus；现在优先使用 interviewer 已知且唯一的目标，其次问题点名或「需要你补充」当轮唯一新增事实所在经历，在 collected 保存 `followup_target={item_id,section,asked_hash}`。下一轮抽取前核对上一轮实际问题 hash，消费后清除；后续追问重新确定目标，同一问题重问可续用，历史重放不消费当前目标。名称规范化唯一匹配可恢复已有 ID；无名称匹配时和逐句兜底可使用有效追问目标；多义名称、跨经历、新经历及失效目标不猜。prompt 带目标名称及 ID，原有数字/职责/语义校验保持。

有拒收子句的收集回复先校正回执再公开输出：有已记录事实说「部分已记下」，全未记录不声称成功；正常回复继续流式。工作区合并同轮回复并忽略拒收/未说完提示。旧拒收核对提示由 active source_quote 覆盖时清理；换说法仅在同一目标上一轮有拒收、本轮确实新增事实且没有新的 uncovered 时清理上一轮提示。草稿合并及核对页阻止旧拒收提示复活，保留其他核对信息及手动删除结果。历史无目标元数据且不能被原文覆盖的同义旧提示仍保守保留；没有真实 LLM 或线上验证。

本轮文件：`backend/app/agents/{fact_extractor,resume_graph,public_reply}.py`、`backend/app/services/resume_workspace.py`、`tests/test_followup_answer_binding.py`（17 项回归）及本交接。排除私有目录、运行数据与凭证的源码副本 `/private/tmp/huhua-followup-safe-ocde7um5` 执行指定 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`：**1417 项，1415 通过、2 项私有样例自动跳过、0 失败（56.158s）**；日志 `/private/tmp/huhua-followup-tests-final.log`。包含并保留并行模板预览测试，相关源码快照无漂移；修改文件 Ruff（忽略既有 E402）及差异检查通过。未修改 `web/`，未访问 cases-private/、runs-private/、data/output/ 或凭证；仅假 LLM/桩测试，未 commit/push/部署。

2026-10-14 模板预览提速（未提交）：编辑器与主页面共用新增 `web/template-preview.js`，按当前 revision 在内存缓存各模板 HTML，悬停 / 聚焦 80ms 预取，当前预览完成后 idle 串行预取（总在途上限 2，正式请求复用预取 Promise）。输入沿用 180ms 防抖，revision / 返回布局 / 账号 / 会话变化中止旧任务并清缓存；会话重置清空两个 iframe。保留旧预览至后台 iframe load、字体 ready（300ms 等待兜底）与缩放完成，再原子交换可见性、固定 ID 和可访问性属性。加载消息以 source + 独立序号验证，另有 revision / request / template / session 校验；字段交互、高度报告、Escape 始终只接收可见 iframe。主页面 sandbox 仅增加 allow-scripts，用于前端注入就绪桥接，仍无 allow-same-origin。performance mark / measure 使用 `huhua-template-switch`，只记录最新有效切换，不输出控制台。

新增 11 项 DOM 回归，扩充已有模板竞态用例，覆盖缓存 / 在途复用 / 失效 / 快速选择 / 旧加载消息 / 字体兜底 / 交互与缩放 / 并发 / 错误重试 / 重置。最终源码隔离副本 `/private/tmp/huhua-tpl-safe-ibj_s7ls`（排除私有目录、输出、真实库与凭证）执行指定全量命令：**1400 项，1398 通过、2 项私有样例自动跳过、0 失败（50.160s）**；日志 `/private/tmp/huhua-tpl-tests-final.log`。JS / HTML 内联脚本语法、差异检查通过；脚本与编辑器 CSS 版本更新为 `20261014-tpl1`，未新增 Tailwind 类。模板、后端渲染、PDF / Word 导出未修改；未 commit / push / 部署。浏览器回归首次等待超时，随后 Chrome / daemon 与本地测试服务器启动受沙箱权限阻断，故未完成视觉及真实耗时验收；缓存热切换仍需 iframe 解析 / 字体 / 排版，不能宣称实测 <100ms。

2026-10-14 前端重复操作修复（未提交）：档案「改名」「保存当前岗位版本」「补充一条信息」复用同一位置的已有表单并聚焦，岗位按钮同步 aria-expanded；保留既有 mutate / MCP 令牌及收件箱行为。检查简历从读取当前稿到模型请求结束保持锁定，失败或切换会话不触发检查；被新修改淘汰的撤销按钮在旧请求失败后保持禁用。编辑器保存重试、导出选项及重试、新建草稿按钮补齐请求期间禁用与结束恢复；精细编辑支持 Escape，先关闭内层菜单或走既有保存再关闭，保存失败保留编辑器，预览 iframe 转发 Escape。更新相关 JS 缓存版本，未改样式或 Tailwind 类。

排查全部 `web/*.js` 与两份 HTML 的内联脚本；持续节点监听仅初始化绑定，未发现重渲染重复绑定，已有历史对话 / 联网 / MCP 请求保护保留。新增 `tests/frontend_reentrancy.dom.js` 与 `tests/test_frontend_reentrancy.py` 共 12 项 DOM 回归；既有档案、MCP、内嵌编辑器 DOM 验证通过，令牌及收件箱函数与本轮开始时逐字一致。排除私有目录、输出、真实数据库和凭证的临时源码副本 `/private/tmp/huhua-ui-safe-wnm8sw8v` 执行指定全量命令：**1389 项，1387 通过、2 项私有样例自动跳过、0 失败（48.975s）**。全前端 JS / HTML 内联脚本语法与差异检查通过；日志 `/private/tmp/huhua-ui-tests-final.log`。原有未提交改动保留，未 commit / push / 部署；未做真实账号或浏览器端到端验收。

2026-10-14 MCP 实机验收反馈修复（未提交）：save / export 从当前账号 active basic 档案解密，复用既有 `context_to_collected_info` 链接投影和 `protect_data`，覆盖客户端姓名 / 电话 / 邮箱 / 个人链接，档案缺项留空；PDF / DOCX 及网页草稿始终包含档案已确认联系方式。无 `profile:contacts` 的工具返回及 fact_check 回显仍隐藏联系方式，标志改为 `contacts_filled_by_server: true`，工具描述明确服务端填入、不返回助手。按 conversation_id 导出使用服务端原稿后再填充。连接面板有效期 / 最后使用 / 最近调用按浏览器本地时区显示 `YYYY-MM-DD HH:mm`，调用缓存新增 UTC `called_at`，静态引用为 `20261014-mcp2`。

新增 2 项 MCP 协议回归并扩充既有 PDF / DOCX 实物测试、审计断言及上海 / 纽约时区 DOM 测试，覆盖无 contacts scope 文件有电话邮箱但返回无、假值覆盖、缺项清空、账号隔离、网页保存导出和按对话导出。排除私有目录 / 输出 / 数据库 / 凭证的临时源码副本 `/private/tmp/huhua-mcp2-safe-_ejvdr1s` 执行指定全量命令：**1377 项，1375 通过、2 项私有样例自动跳过、0 失败（44.441s）**；Ruff（忽略既有 E402）、JS 语法与差异检查通过。原有未提交改动保留；未读取指定私有目录、真实 key，未 commit / push / 部署；修复后的真实 Claude Code 复验未在本轮执行。

2026-10-14 MCP M1 + M2 本地完成：在 `overhaul/tailor` 增加 PAT / scopes / 限频、8 个 MCP 工具、资源与提示词模板、加密 AI 建议收件箱、Cookie 确认 API、一次性导出下载，以及网页“连接 AI 助手”和建议确认分组。核心边界：propose 只写收件箱；确认走既有 manual 来源和冲突 / 等价 / 撤销事务；save 只建带 mcp 标记的网页草稿，事实母版为空，不自动归档。新增两表由 create_all 创建，SCHEMA_VERSION 不变；固定 mcp==2.3.0，MCPServer session manager 随每次 lifespan 新建。

隔离源码副本执行指定全量命令：1375 项，1373 通过、2 项私有样例测试自动跳过、0 失败（45.073s）；新增 18 项真实 SDK Streamable HTTP / ASGI 协议测试和 2 项前端测试。Ruff、JS 语法、差异检查通过；最后补充模板适用说明后重新定向验证 MCP。未读取私有目录、输出或真实 key，无网络、真实账号 / 数据库操作、commit / push / 部署。当前注册表保留 7 模板；网页最近 50 次调用缓存及下载缓存重启清空，元数据审计另写服务日志。实机 Claude Code / Inspector、服务器 P95 与 Python 3.12 镜像运行仍待后续验收。完整文件清单、接口约定与启动 / 连接 / smoke 步骤见 `docs/development/2026-10-14-mcp-handoff.md`。

2026-10-13「档案等价判断」评审修复：仅调整 `profile_equivalence.py` 的技能拆分，熟练度要求明确边界且剥离后非空，逐行去掉 ≤8 字且不跨分隔符的分组标签，保护 A/B 测试/Test 的大小写与空格变体，中文连接词仅在至少一侧紧邻 ASCII 技能时拆分；保留熟练度继承及符号分隔行为。`tests/test_profile_equivalence.py` 新增8项回归，定向34/34（含原有迁移测试），旧数据迁移实现未改。为遵守禁读范围，在排除私有目录、输出及本地凭证的临时源码副本运行指定全量命令：1355项，1353通过、2项私有样例测试自动跳过、0失败（42.286s）；Ruff（忽略既有E402）及差异检查通过。未访问原仓库 cases-private/、runs-private/、data/output/ 或 key，未 commit/push/部署。后续须继续保留上一轮未提交改动。

2026-10-13「档案同一件事判断」本地完成：在 `overhaul/tailor` 将 skill 按账号内规范名称存为集合，槽位含 casefold/去空白/别名后的技能值，独立保留 proficiency；保护 C++、C#、F#、Node.js、Next.js、Vue.js、CI/CD、TCP/IP、.NET。重复只合并提及，熟练度变化复用 state_change 历史/通知/撤销；否定技能输入不新增正向事实、不执行删除。单项更正继续走原入口，防止改名后留下重复槽位；简历投影保持平铺并按规范值去重，模板和分组不变。

新增纯函数 `equivalent_value`：四位年份日期、精度与 planned/done 语气、学历别名、学校明确简称表及校区括注、其它短字段保守比较；数字（含正负号）、工具名、否定含义变化不合并。学校不使用宽泛子序列匹配；两位年份、解析失败及精度与语气各有增减的日期仍返回 different。等价补全以 refine 留历史且可撤销。读取档案时按账号、有效来源和 expected_revision 迁移旧技能与假冲突，关闭为 equivalent；旧技能行留加密快照并标 superseded，关联岗位引用标待同步；已删除技能不复活。补全引起修订变化时，其它真实冲突保持 pending 并对齐修订，避免从面板消失。

改动：`backend/app/services/{profile_service,profile_equivalence}.py`、`backend/scripts/replay_profile_equivalence.py`、`tests/test_profile_equivalence.py`、`tests/account_profile.dom.js`、`web/account-profile.js`、`web/{index,resume}.html`（脚本缓存版本）及本交接。新增 26 项虚构/临时加密库回归，含迁移幂等、并发更正保护、撤销、来源保留、删除屏障、投影去重和只读统计；DOM 覆盖熟练度正文/历史/通知。指定 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` 最终 **1347/1347（41.391s）**；修改 Python Ruff（忽略既有 E402）、JS 语法、档案 DOM、差异检查通过。

离线评估入口：在已有应用解密配置的环境执行 `.venv/bin/python backend/scripts/replay_profile_equivalence.py DB_PATH`，参数必须是待评估数据库副本。脚本使用应用 DataCrypto 解密与 SQLite `mode=ro`，不加载 `.env`、不初始化应用库，stdout 仅含计数/字段分类，失败只给 errors 计数；技能计数包含各状态行，另列 active 数量，预计拆分项数按每条事实内去重后求和。测试验证只读连接拒绝写入、文件哈希不变、输出无原文。本轮未在真实库执行回放或迁移，未查看凭证或进入指定私有目录，未 commit/push/部署；没有已知本地阻塞。

2026-10-13「历史对话标题」本地完成：保留 `overhaul/tailor` 既有提交与全部回放产物。标题仅由结构化状态确定性派生：`jd_info.company · job_title`（缺公司只用岗位）→ `basic_info.objective` / `role_direction` +「简历」→ 前两个经历名；无可用字段时不派生，首次寒暄/长材料均保持「新对话」。上限24字，拉丁词及常见连字符技术词保留完整，中文按字符边界截断。成功保存每轮后更新，标题来源 `title_source` 与上次自动值 `auto_title` 复用加密 `resume_state`；聊天/编辑保存均保留这两项，显式手动来源、自动值被手改或不符合旧首句规则的自定义标题不覆盖。列表对无来源且等于首条用户消息规范化前40字的旧标题按 checkpoint / 已提交状态回填一次，保留活动时间；失败不影响列表，缺失 checkpoint 不误标手动，允许后续重试。无需新增列或结构迁移，沿用 ORM 标题加密与 profile_bridge 隐私过滤。

改动：`backend/app/services/{conversation_store,session_store,canonical_resume}.py`、`backend/app/agents/resume_graph.py`、`backend/app/api/conversations.py`、`tests/test_conversations.py` 与本交接。新增10项虚构/fake回归，覆盖优先级/缺公司/方向/经历/寒暄/长度、逐轮更新、手动保护与两种保存、加密幂等回填/活动时间、失败隔离与缺 checkpoint 重试。指定 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` 最终 **1321/1321（39.754s）**；修改 Python 文件 Ruff（忽略测试原有 E402）及差异检查通过。无真实模型调用、key读取/打印、commit/push/部署或真实库迁移；没有已知本地阻塞。

2026-10-13「预览性能、模板可读性、档案分组与记忆更新」本地完成：在 `overhaul/tailor` 保留既有提交及全部回放产物。A：render/current/PDF/Word 读取已提交稿，不等聊天长锁；交互编辑预览仍对已提交快照校验未保存输入。聊天最终保存用独立线程、自建 DB Session，取消时等保存事务结束再释放写锁；编辑页已有测页线程保留并补回归。B：t004 个人定位移到页头下白底区；实际深底深字问题在 t002，已改浅色。7 模板定位标题/正文实测 CSS 对比度均≥4.5；聊天模板切换取消旧请求，两处预览均验证慢响应不会覆盖新模板。C：档案默认「已有信息」，按基本/教育/项目/工作实习/开源/荣誉/技能分组，同条目合卡；字段保留更正/删除/来源，整条目导入；「信息确认」按钮带待办数，列表默认收起，更正可取消；整理失败显示安全原因并可重试。D：叙述事实多值、字符二元组 Dice 阈值 0.82 去重并合并来源，数字/技术词/否定/归属变化不吞掉；状态明确推进自动更新、保留 history、面板通知可按修订撤销，旧输入不能覆盖新更正。多值更正支持 target_fact_id；旧叙述换说法冲突在档案读取时按行幂等关闭为 kept。复用加密 payload 和现有表，无结构迁移、无真实库读取迁移。

本轮改动文件：A `backend/app/api/resume.py`、`backend/app/agents/resume_graph.py`、`tests/test_resume_read_performance.py`；B `data/jianlimoban/html-template/{t002-jianyue,t004-jianyue}.html.j2`、`web/index.html`、`tests/test_template_summary_contrast.py`、`tests/template_switch.dom.js`、`tests/test_replay_layout_regressions.py`、`tests/resume_embedded.dom.js`（共享 DOM 夹具）；C `web/account-profile.{js,css}`、`web/resume.html`、`web/index.html`、`backend/app/services/profile_service.py`、`tests/account_profile.dom.js`、`tests/test_account_profile_panel.py`；D `backend/app/services/profile_service.py`、`backend/app/agents/profile_archivist.py`、`backend/app/api/profile.py`、`tests/test_profile_memory_rules.py`，复用 C 的通知 UI。仅普通 CSS，档案静态资源两页均更新为 `20261013-profile`。

验证：新增 21 项虚构/fake 回归；指定 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` **1311/1311（40.929s）**；修改 Python 文件 Ruff（忽略既有 E402）、JS 语法、DOM、差异检查通过。无真实模型调用、凭证读取/打印、commit/push/部署。没有已知本地功能阻塞；线上平均/最长耗时及真实浏览器视觉未实测，确定性去重不保证识别所有语义改写。下一步按新授权部署后核对并行聊天/预览日志与移动端档案交互。

2026-10-12「页内精细编辑与下载入口」本地完成：保留 `overhaul/tailor` 既有提交和回放产物。聊天工作区只保留读岗位/挖经历/写简历/核对，写简历预览下提供精细编辑、PDF、Word（可编辑·统一排版）；空稿禁用。精细编辑使用当前会话的 `/resume?session_id=…&embedded=1`，有稿后 idle 预载（计时器降级），关闭只隐藏，切换会话销毁重建；加载中可返回。双向消息校验 origin 与窗口来源，保存成功刷新父预览，对话新版本同步到干净编辑器，未保存输入及请求返回期间的新输入不被覆盖；保存冲突沿用备份/载入最新入口。父子页登录状态同步，直接 `/resume?session=…` 保留导航。下载沿用登录门槛、60秒文件读取超时、文件签名与错误文案，生成中防重复点击，会话切换丢弃旧下载响应；导出意图定位写简历下载区，快捷导出直接导航。只加普通 CSS，无新增 Tailwind utility；相关静态引用版本均更新为 `20261012-embedded`。新增 DOM/Python 与独立纯虚构浏览器夹具，更新既有入口/文案回归。指定 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` 全量 **1290/1290（38.763s）**；新增 DOM、原方案卡 DOM、修改 JS/内联脚本语法与差异检查通过；无真实模型调用、key读取/打印、commit/push/部署。浏览器夹具运行器问题已修正，但 Chrome 后续启动受沙箱 EPERM/SIGABRT 阻止，真实浏览器和视觉验收未完成。Ruff 原有 `resume_workspace.py:111 current_item` 未定义（HEAD 中已有），按范围保留。

本轮文件：`web/index.html`、`web/resume.html`、`web/resume-actions.js`（新增）、`web/resume-editor.js`、`web/resume-editor.css`、`web/resume-workspace.js`、`web/resume-workspace.css`、`web/account-profile.js`、`web/conversation-history.js`；`backend/app/agents/resume_graph.py`、`backend/app/services/resume_workspace.py`；新增 `tests/resume_embedded.dom.js`、`tests/resume_embedded.browser.js`、`tests/test_resume_embedded.py`，更新 `tests/conversation_history.browser.js`、`tests/resume_workspace.browser.js`、`tests/test_resume_flow.py`、`tests/test_resume_import_flow.py`；交接为本文件。浏览器夹具采用页面路由模拟全部接口，需在允许启动 Chrome 的环境执行 `playwright-cli -s=huhua-embedded open about:blank` 后 `playwright-cli -s=huhua-embedded run-code --filename=tests/resume_embedded.browser.js`；其中 PDF 是签名正确的下载模拟体，真实 PDF 生成由全量 Python 测试覆盖。

2026-10-12「写法升级」四项本地完成：保持 `overhaul/tailor` 既有提交与回放产物。推荐/备选增加 `profile_statement`（2–3句、≤90字），复用词面/身份/语义事实校验，并对立场名词及至少两条 active 原文做保守检查；卡片显示原文，确认后写入 summary，确认文本不重复请求语义认可，引用事实失效则重新检查。`positioning` 仅兼容旧方案，不重复展示。个人定位文字替换与写法切换确定性执行；ai_pm/pm 默认 labeled，其余 plain，项目标签按事实分类排序，问题/现状不再被动作过滤或跨标签近似去重误删。原因追问优先于指标，明确答复以 context 和原始引文入档，纯数字回复不误绑为原因；writer 合同要求动作与已知原因同句。正向现状允许，negative_absence 保留并覆盖「未跑通」。7款 HTML 与 Word 页头均显示「个人定位」。新增12项虚构/fake-model回归，指定 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` **1286/1286（42.607s）**；修改文件 Ruff（忽略既有E402）、JS语法、方案卡DOM及差异检查通过。无真实模型调用、commit/push/部署；真实模型文案质量与原生 Word 最终分页未测，无已知阻塞。

本次改动文件：
- 写作/对话：`backend/app/agents/{resume_writer,resume_graph,interviewer,turn_actions}.py`。
- 合同/校验：`backend/app/schemas/writer.py`、`backend/app/services/{structure_plan,writing_style,fact_guard}.py`（`writing_style.py` 新增）。
- 展示/导出：`web/resume-workspace.js`、`data/jianlimoban/html-template/{_macros.html.j2,t003-shenlan.html.j2}`、`backend/app/tools/resume_data_docx.py`。
- 回归：新增 `tests/test_writing_upgrade.py`；更新 `tests/structure_plan.dom.js`、`tests/test_p1_fixes.py`、`tests/test_replay_plan_intake_regressions.py`、`tests/test_replay_polish_regressions.py`、`tests/test_resume_writer.py`、`tests/test_writer_metric_priority.py`；交接为本文件。

2026-10-11「排版自适应一页」本地完成：保留 `overhaul/tailor` 既有提交及深蓝细线未提交改动，7 款可选 HTML 模板共享 density 0–3 参数（正文下限 9.5pt，0 保留原几何）。一页要求先用生产 layout 计页逐档试排，保存最小可行档及最终 hash；3 仍超页才进入原内容压缩。字大/字小/紧凑/松及自动调整走确定性 set_constraint，用户档锁定、可撤销；预览/PDF/通用 Word/模板 Word 同档，保存后编辑器同步排版。PR 链接同行、页头 URL 整体换行，超长 URL 以短链接展示。新增 17 项虚构/无真实模型回归，2 页样例最小选 1/2/3，旧缓存与加密 SQL/checkpoint 回读通过；指定全量 **1274/1274（40.620s）**、Ruff（忽略既有 E402）、JS 语法及差异检查通过。Word 使用自身 1.15 基线对应 1.1/1.05/1 行距；未验证原生 Word 最终分页或真实浏览器自动保存交互。无凭证读取/打印、真实模型调用、commit/push/部署。全部本次文件与 7×4 实际参数见 `docs/development/2026-10-11-adaptive-one-page.md`。

2026-10-11 新增「深蓝细线」模板 `t003-shenlan`：按 Banz 指定的一页 PDF 移植深蓝标题、细线分区、10pt 正文、右上照片及紧凑开源条目。改动仅为新增 HTML 模板、renderer 注册、capacity 新条目及两处写死六模板的测试；原六模板、共用宏、前端、Agent、API、PDF/Word 导出逻辑均未改。35 项模板/容量/预览/安全/PDF 定向检查 + 1 项完整字段检查通过；本人参考内容实际 A4 单页，虚构16项目长标题/长链接样例2页且全部条目保留、无越界，无照片不占位。容量以原探针单测新模板、`HEADER_LINES=3` 校正三行页头，39正文行/每行51汉字，仍以最终PDF实测为准。预览和日志仅在 Git 忽略的 `data/output/navy-template-2026-10-11/`。本轮未提交、push 或部署。

2026-10-11 最新回放四项剩余问题本地修复：在 `overhaul/tailor` 保留 HEAD `eca590d` 与既有回放文件。压缩复用 retention 体系，强制保留本人 action/method_tool/deliverable 引用和主体，缺失拒绝并保留原句，开源接入压缩路径；六模板栏目 margin 小幅收紧，荣誉段落逐行分页、标题跟首行，三行溢出可缩两条最长句，首条拒绝时可尝试第二条且不隐藏确认经历；成稿理由取 experience_plan reason 首个完整短语≤20字，缺失不补套话；空定位从 thesis/lead active 本人事实确定性派生，推荐/备选及确认后 summary 保留，诊断 positioning_source=derived。新增13项虚构/fake-model回归，实际 PDF 两个“差3行”边界样例最终1页且全部确认经历保留。指定全量 **1257/1257（27.087s）**、Ruff（忽略既有E402）、差异检查通过；无凭证读取/打印、真实模型调用、commit/push/部署。根因、完整文件清单与验收见 `docs/development/2026-10-11-replay-remaining-fixes.md`。

2026-10-11 回放剩余四项小修：在 `overhaul/tailor` 保留 HEAD `b8d92fd` 及已有回放文件。六款模板/Word 共用短技能分组合行；生产布局测量新增实际溢出高度/行数，少于页面15%的单页尾部溢出先合并/缩句，不自动隐藏经历，回复按行数或高度描述。方案摘要改为完整一句 + 换行重点，按成对标记之外的标点截断，理由≤20字、含标题总长≤150字。收集提示使用自然确认，把未保存约束标为不向用户复述的内部规则。positioning 合同明确必填，允许概括动作/对象，仍拒绝新数字/工具/成果及主体/状态越界；空值仅从 thesis 恢复与 active 原始事实完整匹配的短句，并记录 missing/empty、拒绝原因和兜底来源。新增16项虚构/fake-model回归，实际 t001 尾部仅两行的2页样例紧凑后1页；指定全量 **1244/1244（22.870s）**，Ruff（忽略既有E402）和差异检查通过。未读取/打印凭证、真实调用模型、commit/push/部署。根因、完整文件清单与验收见 `docs/development/2026-10-11-replay-polish-fixes.md`。

2026-10-11 游客回放七项版式/成稿修复：在 `overhaul/tailor` 保留 HEAD `b06e7ed` 与已有回放产物。六款 HTML/Word 荣誉改为分号段落；定位句新增独立页头 summary，真实自评单独保留；开源简介合并标题、渲染及 writer 去重复 PR 前缀并同步 hash；修复 superseded 专业+学历近似清洗误删 active 专业；方案/成稿 prose 将 requirement/signal id 换为要求原文；只留一处不超过150字的思路及每项不超过20字的 lead 理由；共用隐私提示明确联系方式系统已保存、用户回复不提占位符。新增18项虚构/fake-model回归，含第三轮 collecting→方案→直接写→隔离SQL保存及实际PDF测量；虚构 `t001-jianyue` 由2页降至1页，指定全量 **1228/1228（22.638s）**，Ruff（忽略既有E402）、JS语法与差异检查通过。未读取/打印凭证、真实模型调用、commit/push/部署。根因、完整文件清单与验证：`docs/development/2026-10-11-replay-layout-fixes.md`。

2026-10-11 游客回放 A–G 本地修复：在 `overhaul/tailor`、HEAD `f50fc7e` 保留此前提交，修复联系人非空稀疏合并/链接跨轮保留、共用抽取入口教育专业补救、成对括号与技能项清理、事实清洗后实测与确认方案下合并/缩句、概括定位语义规则和拒绝诊断、lenient schema 裁剪及失败诊断、多答案团队归属/歧义暂存追问/短答接续、状态 role 入档与 canonical 清理。新增28项虚构/fake-model回归，指定 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` 全量 **1210/1210**；修改文件 Ruff（忽略既有E402）及差异检查通过。未读取/打印凭证、真实调用模型、commit/push/部署，既有回放产物保留。根因、全部文件与验收：`docs/development/2026-10-11-replay-guest-fidelity-fixes.md`。

2026-10-11 Flash 回放 fix2 本地完成：在 `overhaul/tailor`、HEAD `4e30f42` 增量修复，保留 P1–P3 与 fix1。方案定位取消 schema 30字硬限制、支持深层 lenient 字段、超过40字整句丢弃；thesis 只用于方案叙事并核对数字/单位/具体技术词，定位句与正文同批语义核验。所有 JD 解码入口加确定性个人资料保护，已有 JD 仅带 JD 特征时替换；待确认补料先提取/导入并持久化，再出新卡；无 pending_plan 的重复确认不改稿，整稿 writer 合并有效技能分组及 active 用户技能；收集提示鼓励一次给全。新增23项虚构/fake-model回归，指定 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` 全量 **1182/1182（22.500s）**、Ruff（忽略既有E402）及差异检查通过。真实模型调用0，无commit/push/部署。逐项根因、文件与验收：`docs/development/2026-10-11-replay-plan-intake-fixes.md`。

2026-10-11 模型回放四处 bug 本地修复：保留已提交 P1/P2/P3（HEAD `4710385`），未回退。空 JD 解码的候选消息回到正常收集并复用并行抽取，JD_INPUT 同样兜底；项目纯状态词在抽取/档案/映射/writer 拦截，旧稿渲染隐藏错误角色但保留状态事实；荣誉名称去首尾标点，HTML/Word/文本统一抑制标题重复 bullet，预览保留原 bullet 索引；advice 按归一化编辑距离 <20% 去重，不足两个时换 style 补一次并重新核验，仍不足如实给一个。新增 25 项虚构/fake-model 回归；指定 `.venv/bin/python scripts/run_tests.py` 全量 1159/1159（22.373s），差异检查和修改文件 Ruff（忽略既有 E402 导入布局）通过。没有读取/打印 key、调用真实模型、commit/push 或部署。根因及逐 bug 文件清单：`docs/development/2026-10-11-replay-bug-fixes.md`。

2026-10-11 PR8 P3 本地完成：本轮最新授权仅实现「定方案」，保留已提交 P1/P2，未实施 P4。首稿先返回推荐/备选结构化 guidance，不写稿、不建版本；按钮/文字确认后只跑 write，后续复用 confirmed_plan（checkpoint + resume_meta）。定位句在现有 summary 展示，主线/定位复用词面 fact guard；明确栏目顺序/取舍直接改，主线变化重跑 plan，新 JD 清确认；旧可见草稿继续编辑，LLM_PLAN_CONFIRM 默认 true、false 保留原单轮成稿。runner 自动插入并计时 auto_confirm，不把方案当版本；容量压缩不再静默隐藏确认经历。新增 28 项虚构/fake-model 回归，最终全量 1134/1134；SSE/checkpoint、Node DOM、防连点、完整 fake benchmark 回放、语法/编译/差异检查通过。真实写作质量 benchmark 与真实浏览器视觉验收未做；真实模型调用 0，无 commit/push/部署。逐文件及耗时说明：`docs/development/2026-10-11-pr8-p3-verification.md`。

2026-10-11 PR8 P2 本地完成：按本轮明确范围仅修 B1–B4，保留已提交 P1，未做 P3/P4。开源贡献按 PR 分条、荣誉结构化、页头链接/实习时间及教育专业/学历/日期/奖学金贯通事实→档案→writer→canonical→六款 HTML/PDF/Word→编辑器；奖学金统一在教育 highlights。move_item 保留条目 ID、正文和服务端来源绑定，数量单位替换由词法 guard 拦截。新增 33 项虚构/fake-model 回归，全量 1106/1106 通过；TLS 原测试用禁 bind 时的 socket pair 夹具保留真实握手/证书验证；无需数据库迁移。浏览器交互仍被环境阻止，不能宣称通过；未调用真实模型、未 commit/push/部署。详情和逐文件说明：`docs/development/2026-10-11-pr8-p2-verification.md`。

2026-10-11 PR8 P1：按 `docs/development/2026-10-11-pr8-mainline-flow.md` 仅实现对话意图与开场，未做 P2–P4。新增 greeting / advice 和独立只读对话节点：各阶段寒暄友好介绍入口；老用户只展示档案姓名与去重经历数量；建议给 2–3 个经 fact guard 核验的选项，不改稿、不建版本，同轮新事实仍提取并保留归档来源，只有明确改稿指令进入改稿。B5 拆开明确缺内容的尾巴（如「分别是」），完整前缀照常提取/按原文补救，尾巴单独提示；归属不明确不猜。新增 26 项虚构资料/fake-model 单测全部通过。全量 `.venv/bin/python scripts/run_tests.py` 为 1073 项：1072 通过，1 项现有本地 TLS 监听测试因沙箱拒绝 bind（Operation not permitted）报错；改动前 1047 项基线也有同一错误，不能宣称全绿。diff 检查通过，Ruff 除基线已有 E402 外通过。未改前端、未调用真实模型、未 commit/push/部署；须在允许本地监听的环境复跑全量。

2026-10-09 Tailor PR4 v5：已本地提交ada326e并完成新公开/私有全套（官方Flash；公开Pro独立评分，私有graph-only）。公开12例70轮69版（68可见），58评分/11无稿；仅补评2个引用错误后21/24（87.5%，3失败），仍未验收。25writer诊断24完成1回退，7结构重试恢复6；事实/编辑Judge仍漏检有时→常等越界，确认新增事实待Claude。私有44facts/6skills和完整主档保持、node/SQL/PDF绑定正确，最终2/2/2/1条、5/8目标满足，但2页；第二轮仅新执行2/14操作（9原已满足、3失败），未达golden。MAIN887/887（含21个PR5独立测试），clean864通过/2私有fixture跳过。旧基线218及v4公开102文件哈希不变。引号限制去重候选在pr4/candidates/v6-limits.patch，103项相关离线通过但未合入/未实时验证。PR5八文件仍未接graph。Ghostty工具安全限制拒绝访问，Claude交接已备未送；不能跳过§8门槛。未push、部署或迁移真实库。

2026-10-08 两份本人历史资料真实生成实测完成：Banz 明确授权 DeepSeek V4.1 Flash（API ID `deepseek-flash`）。在独立临时加密库走真实网页上传 PDF + Markdown、生成、纠错及 PDF/Word 下载；主工作区业务仍为 `a742100`，PR1 未合并。四个真实项目均保留，但联系栏「深圳」误成第五项目；一页要求未执行，默认模板 PDF 为 3 页；mtagent 冲突虽列入核对，正文仍含冲突日期/职责；第二轮明确删改等待约 47.6 秒，data/revision/PDF 完全不变。已只读定位联系栏解析过宽、旧 editor 强制原句保留且未接收篇幅指令、信息提取完整回显与对象数组校验矛盾等原因，未改业务代码或上线。含个人资料的原始 PDF/Word、两轮记录及报告仅保存在 Git 忽略目录 `data/output/tailor-real-materials-20261008/summary.md`；两份原件哈希未变。该结果证明当前应用不能直接产出可投递稿，不代表已单独评估模型写作能力。

2026-10-08 Tailor PR0 R1–R5 修订完成：交付 `evaluation/tailor-bench/runs/20261008-baseline-v2/summary.md`、`cases/README.md` 和 `claude-review-followup-v2.txt`。12 例 approved truth，24 正向要求 + 11 gap；75 项 benchmark 测试、Ruff/diff检查通过。旧代码完整跑 58 轮，32 变化版本（31 可见、1内部）：20 个非空版本统一最终checker评分、12 no_draft；评分0错误/缺失。首稿10/12、两轮内8/12；编辑0/24；要求覆盖 disclosed10/14（71.4%）、truth11/24（45.8%），证据位覆盖12/18及13/46。自动词法/语义疑点0，但7个不可判定字段单列，确认新增经历事实仍待Claude复核，不能借用v1的0。150图调用、10模拟器调用（无回退）、45评分调用含全部旧尝试；首次失败与重评证据保留。旧v1全部103文件逐字哈希一致；业务源码与a742100/v1一致。导入标签未识别和data行动事实落入自评栏已只读定位，留待PR4。PR1独立分支commit `65b06cd`、全套556/556通过，位置 `/Users/yikuaibanz1/.codex/worktrees/tailor-pr1/huhua agent`，未合并到基线、未push、未部署。详见该工作区 `docs/development/2026-10-08-tailor-pr1-verification.md`。

2026-10-08 Tailor PR0 首次交付（v1历史状态，后续修订见上）：`evaluation/tailor-bench/runs/20261008-baseline/summary.md` 为正式报告，`evaluation/tailor-bench/cases/README.md` 为 12 例索引。真实旧 `stream_agent` 在独立临时加密库跑完 59 轮、149 次图模型逻辑调用；捕获 31 次数据变化（30 可见、1 仅内部），19 个有正文版本由不同模型 `deepseek-v4-pro` 评分，其余 12 个空正文版本明确标 no_draft。24 条编辑执行 0/24，终稿要求证据覆盖 14/24（58.3%，模型评审口径）；9 例出现可见经历正文、3 例最终无正文，不能把聊天建议算作已改稿。45 项 benchmark 离线测试、Ruff 与业务源码差异检查通过；业务代码与 `a742100` 一致。当时44条词法/语义疑点待Claude复核；现Claude已确认v1新增经历事实0，原始report/75项review-queue保持历史原样。`direction-01` 有一次规则模拟器漏答，已在报告标注，交互指标不可直接归因于产品。小样 `20261008-pilot` 不进入正式统计。当时未启动 PR1、未推送、未部署、未访问真实用户数据库或发送邮件。

2026-10-08 Banz 要求打开查看。已将本机 8765 服务从 10 月 4 日旧进程正常重启到当前源码，使用现有配置并加载已有 Pango 库路径；应用启动成功，Codex 内置浏览器已打开真实本地页面，可继续操作。未提交对话、未发邮件，生产站点未变。

2026-10-08 核心流程本地修复完成：复现完整聊天资料因缺少固定「项目经历」标题而未导入；现在支持冒号/同行栏目、下一行角色与末尾生成指令，首轮直接形成可核对稿件。「新事实 + 生成」先收集后重建；回执列实际栏目数量、同值不报新增、基本信息稿明确不完整。确定性成功回执等 SQL 保存完成才发送，保存失败会尝试替换 checkpoint 中的成功话术；动态模型指导仍流式输出，提示词禁止提前宣称保存成功。自动分条必须完整覆盖所有原句，防止反馈和未上线限定丢失。全屏编辑器与聊天预览共用本浏览器按会话模板 ID 偏好（不跨设备）。PDF 改为已授权保存稿经 WeasyPrint 返回真实文件，Word/PDF 保留下载入口并有失败/正文读取超时重试；依赖、Docker/CI 原生库和 README 已补齐。

最终离线 **504/504**，整包资料真实 graph/SSE/临时加密库浏览器 **42/42**，模板及真实文件下载浏览器 **20/20**，页面异常均 0；另复验游客体验 28 项、来源/编辑器 31 项、建议采用到真实 PDF 14 项（含聊天/全屏模板往返），文件正文已核对。仅模型润色原样替身，无真实模型或发信调用。六模板 PDF 中文/照片/A4/长文分页检查通过，PDF/Word 下载正文保留最新姓名与未上线限制。首次全套因本机 Pango 路径与沙箱 TLS 监听失败，配置已有库路径并放行本地测试后完整重跑通过，失败日志保留。证据 `evaluation/complete-resume-task-2026-10-08/`，说明 `docs/development/2026-10-08-complete-resume-task.md`。本机测试需 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`，字体缓存可设 `XDG_CACHE_HOME=/private/tmp/huhua-font-cache`。PDF 少数装饰色条与浏览器略有差异；原内置浏览器 Word 失败原因尚未独立复现，实际下载验收使用本机 Chrome。**未部署、未构建 Docker 镜像、未改线上用户资料；线上最近已知版本仍是 20261006-4。** 原未提交工作保留，历史简历未批量重写。

2026-10-06 本地旧功能清理完成：删除 9 个无运行时用途的文件，`agents/prompts.py` 从 272 行缩减为 33 行，只保留内容未变的 JD 提示词；旧评分测试改为当前建议依据核验的 DeepSeek 兼容性测试，并覆盖模型返回无效依据的拒绝情况。离线 **471/471**、改动 Python 文件 Ruff、编译及差异检查通过；首次全套仅因沙箱禁止本地 TLS 测试监听失败，放行本地端口后完整重跑通过。部署源码包 131 文件，已检查旧模块不入包、当前 Skill 和术语库仍在。证据 `evaluation/legacy-cleanup-2026-10-06/verification.json`；受影响文件删除前已在系统临时目录快照并记录 SHA-256。仅本地源码清理，未部署、未改凭证/数据库/用户资料；服务器最近发布仍为下述 `20261006-4`。

2026-10-06 最新用户反馈修复已上线 `huhua-agent:20261006-4`，healthy（image ID `sha256:313774d4f7c5f9cb0bac75bebcca14eefcc77f7aea2a319771a7ba4d7e49d015`）。真实两稿本地解析合并4项目/1教育/6技能组/3奖项，修复姓名与角色年份、Markdown标题及技能串入项目；冲突保留来源、编辑记录排除。追问跟随当前问题/下一步，开放题不强套选项。明确查看+单URL或纯GitHub链接自动读取公开参考；明确JD指令仍解码岗位，GitHub主页最多5仓库/2请求，不改当前稿/目标JD/本人档案。隔离本地与镜像各470/470、前端33/33；线上独立游客脱敏双材料输入、1次真实GitHub+模型、查前后经历不变、来源刷新恢复及页面错误0已验收。原文件仅本机读取、线上用脱敏文本，非上传控件全链路验收；同轮多附件已修，跨轮同项目冲突协调未扩展；原有手工稿与旧对话未批量重写。配对加密备份`/opt/huhua-backups/pre-20261006-4/`，摘要在`evaluation/feedback-fixes-2026-10-06/server-release.log`。无新schema/依赖/密钥/数据卷，无邮件发送。下一次测试刷新后新对话一起上传两稿即可。报告`docs/development/2026-10-06-web-tools.md`，证据`evaluation/feedback-fixes-2026-10-06/`。

2026-10-06 Tavily 已配置并开通：本机backend/.env与服务器app.env均0600，只重建app，镜像仍`20261006-3`，health/database/checkpoint正常，能力read_url/search均true。独立游客浏览器两次真实搜索+模型分析，每轮4条来源；百度/AI产品实习查询未找到直接对应JD并如实说明，The Developer Society/Django Developer找到对应来源并提醒关闭/旧页面。目标JD与未发送输入前后及刷新后保持，来源恢复、页面错误0。不是广泛相关性测试；本会话无本人简历，非空稿件不变仍由既有回归覆盖。证据`evaluation/search-activation-2026-10-06/`。未发邮件、未下载服务器配置、未改代码/schema/账号密钥/数据卷，未检查或调整服务商账单上限。

2026-10-06 文档确认后增量已发布为 `huhua-agent:20261006-3`，healthy。增加正文截断标记并贯穿模型/来源卡片，明确读链接替换 JD、失败计尝试、搜索摘要与最近来源组；修复浏览器旧资源缓存（四个资源版本号）。本地422/422、服务器隔离422/422、前端静态/状态27/27、公网11/11；最终-3只比已测-2改变首页资源版本，后端文件相同，最终健康及线上浏览器新提示已验证、错误0。真实中文页面2份读取成功、1份动态页正确回退。真实模型虚构案例共4次：首次2例发现把“未上线”说成未知，补强提示后2例主要边界通过；仍有“材料未展示→缺口”等表达瑕疵，不当作整体质量证明。真实Tavily仍未调用，等待用户把key放受限配置。证据 `evaluation/web-tools-2026-10-06-followup/`；最新服务器内配对备份 `/opt/huhua-backups/pre-20261006-3/`，摘要在本机server-cache-release.log。未增加schema/依赖、未发邮件、未更换密钥或数据卷。

2026-10-06 工具版本已部署 `huhua-agent:20261006-1`，容器 healthy，宿主 Caddy/原数据卷/密钥保留。公开招聘链接读取已可用；Tavily 搜索接口及界面已完成，但本机和服务器均没有配置 `TAVILY_API_KEY`，入口明确未开通；已异步询问 Banz 是否有凭证，禁止把聊天中的旧 Resend key 用于搜索。离线 **416/416**、服务器无网络隔离 **416/416**、前端静态/纯状态 **20/20**、公网边界 **11/11** 通过；服务器真实读取 Python.org 招聘页成功，私网地址拒绝。本地浏览器以网页/模型替身验收读取、搜索、来源编号、失败回退和输入保留；生产独立游客浏览器用一份公开 Python.org 招聘页完成真实抓取→模型解码→JD/编号来源卡片，页面错误 0；未做真实 Tavily 搜索。发布前服务器内配对加密备份 `/opt/huhua-backups/pre-20261006-1/`，摘要独立留于 `evaluation/web-tools-2026-10-06/server-release.log`。未新增数据库 schema 或 Python 依赖。说明 `docs/development/2026-10-06-web-tools.md`，证据 `evaluation/web-tools-2026-10-06/`。

2026-10-05 游客版本已上线：镜像 `huhua-agent:20261005-2`，最终服务器隔离测试 **377/377**、公网 API **16/16** 通过；游客编辑/预览开放，导出/长期历史/档案要求账号。线上独立游客浏览器完成真实模型一轮虚构资料对话、全屏模板/编辑及导出登录提示；同会话登录接续、未发送输入保留与实际 Word 下载经本地加密后端+内存邮件/虚构模型浏览器验收。真实收件及生产登录接续未验收。本次未换密钥或数据卷，无新增 schema；旧镜像保留。修复既有 SQLite WAL 快照备份工具，停写完成服务器内配对加密备份和隐私快照 `/opt/huhua-backups/pre-20261005-2-wal-fixed/`，摘要独立保存在 `evaluation/guest-experience-2026-10-05/server-final-switch.log`；尚不具备异机恢复材料与完整恢复演练。证据 `evaluation/guest-experience-2026-10-05/`，实际拓扑与命令仍见服务器交接。

首版服务器部署历史：SSH 别名 `banzi`（`ubuntu@49.233.252.47`），目录 `/opt/huhua`，镜像 `huhua-agent:20261005-1`，容器 `huhua-app-1` healthy。保留宿主机 Caddy 与原有网站，仅添加 `resume.yikuaibanz.cn` → `127.0.0.1:18765`；公网 HTTPS 已验证。运维必须使用 `sudo docker compose --env-file deploy/compose.env -f compose.yaml -f deploy/compose.host-caddy.yaml`，不能启动自带 Caddy。两份 SQLite 在 `huhua_app_data` 卷，服务器新密钥只留 0600 运行配置；未迁移本机旧数据。镜像无网络隔离测试 **358/358**，公网边界检查 8 项通过，容器重启后数据库/checkpoint 健康；服务器真实模型一条虚构改写经 2 次调用通过，不能据此声称登录/聊天/导出全流程已验证。证据 `evaluation/server-deployment-2026-10-05/`；实际操作见 `docs/development/2026-10-05-server-deployment.md`。

2026-10-05 邮件域配置完成：通过用户登录的 Chrome 在 Resend 添加 `resume.yikuaibanz.cn`，在阿里云新增 DKIM TXT 与 `rsend.resume`、`send.resume` 两条 CNAME（TTL 600）；服务器公共 DNS 查询均正确，网站 A 仍为 `49.233.252.47`，原 7 条记录保留。Resend 总状态及三条记录均 verified，域名事件显示 03:02 完成。服务器 `RESEND_FROM` 已改为 `Huhua <login@resume.yikuaibanz.cn>`，其余配置保留、权限仍 0600；已重建 app 容器并确认新发件地址加载、Healthy、HTTPS healthz/database/checkpoint 正常。域名管理页为 `https://resend.com/domains/b44ec737-b5dc-46ec-8bd3-d9a480f4ebeb`；证据 `evaluation/server-deployment-2026-10-05/mail-domain-verification.json` 及 `resend-domain-verified.jpg`。

当前待办：已询问可获授权发验证码的测试邮箱，尚无真实邮件发送/收件/朋友登录证据；`login_available=true` 只确认配置，不代表送达。用户误发的 Webhook 签名密钥与验证码发信配置无关，未写入项目或服务器。自动审批曾拒绝把完整服务器 `app.env` 回传本机，已停止且未产生本地副本；仅恢复密钥的异机备份也尚未获单独授权、未完成。

部署配套：镜像秘密排除、显式源码/模板 COPY、非 root 单 worker；`scripts/package_deploy.py` 打包当前未提交工作并排除个人数据、凭证及运行文件，服务器上 `deploy/init_env.py` 只初始化一次密钥。通用新机步骤见 `docs/development/docker-deployment.md`；现有数据若需迁移，保留原数据密钥与 ACCOUNT_SECRET，并走配对库及隐私状态流程。

2026-10-05 源码已完成本轮修复：

- 档案旧值按事实类别、所属经历与字段清理，避免旧年份误伤无关项目和 Go 误伤 Google；完整手机号处理国家码、空格、括号。显式引用的教育/工作/项目保留稳定 `item_id`，事实修订与字段映射保存在已有加密岗位记录，不新增数据库表。
- 稳定关联覆盖改名、重排、改写、图重建、建议采用/撤销及档案更正/删除。同值显式引用建立绑定，不同手工内容保留；缺失、重复、伪造和跨会话 ID 拒绝，整体删除需明确 `removed_item_ids`。旧无映射内容及主动删后任意重写为全新条目的文本，不能完整自动追溯。
- 新增候选生成接口与工作区按钮：选原句、可选偏好、生成及依据核对、预览、明确采用/撤销。每次最多一次生成加一次核对；改候选或稿件版本后重新核对。失败保留输入，生成不自动改稿或归档。导入追问不再假定 CodeWiz 有两项合并 PR。
- 个人预览与导出绑定会话。未保存预览保留表单输入，正式 PDF/Word 使用服务端已保存稿；前端先保存再导出，并正确保留保存期间的新输入和删除。账号模式样例只读，可切模板及导出原样例，明确新建个人草稿后编辑。
- 最新离线全套 **358/358** 通过（审视基线 310）；新增 48 项包含在全套中。浏览器 API 替身：候选流程 **21/21**、来源/编辑器 **27/27**；真实加密后端+浏览器 **26/26**（仅内存邮箱替身，无模型），各自页面异常 0。两份实际 Word 下载已解包核对改名后删除；独立临时 HTTP 复审 5 项也通过，不重复相加。
- 真实模型固定虚构改写六例、10 次调用：3 条可采用、2 条因丢失限定或增加含义被拦、1 条无变化。Codex 做来源比较，不是人工用户研究；候选可用率和长期档案质量仍需验证。首次受限网络失败和单例连通检查另存，不与六例重复统计。
- 审视修复阶段未重启本地 8765 服务；当时健康检查连接失败，仅用 8893 临时加密数据库测试。随后服务器部署是单独获授权的步骤，不改变前述本地验收边界。未 commit/push，原有未提交改动保留；审视阶段源码/文档快照为本机临时目录 `huhua-review-baseline-ge5j0j38`，149 份及 SHA-256 清单。

当前报告：`docs/development/2026-10-05-project-review-and-improvements.md`；证据：`evaluation/project-review-2026-10-05/verification.json`、`semantic-review.json`。复跑方法见该证据目录 README。

历史启用边界：2026-10-04 曾切换本地加密副本到 `huhua-account-v1.db` / `checkpoints-account-v1.sqlite3` 并验证 API，旧数据库保留；来源见 `docs/development/2026-10-04-login-activation.md`。Resend 当时只确认服务商接受一封已授权验证码，收件与真实登录未确认。测试发件域仅支持注册邮箱，对外需发信域验证；聊天中暴露过的旧密钥需轮换，不保存其值。跨对话档案的早期真实模型验收是连接失败，不因本轮“改写六例”通过而改写历史结论。

## 下一步

本轮 MCP 开发交付已完成，先按 `docs/development/2026-10-14-mcp-handoff.md` 用测试账号做 Claude Code 两条手动验收路径，再评估发布；当前未获提交或部署授权，不自动进入 M3。旧主线记录保留如下。

本轮 P3 已完成本地实施和离线验收，先审 P3 diff 与验收记录；后续需另行授权真实模型 benchmark，补 P2/P3 真实浏览器交互与视觉验收。当前未实施 P4，不自动提交、推送或发布。

先让Claude读取 evaluation/tailor-bench/claude-pr4-review-request.txt 与 pr4/summary.md、fact-review-v5.md、runtime-review-v5.md，按§7.6/§8复核事实与误杀，并确认下一修复：明确用户条数应约束模型计划；上游完整性需当前轮次/来源/归属契约；schema透明失败；引号/同义限制候选需审边界。不是再充值或重复当前run的问题。工具明确拒绝访问Ghostty，无法自行送达，已准备可直接转交文件。先修复后另开run，旧v5保持；确认新增事实0且编辑≥90%后再接PR5。PR6模板/API交接尚未验收。

先承接 2026-10-08 的核心流程修复：发布需重新构建带 Pango/中文字体的镜像，再用线上独立测试会话核验完整资料、模板恢复及 PDF/Word 下载；本轮没有发布授权或线上验收结果，不把本地浏览器通过写成线上已解决。

当前产品讨论优先审阅专业能力资料与规则卡：先解决整稿取舍和建议绑定，再扩充知识。现有建议的逐字引用核验可因 PDF 断行误报；聊天建议只有标题和正文，未绑定同一采用对象。上述诊断和修复方向已讨论，尚未实施；本轮仅清理旧功能。继续时承接 Banz 对方案的反馈，不将研究稿视作上线授权。

联网搜索已启用并完成两次真实游客查询。后续关注来源相关性、过期岗位识别与分析文案；只把明确公司/岗位词发搜索服务。更换搜索凭证仅更新受限运行配置并重建app，不索取已有凭证，也不把服务商账户费用上限视作已设置。

用获授权的邮箱验收真实收件、登录、聊天流式输出、保存、采用和 Word 导出；发信域与服务器配置已完成，不重复要求用户添加域名。恢复材料与异机备份/恢复演练另行完成，不能把同机快照视作异机备份。

产品后续优先提升候选生成对否定、参与程度和范围限定的保留，用固定案例观察可采用内容；少量朋友试用记录成稿耗时、修改量与投递意愿。跨对话档案仍需单独完成语义验收；不要用功能测试代替真实收益。

后续更新先核对实际进程及配置，再在授权范围内重启和验证登录，不依据旧记录承诺服务在线。当前单机使用 SQLite，无需为少量朋友测试扩展 PostgreSQL；若改用 PostgreSQL 需单独验收。公开 beta 前补齐真实邮件收件、配对备份与最新隐私状态恢复；代发邀请需明确授权。首期单应用 worker，多实例需要共享会话锁和额外并发验收。

## 文件地图

- `docs/development/2026-10-05-server-deployment.md` / `evaluation/server-deployment-2026-10-05/`：实际服务器拓扑、双配置维护命令、验证证据与未完成项。
- `docs/development/docker-deployment.md` / `scripts/package_deploy.py` / `deploy/`：全新单机部署、允许清单打包与运行配置模板。
- `docs/development/2026-10-05-project-review-and-improvements.md` / `evaluation/project-review-2026-10-05/`：本轮报告与分类验收证据。
- `backend/app/services/resume_provenance.py` / `tests/test_resume_provenance.py`：稳定条目身份、加密字段映射与回归。
- `evaluation/tailor-bench/run_bench.py`：默认 dry-run 的逐版本简历基准入口；旧 evaluate_rewrites 已在 PR4 移除。

- `docs/development/2026-10-04-product-and-profile-plan.md`：已确认开发报告，保留确认时的现状与方案。
- `docs/development/2026-10-04-implementation-handoff.md`：本轮交付、验证范围、启用条件。
- `docs/development/2026-10-04-login-activation.md`：登录修复、真实加密副本迁移、当前服务状态与恢复入口。
- `docs/development/email-login-setup.md`：Resend SMTP、免费测试限制与发送额度配置。
- `docs/development/security-operations.md`：密钥、邮件、显式迁移、配对备份、最新隐私状态与恢复代价。
- `docs/development/profile-archive-contract.md`：档案模型、来源边界、事务事件、API、时间与删除规则。
- `backend/app/services/account_service.py` / `data_crypto.py` / `secure_checkpoint.py`：账号、认证加密与完整图存储包装。
- `backend/app/services/profile_service.py` / `profile_bridge.py` / `agents/profile_archivist.py`：跨对话档案、持久任务、当前稿导入及失效传播。
- `backend/app/services/canonical_resume.py` / `resume_versions.py`：版本校验、稿件历史和撤销；旧 resume_suggestions 已在 PR4 移除。
- `backend/app/services/model_privacy.py`：文本模型请求的联系方式脱敏，映射只留当前调用内存。
- `backend/app/agents/resume_graph.py` / `career_prompt.py` / `career_tasks.py` / `skills/`：主流程、共同事实规则与三项专业方法。
- `backend/app/services/resume_workspace.py` / `web/resume-workspace.js`：右侧工作页、追问与快捷回答。
- `web/account-profile.js` / `account-profile.css`：账号与档案抽屉、冲突/任务状态、采用入口。
- `web/resume-editor.js` / `resume.html` / `resume-preview.js`：当前稿表单、预览与导出。
- `web/conversation-history.js`：私有历史目录与内存草稿恢复；不长期缓存正文。
- `backend/scripts/security_migrate.py` / `privacy_restore.py`：新副本迁移、轮换、加密备份及隐私恢复。
- `scripts/run_tests.py`：强制隔离数据库与空外部凭证的测试入口。
- `evaluation/product-profile-live-2026-10-04/`：真实业务 API/页面及 Word 证据。
- `evaluation/product-profile-2026-10-04/`：模拟前端回归与任务状态提示。
- `evaluation/product-profile-live-model-2026-10-04/`：真实模型连接失败的保留证据。
- `research/skills-memory-2026-10-02/`：先前 Skill 与记忆方案研究，不代表候选框架都已接入。
- `docs/development/2026-10-04-mmr-history.md`：压缩交接前的历史验收记录，保留旧决策与批次边界。
