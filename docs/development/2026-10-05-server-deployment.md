# 胡话简历服务器交接 · 2026-10-05

服务器、HTTPS、正式发信域及游客体验版本均已上线，应用健康。未登录可聊天、上传、编辑及预览模板；导出、长期历史和 Agent 记忆需登录。登录接续已在临时加密环境以虚构模型和内存邮件验证，**真实邮件收件与生产账号登录接续仍未验收**。已完成服务器内配对加密备份，异机恢复材料与完整恢复演练仍待完成。运维沿用宿主机 Caddy，使用本文双配置命令。

## 运行位置

| 项目 | 当前值 |
| --- | --- |
| SSH | `ssh banzi`，对应 `ubuntu@49.233.252.47` |
| 主机 | Ubuntu，`x86_64`；Docker Compose `2.40.3` |
| 项目目录 | `/opt/huhua` |
| 镜像 / 容器 | `huhua-agent:20261019-1` / `huhua-app-1` |
| Compose 配置 | `compose.yaml` + `deploy/compose.host-caddy.yaml`；变量文件 `deploy/compose.env` |
| 应用入口 | 宿主 `127.0.0.1:18765` → 容器 `8765`；单 worker |
| 公网入口 | <https://resume.yikuaibanz.cn>；现有宿主 Caddy `2.11.4` 提供 HTTPS 并反代 `18765` |
| Caddy 原配置备份 | `/etc/caddy/Caddyfile.pre-huhua-20261005` |
| 应用运行配置 | `/opt/huhua/deploy/app.env`，权限 `0600`；使用独立新密钥 |
| 当前发件地址 | `Huhua <login@resume.yikuaibanz.cn>`；已在运行容器内确认加载 |
| 数据卷 | `huhua_app_data`，容器挂载到 `/var/lib/huhua` |
| 配对数据库 | `/var/lib/huhua/huhua.db` 与 `/var/lib/huhua/checkpoints.sqlite3` |

这是新的服务器数据环境，**未迁移本机旧聊天**。数据卷同时保留两份 SQLite；不要删除卷，也不要在代码更新时重新生成数据密钥或 `ACCOUNT_SECRET`。宿主机已有 Caddy 占用 80/443，不启动 Compose 中的 `caddy` 服务或 `bundled-proxy` profile。

## 2026-10-19 第十六批：档案优先 + agent 自动读档案 + 记忆导入（最新）

- 镜像 `huhua-agent:20261019-1`（sha256:4d4df719…），基于 `20261018-1`，整体替换 `backend/app/`、`web/`、`data/jianlimoban/html-template/`。代码 GitHub main `8b89711`（分支 batch16a，含 b）。包用 `git archive` 从提交直接打（无 `._*` / `.env` / `__pycache__`），deploy 32392a74…。
- 内容：登录用户基本信息沿用档案不再弹表单（缺项只显示缺的）；手机/邮箱进简历头部（仍不送模型）；经历清单改为从档案勾选；对话工具 `read_profile` / `use_profile_items`；档案基本信息校验与幂等迁移（所在地为链接、可实习时间吞并其他字段、重复条与重复冲突卡）；档案整理失败细分错误码并记异常类型；「从其他 AI 导入」（网页粘贴 + MCP prompt `import_memory_to_profile`，全部进待确认）。
- 无新依赖、无新表。演练 `REHEARSAL_OK`：4 个账号 get_profile 后 location_url 0、availability_mixed 0、basic_dup 0，二次读取幂等；**回滚演练 `ROLLBACK_OK`**：旧镜像 20261018-1 在迁移后的副本上健康启动并能读档案。容器测试 1996 项全过（skip 40：node DOM 测试 + 私有 fixture + pdftotext）。
- 备份 `/opt/huhua-backups/pre-20261019-1/`（app c4b0b1d4…、checkpoints 98e6901b…、privacy 276a26ad…）；回滚拷回 `deploy/compose.env.pre-20261019-1`（指向 20261018-1）后 `compose up -d --no-build --no-deps --wait app`。注意：回滚不撤销档案迁移（旧行保留为 superseded）。
- 线上验收：healthz 正常；`v=20261019-1` 静态资源生效（选经历卡、从其他 AI 导入）；`/api/profile/import-memory/prompt` 与 `/mcp` 未登录 401。
- 线上旧 4 条 `archive_unavailable` 仍在（旧代码未记异常类型），新版本再失败会记录具体分类。

## 2026-10-18 第十四批对话流程 + 第十五批岗位情报 + MCP 第二版（历史）

- 镜像 `huhua-agent:20261018-1`（sha256:bcb7811d…），基于 `20261017-1`，整体替换 `backend/app/`、`web/`、`data/jianlimoban/html-template/`。代码为分支 `integrate-1018`（第十四批 a–c7 + MCP 第二版 + 第十五批 a–d + 测试环境修正）。
- 内容：模型通过 ask_user 出问题卡、不知道/跳过永久关闭；分阶段对话（基本信息/经历清单表单、逐段深挖、方案门槛）；AI 产品岗按问题/决策/迭代成稿（事实先分槽再逐行改写、子句覆盖校验）；MCP 新增写法指南、本人简历预览（联系方式占位）、逐条排版诊断、模板元数据；贴招聘链接自动读岗位卡、只给方向时后台抽样真实岗位生成画像、公司卡（DeepSeek Search/Fetch，复用 `LLM_API_KEY`，Tavily 兜底）。
- 无新依赖。新增 schema 组件 `job_intel` v1（`job_intel_cache` / `job_intel_usage` 两张表，启动时创建，只增不改）。演练 `REHEARSAL_OK`（4 个账号 get_profile 正常，情报 provider deepseek/tavily 均可用）；**回滚演练 `ROLLBACK_OK`**：旧镜像 20261017-1 可在新镜像启动过的库副本上健康启动。容器测试 1961 项全过（skip 39：原 36 + 3 个需 node 的 DOM 测试）。
- 备份 `/opt/huhua-backups/pre-20261018-1/`（app 03b4aca9…、checkpoints e6e99e04…、privacy 0ce522dd…）；回滚拷回 `deploy/compose.env.pre-20261018-1`（指向 20261017-1）后 `compose up -d --no-build --no-deps --wait app`。
- 线上验收：healthz 正常；新静态资源 `v=20261018-1` 生效；贴美团招聘链接 → 读岗位卡（公司/岗位/要求/职责/加分项）并弹出经历清单卡，服务器直连读取无需代理。
- 坑：本机 macOS tar 会生成 `._*` 附属文件，打包须 `COPYFILE_DISABLE=1`；测试不得写死 `/private/tmp`。

