# 第三方许可与素材清单

本文件记录随项目保留的第三方许可与素材使用边界，不授予任何新增权利。

## 浏览器依赖

以下文件与现有许可证、原始版权注释、校验记录一并保留，未修改其代码：

| 依赖 | 仓库记录版本 | 许可与声明 |
| --- | --- | --- |
| Marked | 18.0.14 | `web/vendor/marked-LICENSE`，MIT，含 MarkedJS 与 Christopher Jeffrey 版权声明 |
| DOMPurify | 3.4.16 | `web/vendor/dompurify-LICENSE`（Apache-2.0）、`web/vendor/dompurify-LICENSE-MPL`（MPL-2.0）；保留双许可文件 |
| Tailwind 浏览器运行时 | 3.4.17 | `web/vendor/tailwindcss-LICENSE`，MIT，保留 Tailwind Labs 声明和构建内注释 |

详细来源、固定版本与供应链检查边界见 `web/vendor/README.md`、`sources.json`、`tailwind-sources.json`。本次迁移不代表重新验证官方发布签名。

## Python 依赖及部署字体

直接依赖列在 `requirements.txt`，包含 FastAPI、LangGraph、LangChain、MCP、Chroma、WeasyPrint、python-docx 等，由安装流程获取，并非本次新打包其源码。多数版本使用下界范围，当前实际解析版本及传递依赖未锁定；旧部署目录的 resolved 清单不能代表新安装环境。发布源码前保留原有来源，分发镜像或二进制前应以实际安装版本的许可证与 NOTICE 做进一步核对。

源码清单未发现独立的 `.ttf`、`.otf`、`.woff`、`.woff2` 字体文件；PDF 构建涉及系统中文字体及字体子集，部署包需另行确认实际字体来源及相应许可。DOCX/PDF 内嵌资源未做全面权利审计。

## Word 模板、图片与示例输出

- `data/jianlimoban/` 含 147 个 Word 模板（包括 `_trash/` 与 `_trash_low_coverage/`）；本次未删除。
- 模板保留原始文件及其元数据；元数据不单独证明作者身份或许可范围。
- 第三方模板不因项目 README 的 MIT 声明而自动适用 MIT；再次使用、修改或分发时，应核对相应素材的授权范围。原仓库未附完整的素材授权文档。
- `web/home/`、`web/icons/`、`docs/design/`、`evaluation/` 中还包含图像、截图与示例输出。首页插画的制作记录见 `docs/development/2026-10-15-home-page-verification.md`；素材的来源记录、内嵌标识和权利声明均应保留。

## 项目自身许可与署名

源仓库：<https://github.com/YIKUAIBANZI/huhua-agent>，基线 main：`99abf966e8c19bf0ba05574251e4edb87bd066db`。

沿用原 README 的 MIT 声明及 `Built by @YIKUAIBANZI` 署名，保留原始提交历史与第三方声明。仓库位于 Duncan-maker117 账号下，不改变历史贡献者的署名，也不将第三方组件或素材归为该账号原创。
