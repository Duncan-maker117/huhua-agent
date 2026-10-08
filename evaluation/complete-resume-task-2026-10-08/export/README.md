# 模板恢复与真实文件导出验收

全部使用公开样例或虚构资料、独立临时加密数据库、内存邮箱，无真实邮件、模型调用或生产部署。

- `browser-checks.json`：最终浏览器 20 项通过，包含两个会话的模板刷新/切回恢复、先保存后导出、实际 PDF/Word 下载、保留下载入口、生成失败重试、响应头后文件正文停滞超时、保存失败阻止导出；页面异常 0。
- `browser-export.pdf` / `browser-export.docx`：真实浏览器下载的文件。`download-content-checks.json` 已分别抽取正文核对最新保存姓名与“完成了静态原型，尚未上线。”，保留 SHA-256。
- `pdf-regression.log`：新增后端 9 项通过；覆盖六模板 A4/中文/头像、长文分页、已保存稿权属、未登录拒绝、资源抓取阻断、异常恢复及无效照片处理。
- `render-checks.json`、六模板 PDF 和对应页 PNG、`template-render-review.png`：最终服务端渲染，6 个模板共 7 页；已目视检查中文、头像、页脚和跨页正文。简约单栏的样例内容自然排成 2 页，没有截断或强行缩小字体。

模板偏好仅按会话保存在当前浏览器 `huhua_resume_template:<session>`，值只含模板 ID，不含简历内容或登录凭证；尚不跨设备同步。账号退出的既有清理逻辑会移除该偏好。

PDF 使用 WeasyPrint 70.0，基于授权会话的已保存内容；上传照片仅允许 PNG/JPEG data URL，拒绝网络、文件和 SVG 资源。PDF 是实际下载文件，不再依赖弹窗打印。Word 的线上内置浏览器下载失败根因仍未独立复现；本轮补齐明确状态、保留文件链接与重试，并在本机 Chrome 验证实际下载，不能据此声称所有内置浏览器均已验证。

WeasyPrint 不支持模板内的 `clip-path` 与 `width: fit-content`，部分装饰色条的宽度/边缘和浏览器预览有轻微差异。Docker 已声明 Pango 和 Noto CJK，但本次没有构建 Docker 镜像；Linux字体/最终部署仍需发布阶段验收。

验证命令：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib XDG_CACHE_HOME=/private/tmp/huhua-font-cache .venv/bin/python scripts/run_tests.py -q -k ResumePdf
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib XDG_CACHE_HOME=/private/tmp/huhua-font-cache .venv/bin/python tests/product_live_server.py --port 8898
playwright-cli -s=huhua-export open http://127.0.0.1:8898/resume
playwright-cli -s=huhua-export run-code --filename=tests/resume_export.browser.js
playwright-cli -s=huhua-export close
```

最终验收后已停止专用 `huhua-export` 浏览器和本机 8898 夹具服务。官方 API 依据：[WeasyPrint 70 API](https://doc.courtbouillon.org/weasyprint/stable/api_reference.html)。