## 2026-10-17 第十三批 UI：三页结构 + 统一顶栏 + 登录弹窗 + MCP 接入页

- 镜像 `huhua-agent:20261017-1`（sha256:c464719a…），基于 `20261016-4`，只覆盖 `backend/main.py`（新增 `GET /connect`）与 16 个前端文件，外加顶栏统一后的 `web/comparison.html/.css`（对比页其余文件与数据沿用基础镜像，仍未入库）。代码 `6dcf2b0`。
- 首页 / `/connect` / 对比页共用 `site-chrome.css` + `site-nav.js`：中间为本页章节 + 阅读进度短线，右上角 MCP 接入 / 登录 / 开始写简历；首页登录改弹窗（`home-auth.js`）；`/connect` 生成/吊销 MCP 令牌；聊天页「MCP」入口、删快捷键行、未登录登录改居中窗口；编辑页 logo 回首页。
- 无新依赖、无 schema 变更。演练 `REHEARSAL_OK`（4 个账号 get_profile 正常）。容器测试 1698 项全过（skip 36）。备份 `/opt/huhua-backups/pre-20261017-1/`；回滚拷回 `deploy/compose.env.pre-20261017-1`（指向 20261016-4）后 `compose up -d --no-build --no-deps --wait app`。
- 线上验收：`/`、`/connect`、`/chat`、`/resume`、`/static/comparison.html`、`results.json`、新 JS/CSS 200，`/mcp` 401，日志无异常；浏览器内首页登录弹窗与 `/connect` 正常。真实邮箱登录与线上生成令牌待用户验收。

## 2026-10-16 第十二批：模型故障中止 + 条目内去重（历史）

- 镜像 `huhua-agent:20261016-4`（sha256:4ba35b20…），基于 `20261016-3`，只替换 `backend/app`、`main.py`、`backend/scripts`，代码 `bf96f3d`。抽取/主写作连接错误、超时、空响应改为可重试 `E-MODEL-*`（保留原消息与旧稿，不再拼原文兜底项目）；writer/修改/更正写回时条目内去重同一指标与重复动作子句。
- 无新依赖、无 schema 变更。演练 `REHEARSAL_OK`。容器测试 1696 项全过（skip 35）。备份 `/opt/huhua-backups/pre-20261016-4/`；回滚拷回 `deploy/compose.env.pre-20261016-4`（指向 20261016-3）后 `compose up -d --no-build --no-deps --wait app`。
- 本地：五人物回放 71/71；故障注入（坏 LLM_BASE_URL）首轮返回可重试错误、无垃圾稿，恢复后同会话重发正常成稿。
- 线上验收：`/`、`/chat`、`/resume`、`/static/comparison.html` 200，`/mcp` 401，日志无异常。线上实跑对比用例三轮流程正确（落库、12 名、删校园活动、SQL 基础），**但第三轮成稿出现新瑕疵**：RAG 项目一条只有日期的要点「2026.03—2026.05」、丢失「用Python和Streamlit在本地搭建」、拾光要点尾部挂「时间为2026.06—2026.09」。结果存 `evaluation/persona-ux/runs/live-20261016-4-comparison-case.json`（git 忽略），待下一批修。

## 2026-10-16 第十一批：混合材料直接成稿 + 聊天与工作区同一份稿 + MCP 任务示例（历史）

- 镜像 `huhua-agent:20261016-3`（sha256:a14054d0…），**基于线上对比页镜像 `comparison-20261015145908-1f4259`**（v2 + `web/comparison*` 静态页与首页「实测对比」入口），代码 `9b97214`：替换 `backend/app`、`main.py`、`backend/scripts`，只覆盖 6 个前端文件（`home.html/css/js`、`account-profile.css/js`、`index.html`；`home.html` 为 MCP 三步接入 + 「实测对比」合并版），对比页文件沿用基础镜像。
- 第十一批（c6fc810）：带【教育】【项目】分节的混合材料与自然表达招聘要求可拆分；用户自带虚构/测试材料不再被防编造规则拦截；「直接成稿」当轮落库；修改/最终交付更新同一份 resume_data；统一交付闸门；「不支持 PDF」按状态改为右侧下载入口；成稿限定语/角色/技能/重复指标修复。3c87f56 MCP 三步接入与任务示例同批上线。
- 无新依赖、无 schema 变更。演练 `REHEARSAL_OK`（4 个账号 get_profile 正常）。容器测试 1676 项全过（skip 35）。备份 `/opt/huhua-backups/pre-20261016-3/`；回滚拷回 `deploy/compose.env.pre-20261016-3`（指向对比页镜像）后 `compose up -d --no-build --no-deps --wait app`。
- 本地五人物回放 69/71（design 一轮模型超时；`service.complaint_limit` 既有待办）；对比页冻结三轮本地/线上均落库成稿。
- 线上验收：`/`、`/chat`、`/resume`、`/static/comparison.html`、`results.json`、豆包 PDF 200，`/?session=x` 302，`/mcp` 无令牌 401，日志无异常；线上游客实跑对比页 P1/P2/P3：首轮直接成稿、邮箱原值，P2 18→12/删校园活动/SQL 仅基础查询，P3 不恢复、回复指向右侧下载。残留：RAG 项目同一指标换说法出现两次，「绘制原型」两条要点重复。

