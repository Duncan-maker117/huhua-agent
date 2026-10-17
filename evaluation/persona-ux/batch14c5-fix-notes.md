# 第十四批 c5：AI 产品岗 labeled 成稿骨架

基于 `huhua-b14 / batch14 / 8a341da`。仅本地修改；不 commit、push、部署，不启动或调用 8833/8834，不调用真实模型。接手时已有的 `mmr.md` 修改保留；c4 回放及其他已有回放文件只读。

## plain 漂移根因

`after-b14c4/aipm/01-initial.json` 与 `02-experiences.json` 的岗位为 `ai_pm`；到 `03-answers_1.json` 变成 `other`，`role_direction` 被替换成整段项目回答；`04-basics.json` 的方案卡和最终 `confirmed_plan` 均为 plain。

确定性入口 `_looks_like_role_direction` 同时命中了回答里的“设计”和“虚拟求职者”中的“求职”，把项目回答识别成新求职方向；`_direction_profile_update` 据此覆盖了岗位画像。后续沿 general 手册默认 plain，并非发现了宽容 schema 把 labeled 转成 plain 的证据。修复排除“关于「项目」”回答，并令“求职者”不能匹配求职意图；真实改投后端仍可更新方向。

写法另加独立保护：手册 labeled 优先，只有方案卡或明确写法编辑产生的 `bullet_style_source=user` 可覆盖。此来源标记不开放给模型 schema。plan、备选、confirmed_plan、writer（含 one-pass 返回 plain）及再校验均保持选择；只从 resume_meta.match_plan 恢复的续写也保留用户普通写法来源。

## 四个痛点的事实边界

真实第 4 条原话中的填空繁琐、复制粘贴、PDF 无法编辑、AI 不懂结构，在保存的经历投影及最终 active fact coverage（共 13 条，包括教育）中均未出现；PDF/结构那一段反而进入 `writing_rules`。回放没有保存完整的原始 extractor 响应、项目事实 kind/source_quote，不能断言每条是模型没抽，还是哪一层逐条过滤。

源码确认的缺口：`non_fact` 会排除“不知道”，通用遗漏补回又把“生成”视作指令，并要求叙事/动作线索，无法保证保留这种问题先行的产品描述。

新增 `product_pains.py`：原文明确的产品痛点进入 context，保留连续 source_quote；新建项目、已有唯一项目可兜底恢复，多个项目无唯一归属则不猜。明确编辑指令、本人“不知道”、外部参考均不转成痛点。抽取 prompt 同步要求分开痛点、分工、决策、状态；写作要求不再收录产品痛点。原事实母版不被 writer 修改。

`tests/fixtures/batch14c5-replay.json` 复制 c4 原输入和 coverage 中的 ID/text。测试使用的缺失 kind/source_quote 是明确标注的重建：以保存的事实文本作为引用，不声称它就是那次模型的原始 source_quote；抽取测试另使用逐字原输入。

## 两步写作与最终约束

1. 每个项目先调用严格 `FactSlots`：每个 active fact_id 恰好一次，槽位只能是问题/决策/迭代/技术/现状/标题性质/不用。不存在、遗漏或重复 ID、非法枚举使模型分类失效；确定性规则补全并纠正明显错分。分类只据 fact.text，题干不是本人事实。
2. writer 收到槽位映射及系统级写作合同。最终按槽位生成一行，引用仅限同经历、同槽位；正常句子、修复句子和整理后的兜底句全部走现有 fact_guard，再逐事实反向检查覆盖。引用一串 ID 不能代替正文表达。
3. 混写分工/现状的决策、跨槽引用、缺失行触发一次结构化 RepairOutput 修复；仍不合格则整理该槽事实并再校验。plain 或错标签但事实同槽的行可直接纠正标签。失败关闭，不发布未过校验的改写；具体未交付槽位进入诊断及核对提示。
4. 最终槽位门在旧的 polish、事实补回、限定保留、去重之后执行，防止它们重新追加无标签原话。项目标题性质和与标题逐字重复的事实不占正文。格式切换路径也禁止无标签行和纯个人项目性质行。
5. 行内 1–3 个短句，用分号连接；四个相关痛点可将后两点组成一个短句。自我评价压缩为“简历生成与使用效果仍在优化”，不提升为已改善。自动 labeled 项目方案最多 4 行；明确的 0/1/3 行上限、brief/backup 仍生效；工作经历等原有 plain 行数上限不扩大。

