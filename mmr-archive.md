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

2026-10-15 首页与 MCP 入口调整（资源版本 `20261016-ui1`，仅本地，未提交/部署）：

- 工作台桌面/移动端增加「AI 助手」，复用账号抽屉和登录接续；连接视图仅请求令牌接口，显示连接标题、账号与令牌/最近调用，个人档案移除连接按钮。保留已有品牌返回首页改动。
- 首页右上增加「获取 MCP 密钥」，账号文案为「登录/注册」或「我的档案」；窄屏菜单保留入口。产品展示默认「对话写简历」，支持「精细编辑」、ARIA 标签及左右键切换；无 JS 默认对话图可见。
- `web/home/chat-1440.png` / `.webp` 当前复制自编辑器图，仅作占位，待 Banz 覆盖为 1440×900 对话截图。`home.html` 全部资源及本次修改的工作台脚本使用新版本号。
- 指定全量命令 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`：**1588/1588 通过，57.937s**，日志 `/private/tmp/huhua-ui1-tests-final.log`。相关 DOM 回归覆盖入口、登录/游客接续、连接与档案隔离、令牌操作和标签键盘行为；首页合成浏览器 22 项通过，含 390px 无横向溢出，已检查桌面/移动截图。工作台额外浏览器检查因本机 Chrome 启动 EPERM 未完成；未声称真实账号/邮件/MCP 客户端联调。JS 语法与 diff 检查通过，未改后端或 `evaluation/`。

2026-10-15 第九批人物修复（基于 `75716f4`，仅本地，未提交/部署）：

- 结构化附件/粘贴块在确定性导入层按行解析职务和日期、按句拆事实，保留每条原文/文件来源和重复附件冲突；共用第八批年月范围解析。校园协会已填字段不再显示缺失；保留“按部长文案制作 6 张海报”的实际动作，独立否定事实阻止升级为活动策划。
- 项目日期只进字段，不再成为正文；结构化项目保留分行，PDF 软换行与数量单位校验保留数字边界，避免日期与“3 人课程小组”粘成 `063`。既有竖线式校园标题和口语 ops/tech 路径回归通过。
- 新增 14 项 fake/stub 回归。指定全量命令在无真实配置/私有样例/原输出的源码副本 `/private/tmp/huhua-batch9-safe`：**1586 项，1584 通过、2 项原有私有样例跳过，0 失败，54.330s**；日志 `/private/tmp/huhua-batch9-full.log`。6 份修改 Python 源码/测试与副本 SHA-256 一致，AST、Ruff、diff 检查通过。
- 修复说明 `evaluation/persona-ux/batch9-fix-notes.md`。未改检查口径、fixtures、历史回放、私有目录或原输出；未调用真实 LLM，未重新测量真实 71 项回放通过率；HEAD 仍为 `75716f4`。

2026-10-15 第八批人物修复（仅本地，未提交/部署）：

- 具名经历日期在抽取入口确定性恢复，支持结束月份继承起始年份、已有 item_id 回填；明确兼职进入新 schema 枚举 `part_time`，默认类型不变。技能恢复原话“了解/熟悉/基础”等限定，拒绝否定技能，分组不丢限定。
- 咖啡店代称按原事实唯一定位；已有正文的局部润色绕过整稿方案确认，pipeline 和 SQL 写回前均恢复目标外字段。文章排版/初稿数字动作重复句采用保守确定性去重，保留更完整原句与引用。
- 新增鉴权 `POST /api/chat/session/{session_id}/cancel?turn_id=…`，显式取消当前轮生产任务、阻止未提交事实/成稿写入并恢复 checkpoint；取消前已提交的独立事实保留。无取消信号的刷新/断网继续完成保存；前端收到取消回执后断流并恢复输入。沿用 Docker 单 worker/会话锁。
- 新增22项 fake/stub/隔离SQLite/LangGraph/Node回归。指定全量命令在 `/private/tmp/huhua-batch8-safe`：**1572项，1570通过、2项原有私有样例跳过，0失败，54.509s**；日志 `/private/tmp/huhua-batch8-full.log`。19份源码/测试SHA-256一致；AST、JS语法、diff检查通过，Ruff仅原有E402。修复说明：`evaluation/persona-ux/batch8-fix-notes.md`。
- 未调用真实LLM、未重新进行71项真实人物回放；未改检查口径/fixtures/历史回放/私有目录/原输出，保留用户已有 `posters_ownership` 正则修改。下一步为真实模型人物回放验证，本轮无部署或提交授权。


2026-10-15 五人物回放剩余问题修复（基于 `03a5c70`，仅本地）：

- 首轮方向与经历同收集；验证后的事实通过独立 SQL intake 事务先保存，保留旧成稿/版本；回复失败回填 checkpoint。SSE 请求关闭后生产任务继续持有会话锁、完成抽取和保存，刷新后的下一轮仍按该锁串行。
- 移除「对话中描述的经历」生成兜底；未知归属留原始待核对材料。经历抽取过滤姓名、教育及生成/润色指令；写作要求进入 session_constraints/metadata。补 `在X做/当/任Y` 公司和职位，拒绝学校/家及动词开头的地点。
- 用户明确保留的参与程度/测试环境限定，以及同源数字成果的限定，回接相关 bullet 并维护引用/hash。带数字动作不依赖 result_metric 分类；验证正文覆盖而非仅引用 ID；满额优先数字，必要时合并数字事实；“12 条测试”不再误判为条数指令。
- 旧 COLLECTING 稿的润色/数字更正走编辑事务；补唯一定位的“培训次数改成 4 场”，仍须正文新值出现、旧值消失才回执成功。删除正常一页稿的排版档位提示，超页时保留自然决策说明。
- `checks.py` 仅修复 service/design 的交付时点：initial 及自己的 initial_confirm 取最新交付稿，不借 recovery/paste；直接生成当轮检查保持严格。after-batch6 冻结产物重评 **53/71**（原47；6项取样修正，非本批真实回放提升）；见 `evaluation/persona-ux/after-batch6-rechecked.md`。
- 在无实际配置及私有/输出目录的源码副本 `/private/tmp/huhua-persona-batch7-safe` 执行指定命令：**1550项，1548通过、2项原有私有样例跳过，0失败，49.464s**；日志 `/private/tmp/huhua-persona-batch7-final.log`。26份变更Python与测试副本hash一致；AST、diff通过；Ruff前后均22项既有问题，无新增。新增人物回归含真实隔离SQLite回读、回复阶段异常、断连继续保存、无后缀公司、限定与数字、旧状态更正；既有测试仅同步删除兜底/内部提示及新增intake存储桩。
- 没有调用真实LLM、提交、推送或部署。尚未验证新代码的真实模型回放；无旧值/多归属的模糊更正仍保守拒绝；进程在抽取完成前终止不保证自动续跑。完整逐项根因和文件清单见 `evaluation/persona-ux/batch7-fix-notes.md`。


2026-10-15 合成人物事实与输入回归修复（本地，未提交）：

- 本批对应 `evaluation/persona-ux-2026-10-15/反馈.md` 第 1、2、3、5 项，直接使用 `fixtures.json` 和设计 TXT。`turn_actions` 分开形容词“更专业”和教育字段指令；抽取、路由共用专业校验。定向润色锁定经历，正常/失败 writer 路径均保留其他栏目、条目及目标经历标题字段。
- 数字/明确引号片段更正走 `fact_corrections` 局部事务：先定位事实，经 `apply_fact_patch` 保留 superseded 审计和新引用，再同步全部相关 bullet、描述及有引用的摘要；更新引用、hash 和覆盖记录，校验新值出现/旧值消失后才能保存和回执。歧义、找不到正文、同句多个无法区分的同值均整轮保留原稿并说明失败；不调用 writer，不改其他措辞或数字。
- 混合消息先拆出明确 JD 段落，同轮收集本人材料；个人附件优先导入，可从会话原附件纠正误分类。补“课程项目名称/时间”、逐行教育和学生组织标题，上传指令与文件正文分开；同名课程/学校合并，“在新城职业学院”清掉前缀，否定技能不展示。嵌套收集→构建保留用户原消息，并识别“直接生成”，避免开启方案确认后丢掉本轮直接成稿要求。
- 新增 `tests/test_persona_regressions.py` 14 项：不完美抽取/分类/writer 桩、首稿完整性、专业字段正反例、精确更正、失败不报成功、相同数字隔离、限定保留、跨栏目不变和保存先于回执。在无实际配置/私有目录/原运行数据的源码副本 `/private/tmp/huhua-persona-safe-8ez_rwtm` 运行指定命令：**1537 项，1535 通过、2 项私有样例跳过、0 失败，92.807s**，日志 `/private/tmp/huhua-persona-final.log`。12 份本批 Python 文件 AST 通过、hash 与验证副本一致；差异检查通过；Ruff 无新增问题，仅 `resume_graph.py:188` 原有 E402。真实 LLM 未调用；隐含 JD 边界、不带旧值的自由措辞更正未在本批承诺通用识别。
- 本批改动：`backend/app/agents/{turn_actions,fact_extractor,resume_graph,tailor_pipeline}.py`；`backend/app/services/{candidate_language,candidate_material,candidate_sections,education_fields,fact_corrections,skill_groups,structure_plan}.py`；新增测试；本交接。沿用上一批自动润色、归属与不追问规则。未改 `web/` 或 `backend/main.py`，未 commit/push/部署，未访问原工作区私有样例/运行结果/输出及实际凭证。其他工作在本轮期间改动了 `web/index.html` 和 `web/resume-workspace.js`，未覆盖，并将最新文件同步进测试副本。

2026-10-15 成稿自动润色、覆盖与归属修复（本地完成，未提交）：

- 根因核实：`208bd45` 的覆盖补回按字面判断并直接追加事实；`WrittenBullet.fact_ids` 已存在，但概括被具体表达覆盖时仍误补。现在用同经历有效引用、正文 hash、动作/对象归一及反向 `verify_semantics` 判断覆盖，过度引用 ID 不能掩盖独立职责遗漏。真正遗漏经单条 writer 改写与事实校验后补回，失败走确定性清洗及词法/数量/职责校验，补回后再去重；压缩稿继续审计覆盖。
- 新增 `services/auto_polish_gate.py:needs_polish`：口述第一人称、口语、少于8字且无数量/对象的碎片、流水账开头、同经历重复、source_quote 原样。只改命中句，未命中好句保持原样。每条 `resume_meta.bullets[item_id][i].polish` 记录 `rewritten/reasons/method`，`coverage_fact_ids` 记录与正文 hash 绑定的覆盖证明。
- 权限、非负责人、他人定选题/给文案及数据缺失保留为 `status_limit`，仅约束措辞，不输出为 bullet 或备用清单；裁掉限制的来源引文拒绝。先拒绝未知 ID，再按子句明确主体/最近工作或校园经历名称归属；「我还…」可跨句，换主体/换段停止接续，明确回协会仍归协会；占位命名更新原条目。
- Canva/可画分别保留，PS→Photoshop，「会一点」→（基础），「会用Excel」→Excel，补齐剪映。备用只报数量并指向核对页，已识别 objective 不报漏记。本轮/此前「不要再追问、直接生成、不用问了」抑制名称及 interviewer 追问，偏好保留在会话状态。
- 验证：新增 `test_auto_polish_gate.py` **10项**，含两段虚构输入、错归属抽取桩、部分引用/好句与口语句 writer 桩、真正遗漏、编造拒绝、语义失败、跨经历引用、停问持久化、两家公司就近归属。既有测试仅随清洗文案、摘要回执和局部润色调用更新预期，未放宽事实/作用域校验。
- 全量在排除实际配置、私有目录和输出目录的源码副本 `/private/tmp/huhua-polish-safe-fi3_57vk` 执行指定命令：**1523项，1521通过、2项私有样例跳过、0失败，72.078s**；日志 `/private/tmp/huhua-polish-accepted.log`。开始基线1470项，期间其他任务新增测试已同步验证。20份改动 Python 文件 AST 与副本 SHA-256 一致、差异检查通过；Ruff 无新增，HEAD 原有 `resume_graph.py` E402 与 `test_tailor_pr5_gate.py` 的3项未使用符号保留。
- 边界：仅桩模型，真实 LLM 改写效果及额外延迟未实测；归一规则范围有限，多义指代仍保守处理，项目归属沿用原校验。本任务未改 `web/`、`backend/main.py`，未读取实际凭证或访问 `cases-private/`、`runs-private/`、`data/output/`，未 commit/push/部署。

本轮改动文件：
- `backend/app/agents/`：`fact_extractor.py`、`resume_writer.py`、`resume_graph.py`、`tailor_pipeline.py`。
- `backend/app/services/`：`auto_polish_gate.py`（新）、`candidate_language.py`、`candidate_skills.py`、`fact_coverage.py`、`fact_guard.py`、`skill_groups.py`。
- `tests/`：`test_auto_polish_gate.py`（新）、`test_fidelity_followup.py`、`test_llm_compat.py`、`test_parallel_calls.py`、`test_replay_plan_intake_regressions.py`、`test_resume_writer.py`、`test_speed_switches.py`、`test_structure_plan.py`、`test_tailor_pr5_gate.py`、`test_writer_metric_priority.py`；交接 `mmr.md`。

2026-10-15 官网主页本地完成（`overhaul/tailor`，未提交/推送/部署）：按 `docs/design/2026-10-15-home-page.md` 使用方案 A，新增独立 `web/home.{html,css,js}`。`/` 为官网，`/chat` 为原工作台；旧 `/?session=…` 以 302 保留原查询串跳到固定本站路径。返回聊天、档案来源/岗位、MCP 收件箱/草稿及浏览器脚本已迁移；`panel=profile/connect` 复用账号面板，登录/游客认领后接续指定视图。模板入口支持指定模板，所有官网图片有 WebP/PNG 兜底。透明线描插画为内置 imagegen 生成，PNG 74,026 字节。

验证：不含真实配置、私有目录和输出目录的源码副本执行指定全量命令，**1470 项，1468 通过、2 项私有样例跳过、0 失败，51.894s**。41 份改动源码/资产哈希与通过测试的副本一致；官网合成浏览器检查通过、1440px/390px 截图已审阅，图片加载后复查模板裁切；最后一次额外浏览器重跑受沙箱 Chrome 启动限制。交付清单、文案边界、插画提示词和测试路径见 `docs/development/2026-10-15-home-page-verification.md`。下一步为人工审阅本地官网；没有部署授权。

2026-10-15 五种岗位线上游客体验反馈（仅评测）：按 Banz 请求实际体验 `resume.yikuaibanz.cn`，以合成材料覆盖 Java 后端、新媒体运营、行政转 SaaS 客户成功、UI 设计实习 TXT 导入、电商客服普通口述。已走材料输入/补述、推荐方案、生成、润色、两次数字更正、模板切换、手动编辑、刷新恢复、游客 PDF 下载登录提示及 390×844 视口。

线上观察：Java 完整输入首稿只有教育；设计附件内容进入岗位解读而本人经历为空，重贴正文后仍丢核心课程项目；运营咖啡店海报错挂协会；客服教育重复。Java 与无测试提示词的客服均把“更专业”误认成改教育专业，分别写入“请把实习经历润色得更”/“写得更”；170→190ms、培训6→4场请求完成后预览仍为旧值。润色存在删除限定、重复原句和牵连其他字段；未观察到运营粉丝增长或行政续费/CRM成果编造。模板切换、手动改专业、完成保存及刷新恢复通过；下载只验收到登录提示，未发验证码、未用真实账号、未取正式PDF/Word。

反馈与原始输入/各轮可见内容/截图：`evaluation/persona-ux-2026-10-15/反馈.md`、`fixtures.json`、`design-material.txt`、capture日志/JSON、screenshots/。独立游客、实际线上流程，无API桩；不是用户研究或成功率统计。只新增评测产物和本交接，未改业务代码、未提交/推送/部署，不据线上现象推断本地修复是否已发布。优先建议：润色/字段修改意图区分→数字更正→混合输入/附件保留→经历归属去重→精准改稿→引导减负。

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

## 2026-10-15 第十批：同段经历拆分与合并更正（本地，未 commit/部署）

- 根因：`日常更新` 被 personal 启发式误判，句号切断主体续接且同轮命名条目未预载；教育解析从整段取首个日期；原更正协议只支持单条事实，缺少条目合并，归属元陈述未过滤。
- 修复：有明确名称的结构化行/编号经历先建立主体范围，职责和日期沿用该主体；B 首轮使用原文“本地连锁烘焙品牌”，不造个人练习/工作占位。教育日期局部取值，明确教育时间更正替代旧事实。公司 + 同段/非个人项目声明 + 唯一事实主题匹配生成合并补丁，迁移事实 ID/来源/链接、删除占位条目并保存 `merged_from`；同段归属元陈述不作为 active 经历事实。否定或歧义不合并，不误伤个人练习、行政工作及非负责人限定。
- 文件：`agents/fact_extractor.py`、`agents/turn_actions.py`；`services/candidate_language.py`、`experience_dates.py`、`fact_corrections.py`、新增 `experience_subjects.py`；新增 `tests/test_batch10_regressions.py`（15 项）。根因、逐文件改动和测试说明见 `evaluation/persona-ux/batch10-fix-notes.md`。
- 验证：指定命令 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` 在当前仓库运行，最终 **1603/1603 通过，0 失败、0 跳过，53.440s**；日志 `/private/tmp/huhua-batch10-verified.log`。新增测试覆盖 A/B、错归属/倒序抽取、连续两轮、历史合并、日期归属、元陈述过滤、歧义/否定与工作区投影；Ruff（7 份本批 Python 文件）和 diff 检查通过。
- 边界：未改 `evaluation/` 的 checks.py、fixtures 或检查口径；未调用真实模型、未复跑 8833 的 deepseek-flash，也未 commit、部署。其他任务的 `web/comparison*` 改动保留。后续真实模型回放属于尚未验证部分。

