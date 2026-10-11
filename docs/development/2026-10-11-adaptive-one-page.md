# 2026-10-11 排版自适应一页

分支 `overhaul/tailor`；保留已有提交及开始时的未提交改动（包括深蓝细线注册/容量/模板）。本次不读取或打印凭证，不调用真实模型，不 commit/push/部署。以下样本全部为虚构资料。

## 行为与数据

- 可选 `resume_data.layout = {density: 0..3, density_source: auto|user}`，旧数据缺省 0；非法类型/越界值在 API schema 拒绝，服务端渲染只使用整数档位生成固定 CSS 值。
- `measure_rendered_pages` 在一页要求且非 user 锁定时，从 0 依次试到 3，采用第一个合格档。仅调用生产 `measure_resume_pdf_layout` 的最终布局，不生成试排 PDF 字节、不调用模型、不改正文。选定档位写回调用方的投递文稿；页数、尝试记录和 hash 绑定选定后的文稿。
- 0 已合格时保持 0；自动稿内容变短后可回到较松档。两页要求不自动试档。user 锁定只测指定档位，保留用户选择。
- 3 仍超页才继续既有压缩、保留核验与删减建议；用户锁定档位时保留原档，用既有超页处理。试排出错保留原文/原档，页数未知，不借估计触发内容压缩。
- 保存后的页数重验会补建旧稿页数记录；旧“超页但内容 hash 未变”的缓存需要重新试排；有效新计页缓存可以继续复用。
- 字大一点/排松一点减 1；字小一点/排紧凑点加 1，夹在 0..3；自动调整解除锁定。经现有 `set_constraint` 执行器校验原话并更改 layout，纯排版对话绕过 router/writer 模型。操作可撤销，回复保留档位与实际页数。
- HTML 预览、PDF、两条 Word 导出路径均读取文稿 layout。编辑器保存成功后只同步返回的 layout 元信息，并刷新同版本预览；不覆盖保存期间的新输入。旧客户端缺 layout 时继承已保存设置。
- PR 号与仓库标题同行，标题及同行短“链接”均可点击，完整 URL 保留为 href/Word hyperlink 关系。页头使用不拆分的联系/链接单元；超过 60 字符的 URL 显示短“链接”，完整目标保留在 href/title 中。

## 实际 HTML 参数

正文尺寸含继承字号 / li 与 desc 字号；正文变量均不小于 9.5pt。日期、联系方式和装饰圆点保留各模板原有字号。0 档保留原正文几何，PR/联系栏优化在全部档位生效。所有模板配色、灰条/细线、斜切及装饰结构保留。

1 档间距系数 .65；2 档 .5；3 档 .4。栏目左右内边距保持风格；2/3 档页面左右/预览上下留白分别乘 .92/.88。PDF 上下边距为 10/10/9/8mm。

