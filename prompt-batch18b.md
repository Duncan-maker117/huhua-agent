# 第十八批 b：项目 / 工作经历的「技术栈」行

仓库：胡话简历（FastAPI 后端 `backend/`，前端静态页 `web/`，模板 `data/jianlimoban/html-template/*.html.j2`）。当前分支 batch18b（基于 batch18a `b9b4134`）。线上开启编排模式 `AGENT_MODE=loop`。产品原则：先写后问、**不编造**——事实只经 record_facts 进入、fact_guard 守底线、引用（citations / fact_ids）可追溯。

请先读懂相关代码再动手；只做本需求，不顺手重构。不要 commit / push / 部署，不调用真实模型（测试用桩）。

## 需求

用户原话：「有的项目需要标注技术栈，这个很重要，例如我们这个项目使用了 MCP、记忆、tool calling、longchain」。

已定方案（用户已拍板）：
- 项目（`ProjectItem`）和工作/实习（`WorkItem`）都新增可选字段 `tech_stack: list[str]`，为空时序列化省略（沿用 `exclude_if` 写法），旧数据完全兼容。
- 渲染位置：**条目标题行下方单独一行**「技术栈：MCP、Tool Calling、LangChain、长期记忆」，在要点列表之前；为空则不渲染这一行。

```
胡话简历 Agent ｜ 个人项目        2026.09—2026.10
技术栈：MCP、Tool Calling、LangChain、长期记忆
• 设计……
```

## 要求

1. **数据结构**：`backend/app/schemas/editor.py` 两个类加字段；MCP 的 `MCPResume` 等对外 schema 同步；canonical 保存、会话持久化、版本/撤销、diff/变更卡等所有复制或比较条目字段的地方都要带上（全仓搜索条目字段列表，如 `polished_bullets`、`links` 出现的地方，逐个判断）。
2. **不编造**：技术栈每一项必须来自用户原文（或档案中用户自己的事实）。可以做**确定性**的拼写/大小写规范化（如 longchain→LangChain、toolcalling/tool calling→Tool Calling、mcp→MCP），用一张小的别名表实现，不能让模型自由扩写；用户没说过的技术不得出现。按现有引用/事实覆盖机制给技术栈引用 fact_ids，fact_guard 或现有校验要能拒绝无来源的技术项。去重（规范化后同名只留一个），保持用户提及顺序，单条最多约 8 项。
3. **写稿**：编排模式（loop）的 write_draft / edit_resume 路径和旧流程 writer（`resume_writer.py`、`labeled_writer.py` 等）都能产出该字段。用户提到项目用到的技术/框架/协议/模型能力时填进去；用户明确说「标一下技术栈」「这个项目用了 X、Y」时必须填。要点正文里可以继续自然提到关键技术，但不要再出现一条纯罗列技术的要点（如「技术栈：……」作为 bullet），若出现则确定性移到字段里。`loop_followup.py` 已有 `tech_stack: "技术工具"` 槽位，请复用而不是另起一套。
4. **用户修改**：用户说「给 X 项目加上技术栈 A、B」「把 LangChain 去掉」时，edit_resume / 字面更正路径能增删该字段。
5. **模板**：全部 9 个模板（`_macros.html.j2` 的 project_head 及各模板中工作经历的头部）渲染该行，带 `data-field-path="/projects/{i}/tech_stack"`、`/work_experience/{i}/tech_stack`，样式与各模板现有副标题/角色行协调（字号同正文或略小、「技术栈：」可加粗）。一页排版测量（resume_capacity / measure）要把这一行算进去。DOCX 导出也输出这一行。
6. **网页编辑器**（`web/resume-editor.js` 等）：项目与工作条目可编辑技术栈（逗号/顿号分隔的单个输入框即可），保存后回写为列表。
7. **MCP**：`writing_guide.py` 写法指南说明该字段及「只填用户说过的技术」；`check_facts` 能校验它的引用；预览/导出正常渲染。
8. 静态资源版本号沿用 `20261021-1`（同一批发布）；若改了 batch18a 未改的前端文件，记得一并改版本号。

## 验证
- 新增测试至少覆盖：schema 兼容（旧数据无字段、空列表省略）；别名规范化与去重；无来源技术项被拒；loop 写稿桩与旧 writer 桩产出字段；纯技术罗列 bullet 移入字段；edit 增删；9 个模板渲染与 field-path；空字段不渲染；DOCX 含该行；编辑器 DOM（node 测试须 `skipUnless(shutil.which('node'))`）；MCP schema/check_facts。
- 全量：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py`，基线 2229 项全过，改动后必须全过。
- 改动的 Python 文件 Ruff 通过；`git diff --check` 通过。
- 不要改 `mmr.md` 以外的历史文档；在仓库根写 `batch18b-report.md`：改了哪些文件、设计取舍、测试数量与结果、未做/风险。
