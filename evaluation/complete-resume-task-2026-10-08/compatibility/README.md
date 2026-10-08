# 旧浏览器测试适配验收（2026-10-08）

修改范围：`tests/product_suggestion_pdf.browser.js`、`tests/guest_experience.browser.js`、`tests/resume_provenance.browser.js`。仅更新测试及本目录证据，未修改产品代码。

- 游客与登录衔接：28 / 28 通过。API 全部 mock，保留游客导出阻断、登录认领/重试、输入保留与编辑保存顺序边界。结果摘要在 `guest-experience.json`；首轮完整成功 stdout 只在工具调用中观察，未存档。
- 经历来源与样例：31 / 31 通过。保留 item_id、删除记录、并发保存、样例只读、原样例导出、会话归属断言；新增个人和样例 PDF 下载。完整 stdout 及 JSON 已保存。
- 真实加密应用建议采用 + PDF：14 / 14 通过。使用 `tests/product_live_server.py --port 8894`，临时数据库、内存验证码、虚构资料，无外部邮件或模型。含聊天第 4 模板刷新保持、进入全屏保持、全屏第 2 模板返回聊天保持这 3 项断言。
- 实际 PDF 下载后另用 pdfplumber 抽取：1 页、`%PDF-` 头、姓名「虚构打印验收」、已采用句「整理虚构文档测试。」均存在，不含编辑器操作文字。见 `pdf-text-check.json`、`suggestion-applied.pdf`、`suggestion-applied.txt`。
- 三个文件 `node --check` 和 `git diff --check` 均通过；没有只做语法检查的测试，没有重跑后端全套。

## 修复和失败尝试

1. 旧 Word mock 没有 ZIP 签名，已加 `PK\x03\x04`；旧 PDF print-popup 改为 `/api/resume/export/pdf/` + download 契约。
2. Guest 首次运行发现 CLI Node 沙盒无全局 URL；测试请求解析改用已有字符串查询解析模式，随后完整通过。
3. Provenance 首次在旧「查看模板样例」按钮超时、第二次旧「只能导出原样例」文案断言失败；产品现在无会话自动展示只读样例，测试按新入口/文案调整，事实来源与权限断言保留。
4. 本机首轮真实 PDF 返回 503：fixture 未设置 Homebrew 原生库路径。复用已安装依赖，以 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib XDG_CACHE_HOME=/private/tmp/huhua-font-cache` 重启后返回 200。
5. 个别独立 open 后的 CLI session 无法续接；改为同一命令 open + run，未更改用户浏览器。
6. CLI 的页面网络 Response.body() 在已成功下载时返回空数组；APIRequestContext 同端点返回正常 PDF。最终测试读取实际下载链接 Blob 的前 5 字节，并另用本地 pdfplumber 验证保存文件；未放宽实际 PDF 内容核对。

静态 fixture 仅监听 127.0.0.1:8893 / 8896，真实 fixture 仅监听 127.0.0.1:8894。测试结束关闭本次专用服务与浏览器会话。
