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
- 右侧五页分别呈现 JD、经历、简历、核对、导出；左侧简短反馈、建议和具体补问。点选快捷回答即发送完整句，同组防连点，保留输入草稿与附件。
- 服务端需要处理明文，因此是加密存储与受控解密，不是端到端加密。姓名/经历按任务需要发模型，常规文本邮箱/电话先脱敏；图片识别仍发原图。
- 登录后资料默认保留至手动删除；游客按上述临时保留期处理。档案删除阻止未来使用，原聊天删除独立处理；最小旧值排除资料加密保留以阻止旧副本复活。恢复需独立最新隐私状态与可信摘要。

## 当前状态

2026-10-09 Tailor PR4：v3候选已合入主工作区，784/784与Ruff/diff通过，尚未真实模型验收。v1编辑0/24；v2编辑11/24（2无diff、3未遵循、6评分错误、2未运行），65版本53已评分/11无稿/1错误；语义疑点9，确认新增事实待Claude。v2末段与补评分遭API失败；独立官方Flash检查HTTP402，官方余额API曾返回is_available=false；Banz随后充值，只读复查is_available=true，准备恢复v3测试。v3修复结构错误一次有界重试、失败保留有效旧稿但执行明确更正/删除、原始引文与主体/动作/负面事实守卫。私有real-01-v2最终1页且无SQL误删，但writer回退导致稿质差，6/8目标满足，不能验收。交付 `evaluation/tailor-bench/pr4/summary.md`、`verification.json`、`fact-review-v2.md`。旧218基线文件哈希不变；所有已跑run保留，v3无run。PR5组件仍未接graph，未push/部署/迁移真实库。

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

PR3 已提交 `ecf7a33`。余额已恢复，接下来新开 PR4 v3 全套逐版本验收与 Claude 事实复核，达到编辑≥90%、确认新增事实0后再接 PR5 router/复合编辑。PR6 接口草稿见 `docs/development/2026-10-08-tailor-api-handoff.md`，尚未交付前端验收。真实材料旧基线见 `evaluation/tailor-bench/runs-private/20261008-saved-real-01-baseline/summary.md`：两轮均3页，第二轮执行0/8目标、0/14操作。新旧运行的事实结论分别复核，不相互借用。

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
