# 真实加密后端与界面联调

2026-10-04。本批使用 `main.app` 的真实路由、认证、生命周期、SQLAlchemy、LangGraph checkpoint、档案与简历服务，以及真实前端静态资源。

隔离环境：`127.0.0.1:8894`；新建临时应用 SQLite 与 checkpoint；随机进程内测试加密密钥和账号秘密；`APP_ENV=local`、`REQUIRE_ACCOUNT=true`、`AUTH_COOKIE_SECURE=false`、`ALLOW_INSECURE_LOCAL_STORAGE=false`、`LLM_API_KEY=''`。只把 SMTP 传输替换为内存 Mailbox，验证码仍通过真实 start/verify 与持久登录挑战验证。邮箱仅接受虚构的 `@huhua-fixture.invalid`；没有外发邮件或模型请求。未读取、迁移或连接原 8765 用户数据库。

## 验收结果

`verification.json` 中 22 项真实联调检查通过，浏览器脚本异常为 0：

- 未登录不能读取个人档案；真实验证码登录设置 HttpOnly / SameSite=Lax Cookie。
- 通过界面新增姓名与项目事实，并显式用于当前简历。
- 在真实编辑页修改姓名，实际保存后刷新仍一致。
- 通过当前简历原句选择、标点修改的依据核对、采用与撤销。此项不代表真实模型语义核对已验收。
- 通过真实界面下载 Word。
- 删除档案事实后，真实档案与 current 不再返回该事实；用旧稿尝试导出返回 409。刷新页面后再次成功导出当前稿。
- 第二个独立账号拥有新的会话与空档案；即使知道第一个账号的 session ID，读取简历、读取对话和删除均返回 404。
- 对应用 SQLite、checkpoint SQLite 及其 WAL / SHM 查找四个已写入的虚构标记，没有发现明文字节。浏览器 localStorage/sessionStorage 没有聊天或简历全文缓存。

Word 文件已按 ZIP 解包核对 `word/document.xml`：`nora-before-delete.docx` 包含目标事实，`nora-after-delete.docx` 不含；两者都保留手工修改并保存后的姓名。这些是虚构测试导出文件，作为验收证据保留。

桌面 `desktop-profile.png` 与 390px `mobile-profile.png` 已目视检查，档案内容和操作可读，手机无横向溢出。

## 重现

1. 在项目根目录执行 `.venv/bin/python tests/product_live_server.py --port 8894`。
2. 新建隔离 Playwright 浏览器，运行 `tests/product_encrypted_live.browser.js`。脚本不会拦截任何业务 API；只通过测试夹具的 `/__test__/otp` 读取内存邮件验证码。
3. 测试完成后关闭浏览器并停止夹具进程。进程正常退出会移除临时数据库，随机密钥不会保存到仓库。

本批测试没有修改业务认证或业务接口。未调用真实模型、发送真实邮件、部署公网服务或验证线上TLS。

## 补充：采用建议后的实际 PDF

同日再次使用新的临时加密数据库与虚构账号，运行 `tests/product_suggestion_pdf.browser.js`，5 项检查通过：建议通过界面核对并采用；持久 current 包含采用句；真实编辑页导出 PDF 打印窗口包含最新姓名与采用句；打印页没有编辑控件；打印不改变 canonical revision。

实际从该打印窗口用 Chromium PDF 输出保存 `suggestion-applied.pdf`，并用 Poppler 检查：1 页 A4，文字包含「虚构打印验收」「整理虚构文档测试。」；页面渲染 `suggestion-applied-render.png` 已目视检查，无缺字、重叠或截断。`suggestion-print-window.png` 是实际打印窗口截图，`pdf-verification.json` 是本轮结果。没有调用模型或外发邮件；标点采用不代表一般语义建议质量。
