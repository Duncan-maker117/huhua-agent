# 第十七批第 2 期第二轮：P2h

日期：2026-10-19。工作分支 `batch17h`，起点 `31cfd13`。仅修改 loop 编排、工具适配器、上下文及对应测试；旧图节点、writer/fact_guard、岗位手册、评测判定和前端不改。

## 证据与根因

本 worktree 没有被忽略的回放目录；只读核对了 `../huhua-b17b/evaluation/persona-ux/runs/{p2-loop-all-1,p1-loop-all-5}/`，没有修改相邻 worktree。

离线对比见 [p2h-frozen-comparison.md](p2h-frozen-comparison.md)。这是旧产物重评，不是本次修复后的真实回放；两次运行的 fixtures/recovery 设置不同，不能视为严格同脚本实验。原口径合计 147/168 → 143/168；P2 有编排记录的 34 轮平均 21.000s，单次 prompt 中位 3256、最大 5876。用户提供的模型 8.4s / 工具 12.6s 为已有统计，本次不伪造修复后的节省量。

1. **先写后问**：`write_draft` 成功后直接 `stop=True`，系统提示也要求把未完补问留到下轮。即使模型知道应追问，也只能收尾说文字，无法再发卡。
2. **cold**：第 3/4 轮的 `match_plan.bullet_style=plain`、`role_family=data`，没有 labeled 槽位分类；实际拒绝为 `guard_fallbacks.reason=invalid_refs`，`semantic_failed=false`。原事实被拆到一个有名称/日期的校园条目和一个有职责/具体动作的占位条目。结构方案声称事实已并入前者，却只在文案里说合并，实际隐藏了后者。writer 引用了另一条目的事实，核对正确拒绝；本条又没有可写动作，旧回退无法恢复。不能把这次失败归因于 labeled 槽位或模型语义误判。
3. **联系方式**：写稿时已设置 `contacts_requested`，但公开回复完全依赖模型遵守提示。cold 没有实际索要，却在后续轮被视为问过。
4. **tech objective**：初稿已为空，并非只在润色时丢失。会话方向包含岗位名称及很长的括号技能说明，整串超过 `safe_objective` 的长度限制；loop 又只投影手机/邮箱，没有恢复有效岗位名称。
5. **returning 回执**：本轮第 1 轮已说“直接采用了两段”并点名，第 2 轮说“导入的：从档案选了两段”并点名，后者同轮可见数据也有两段。当前检查器的完成态正则不覆盖这些表达，第 1 轮还没有稿件数据，因此旧产物仍失败。遵守第十六批规则：模型已逐一点名就不重复；不为匹配正则强加第二份回执，也不越界修改评测。
6. **耗时**：此前只有编排调用耗时，没有每个工具的耗时；强制纯文字收尾仍默认 thinking。

## 实现

### 编排及工具闭环

- `orchestrator_tools.py`：成功写稿后调用既有 `interviewer.question_candidates`，选第一个可展示候选，转换成一个开放式问题卡并通过 `validate_card`。不调用额外问题模型；关闭维度、停止追问、已有问题卡仍受原规则约束。长题干使用卡片 placeholder，稳定维度/问题 ID 保留。
- 结果带 `followup`。`orchestrator.py` 在剩余工具及模型预算内只允许再执行一次 `ask_user`，随后收尾；写稿后的其它工具请求被拒绝。候选问题不会出现在写稿前。
- 模型/工具预算不足时由写稿工具调用同一个 `ask_user` 适配器附卡，返回 `followup_attached`。模型直接收尾、问卡参数非法、请求了其它工具或收尾失败时，编排仍用该适配器确定性附卡。卡片同时进入 guidance 事件和最终 AIMessage，下一轮答案/不知道/跳过能沿原路径关闭维度。
- `orchestrator_context.py` 优先保留 followup；工具结果清理仅放行问题卡里的选择 ID，不放行事实/槽位 ID，防止压缩后卡片无法提交。

### 写稿与头部

- 只在 `record_facts` 入口修复校园身份拆分：占位条目的角色明确写出唯一同名组织、两条有同轮来源、占位条目的 active facts 全属该轮且日期不冲突，才复用 `apply_experience_merges` 合并。事实 ID、来源、否定限制及 `merged_from` 审计保留；多个候选、跨轮混入、不同日期、已经有独立名称均不猜测合并。不由 writer 合并事实，也不允许跨条目引用。
- loop 写稿后增加最后的空正文恢复：从本条 active facts 调用 c6 的 `fallback_row` 规范化，生成带原 fact_ids、coverage_fact_ids、hash 的正文；不使用失败模型文本，不再次请求语义模型。校园和非 labeled 岗位使用 plain；结构化项目仍使用既有槽位写法。岗位类型与校园类型的回归均验证未调用 FactSlots。
- 兜底只恢复当前写作范围内可用事实；尊重 backup、零行、隐藏条目、已删除事实和局部修改范围。纯约束、日期/名称等不能凭空变成经历动作；单句编辑仍保留旧 writer 的编辑边界。恢复后复用限制保留、覆盖统计、版本快照、页数测量，清掉该条过期的交付失败提示，并记录 `deterministic_body_fallbacks`。不会为了单页截断事实；恢复后超页会如实报告。
- `_project_identity` 在写入前后投影会话岗位，保留已明确手改的不同头部；长方向仅提取括号前可通过原 `safe_objective` 的岗位名称。手机/邮箱仍由代码投影，不进入 LLM 输入。修改后重新测量并按原状态建立单次版本事务。

