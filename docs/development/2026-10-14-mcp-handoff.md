# MCP M1 + M2 本地交接

2026-10-14，分支 `overhaul/tailor`。按 `2026-10-14-mcp-plan.md` 第 10 节实现；未 commit、push、部署或修改真实库。

## 已实现

- `/mcp`：MCP 2.3 Streamable HTTP，8 个工具、档案与模板预览资源、2 个提示词模板。每次应用 lifespan 创建新的 SDK session manager，正常启动和关闭，兼容同一应用的重复启动。
- PAT：`hh_pat_` + 32 字节随机数，只存 SHA-256；Cookie 登录用户可设置名称、scope、1–365 天有效期（默认 90）、查看和吊销。MCP 不使用 Cookie；令牌错误、吊销、过期均返回 401 / `WWW-Authenticate: Bearer`。scope 拒绝以工具错误返回。
- 联系方式：默认 PAT 不带 `profile:contacts`；档案默认不返回 basic 联系方式，显式请求还需相应 scope。save / export 从账号已确认的 active basic 事实解密，复用 `context_to_collected_info` 的链接映射和 `protect_data` 的隐私保护，覆盖客户端姓名、电话、邮箱及个人链接；无档案值的对应字段留空。PDF / DOCX 和网页草稿保留服务端填入值；无 contacts scope 的工具返回（含 fact_check 回显）仍脱敏。返回标志为 `contacts_filled_by_server: true`。
- 限频：每令牌每分钟 60 个 HTTP 请求（包括初始化）；measure/export 合计每分钟 10 次，缩略图也计入此渲染配额；propose 每 24 小时滑动窗口 200 条。进程内实现。
- 审计：服务日志仅记录 token_id / tool / duration_ms / status_code；网页从进程内有界缓存显示本账号最近 50 次，缓存补充 UTC `called_at`。有效期、最后使用和最近调用时间统一按浏览器本地时区显示 `YYYY-MM-DD HH:mm`；缺失 / 无效时间给安全占位。缓存重启清空，界面已说明；不记录参数或返回正文。
- 收件箱：加密载荷、30 天有效期、pending / accepted / rejected / expired；重复待确认候选复用 ID，已确认的等价内容标记“已存在”。确认入口只有 Cookie API，走既有 `enqueue_archive_event` 的 `source_kind="manual"` 载荷及 `_apply_proposal`，同一事务复用冲突、等价、历史和撤销。失败回滚，不恢复已删除的事实。
- save：每次新建网页可见的 MCP 对话与版本，保存前强制词法检查，“核对”页显示问题。MCP 草稿不会写入事实母版或档案，不伪造用户消息。
- export：PDF / DOCX 生成完毕后返回随机一次性 URL，10 分钟有效，单文件上限 5 MB、全进程缓存上限 50 MB。下载不用 Cookie 或 PAT，消费后及过期均为 404。
- 网页：连接 AI 助手、令牌仅显示一次、复制 Claude Code 命令和 Cursor / Codex 配置、吊销、最近调用；信息确认增加 AI 建议及三个操作，红点包含 pending 收件箱。关闭面板移除令牌 DOM，不写浏览器存储。改后确认使用 accept 接口的可选 `value`。

## 工具约定

| 工具 | scope | 关键输入 / 输出 |
|---|---|---|
| `huhua_profile_get` | `profile:read` | `include_contacts=false`、`categories?`；事实正文在 `untrusted_text` |
| `huhua_templates_list` | 有效 PAT | 模板名称、风格、适用说明、容量与 preview URI |
| `huhua_resume_get` | `resume:read` | `conversation_id?`；最近已保存稿、版本号与 source |
| `huhua_resume_measure` | 有效 PAT | `resume`、`template_id`、`density?`；复用生产测页 |
| `huhua_facts_propose` | `profile:propose` | `candidates` 1–50 条，字段为 category / subject / field / value / evidence |
| `huhua_resume_check_facts` | `profile:read` | `bullets: [{id?, text, fact_ids}]`；仅词法，不调用 LLM |
| `huhua_resume_save` | `resume:write` | `resume`、`template_id?`、`citations?`；新对话链接和检查结果 |
| `huhua_resume_export` | `resume:export` | `resume` 或 `conversation_id` 二选一、`template_id`、`format`、`citations?`；读已有对话另需 `resume:read` |