## 2026-10-15 第十批补充 10b：经历日期字段与公司描述（本地，未 commit/部署）

- 根因：日期已进入带 field 的事实，但补丁没有写入经历条目的 start_date/end_date，右侧只读条目字段而继续报缺失；独立日期及公司括号描述没有从普通事实排除，第二轮合并也会带入描述。同句连续编号还可能被整句多日期/非事实判定跳过。
- 修复：按明确主体范围恢复日期，保留原自由文本回填；补丁、更正/删除和合并后仅对本轮涉及条目同步有效日期字段。清除独立日期和纯公司描述要点，历史合并的描述保留审计但退出 active；带日期的动作和括号内职责不误删。
- 文件：`agents/fact_extractor.py`、`services/experience_dates.py`、`services/experience_subjects.py`、`services/fact_corrections.py`；`tests/test_batch10_regressions.py` 新增 6 项，涵盖 A/B 条目字段、工作区缺口、投影/桩 writer、合并、连续编号及日期更正/删除。详细说明追加在 `evaluation/persona-ux/batch10-fix-notes.md` 的「10b」一节。
- 验证：第十批定向 **21/21**；指定全量 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` **1609/1609 通过，0 失败、0 跳过，50.890s**，日志 `/private/tmp/huhua-10b-full.log`。Ruff（5 份 Python 文件）、diff 检查通过；第八批日期回填与第十批教育日期归属回归保持通过。
- 边界：保留第十批及其他未提交改动，checks.py、fixtures、已有 web/comparison* 等保护文件哈希未变；未 commit、未部署。本次仅离线桩模型验证，未复跑 8833 的真实 deepseek-flash 对话。

## 2026-10-15 第十批补充 10c：tech 首稿职责与日期残片（本地，未 commit/部署）

- 根因：失败快照中接口职责从工作区正文变为 role；抽取器接受 `field=role` 后，writer 的正文事实筛选和补漏跳过它。复合「日期，3 人组队」早在第九批已存在，10b 的整串日期/端点过滤未覆盖这种形式，数字覆盖会把整句补进正文。以相同抽取/writer 桩对照 HEAD `e19c18c` 第九批后端和第十批 + 10b，两者在 role 误标下均丢接口、普通 action 下均保留；不能将回放时序差异归因于最近主体、公司描述过滤或日期分段的某处改动。详细证据与排除过程见 `evaluation/persona-ux/batch10-fix-notes.md`「10c」。
- 修复仅两处：`fact_extractor.py` 将项目中误标为 role 的「负责……」职责归回正文 action，真正职务保持 role；`experience_dates.py` 只移走复合事实中与已恢复字段一致的独立日期子句，保留团队规模、课程语义和原始引文，带日期的实际动作不误删。
- `tests/test_batch10_regressions.py` 新增 4 项桩回归，修复前复现失败；完整 tech 原文经抽取→事实应用→初稿投影→writer 后包含商品发布/搜索接口、Spring Boot/MySQL、团队及登录/实验室演示限制，正文与 description 无日期残片。覆盖 action/role 两种抽取输出及只写背景的 writer，原 A/B 与 10b 断言保持通过。
- 验证：定向 **25/25，0.222s**；指定全量 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` **1613/1613 通过，0 失败、0 跳过，60.913s**，日志 `/private/tmp/huhua-10c-full.log`。3 份 Python 文件 Ruff、diff 检查通过；107 份 checks/fixtures/历史回放/既有网页保护文件哈希未变。前后源码固定输出对照日志 `/private/tmp/huhua-10c-causality.log`。
- 边界：保留第十批 + 10b 和其他未提交改动；未启动/调用 8833、未调用真实 LLM、未 commit/部署。真实 tech 回放通过率未重测，下一步若授权真实回放，再验证 `tech.initial_project`；本轮交付为离线桩与全量测试通过。

## 2026-10-15 MCP 接入任务示例 UI2（本地，未 commit/部署）