## 2026-10-15 首页对话示例/AI 助手入口 + 第十批抽取修复（历史）

- 镜像 `huhua-agent:20261016-2`（sha256:da2354d6…），基于 `20261016-1`，代码 `03bacd5`：首页「对话写简历/精细编辑」展示切换与虚构人物对话截图、首页右上「获取 MCP 密钥 · 登录/注册」、工作台顶栏「AI 助手」接入面板从个人档案拆出、工作台 logo 回首页；第十批：同一段经历不再被拆成「个人练习/工作经历（待补）」占位条目（行首标签与编号段确定主体，「日常更新」不再判为个人练习）、合并类更正（"是同一段实习，不是个人练习"）合并占位条目、实习起止时间写入字段、教育日期不再误挂实习时间、公司描述不作要点、项目职责误标 role 时回归正文。
- 无新依赖、无 schema 变更。演练 `REHEARSAL_OK`：线上库副本启动正常，计数不变，3 个账号 get_profile 正常。
- 包 `huhua-deploy-20261016-2.tar.gz`（文件清单与 20261016-1 一致，仅新增 `experience_subjects.py` 与 `chat-1440.png/.webp`；不含未发布的 `web/comparison.*`）。容器测试 1613 项全过（skip 35）。备份 `/opt/huhua-backups/pre-20261016-2/`；回滚拷回 `deploy/compose.env.pre-20261016-2` 后 `compose up -d --no-build --no-deps --wait app`。
- 本地五人物回放 68/71：`tech.initial_project` 已恢复；`career.correction_four/retained_duties` 为既有间歇问题（第九批代码 3 次中 1 次同样失败）；`service.approval_limit` 为既有待办。
- 线上验收：`/`、`/chat`、`/resume`、`chat-1440` 图片 200，`/?session=x` 302 到 `/chat?session=x`，`/mcp` 无令牌 401，`/static/comparison.html` 404（未发布，符合预期），日志无异常；1440/390 截图正常；线上虚构用例 A 抽取为单条「麦穗烘焙 · 新媒体运营实习生 · 2025.03—2025.08」，无占位条目。

## 2026-10-15 第八+九批回放修复（历史）

- 镜像 `huhua-agent:20261016-1`（sha256:d53e4cbf…），基于 `20261015-1`，代码 `63f5832`（75716f4 第八批：经历日期回填、兼职 `part_time`、局部润色硬边界与条目内去重、技能熟练度保留、中断生成真取消；63f5832 第九批：附件「字段:值」块按行拆分、日期不与后续数字粘连）。五人物回放 71 项断言 66 → 69~71（service 两项为模型波动，单独重跑 14/14）。
- 无新依赖、无 schema 变更。演练 `REHEARSAL_OK`：线上库副本启动正常，计数不变，3 个账号 get_profile 正常。
- 包 `huhua-deploy-20261016-1.tar.gz`（bf88cc2b…），测试包带 `evaluation/persona-ux/*.py` 与 `evaluation/persona-ux-2026-10-15/*.json`。容器测试 1586 项全过（skip 35）。备份 `/opt/huhua-backups/pre-20261016-1/`；回滚拷回 `deploy/compose.env.pre-20261016-1` 后 `compose up -d --no-build --no-deps --wait app`。
- 线上验收：`/`、`/chat`、`/resume` 200，`/?session=x` 302 到 `/chat?session=x`，`/mcp` 无令牌 401，日志无异常；官网 1440 与工作台 390 截图正常，控制台无错误；线上实测「生成草稿」后中断，显示「已中断，本轮未修改简历」，未出现恢复稿提示。

## 2026-10-15 官网主页 + 五人物回放修复（历史）

- 镜像 `huhua-agent:20261015-1`（sha256:3f8b48e8…），基于 `20261014-1`，代码 `965c9dd`（3d22a81 官网 `/` 与工作台迁 `/chat`、旧 `?session=` 302 到 `/chat`；44f2c58 刷新后默认停在挖经历；03a5c70/a66dd60 第五至七批：自动润色闸门、更正执行校验、「更专业」不改专业字段、附件与 JD 分流、首轮即抽取落库、断连服务端跑完、去杂项兜底条目）。五人物回放 71 项断言由 25 → 66 通过。
- 无新依赖、无 schema 变更。演练：线上库副本启动正常，计数不变，3 个账号 get_profile 正常。
- 包 `huhua-deploy-20261015-1.tar.gz`（f81ea512…）。容器测试 1550 项全过（skip 34）；首次运行因测试包漏带 `evaluation/persona-ux-2026-10-15/*-capture-*.json` 报 6 个 FileNotFoundError，补包后全量重跑通过。备份 `/opt/huhua-backups/pre-20261015-1/`；回滚拷回 `deploy/compose.env.pre-20261015-1` 后 up。
- 线上验收：`/`（官网）、`/chat`、`/resume` 200，`/?session=x` 302 到 `/chat?session=x`，官网全部静态资源 200，`/mcp` 无令牌 401，日志无异常；官网 1440 与工作台 390 截图正常，控制台无错误。

