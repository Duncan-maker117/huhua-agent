# 第十八批 b 修复轮 2：真实模型重跑仍有 3 个问题

承接修复轮 1（报告 `batch18b-report.md`「修复轮」一节）。修复轮 1 的数据丢失问题已在真实模型下确认修好（第 3 轮 `['MCP','Tool Calling','LangChain','FastAPI']`，要点逐字不变）。用同一脚本 `evaluation/batch18b-live/chat_tech.py` 再跑真实模型，复现材料在 `evaluation/batch18b-live/run2/`（`db/app.db`、`db/cp.sqlite3`、`tech_sid.json`、`server.log`；虚构人物，目录已 gitignore，勿提交）。稿件在 SQL：`app.services.session_store.load_resume_session(sid)`。

各轮工具：
- 第 1 轮 31.7s：record_facts ok → write_draft ok → ask_user ok
- 第 2 轮 24.6s：record_facts ok → **edit_resume ok**（没有调用 write_draft）
- 第 3 轮 7.9s：record_facts ok → edit_resume ok → check_layout error

## 问题 A（严重，谎报）：新增经历被 edit_resume 吞掉
第 2 轮用户补充「2025.07-2025.09在一家电商公司做后端开发实习，用Java和MySQL写订单查询接口，给慢查询加了联合索引，平均耗时从约400ms降到约150ms。」模型调用 edit_resume，返回 ok，回复说「已把你刚说的这段实习写进稿子……技术栈记为 Java、MySQL」，但最终稿件 `work_experience` 为空，版本历史也没有包含工作经历的版本。
- 先确认这是否在 `627a06f`（batch17b，线上版本）就存在，还是 batch18b 引入；在报告中写明。
- 修复：edit_resume 遇到需要新增条目的请求，要么能基于本轮 record_facts 的事实真正新增条目，要么返回明确的 insufficient/提示模型改用 write_draft；**绝不能返回 ok 却没有对应改动**。工具结果要基于实际稿件 diff 说明改了什么（新增了哪个条目），没有 diff 就不是 ok。
- 另查 check_layout 第 3 轮 error 的原因。

## 问题 B：罗列技术的要点在 write_draft 首稿未清理
版本 1（label「定制简历」）项目要点：
1. 「负责帮学生写简历 agent 的后端与工具编排」
2. 「项目使用 MCP、记忆、Tool Calling 与 LangChain，并可通过 MCP 接入 Claude 使用」
3. 「项目采用 MCP、记忆、Tool Calling 与 LangChain 搭建 agent 能力」
技术栈行已是这 4 项。第 2、3 条是修复轮 1 应清理的形态，但真实 loop write_draft 路径没生效（离线 fixture 通过而真实路径没走到？请找出真实路径差异）。第 3 条「采用 X、Y 搭建 agent 能力」也属于空泛罗列（「搭建 agent 能力」不是具体动作），应删除整条或删掉罗列部分。用户原话里的具体功能「能根据用户口述直接出简历初稿」在版本 1 中**没有写进要点**，却被技术罗列占了位，最终稿也没有——事实覆盖应当发现它被漏写。

## 问题 C：删子句后残留连接词
版本 2（label「局部修改」）第 2 条变成「并可通过 MCP 接入 Claude 使用」。删除罗列子句后，剩余部分开头的连接词（并/并且/且/同时/以及/还/，、等）要确定性去掉，变成「可通过 MCP 接入 Claude 使用」；更好的是保留主语动作形如「通过 MCP 接入 Claude 使用」。加回归。

## 验证
- 用 run2 的真实状态做离线回归（导出 fixture 到 tests/fixtures/），断言：A 新增经历要么落稿要么工具不报 ok；B 首稿两条罗列要点被清理、口述出稿功能被覆盖检查捕获；C 无残留连接词。
- 全量 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py` 必须全过；Ruff、`git diff --check` 通过。
- 不调用真实模型，不 commit/push/部署。在 `batch18b-report.md` 末尾追加「修复轮 2」一节。