- 首页 #mcp 增加三步接入及「按 JD 改简历 / 把项目记进档案 / 检查简历依据」三项可复制示例，保留命令卡、隐私说明及复制反馈；工作台 AI 助手面板在令牌表单上方展示相同任务，连接入口登录页列任务名，令牌仅显示一次面板补两个 Claude Code prompt。档案视图不加任务内容。home.html 资源与 index.html 的 account-profile.js/.css 版本更新为 `20261016-ui2`。
- 指定全量 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`：**1614/1614 通过，0 失败/跳过，113.907s**，日志 `/private/tmp/huhua-ui2-full-tests.log`。首页/面板 DOM 覆盖任务复制成功/失败、aria-live、登录任务名和档案隔离；JS 语法及 diff 检查通过。已补 390px 页面/卡片溢出浏览器断言，但本次 Chrome CLI 启动与备用静态服务器监听均遭本机权限拒绝，未完成浏览器尺寸/截图验收。
- 仅修改 `web/home.html`、`web/home.css`、`web/home.js`、`web/account-profile.js`、`web/account-profile.css`、`web/index.html`，以及 `tests/test_home_page.py`、`tests/test_mcp_ui.py`、`tests/home.dom.js`、`tests/mcp_profile.dom.js`、`tests/home.browser.js` 和本记录。首页 MCP/资源版本以外内容与操作前逐字一致。未写入 comparison.* 或 cross-tool 目录；期间观察到其他会话更新 comparison.html 和 methodology.md，原样保留。未改后端、未启动或调用 8833、未 commit。

## 第十一批：混合输入直接成稿、统一交付与能力声明（本地，未 commit/部署）

- 根因已核实：自然语言招聘要求与【个人分节】未拆分、请求前缀误把“虚构测试材料”当成编造指令；聊天正文缺少保存闸门。另修复数字更正提前返回而漏执行同轮其他修改，以及贡献限定可能被正文取舍丢弃。
- 运行时按明确分节分离 JD 与个人材料，保留显式 JD 和纯 JD 路径；只拒绝要求 AI 编造的指令，并明确回执。明确直出请求同轮采集、采用推荐方案并完成正式写稿；缺失字段省略。P2 的 18→12、校园整段隐藏、SQL 仅基础查询在一次编辑中落库，P3 沿用该稿。
- SSE 在正文/能力声明边界缓冲，SQL 保存后统一校验公开回复及历史；整份聊天稿改为指向右侧唯一稿件。能力提示和否定声明修正按真实导出状态及登录策略显示；现有联系方式脱敏不变，工作区保留原始电话/邮箱。指标口径回接对应评测要点，贡献/审批边界保留在要点或角色行，并拒绝把他人贡献反向归属本人。
- 新增 `tests/test_batch11_comparison_case.py` **27 项**，使用公开冻结 P1/P2/P3、桩模型和独立 SQLite，覆盖拆分/路由、正反防编造、直接生成、交付闸门、能力声明、限定恢复、三轮事实/稿件与数据库一致性。指定全量命令 **1641/1641 通过，0 失败/跳过，48.306s**；日志 `/private/tmp/huhua-batch11-complete.log`。本批 16 份 Python 文件 Ruff、diff 检查通过；177 份保护文件前后 SHA-256 一致。
- 未修改受保护文件或既有测试断言；保留其他未提交工作。未启动/调用 8833，未调用真实模型，未 commit/部署；真实模型回放仍由 Banz 执行，桩测试不代表真实模型效果已复测。

## 2026-10-16 第十一批 b：成稿质量与流式缓冲回退（本地，未 commit/部署）

- 依据 Banz 提供的 `batch11-replay.json`：P1 方案给拾光 3 条，最终正文 2 条，访谈只留在 description；未发生页面压缩。使用同一 match_plan/事实的桩做阶段对照：旧 `_numeric_fact` 漏认「18 名/8 名」，却把「4 人课程项目」当数字成果，满额补条替换访谈，随后背景合并把团队规模并入原型句，最终变成 2 条。修复识别单位、排除纯团队规模，并在确认方案的条数上限内优先恢复已选岗位证据。额外修复 fact_guard 将「不是负责人」误解为禁止所有「负责…」的规则，以及 phase=write 把整个条目 withheld 而跳过补漏的问题。原回放没有原始 WriterDraft，未声称拿到了真实模型中间输出；确定性对照 `/private/tmp/huhua-b11b-causality.json`。
- 角色恢复原文正向身份；否定角色保留为事实约束，不充当 role。团队规模、项目未上线进入标题/角色行；他人负责代码/接口的边界移出指标句。课堂/离线/本地/自拟/人工判定按相关动作自然整合，重复指标按同一对象与有序起止值消重，纯否定尾巴不入稿；维护对应引用和 hash。教育缺失说明不渲染；技能保留 Figma 基础流程/低保真原型、Agent 工具调用/RAG 基本流程和 Python 简单脚本等原文能力范围，SQL 仍仅基础查询。
- P2 写回另发现旧值清理按近似文本把「负责访谈12名…」当作旧 18 名句删除：已让有 replaces 关系的有效原文更正优先于模糊匹配，旧文本仍删除。隔离 SQLite 回读确认访谈 12 名出现在渲染正文，校园删除、SQL 限定和 P3 不恢复的既有三轮回归保留。
- 普通回复按模型 token 直接流出；仅明确交付请求或累积文本出现姓名标题、简历分节、联系方式行时缓冲正文。PDF/Word/文件/下载声明只缓冲当前未结束句，句末修正后恢复流式；已保存稿的能力文案读取初始会话状态。若文件关键词到达前已有句前缀流出，SSE 无法撤回，追加明确更正并修正历史，不扩大为整条回复缓冲。
- `tests/test_batch11_comparison_case.py` 新增 **14 项**（合计 41 项），内嵌公开回放 plan/事实，不依赖临时回放文件：覆盖 writer 已写/漏写访谈、选中非数字证据优先、角色、重复指标/口径/引用、教育元信息、技能限定、P2 SQL、旧值隔离和首 chunk 时序（不/无/简历/项目/技能均在请求第二 token 前产出）。`test_batch10_regressions.py` 与 `test_persona_regressions.py` 各一处旧语义断言按本批要求更新为保留「只给班里演示」、禁止正文「没有真实用户」，其余断言未改。
- 最终指定全量命令 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`：**1655/1655 通过，0 失败/跳过，50.156s**；日志 `/private/tmp/huhua-b11b-full-verified.log`。24 份现有变更 Python 文件（含第十一批）Ruff 通过，diff 检查通过；178 份 checks/fixtures/web/comparison*/evaluation/cross-tool-*、打包脚本和首页保护文件 SHA-256 未变。
- 保留第十一批及其他未提交工作，未 commit/push/部署，未启动或调用 8833，未调用真实模型。这里验证的是桩模型与纯函数/隔离数据库，deepseek-flash 的新一轮真实成稿效果仍待外部复测。

## 2026-10-16 第十一批 c：tech 指标、角色与限定恢复（本地，未 commit/部署）

- 定位：`after-batch11/tech/01-initial.json` 的经历投影及 active fact coverage 已没有 420/170 指标；`guard_fallbacks` 明确记录 `unsupported_numbers:170,420`，指标句因此回退成联合索引动作。并非已证实由最后的背景合并删掉完整指标：该回放未保存原始 extractor/WriterDraft；确定性等价桩证明抽取器只交付索引动作时，原补漏器不识别“平均耗时由约 420ms 降到约 170ms”。宽 source_quote 含数字而 fact.text 漏数字时也会漏补。本轮在采集端恢复有明确归属的原文结果，保留相邻动作/测试环境出处，拒绝计划、否定及无归属；满额数字修复将同源结果接回动作，不挤掉原动作。
- 角色根因：`positive_role` 只过滤否定而接受职责，`sourced_role` 优先沿用错误 current role；11b 限定恢复又主动把他人贡献挂到 role。现在身份字段排除职责/他人动作，误标 role 的事实在 writer 证据视图回归 action，原事实审计不变；职责、登录模块由同学编写和审批边界保留在正文。`resume_bullet` 同时清除裸职位回声，并保留无效 header 引用的 guard 诊断。Banz 手加的 `sourced_role(..., name)` 同名去重和 `choose_edit_plan` 尾部 remove_section 去重均保留。
- 限定修复：按保守语法等价识别“对一个慢查询加了联合索引”与“对慢查询加联合索引”，清理已有重复括号；“没做线上压测”默认只约束，明确保留限制时自然接入一次。部署地点与演示受众共同恢复为“部署在实验室服务器，只给班里演示”，不因正文已有登录分工或满额而只留下演示受众；贡献边界优先放非指标要点。各步同步引用、coverage 缓存和 text_hash，重复执行幂等。
- 回归：`tests/test_batch11_comparison_case.py` 新增 **7 项**（模块合计 **50 项**，含此前两项手改），修改前复现 6 个失败断言。等价抽取/写稿桩覆盖窄/宽引文漏指标、三轮正文、角色误标、职位回声、重复括号、实验室演示、条数预算、引用/hash、否定与计划边界；P3 同时走字面事务与实际 evaluating 路由，断言只把 170 换成 190、其余正文逐字一致且不调用 writer。原 11/11b 对照回归保留，角色行分工断言改为正文；`test_writer_repair_context.py` 两项旧回退文本断言同步要求正文保留分工，原有调用次数/失败回退检查不变。五人物现有 fixtures 对应桩测试及相关修复测试 **142/142** 通过。
- 验证：指定全量 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` 最终 **1664/1664 通过，0 失败/跳过，50.011s**；日志 `/private/tmp/huhua-11c-full-final.log`。26 份变更相关 Python 文件 Ruff、diff 检查通过；178 份 checks/fixtures/web/comparison*/evaluation/cross-tool-*、打包脚本和首页保护文件 SHA-256 未变。未改历史回放，未调用真实模型或 8833，未 commit/push/部署；真实五人物回放仍是 Banz 提供的 68/71，本次没有声称新的真实模型通过率。

2026-10-16 第十一批 d（承接当前未提交 11/11b/11c 与两处手改，仅本地）：

- 交付闸门改为定位具体简历条目块：有日期的「公司/项目 | 职位 | 日期」标题及其要点，或姓名/联系方式与简历分节、要点组成的正文。迁移分析表格、证据缺口列表、改法说明和普通中文分析标题不再因标题/列表数量被误判。混合回复只将草稿块替换为一句「草稿已放到右侧『写简历』」；未保存时如实提示，保留分析、说明和问题。
- 流式保留 11b 的明确交付/正文起始缓冲条件；未完成的 Markdown/姓名/联系方式标题先判定再释放。收尾按每条消息已消费的原文位置只追加剩余内容，历史使用实际已发前缀加处理后的尾部，避免整条替换接在 `## 能` 后。迟识别的纯文本条目标题先完整补齐该行，再追加草稿提示；普通追问首 token 即时流出回归保留。
- 职责与分工从 role/title 移出时同步进入初始正文，并在 writer 首稿遗漏时确定性补回已有条目；混合的「身份 + 职责 + 他人分工」保留身份、将职责/边界放入正文。保留条数预算及引用/hash；不依赖 polish 才恢复登录模块分工。
- 慢查询平均耗时按对象、顺序数字对、单位与约数限定识别「降到/降至」等价表达；已覆盖但漏引的事实只补引用，补漏前再次检查正文。重复指标只删重复子句，保留同条的 12 条接口测试、导师指导与 Redis 缓存等独立事实；不同对象、反向数字与计划不合并。Agent 工具调用与 RAG 的短技能别名与基本流程原话去重，保留更具体的原文。
- 新增 `tests/test_batch11d_regressions.py` **12 项**，内嵌 `after-batch10c/career/01-initial.reply.txt` 完整原文并核验逐字一致；覆盖有/无保存、分析保留、1/2/7/53 字与整段分块、流式与历史一致、首稿漏写分工、混合 role、指标重复及引用/hash/幂等、技能正反顺序去重。既有 11/11b/11c 模块仅同步两条交付判定/回执断言，累计相关回归 **62/62**。Banz 手改的 `sourced_role(..., name)` 与 `choose_edit_plan` 函数 AST 均与本轮开始时一致。
- 验证：指定全量命令最终 **1676/1676 通过，0 失败/跳过，50.223s**，日志 `/private/tmp/huhua-11d-full-final.log`；27 份当前变更相关 Python 文件 Ruff 与 diff 检查通过。3258 份受保护文件（checks/fixtures、全部 evaluation 历史材料、web/comparison*、`scripts/package_deploy.py`、`web/home.html`）SHA-256 未变。未调用真实模型或 8833，未 commit/push/部署；真实五人物回放仍按 Banz 提供的 after-batch11c **69/71** 记录，本轮不声称新的真实回放分数。补充证据边界：本轮读取到的 tech 首稿 JSON 已含登录分工，因此另用明确漏写的 writer 桩验证首稿确定性恢复，指标重复则与该文件一致。