| 模板 | 档 | 正文/列表 pt | 行高 | 栏目字号 pt | 栏目上/下间距 px | 栏目 padding 上下/左/右 px | 条目/li 间距 px | 页左右/预览上下 | PDF 上下 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| t001-jianyue | 0 | 10.5pt/10pt | 1.7 | 11.5pt | 14px/8px | 6px/14px/14px | 14px/3px | 16mm/12mm | 10mm |
| t001-jianyue | 1 | 10.5pt/10pt | 1.5 | 11.5pt | 9.1px/5.2px | 3.9px/14px/14px | 9.1px/1.95px | 16mm/12mm | 10mm |
| t001-jianyue | 2 | 10pt/10pt | 1.42 | 11.5pt | 7px/4px | 3px/14px/14px | 7px/1.5px | 14.72mm/11.04mm | 9mm |
| t001-jianyue | 3 | 9.5pt/9.5pt | 1.38 | 11pt | 5.6px/3.2px | 2.4px/14px/14px | 5.6px/1.2px | 14.08mm/10.56mm | 8mm |
| t002-jianyue | 0 | 10pt/9.5pt | 1.65 | 11pt | 0px/8px | 5px/14px/14px | 12px/3px | 28px/0px | 10mm |
| t002-jianyue | 1 | 10pt/9.5pt | 1.5 | 11pt | 0px/5.2px | 3.25px/14px/14px | 7.8px/1.95px | 28px/0px | 10mm |
| t002-jianyue | 2 | 10pt/9.5pt | 1.42 | 11pt | 0px/4px | 2.5px/14px/14px | 6px/1.5px | 25.76px/0px | 9mm |
| t002-jianyue | 3 | 9.5pt/9.5pt | 1.38 | 10.5pt | 0px/3.2px | 2px/14px/14px | 4.8px/1.2px | 24.64px/0px | 8mm |
| t003-shenlan | 0 | 10pt/10pt | 1.45 | 11pt | 12px/8px | 0px/0px/0px | 8px/2.66667px | 35pt/35pt | 10mm |
| t003-shenlan | 1 | 10pt/10pt | 1.45 | 11pt | 7.8px/5.2px | 0px/0px/0px | 5.2px/1.73333px | 35pt/35pt | 10mm |
| t003-shenlan | 2 | 10pt/10pt | 1.42 | 11pt | 6px/4px | 0px/0px/0px | 4px/1.33333px | 32.2pt/32.2pt | 9mm |
| t003-shenlan | 3 | 9.5pt/9.5pt | 1.38 | 10.5pt | 4.8px/3.2px | 0px/0px/0px | 3.2px/1.06667px | 30.8pt/30.8pt | 8mm |
| t004-jianyue | 0 | 10pt/9.5pt | 1.65 | 11pt | 0px/6px | 4px/12px/0px | 10px/3px | 28px/0px | 10mm |
| t004-jianyue | 1 | 10pt/9.5pt | 1.5 | 11pt | 0px/3.9px | 2.6px/12px/0px | 6.5px/1.95px | 28px/0px | 10mm |
| t004-jianyue | 2 | 10pt/9.5pt | 1.42 | 11pt | 0px/3px | 2px/12px/0px | 5px/1.5px | 25.76px/0px | 9mm |
| t004-jianyue | 3 | 9.5pt/9.5pt | 1.38 | 10.5pt | 0px/2.4px | 1.6px/12px/0px | 4px/1.2px | 24.64px/0px | 8mm |
| t1000 | 0 | 10pt/9.5pt | 1.65 | 11pt | 12px/8px | 5px/14px/16px | 12px/3px | 14mm/12mm | 10mm |
| t1000 | 1 | 10pt/9.5pt | 1.5 | 11pt | 7.8px/5.2px | 3.25px/14px/16px | 7.8px/1.95px | 14mm/12mm | 10mm |
| t1000 | 2 | 10pt/9.5pt | 1.42 | 11pt | 6px/4px | 2.5px/14px/16px | 6px/1.5px | 12.88mm/11.04mm | 9mm |
| t1000 | 3 | 9.5pt/9.5pt | 1.38 | 10.5pt | 4.8px/3.2px | 2px/14px/16px | 4.8px/1.2px | 12.32mm/10.56mm | 8mm |
| t1001 | 0 | 10pt/9.5pt | 1.65 | 11pt | 12px/8px | 5px/14px/22px | 12px/3px | 16mm/12mm | 10mm |
| t1001 | 1 | 10pt/9.5pt | 1.5 | 11pt | 7.8px/5.2px | 3.25px/14px/22px | 7.8px/1.95px | 16mm/12mm | 10mm |
| t1001 | 2 | 10pt/9.5pt | 1.42 | 11pt | 6px/4px | 2.5px/14px/22px | 6px/1.5px | 14.72mm/11.04mm | 9mm |
| t1001 | 3 | 9.5pt/9.5pt | 1.38 | 10.5pt | 4.8px/3.2px | 2px/14px/22px | 4.8px/1.2px | 14.08mm/10.56mm | 8mm |
| t1002-jianyue | 0 | 10pt/9.5pt | 1.7 | 11pt | 12px/8px | 4px/16px/28px | 10px/3px | 16mm/12mm | 10mm |
| t1002-jianyue | 1 | 10pt/9.5pt | 1.5 | 11pt | 7.8px/5.2px | 2.6px/16px/28px | 6.5px/1.95px | 16mm/12mm | 10mm |
| t1002-jianyue | 2 | 10pt/9.5pt | 1.42 | 11pt | 6px/4px | 2px/16px/28px | 5px/1.5px | 14.72mm/11.04mm | 9mm |
| t1002-jianyue | 3 | 9.5pt/9.5pt | 1.38 | 10.5pt | 4.8px/3.2px | 1.6px/16px/28px | 4px/1.2px | 14.08mm/10.56mm | 8mm |

