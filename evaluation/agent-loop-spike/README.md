# 第十七批 s：独立编排循环 spike

本批只验证编排的协议与代码边界，未接入线上图。两种模式的 10 例脚本桩均完成并符合预设序列；这不是模型工具选择正确率。真实 DeepSeek 的选择质量、400 是否消失、耗时和 token 消耗仍待 Claude 执行 `--real`。

## 设计与协议依据

`backend/app/agents/orchestrator_spike.py` 不被现有节点引用。两种模式都用现有 OpenAI SDK 的流式 Chat Completions，工具、系统提示与预算一致，避免把 LangChain/SDK 差异混进模式比较。

| 模式 | 请求开关 | assistant 回传 | 当前证据 |
|---|---|---|---|
| `off` | `thinking.type=disabled` | content、tool_calls；移除思考字段 | SDK 模拟流与脚本桩通过 |
| `thinking` | `thinking.type=enabled` | 拼接完整 reasoning_content，连同 content、tool_calls 持续回传 | SDK 模拟流与脚本桩通过；真实 400 待测 |

DashScope 按项目 `llm_compat` 的既有约定改用 `enable_thinking`。其他兼容代理的开关和字段透传仍需实际核验，没有静默降级或自动切换模式。思考模式不强制指定某个工具；使用 `auto`，预算耗尽后用 `none`。

本机检查的版本是 `openai 3.17.0`、`langchain-openai 1.6.3`。该版 LangChain 的 `_convert_dict_to_message` / `_convert_message_to_dict` 不保留 `reasoning_content`。SDK 读取流式 delta 的扩展字段，按工具 index 拼接 name/arguments，保留 id，再给每个调用追加匹配的 `role=tool` 消息。不得以空字符串替代丢失的思考内容；缺字段、重复 ID、截断响应会报告协议错误。

DeepSeek 官方文档要求携带 tools 的后续请求回传完整思考字段，因此本实现保留本轮全部 assistant 的思考内容，而不是只保留最近一次。参考：[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)、[Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)。官方工具示例也使用 `thinking.type=disabled` 关闭思考。本批没有请求真实模型验证这些服务端行为。

“≤4 步”在此定义为**最多 4 次工具执行尝试**，工具失败也消耗预算；最多 4 个带工具的模型轮次，再加 1 次仅生成最终回复的模型调用，所以模型请求上限为 5。即便模型一次返回多个工具，也逐项计数，超额工具只得到预算错误、不执行。报告同时保留请求序列和实际执行序列，避免超额/禁止请求被隐藏。

## 数据与护栏

- 系统提示只放通用产品原则。案例内容、预期、脚本及人工检查点只在 `cases.json` 中；真实模型只收到该例的历史摘要、本轮消息、已有事实和稿件状态，不收到预期或脚本。
- 来源、摘要、JD、档案和工具返回值均作为 user/tool 的 JSON 数据传入；不会拼到 system。工具结果包在 `untrusted_data` 中。`read_jd` / `record_facts` 只允许 `source_id`，原文由代码取，不接收模型生成的事实文本。
- `record_facts` 拒绝已识别为 JD/reference 的来源，并复用现有候选人证据过滤。引用边界和来源检查不等于完整的语义抗注入防线；来源本身的恶意文本、未经识别的混合材料仍需后续事实验证。第 0 期没有生产级写稿或权限承诺。
- 复用 `ContactRedactor` / `redact_model_messages`，每个出站请求都检查；原始工具结果、历史、稿件、参数在进入模型前脱敏。JSON 先按文本处理，不能通过伪装成媒体字典绕过。工具 ID 若带联系方式则拒绝。
- `reasoning_content` 必须原样保留的要求与联系方式隐私冲突时，**停止本轮后续请求**，报告 `contacts_in_reasoning`；不把原始联系方式发送出去，也不悄悄改写思考字段骗过协议。报告不落盘原始思考内容、请求头、密钥或服务端错误正文。
- 每次模型和工具调用都有超时；模型异常记录类型和 HTTP 状态（可用时），工具异常以结构化结果回传。没有无限重试，没有真实存储写入。

## 工具实现与可注入点

九个 schema：`read_profile`、`use_profile_items`、`read_jd`、`search_company`、`record_facts`、`ask_user`、`write_draft`、`edit_resume`、`check_layout`。

默认 `FakeTools` 只操作本轮内存。事实模拟器原文保存，初稿模拟器拼接已记录事实；编辑工具回显请求，排版工具返回模拟结果，搜索工具不联网。它们不验证生产能力或生成质量。`results={tool_name: result}` 可模拟信息不足等返回；`handlers={tool_name: callable}` 可注入同步/异步实现。每例使用独立实例，不会串状态。

