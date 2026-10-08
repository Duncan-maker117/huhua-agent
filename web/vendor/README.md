# 固定版本浏览器依赖

核验日期：2026-10-02。直接使用本地浏览器分发文件，无 npm 安装、构建步骤或运行时 CDN 请求。

| 文件 | 固定版本 | 上游 | 许可证 |
| --- | --- | --- | --- |
| `marked.umd.js` | 18.0.14 | [Marked 官方标签](https://github.com/markedjs/marked/releases/tag/v18.0.14) | MIT，见 `marked-LICENSE` |
| `purify.min.js` | 3.4.16 | [DOMPurify 官方标签](https://github.com/cure53/DOMPurify/releases/tag/3.4.16) | Apache-2.0 或 MPL-2.0，保留 `dompurify-LICENSE` 和 `dompurify-LICENSE-MPL` |

`sources.json` 记录版本、官方 npm archive URL、registry metadata URL、archive SHA-512 integrity 与本地文件 SHA-256。下载后先核对 registry 的 SHA-512，再从 archive 复制指定分发文件和许可证；没有修改第三方源文件，也没有运行包脚本。这是传输与包内容一致性校验，不等同于独立软件供应链审计或 Sigstore 签名验证。

[Marked 官方用法](https://marked.js.org/)明确说明 Marked 不清洗 HTML，建议配合 DOMPurify。`chat-markdown.js` 使用两者：先解析，再用标签/属性 allowlist 清洗，最后检查链接协议。图片语法只展示 alt text，原始 HTML 以文字展示，避免资源自动加载；脚本、事件、危险链接、SVG、表单和嵌入标签无法变成活动 DOM。

## 接入与行为

按顺序加载 `marked.umd.js`、`purify.min.js`、`chat-markdown.js`，并加载 `chat-markdown.css`。调用：

```js
window.HuhuaMarkdown.render(element, originalMarkdown, { streaming: true });
```

- 渲染器给容器加 `.chat-markdown`；它只更新容器 DOM，不保存、改写或回传原文，也不设置 `aria-busy`。
- `streaming: false` 用于完整回复与历史消息，支持标准 Markdown/GFM。
- `streaming: true` 还对未闭合的简单 `**` 临时显示粗体，或隐藏仅有的 `**` 尾标记。中断时可继续用该模式显示已收到的片段，持久化仍用原文。
- `**标题 **` 的多余关闭空格仅由一个窄范围 Marked inline extension 容错；代码、转义标记和 ASCII 单词内 literal 由标准 parser 保留。
- 未闭合的复杂嵌套强调、单星号/下划线强调或不完整链接不做自定义修复；完整文本仍交给标准 Markdown parser。完整历史中故意未闭合的 literal 保持原样。
- 代码为纯文字等宽排版，没有新增语法高亮库。GFM 表格和长代码在消息内横向滚动。
- 缺失依赖、不支持 DOMPurify 或解析异常时退为 `textContent` 纯文字，禁止退回未清洗 `innerHTML`。

升级时替换固定版本并更新 checksum / license，再执行针对性的格式、流式与安全 DOM 验证。

## Tailwind 浏览器运行时

`tailwindcss-3.4.17.js` 是原首页已使用的 [Tailwind 官方 CDN 响应](https://cdn.tailwindcss.com?plugins=forms,container-queries)的完整本地副本，包含原有 forms、container-queries 插件。文件内部声明版本 `3.4.17`，保留了第三方注释；主库 MIT 许可见 `tailwindcss-LICENSE`，来源为 [官方 v3.4.17 LICENSE](https://github.com/tailwindlabs/tailwindcss/blob/v3.4.17/LICENSE)。

2026-10-02 实际浏览器多次出现外部 CDN 阻塞 HTML 解析、返回聊天时页面没有 body；因此只把同一运行时改为本地加载，保留原配置与 UI。`tailwind-sources.json` 记录下载地址、字节数、SHA-256 与验证边界。该文件是冻结的现有 CDN 构建，并非 npm archive；校验值仅确认本地文件字节，未独立验证发布签名。生产构建 CSS 的迁移不在本次改动范围。
