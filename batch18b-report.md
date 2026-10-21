# 第十八批 b：项目 / 工作经历技术栈行

完成日期：2026-10-21。分支 `batch18b`，基线 `b9b4134`（batch18a）。只修改本需求；未 commit、push、部署，未调用真实模型。

## 实现结果与设计取舍

- `ProjectItem` / `WorkItem` 新增 `tech_stack: list[str]`；缺省和空列表在序列化时省略，旧数据无需迁移。MCPResume 继承同一文档模型，外部 JSON schema 同步拥有该字段。
- `services/tech_stack.py` 统一完成别名、去重、提及顺序、8 项上限和来源匹配。确定性别名包括 longchain → LangChain、toolcalling / tool calling → Tool Calling、mcp → MCP；未知名称只在原文有对应字面证据时保留。单独“记忆”仍是“记忆”，不会擅自扩成“长期记忆”。
- loop 和旧 writer 共用投影入口：模型可以提出字段，但每个名称最终必须匹配当前经历的 active fact 原始引用。纯技术清单从 bullets / 项目 description 移到字段，具体技术动作仍留在正文。写稿覆盖检查认可技术栈清单的覆盖，不把它当作行动或成果的替代。
- 每项引用保存为 `resume_meta.tech_stack[item_id][index] = {text_hash, fact_ids}`；沿用现有事实、覆盖、版本与核对机制。fact_guard 对技术栈 JSON Pointer / claim_kind 使用确定性匹配，拒绝缺引用、失活引用、跨条目引用及原文没有的名称，不调用模型自由补全。复用既有 `tech_stack` 追问槽位，没有新增同义维度。
- 明确增删指令从实际用户消息解析，新增经 `record_facts` 入库，再修改稿件；工具参数中的模型转述不能代替用户原话。删除只影响当前呈现，并记录排除名称，避免下一次写稿自动加回；撤销可恢复旧文档及对应引用。网页编辑沿用现有 `append_editor_facts` 手动输入边界，修改过的技术栈列表由用户输入确认。
- canonical、SQL 会话、checkpoint、diff、版本、撤销、移动经历、局部重写、档案导入/撤销同步保留或清理字段与引用。已审查 `polished_bullets` / `links` 字段列表：整对象深拷贝和通用比较无需另加白名单；只针对标题、动作 bullet、URL 的逻辑保持原用途。`active_facts_for_writer` 继续仅传 active facts，避免从过时展示字段反向制造事实。
- HTML 在条目标题下、要点前显示“技术栈：…”，项目和工作均有 `data-field-path`；空值不显示。仓库实际为 **7 个当前可选模板、14 个模板文件**（另有宏），与需求中的“9 个”数量不同。本次覆盖全部 14 个文件，没有改变模板注册列表。
- DOCX 同样输出独立技术栈行。现有 resume_capacity / MCP measure 使用生产 HTML 的真实 WeasyPrint 测量，无需人为加行数；测试确认新增行增加实际高度，并分别增加项目、工作经历的测量行数。
- 网页用单个输入框编辑，支持逗号/顿号等分隔；列表回写，输入时预览保留“技术栈：”前缀。别名归一与最终 8 项限制统一在后端处理，避免前端提前截断有效名称。变更卡、核对页显示技术栈及引用；改动资源引用统一 `20261021-1`。
- MCP 写法指南说明用户来源和数组引用路径。`check_facts` 支持逐项路径和数组路径引用；外部传入文档保存/导出时，无来源技术会被拒绝。按 conversation_id 导出已有保存稿沿用当前存储权威边界，不要求重新提交 citations；档案失效清理仍生效。MCP 整体事实检查仍明确是词法初筛，不声称已完成完整语义核验。

## 验证

- 新增 **35 项 Python 测试**（含 Node DOM 测试入口）；覆盖旧 schema / 空值省略、别名与去重 / 上限 / 顺序、来源与失活 / 否定 / 计划 / 引用、loop 与旧 writer 桩、labeled writer、纯清单迁移、增删与撤销、删除不复活、14 模板及 field-path、空/隐藏项、DOCX、真实 PDF 测量、MCP schema / check / 保存 / 预览 / 导出、SQL 与 checkpoint 持久化、档案撤销。
- Node DOM 执行实际编辑器和变更卡代码，验证项目与工作输入、列表保存、清空、即时预览前缀、别名归一前不提前截断。Python 入口使用 `skipUnless(shutil.which('node'))`；本机 Node 测试实际执行通过。
- 更新 batch10 的一个旧测试：原先断言纯技术清单必须在 bullet，现检查独立字段仍为 Spring Boot / MySQL，并保留动作、分工、日期及限制断言；没有删除测试或放松来源校验。
- 指定全量命令：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