可选真实适配器通过 `real_adapters(llm)` 返回 `read_jd` 和 `record_facts` 两个 handler，分别包装 `run_decoder_chain`、`extract_facts_patch` + `apply_fact_patch`。使用方式：

```python
handlers = real_adapters(llm)  # 调用方显式提供已配置的 ChatOpenAI
tools = FakeTools(user_message, state=state, handlers=handlers)
result = await run_loop(model, tools, user_message=user_message, mode="thinking")
```

这些适配器仅写 `tools.state` 内存，沿用原函数的脱敏与来源验证。CLI 的 `--real` **只替换编排模型，九个工具仍为假实现**，以隔离编排能力。真实适配器仅提供代码注入入口，不会被 CLI 自动打开；若另行注入，嵌套模型的 token 不包含在编排报告中，不能用该报告声称整条业务链的成本。

## 运行

在仓库根目录，使用项目已有虚拟环境，不安装依赖：

```bash
SPIKE_PYTHON="/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python"
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "$SPIKE_PYTHON" scripts/run_agent_spike.py --mode off --stub --cases evaluation/agent-loop-spike/cases.json
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "$SPIKE_PYTHON" scripts/run_agent_spike.py --mode thinking --stub --cases evaluation/agent-loop-spike/cases.json
```

`--stub` 不读取 `.env`，不创建网络客户端。脚本给定调用序列、回复和 token 计数；桩耗时是本机代码及首次导入开销，不能比较模型性能。已生成 [off 报告](runs/stub-off/report.md) 和 [thinking 报告](runs/stub-thinking/report.md)，各有对应 `report.json`。

以下命令留给 Claude 在有网络的环境运行，本批未执行：

```bash
SPIKE_PYTHON="/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python"
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "$SPIKE_PYTHON" scripts/run_agent_spike.py --mode off --real --cases evaluation/agent-loop-spike/cases.json
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "$SPIKE_PYTHON" scripts/run_agent_spike.py --mode thinking --real --cases evaluation/agent-loop-spike/cases.json
```

`--real` 读取 `backend/.env` 的 `LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`、`LLM_CHAT_TEMPERATURE`（兼容 `LLM_TEMPERATURE`）、`LLM_MAX_TOKENS`；同名进程环境变量优先。前三项必须显式配置，禁止意外落到 SDK 默认供应商。不要把密钥写入命令或报告。`--timeout` 默认每次 120 秒，SDK 自动重试关闭。

输出位于 `evaluation/agent-loop-spike/runs/<时间-模式-来源>/report.{md,json}`。也可用 `--name` 固定名称，已有目录会拒绝覆盖；`--output-root` 可用于隔离实验。退出码：0 自动检查全部通过；1 至少一例未通过；2 配置/输入或报告生成失败。单例模型错误不会中断其他案例。

报告包括逐例请求/执行工具序列、自动预期匹配、工具步数、模型调用数、模型与工具各自耗时、总耗时、prompt/completion/reasoning token、最终回复与人工检查点。未报告的 token 为 `null` / `N/A`，不估算成 0；reasoning 是 completion 的子集，不重复相加。保留案例与提示/schema 哈希和依赖版本，比较时确认一致。

## 待 Claude 实测回答

1. 当前配置的模型和端点是否接受两种开关？思考模式经过第二、第三步工具回传后是否仍出现 400？若失败，确认 HTTP 状态及错误类型，再在安全的本地调试中核对供应商扩展字段。
2. 每例是否在可接受序列中，有没有漏掉必要工具、错误顺序、无用调用或超过 4 步？先看请求序列，再看工具结果；不能只看最终回复好不好听。
3. 是否先展示价值、信息足够先写后问、局部编辑不重收集、遇到未知信息允许跳过？自动序列通过不代替这些语义核对。
4. 联系方式是否始终脱敏？JD、档案和返回结果中的指令有没有改变行为或导致虚构个人事实？脚本桩通过只说明数据边界正确，不证明模型能识别恶意指令。
5. 每例各步耗时及三类 token 分别是多少，供应商是否提供 reasoning token？建议相同案例两种模式交错重复至少 3 次，分别给出成功率、中位数与尾部耗时，勿从一次测量得出成本优势。
6. 思考模式增加的质量是否足以覆盖耗时和 token 成本？在工具全部模拟的前提下，只决定是否值得继续下一期；真实业务工具、跨用户轮次历史管理和线上迁移另行验证。

## 本地验证

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py -p test_orchestrator_spike.py
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

新增测试涵盖 10 例×两模式、4 次上限、超额批量调用、异常回传、来源与参数校验、信息不足、SDK 流式分片和完整历史、缺失思考字段、ID 错配、全边界脱敏、注入文本数据边界、真实适配器委托和报告生成。具体结果见 [修复说明](fix-notes.md)。
