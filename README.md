# 胡话简历 · Huhua Agent

AI 简历对话工作台：聊天收集真实经历 → 针对岗位整理 → 核对事实 → 6 款 A4 模板导出 PDF / Word。

基于 **FastAPI + LangGraph** 构建，不是一次性填表工具——像朋友聊天一样把你的经历抽成结构化简历。

---

## 能干嘛

- **对话式收集**：不硬要 JD，随便聊"最近在忙什么"都能抽出项目素材
- **截图解码**：上传 JPG/JPEG/PNG 岗位截图后由视觉模型转写文字；识别结果可以先核对、修改，再发送给 JD 解码流程
- **整理经历**：从自然语言中提取已确认事实，整理到当前简历；自动同步保留原始证据，不补用户没说过的数字
- **候选改写**：选择当前简历原句，让 AI 生成措辞并核对依据；查看差异后明确采用，也可撤销。手动改候选后需重新核对，采用只修改当前稿
- **智能分组**：Java/Python → 技术栈；PRD/竞品 → 产品方法；Claude Code/ChatGPT → AI 工具——自动归类不用手动分
- **投递检查**：指出 JD 证据缺口、待核实数字和导出风险，不虚构面试概率
- **6 款模板**：简约单栏 / 深蓝横幅 / 灰条夹页 / 浅蓝斜切 / 浅蓝色块 / 淡青平行
- **实时表单编辑**：右侧按栏目填写，输入立即更新 A4 预览；悬停文字显示虚线框并高亮对应输入框，点击可定位编辑。支持增删经历、要点与技能分组
- **自定义栏目**：拖动栏目把手排序，或用上移/下移按钮；可修改标题、删除与撤销，也可添加自定义标题和多行正文。自定义标题留空时只显示正文；六款模板与 PDF / Word 都遵循当前栏目顺序
- **头像上传**：base64 内嵌，DOCX 导出也会带图
- **导出**：所选模板由服务端生成可下载 PDF；Word 使用统一排版，便于继续编辑
- **先体验再登录**：首次打开即可看模板、聊天和编辑当前简历；登录后保存当前对话、启用长期档案并导出
- **历史对话**：登录后每段对话独立保存 JD、已收集经历和最新简历；点“新对话”保留账号里的旧内容，点“历史对话”可回到原聊天继续修改与导出
- **对话工作区**：右侧“读岗位 / 挖经历 / 写简历 / 核对 / 导出”可切换查看，JD 解读和经历集中展示；左侧以简短反馈、明确建议和追问为主
- **边聊边完善**：已有简历可直接导入，收集到的新事实逐轮同步到同一份预览与导出数据；输入框上方提供具体问题与简短选项，点选即发送一句完整回答。同组选项收起并防止连点重复提交，原输入草稿和附件保留，也可自由输入；发送失败可重试

---

## 架构

```
用户 ──► SSE 聊天 ──► LangGraph StateGraph
                      │
                      ▼
          JD_INPUT → COLLECTING → BUILDING → EVALUATING → EXPORT
                      │           │
                      │           └── editor_chain（技能分组 / 原句摘取排序 / 栏目命名）
                      │
                      └── triage_chain（9 个 Action 路由：DECODE_JD / WRAP / ASK_EXP / READY_TO_BUILD / …）

专业任务：skill_task → JD 解码 / 经历整理 / 简历检查 / 外部资料分析
方法文件：career_prompt + jd-decode / experience-write / resume-review
联网入口：read_url / read_public_url / search（每轮一次受限调用）
后台档案：已登录用户的归档事件 → profile_archivist → 依据核验后保存

渲染：ResumeData → Jinja2 模板 → HTML → WeasyPrint（直出 PDF）/ python-docx（直出 DOCX）
```

当前业务由 `resume_graph` 编排。可选 RAG 仅为 JD 解码提供 `jargon_dict` 参考，默认 `ENABLE_RAG=false`。改写整份直接生效并保存历史版本，用户可在聊天里的「本次修改」卡片一键撤销。

**模型配置**：代码默认值与 `.env.example` 一致：`LLM_MODEL=gpt-4o`，`LLM_STRUCTURED_MODEL` 留空时沿用主模型，未设置 `LLM_BASE_URL` 时使用 OpenAI SDK 默认端点。内部提取、JD 解码与编辑可通过 `LLM_STRUCTURED_MODEL` 单独选模型；DashScope 和 DeepSeek 的显式配置见 `.env.example`，模型名应使用对应服务实际支持的值。

`LLM_CHAT_TEMPERATURE` 默认 `0.7`；原 `LLM_TEMPERATURE` 仍兼容，新键优先。提取、Triage 和 editor 保持原有温度 `0`，JD 解码沿用主模型温度，简历审查保持 `0`，现有候选改写和档案整理沿用其传入模型温度。`LLM_WRITER_TEMPERATURE` 默认 `0.4`，仅为后续写作节点预留，当前流程未使用它。