## 2026-10-15 MCP 接入 + 模板加速 + 非技术用户回放修复（历史）

- 镜像 `huhua-agent:20261014-1`（sha256:8f5ea925…），基于 `20261013-2`，代码 `3206d2b`（5d9d003 MCP M1+M2 与重复表单修复、691a488 模板切换缓存+预取+双缓冲、8cf646c/208bd45/3206d2b 三批回放修复）。
- 新依赖 `mcp==2.3.0`：本机按 linux x86_64/cp312 下载 wheel（`huhua-wheels-20261014-1.tar.gz`），镜像内 `pip install --no-index` 离线安装，`pip check` 无冲突，pydantic 2.13.5 / starlette 1.7.0 保持不变。
- 新表 `personal_access_tokens`、`profile_inbox` 由 create_all 建立，不升 SCHEMA_VERSION。演练：线上库副本启动正常，新表为空，旧数据计数不变，3 个账号 get_profile 均正常。
- 包 `huhua-deploy-20261014-1.tar.gz`（1b8178de…）。容器测试 1462 项全过（skip 32）。备份 `/opt/huhua-backups/pre-20261014-1/`；回滚拷回 `deploy/compose.env.pre-20261014-1` 后 up（多出的空表无害）。
- 线上验收：首页/编辑页/新静态资源 200（`?v=20261014-tpl1`、`20261014-ui1`），`/mcp` 无令牌 401，日志无异常；样例模板切换线上实测 65–106ms；1440 与 390 宽度截图正常。线上 MCP 端到端（令牌→Claude Code）待用户账号生成令牌后验收。

## 2026-10-13 技能集合 + 等价判断 + 视觉统一 + 标签页图标（历史）

- 镜像 `huhua-agent:20261013-2`（sha256:f72f0079…），基于 `20261013-1`，代码 `5c3cbc1`（ccd6ae2 等价判断 + 5c3cbc1 视觉与图标）。无 schema 迁移、未清数据。
- 内容：技能按单项集合存储（拆分、别名、熟练度更新可撤销、永不弹冲突）；日期（含预计/已完成语气）、学历、学校简称等价判断，换说法不再弹卡；读取档案时幂等迁移旧整串技能与假冲突。前端统一视觉 token（Opus 子代理）、标签页图标（Codex，气泡+简历横线）。
- 包 `huhua-deploy-20261013-2.tar.gz`（06c6fb0a…）。容器测试 1355 项全过（skip 7）。演练正常。切换前用新镜像在线上库副本上跑 get_profile 迁移：无报错、二次读取不变；技能 2 条整串→8 项，用户可见待确认冲突 7→1。备份 `/opt/huhua-backups/pre-20261013-2/`；回滚拷回 `deploy/compose.env.pre-20261013-2` 后 up。
- 线上验收：首页/静态资源/图标 200，title「胡话简历」，1440 与 390 宽度截图正常，日志无异常。

## 2026-10-13 预览提速 + 档案面板/记忆规则 + 对话标题（历史）

- 镜像 `huhua-agent:20261013-1`（sha256:e7339b2f…），基于 `20261012-3`，代码 `968adc5`（提交 worktree 打包）。无 schema 迁移、未清数据（会话 7、账号 3、档案事实 84）。
- 内容：render / current / 导出读已提交数据不等会话锁，保存测页走 `to_thread`；t004 个人定位移到白底、t002 深色页头浅色字；模板切换丢弃过期渲染；档案面板按条目合卡、「信息确认」红点、「我来更正」可取消；叙述类事实追加、状态类自动更新可撤销；对话标题按公司·岗位/方向/经历名生成。
- 包 `huhua-deploy-20261013-1.tar.gz`（a77da1cc…）。容器测试 1321 项全过（skip 7）。演练正常。备份 `/opt/huhua-backups/pre-20261013-1/`；回滚拷回 `deploy/compose.env.pre-20261013-1` 后 up。
- 线上验收（游客、虚构资料 handson-02）：方案卡→按推荐写→成稿→页内精细编辑正常；render 请求 8–12ms（上一版平均 16s）；对话标题为「AI 产品经理实习生（Agent 方向）」；发布后日志无异常。登录态档案面板待用户目视确认。

## 2026-10-12 加载提速 + 页内精细编辑（历史）

- 镜像 `huhua-agent:20261012-3`（sha256:1e2fe187…），基于 `20261012-2`，代码 `858221b`。无迁移、未清数据（会话 12、档案事实 84）。
- 提速：Tailwind 改预编译 `web/tailwind.css`（配置 `web/tailwind.config.js`，含 @tailwindcss/forms；新增 class 需重新编译），去掉 Google Fonts，`/static` 开 gzip（只作用于静态挂载，不影响 SSE），带 `?v=` 的静态文件 `max-age=31536000, immutable`。线上 resume-editor.js 62KB/1.1s → 18KB/0.33s，样式 5.6KB。
- 交互：「精细编辑」在聊天页内以预加载 iframe（`/resume?embedded=1`）打开，双向同步，关闭不重载；「写简历」顶部「精细编辑 / 下载 PDF / 下载 Word」；去掉「导出」标签与右上角「全屏模板 / 通用 Word」。
- 包 `huhua-deploy-20261012-3.tar.gz`（671dc99e…）。容器测试仅 2 项需 node 的前端测试报错（之后已改为无 node 时跳过）。备份 `/opt/huhua-backups/pre-20261012-3/`；回滚拷回 `deploy/compose.env.pre-20261012-3`。
- 线上验收（游客）：成稿后精细编辑页内打开、URL 不变、标签 4 个；本地验证编辑保存后聊天页预览同步、对话保留。

