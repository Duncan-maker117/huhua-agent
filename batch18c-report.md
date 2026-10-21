# 第十八批 c：按需流程 skill

## 范围与状态

在 `batch18b` / `1c5855e` 上继续；未切分支、commit、push、部署或调用真实模型。开场已有的 5 个 `skills/flows/*.md`、`skills/resume-write/SKILL.md` 修改和 3 个未跟踪 prompt 文件均保留，skill 内容没有改动。开场 `mmr.md` 的旧 HEAD 记录已过时，以实际 git 核验为准。

## 改动文件

| 文件 | 改动 |
| --- | --- |
| `backend/app/agents/flow_skills.py` | 启动时解析本地 YAML frontmatter；检查必填字段、类型、名称、重复和空目录/正文；目录按 name 排序；从同一目录生成 Literal 参数枚举 |
| `backend/app/agents/orchestrator.py` | 追加自动生成目录与使用说明；开启同消息多 tool_calls；优先加载 skill；免业务工具预算；进度文案；metrics.skills |
| `backend/app/agents/orchestrator_tools.py` | 注册 use_skill、每轮 loaded_skills 去重；可信正文不经资料字段清理；两种 edit_resume hint；技术栈正文同步回执 |
| `backend/app/agents/orchestrator_context.py` | 优先保留 hint 和 tech_stack_body_receipt，避免被大段诊断挤掉 |
| `backend/app/services/tech_stack.py` | 保守删除技术列表成员、同步 bullet 引用/hash、保留无法安全删除的原句并说明；支持已删除技术的重试识别 |
| `requirements.txt` | 显式声明 PyYAML，避免仅依赖间接安装 |
| `tests/test_batch18c.py` | 24 项新回归：目录、工具、HTTP 协议、预算、metrics、hint、正文同步与真实写稿提示路径 |
| `tests/test_batch18b_fixes.py` | 调整本批已改变的“技术删除但正文完全不变”断言；仍检查其他正文、事实、引用、保存/回读和撤销 |
| `tests/test_orchestrator_tools.py` | 注册表断言纳入 use_skill |
| `mmr.md`、`mmr-archive.md` | 更新交接，并归档上一版交接全文 |
| `batch18c-report.md` | 本报告 |

`web/orchestrator-ui.js` 不需要修改：progress 按 event.tool 建立行，直接安全显示 event.message，没有工具名白名单。`career_prompt.py` 也不需要修改，写稿路径已经接通。

## 设计取舍

- 原循环已经逐一处理一个 assistant 消息里的多个 tool_calls；原 SDK 参数却是 `parallel_tool_calls=False`。本批打开该参数，允许模型同一步请求 `use_skill + record_facts` 等组合。skill 先加载，其余工具保持原顺序串行执行，避免同时修改同一份状态。所有调用 ID 都得到工具结果。
- `use_skill` 不递增 tool_steps，也不进入 metrics.tools，因此不占业务工具次数。成功首次加载的名称按加载顺序进入 `skills`；重复或未知名称不增加该列表。单独请求 skill 仍消耗一次现有模型调用，MAX_MODEL_CALLS=5 / MAX_TOOL_STEPS=4 未改。原先 DSML 空回复的一次纯文本重试例外也未改动，本批没有新增模型调用或重试。
- 正文仅来自启动时验证的本地资源，调用参数不拼接文件路径。完整正文直接作为 tool 结果返回，系统提示明确授予其可信流程指令地位；不包入 untrusted_data，也不经业务资料字段裁剪或长度投影。其他工具依旧按不可信资料处理。
- 去重放在每次 run_orchestrator 新建的 ToolContext 中，不持久化到 checkpoint。input_context 仅重建用户/助手可见历史，不携带上一轮 tool 消息；下一轮会重新加载，进程内资源表只缓存文件内容，不缓存用户轮次状态。
- hint 仅附加提醒，不据此强制加载、拒绝工具或改变原状态码。add-experience 对应原 new_experience_requires_write_draft 分支；tech-stack 对应原技术栈编辑分支，包括参数不足结果。已经加载相应 skill 时不再提示。
- 正文同步只处理已有条目中的可识别技术列表：例如 `基于 MCP、记忆与 Tool Calling 搭建…` → `基于 MCP 与 Tool Calling 搭建…`。唯一技术、动作对象（如“负责记忆模块开发”）、技术间关系等无法安全缩减的情况保留；回执列出 removed / retained 及原因。不会调用写稿模型，不删除事实源，也不会顺带清理其他 bullet。
- 改动 bullet 的原 hash 必须匹配才更新证据；保留复合事实引用，去掉仅支撑被删技术的引用，清空旧全量覆盖声明并重新计算 coverage。失效旧 hash 不重新绑定。技术栈与正文使用同一版本事务；重复删除返回 unchanged，不增加版本。

