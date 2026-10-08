# Tailor PR1：无用代码清理与配置一致性

2026-10-08，独立 `tailor-pr1` worktree；基于 `58ee7a6`，未合并主工作区、推送或部署。PR0 / baseline-v2 仍使用主工作区的旧业务代码。本记录不更新项目 `mmr.md`。

## 变更

- 删除无调用方的 `backend/app/deps.py`、`_jd_requirements_summary`、`format_strategy_for_prompt`。
- 删除未调用的 `COLLECTING` 占位、`SKIP_JD_OK`、`BUILDING`、`EVALUATING`、`EXPORT` prompt；所有实际使用的 `COLLECTING_*`、`JD_INPUT`、`LIGHT_MODE_ASK` 内容逐字保留，状态机未改。
- 主对话读取 `LLM_CHAT_TEMPERATURE`，默认仍是 `0.7`；兼容旧 `LLM_TEMPERATURE`，新键优先。提取 / Triage / editor 的显式 `0`、decoder 的继承温度、审查的 `0`、候选改写和归档的继承温度均保留。
- 增加可选 `LLM_MAX_TOKENS`，默认 `None`；仅显式配置正整数时对当前文本模型和图片转写设置输出上限。OCR 未配置时不发送该字段。`LLM_WRITER_TEMPERATURE=0.4` 仅预留，当前没有新 writer。
- 保留实际模型默认值 `gpt-4o`、结构化模型回退主模型、SDK 默认端点；将 `.env.example` 和 README 与其统一，供应商配置作为显式示例。
- JD 技能核对使用 ASCII 词边界：Java 不再由 JavaScript 命中，Go 不再由 Google 命中；支持中文相邻文字、大小写及 C++ / C# / Node.js 等字面名称。

本 PR 未改变事实抽取、写作/建议采用、档案存储、编辑器或 benchmark，未删除测试文件。全局 `max_tokens` 是可选输出限制，并不是输入长度或费用预算。

## 验证

| 检查 | 结果 |
|---|---|
| 配置、OCR 与正文核对定向回归 | 15 / 15 通过 |
| `scripts/run_tests.py` 隔离全套 | 556 / 556 通过，12.987 秒 |
| 修改的 Python 文件 Ruff | 通过 |
| 活跃 prompt 字面值对比 | 6 条全部与基线相同 |
| `git diff --check` | 通过 |
| 主工作区 `git diff a742100 -- backend` | 无业务差异 |

复跑命令（使用现有虚拟环境解释器即可）：

```sh
PYTHONDONTWRITEBYTECODE=1 \
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
XDG_CACHE_HOME=/tmp/huhua-pr1-font-cache \
python scripts/run_tests.py
```

测试入口强制临时数据库与空外部凭证；本次使用主工作区已有解释器，仅复用依赖，没有复制 `.env`、数据库或凭证。全套日志保留在 `/tmp/huhua-pr1-full-tests.log`，SHA-256 为 `529e1b1883999262f0e81018865adebc61b9921677033a4e634d4fc805ead708`。

已知边界：未调用真实模型验证自定义输出上限；显式设得过低可能截断模型输出，默认未启用。后续阶段若要统一 decoder / 候选改写 / 归档温度，应作为独立行为变更评估。未实施 PR2 及之后的架构。
