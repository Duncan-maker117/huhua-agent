# 胡话简历 · Huhua Agent

> 我是胡话，专治简历里的胡话。

一个很会做简历的 AI agent：你随便聊几句、丢一份旧简历或一段 JD，它先写出一版能看的简历，再针对缺口追问；所有内容只来自你说过的话，不替你编数字。

线上体验：<https://resume.yikuaibanz.cn> · 基于 **FastAPI + LangGraph**

---

## 能干嘛

**先写后问**
- 首屏四个入口：自我介绍、上传旧简历、贴岗位 JD、从个人档案开始；也可以直接打字
- 信息够写就先出稿，出稿后再用问题卡补缺口（项目名称 / 起止时间 / 角色，再按岗位维度深挖），共享轮数预算，不没完没了地问
- 联系方式不阻塞出稿，整段对话最多问一次

**不编造**
- 事实只经确认后入库，正文每条都能追溯到你说过的原话；凭空出现的数字、职责会被核验拦下
- 候选改写需要你看过差异后明确采用，可随时撤销

**懂岗位**
- JD 解码：岗位要什么、你的证据缺口在哪；支持岗位截图识别
- 贴招聘链接自动读取岗位卡，联网补充公司信息

**长期档案**
- 登录后经历沉淀为个人档案，新简历可直接取用；支持来源、更正、删除和冲突处理
- 可把 ChatGPT / Claude 等其他 AI 对你的记忆导入档案，逐条确认后生效

**排版与导出**
- 7 款 A4 模板：简约单栏 / 深蓝横幅 / 深蓝细线 / 灰条夹页 / 浅蓝斜切 / 浅蓝色块 / 淡青平行
- 自动调一页：先调字号与间距档位，仍超页再给删减建议，不擅自删内容
- 网页精细编辑器：表单实时预览，悬停定位字段，栏目拖拽排序、改名、自定义；头像上传
- 服务端直出 PDF（常用字字体子集，单页渲染约 0.7s）与 Word

**接进你的 AI 助手（MCP）**
- 在 `/connect` 生成个人令牌，把胡话接进 Claude / Cursor 等支持 MCP 的助手
- 助手可读档案、按 JD 写稿、核对事实、测量排版、预览与导出；联系方式由服务端填入，不经过助手
- 导出时附带网页精细编辑链接，不满意的地方点进去直接改；同一份简历反复修改只保留一份草稿，并防止助手用旧稿覆盖你的手改

---

## 架构

```
用户 ──► SSE 聊天 ──► LangGraph
                       │
         AGENT_MODE=loop ──► orchestrator（模型编排工具，代码守底线）
                       │       工具：read_profile / use_profile_items / read_jd / search_company /
                       │             record_facts / ask_user / propose_plan / write_draft /
                       │             edit_resume / check_layout
                       │       护栏：事实只经 record_facts、fact_guard 核验、联系方式不进模型、
                       │             出稿后问卡与联系方式询问由代码兜底
                       │
         AGENT_MODE=off  ──► 阶段路由（triage → 收集 → 写稿 → 核对 → 导出）

按钮 / 表单 ──► 确定性路径（两种模式共用）
后台档案   ──► profile_archivist：已登录用户的事实经核验后归档
MCP        ──► /mcp（个人令牌 + 权限范围 + 限流），与网页共用同一份草稿与版本
渲染       ──► ResumeData → Jinja2 → WeasyPrint（PDF）/ python-docx（Word）
```

- `AGENT_MODE` 默认 `off`。编排模式的决策轮使用思考模式（漏记原话比慢两秒更严重），收尾纯文字轮关闭思考以省时。
- 真实模型回放（DeepSeek）：编排模式 10 个测试人物检查项 100% 通过，旧流程基线 95.8%。

---

## 启动

默认支持游客体验；导出、长期历史和个人档案需要邮箱验证码登录。运行需要加密密钥和账号密钥，先按 [账号与安全运维说明](docs/development/security-operations.md) 配置 `DATA_ENCRYPTION_KEYS`、`DATA_ENCRYPTION_ACTIVE_KEY`、独立的 `ACCOUNT_SECRET` 和邮件服务。本机 HTTP 设 `AUTH_COOKIE_SECURE=false`；公开环境必须 `APP_ENV=production`、HTTPS `APP_ORIGIN` 与安全 Cookie。**已有旧数据库不能直接启动新版**：先对离线副本迁移验证，再切换。