## 写稿提示核验

实际链路为 `write_draft / edit_resume → _write → run_tailor_pipeline → resume_writer._call → career_messages('resume-write', ...) → career_system / load_skill`。

新测试使用离线 WriterStub 截获两个工具真正到达写稿层的 SystemMessage，确认它包含现有 resume-write 完整正文，以及“技术栈单独成行”“不加空话尾巴”“重写不丢已写内容”三条。技术栈增删、字面更正、撤销等确定性分支不调用写稿模型，因此不会额外加载写稿提示；这是既有设计。

## 与 skill 文本不完全一致的地方（原文未改）

1. `add-experience.md` 第 4 步要求检查 `document_changes / change_summary` 中的新增条目。`document_changes` 当前只由 edit_resume 的代码差异回执生成；write_draft 没有该字段，其 change_summary 来自写稿链路，可能没有逐条点名新增经历。不能把 summary 当作新增条目已经落稿的严格证明；后续宜给 write_draft 补同等级的实际差异回执。
2. `targeted-edit.md` 第 1 步将数字、日期、条数、角色更正都概括为 record_facts 同步改事实与正文。实际 `correction_applied` 快捷路径只覆盖 `correction_pairs` 识别的带单位数字及成对引号替换等语法；普通日期、角色口述不保证命中，可能只是完成事实抽取。流程应以实际 correction_applied 回执为准。
3. `tech-stack.md` 要求删技术时要点中不再提它；本批按明确要求保留“唯一技术/无法安全删减”的句子，并返回 tech_stack_body_receipt。这比 skill 文本更保守，不保证任何上下文中的字面词都消失。
4. `resume-write/SKILL.md` 要求 tech_stack 中没有的技术不出现在 bullet。代码的技术栈有 8 项上限及显式排除名单，并允许保留不能安全删减的动作句；因此这条是写稿指令，不是全部确定性编辑路径的硬约束。

其余核对：5 个流程提到的工具名均已注册；source_id、direction、emphasis、instruction 字段及 new_experience_requires_write_draft、correction_applied 均存在。read_jd 的招聘链接路径、search_company 每轮一次、check_layout 返回 page_check.pages 也与流程相符。

## 建议下批移出系统提示的原句

本批没有删改任何原 SYSTEM_PROMPT 句子。下列是可由对应 skill 承担的单场景内容；移出前需确保该流程被加载：

- → add-experience：`新增经历先 record_facts 再 write_draft；edit_resume 返回 new_experience_requires_write_draft 时按 next_tool 继续，不能声称新增已完成。`
- → tech-stack：`tech_stack_receipt 是当前稿件技术栈的实际结果；别名按规范名写入后，不得说成该技术被拒绝或未写入。guard_fallbacks 只说明候选要点的校验情况，不代表整份稿件或技术栈缺少该技术。`
- → targeted-edit：`已有稿局部修改用 edit_resume；数字或条数更正先 record_facts，工具会按用户原话同时核对并更新事实与正文，correction_applied 时不要再重写；更正失败如实说明，不能用普通润色绕过。`
- → one-page：`排版检查用 check_layout。`

以下继续留在系统提示更合适：真实事实边界、资料不可信边界、所有场景的实际回执/changed=false/uncovered_facts 解释、工具预算、联系方式与问题卡约束。JD source_id 的说明也同时约束事实采集，不建议整句移出。

## 验证

- 新增专项：24/24 通过；HTTP 全部使用 httpx.MockTransport，写稿与抽取使用离线桩。
- 全量：2331 项，2329 通过、2 项既有私人材料跳过、0 失败；耗时 116.141 秒。基线 2307 项，本批净增 24 项。
- Ruff：通过（本机 `/opt/homebrew/bin/ruff`；指定虚拟环境没有 ruff 模块）。
- `git diff --check`：通过。
- 6 个 skill 文件 SHA-256 与开场记录一致；用 AST 对比 HEAD 确认原 SYSTEM_PROMPT 字符串逐字未改。
- 运行命令：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py`。
- 日志：`/private/tmp/huhua-b18c-targeted.log`、`/private/tmp/huhua-b18c-full.log`。测试运行器隔离数据库并清空真实提供方 key，未运行线上或真实模型回放。

真实模型是否更稳定选择流程尚未验证；本批证据是离线协议、状态和写稿提示回归。
