# 2026-10-11 最新回放剩余四项修复

分支 `overhaul/tailor`，原 HEAD `eca590d` 保持不变。保留此前提交及既有回放目录；没有读取或打印凭证、真实模型调用、commit/push/部署。所有新夹具均为虚构资料和 fake writer/model，PDF 使用生产渲染器。

## 根因与修改

1. **本人动作被压缩删除**：原保留校验只做整句反向蕴含，没有独立检查本人动作引用和主体，且容量目标遗漏 `open_source`。在 `_retain_compressed_body` 中要求压缩后每条句子引用同条目 active 的本人 `action/method_tool/deliverable` 事实；保守过滤明确第三方主体及其逗号接续，只有维护者动作、仅结果或第三方引用时拒绝，原文和 metadata 保留，记录 `personal_action_missing`。继续复用原语义保留核验并明确其压缩合同，两种 writer 模式同步合同。开源贡献接入原压缩目标路径。
2. **只差几行仍推整栏**：六模板没有 section 级 `break-inside: avoid`；实际约束是 PDF 全局 `p` 的 `orphans/widows: 2` 与标题的 `break-after: avoid` 叠加，紧凑荣誉段落不能只留首行。共用 CSS 显式允许栏目/条目拆分，标题跟随首行，荣誉段落设 `orphans/widows: 1`；仅收紧六模板栏目 margin（2–4px），保留字体、配色、灰条、padding 和装饰。小幅溢出给出两条最长句候选，保持最多两轮、每轮最多一次 writer；首个候选拒绝后可以尝试下一条，确认经历不能隐藏。
3. **重点理由变成套话**：`plan_summary` 在无法安全截短 reason 时补入“按已确认方案重点展示”。现在读取该经历的 reason，去重复经历名前缀，取第一个完整短语且不超过 20 字；缺失或没有可安全保留的短语时只列经历名，保持整段 150 字预算及成对标记完整。
4. **空定位一路写成空 summary**：原 validate 兜底仅接受 thesis 子句与事实全文逐字匹配，且只处理推荐方案。现在推荐与备选的空定位都先用有本人事实支持的 thesis 子句，否则按 lead 顺序用 active 本人动作原词生成定位；可加已有教育字段和明确求职目标，不新增数字、工具、成果、职责或在读状态。只在有事实支持时生成，记录 `positioning_source=derived` 与具体来源；确认后写稿重新从事实计算并对照，保留定位及其来源，不因缺少模型判定而消失。模型返回的越界非空定位仍拒绝。

## 回归与验证

- 新增 `tests/test_replay_remaining_regressions.py` 的 **13 项回归**：三类经历 × shorten/merge 的本人主体规则、action/method/deliverable 正例、结果/第三方引用拒绝、开源拒绝诊断、两种 writer 合同、成稿理由、三次空定位出卡及确认后 summary/来源、缺事实与过期事实边界、六模板分页规则、实际 PDF 分栏和压缩循环。
- 两个虚构边界简历均实际测得 **2 页、溢出 3 行**。紧样例缩短两条最长 bullet 后为 **1 页**；另一个首条被拒绝保留原文，再缩第二长句后为 **1 页**。用 `count_resume_pdf_pages` 复核；确认项目、开源贡献、荣誉和活动均保留，事实母版与输入 state 未变。
- 实际 PDF 另验证荣誉标题与首行在第 1 页、后续内容可跨到第 2 页，全部荣誉文本保留。
- 调整 4 个旧测试文件：原来关于空定位及套话理由的断言更新到新合同；缺类型的容量夹具显式标记为 action；技能合行边界夹具由 29 行调为 30 行以适配收紧后的真实布局。未放宽事实 guard 或语义失败的既有回归。
- 定向新回归 **13/13**；指定全量命令 **1257/1257，27.087 秒**：

  ```sh
  DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py
  ```

- 修改 Python 文件的 Ruff（忽略仓库既有导入布局 E402）通过；`git diff --check` 通过。

## 改动文件

业务：

- `backend/app/agents/resume_writer.py`
- `backend/app/agents/tailor_pipeline.py`
- `backend/app/services/fact_guard.py`
- `backend/app/services/resume_capacity.py`
- `backend/app/services/resume_facts.py`
- `backend/app/services/resume_pdf.py`
- `backend/app/services/structure_plan.py`

模板：

- `data/jianlimoban/html-template/_macros.html.j2`
- `data/jianlimoban/html-template/t001-jianyue.html.j2`
- `data/jianlimoban/html-template/t002-jianyue.html.j2`
- `data/jianlimoban/html-template/t004-jianyue.html.j2`
- `data/jianlimoban/html-template/t1000.html.j2`
- `data/jianlimoban/html-template/t1001.html.j2`
- `data/jianlimoban/html-template/t1002-jianyue.html.j2`

测试：

- `tests/test_replay_remaining_regressions.py`（新增）
- `tests/test_replay_polish_regressions.py`
- `tests/test_replay_layout_regressions.py`
- `tests/test_structure_plan.py`
- `tests/test_tailor_pipeline.py`

交接：本文件与 `mmr.md`。
