# 游客回放 A–G 修复

工作分支 `overhaul/tailor`，保留 HEAD `f50fc7e` 及此前提交；本轮没有 commit、push、部署、真实模型调用或读取/打印凭证。仅用虚构资料、fake 模型和隔离测试库验证。

## 根因与修复

| 项 | 根因（一句话） | 修复与主要文件 |
| --- | --- | --- |
| A | ContactRedactor 只是调用内脱敏，抽取契约却只列 links/availability，缺少联系人字面补救，且 basic_info 的整字典 update 会让空 links 覆盖历史。 | `candidate_sections.py` 加显式姓名/电话/邮箱/城市/意向解析；`fact_extractor.py` 补契约并采用非空稀疏合并、链接去重并集；`resume_writer.py` 将真实联系人覆盖到空页头。 |
| B | 现有字面教育解析器能拆“专业名+学历”，但模型漏 major 时，部分生成/恢复入口没有教育补救。 | `fact_extractor.py` 在共用抽取入口补学校、专业、学历、日期、奖学金 field facts，并匹配已有教育条目；不把学校修改命令当新事实。 |
| C | trim_name_punctuation 把所有 Unicode 标点都逐字符剥离，误删右括号；技能后缀清理又先于句末标点清理。 | `resume_field_hygiene.py` 按成对关系保留括号/引号，仅清理句末标点和不配对括号；`skill_groups.py` 先清标点再拆分、剥离“辅助开发”等后缀；`resume_facts.py` 清理技能项名称并保留原始来源。 |
| D | 保存时事实清洗发生在容量循环之后，又把重新实测的 within_page_limit 置为 None，导致超页结论和进一步压缩失效。 | `tailor_pipeline.py` 在每次容量判断前清洗正文；`resume_capacity.py` 保留实测布尔值并独立记录清洗状态；确认方案规划压缩时不先模拟 hide_item，允许 merge/shorten，保护已确认定位；`resume_graph.py` 报告多出的页数及可见 brief/backup 候选，由用户决定删减。 |
| E | 定位虽然绕过部分词面约束，但语义核验仍按逐条正文成果判断概括性求职定位，且 validate_structure_plan 丢弃定位时没有诊断。 | `structure_plan.py` 与 `fact_guard.py` 标记 claim_kind=positioning 并明确概括规则；仍核验具体事实、数字、任职经历及职责程度；`resume_writer.py` 保存定位拒绝原因、失败维度与固定错误码；已确认定位继续走现有个人定位/summary 模板。 |
| F | lenient schema 只忽略额外字段，仍硬拒绝 alternatives 超长、数值越界和可归一化的 Literal，且 plan 的异常分支没保留完整安全诊断。 | `schemas/writer.py` 在 lenient 模式截断 list、夹取 ge/le、归一化合法枚举的空白/大小写，严格模式不变；未知枚举继续失败；`resume_writer.py` 记录 schema_repairs、validation_errors、schema_failure_reason_code。 |
| G | 原短答绑定把整条多答案消息挂到首先点名的项目，还会用唯一项目兜底，未区分对应追问；状态词 role 的清理没有覆盖所有 canonical/编辑入档入口。 | `turn_actions.py` 按句确定显式项目或上一轮分工追问的唯一对象，迁移误挂事实/原话，歧义暂存 pending_ownership 并支持随后确认；`resume_graph.py` 防止兜底再猜归属并追问一句；`resume_facts.py`、`resume_writer.py`、`profile_bridge.py` 在事实入档、序列化和保存时清除状态 role、保留 status_limit 事实。 |

## 设计核对

- 游客没有账号档案或独立联系人实体。姓名/联系方式属于 `collected_info.basic_info`，再进入 `resume_data.basic_info`；ContactRedactor 的映射仅存在于单次调用内存，不能充当存储。原始电话/邮箱仍不出现在文本模型输入中。
- 空抽取字段表示本轮未提供，不能解释为删除历史联系信息。用户编辑器显式修改/清空仍走既有编辑器保存边界。
- 事实清洗和容量判断是两个维度：`content_integrity=changed_by_fact_sanitizer` 不再抹掉实际是否超页；保存后清洗所形成的“符合页数”也不被宣称为原改写稿的压缩成功。
- 歧义团队原句不进入 active facts，也不交给 writer。追问为“**三人团队这句说的是哪个项目？**”，确认后使用原话和原轮次入档；一次短答只确认一条待确认记录。
- 定位语义核验不可用、结果缺失或确实增加事实时仍清空定位；诊断只保存固定原因、字段路径和失败维度，不保存模型错误输入或个人资料。

## 修改文件完整清单

业务文件：

- `backend/app/agents/fact_extractor.py`
- `backend/app/agents/resume_graph.py`
- `backend/app/agents/resume_writer.py`
- `backend/app/agents/tailor_pipeline.py`
- `backend/app/agents/turn_actions.py`
- `backend/app/schemas/writer.py`
- `backend/app/services/candidate_sections.py`
- `backend/app/services/fact_guard.py`
- `backend/app/services/profile_bridge.py`
- `backend/app/services/resume_capacity.py`
- `backend/app/services/resume_facts.py`
- `backend/app/services/resume_field_hygiene.py`
- `backend/app/services/skill_groups.py`
- `backend/app/services/structure_plan.py`

回归与交接：

- `tests/test_replay_guest_fidelity_regressions.py`：新增 28 项虚构资料/fake-model 回归。
- `tests/test_resume_capacity_commit_fix.py`、`tests/test_committed_resume_receipts.py`：更新清洗后实测页数的断言，继续覆盖保存回执与 checkpoint 修复失败。
- `mmr.md`、本文件。

## 验证

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py
```

全量 **1210/1210 通过**。覆盖游客联系人两轮保留与 writer 页头合并、专业连写、成对括号与技能拆分、清洗后的 merge/shorten/超页回执、定位批量核验及诊断、lenient 裁剪与严格失败、团队句迁移/歧义追问/短答接续、状态 role 的入档和 canonical 清理。

修改文件 Ruff 通过（沿用仓库既有 E402 导入布局，检查时仅忽略 E402），`git diff --check` 通过。模型调用均由 fake/局部替身承担；没有真实模型回放、外部写入或更改既有回放产物。
