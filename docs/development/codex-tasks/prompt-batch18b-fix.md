# 第十八批 b 修复轮：技术栈真实模型回放发现的 3 个问题

承接你上一轮的 batch18b（技术栈字段，报告 `batch18b-report.md`）。Claude 之后改过 `backend/app/services/tech_stack.py`（`LIST_ONLY` 中文能力词只在列表语境生效、`split_spaced` 空格分隔列表拆分）并在 `tests/test_batch18b.py` 末尾加了 `TechStackProseBoundaryTests`，请保留。当前全量 2267 项通过。

用本地真实模型（DeepSeek，AGENT_MODE=loop）跑了三轮，脚本与临时库在 `evaluation/batch18b-live/`（`chat_tech.py`、`db/app.db`、`db/cp.sqlite3`、`tech_sid.json` 是会话 id；均为虚构人物，可用于离线复现，**不要提交该目录**）。结果：

- 第 1 轮（用户：「……我们这个项目使用了 mcp 记忆 toolcalling longchain。帮我写简历。」）：项目 tech_stack = `['MCP','记忆','Tool Calling','LangChain']` ✓。
- 第 2 轮（补一段电商实习）：工作经历 tech_stack = `['Java','MySQL']` ✓。

## 问题 1（严重，数据丢失）
第 3 轮用户说「给简历 agent 那个项目的技术栈加上 FastAPI，去掉记忆。」工具记录：`record_facts ok → edit_resume insufficient → edit_resume insufficient`，edit_resume 返回「请指明要修改技术栈的项目或工作经历」。**但保存后的稿件被改了**：该项目 tech_stack 从 4 项变成只有 `['MCP']`，要点从 3 条变成 1 条（只剩「完成一个帮学生写简历的 agent」）；FastAPI 没加上。
要求：
- 定位是谁改了稿件（怀疑 record_facts 对「去掉记忆」的处理/重算技术栈或覆盖重算，或 insufficient 路径仍写回）。工具失败（insufficient）时稿件必须**逐字不变**；任何路径都不得因一次增删而丢掉其他技术项或要点。
- 「那个项目」「简历 agent 那个项目」这类指代应能匹配到唯一项目（只有一个项目时直接命中；有多个时按名称子串/语义关键词匹配，仍不唯一才 insufficient）。修好后本例应得到 `['MCP','Tool Calling','LangChain','FastAPI']`，其他要点不变。
- 加回归：用该会话的真实状态（可从 checkpoint 导出成 fixture，脱敏无需，人物虚构）或等价桩复现，断言失败路径稿件不变、成功路径结果正确。

## 问题 2：正文重复技术且原样带错拼写
第 2 轮后项目要点为：「负责后端与工具编排，项目采用 MCP、记忆与 Tool Calling…」「项目使用 longchain，并通过 MCP 接入…」。已有技术栈行时：
- 要点里出现的技术名必须用规范名（longchain→LangChain 等，用同一张别名表确定性替换，仅替换别名表中的词）。
- 要点中「项目采用/使用 X、Y、Z」这类**只是罗列技术、没有具体动作**的子句，在技术栈行已覆盖这些技术时确定性删除该子句（保留同一要点里的其他动作，例如「通过 MCP 接入 Claude」是具体用法，要保留）。若整条要点只剩罗列则整条删除。同步引用/hash/coverage，幂等。
- 写稿提示里说明：技术栈已单独成行，要点写「用 X 做了什么」，不要单纯罗列技术。

## 问题 3：回复措辞与事实不符
第 1 轮回复说「你原话里的 longchain 我按 LangChain 处理，但工具那边没接受这个写法，所以正文没有替你写进具体框架名」，而技术栈行已含 LangChain。查明是哪个工具结果让模型这么说（可能是某处对 longchain 的拒绝/警告信息），让工具结果如实反映「已按规范名 LangChain 写入技术栈」，避免误导。

## 验证
- 全量 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py` 必须全过；Ruff、`git diff --check` 通过。
- 不调用真实模型，不 commit/push/部署。在 `batch18b-report.md` 末尾追加「修复轮」一节：根因、改动、测试数量与结果。
