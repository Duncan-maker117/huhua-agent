# 胡话简历交接

## 目标
第十八批 c：给编排模式接入按需 use_skill，并同步删除技术栈与正文中的安全列举项。

## 已完成
- 启动解析 skills/flows 的 YAML frontmatter，校验必填字段并按 name 生成系统目录与 Literal 工具枚举。
- use_skill 返回完整可信正文；同轮去重、跨轮重置，不占四次业务工具预算，不增加模型调用。开启同消息多调用，skill 先加载，其余有状态工具顺序执行。
- metrics.skills 记录加载名称；沿用 tool_status 进度；两种 edit_resume 风险场景附 hint，已加载不提示。
- 删除技术时保守缩减同条目 bullet 的技术列表；唯一技术/无法安全缩减原句保留并出回执；更新引用/hash/coverage，重复删除不增加版本。
- 实测 write_draft 和模型改写的 edit_resume 均经过 resume_writer → career_messages('resume-write')，已加载新三条规则。
- 24 项新回归通过；全量 2331 项（2329 通过、2 项既有跳过、0 失败），116.141 秒。8 个相关 Python 文件 Ruff 与 git diff --check 通过。
- 6 个 skill 文件哈希未变，原 SYSTEM_PROMPT 字符串未改；差异与下批移出候选详见 batch18c-report.md。

## 未完成
授权的本地实现与离线验证已完成。真实模型命中率/流程选择没有回放；未 commit、push 或部署。

## 失败做法
- 将 skill 当业务工具计数或先执行写稿再加载，会浪费预算/导致同消息 hint 误判。
- 原 batch18b 的“删技术后正文逐字不变”断言不再符合本批要求；已改成只删目标列表成员，同时保留保存、撤销与其他正文断言。
- 指定虚拟环境没有 Ruff 模块，改用本机 /opt/homebrew/bin/ruff。

## 关键决策与理由
- 不并发修改业务状态；多 tool_calls 共享一轮模型调用并返回全部 ID。
- 本地正文由系统提示明确授权为可信指令，不经 untrusted_data/资料字段清理；未知 name 严格拒绝。
- 删除只改可识别列表，不调用模型；保留复合事实，不把删后的短句当成全量覆盖证明。
- write_draft 尚无代码生成的 document_changes；日期/角色更正并非全部能进入 correction_applied 快捷路径，已如实记入报告。

## 当前状态
分支 batch18b，HEAD 1c5855e，本批未提交。开场已有 flows/、resume-write 修改及 3 个 prompt 文件保留。本批增加 flow_skills.py、test_batch18c.py 和报告。旧交接全文追加到 mmr-archive.md。
日志 /private/tmp/huhua-b18c-full.log；测试使用隔离临时库及离线桩，没有本轮常驻服务。

## 接手步骤
1. 读 batch18c-report.md 并核对 git 状态；不要把开场 skill 修改当成本批改写。
2. 全量：DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py。
3. 若后续授权真实模型回放，重点核对 skills 命中、同消息加载、实际新增条目回执，以及删除后的正文/版本；不要只信最终回复。