## 2026-10-12 P5 写法升级（历史）

- 镜像 `huhua-agent:20261012-2`（sha256:aa5c7c0c…），基于 `20261012-1`，代码 `c493ca7`（提交 worktree 打包）。无迁移、未清数据。
- 内容：方案卡新增「个人定位」（确认后写进页头下方，可「个人定位改成…」）；追问优先问决策原因并点名决策；现状可正向表述；「问题-决策-结果」标签写法为方案卡可选项（默认普通写法——实测默认开启会挤掉核心事实）。
- 包 `huhua-deploy-20261012-2.tar.gz`（33deac1f…）。容器测试 1287 项仅已知 node 测试报错。演练正常。备份 `/opt/huhua-backups/pre-20261012-2/`。回滚：拷回 `deploy/compose.env.pre-20261012-2` 后 up。
- 线上验收（游客、虚构资料）：方案卡→确认→成稿，个人定位准确出现在页头；原因追问点名决策。已知瑕疵：原因已在原话中时仍会追问。

## 2026-10-12 排版自适应一页 + 深蓝细线模板（历史）

- 镜像 `huhua-agent:20261012-1`（sha256:55e35415…），基于 `20261011-2`，代码 `a7955c5`（从提交 worktree 打包，未混入工作区未提交改动）。无 schema 迁移、未清数据（会话 8、账号 3、档案事实 84）。
- 内容：每个模板 density 0–3（行距/间距/字号，正文最低 9.5pt），超页时先自动选最松的一页档位再压缩内容；"字大一点/排紧凑点"手动调档；预览、PDF、Word 同档。新增模板 `t003-shenlan`（深蓝细线）。
- 包 `huhua-deploy-20261012-1.tar.gz`（1f920276…）；测试包用 `COPYFILE_DISABLE=1` 打，无 `._*` 文件。容器测试 1274 项仅 1 项需 node 的前端测试报错（镜像无 node）。
- 备份 `/opt/huhua-backups/pre-20261012-1/`（app f5d4f731…、checkpoints e80dee66…、privacy 60c4c385…）。回滚：拷回 `deploy/compose.env.pre-20261012-1` 后 up。
- 用户 2 页简历数据本地验证：density 0 为 2 页，自动选 1 档即 1 页，正文未删减。

## 2026-10-11 PR8 主线流程上线（历史）

- 镜像 `huhua-agent:20261011-2`（sha256:775776dfad20…），基于 `20261011-1` 只替换代码/前端/模板；无 schema 迁移、未清数据（会话 3、账号 3、档案事实 51 保留）。代码 `dbe2c86`。
- 包：`huhua-deploy-20261011-2.tar.gz`（0df82934…），`huhua-tests-20261011-2.tar.gz`（d7abf2ac…）；脚本 `dist/{build,rehearse,release}-20261011-2.sh`。
- 容器测试 1257 项：除 1 项需 node 的前端测试（镜像无 node）外全过；macOS 打的测试包含 `._*` AppleDouble 文件会导致 3 项读用例报错，删除后通过——下次打包加 `COPYFILE_DISABLE=1`。
- 演练：新镜像在线上库与 checkpoint 副本上启动健康。切换前加密备份 `/opt/huhua-backups/pre-20261011-2/`（app 3d985239…、checkpoints 41e88f20…、privacy 26fc96ca…）。
- 回滚：`deploy/compose.env.pre-20261011-2` 拷回 `deploy/compose.env` 后 `compose up -d --no-build --no-deps --wait app`（数据库未改动，可直接回旧镜像）。
- 线上验收（游客、虚构资料，浏览器）：开场、JD、出方案卡、按推荐写成稿、征求意见均正常；`LLM_PLAN_CONFIRM=True`。

## 2026-10-11 JD 定制重构上线（历史）

- 镜像 `huhua-agent:20261011-1`，ID `sha256:da8f6f4be8285203beddb2881e5b9a374b9720a260917dfe4aeb71dd19a51dbe`，基于 `20261006-4` 补装 `libpango`、`fonts-noto-cjk` 与 `weasyprint==70.0`（旧镜像缺这三项，PDF 导出此前不可用），并复制 overhaul/tailor 分支 `0b16aa5` 的应用、前端、模板、`tech_terms.txt`、`capacity.json`。构建与切换脚本：`dist/build-20261011-1.sh`、`dist/rehearse-20261011-1.sh`、`dist/release-20261011-1.sh`；部署包 SHA-256 `c80ddd40…791ce9`。
- 服务器断网测试 1047/1047（跳过 3）。计页改为排版结果（0.12s）；服务器写 PDF 因 CJK 字体子集化约 13s，只影响导出。
- 数据：库结构 1→2（`resume_sessions.resume_state`），用 `security_migrate.py application-migrate` 新建文件迁移；按 Banz 决定清空旧简历 6 份、对话 5 个、`claimed_history_imports` 3 条，保留账号 3、个人档案 1、档案事实 35；检查点库换为空库。迁移前在副本上演练通过。
- 停写后配对加密备份 `/opt/huhua-backups/pre-20261011-1/`（app/checkpoints/privacy，privacy digest `3e9f33dc…be3fef`）。旧检查点库保留为数据卷内 `checkpoints.sqlite3.pre-20261011-1`。**原 `huhua.db` 未留改名副本**（脚本对 root-only 卷目录做存在判断未加 sudo，已在脚本中修正），回滚须用上述加密备份恢复原库后切回 `20261006-4`；旧镜像不能直接读新库（版本 2）。`deploy/compose.env.pre-20261011-1` 保留。
- 线上游客虚构资料验收：JD 8.3s、首稿 12.5s、编辑 12.0s、改学校 1.4s，错误 0。发现 badcase：点名内容按字面核对（「模型乱推荐」未匹配原话「模型老推荐不存在的店」），记入试用期待修。
- 模型：DeepSeek 官方 `deepseek-flash`，发布时余额约 ¥16，与本地测试共用同一 key。

