# Tailor PR3：事实母版、保存与导入边界

PR3 把候选事实与投递文稿分离。`collected_info` 中每段经历有稳定身份、active/superseded/deleted 事实及原文出处；writer 输入只包含 active facts。聊天抽取使用 sparse patch，逐条校验出处、数量、责任、状态及语义，坏一条不废掉整轮。

## 保存与恢复

`resume_sessions.resume_state` 是单独加密的 JSON 字段，与已有文稿和文本在同一 SQL 事务提交。writer/restore 保存不从稿件重建母版；手工新增或改写才追加 `source=editor` 事实，删除 bullet 不删事实。恢复以 SQL 已提交的文稿、事实、元数据和版本为准。checkpoint 写入失败/SQL 失败均不会报告成功。

来源禁用、档案更正及删除会清理事实、原始笔记、元数据和旧版本；无元数据的旧稿仍按同条目失效原文和近似表述清理。服务器生成的身份保留跨会话、伪造、去 ID 和明确删除防护。密钥迁移、备份摘要包含新字段。

新增 schema 版本 2。现有数据库必须按既有显式副本迁移流程升级；没有自动迁移真实库，也没有重启已有服务或部署。

## 导入与输出

同名经历合并事实及出处；联系栏不再成为项目。编辑记录只作上下文，冲突保留选择项且正文只选一个值；Markdown 链接保存可读文字及结构化 URL。隐藏经历仍保留在数据里，六模板 HTML/PDF、Word 和纯文本均跳过，预览字段路径保持原数组索引。

使用忽略目录中的 real-01 原始材料进行确定性导入检查：识别四个真实项目，联系方式进入基本信息，两个项目链接保存，四条字段冲突进入核对记录；writer 投影不含 raw_notes。结果位于 `evaluation/tailor-bench/runs-private/20261008-pr3-import-check/`。这不是新 writer 实测或一页成稿验收，未发送材料给外部模型。

## 验证

- 全套隔离离线测试：677/677，15.679 秒，日志 `/tmp/huhua-pr3-full-tests-v2.log`。其中 9 条属于并行准备且尚未集成的 PR4 容量/版本纯组件测试。
- 存储、来源、隐私、迁移专题：137/137。抽取、导入、会话事实专题：97/97。与全套有重叠，不累加。
- 词法/语义边界包括中文数字、Java/JavaScript、责任升级、否定、原型、同一行 JD 污染、截断否定的 quote、未知和跨条目 ID。
- 独立复核发现的同行 JD、无元数据旧稿残留、跨条目归属和失效标题问题已修并回归。
- Ruff 与 `git diff --check` 通过。旧 benchmark 218 个文件 SHA-256 未变；真实用例和结果留在 Git 忽略目录。

旧行为测试改为 sparse patch/active facts/文稿隐藏契约，安全、权限、隐私、加密、导出覆盖保留。删去无调用方的旧 `_merge_extracted_patch` 和 `_extracted_facts_have_source`；未删除安全测试文件。

后续按 §8 接入 PR4 writer、局部修改、版本撤销与页数预算，再跑逐版本 benchmark。离线通过不能替代模型事实与写作质量复核。