`citations` 用 JSON pointer 对应档案 fact ID，例如 `{"/projects/0/polished_bullets/0": ["档案事实 ID"]}`。save / export 检查全部可打印文本，包括标题和日期，未引用的文字也标待核对。词法通过不代表语义已核实。

measure 返回 `suggested_density`，客户端应将它设到 `resume.layout` 后再测量 / 导出；服务不会静默改写正文。显式的 `layout.density_source="user"` 沿用现有测页语义。

## 验证

实机反馈修复后的最终本地验收（`20261014-mcp2`）：在不含私有目录、输出、数据库或凭证的 `/private/tmp/huhua-mcp2-safe-_ejvdr1s` 源码副本运行下列原命令，**1377 项，1375 通过、2 项私有样例自动跳过、0 失败（44.441s）**。新增 2 项协议回归并更新现有实物导出和 DOM 测试：无 contacts scope 的 PDF / DOCX 包含档案电话、邮箱及个人链接，工具返回无联系方式；客户端假值覆盖，档案缺项清空，账号隔离；MCP 保存后网页 PDF 可导出，按对话导出同样填充；上海 / 纽约时区、跨日、缺失及无效时间显示正确。Ruff（忽略既有 E402）、JS 语法和差异检查通过。修复后的真实 Claude Code 复验未在本轮执行。

指定命令：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py
```

在 `/private/tmp/huhua-mcp-safe-h4qr39do` 的临时源码副本执行：**1375 项，1373 通过，2 项私有样例测试自动跳过，0 失败（45.073s）**。副本从已跟踪源码及本轮新增文件建立，排除私有目录、输出、数据库、凭证和历史评估运行目录，仅复用已安装的 `.venv`。没有读取原仓库 `cases-private/`、`runs-private/`、`data/output/` 或真实 key。

新增 20 项：18 项 SDK 真实 Streamable HTTP / ASGI 协议测试和 2 项前端测试。覆盖工具结构及各 scope 拒绝、收件箱不变量与 manual 来源、等价和 pending 去重、冲突 / 撤销 / 回滚、账号隔离、令牌鉴权、默认脱敏、真实测页比对、抛异常假 LLM、网页对话可见性、一次性 / 过期 / 大小限制、审计、限频、重复 lifespan、smoke 脚本输出。DOM 覆盖新分区、一次显示、三种复制、吊销、确认 / 编辑 / 拒绝及红点。

修改 Python 的 Ruff（忽略既有 E402）、JS 语法及 `git diff --check` 通过。最后补充模板适用说明后再次定向执行全部 MCP 测试。

## 与早期规格的差异和边界

- SDK 使用 `MCPServer`、新表不提升 `SCHEMA_VERSION`、下载采用随机能力令牌，均按第 10 节覆盖早期描述；只增加 `personal_access_tokens` 和 `profile_inbox`，不改旧表列。
- 返回当前注册表的 **7 款**模板，保留后来加入的模板，未按早期“6 款”删减。缩略图用公开虚构样例离线生成并缓存。
- save 采用规格允许的“新对话”分支，不覆盖已有对话。审计日志保留由运行日志管理，网页最近调用缓存重启清空。配额和下载缓存均为单进程；下载链接在服务重启后失效。
- 仓库没有 `Dockerfile.release`。现有 `Dockerfile` 从 `requirements.txt` 安装依赖，已固定 `mcp==2.3.0`；若后续使用只复制代码的外部发布流程，必须另行重建依赖层。本轮未操作镜像或部署。
- 本轮离线，未操作真实账号 / 真实令牌，也未完成 Claude Code / MCP Inspector 实机验收、线上审计抽查或服务器 P95 测量。Python 3.13 本地已验证，语法兼容镜像 Python 3.12，但未构建运行 3.12 镜像。
- 样例 smoke 检查 PDF 签名和下载成功，不把无引用样例的词法结果说成零问题，也不替代第 7 节的真实 JD 验收。OAuth 和托管写作属于 M3，未实现。

## 本地启动与手动验收

在已配置账号和加密存储的本地环境，仓库根目录运行（本轮没有读取或变更这些配置）：

```sh
APP_ENV=local APP_ORIGIN=http://127.0.0.1:8000 AUTH_COOKIE_SECURE=false \
LLM_API_KEY='' ENABLE_RAG=false DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
.venv/bin/uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log
```

1. 打开 `http://127.0.0.1:8000/`，登录测试账号，进入“我的档案 → 连接 AI 助手”。生成默认权限令牌，复制面板上的 Claude Code 命令：

   ```sh
   claude mcp add --transport http huhua http://127.0.0.1:8000/mcp --header "Authorization: Bearer <token>"
   ```