## 2026-10-16 第十二批：模型故障中止与条目内去重（本地，未 commit/部署）

- 根因：`fact_extractor.extract_facts_patch` 吞异常返回空补丁，`_extract_info_from_message` 又回退原状态；collecting 继续回执，最终保存的 `_serialize_to_resume_data → _harvest_projects_from_messages` 将混合原文拼成项目。现将抽取、写作/修复及必要语义核验的连接、超时、空响应转为 `E-MODEL-*`，SSE 走错误机制，checkpoint 记可重试错误、保留原消息与旧稿；已独立提交的有效材料保留。旧 snippet 仅接受短且归属明确的经历，拒绝指令及跨经历混合文本。
- 新增确定性条目内收尾：同组至少两个数字的要点合并保留更完整表述；后一要点的重复动作子句删除，独有数字/限定保留。同步引用/hash、事实覆盖；writer、聊天 SQL 与 canonical 保存入口共用。提供的第三轮快照离线清理后，拾光原型动作出现1次，RAG 的71→82指标只保留1条；原文件未改。
- 新增16项回归，含连接/超时/空响应 × 抽取/写作 × 首轮/已有稿件的12组真实SSE/隔离SQLite/checkpoint失败与同消息重试，以及语义核验故障、去重幂等/补漏、三轮对比和保存入口。既有格式校验桩改用非空错误结构，超时断言改为中止；排版断言随去重后的真实密度调整，fixtures未改。指定全量命令 **1692/1692通过，0失败/跳过，54.738s**；日志 `/private/tmp/huhua-b12-full-verified.log`。本批13份Python文件Ruff、diff检查通过；全后端另有HEAD既存的`named_content.py`三项E741，未扩改。
- 3385份evaluation/fixtures/comparison/首页/打包脚本保护文件SHA-256未变，原mmr内容完整保留。HEAD仍为`a35a805`；未调用真实模型或8833，未commit/push/部署，未声称线上效果已复测。

## 2026-10-16 第十二批 b：收窄主调用错误与生成稿去重（本地，未 commit/部署）