- 最终全量结果：**Ran 2264 tests in 103.210s — OK (skipped=2)**，即 2262 通过、2 跳过、0 失败/错误；相对基线 2229 项新增 35 项。两项既有跳过来自未随仓库分发的私人基准材料，新增测试无跳过。最终日志：`/private/tmp/huhua-b18b-full-verified.log`。

- 改动的 **30 个 Python 文件** Ruff 通过；3 个修改的 JavaScript 文件 `node --check` 通过；`git diff --check` 通过。
- 测试脚本使用临时数据库、清空模型及检索凭据；写稿、语义判定等全部用桩。日志中的 provider 成功/失败记录来自既有离线测试替身，不是本轮真实模型调用。

## 未做与边界

- 未做真实模型效果测试、线上验证或发布。没有新增接口授权、重构测试框架或改变模板可选列表。
- 自动名称提取有意保守：否定、计划、示例不成为技术栈；复杂句式不能确定时，不猜名称。未知技术可用明确列表输入或由 writer 提出、再按原文逐项验证。
- 技术栈可能换行并增加页数；测量会计入实际占用，不承诺任意内容仍是一页。DOCX 继续使用既有通用 Word 导出样式。
- 未修改历史文档；仅更新 `mmr.md` 并新增本报告。开场已有的未跟踪 `prompt-batch18b.md` 保留原样。

## 文件清单

以下为本批实现、测试和交接文件（相对仓库根目录）：

- `backend/app/agents/advisor.py`
- `backend/app/agents/interviewer.py`
- `backend/app/agents/orchestrator_tools.py`
- `backend/app/agents/profile_archivist.py`
- `backend/app/agents/resume_graph.py`
- `backend/app/agents/resume_writer.py`
- `backend/app/agents/tailor_pipeline.py`
- `backend/app/mcp/writing_guide.py`
- `backend/app/schemas/editor.py`
- `backend/app/schemas/writer.py`
- `backend/app/services/canonical_resume.py`
- `backend/app/services/edit_plan.py`
- `backend/app/services/fact_corrections.py`
- `backend/app/services/fact_coverage.py`
- `backend/app/services/fact_guard.py`
- `backend/app/services/labeled_writer.py`
- `backend/app/services/mcp_service.py`
- `backend/app/services/named_content.py`
- `backend/app/services/profile_bridge.py`
- `backend/app/services/profile_memory.py`
- `backend/app/services/profile_service.py`
- `backend/app/services/resume_facts.py`
- `backend/app/services/resume_provenance.py`
- `backend/app/services/resume_review.py`
- `backend/app/services/resume_sections.py`
- `backend/app/services/resume_versions.py`
- `backend/app/services/tech_stack.py`
- `backend/app/tools/resume_data_docx.py`
- `batch18b-report.md`
- `data/jianlimoban/html-template/_macros.html.j2`
- `data/jianlimoban/html-template/t001-jianyue.html.j2`
- `data/jianlimoban/html-template/t002-jianyue.html.j2`
- `data/jianlimoban/html-template/t003-jianyue.html.j2`
- `data/jianlimoban/html-template/t003-shenlan.html.j2`
- `data/jianlimoban/html-template/t004-jianyue.html.j2`
- `data/jianlimoban/html-template/t016-jianyue.html.j2`
- `data/jianlimoban/html-template/t017-jianyue.html.j2`
- `data/jianlimoban/html-template/t062-biaoge.html.j2`
- `data/jianlimoban/html-template/t1000.html.j2`
- `data/jianlimoban/html-template/t1001.html.j2`
- `data/jianlimoban/html-template/t1002-jianyue.html.j2`
- `data/jianlimoban/html-template/t101-biaoge.html.j2`
- `data/jianlimoban/html-template/t1010.html.j2`
- `data/jianlimoban/html-template/t1018-huise.html.j2`
- `mmr.md`
- `tests/batch18b.dom.js`
- `tests/test_batch10_regressions.py`
- `tests/test_batch18b.py`
- `web/change-card.js`
- `web/index.html`
- `web/resume-editor.js`
- `web/resume-workspace.js`


## 修复轮

完成日期：2026-10-21。保留 Claude 的 `LIST_ONLY`、`split_spaced` 和 `TechStackProseBoundaryTests`；原 `tests/test_batch18b.py` 无改动。本轮只做离线复现、代码修复与验证，未调用真实模型，未 commit / push / 部署。

### 根因与回放证据

