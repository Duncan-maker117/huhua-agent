# 第十七批 s 修复说明

## 根因与边界

本机 `langchain-openai 1.6.3` 的 Chat Completions 消息转换不保留 DeepSeek 的 `reasoning_content`。因此思考模式的多步工具调用无法直接依赖现有 ChatOpenAI 消息往返。关闭思考可绕过此协议要求；思考开启时本 spike 改用现有 OpenAI SDK，保留完整流式字段。服务端 400 未在本批复现或实测消除。

项目现有 `model_privacy.redact_model_messages` 对字典的 content/function_call/tool_calls 脱敏，不包含 provider 的思考扩展字段。spike 单独检查该字段；如含联系方式则停止后续请求，避免隐私外发，也避免破坏需要原样回传的协议。本批不修改公共脱敏函数。

## 改动文件

- `backend/app/agents/orchestrator_spike.py`：独立循环、两种模式、九个工具 schema、注入式假工具、可选真实 decoder/extractor 适配器、预算/异常/隐私/来源边界。
- `scripts/run_agent_spike.py`：显式 `--stub/--real`、配置隔离、预期判定、逐步指标及 Markdown/JSON 报告；不自动运行真实模型。
- `evaluation/agent-loop-spike/cases.json`：十类合成案例、可接受序列、禁用项、人工复核点及脚本桩，未把人物材料加入系统提示或手册。
- `tests/test_orchestrator_spike.py`：17 项离线单测，其中一项遍历 10 例×两种模式；SDK 测试通过 `httpx.MockTransport`，不请求真实网络。
- 本目录 README、修复说明、两个 stub run 报告；根 `mmr.md` 仅在末尾追加本批交接。

## 验证

- 新增定向测试：17 项通过。
- CLI：off / thinking 各 10/10 符合脚本预设，报告成功生成。脚本 token、回复和选择是给定数据，不能解释为 DeepSeek 正确率、速度或成本。
- 指定全量命令：2013 项，2011 通过、2 项原有跳过、0 失败，88.964 秒，退出码 0；日志 `evaluation/agent-loop-spike/full-tests.log`（按仓库规则忽略）。Ruff 与差异空白检查通过。
- 未改已有测试断言、route_by_stage、现有节点、前端或 dist；未安装依赖、调用真实模型、访问 8833/8834、提交、推送或部署。

## 失败做法与修正

- 不能靠把 reasoning_content 塞进普通 LangChain assistant 的 additional_kwargs 就假设可回传：当前版本转换器会丢掉扩展字段，因此采用原始 SDK 消息字典。
- 新增测试首轮因系统提示中的通用短语与一例短消息完全相同触发防场景泄漏断言（两种模式各一次）。改为不引用案例原句的通用原则后通过，未放宽测试断言。
- DeepSeek 文档网页正文抓取部分超时；已读取官方 Tool Calls 页面及官方 Thinking Mode 搜索摘要。协议实现以字段级 SDK 离线测试验证，服务端结论明确留待实测。

## 未完成

真实模型两模式的 10 场景选择、顺序、延迟、token、400 消失及语义抗注入尚未实测，由 Claude 按 README 执行。默认写稿/编辑/排版/公司搜索均为模拟能力；真实适配器只验证了委托结构，未调用真实 decoder/extractor 模型。不会据本批离线结果替换现有路由。