```bash
# 1. 仅首次复制示例配置；已有配置不要覆盖
cp -n .env.example backend/.env
# 填写数据密钥、账号密钥、邮件服务和 LLM_API_KEY；想试编排模式加 AGENT_MODE=loop

# 2. 安装依赖并启动
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
cd backend
../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8765

# 3. 打开浏览器
open http://127.0.0.1:8765/
```

- **模型**：DeepSeek 示例——`LLM_PROVIDER=deepseek`、`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL` / `LLM_STRUCTURED_MODEL` 填服务实际支持的模型名；其他服务与视觉模型配置见 `.env.example`。密钥不要提交到仓库。
- **PDF 依赖**：WeasyPrint 需要 Pango 与中文字体。Debian/Ubuntu 安装 `libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-cjk`；macOS 用 Homebrew 的 `pango` 并设置 `export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib"`。可用 `scripts/prepare_pdf_fonts.py` 预生成常用字字体子集、`scripts/build_template_previews.py` 预生成模板预览以加速渲染。
- **游客**：`ALLOW_GUEST_EXPERIENCE=true`、`GUEST_RETENTION_HOURS=24`、`GUEST_DAILY_TURN_LIMIT=20` 为默认值；游客数据加密临时存储，过期清理，不进入长期档案。
- **数据**：本地默认 `backend/data/huhua.db` 与 `backend/data/checkpoints.sqlite3`，线上按 `DATABASE_URL` 使用 Postgres。备份需同时保存两份数据库。

## 测试

```bash
.venv/bin/python scripts/run_tests.py -v
```

测试入口强制临时数据库、空模型与邮件配置，模型请求使用离线替身，不消耗额度；GitHub PR 自动运行同一套测试。真实模型表现用 `evaluation/persona-ux/` 下的人物回放评测（`run_persona.py`，可对比 `AGENT_MODE=off|loop`）。

编辑器交互回归（需本地服务，无需模型密钥）：

```bash
playwright-cli -s=huhua-editor open http://127.0.0.1:8765/resume
playwright-cli -s=huhua-editor run-code --filename=tests/resume_editor.browser.js
playwright-cli -s=huhua-editor run-code --filename=tests/resume_sections.browser.js
```

## 部署

- 单机 Docker 部署见 [Docker 部署步骤](docs/development/docker-deployment.md)（干净源码打包、Compose、Caddy HTTPS、持久数据卷）；现网版本与验证状态以 [服务器交接](docs/development/2026-10-05-server-deployment.md) 为准。
- 数据密钥、账号密钥、邮件凭证和 `LLM_API_KEY` 作为 Secret 注入，不进仓库。
- 首期只支持单个应用 worker：会话锁、模型并发和 IP 限流在进程内；扩到多实例前需要分布式锁与共享限流。
- 服务端最多接受 10MB 文件；正式扩量前需在网关限制请求体大小。

---

## 目录

```
backend/
  app/
    agents/     # orchestrator(_tools/_context) 编排 / resume_graph 阶段流程 / resume_writer 写稿 /
                # fact_extractor 事实抽取 / decoder_chain JD 解码 / profile_archivist 档案
    api/        # chat / resume / account / profile / conversations / mcp_download
    mcp/        # MCP 服务：工具、令牌鉴权与限流、写法指南、模板元数据
    services/   # 渲染、版本、事实核验、档案、MCP 业务、模板预览
    schemas/    # ResumeData 等 pydantic 模型
    tools/      # resume_data_docx（结构化 → Word）
  main.py
web/            # 首页、聊天工作台、简历编辑器（/resume）、MCP 接入页（/connect）
data/
  jianlimoban/html-template/  # 7 款 Jinja2 模板
  sample_resume.json          # 模板预览占位数据（胡小豆）
evaluation/     # 人物回放、改写评测与各批验收记录
docs/development/  # 各批规格、验收与部署文档
```

---

## License

MIT

---

Built by [@YIKUAIBANZI](https://github.com/YIKUAIBANZI)