2. 在 Claude Code 的 MCP 列表确认连接，让它调用 profile_get / templates_list；提交至少 3 条虚构、有 evidence 的候选。确认之前 profile_get 不应出现候选；到网页分别确认、改后确认、拒绝，再读档案。确认产生冲突时在“信息确认”中继续选择，不能将 accepted 等同于已覆盖原值。
3. 用虚构档案和公开 JD 组织带 fact_ids 的要点，check_facts → measure → 按建议设置 layout → export。核对 PDF 为一页，新增数字 / 工具警告为零。再 save，网页历史出现“AI 助手（MCP）简历”，核对页可见检查结论。
4. 吊销测试令牌，重试应失败；Cookie 单独访问 `/mcp` 应为 401。若采用空 LLM key 的上述启动方式，MCP 验收不需要配置模型。

脚本使用环境变量，不把令牌写进命令参数；在 zsh 隐藏输入：

```sh
read -rs 'HUHUA_MCP_TOKEN?粘贴测试令牌（不回显）: '
export HUHUA_MCP_TOKEN
.venv/bin/python scripts/mcp_smoke.py --url http://127.0.0.1:8000 --token-env HUHUA_MCP_TOKEN
unset HUHUA_MCP_TOKEN
```

脚本实际执行 list tools → profile_get → templates_list → 测量 `data/sample_resume.json` → 导出 PDF → 匿名消费下载链接。只打印结构与计数，错误只给固定代码，不打印档案值、令牌或下载 URL。脚本流程已通过 ASGI 内存传输验证。

## 本轮文件清单

新增：

- `backend/app/mcp/__init__.py`
- `backend/app/mcp/auth.py`
- `backend/app/mcp/server.py`
- `backend/app/services/mcp_service.py`
- `backend/app/api/mcp_download.py`
- `scripts/mcp_smoke.py`
- `tests/test_mcp_protocol.py`
- `tests/test_mcp_ui.py`
- `tests/mcp_profile.dom.js`
- `docs/development/2026-10-14-mcp-handoff.md`

修改：

- `backend/app/models/account.py`
- `backend/app/models/profile.py`
- `backend/app/services/profile_service.py`
- `backend/app/services/canonical_resume.py`
- `backend/app/api/account.py`
- `backend/main.py`
- `requirements.txt`
- `web/account-profile.js`
- `web/account-profile.css`
- `web/index.html`
- `web/resume.html`
- `mmr.md`

静态引用版本为 `20261014-mcp2`；没有新增 Tailwind utility，因此未重新编译 `tailwind.css`。原本未跟踪的规格文件及评估 runs 原样保留。
