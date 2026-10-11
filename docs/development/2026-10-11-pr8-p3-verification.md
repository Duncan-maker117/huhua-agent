# PR8 P3 定方案：本地验收

2026-10-11，分支 `overhaul/tailor`。仅实施 P3，保留已提交 P1/P2；没有 commit、push 或部署。没有读取私有 benchmark 材料、改动已有 runs，真实模型调用为 0。

首稿先输出推荐方案及 1–2 个备选，方案本身没有简历版本、写稿或 PDF 页数测量。推荐/备选按钮与自然语言确认使用确定性解析，确认后仅调用 WriterDraft。方案保存在 checkpoint，confirmed_plan 同时写入 resume_meta，沿用现有加密会话持久化，无数据库迁移。

定位句在现有 self_evaluation（summary）区域展示，最长 30 字；定位句和主线复用 fact guard 的词面、工具及数量检查，不额外发语义核验请求。无依据的句子删除；无效/不存在的 item、fact 引用过滤。空泛理由回退为具体条目的事实与 JD 关系。结构命令不改事实母版，省略经历使用备用取舍；备选只展示相对推荐的经历差异。

已有可见草稿且无 confirmed_plan 的旧会话保留原编辑流程。新会话在收集阶段已有事实预览也要确认方案；新 JD 或重新定方案清空确认状态。后续明确结构编辑同步方案和当前稿；主线变化重跑 plan。页数压缩可以调整正文，但不自动把用户确认要写的经历移为备用；仍超页时按原回执提示用户决定。

| 文件 | 修改 |
|---|---|
| `backend/app/schemas/writer.py` | 在 MatchPlan 上增加推荐方案与仅含差异的备选方案契约。 |
| `backend/app/config.py` | 增加默认 true 的 LLM_PLAN_CONFIRM 开关。 |
| `backend/app/agents/resume_writer.py` | 复用 plan/write 阶段，单独返回方案、按完整确认主线写稿，并在失败时保留已确认取舍。 |
| `backend/app/services/structure_plan.py` | 集中验证方案、合并备选、解析确认与结构修改、生成 guidance 和思路摘要。 |
| `backend/app/services/fact_guard.py` | 增加仅运行现有词面检查的选项，默认正文核验行为保持。 |
| `backend/app/agents/resume_graph.py` | 接入首稿确认、直接写、重新定方案、新 JD 失效、后续结构同步和方案节点公开流。 |
| `backend/app/agents/tailor_pipeline.py` | 强制复用确认方案、持久化方案，并阻止容量压缩静默隐藏经历。 |
| `backend/app/agents/interviewer.py` | 从确认方案的主线和 lead 理由生成“这版的思路”，移除截断原文模板。 |
| `backend/app/services/resume_workspace.py` | 将方案作为结构化 guidance 投影到 SSE/刷新/历史工作区，并优先显示方案。 |
| `web/resume-workspace.js` | 沿用现有样式显示推荐、定位、主线、栏目、取舍理由和可展开备选差异，按钮发送确定性文本。 |
| `evaluation/tailor-bench/run_bench.py` | 自动插入可计时的 auto_confirm 轮、避免把方案当版本、保存方案上下文及 LLM_PLAN_CONFIRM。 |
| `scripts/run_tests.py` | 旧“一轮出稿”夹具使用关闭开关的兼容路径；P3 夹具显式开启确认。 |
| `tests/test_structure_plan.py` | 新增 28 项离线回归，覆盖全流程、guard、失败、旧会话、SSE、DOM 和完整 fake benchmark 回放。 |
| `tests/structure_plan.dom.js` | 验证真实前端渲染函数的卡片字段、备选展开与按钮发送/防连点行为。 |
| `tests/test_p1_fixes.py` | 将思路句断言更新为确认方案的具体理由，保留原证据边界回归。 |
| `tests/test_tailor_interviewer.py` | 给原追问排序夹具补充确认主线，继续验证原排序和定位。 |
| `tests/test_tailor_pr5_gate.py` | 给原思路解释频次夹具补充确认方案，保留迁移表述和不重复解释的验收。 |
| `docs/development/2026-10-11-pr8-mainline-flow.md` | 在 §9 追加 P3 本地实施记录，保留 P2 原记录。 |
| `mmr.md` | 更新当前 P3 状态、验收及下一步边界。 |
| 本文档 | 记录实现、验证及尚未验证的质量边界。 |

## 验证

- `.venv/bin/python scripts/run_tests.py`：**1134/1134 通过**，22.165 秒；包含新增 28 项（P3 开启）和全部 1106 项原有回归（原单轮出稿夹具关闭开关）。
- 完整 fake benchmark 回放：opening 返回卡片、0 个版本；auto_confirm 生成 1 个可见版本，单独记录轮次/耗时、首稿轮数及上下文。
- 实际 graph/checkpoint 连续两轮、公开 SSE 收发与保存参数：方案轮不序列化草稿、不产生版本；确认轮公开回复并保存 confirmed_plan。
- Node DOM 夹具：推荐及备选内容渲染、确定性按钮文本、同卡片防连点通过；这是 DOM 级离线验证，未做真实浏览器视觉验收。
- JS 语法、Python 编译、git diff --check 通过。修改的业务代码与新增测试 Ruff 通过（排除既有 E402）；原 test_tailor_pr5_gate.py 中既有 3 条未使用导入/变量告警未扩大处理。

## 调用数和预计耗时

正常首稿写作主链从一次 OnePassOutput 变为一次 StructurePlan + 一次 WriterDraft，即 **1 → 2 次**。确认发生在用户另一个请求中；“直接写”仍是两次模型请求，但没有确认等待。沿用方案的后续写作只跑 WriterDraft；可确定性解析的结构调整为 0 次模型调用，主线调整为 1 次 plan 调用。原有提取、JD 解码、语义 guard、修复重试和必要压缩调用另计，没有把它们计入上述主链数字。

预计首稿总等待为 `T_plan + T_用户确认 + T_write`，相对原 `T_one_pass` 多一轮模型请求及确认等待。用户可在方案轮后阅读/调整，最后成稿请求只承担 write 阶段；直接写为 `T_plan + T_write`。因为本轮禁止真实调用，没有可据此报告的真实秒数或 token 成本；fake 测试时长不能当作模型性能数据。

## 留下的问题

没有运行真实模型的写作质量 benchmark、自然选择类语义评分或真实浏览器视觉验收，不能宣称质量已不退步。词面 guard 能拦明确工具、数字和职责等越界，不能证明任意改写的全部语义；这是本轮明确使用词面检查的边界。需要后续获授权的独立 benchmark 比较真实主线选择、理由具体性和写作质量，保留现有 runs 不覆盖。P4 老用户快速入口未实施。

恢复原单轮出稿流程可设置 `LLM_PLAN_CONFIRM=false`；这不会删除已有资料或简历版本。