`t002` 栏目上间距在 `.section`，为 12/7.8/6/4.8px；`t004` 同值作用于栏目下间距。横幅 t002 页头上下 padding 为 14/9.1/7/5.6px，内容底 padding 24/24/22.08/21.12px；t004 内容上下 padding 为 20/20/18.4/17.6px。深蓝细线栏目独立行高 15/15/15/14pt，其余栏目继承正文行高。技能行/条目标题下间距随同间距系数收紧。

## Word 参数

通用 Word 保留 0 档现状：10.5pt 正文，内置 1.15 倍行距（docDefaults），上下 0.8in、左右 1in。Word 原行距已较小，使用以下对应档位，避免套用 HTML 的 1.5 导致 Word 反而拉长。

| 档 | 正文/列表 pt | 行距 | 普通段后 pt | 列表段后 pt | 栏目字号 pt | 页边距系数 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 10.5 / 原列表继承 | 原设置 | 原设置 | 原设置 | 13 | 1 |
| 1 | 10.5 / 10 | 1.1 | 6.825 | 1.4625 | 11.5 | 1 |
| 2 | 10 / 10 | 1.05 | 5.25 | 1.125 | 11.5 | .92 |
| 3 | 9.5 / 9.5 | 1 | 4.2 | .9 | 11 | .88 |

Word 按 twip 四舍五入段距。旧 DOCX 填充路径同时调整 Normal/List Bullet、表格单元段落、显式字体/段距和页边距；原有更小的倍数行距保留。遇到任意 PR/链接等原本就需结构化兜底的数据，兜底保留 layout。

## 验证

- 新增 `tests/test_resume_density.py` 17 项：生产布局最小选档；短稿与回松；用户锁定；两页要求；已生成 PDF 再试档；布局失败；旧超页缓存；7×4 模板变量/字号边界；链接同行/长 URL；通用和填充 Word；schema；无模型确定性对话及撤销；自动解锁；拒绝未提出指令；3 档超页进入既有压缩；加密 SQL/checkpoint 保存回读；授权预览/PDF/Word 读取同一档。
- t001 虚构 4/5/6 个项目在 0 档均为 2 页，最小可行档分别 1/2/3；5 项样本各档页数为 2/2/1/1。条目及 bullet 全部保留，只增加 layout。
- 10 项样本 3 档仍超页，进入原压缩/保留核验，并向用户说明继续缩句或移除；未核验文字不被测试替身错误压掉。
- 两个旧小溢出专项夹具显式锁定 user 0 档，继续验证原“合行”与“保留动作缩句”的回归。存储恢复测试比较完整 SQL metadata，兼容保存时新增 page_check。
- 指定全量命令：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py`。**1274/1274 通过，40.620 秒**。日志 `/private/tmp/huhua-density-verified-tests.log`；修改 Python 文件 Ruff（沿用仓库忽略 E402）通过；两份 JS 的 `node --check` 和 `git diff --check` 通过。

## 本次文件

- 新增：`backend/app/services/resume_layout.py`、`tests/test_resume_density.py`、本说明。
- 服务：`renderer.py`、`resume_pdf.py`、`resume_capacity.py`、`canonical_resume.py`、`edit_plan.py`、`resume_versions.py`（均在 backend/app/services）。
- Agent：`resume_graph.py`、`router.py`、`turn_actions.py`、`tailor_pipeline.py`（均在 backend/app/agents）。
- schema/Word：`backend/app/schemas/editor.py`、`backend/app/tools/resume_data_docx.py`、`backend/app/tools/docx_template_filler.py`。
- 模板：`_macros.html.j2` 与 `t001-jianyue`、`t002-jianyue`、`t003-shenlan`、`t004-jianyue`、`t1000`、`t1001`、`t1002-jianyue`（均在 data/jianlimoban/html-template，模板后缀 .html.j2）。
- 编辑器/卡片：`web/resume-editor.js`、`web/change-card.js`、`web/resume.html`、`web/index.html`（资源版本随修改更新）。
- 旧回归适配：`tests/test_replay_polish_regressions.py`、`tests/test_replay_remaining_regressions.py`、`tests/test_fact_draft_storage.py`。
- 交接：`mmr.md`。

## 剩余边界

PDF 实测一页与导出页数一致；Word 已核验 XML 字号、段距、行距、完整超链接和使用同一档位，但没有调用原生 Microsoft Word 排页，不把 Word 档位一致等同于各客户端最终页数一致。浏览器自动保存后的 layout 同步做语法/流程检查，未单独执行真实浏览器交互。没有部署。