- 恢复 `test_repair_timeout_still_falls_back_once` 及原行为：主写作成功后，单条 `RepairOutput` 超时只让该条回退安全事实文本，保留其他要点/经历并交付整稿，不拼接原始聊天。语义核验、抽取后的语义检查、修补、润色、指标补漏及容量压缩的失败恢复局部降级；规划有确定性保守替代时也保留原降级。代码注释明确主要抽取/写作调用失败、必要且无确定性替代的模型路由失败与次级调用失败的边界。
- 主要 `OnePassOutput`/`WriterDraft` 调用最多尝试两次，每次有独立超时；`None` 恢复原来的结构重试入口，连续空响应、连续非对象、结构错误或调用故障最终抛可重试 `ChatTurnError`，不再将失败主调用报告为 `model_fallback` 成功。SSE/SQL/checkpoint 回归验证已有稿不变、保留输入并能同消息重试。结构合法但未选择条目的旧 `EmptyWriterDraft` 确定性恢复路径保持原有行为，区别于 `None`/非对象；普通流程旧桩从 `object()` 改为这种合法结构桩，保留其业务断言，原失败降级的源事实断言明确用于次级压缩。
- 去重完全移出 `save_resume_session` 和 `save_canonical_resume`，通用保存器无需来源猜测或默认去重参数。writer 产出按目标条目去重；edit_plan 后的确定性更新显式 `dedupe=True`，以及更正写回仅处理本次实际改变正文的条目，均在版本/页数计算前清理并同步引用/hash/coverage。只改排版/标题、编辑器/API 直接保存、只读聊天与恢复历史不做该清理。`test_resume_density.py` 已逐字恢复 HEAD 的原文件，包括 density=2 断言和移除第十二批新增的 noqa。
- 新增 4 项回归：主写作两次超时且旧稿不变；编辑器/API 重复内容在回执、SQL、checkpoint 和只读聊天后均保留；edit_plan 生成结果去重且撤销恢复原稿；字面更正写回去重。恢复并加强修补超时测试，空/非对象主响应与次级语义故障测试同步边界。通用模型桩补齐 OnePass/确认方案 WriterDraft 的正确结构，未放宽原业务断言；更正旧测试的预期显式应用本批要求的条目内去重。
- 验证：指定全量 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py` **1696/1696 通过，0 失败/跳过，62.702s**，日志 `/private/tmp/huhua-b12b-full-final.log`；28 份当前改动相关 Python 文件 Ruff 通过，日志 `/private/tmp/huhua-b12b-ruff.log`；`git diff --check` 通过。已恢复原样的 density 测试仍有 HEAD 既存 E402，未以新 noqa 掩盖或扩改；本次 Ruff 口径为当前有差异/新增 Python 文件。3369 份保护文件 SHA-256 均与本轮开始一致（evaluation/fixtures/checks、web/comparison*、输出材料、首页及打包脚本），mmr 原内容完整保留。HEAD 仍为 `a35a805`，未 commit/push/部署，未启动/调用 8833，未调用真实模型；没有声称新的线上或真实人物回放成绩。


## 第十六批 a 记录 · 2026-10-18

- 目标与范围：在 batch16a 完成规格 A/B/C/D：基本信息档案优先、质量迁移与失败细分、从档案选经历、read_profile/use_profile_items 及 returning 离线回放；E 不在本批范围。
- 已完成：基本信息和第一条教育（含手机/邮箱/链接）确定性沿用，完整档案不出 basics 卡；缺项表单与“改”；到岗时间可选；七模板联系方式投影验证。基本信息校验、结构化表单拆分、本人主体归一、同值/冲突去重、按账号幂等 superseded 迁移。归档异常按阶段及类型安全记录，区分模型/解密/数据库错误且可重试。
- 已完成：经历目录复选、岗位相关排序/预选、共用 fact_ids → prepare_graph_context 导入和 provenance、已知维度不重问；账号限定的档案工具、有界 read → use → 回复、命名回执与图/SQL 持久化；正常档案请求不再误报“没记下来”。新增 returning 人物、显式隔离数据库预置参数及十八项离线回归。
- 关键决策：联系方式只走确定性投影，保持原 model_privacy/ContactTokenStream 与 MCP PNG 占位；目录可见不等于经历自动导入；工具使用服务端账号/会话归属，不信任模型提交的 ID；没有改写作/槽位/校验链路。
- 失败做法已修正：空 ID 列表误回退默认查询；读事务迁移新 ID 回滚；迁移同事件冲突碰唯一约束；“本人”归一后漏过滤已删除 GitHub 链接；工具中途持久化与节点末尾来源分类不一致触发 source_id_reused。HTTP 离线回归已覆盖保存和回读。
- 验证：用户指定全量命令最终 1979 项 / 81.871s，1977 通过、0 失败、2 项已有私有 fixture 缺失跳过。intake DOM、JS 语法、git diff --check 通过；变更 Python Ruff 通过（旧 test_batch14b_intake.py 模块文档前 import 的十条 E402 未顺手调整）。无真实模型调用，无 8833/8834 访问，无 commit/push/部署；未改 dist 或部署脚本。
- 未完成：Claude 接手真实模型 returning 回放和 UI 视觉；线上四条旧 archive_unavailable 的精确原因、真实存量迁移结果仍需实际环境证据。离线成功不等于真实模型推荐质量已验证。
- 接手：先看 evaluation/persona-ux/batch16a-fix-notes.md（含改动文件、旧断言逐条理由、迁移恢复边界和回放命令）。returning 需本地独立服务已初始化的 SQLite，使用 --returning-db 并保持服务与 runner 加密配置一致；合成账号凭证只留内存。真实回放不要指向生产或用户数据库。
## 2026-10-18 第十六批 b：记忆导入（规格 E，本地，未 commit/push/部署）

- 目标与范围：只完成 `docs/development/2026-10-18-batch16-plan.md` 的 E；A–D、intake/public_reply/resume_graph、dist 和部署脚本未改。接手分支 batch16b，仅规格文件预先未跟踪，未修改它。
- 已完成：新增已鉴权的提示词 GET 与记忆导入 POST；固定中文导出提示词为后端单一来源，枚举与共享 FactCandidate 对齐，uncertain 标在 evidence。JSON 优先严格校验；失败回退档案抽取器 source_kind=import，仍做联系方式脱敏和字面依据检查。输入最多处理 100000 字/200 条，截断有提示；分批 ≤50 调原 propose_to_inbox，复用去重、30 天过期和人工采纳，跨批同事务，不直接入档。
- 已完成：档案面板复制提示词/粘贴/提交/结果/查看待确认，失败保留输入；MCP prompt `import_memory_to_profile` 与 /connect 话术/复制入口。未新增 CSS。
- 决策与失败做法：自动归档 worker 不适合导入的人工确认边界，保持原来源限制。初稿 token_id=None 经静态检查发现违反原表非空约束，测试前改为来源标记 web-memory-import，不授予 PAT 权限或改表。旧测试仅精确扩展 MCP prompt 目录集合；其余旧断言未放宽。
- 当前验证：新增 16 项回归。指定离线全量 1977 项（1975 通过、2 项原有私有样例跳过），0 失败/错误，82.605s；Ruff、JS 语法、DOM 和 diff 检查通过。日志系统临时目录 `huhua-b16b-tests.D6Vry7bb1j`，完整路径见修复说明。
- 未完成/接手：本地规格 E 无阻塞。下一步由整合任务合并 A–D，再由 Claude 做视觉；真实模型/外部 AI 导出/在线 MCP 尚未验收，不得以离线桩代表线上效果。未启动或访问 8833/8834、未调用真实模型。
- 文件与说明：新增 `backend/app/services/profile_memory.py`、`backend/app/schemas/profile_import.py`，接入 api/profile、profile_archivist、mcp/server、web/account-profile、connect；完整文件、根因及测试在 `evaluation/persona-ux/batch16b-fix-notes.md`。本 mmr 仅追加，原交接完整保留。

## 2026-10-19 第十七批 s：DeepSeek 多步工具编排 spike（batch17s）

- 目标：仅做第 0 期协议和可行性验证，不接入线上图，不替换 route_by_stage 或阶段状态机。
- 完成：新增 `agents/orchestrator_spike.py`，现有 OpenAI SDK 流式调用支持 off/thinking，完整保留 reasoning_content、tool_calls 与 ID；最多 4 次工具执行尝试 + 1 次最终回复。九个默认内存假工具可注入，实现可选 decoder/fact_extractor 真实适配器（仅本轮内存）。来源 ID、工具错误、预算和联系方式保护由代码处理。
- 完成：`scripts/run_agent_spike.py`、`evaluation/agent-loop-spike/cases.json` 十例、README/修复说明、`runs/stub-off` 与 `runs/stub-thinking` 报告。两模式各 10/10 符合脚本预设，不代表真实模型正确率或成本。
- 验证：新增 17 项离线单测；指定全量 2013 项，2011 通过、2 项原有跳过、0 失败，88.964s；Ruff 通过。SDK 流式分片/序列化用 httpx.MockTransport，无真实模型调用。未修改已有断言。
- 决策及失败做法：当前 langchain-openai 1.6.3 转换器丢失 reasoning_content，采用原始 SDK 字典而非 additional_kwargs 假定透传；若思考内容含联系方式则停止后续请求，不破坏原样回传也不泄露隐私。新测试首次命中提示中与短案例原句重合，改为通用表述后通过，未放宽断言。
- 未完成/接手：由 Claude 按 README 在有网络环境执行两种 `--real`（真实编排模型 + 假工具），逐例复核工具选择、顺序、语义、真实耗时/token 及 400；先比案例/提示哈希，不把 stub 指标当模型表现。真实业务工具与跨用户轮次续接尚未验证。
- 边界：未读真实 LLM 配置/调用真实模型，未访问 8833/8834；未改现有节点、前端、dist、依赖或另一 worktree；未 commit/push/部署。当前仅本地新增 spike 文件与本节追加；交付入口 `evaluation/agent-loop-spike/README.md`。

## 2026-10-19 第十七批 m：MCP 体验与网页小修（batch17m）

- 已完成：模板列表返回配置 origin 的总画廊/逐模板链接，`/resume?template=` 选中并滚动；测量/预览统一固定联系方式占位，中文说明要求留空手机邮箱、导出服务端填入；12 行 instructions 覆盖五条使用流程和原安全边界；writing guide 标准栏目规则，save/export 返回非改写式栏目诊断；游客/空档案不再显示空摘要及“改”。
- 预览：本机七套含淡青平行均可渲染，未复现原部署端超时；补独立子进程 15 秒超时杀死回收、最多 2 并发，工具及模板资源返回安全超时与网页回退提示。导出渲染/联系方式填充和既有权限/限流保持原行为。固定占位是保守预算，超长联系方式/额外链接仍需核对最终导出页数。
- 验证：指定离线全量 **2008 项，2006 通过、2 跳过、0 失败/错误，100.518s**；MCP 定向 63 项通过，DOM / Ruff / JS 语法 / diff 检查通过。新增 12 项及增量 DOM/协议断言，覆盖七模板真实 PNG、无额外 scope、超时进程回收、隐私、栏目不改写、链接与空表单。日志 `/tmp/huhua-b17m-full-tests-final.log`。
- 失败与决策：旧 spy 改到新预览入口；联系方式占位多一行，单字临界分页测试移除一条填充行，仍严格断言 2 页→1 页；SDK 资源错误改用 ResourceError，避免隐藏超时原因。完整说明：`evaluation/persona-ux/batch17m-fix-notes.md`。
- 接手边界：未访问 8833/8834，未调用真实模型，未改 dist，未 commit/push/部署。未验证真实 Codex 自动审批或线上超时根因；下一步如需线上验收须另行授权部署。本节仅追加，未重写既有交接。


## 第十七批 r · 2026-10-19：PDF CJK 子集与预览超时（本地，未提交/部署）

- 在 batch17m / HEAD 0a35e35 的 m 未提交改动上继续；其余 m 文件与两份只读源 TTC 的 SHA-256 不变。使用标准字符集构建 SC Regular/Bold CFF 子集（合计 7.18 MiB），保留原轮廓及完整系统字体回退；新增 scripts/prepare_pdf_fonts.py、PDF 固定字体资源白名单。未采用近似转 TTF 或 full_fonts。
- 指定 Noto CJK + 强制 fontTools 的本机 3 次中位数：t001 3.093s → 0.688s、299495 → 125407 字节；七模板 0.581–0.852s。144 DPI 七模板与独立罕见字/繁体/假名/符号、400/700 探针均零像素差、文字一致、无缺字；完整字体回退仍慢（探针 3.016s）。这是 macOS arm64 实测，不是生产 4 核 Linux 达标证据。
- 预览执行超时 Settings 默认90s，公共画廊排队默认300s，并发仍2；私人请求满槽仍503。同模板合并并发miss、异常不缓存；构建公共PNG并校验源码/字体/图片指纹，七图首次读取34ms、热缓存0.31ms。单张预览3次中位数1.034s；无预生成资源七张并发4.610s、7/7完成。
- 新增11项回归；指定全量2019项，2017通过、2项原有私有样例跳过、0失败/错误，104.575s；日志 /tmp/huhua-b17r-full-verified.log。run_tests隔离公共预览目录，避免镜像内预生成PNG绕过旧超时断言；原测试断言未改。Ruff/diff通过。
- 交付 evaluation/persona-ux/batch17r-fix-notes.md（方案表、Dockerfile.release插入层、上线/回退步骤）及 batch17r/ 下原新PDF/PNG/差异图/实测JSON。下一步在隔离生产镜像构建字体与七图、同4核Linux复测后再发布；发布包须补入两个构建脚本，旧allowlist未包含根scripts。原408ms HTTP500缺少异常证据，未声称已修复。未访问8833/8834、调用真实模型、改dist、commit/push/部署。

## 2026-10-19 第十七批第 1 期 P1b：编排节点与接线（batch17b）

- 目标/范围：仅完成规格的 P1b。新增生产 orchestrator、AGENT_MODE（默认 off）、自由输入分流、loop 自动表单关闭、首屏四入口与 SSE 工具进度；未实现 P1a 业务适配器或 P1c 评测。
- 已完成：OpenAI SDK 流式与思考字段回传、最多 4 次工具尝试/5 次模型请求（包括一次降级）、超时/取消/来源 ID/联系方式保护、状态增量合并、独立事实保存与最终 checkpoint/SQL 对账。结构化表单、问题卡作答、方案选择及 requested_task 保留原路径；loop 记录材料不自动投影出稿。
- 关键决定：orchestrator_tools.py 仅契约 stub，明确返回 adapter_not_installed，合并时由 P1a 替换；stop=True 严格收束，已执行工具不因降级重做。auto 响应缓冲确认无工具后发布，强制最终响应实时流式，避免工具旁白冒充最终正文。日志仅计编排 SDK 请求，不声称包含业务适配器全部成本。
- 验证：新增 23 项离线测试；指定全量 2036 项（2034 通过、2 项原有跳过），0 失败/错误，407.757s，退出码 0。Ruff、JS/HTML 内联脚本语法、交接 shell 语法、diff 检查通过。最终日志 evaluation/agent-loop-spike/p1b-full-tests.log（忽略文件）。未放宽或修改旧断言。
- 失败做法：旧精简配置对象无 AGENT_MODE 导致首轮 12 个错误，改为缺字段默认 off；新增测试辅助参数重名及额度表注册时序已修正。虚拟环境无 Ruff 模块，使用已有系统 Ruff，未安装依赖。
- 当前状态/接手：P1b 本地实现已完成，未 commit/push/部署、未改 dist、未启动/访问 8833/8834、未调用真实模型。Claude 合并 P1a/P1c 后按 evaluation/agent-loop-spike/p1b-notes.md 的接口说明及 8847 独立数据库命令运行真实回放，再做视觉与业务联调验收；真实模型质量、首字耗时及适配器效果未由本批验证。本 mmr 仅追加，原内容保留。
## 2026-10-19 第十七批第 1 期：P1a 工具适配器

- 目标与范围：仅完成 batch17a 的 P1a；遵守本期 ToolOutcome / TOOLS 接口，不改 P1b 编排/路由/配置/前端及 P1c 回放。
- 已完成：新增 `backend/app/agents/orchestrator_tools.py`，统一 10 个工具、严格参数、原始 HumanMessage 来源、联系方式脱敏与确定性投影、问题/方案卡、事实先保存、写稿/编辑事实护栏、可撤销版本及不写 PDF 的测页；新增 `tests/test_orchestrator_tools.py` 的 36 个离线测试。
- 关键决策：调用既有抽取/持久化/写作/编辑/测页服务，不调用整个阶段节点，避免引入阶段门槛和隐式事实恢复；写稿/方案序列化禁止从未记录聊天补字段。成功 write_draft 的 stop=True 严格遵循共同接口。
- 验证：指定全量命令最终 2049 项，2047 通过、2 跳过、0 失败，92.964s；新增测试在全量发现环境下 36/36 通过；Ruff、语法、空白检查通过。未修改任何旧断言。
- 失败做法：旧混合材料拆分会漏掉明确本人标签的前缀，已在适配器补界限；writer 异常按真实 ChatTurnError 契约保留旧稿；新测试曾受 benchmark 的被拒文本诊断开关影响，显式隔离生产开关后保留原断言通过，详见说明。
- 未完成：真实模型与 P1b/P1c 合并后的跨轮回放由 Claude 运行；本期没有调用真实模型、访问 8833/8834、commit、push、部署或修改 dist。
- 接手：阅读 `evaluation/agent-loop-spike/p1a-notes.md`；内含工具参数、ToolContext 生命周期、状态/事件合并、持久化上下文要求及可直接执行的离线与真实业务工具 smoke 命令。合并时保留 _intake_saver/profile_runtime；总预算、超时、模型计量、最终回复/持久化由 P1b 接线。
- 当前状态：工作在 batch17a，代码与说明待合并；本节仅追加，未改动此前交接内容。
## 2026-10-19 第十七批第 1 期 P1c 评测（batch17c）

- 目标/边界：只补评测；生产工具、编排、路由、配置、前端及 dist 未改。未调用真实模型、访问 8833/8834、提交、推送或部署。
- 已完成：spike cases v2 共13例，04/08允许写后追问，新增档案+方向、介绍即出稿、换方向；旧12份真实报告逐字节不变。run_persona 支持 --agent-mode off|loop 与 cold/upload，保留原8人物检查；report 修复 returning 派发并输出模式、首稿轮数、调用数及耗时对比。
- 关键决策：显式评测服务 serve.py 设置并核验实际 AGENT_MODE，独立数据库/端口；评测外壳统计每轮实际模型HTTP尝试（含内部调用/重试），缺证据保留null；出站联系方式未脱敏则阻止发送并标失败。不改变 ToolOutcome/TOOLS 或替生产代码修补脱敏。
- 验证：新增20项回归通过；spike原17项通过（13例×2模式），CLI stub各13/13。指定全量最终2033项：2031通过、2项原有跳过、0失败，278.247秒；Ruff/AST/diff及文档命令语法通过。
- 失败记录：新邮箱断言曾把中文标签算进地址，修正ASCII边界，未放宽投影检查。中间全量一次旧writer计时断言170ms超过85ms；保持原断言，单文件17/17及最终全量均通过，失败日志保留。
- 未完成/接手：真实回放待Claude合并P1a/P1b后按 evaluation/agent-loop-spike/p1c-notes.md 启动8847/8848隔离服务，先cold/upload/returning再其余7人物，生成off/loop对比。cold四条输入与≤3总轮首稿可能冲突，严格检查未改；case05旧追问规则亦保留。固定材料词法检查不等于通用语义事实保真或真实质量提升。

## 2026-10-19 第十七批 d：范围句经历拆项与 DSML 回归（batch17d）

- 目标/范围：修复粘贴旧简历的角色、具体工作、范围行被拆成独立项目；补编排 DSML 与写稿结果状态过滤单测。起始 HEAD `ae9547f`，仅本地修改。
- 已完成：名称正则不再跨换行拼接动作与否定句，拒绝否定/职责边界名称；显式经历接续紧邻的标注字段，恢复遗漏原文及正向角色，遇新栏目/普通文字停止归属。抽取专用 `experience_constraint` 保留限定为事实，原成稿清理规则不变。旧 collecting 和 record_facts 两条真实代码路径离线验证均只保留一个项目，保留全部计数、动作、环境和职责限定，出站联系方式脱敏。
- 根因/决策：即使模型桩输出正确单项，旧确定性名称识别也会生成“不是”；先修主体范围与名称识别，不盲目合并历史条目。真实模型原始 JSON 未采集，不能归因于模型先拆错；正常/拆项/稀疏/空 JSON 均由离线桩覆盖，人物仅在测试 fixture/测试代码。
- 编排：修复 auto 回复 DSML 前有正文仍误重试，以及无完整标记时吞尾部；覆盖所有标记切分位置、仅一次纯文字重试、伪调用不进历史、不执行伪工具、联系方式和占位符分片。`_document_outcome` 现有状态白名单通过新增测试，无需改生产适配器。
- 验证：新增 13 项测试；指定全量最终 **2104 项，2102 通过、2 项原有跳过，0 失败/错误，86.197s，退出码 0**。Ruff、7 文件 AST、diff 检查通过，旧断言未修改/放宽。日志 `evaluation/agent-loop-spike/p1d-full-tests.log`（忽略文件），说明 `evaluation/agent-loop-spike/p1d-notes.md`。
- 失败做法：首版扩展共享 `constraint_only` 导致正文范围被误删，全量出现 14 个失败断言；已恢复旧正文规则并隔离抽取判断，原断言全部通过。新 collecting 桩构造与角色断言按实际契约修正，详见说明。
- 未完成/接手：真实模型回放与成稿质量未复测；如后续获授权，可运行该 fixture 的 off/loop 隔离回放并核对模型原始输出。本次未访问 8833/8834、未调用真实模型、未改 dist、未 commit/push/部署；测试未写死临时路径。本节仅追加，原交接内容保留。

## 2026-10-19 第十七批第 2 期：P2a 时延与上下文（batch17e）

- 目标/边界：只改 `orchestrator.py` 非 SYSTEM_PROMPT 部分并新增 `orchestrator_context.py`；P2b 适配器/提示词与 P2c runner/旧测试未改。本节仅追加。
- 已完成：模型专用事实/稿件/岗位/方案摘要；最近 3 个用户轮原文与更早确定性摘要；sources 仅送索引，服务端原文与工具状态完整；固定 system 隐私前缀及 schema 顺序；收尾 `AGENT_FINAL_MODE=thinking|off`；逐次 prompt/completion/reasoning/cache token、phase/mode、耗时日志，不含正文。
- 关键决策：先脱敏再截断，不摘要当前 thinking 回传；read_profile 选择 ID 保留；关闭收尾思考只作用于强制最终请求，决策仍 thinking；默认暂保留 thinking，待 Claude 实测确定。设置在独立 context 模块读取环境/.env，不越界改 config.py。
- 验证：现有编排 82/82；新增独立回归 15/15（evaluation/agent-loop-spike/test_p2e_context.py）；指定全量 2104 项，2102 通过、2 项原有跳过、0 失败，89.107s，退出码 0。旧断言原样保留；Ruff/AST/文档命令语法/diff 通过，SYSTEM_PROMPT 字面量与 HEAD 一致。
- 证据：从 ../huhua-b17b 只读两组完整旧 run 与人物目录；旧 loop 31 份成稿快照工具投影 JSON 字符中位 2413→739，非真实 prompt token 或性能提升证明。原 run 哈希与大小统计在 p2e-context-sizes.json。
- 失败做法：超大合成 JSON 压力样本曾耗时在既有隐私正则，中断后限制测试数据规模；无分隔长英文被整体识别为邮箱导致新截断断言失败，修正样本分隔后全部通过。未改隐私服务或放宽旧测试。
- 未完成/接手：读 `evaluation/agent-loop-spike/p2e-notes.md`，先运行独立 15 项与全量命令；Claude 合并 P2b/P2c 后按文档在 8849 用独立数据库串行比较收尾 thinking/off。真实 token ≤6k/≤20k、缓存/时延/质量与最终默认值仍待实测。旧回放的 HTTP 调用计数全为 0，不作为有效成本基线。
- 当前状态：本地修改待交接，未调用真实模型、未访问 8833/8834、未启动服务、未改 dist、未 commit/push/部署。

## 2026-10-19 第十七批第 2 期 P2b 写作对齐与行为（batch17f，仅本地）

- 目标/边界：按第 2 期规格仅处理 P2b；起始 HEAD `815d22f`。生产修改限 `orchestrator_tools.py`、`orchestrator.py` 的 SYSTEM_PROMPT，以及 `resume_graph.py` 原字面更正事务的小幅抽取。另新增 `tests/test_orchestrator_writing.py` 与 `evaluation/agent-loop-spike/p2f-notes.md`；本节只追加，未改旧交接。
- 已完成：write_draft 自动选择既有结构方案并走 phase=write/labeled writer，保留确认方案和用户写法；record_facts/edit_resume 共用旧数字更正事务，原话授权、正文/事实引用/版本同步，成功后 stop 避免整稿重写。联系方式已请求状态写入 session_constraints，跨轮不重复索要，明确导出仍缺时可再问；工具回执去内部引用，保留档案选择句柄，导入回执逐段点名；开场提示只用标注假设的无编造数字示意。
- 关键决策：不调用整个旧节点，不复制编排/抽取逻辑；旧 evaluating 分支仅改成调用抽出的同一函数，节点行为不变。测试人物只在测试材料，不写入生产提示/手册。第 1 期 run 目录在相邻 huhua-b17b，只读核对，未改冻结结果。
- 验证：新增 11 项测试方法，覆盖两类 AI 产品 labeled 成稿、原写法、数字更正与旧节点一致、失败/歧义/参考来源、持久化回调、跨轮联系方式及隐私。指定全量最终 2115 项，2113 通过、2 项原有跳过，0 失败/错误，91.102s，退出码 0；日志 `evaluation/agent-loop-spike/p2f-full-tests-final.log`。Ruff/AST/diff 通过，AST 确认 orchestrator 除提示常量无改动，旧断言原样保留。
- 失败做法/未完成：未用普通抽取+整稿润色修数字；回执只删 ID 字段不足，最终补正文/诊断键引用过滤。真实模型未回放，不能宣称人物通过率提升；答案接续/检查口径仍交 P2c，实际延迟交 P2a。普通回复的联系方式约束仍需真实回放验证。
- 接手：合并三支时保留 session_constraints.contacts_requested 的模型可见状态/摘要；按 p2f-notes.md 命令在新数据库、8857/8858 串行跑 off/loop 全人物，并核对 canonical 正文与引用。未访问 8833/8834、未调用真实模型、未改 dist、未 commit/push/部署。
## 进行中记录
- 2026-10-19 P2c（batch17g）：只改评测与指定比较脚本；第 1 期两组 run 在 sibling huhua-b17b 只读核对。确认 aipm 首稿终止截断后续问答、returning 字面“导入”误判；career/design 重复索要联系方式属真实失败，保留。旧回放 HTTP 计数全为 0，新增编排指标独立取证，不将旧零值当作零成本。

## 2026-10-19 第十七批第 2 期 P2c 评测交接（batch17g）

- 目标/边界：仅 P2c；改 evaluation、评测测试和规格点名的 scripts/compare_persona_runs.py。本文件仅追加；生产编排/工具/提示词/手册、其他 worktree 与 dist 未改，未调用真实模型、访问 8833/8834、commit/push/部署。
- 已完成：loop 的 aipm/aipm_real 首稿后继续真实问题卡/纯文本追问，绑定实际 turn_id，使用原 VALUES 和 INTAKE 来源；off 停止流程、真实人物前四轮和严格失败断言保留。returning 接受完成态“选用/写入”且核对同轮两段可见经历；联系方式按轮去重、分句识别，真正重复仍失败。新增两目录比较脚本、逐轮/逐次编排 token/耗时及共同断言表。
- 根因/关键决策：旧回放 78 轮 HTTP 调用数全为 0，实际 SDK 继承 httpx2.AsyncClient，旧评测只 patch httpx；现兼容两种同步/异步传输并在发送前阻断联系方式。编排指标从现有日志做数值白名单，不保存正文/思考；缺失为 N/A，计数矛盾不以推算填零。真实 SDK + MockTransport 离线验证通过。
- 证据：第 1 期只读来源 ../huhua-b17b/evaluation/persona-ux/runs/p1-{off,loop}-all-5，共 178 份文件核对一致。冻结重评 off 113/118、loop 147/168；唯一变动 returning.profile.import_receipt FAIL→PASS，属判定纠错，非模型质量提升。报告 evaluation/persona-ux/p2g-p1-comparison.md。
- 验证：新增 18 项；指定全量 2122 项，2120 通过、2 项原有跳过、0 失败/错误，85.412s，退出码 0。旧测试文件/断言未改。Ruff、10 文件 AST、交接命令语法和 diff 检查通过；最终日志 evaluation/agent-loop-spike/p2g-full-tests.log（忽略）。
- 失败做法：首版只测 httpx 未覆盖当前 SDK，虽中间全量通过仍补实际 SDK 传输回归；新增测试闭括号、分句“还差”和 SDK 异常包装预期已修正，详见 evaluation/agent-loop-spike/p2g-notes.md。
- 未完成/接手：Claude 合并 P2a/P2b/P2c 后按 p2g-notes.md 的完整命令启动 8847/8848 独立临时数据库，顺序跑 off/loop 全人物并生成简表/明细；trap 清理服务。真实质量、token 预算与缓存命中未实测，旧零计数不能代表零成本或隐私覆盖。本轮无遗留应用服务或付费任务。

## 2026-10-19 第十七批 P2h：先写后问、写稿回退与编排耗时

- 目标/范围：batch17h 从 31cfd13 接续，仅改 orchestrator.py、orchestrator_tools.py、orchestrator_context.py 和对应测试；不改旧图节点、评测判定、手册或 dist。本节只追加，前文保留。
- 已完成：write_draft 后复用 question_candidates 生成一个校验过的 followup；预算内只再允许 ask_user，预算不足/模型漏调用/失败时确定性附卡，状态与事件保持一致。成功出稿收尾补齐遗漏的联系方式请求，跨轮不重复；档案回执按第十六批逐一点名规则补漏去重。
- 根因/决策：cold 实为 plain/data 路径，校园身份拆为两个条目，方案错误隐藏了动作所属条目，跨条目引用被 invalid_refs 正确拒绝。仅在 record_facts 对明确同名、同轮、唯一且无日期冲突的占位校园条目复用旧合并事务，保留原 fact IDs/来源与审计；不放松 fact_guard。loop 写稿空正文复用 c6 active facts 规范化兜底，尊重隐藏/备用/零行/作用域，并更新引用、版本与测量。
- 已完成：write/edit 投影会话岗位；tech 的长方向附括号技能说明会被 safe_objective 整串清空，现提取合法岗位名，保留不同的手改头部。联系方式仍不进模型。
- 耗时：orchestrator_turn 新增 tools[] 的名称/秒数/状态/固定错误码，自动附卡单列，扣除嵌套计时；无正文/参数。AGENT_FINAL_MODE 默认 off，仅强制文字收尾关闭思考，决策仍 thinking，可显式恢复。自然语言质量与真实耗时收益待回放；record_facts 后没有硬编码直跳写稿。
- 验证：最终指定全量 2149 项，2147 通过、2 原有跳过、0 失败/错误（85.884s，退出码 0）；额外 P2e 上下文 15 项全过（0.458s）。新增 P2h 回归 16 项；Ruff、6 文件 AST、diff check 通过。旧 SDK 思考协议测试显式选 thinking，原断言保留；P2e 仅按需求更新两处收尾默认值期望。
- 失败做法：没有沿用 labeled 导致 cold 失败的假设；没有绕过跨条目核对；新增测试曾误把无 match_plan 当无候选，已按手册候选实际行为修正测试场景。第一次全量后补长方向回归，再跑最终全量。
- 当前状态/接手：未 commit/push/部署，未调用真实模型、启动应用服务或访问 8833/8834。说明见 evaluation/agent-loop-spike/p2h-notes.md；旧产物对比见 p2h-frozen-comparison.md。returning 本轮实际已点名两段，旧检查器完成态表达不兼容仍保留失败，评测任务需核对；本任务不为字面通过重复回执。下一步由集成任务合并后做真实回放，核对卡片续答、cold 正文、tech 头部及工具分项耗时；旧产物不是修复后验收。


## 2026-10-19 P2i：loop 问题卡作答与编排衔接（batch17i，仅追加）

- 目标：问题卡答案确定性落库后交编排，统一深挖预算，回写名称/时间/角色，确保非空回执，联系方式全会话一次，纠正 returning/ops 检查器误判。
- 已完成：loop 的 answers 从 collecting 分流到 orchestrator；答案及关闭记录在模型前保存，不二次自由抽取。与旧回放共用 6 轮常量，卡片/文字按用户轮合并计数；最后一张合法卡仍可提交，整轮不知道/跳过后收尾。字段事实保留来源，按 item_id 同步标题与版本；真实名称不覆盖，未知时间不猜。公开流与 checkpoint 同样过滤重复/越限提问，并附确定性答卡回执。off 默认路径保留。
- 关键判断：ops 原失败的第二轮是“手机拍摄 + 文案由店长提供”词法误判；首轮另外确有模型文案与代码补问重复，已分别修复。returning 现在逐名称核对完成态及同轮可见数据，仍拒绝不点名、将来、否定和失败。旧断言仅改 loop answers 路由和导出不再重复要联系方式，两项理由见说明。
- 验证：最终指定全量 2162 项（2160 通过、2 原有跳过），0 失败/错误，88.102s；新增 P2i 13 项，含两人物 runner + 真实 LangGraph/writer 离线桩和 stream_agent/内存数据库回读。额外 P2e 上下文 15 项通过；14 份 Python AST、Ruff、diff 检查通过。未调用真实模型、未访问 8833/8834、未启动应用服务、未改 dist、未 commit/push/部署。
- 失败做法：按句流式缓冲初稿漏算未发布尾巴，导致无句号文本重复；保留旧断言修复。预算测试误用移除了 turn_id 的模型投影卡，改为实际 UI 卡。没有放宽事实/深度/写法/隐私检查。
- 当前状态与未完成：修复在本 worktree，尚未提交。新真实模型质量/延迟未验证；冻结重评仅 returning/ops 两项判定纠错，aipm 11/14、aipm_real 5/16 的旧失败原样保留。
- 接手：读 `evaluation/agent-loop-spike/p2i-notes.md` 与 `p2i-frozen-comparison.md`，审阅 diff 后按负责方流程整合；需要新授权的真实回放仍由后续任务执行。日志 `p2i-full-tests-final.log` / `p2i-targeted-tests.log` / `p2i-context-tests.log` 按仓库规则忽略。相邻 worktree 未改。

## 第十七批第 2 期第四轮 P2j（2026-10-19，batch17j）

- 目标：loop 出稿后先补主经历标题，联系方式兜底去重，首稿验收按首次可写材料起算。起点 `9634dae`；本节仅追加，旧交接原样保留。
- 已完成：按当前正文及已采用方案选主经历，一张卡问缺少的名称/起止时间/角色；模型不能替换确定性卡，预算耗尽和失败仍自动附卡。复用 P2i 答案/标题回写与追问上限；off 收集行为不改。design“需要的话补一个”已有请求时不再追加。首稿材料起算 ≤3，同时保留会话总轮次与材料起始轮次。
- 验证：指定全量 2169 项，2167 通过、2 原有跳过，0 失败/错误，86.544s；定向 97 项、额外 P2e 15 项全过，AST/Ruff/diff 检查通过。aipm/aipm_real 离线 runner 在出稿首卡补标题，作答后真实名称、日期、角色和定位完整，引用/hash 与手机/邮箱不进模型断言保留。
- 失败做法：首次把 sections 当字符串列表导致漏卡，已按 kind 对象列表修正且回归通过。没有放宽原交付质量断言；旧首稿时点断言因明确需求变更而调整，理由逐项写入说明。
- 未完成/边界：未做新真实模型回放；冻结 design 第 2 轮“不用现在补”仍被旧 contacts_once 检查器误计，留待评测任务复核。冻结 aipm_real 仅首稿时点重评从失败变通过，不代表旧标题或正文失败已消失。
- 当前状态/接手：实现及文档未提交。先看 `evaluation/agent-loop-spike/p2j-notes.md`、`p2j-offline-replay.json`、`p2j-frozen-timing.json`；后续授权后再验证真实回放。未访问 8833/8834、调用真实模型、改 dist、commit/push/部署，未写相邻 worktree，无遗留后台任务。

## 第十七批第 2 期第五轮 P2k（2026-10-19，batch17k）

- 目标/范围：起点 `e51b15e`；修标题合题与答卡后按岗位继续深挖，本节仅追加。已读 P2h/P2i/P2j；相邻 all-4/var-1 回放只读核验，aipm 均为同样三个失败项。
- 已完成：起止时间合并 dates 一题，名称/角色各一题；日期答案确定性投影两字段且保留原答案来源。有效答卡固定记录→按需调用原 writer 定向更新条目→同轮一张后续卡→收尾，不依赖模型再次决定提问。沿用确认写法、labeled/guard/引用/版本；无新深挖事实不重写正文，异常保留旧稿和已保存事实。
- 关键决策：抽出原 off deepen 岗位维度表共用，保留 question_candidates 具体题干和普通岗位候选优先级；不调用整个旧节点。未知/跳过只永久关闭本维度，明确停止及原六轮共享上限保留，末张答案仍可写入。模型收尾失败不丢卡、同轮不得再问第二张。
- 验证：新增 8 项回归；稀疏 aipm 离线 runner 为 dates→problem→my_work→decision→iteration→evaluation→停止，最终正文含问题/决策/迭代/现状，9 项原人物检查全过并逐标签引用卡片答案。最终指定全量 2177 项：2175 通过、2 原有跳过、0 失败/错误，83.399s；额外 P2e 15 项、9 文件 Ruff/AST、diff 检查通过。
- 失败做法：一度将维度表排在普通岗位候选前，导致 P2h 顺序断言失败，已修复并保留原断言；日期合题、未知继续及对应旧断言变化逐条见说明。离线写作桩最初复述原话，改桩并加强完整人物检查，未改生产 writer/提示/手册。
- 未完成/接手：未做新真实模型回放，不能宣称真实 aipm 14/14 或延迟改善。见 `evaluation/agent-loop-spike/p2k-notes.md`、`p2k-offline-replay.json`；真实复测需由后续授权任务执行。未访问 8833/8834、启动应用服务、修改其他 worktree/dist、commit/push/部署；本地实现与交接待审阅。

## 第十七批第 2 期第六轮 P2l（2026-10-19，batch17l，仅追加）

- 目标：修复同一消息中新建的“占位名+动作”和“真实名+时间”拆分；开场审阅并保留 fact_corrections.py / resume_graph.py / orchestrator_tools.py 的中断改动，基线 3a6daf1。
- 已完成：record_facts 及旧 collecting 共用保守补充规则：同栏目唯一新占位/真实名二条、真实名在本人消息原文、全部事实来源同轮 chat、日期无冲突才合并。保留原事实/来源/限制/笔记/链接和 merged_from；P2h 原强证据路径不变。未解决的拆分在 write_draft 返回 insufficient + experience_identity_unresolved，同轮附一张归属澄清卡；覆盖占位已隐藏和真实名无事实，保留停止/关闭/预算规则。
- 验证：新增 12 项离线回归，冻结快照合并为一条，8 条事实（含 3 条限制）原样保留；实际 writer/guard 配离线桩正文非空、编造值被拒、引用/hash/隐私检查通过。最终指定全量 2190 项：2188 通过、2 原有跳过、0 失败/错误，83.268s。P2h/P2l/职责归属定向 35 项全过，4 文件 AST/Ruff/diff 检查通过，旧断言未改。
- 失败做法：首次全量 1 项旧归属回归失败，新 turn_id 未传给原 bind_role_followup 导致错挂事实无法迁移；补传同一 ID 后原断言及最终全量通过。未放宽 writer 跨条目引用，也未通过名称/日期编造动作。
- 当前状态/未完成：修复、测试和说明均未提交；未做新真实模型回放，不能宣称真实 cold 已全过或延迟改善。无应用后台进程；未访问 8833/8834、调用真实模型、改其它 worktree/dist、commit/push/部署。
- 接手：看 evaluation/agent-loop-spike/p2l-notes.md 和 tests/test_orchestrator_p2l.py，审阅当前 diff 后按集成任务处理。最终日志 p2l-full-tests-final.log；首次失败日志 p2l-full-tests.log，均按规则忽略。后续真实回放由负责方另行执行。


## P2l 中断后复核交接（2026-10-19，仅追加）

- 目标/已完成：承接并审阅 batch17l 基线 3a6daf1 上的全部未提交改动；保留同消息唯一占位/真实名合并、旧 collecting 接入及 insufficient 归属澄清卡，无需追加业务修改，旧测试与断言未改。
- 关键决策：继续以同轮来源、新建条目、原文具名、唯一候选和无日期冲突为新增合并边界；沿用原事实/来源/限制/merged_from 和 writer 核对，未满足条件就明确询问归属。
- 本次验证：指定全量重新通过，2190 项、2188 通过、2 原有跳过、0 失败/错误，83.312s，退出码 0；包含 P2h、12 项 P2l 和职责归属回归。4 文件 AST、Ruff、diff 检查通过。日志 evaluation/agent-loop-spike/p2l-full-tests-resumed.log；详情 p2l-notes.md 的中断后复核节。
- 当前状态/未完成：代码、测试与说明均未提交；未做新真实回放，不能宣称真实 cold 已全过。测试进程已结束，未启动应用服务；未访问 8833/8834、调用真实模型、改其它 worktree/dist、commit/push/部署。本次没有新增失败做法。
- 接手步骤：审阅当前 diff 和 evaluation/agent-loop-spike/p2l-notes.md 后交由集成任务处理；真实回放仍由负责方另行执行。


## 2026-10-20 batch17b 合入 batch17m：临时合并验证

- 目标与边界：整合 batch17b `0f0af61` 和 batch17m `d4a0aed`，保留编排/评测与 MCP/渲染/编辑器两边行为；AGENT_MODE 默认 off。仅使用已跟踪分支内容，没有复制相邻 worktree 的未跟踪字体、PNG/PDF 或 batch17r 产物；未改 deploy/、发布脚本，未 push/部署。
- 冲突处理：mmr 的两边追加记录全部保留，按提交时间将 m/r 放在 spike 与 P1 之间；web/index.html 使用统一版本号 20261020-b17bm。其余共享文件自动合并，非重叠改动逐字节与对应父分支一致。
- 验证：指定全量在临时合并树运行，Ran 2221 tests in 142.287s / OK (skipped=2)，退出码 0（2219 通过、2 跳过、0 失败/错误）；另在 AGENT_MODE=loop 下复用 5 项 MCP 草稿生命周期回归全过，独立 P2e 上下文 15 项全过。JS 语法及 diff 检查通过。无额外业务修复。
- 接口：MCP save/export 新参数尾部可选，编排未直接调用它们；共享 PDF/测页签名、build_graph 与 canonical 保存契约保留，编辑器 session 参数和事件不变。预览执行超时默认 90s，公开预览排队 300s。
- 本轮阻塞与接手：原 worktree 的 Git 元数据位于只读的 ../huhua agent/.git，无法创建 ORIG_HEAD.lock；本次会话未更新源 batch17b，也未生成 merge commit。临时目录 /private/tmp/huhua-b17bm-integration-6dbwu3u7 保留合并补丁、冲突文件、测试日志与 finish-merge.sh；在具备 Git 写权限的环境执行该脚本，会校验两支 HEAD/干净状态，完成实际合并、再次全量测试并提交中文 merge commit。此条记录描述临时验证，实际整合状态以 Git 为准。


## 进行中记录
- 2026-10-21 batch18a：基于 627a06f，实现 loop 同次流式回复附带并剥离 next_hint，通用意图白名单防编造；带 from=mcp 的已登录读取才区分跨账号，前端复用退出并保留链接。仅本地，离线桩与全量验证进行中。
- 2026-10-21 batch18a：新增 19 项离线回归，相关 32 项通过；首次全量的旧 Request 缺 query_string 导致 3 个子场景错误，改为先检查账号身份再读 from 参数，保留旧断言。修复取消后 hint 残留并补会话切换回归，最终全量运行中。


## 2026-10-21 batch18b fix handoff archive

# 胡话简历交接

## 目标
第十八批 b：项目 / 工作经历新增可选技术栈行；保持“先写后问、不编造、引用可追溯”。FastAPI `backend/`、静态前端 `web/`、Jinja 模板。线上配置为 `AGENT_MODE=loop`，本次未改线上环境。

## 已完成
- 2026-10-21：在 `batch18b`（HEAD `b9b4134`，batch18a）完成 tech_stack schema、确定性别名与来源校验、loop / 旧 writer、纯技术 bullet 迁移、字面增删。
- canonical / SQL / checkpoint、版本 / 撤销 / diff、局部重写、档案投影及撤销均保留字段和引用；网页输入、变更卡、核对页、MCP 指南 / 校验 / 保存 / 预览 / 导出贯通。
- 全部 14 个模板文件输出标题下独立技术栈行及 field-path；当前注册可选仍为 7 个。DOCX 同步；真实 PDF 测量计入新行。静态资源版本保持 `20261021-1`。
- 新增 35 项测试；最终全量 2264 项，2262 通过、2 项既有私人材料跳过，0 失败。30 个改动 Python 文件 Ruff、3 个 JS 语法检查、git diff --check 通过。

## 未完成
本需求本地实施与验收已完成。真实模型效果、线上验证和发布未做；用户明确禁止 commit / push / 部署。本轮无运行中的测试或服务进程。

## 失败做法
- 纯技术清单识别不能只看“技术：”前缀；那会误移含动作的 bullet。已限制为名称列表，并保留借助、调用、提交等动作句。
- 不能只按展示名称查普通词法词表；任意新技术需检查 active 原始事实引用。修正记录中的旧审计引文也不能复活已替换技术。
- 不能在前端别名归一前截断到 8 项；去重和上限统一由后端落实。

## 关键决策与理由
- `services/tech_stack.py` 为统一确定性入口；未知名称必须字面有据，“记忆”不扩写为“长期记忆”。复用已有 tech_stack 槽位。
- 每项引用位于 `resume_meta.tech_stack[item_id]`，使用 text_hash / fact_ids；删除用 tech_stack_excluded 保持呈现意图，撤销不回滚事实母版。
- 聊天添加经 record_facts；网页手动编辑沿用 append_editor_facts。外部 MCP 新文档缺技术来源即拒绝；已有保存稿导出沿用存储边界。MCP 总体核验仍是词法初筛。
- 整对象持久化、通用 diff 和真实渲染测量已支持新增字段，不另做结构重构。

## 当前状态
所有改动未提交；开场已有未跟踪 `prompt-batch18b.md` 保留。只更新本 mmr，未改历史文档；既有 mmr-archive.md 保持原样。文件清单、设计与测试证据见 `batch18b-report.md`。最终日志 `/private/tmp/huhua-b18b-full-verified.log`。

## 接手步骤
1. 先核对 git 状态及 `batch18b-report.md`，避免把未跟踪原始需求文件当成生成物。
2. 有新改动时按影响范围验证；需要完整复验可运行报告中的指定 Python 命令（临时数据库、模型凭据清空、仅用桩）。
3. 不自动提交或发布；后续动作以 Banz 新指令为准。

## 进行中记录
- 2026-10-21：修复轮离线解密 checkpoint 证实：通用 record_facts 删除复合技术事实，保存层 sanitize_fact_history 连带清理正文；LangChain 误报来自正文 guard 的 unsupported_tool 与技术栈别名判断不一致。正在加入原子增删、指代匹配与正文去重回归。


---

## 2026-10-21 修复轮 2 交接归档

# 胡话简历交接

## 目标
第十八批 b 技术栈修复轮：解决真实模型回放发现的数据丢失、正文重复/错拼写和工具结果误导；保持事实可追溯、局部编辑及失败不改稿。

## 已完成
- 2026-10-21：只读分析 `evaluation/batch18b-live/` checkpoint，定位复合事实误删后保存层清理；导出虚构人物第二轮状态到 `tests/fixtures/batch18b_tech_edit.json`。
- 技术栈唯一指代解析、同句增删事务、失败结果不写回、8 项上限拒绝；原事实与要点保留，保存/回读/撤销通过。
- 正文同表别名规范化、已覆盖纯罗列子句删除、引用/hash/coverage 同步与幂等；局部 bullet 清理只作用指定要点。
- guard 别名一致，实际技术栈回执和压缩上下文可见；写稿提示要求写具体用法。
- 保留 Claude 的 LIST_ONLY、split_spaced 和 TechStackProseBoundaryTests；原 test_batch18b.py 无差异。回放目录已 Git 忽略。
- 新增 24 项回归；定向 62 项通过。最终全量 2291 项：2289 通过、2 项既有私人材料跳过、0 失败；10 个改动 Python 文件 Ruff 与 git diff --check 通过。

## 未完成
用户授权的本地修复与离线验证已完成。未调用真实模型，未 commit / push / 部署，未改写原回放数据库。

## 失败做法
- 定位失败后继续通用事实提取，会把「去掉记忆」错误扩成删除包含四项技术的整条事实；保存层随后删除失活引用正文。
- 增删时重投影整项会误丢其他技术/正文；失败出口必须不携带更新。
- 正文 guard 与字段投影各用不同别名规则，且工具上下文隐藏技术栈，会产生 LangChain 已写入却被说成拒绝的误导。

## 关键决策与理由
- 统一入口 `services/tech_stack.py`；删除是呈现意图，保留事实母版。局部增删不重写已有要点。
- 纯罗列仅在技术栈完整覆盖时删除；动作仍需正文及有效引用。未知词不猜规范名。
- 失败返回 insufficient，无更新；正常新增经历叙述仍走原事实提取。

## 当前状态
修复未提交；开场未跟踪的 `prompt-batch18b-fix.md` 保留。原交接与进行中记录已追加归档到 `mmr-archive.md`。根因和验证详见 `batch18b-report.md` 末尾「修复轮」。最终日志 `/private/tmp/huhua-b18b-fix-final.log`；无本轮运行中的测试/服务。

## 接手步骤
1. 核对 git 状态；不要提交被忽略的 `evaluation/batch18b-live/`。
2. 当前修复已离线验收；有新改动再做对应验证，不自动调用真实模型。
3. 如获准真实模型回放，使用测试人物与隔离库，检查实际稿件、工具回执及原三条要点；不自动提交或部署。

## 进行中记录
- 2026-10-21 修复轮 2：只读 load_resume_session 与 checkpoint 导出 run2 虚构 fixture；发现旧版 edit_resume 缺新增条目校验，首稿清理漏匹配「并可通过」「搭建 agent 能力」，口述出稿已标遗漏但回执未显式呈现；正在补新增路由、实际 diff 回执和回归，未调用模型。
- 2026-10-21 修复轮 2：627a06f 独立源码+run2 要点桩复现 ok/changed=true 但 work_experience=[]；当前新增经历改为 insufficient→write_draft，所有 edit 回执按 actual diff；78 项 batch18b 定向通过。首轮全量仅旧 correction 测试的回执全字典比较失败，已更新契约断言，重跑全量中。
