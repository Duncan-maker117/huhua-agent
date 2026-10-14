# 官网主页交付与验证

2026-10-15，分支 `overhaul/tailor`。方案 A：「把聊过的经历，写成一页真实的简历。」未 commit、push、部署。原有未跟踪设计稿、素材 PNG、评测目录保持原样；保留其他任务新增的 mmr 评测交接。

## 文件清单

新增：

- `web/home.html`、`web/home.css`、`web/home.js`：官网、独立视觉 token、复制/导航/FAQ 链接/移动菜单。
- `web/home/editor-1440.webp`。
- `web/home/tpl-{t001-jianyue,t002-jianyue,t003-shenlan,t004-jianyue,t1000,t1001,t1002-jianyue}.webp`。
- `web/home/hero-illustration.png`、`web/home/hero-illustration.webp`。
- `tests/test_home_page.py`、`tests/home.dom.js`、`tests/home_entry.dom.js`、`tests/home.browser.js`。
- `docs/development/2026-10-15-home-page-verification.md`（本文件）。

修改：

- `backend/main.py`：官网/工作台路由与旧书签重定向。
- `backend/app/services/mcp_service.py`：收件箱确认地址和保存稿对话地址。
- `web/index.html`：工作台入口、面板查询参数和资源版本。
- `web/conversation-history.js`：切换、新建、删除对话时保持 `/chat` 路径。
- `web/account-profile.js`：登录后接续指定面板；来源、岗位和退出链接。
- `web/resume.html`、`web/resume-editor.js`：返回聊天、资源版本、官网指定模板预览。
- `tests/test_mcp_ui.py`、`tests/test_mcp_protocol.py`：更新资源版本断言并校验 MCP 返回链接。
- `tests/{account_login,change_card,chat_stream,complete_task_live,conversation_history,conversation_history_live,guest_experience,product_encrypted_live,product_profile,profile_import_status,resume_embedded,resume_export,resume_provenance,resume_workspace,tailor_panels}.browser.js`：工作台入口改为 `/chat`，相应静态页面桩与返回地址断言同步。
- `evaluation/project-review-2026-10-05/run-real-browser.js`：可执行评测脚本的工作台入口。
- `mmr.md`：只新增本次状态与验证说明，保留并行任务的交接。

## 路由与交互

| 入口 | 行为 |
|---|---|
| `/` | 新官网，不加载工作台 Tailwind 或外部字体/CDN |
| `/chat` | 原聊天工作台 |
| `/?session=…` | 302 到 `/chat?<原查询串>`，固定本地路径，包含空 session 的旧链接也兼容 |
| `/chat?panel=profile` | 打开档案；未登录时先显示现有登录表单 |
| `/chat?panel=connect` | 打开连接 AI 助手；未登录先登录，成功/游客认领后保持目标视图 |
| `/chat?profile=inbox` | MCP 网页人工确认入口 |
| `/resume?template=<模板 ID>` | 优先选择对应模板；未知 ID 继续使用原有模板偏好 |
| `/resume`、`/mcp` | 继续原有用途 |

官网命令使用 `location.origin`，复制的令牌仍为占位符。所有官网静态引用使用 `?v=20261015-home1`。7 张模板按 `788 / 710` 固定比例、`object-fit: cover`、顶部对齐裁掉提示条。截图为 1440×900，插画为 600×582，全部声明尺寸；产品截图优先加载，其他图片 lazy。

## 插画

使用内置 imagegen 生成，非 SVG 回退。透明 PNG 为 **74,026 字节**，同时提供 WebP。使用 Pillow 按用户要求压缩、转换，保留 alpha。

生成提示词：

> Use case: illustration-story. Asset type: small editorial hero illustration for a Chinese resume product website, displayed beside a serif headline. One human hand gently folds a simple speech bubble into a single sheet of resume paper, with just a few small horizontal ink lines suggesting writing. Minimal hand-drawn editorial pen line art inspired by Anthropic website illustrations, natural slightly imperfect strokes, restrained and airy. Ink #121212 with only two small terracotta #d97757 accent details. Genuine transparent background, generous empty space, square composition, no text, no letters, no logos, no gradient, no 3D, no shading, no painted background. Crisp recognizable silhouette at 220 pixels. Return the generated image as a local file usable in a code workspace.

## 验证

避免测试自行读取真实 `.env` 或私有样例，在 `/private/tmp/huhua-home-verification` 建立只含源码、公开素材、测试和公开模板配置的副本。虚拟环境指向仓库现有 `.venv`；`.env.example` 来自 Git 中的公开样例，没有复制真实配置、数据库、`cases-private/`、`runs-private/` 或 `data/output/`。

执行：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py
```

结果：**Ran 1470 tests in 51.894s — OK (skipped=2)**，即基线 1462 + 新增 8；1468 通过，2 项依赖本机私有材料的用例跳过。41 份改动源码/资产与该通过副本 SHA-256 一致（交接文档不计）。完整日志：`/private/tmp/huhua-home-tests.log`。

新增验证覆盖首页/工作台内容、原始查询串 302、`//evil.com` 等路径不得出站、官网资源本地且带版本、编辑页返回地址、复制成功/拒绝反馈、登录态导航、菜单/Escape、隐私锚点、登录后连接视图与游客认领接续、指定模板及无效 ID 回退。MCP 用例额外校验返回的网页地址。

浏览器使用 Playwright 合成接口，无真实用户、发信或模型调用。首轮官网脚本检查通过：标题、当前 origin 命令、复制、FAQ、390px 无横向溢出、移动菜单/Escape、7 图裁切、已登录导航、减少动态效果、无脚本异常与外部资源请求。随后加载所有 lazy 图片补拍完整截图并人工审阅。复用同一浏览器重跑曾遇到测试桩重复定义 clipboard，已将桩改为 configurable；最后额外复跑受当前沙箱 Chrome 启动权限限制，未重新启动真实服务。

- `/private/tmp/huhua-home-desktop-hero.png`、`/private/tmp/huhua-home-mobile-hero.png`：首屏。
- `/private/tmp/huhua-home-desktop.png`、`/private/tmp/huhua-home-mobile.png`：完整页面，模板已加载。
- JavaScript 语法与 `git diff --check` 通过。

## 文案边界与未验证项

- MCP 代码支持额外授予联系方式权限，因此表述为「默认权限下，助手看不到电话和邮箱」，没有承诺所有授权模式下都不可见。
- 设计稿「换个说法不会误判冲突，所有修改可撤销」改为代码能支撑的「核对已有信息、减少重复与冲突、档案更新支持撤销」，没有承诺零误判或所有操作均可恢复。
- 隐私沿用当前说明：访客闲置 24 小时清理、登录后长期保存、可删除、第三方模型处理；明确档案信息与原聊天需分别删除。未添加“不用于训练”等承诺。
- 分享图采用生产域名的绝对 URL，指向已有 editor PNG；实际社交平台抓取效果未验证。
- 本轮没有真实账号/客户端 MCP 联调、模型质量评测或线上部署；官网展示不构成这些链路的重新验收。