1. **数据丢失是事实误删触发保存层清理。** 只读导出原 checkpoint：第二轮结束 `1f1cd068-4434-66c6-8008-17517aba4acb` 保留 4 项技术、3 条要点；第三轮图状态 `1f1cd068-c2f0-6500-800b-5b1394e6072f` 的稿件尚未变化，但 `record_facts` 已将整条「项目使用了 mcp 记忆 toolcalling longchain」标为 `deleted`，另录入 FastAPI。最终保存协调后的 `1f1cd068-c43c-6c42-800c-f9581b740bd2` 只剩 MCP 和 1 条要点。原 `parse_stack_edit` 只认完整经历名称，未分开项目和工作候选，且 removal 分支优先、不能执行复合增删；定位失败后 `record_facts` 继续通用模型提取，误删复合事实。`save_resume_session → protect_data → sanitize_fact_history` 随后清理失活来源及其正文引用。两次 `edit_resume insufficient` 本身没有产生正文更新。
2. **正文缺少规范化与子句清理。** 原 `project_item_stack` 只迁移整条纯清单，无法移除混在动作要点里的「项目采用 MCP、记忆与 Tool Calling 方案」，也未把正文里的 longchain 替换成 LangChain。
3. **误导来自 `write_draft` 的正文校验结果及上下文投影。** 第一轮 checkpoint `1f1cd067-316f-6816-8003-4b4c7c7318e0` 的 `guard_fallbacks` 为 `guard_repair_failed / unsupported_tool:LangChain`，同时稿件技术栈已经含 LangChain。`fact_guard._skill_supported` 原先未使用技术栈别名表；`_document_outcome` 会把该诊断放入 `write_draft` 工具结果，而 `orchestrator_context._items` 又未保留 `tech_stack` 和项目 `polished_bullets`。这解释了模型可见结果中的矛盾；未重跑真实模型去推测其内部原因。

### 改动

- 技术栈编辑按经历类型、名称子串及正文关键词确定唯一目标；一个项目与一段工作并存时，「那个项目」「简历 agent 那个项目」可直接定位项目；多项目仍有歧义即 insufficient。
- 同一句增删作为一个事务执行，支持先加后删及先删后加。`record_facts` 只追加新增技术的原文事实，删除只记录呈现排除项；不删除包含其他技术或动作的复合事实。模糊技术栈指令不再落入通用提取；普通新经历叙述仍可进入正常事实录入。
- 局部增删保持其他技术的次序、正文、引用和历史版本；不再调用整项投影重算。超过 8 项返回 insufficient，防止静默截断。未知删除不清空整行，删除「长期记忆」不误删另一个独立的「记忆」。`edit_resume` 的失败出口丢弃更新，阻止失败结果携带稿件/元数据/事实写回。
- `normalize_prose` 仅用 `ALIASES` 和词边界确定性替换。写稿投影只删除已被技术栈完整覆盖的纯罗列子句，保留「通过 MCP 接入 Claude」等具体动作；整条只剩清单则删除该条。局部 bullet 重写只处理目标要点，技术栈增删保持既有要点逐字不变。
- 清理时同步 bullet 引用、text_hash、coverage_fact_ids 和描述；覆盖检查支持同一复合事实由技术栈清单和带有效引用的正文动作共同覆盖，不能仅靠技术栈代替动作。重复投影结果幂等。
- 正文工具来源校验复用同一别名表，保留否定、计划及名称边界检查。工具结果新增基于实际稿件的 `tech_stack_receipt`，明确说明「已按规范名 … LangChain … 写入技术栈」；压缩上下文保留技术栈和项目要点。写稿和编排提示同步说明独立技术栈行、要点写具体用法及实际结果优先。
- 第二轮真实虚构人物状态导出为 `tests/fixtures/batch18b_tech_edit.json`，测试无需原数据库、凭据或真实模型。`evaluation/batch18b-live/` 仅只读使用并加入 `.gitignore`，不作为提交内容。

### 测试数量与结果

- 新增 **24 项**离线回归，覆盖真实状态 record→edit→保存回读→撤销、反复 insufficient 的逐字保留、原子增删、歧义与指代、8 项上限、失败出口、旧图路径、纯罗列与动作边界、正文别名、引用/hash/覆盖、幂等、指定 bullet 范围以及工具结果真实性。
- batch18b 定向测试：**62 项通过，0 跳过**；日志 `/private/tmp/huhua-b18b-fix-focused.log`。
- 指定全量命令：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py`。
- 最终结果：**Ran 2291 tests in 365.965s — OK (skipped=2)**，即 **2289 通过、2 项既有私人基准材料跳过、0 失败/错误**。相对本轮基线 2267 项新增 24 项。最终日志 `/private/tmp/huhua-b18b-fix-final.log`。
- 改动的 **10 个 Python 文件 Ruff 通过**，`git diff --check` 通过；原 `tests/test_batch18b.py` 无差异。测试脚本隔离数据库并清空模型/检索凭据，所有模型行为均为桩。
- 本例离线验证最终技术栈为 `['MCP', 'Tool Calling', 'LangChain', 'FastAPI']`，原三条要点逐字保留。未改写原始回放数据库，未做真实模型或线上验证。