`LLM_MAX_TOKENS` 默认为未设置，保留服务商原有输出上限；显式填写正整数后，主对话、内部调用和图片转写均使用该上限。它不限制输入上下文，也不代表整次对话的 token 或费用预算。

图片使用 `LLM_VISION_MODEL`。留空时按 API 地址选择：DeepSeek 使用 `deepseek-flash`，DashScope 使用 `qwen-vl-plus`，OpenAI 默认地址使用 `gpt-4o-mini`。图片会发送到配置的视觉模型服务；没有配置 `LLM_API_KEY` 时返回明确错误。图片上传仍受 10MB 限制，并有单独并发与请求频率限制。

---

## 启动

新版默认支持游客体验，导出、长期历史和个人档案需要邮箱验证码登录；运行仍需加密密钥和账号密钥。先按 [账号与安全运维说明](docs/development/security-operations.md) 配置 `DATA_ENCRYPTION_KEYS`、`DATA_ENCRYPTION_ACTIVE_KEY`、独立 `ACCOUNT_SECRET` 和已授权的邮件服务；空配置会拒绝启动或明确显示登录不可用。本机 HTTP 配 `AUTH_COOKIE_SECURE=false`；公开环境必须 `APP_ENV=production`、HTTPS `APP_ORIGIN` 与安全 Cookie。**已有旧数据库不能直接启动新版**：先对配对离线副本执行迁移与验证，再明确切换；命令不自动迁移用户现用数据。

生产环境保持 `REQUIRE_ACCOUNT=true`，游客体验由独立配置控制：`ALLOW_GUEST_EXPERIENCE=true`、`GUEST_RETENTION_HOURS=24`、`GUEST_DAILY_TURN_LIMIT=20` 均为默认值。游客当前稿和对话加密临时存储，24 小时未更新后过期，不进入长期档案。登录后只接续并保存当前会话；其他游客会话仍按临时期限清理。

```bash
# 1. 仅首次安装复制示例；已有配置不要覆盖
cp -n .env.example backend/.env
# 按下方说明配置数据密钥、账号密钥、SMTP 和 LLM_API_KEY

# 2. 安装依赖并启动
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
cd backend
../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8765

# 3. 打开浏览器
open http://127.0.0.1:8765/
```

PDF 导出使用 WeasyPrint，Docker 和 CI 已包含 Pango 与中文字体。直接在 Debian/Ubuntu 运行时需安装 `libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-cjk`；macOS 可用 Homebrew 的 `pango`，并在启动/测试的终端设置 `export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib"`。原生库缺失时 PDF 会明确报错，Word 仍可导出。

如果使用 DeepSeek，在 `backend/.env` 中设置 `LLM_PROVIDER=deepseek`、`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL=deepseek-flash`、`LLM_STRUCTURED_MODEL=deepseek-flash`，并填写新生成的 `LLM_API_KEY`。`LLM_VISION_MODEL` 可留空，图片识别会自动使用 `deepseek-flash`。请勿把密钥提交到仓库或贴进聊天。

服务固定读取本项目的 `backend/.env`，不受启动目录影响；环境变量优先于该文件。修改配置后需要重启服务。DeepSeek 的 Triage、编辑与改写核验结构化调用使用工具调用，并单独关闭思考模式，以适配其接口格式。

运行回归检查：

```bash
.venv/bin/python scripts/run_tests.py -v
```

该入口强制临时数据库和空模型/邮件配置，安全集成用例在各自夹具中注入随机密钥和内存邮件运输器。GitHub PR 会自动运行同一套测试。

这套自动化测试会显式将模型密钥设为空值，模型请求使用离线替身，不会消耗本地配置的模型额度。真实模型连通与生成流程需要另行验证。

候选改写的固定虚构案例可用 `.venv/bin/python scripts/evaluate_rewrites.py --max-cases 6` 查看计划；默认不调用模型。明确加上 `--live` 后才使用本地已配置模型，每例最多两次调用，临时加密数据库与邮件配置隔离。最近一次结果及局限见 [项目审视与改进报告](docs/development/2026-10-05-project-review-and-improvements.md)。

模板编辑页位于 `/resume?session=...`，从指定聊天读取简历。个人草稿自动保存到同一会话，返回聊天携带原会话 ID；在会话有效且浏览器凭证仍在时，刷新可恢复已保存的字段、栏目和正文。保存冲突或断线时会明确提示，并支持下载未保存草稿。个人预览与导出请求均绑定会话，正式导出使用服务端已保存的稿件。没有个人简历时可主动新建空白草稿或查看模板样例；样例可免登录查看、切换模板，新建个人草稿后再填写自己的内容。模板选择按当前会话保存在本机浏览器，刷新恢复，不跨设备同步。PDF 使用选定模板生成可下载文件，Word 为通用版式；文件生成后保留下载/打开入口，失败可重试。产品 PDF / Word 导出入口要求登录；浏览器中可见的预览无法阻止用户自行复制或使用浏览器打印。