### 确定性收尾及耗时

- 记录本轮成功写稿返回的 `contacts_missing`；收尾扫描已实际索要的字段，仅补问遗漏项。模型完全漏问或失败仍补齐，后续轮依旧由 `contacts_requested` 抑制重复；已有联系方式不再索要。
- 收集成功 `use_profile_items.imported`，若最终文字没有逐一点名，追加“已从档案导入：…”；全部点名则不追加，与原 `public_reply.py` 去重规则一致。公开流和 checkpoint 保存同一回执，回执也经过联系方式脱敏。
- `orchestrator_turn.tools[]` 每次记录 `name / seconds / status`，错误附固定 `code`；确定性问卡另标 `automatic=true`。不记录参数、正文、事实或异常正文。工具耗时扣除其中嵌套自动附卡的耗时，避免累加重复。`tool_steps` 仍指最多 4 次模型工具执行；自动附卡属于出稿的确定性收尾，不额外占用模型决策预算。
- `AGENT_FINAL_MODE` 及 `run_orchestrator` 默认改为 `off`；显式配置 `thinking` 可恢复。只有已经禁止工具的纯文字收尾关思考；正常决策及直接返回文字的 auto 决策仍 thinking，协议错误的一次降级规则保留。
- 风险：关思考后，复杂取舍说明、部分成功/失败边界的自然语言表达可能变差。联系方式、导入回执、问卡有代码兜底，其它文字质量仍需真实回放验证；没有宣称已降低某个秒数或保持真实通过率。

## 测试与文件

- 生产文件：`backend/app/agents/{orchestrator,orchestrator_tools,orchestrator_context}.py`。
- 新增 `tests/test_orchestrator_p2h.py`，16 项离线回归及多组子场景：先写后卡、一次追问、关闭维度、模型/工具预算耗尽、非法卡/错误工具/收尾失败、无稿/无候选/停止追问、压缩不丢卡片 ID、缺联系方式一次补问和跨轮不重问、导入回执去重、日志无正文；校园拆分的保守合并和反例、真实 writer/guard plain 链、c6 空正文兜底、引用/版本/页数、backup/隐藏/删除/作用域保护、长方向初稿及润色投影、联系方式不进请求。
- 既有 `test_orchestrator_writing.py` 的两类 AI 产品 labeled 回归、用户选 plain、数字修正等断言原样保留。
- 交付文档：本说明、冻结对比表、根目录 `mmr.md` 末尾追加交接。

旧测试调整仅有以下需求变化，没有放宽质量断言：

1. `evaluation/agent-loop-spike/test_p2e_context.py` 的设置默认值从 thinking 改为 off，锁定本轮要求。
2. 同文件强制收尾请求的模式期望从 thinking 改为 off；auto 决策仍 thinking 的断言不动。
3. `tests/test_orchestrator.py` 的 SDK 思考片段/回传测试显式传 `final_mode="thinking"`，保留全部原始 reasoning、tool ID 配对和流式正文断言。默认 off 的 SDK 配对及移除 reasoning 由原 P2e 回归覆盖。

## 验证

最终指定全量：**2149 项，2147 通过、2 项原有跳过，0 失败/错误，85.884s，退出码 0**。新增 16 项包含在全量中。日志：`evaluation/agent-loop-spike/p2h-full-tests.log`。

编排定向 113 项通过；全量入口不发现 evaluation 目录的 P2e 用例，额外运行 **15 项全过，0.458s，退出码 0**，日志 `p2h-context-tests.log`。6 份 Python 文件 AST、Ruff 和 `git diff --check` 均通过。测试日志按仓库规则忽略；测试不写死 `/private/tmp`。

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

## 失败做法、未完成与建议

- 没有沿用“把 cold 归因于 labeled”这一初始假设；冻结诊断显示的是 plain + 跨条目引用拒绝，故没有放松 fact_guard 或修改全局槽位分类。
- 首次定向测试暴露旧 SDK 用例隐式依赖 thinking 默认值，已改为显式选择模式，断言未删。新增测试曾把“没有 match_plan”误当“没有候选”，实际岗位手册仍会提供候选；已用没有可见经历构造无候选分支，关闭维度的测试则严格检查不重问该维度，不禁止其它合法维度。
- 首次全量通过后复查 tech 的真实方向字段，补上括号技能说明导致岗位投影为空的回归，再运行最终全量。Ruff 不在该 Python 环境中，使用现有 `/opt/homebrew/bin/ruff` 校验，没有安装依赖。
- 未执行新的真实模型回放，因此真实先写后问质量、延迟与 returning 严格检查是否通过仍未验证。returning 旧产物的表达兼容问题已定位，评测修改留给对应任务，冻结失败项保留。
- 建议先根据新增工具耗时分辨 planner、writer/guard 等耗时；再独立评估是否能复用同版本诊断、减少无变化的测量或重复上下文。这些仅为建议，未实施。`record_facts` 后是否写稿仍由模型决策，没有加入自动直跳或硬编码条件。
- 没有启动应用服务、访问 8833/8834、调用真实模型、改 dist、commit、push 或部署；没有留下付费任务或应用后台进程。