这增加了每项目一次分类及有界的槽位检查/必要修复；真实模型成本、时延与审美稳定性尚未测量。覆盖不足或事实保护失败时宁可提示待核对，不能保证在语义服务不可用时仍交付所有槽位。

## 回归与旧桩调整

新增 15 项 c5 测试，覆盖两份 c4 原输入/事实、缺失痛点与错 kind、未命名项目/多项目归属、外部参考/指令/unknown、岗位漂移、模型返回 plain、错误槽位和非法/重复 ID、分工/现状混写、无标签输出、跨经历引用、新数字、语义失败、标题重复、条数上限、plain 兼容及 hash/事实不变。旧的两个人物图回归及五人物/其他岗位回归继续运行。

旧断言只按明确的新行为调整：c3 的三行例子改用四行以同时检查问题/决策/迭代/上线；c4 原先允许的“纯定位无标签行”改为仅 plain 保留；明确普通写法测试补用户选择来源。`PlanModel` 和 intake 的 source-echo 桩补新分类协议，后者补成功语义响应；没有放宽事实保护或取消旧的业务断言。

实现验证中修复过：最终校验写入 deepcopy 前的旧条目导致正文/hash 错配；“逐项/持续”同义改写被既有硬校验拒绝，改用受支持措辞；“真实模型全流程仍需验证”被过宽的“全流程”所有权规则误排除，已收紧。失败日志保留在 `/private/tmp/huhua-b14c5/`。

## 改动文件

- `backend/app/agents/{fact_extractor,resume_graph,resume_writer,tailor_pipeline}.py`
- `backend/app/schemas/writer.py`
- `backend/app/services/{structure_plan,writing_style,labeled_writer,product_pains}.py`（后两份新增）
- `tests/test_batch14c5_labeled.py`、`tests/fixtures/batch14c5-replay.json`（新增）
- `tests/test_batch14c3_real.py`、`tests/test_batch14c4_replay.py`、`tests/test_replay_plan_intake_regressions.py`、`tests/test_resume_writer.py`、`tests/test_writing_upgrade.py`
- 本说明及 `mmr.md` 追加记录。

## 最终验证（2026-10-18）

- 指定全量命令：**1823 项，1821 通过、2 项原有跳过，0 失败**，60.094 秒；新增 15 项。日志 `/private/tmp/huhua-b14c5/full-final-verified.log`。
- 15 份变更 Python 文件 AST、Ruff 通过；`git diff --check` 通过。日志 `/private/tmp/huhua-b14c5/ruff-final.log`、`diff-check.log`。
- 接手时冻结的 **364 个回放文件 SHA-256 全部不变**；最终源码 SHA、分支、HEAD 记录于 `/private/tmp/huhua-b14c5/integrity.json`。
- 两人物错误 writer 桩的最终实际输出、槽位、引用/hash、覆盖及诊断：`/private/tmp/huhua-b14c5/aipm-stub.json`、`aipm_real-stub.json`。
- 本轮通过的是离线图/抽取/writer/事实保护/已有五人物等回归，**不是新的真实模型回放结果**。未调用真实模型，未复测真实模型耗时和标杆结构成功率。

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

分支仍为 `batch14`、HEAD 仍为 `8a341da`。下一步是在另有授权时进行新真实模型回放，保留本次冻结 c4 产物；本轮不自动执行。