聊天目录、简历数据和完整 Agent 上下文均落在数据库：本地默认使用 `backend/data/huhua.db` 和 `backend/data/checkpoints.sqlite3`，线上按 `DATABASE_URL` 使用 Postgres。备份/迁移本地数据需同时保存两份数据库（服务停止后复制，或使用数据库备份工具）。旧浏览器历史需要在持有有效浏览器凭证时登录并显式认领；无法仅凭姓名或 session ID 认领。浏览器不再长期缓存简历、对话或未保存草稿全文；未保存草稿仅留当前页面，可主动下载。

历史目录要求登录；当前会话的私有读写验证账号或游客浏览器凭证的归属，不能仅凭 session ID 访问。一个账号维护本人一份主档案，支持来源、时间、更正、删除和冲突处理；不同聊天保留独立 JD 与简历。基本事实可随新聊天取用，项目经历需显式选用，AI 建议不会自动成为事实。账号会话默认 `SESSION_RETENTION_DAYS=0` 持续保留，只有显式删除才清除；设为正数则在对应天数未更新后过期。游客另受 24 小时闲置期限约束，不能将当前页面恢复能力视作长期历史保存。

本地服务启动后，可用已安装的 `playwright-cli` 运行交互回归（无需模型密钥）：

```bash
playwright-cli -s=huhua-editor open http://127.0.0.1:8765/resume
playwright-cli -s=huhua-editor run-code --filename=tests/resume_editor.browser.js
playwright-cli -s=huhua-editor run-code --filename=tests/resume_sections.browser.js
```

检查覆盖悬停与定位、连续输入和慢请求、增删后的字段对应、技能分组、原生栏目拖拽/改名/撤销、自定义正文、六款模板、最新内容导出及手机布局。普通导出不包含编辑脚本或高亮样式。

## 公开 beta

- 自有 Linux 服务器的全新单机部署见 [Docker 部署步骤](docs/development/docker-deployment.md)：干净源码打包、Compose、Caddy HTTPS、持久数据卷及运行密钥生成。现有实例的部署版本和验证状态以 [实际服务器交接](docs/development/2026-10-05-server-deployment.md) 为准。
- `Dockerfile` 与 `render.yaml` 是部署配置，必须先配齐加密、账号、HTTPS 来源及邮件服务。Postgres 需在目标环境做迁移和恢复演练。
- 在托管平台将数据密钥、账号密钥、SMTP 凭证和 `LLM_API_KEY` 分别作为 Secret 注入，不能提交到仓库。
- 登录后默认持续保存历史；游客仅临时体验。“新对话”新建独立会话；用户在历史列表中明确删除某项时，清除对应聊天上下文、简历与目录记录。
- 首期只支持一个应用 worker。会话锁、模型并发和 IP 限流在本进程；账号每日生成/核对/归档操作配额持久化，不能等同精确 token 或金额上限。扩到多 worker/实例前需分布式会话锁、共享限流和并发实测；不能直接相信客户端传来的 `X-Forwarded-For` 首项。
- 服务端最多接受 10MB 文件，并对常见的超大上传提前拒绝；正式扩量前还需在网关限制分块上传的请求体大小。
- 部署配置中的套餐仅为示例，实际价格、休眠和数据库保留政策需在选择托管服务时核对。正式开放需验证邮件送达、TLS、存储权限、配额告警及恢复演练。

---

## 目录

```
backend/
  app/
    agents/           # resume_graph / career_prompt / triage / decoder / editor / profile_archivist
    api/              # chat.py / resume.py
    services/         # renderer.py（Jinja2）/ resume_sections.py（栏目顺序）/ file_extractor.py / image_ocr.py
    schemas/          # ResumeData / BasicInfo 等 pydantic
    tools/            # resume_data_docx.py（结构化 → Word）
  main.py

web/
  index.html          # 聊天页（Eloquent Canvas 紫色风）
  resume.html         # 模板选择 + 实时表单编辑 + 导出
  resume-editor.js    # 表单与渲染请求、字段联动
  resume-editor.css   # 编辑工作台与移动端布局
  resume-preview.js  # 隔离 iframe 中的字段映射与高亮

data/
  jianlimoban/html-template/  # 6 款 Jinja2 模板
  jargon_dict.csv              # 可选 JD 术语检索参考
  sample_resume.json           # 模板预览占位数据（胡小豆）
```

---

## License

MIT

---

Built by [@YIKUAIBANZI](https://github.com/YIKUAIBANZI)