## 2026-10-06 用户反馈修复（历史）

- 镜像 `huhua-agent:20261006-4`，ID `sha256:313774d4f7c5f9cb0bac75bebcca14eefcc77f7aea2a319771a7ba4d7e49d015`，healthy；宿主 Caddy、原密钥与数据卷保留，无新增 schema/依赖。
- 多附件分别解析合并、情境追问及公开主页/仓库读取已部署。隔离测试本地470/470、镜像470/470；前端33/33。线上独立游客脱敏导入、真实GitHub+模型一轮、经历不变和来源刷新恢复通过，页面错误0。详情见 `2026-10-06-web-tools.md` 与 `evaluation/feedback-fixes-2026-10-06/`。
- 发布包 `dist/huhua-deploy-20261006-4.tar.gz`，139文件，SHA-256 `3a5e518c30b4aa9fe47a12cef640d512e26a48bf671abed192ffe6a712a02844`；构建目录 `/opt/huhua-validation-20261006-4`，基于-3原依赖复制本次应用/前端。
- 停写后服务器内配对备份 `/opt/huhua-backups/pre-20261006-4/`（app/checkpoints/privacy）；摘要在本机 `evaluation/feedback-fixes-2026-10-06/server-release.log`。app.env/compose.env仍0600。恢复应结合最新隐私状态；同机备份不是异机灾备。
- 旧镜像-3保留，发布脚本失败自动切回旧镜像。未发邮件、未获取生产个人对话、未更换运行凭证；资料修复不自动重写旧用户会话。交接文档发布后另行同步，不改变运行代码。

## 2026-10-06 搜索配置启用（历史）

- Tavily凭证已写入受限app.env，权限0600；已按双配置命令仅重建app，镜像仍`huhua-agent:20261006-3`，健康正常。公开能力`read_url=true`、`search=true`。
- 独立游客浏览器两次真实搜索及模型分析通过，各4条来源；来源恢复与当前JD保持，错误0。相关性/在招状态须逐例核对，详见`evaluation/search-activation-2026-10-06/`。
- 配置前备份只留服务器`deploy/app.env.pre-tavily-20261006`（含其他运行凭证，不可进入源码或报告）。关搜索只清空单个TAVILY_API_KEY并重建app；原账号密钥及卷保留，未改schema或服务商账单设置。

## 2026-10-06 文档确认后的增量（当前）

- 当前镜像 `huhua-agent:20261006-3`，ID `sha256:f54511951c69940b3a52bce9f7ec04dd031546ee95bba1c4be61b63feca0cc43`。先发布-2修复材料范围与提示，再发布仅更新首页四个资源版本号的-3，解决浏览器继续加载旧JS的问题。
- 后端/前端范围提示和研究事实约束详见[工具说明](2026-10-06-web-tools.md)；当次发布时搜索未配置；后续已按上节开通。
- 本地与服务器各422项回归通过，前端静态/状态27项、公网边界11项。最终-3源码与已测-2逐文件对比只改首页资源版本；最终健康检查及线上浏览器新提示验证通过、错误0。
- 两份中文公开网页读取成功，一份动态页正确回退。真实模型虚构案例4次，前2例发现否定事实表达问题，后2例主要边界通过；搜索供应商仍无真实验收。证据 `evaluation/web-tools-2026-10-06-followup/`。
- 最新配对备份 `/opt/huhua-backups/pre-20261006-3/`，摘要在本机 `server-cache-release.log`；旧镜像及 `deploy/compose.env.pre-20261006-3` 保留。密钥/卷未变，运行配置仍0600。
- 实际部署包 `dist/huhua-deploy-20261006-3.tar.gz`，138文件，SHA-256 `4717f8aadbbbb61c74e9838a71a2047d12638dc04a4b964e2a76e54c33adf163`。构建配方 `/opt/huhua-validation-20261006-3/Dockerfile.release`。文档发布后单独同步，运行代码不变。

## 2026-10-06 招聘链接与搜索工具更新（历史）

- 当时镜像 `huhua-agent:20261006-1`，ID `sha256:245bde8ef6311653f75597e05cf31309a66e0c26f50742bba4b27682fdebc1f5`。沿用上一版依赖，无新增 schema，构建配方 `/opt/huhua-validation-20261006-1/Dockerfile.release`。
- 单招聘链接读取、来源卡片与 JD 解码开放给游客。公司/岗位搜索代码已接入 Tavily；未配置 `TAVILY_API_KEY`，能力接口返回 `search=false`，不能宣称真实搜索已开通。配置说明见 [工具说明](2026-10-06-web-tools.md)。
- 本地与服务器无网络隔离套件分别 **416/416** 通过；前端静态/纯状态 **20/20**，公网检查 **11/11**。服务器真实公共招聘正文提取成功；生产浏览器与模型验收结果单独记录在 `evaluation/web-tools-2026-10-06/verification.json`。
- 发布前停写完成 `/opt/huhua-backups/pre-20261006-1/` 下的应用、checkpoint 与隐私状态配对加密备份，摘要独立留证于本机 `evaluation/web-tools-2026-10-06/server-release.log`；原数据卷、密钥、邮件配置与其他站点保留，运行环境文件仍 0600。旧镜像 `20261005-2` 与 `deploy/compose.env.pre-20261006-1` 保留可回退。
- 实际部署包 `dist/huhua-deploy-20261006-1.tar.gz`，138 文件，SHA-256 `677a8de7c1d81c12676ae96455d04041c5680b17df32c4ad581f66bbde28761e`。交接文档在发布后单独同步，运行代码不变。

