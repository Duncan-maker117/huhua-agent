# 第十八批 c：编排模式的流程 skill（use_skill）

仓库：胡话简历。分支 batch18b（HEAD `1c5855e`），本批直接在其上继续（不要切分支，不要 commit/push/部署，不调用真实模型）。编排模式代码：`backend/app/agents/orchestrator.py`（SYSTEM_PROMPT、run_orchestrator、MAX_MODEL_CALLS=5、MAX_TOOL_STEPS=4）、`orchestrator_tools.py`（`@_register` 工具注册）、`orchestrator_context.py`。

## 背景

编排模型目前只有一段长系统提示，靠它决定每种场景用哪些工具；真实回放里出现过「新增经历调了 edit_resume」「改稿失败还说改好」等选错流程的问题（代码兜底已在 batch18b 修复轮做了）。Claude 已写好 5 个流程 skill：`backend/app/agents/skills/flows/*.md`（add-experience、tech-stack、targeted-edit、jd-tailor、one-page），frontmatter 有 `name`、`title`、`when`。另外 Claude 改了 `skills/resume-write/SKILL.md`（技术栈、不加空话、重写不丢内容三条）。**这些 skill 文件的内容不要改**，如发现与代码实际行为不符（工具名、字段名、返回码），在报告里列出，不要自行改写。

## 要做

1. **skill 目录进系统提示**：启动时读取 `skills/flows/*.md` 的 frontmatter，在 SYSTEM_PROMPT 末尾生成一小段目录（每个 skill 一行：`name：title——when`），加一句：「遇到对应场景，在本轮第一步与第一个工具同时调用 use_skill(name)；已加载过的不必重复。」目录由代码生成，不手抄。
2. **use_skill 工具**：`use_skill(name: Literal[...])`，返回该 skill 正文（去掉 frontmatter）。要求：
   - **不占 MAX_TOOL_STEPS 和工具次数**，允许和其他工具在同一步并行调用（一个 assistant 消息里多个 tool_calls）；确认当前编排循环支持同一步多个 tool_calls，若当前只支持一次一个，按最小改动支持「use_skill + 一个真实工具」同步执行。
   - 不额外增加模型调用；如果模型单独一步只调了 use_skill，允许但计入 MAX_MODEL_CALLS（不加大上限）。
   - 同一轮重复加载同一 skill 直接返回「已加载」短结果。跨轮不缓存（每轮都是新上下文）——如果编排上下文会把上一轮工具结果带进来，就不重复注入正文。
   - 正文属于系统可信内容（不是 untrusted_data）。
   - 进度文案「正在查看做法…」或类似，前端工具进度展示沿用现有机制（看 `web/orchestrator-ui.js` 是否需要映射新工具名）。
   - metrics（`orchestrator_turn` 日志）记录本轮加载的 skill 名列表，便于线上统计命中率。
3. **高风险场景代码提醒（不强制）**：本轮用户消息经 record_facts 产生了稿子里没有的新经历，而模型本轮没加载 add-experience 却要调用 edit_resume 时——现在 edit_resume 已返回 `new_experience_requires_write_draft`，在这个返回里加一句 `hint: "先 use_skill('add-experience')"`。同理 edit_resume 涉及技术栈增删而未加载 tech-stack 时，结果附 hint。只加提示字段，不改变工具判定逻辑。
4. **精简系统提示**：SYSTEM_PROMPT 中已被 skill 覆盖、且只适用于单一场景的流程句可以移到对应 skill 由 use_skill 提供——**但本批不删除任何系统提示原句**（防止回归），只在报告里列出「建议下批移出」的句子清单。
5. **技术栈删除同步正文（代码）**：edit_resume 删除某技术 B 时，同一条目 bullet 中只是列举 B 的部分（如「基于 MCP、记忆与 Tool Calling 搭建…」删去「记忆」→「基于 MCP 与 Tool Calling 搭建…」）确定性去掉；B 是 bullet 唯一技术或去掉后句子不成立时保留原句并在回执里说明。同步引用/hash，幂等。回归用 batch18b 真实场景：tech_stack 去掉「记忆」后 bullet 不再含「记忆」。
6. 写稿提示：`career_prompt.py` 加载的 resume-write 已含新规则，确认 loop 的 write_draft / edit_resume 实际会加载到它（若 loop 路径用的是别的提示，报告说明并接上）。

## 测试
- 目录生成（frontmatter 解析、缺字段的文件被拒并报错、按 name 排序）。
- use_skill：返回正文、未知 name 拒绝、同轮重复、与 record_facts 同步并行时两个结果都回到模型、不占工具步数、不加模型调用（用 HTTP MockTransport 桩，参考 `tests/test_batch18a.py` 历史版本或 `test_orchestrator*.py` 写法）。
- metrics 含 skills 列表；hint 字段在两种场景出现、其他场景不出现。
- 技术栈删除同步正文：正反例、幂等。
- 全量：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py`，基线 2307 全过，改后必须全过；Ruff、`git diff --check` 通过。
- 报告写 `batch18c-report.md`：改动文件、设计取舍、测试数、与 skill 文本不符之处、建议移出系统提示的句子。
