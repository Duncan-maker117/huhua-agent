# 回放剩余四项小修（本地）

分支 `overhaul/tailor`，HEAD `b8d92fd` 保留。既有提交及回放产物未回退或改写；未 commit/push/部署，未读取/打印凭证，真实模型调用 0。

## 1. 两行溢出

根因：技能分组各占一行，容量检查只返回页数且优先隐藏 brief，回复把新增一张 PDF 页误当成溢出一整页。

- 共用 `display_skill_rows`：至少三个非空分组时，相邻短组（1–2项、显示宽度受限）两两合行，以分号分隔，保留原名称、顺序和编辑路径；长组、只有两组时保持独立。六款模板的共用宏和 Word 使用同一逻辑，事实及结构化技能不变。
- 生产 PDF 的最终布局直接提取文字 LineBox，记录 CSS px 高度、实际文字行数及页面占比；不写 PDF 字体即可测量。传入已渲染 PDF 时使用文字几何位置测量。
- 单个超出页的内容高度小于正文页面15%时，压缩计划不隐藏经历，先合并/缩短已核验 bullet；保留现有两轮上限、语义保留检查和局部编辑范围约束。技能在第一次测量前就按紧凑规则渲染。
- 回复优先“超出约 2 行”，只有高度时给页面占比，只有页数时给“内容延伸到第 2 页”；轻微溢出不建议移除经历。
- 实际虚构 t001 样例：旧布局第2页仅含工具/其他两行，溢出50.60px、约4.83%；紧凑布局1页，全部29条虚构正文保留。PDF文字提取确认尾页没有经历正文。

文件：

- `backend/app/services/skill_groups.py`
- `backend/app/services/renderer.py`
- `data/jianlimoban/html-template/_macros.html.j2`
- `backend/app/tools/resume_data_docx.py`
- `backend/app/services/resume_pdf.py`
- `backend/app/services/resume_capacity.py`
- `backend/app/agents/tailor_pipeline.py`
- `backend/app/agents/resume_graph.py`
- `tests/test_resume_capacity.py`（渲染失败的替身改挂新的布局入口）
- `tests/test_replay_guest_fidelity_regressions.py`（只有页数时的回执断言改为页码延伸）

## 2. 思路拼接和截断

根因：thesis、理由和最终输出都按字符硬切，随后用空格拼接，造成半句、半词及未闭合的括号/引号。

固定为完整一句，换行 `重点：A（理由）、B（理由）`；保留最多三条重点，每项理由≤20字，含标题总长≤150字。截断只在成对标记之外的句号、逗号等标点处发生；无法安全缩短时使用确认方案的通用说明，不输出残缺词。不再用最终字符切片兜底。

文件：`backend/app/services/structure_plan.py`。

## 3. 收集回复暴露内部保存状态

根因：COLLECTING_WRAP 把“正在同步草稿；保存尚未完成”混在面向用户的确认指令中。

面向用户示例改为“已记下，右侧草稿会同步更新”；明确把不得提前声称保存完成的约束标为不可复述的内部规则。fake 收集轮验证实际使用该提示词并返回自然确认，没有已保存承诺。

文件：`backend/app/agents/resume_graph.py`。

## 4. positioning 空值

根因：合同未明确要求模型必须给定位句，空默认值掩盖省略，同时定位复用正文的全部语义维度，可能因概括动作/对象词被误拒绝，且没有事实支持的 thesis 兜底。

- 合同和字段描述明确必填；缺乏事实时允许空，禁止硬造，保留旧结构解析兼容。
- 允许概括性的动作/对象表达；数字、单位、具体工具仍做确定性核验，成果、主体、状态限制仍须语义支持。模型不可用、结果缺失、新成果均拒绝。
- recommended 为空时，只采用 thesis 的完整短语中与 active 原始事实完整匹配、≤40字的内容；不凭相似度推断。找不到就空。
- 诊断记录 `positioning_model_output`（missing/empty/provided）、`positioning_rejected_reason`、`positioning_source`、`positioning_fallback_reason` 和 `positioning_semantic_relaxed`，不记录原始个人文本。
- 旧 fake 的 `fail_ids` 现在明确包含成果不获支持，用来保留真正拒绝场景；新的 `abstract_fail_ids` 专门覆盖仅概括动作维度误拒绝。没有删除原来失败、缺失或模型异常的拒绝测试。
- 两份已有公开 handson 回放 turns.json 未包含定位拒绝诊断；未由历史空值猜测具体是哪次模型省略。本轮验证针对上述代码分支。

文件：

- `backend/app/agents/resume_writer.py`
- `backend/app/schemas/writer.py`
- `backend/app/services/fact_guard.py`
- `backend/app/services/structure_plan.py`
- `tests/test_replay_plan_intake_regressions.py`

## 验证和交接

新增 `tests/test_replay_polish_regressions.py` 的16项虚构/fake-model回归，涵盖实际PDF、六模板/Word一致性和编辑路径、轻微超页压缩、自然收集确认、摘要断句、定位缺失/空值、概括性误拒绝与新数字/工具/成果拒绝。

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py
```

最终 **1244/1244，22.870s，OK**；相关回归 **90/90，1.605s**；改动 Python 文件 Ruff（仅忽略既有 E402）和 `git diff --check` 通过。全量入口隔离数据库且清空外部凭证，不访问真实用户存储或模型。首轮失败是旧回执/核验断言和短组贪心分配造成最后一组独占行；已按新行为修复并全量重跑。

日志：`/private/tmp/huhua-replay-polish-final.log`、`/private/tmp/huhua-replay-polish-focused-final.log`。交接更新：`mmr.md`。本轮只做本地验收，未进行真实模型回放。