## 2026-10-05 游客体验更新（历史）

- 运行镜像 `huhua-agent:20261005-2`，ID `sha256:7a249bdd7a75c906bb3721f4bc23bdabc8f8e03984daf89b88d7bf9db4cc24d2`。沿用 `20261005-1` 已验证依赖，只复制更新的应用、前端与运维脚本。新机仍使用标准 Dockerfile；本次构建配方在服务器 `/opt/huhua-validation-20261005-2/Dockerfile.release`。
- 服务器镜像隔离回归 **377/377**，无网络、不挂载生产数据，37.289 秒。公网 API **16 项**通过：游客创建、读写、个人预览均 200；历史、档案、Word/PDF 导出要求登录；跨浏览器读 404、跨源写 403；虚构 API 测试稿已删除。
- `REQUIRE_ACCOUNT=true` 保留；运行值确认 `ALLOW_GUEST_EXPERIENCE=true`、`GUEST_RETENTION_HOURS=24`、`GUEST_DAILY_TURN_LIMIT=20`。只认领当前游客会话，保留 checkpoint 原加密绑定；游客不建立长期档案。正式导出需登录，HTML 预览仍可被浏览器自行打印。
- 线上未登录浏览器完成一轮虚构资料的真实模型对话，点击 Word 弹出登录提示；全屏模板显示、切换和游客编辑均已验收。未调用真实验证码发送，也没有将虚构资料存进真实账号档案。
- 本地浏览器真实加密后端验收：首次模板预览、游客聊天、点击 Word 提示登录、原页登录认领、同一会话和未发送输入保留、历史目录、实际 Word 下载与 XML 内容核对通过。模型和邮件为测试替身；不当作真实发信或记忆提取质量验收。
- 发布前停写取得配对备份，位置 `/opt/huhua-backups/pre-20261005-2-wal-fixed/`：`app.encrypted`、`checkpoints.encrypted`、`privacy.encrypted`；加密备份及隐私摘要在本机 `evaluation/guest-experience-2026-10-05/server-final-switch.log` 独立留证。密钥和原数据卷未更换，运行配置仍为 0600；这些同机文件不代替异机灾备。恢复前还须取得届时最新隐私状态。
- 初次备份遇到 SQLite WAL 快照反序列化错误，修复只规范化内存副本标记、不修改源库；3 项 WAL 回归与 7 项既有隐私恢复检查通过，包含在最终全套中。另一次发布因只读摘要检查的 shell 展开权限报错自动回滚，修正检查后已成功切换。旧 `20261005-1` 镜像保留。
- 实际发布包 `dist/huhua-deploy-20261005-2.tar.gz`：134 文件，SHA-256 `3838655075bf7253caaf3c219ab159aaa2053833019ead8cba39184f0c19b5f2`。最终交接文档更新在发布后单独同步，不改变运行代码。

证据：`evaluation/guest-experience-2026-10-05/verification.json`、`public-checks.json`、发布日志、浏览器截图与 `guest-ui-export.docx`。

## 首版部署已验证（历史记录）

- 服务器镜像构建成功；使用禁用网络的临时容器执行 **358 项测试，全部通过，耗时 33.157 秒**。
- 公网 `/`、`/resume`、`/healthz` 返回 `200`；应用重启后，`healthz`、database 与 checkpoint 检查均正常。
- Resend 域名总状态及 DKIM、`rsend`、`send` 三项记录均为 `verified`，域名事件显示北京时间 03:02 完成。DNS 服务器查询三项记录正确，网站 A 记录仍为 `49.233.252.47`。
- 服务器只修改了 `RESEND_FROM` 为 `Huhua <login@resume.yikuaibanz.cn>`，其他运行配置完整保留，`app.env` 仍为 `0600`。双 Compose 配置执行 `--force-recreate --wait` 成功，`huhua-app-1` 为 `Healthy`，容器内已确认新发件地址加载。
- 切换后公网 `/healthz` 返回 `200`，database/checkpoint 均正常；`/api/account/me` 返回 `200`，`login_available=true`、`require_account=true`。登录入口可用不等于邮件已送达或用户已登录。
- 首版未登录访问个人档案返回 `401`，跨源写请求返回 `403`，匿名 render/export 为 `401`。游客版现已开放 render 预览，正式导出仍为 `401`，以上更新章节为当前边界。
- 用一条虚构经历完成真实改写，经过 **2 次模型调用**返回可用候选句；生成没有自动修改保存稿。
- 原有站点入口状态部署前后相同：首页 `200`、Jev `302`、PandaFlow `302`。

这些检查没有证明真实用户已收到验证码、登录成功或完成聊天 SSE 全流程。本次没有发送任何测试邮件。

验收证据保存在 `evaluation/server-deployment-2026-10-05/`：`verification.json`、`public-checks.json`、`live-rewrite.json`、`deployment-summary.json` 与 `requirements.resolved.txt`。本次邮件域验证与切换证据由主线程汇总到同目录的 `mail-domain-verification.json` 和 `resend-domain-verified.jpg`。本交接文档不替代对应原始记录。

## 当前待办与接手顺序

1. **等待获准测试的收件邮箱，完成真实使用验收。** 已异步询问用户，尚未收到邮箱回复；本次没有发送邮件，也未确认收件或登录。取得邮箱与测试授权后，验证“验证码送达 → 登录 → 刷新保持 → 聊天 SSE → 保存 → 建议采用 → 导出”的完整路径。域名验证和发件地址切换已完成，无需再次要求用户验证域名。
2. **补齐异机恢复材料与恢复演练。** 服务器内配对加密备份已完成，详见游客更新章节。 自动审批此前拒绝回传完整 `app.env`，该动作已停止；仍等待用户是否授权仅备份 `DATA_ENCRYPTION_KEYS` 与 `ACCOUNT_SECRET` 两项恢复材料到独立受控位置。不要把完整运行配置、模型/邮件凭证或密钥值写进交接文档和聊天。后续还需按 [账号与加密运维说明](security-operations.md) 备份两份数据库、最新隐私状态及独立可信摘要，并完成恢复演练；同机命名卷与单独备份密钥都不能代替完整灾备。

## 已配置的 Resend DNS 记录

以下主机记录均相对阿里云主域 `yikuaibanz.cn`；三项记录已写入阿里云，TTL 均为 10 分钟。原有 7 条 A 记录保留，新增后共 10 条记录。

Resend 域名 ID：`b44ec737-b5dc-46ec-8bd3-d9a480f4ebeb`；[打开域名页面](https://resend.com/domains/b44ec737-b5dc-46ec-8bd3-d9a480f4ebeb)。最终总状态为 `verified`，DKIM、`rsend`、`send` 均为 `verified`；域名事件显示北京时间 2026-10-05 03:02 完成。DNS 服务器查询结果正确，网站 A 记录保持 `49.233.252.47`。

| 类型 | 主机记录 | 记录值 |
| --- | --- | --- |
| TXT | `resend._domainkey.resume` | 见下方 DKIM 公钥 |
| CNAME | `rsend.resume` | `rsend.forge.rmta.net` |
| CNAME | `send.resume` | `send.forge.rmta.net` |

TXT 记录值（DKIM 公钥，可公开；整段为一条记录）：

```text
p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCnQwQrcUzXfmfFcy3NACzf4LuVZthJxI9tN1ZGLnprMqqnCuYWb/cDofFLcQErs3v6q+NdzTxHEADz57uDr2xZqt9uSb4Tgd6Dgd0WlstSTrQpyNrXco1bsV7c75AfiyVUkvfe9qo+EUisUOgS0yyRGHBbJDU07Wv08TEIx9toaQIDAQAB
```

服务器已使用上述验证域的正式发件地址；测试邮件尚未发送。当前发送 key 保持原值，未做密钥轮换；该 key 的发送权限与后台完成域验证不冲突。当前任务不使用 webhook 签名 secret，本文不保存该值。

## 查看、重启与更新

先进入服务器目录。当前 `ubuntu` 用户没有 Docker socket 权限，以下命令使用 `sudo docker compose`；始终包含变量文件与两个配置文件，并只启动或更新应用服务。

```sh
ssh banzi
cd /opt/huhua

sudo docker compose --env-file deploy/compose.env -f compose.yaml -f deploy/compose.host-caddy.yaml ps
sudo docker compose --env-file deploy/compose.env -f compose.yaml -f deploy/compose.host-caddy.yaml logs --tail=100 app
curl --fail https://resume.yikuaibanz.cn/healthz
```

普通应用重启：

```sh
sudo docker compose --env-file deploy/compose.env -f compose.yaml -f deploy/compose.host-caddy.yaml restart app
```

修改 `deploy/app.env` 后，`restart` 不会重新加载容器环境；需使用以下命令重新创建应用容器，保留命名卷：

```sh
sudo docker compose --env-file deploy/compose.env -f compose.yaml -f deploy/compose.host-caddy.yaml config --quiet
sudo docker compose --env-file deploy/compose.env -f compose.yaml -f deploy/compose.host-caddy.yaml up -d --no-build --no-deps --force-recreate --wait app
```

更新代码前先安排维护窗口与配对备份，保留运行配置及 `deploy/compose.host-caddy.yaml`。上传经审核的源码包，把 `deploy/compose.env` 中的 `HUHUA_IMAGE_TAG` 改为新版本标签，再执行：

```sh
sudo docker compose --env-file deploy/compose.env -f compose.yaml -f deploy/compose.host-caddy.yaml config --quiet
sudo docker compose --env-file deploy/compose.env -f compose.yaml -f deploy/compose.host-caddy.yaml build app
sudo docker compose --env-file deploy/compose.env -f compose.yaml -f deploy/compose.host-caddy.yaml up -d --no-build --no-deps app
sudo docker compose --env-file deploy/compose.env -f compose.yaml -f deploy/compose.host-caddy.yaml ps
```

使用 `config --quiet`，避免展开打印运行密钥。更新后重新检查健康、登录、保存、导出及原有站点入口；不要运行带 `down -v` 的命令。

## 回滚边界

应用只有在数据库结构兼容时，才能将镜像标签改回已有旧版本，再用上述双配置的 `up -d --no-build --no-deps app` 命令切回。涉及数据库恢复时须使用配对数据库、对应密钥及最新隐私状态，不单独覆盖一份 SQLite。

Caddy 回滚前先比较 `/etc/caddy/Caddyfile` 与备份，确认部署后是否已有其他站点或配置变更；只撤销本次 `resume.yikuaibanz.cn` 相关修改，**不要直接用备份覆盖整份配置**。编辑完成后先验证，验证成功才 reload：

```sh
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```
