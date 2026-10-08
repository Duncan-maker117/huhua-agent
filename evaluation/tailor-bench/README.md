# Tailor benchmark（PR0）

用 12 个**完全虚构、已按 Claude 审定意见修订的 truth** 案例测量现有 `stream_agent`。
业务基线为本地 `overhaul/tailor` 分支的 `a742100`（`chore: snapshot before tailor overhaul`）。
`baseline-v2` 始终使用该旧业务源码；PR1 在独立工作区并行，不进入基线。不推送或部署。

修订交付：[v2 summary.md](runs/20261008-baseline-v2/summary.md)、[12 个用例](cases/README.md)、[v2 Claude 待审队列](runs/20261008-baseline-v2/review-queue.json)。[v1 历史报告](runs/20261008-baseline/summary.md) 及其全部原始证据保持不变。

## 文件与证据

- [用例索引](cases/README.md)：八类岗位与四个特殊场景；每例两个纯编辑指令。
- `run_bench.py`：真实 graph 入口、隔离数据库、调用计量、逐版本捕获、独立评分。
- `simulate_user.py`：temperature 0 模型仅选尚未披露的事实编号；确定性移除项目口语前缀后渲染，拒绝模型自写答案与非法编号。
- `judge.py`：数字/禁断言初筛、逐条语义核验、五维质量、覆盖率、编辑执行与双向盲评。
- `report.py`：聚合指标、失败清单和 Claude 待复核队列。
- [费率来源与区间口径](pricing.json)：已报告 token 的费用估计范围，不是实际账单。
- `runs/<run>/<case>/case.json`：该次运行实际使用的冻结用例，之后修改 cases 不会改变历史输入。
- `turns.json` / `transcript.md`：每轮输入、公开回复、阶段、耗时和调用用量。
- `versions.json`：每次不同 `resume_data` 的完整快照、当时已披露材料与可见性。
- `resume.json`：SQL 最终已提交稿件；聊天里给过正文不等于已写入此文件。
- `scores.json`：每版评分、每条 edit 的执行判断及失败重评历史。
- `edit-inputs.json`：每条 edit 的前后稿件和当时已披露材料。
- `meta.json`：首稿事件、版本映射、图/模拟器/评审调用分别计量。
- `manifest.json`：业务源码文件 SHA-256、Git 快照、模型、运行配置、用例哈希及重评记录。

## 运行

在仓库根目录，使用已有 `.venv`；无需新增依赖。默认只验证用例，不调用模型：

```sh
.venv/bin/python evaluation/tailor-bench/run_bench.py
.venv/bin/python -m unittest discover -s tests -p 'test_tailor_bench_*.py'
```

完整运行（会使用项目已配置模型产生费用）：

```sh
.venv/bin/python evaluation/tailor-bench/run_bench.py --live --concurrency 3 --output evaluation/tailor-bench/runs/NEW-RUN
```

也可以先固定所有对话，再独立评分，避免评分重试影响被测对话：

```sh
.venv/bin/python evaluation/tailor-bench/run_bench.py --live --graph-only --concurrency 3 --output evaluation/tailor-bench/runs/NEW-RUN
.venv/bin/python evaluation/tailor-bench/run_bench.py --live --rescore evaluation/tailor-bench/runs/NEW-RUN --concurrency 3
```

`--graph-only` 返回 `partial` 和非零退出码，因为语义评分尚未完成。
`--rescore` 默认只重评 `error/not_run` 等未完成评分，保留旧尝试，不重复任何用户对话。
评分契约修订后，用 `--rescore PATH --rejudge-versions` 统一重评所有非空版本（含已完成版本）；原分数进入 `previous_attempts`，调用和用量累计保留，最终评分记录 `judge_code_sha256`。该选项必须与 `--rescore` 同用，不会重新生成对话。
`--case ai-pm-01` 可限定运行/重评用例；输出目录已有内容时拒绝覆盖。
模型响应格式错误保留已解析的评分 JSON 与受控校验原因；不保存 provider 错误正文、凭证或推理内容。

## real-01：私有真实材料

默认命令始终只选上面的 12 个公开合成用例。`real-01` 的原上传消息、237 字第二轮修改指令及来源事实只存于 Git 忽略的 `cases-private/real-01.json`；`golden-one-page.md` 仅作验收参照，绝不送入 graph、模拟用户或 writer。所有含此用例的运行只能写入 Git 忽略的 `runs-private/`，不能指定公开 `runs/` 或仓库外路径。

已保存的旧 UI 实测可离线导入新基线，不调用任何模型，也不修改原始材料、PDF 或既有 run：

```sh
.venv/bin/python evaluation/tailor-bench/private_case.py \
  --from-real-run data/output/tailor-real-materials-20261008 \
  --output evaluation/tailor-bench/runs-private/NEW-SAVED-BASELINE
```

本地已导入 `runs-private/20261008-saved-real-01-baseline/`：两轮稿件完全相同，两份保存的 PDF 哈希相同，实际均为 3 页；终稿 32 条 bullet。8 项用户目标中 1 项原本满足、7 项失败；第二轮 14 个底层操作执行 0 个，1 个原本满足、1 个因缺少历史会话约束证据而未知，其余 12 个未执行。导入状态为 `incomplete`，因为语义事实、质量和覆盖率尚未评分。详细证据见本地私有目录的 `summary.md`、`private-acceptance.json` 与 `manifest.json`。

显式选择私有回放的无模型预检：

```sh
.venv/bin/python evaluation/tailor-bench/run_bench.py --include-private --case real-01 --graph-only
```

需要实际重跑当前 graph 时才加 `--live` 与一个**新的** `runs-private/` 输出路径。私有 live 只允许 `https://api.deepseek.com` 的 `deepseek-flash`（主模型与结构化模型），且必须 `--graph-only`；独立语义 judge 尚无授权，因此不能送往默认 `deepseek-v4-pro`。固定两轮回放不插入模拟追问。报告分开列出 8 个用户目标、14 个操作、`already_satisfied` 与 `executed`，以及真实 PDF 页数和仅用于诊断的估算行数。

## 评测口径

1. JD 独立一轮走当前 `task=decode_jd` 入口，候选材料和 edit 均走 `task=auto`。无 JD 用例直接发送方向。
2. 完成 opening 后最多回答四轮真实追问；不主动注入生成指令。只有 agent 明确提出生成邀约时才接受。
3. 模拟用户以结构化 JSON 选择最多两个未披露事实编号，模型不写回答。仅去掉 truth 的 `在“项目”中，` 前缀，其余字符与否定限定保留；失败走关键词回退。选空时优先返回相关的已有否定事实（可重复），无依据时明确不知道。编号选择与回退均记录；`opening_fact_indices` 和每版本 `disclosed_fact_indices` 用于去重及披露覆盖率，不送入被测应用。
4. 固定 edit 不提供隐藏事实；只有岗位重排与精简要求。其字面文本仍作为当轮用户输入保留。
5. 每轮读取持久 checkpoint 历史及 SQL 提交结果，按变化顺序记录，不做跨时间全局去重。撤回旧稿也会产生版本。
6. 内部 checkpoint 不等于用户已看到的稿。`user_visible=true` 才表示提交成功。**首稿只取首个可见、至少一段经历 bullet/description 非空的版本**，轮数和五维质量都按它计算；stage 仅留诊断，不用于验收。
7. 每版评分只见候选人正文、JD、完整 truth 和截至该版的已披露材料；不见版本名、生成理由、图阶段。仅存于完整 truth、未披露的主张标记 `truth_only`。
8. title/name/skill 按字段分流做已披露文本确定性核对，错误标题、重复项目、方向扩写和已披露教育缺失属于质量检查；句子断言才送模型事实核验。`uncertain` 单列 `unverifiable_units`，不计疑点；词法命中、`unsupported/truth_only` 仍是待复核疑点。`confirmed_fabrications=null` 不等于零；Claude 后续逐条复核。没有正文、模型失败或评分格式失败不能算安全通过。
9. 本次只有基线，无新版对手，pairwise 胜率不适用；`pairwise()` 已实现固定 seed 的 A/B 随机与交换顺序评审，供后续对照使用。
10. 每版同时报告 `coverage_of_disclosed`（该版已披露证据）和 `coverage_of_truth`（完整事实池，终稿衡量追问+写作）。一个要求有任一合格事实证据即记要求覆盖，另列 fact coverage 防止把部分证据称为全部覆盖；全未披露要求在 disclosed 中 N/A。11 个 gap 要求不进入正向分母，单列 match_plan 诊断；旧链路未实现 match_plan 记 N/A。事实编号按完整事实的严格口径处理：部分披露不加入 `disclosed_fact_indices`，正文只表达一个事实的部分内容也不能给整个事实计覆盖。`fact_total` 统计 `(requirement_id, fact_index)` 证据位，同一事实用于两个要求分别计数。独立技能、标题和求职意向不能充当经历覆盖证据；无经历断言但有技能的稿仍接受质量评分，正向经历覆盖为零。
11. 全体 12 例是起步回归集，不是八类岗位能力证明；模拟用户也不代表真实使用研究。

## 隔离与计量

在导入任何 app 存储模块前覆盖数据库路径，使用临时 SQLite、随机临时加密密钥和生产同款 `SecureCheckpointSaver`。
不会启动服务器、档案后台任务、邮件、联网工具、RAG 或外部 tracing；只向已配置模型服务发送合成文本。
应用数据库与 checkpoint 在运行退出后清理，输出的合成证据保留。

图模型使用现有主模型/结构化模型及当前参数，不修改旧链路构造行为。当前凭证的模型列表返回 `deepseek-flash` 与 `deepseek-v4-pro`：前者是旧链路模型，后者是唯一不同于旧链路且已验证可访问的评审候选。不能据此宣称它是所有模型中最强或与主模型完全独立。

上下文 callback 覆盖图内重新创建的模型；报告的是 **logical_model_calls**。SDK 内部 HTTP 重试不可观测，失败调用未报告的 token 不算零。图、模拟器与 judge 的 token 分别列出，费用仅对已报告 token 给当前公开费率范围。

`20261008-pilot` 是评测器开发小样：追问上限为 1，旧编辑指令和初版评审校验存在问题，其结果不能并入正式基线。修订后的正式结果以 `20261008-baseline-v2` 为准；v1 不覆盖。业务源码是否改变由 manifest 的 SHA-256 检查及 `git diff a742100 -- backend web` 验证。

v1 的 direction-01 分工、ai-pm-01 重测追问存在规则漏答；v2 两条原问题已通过真实模型选择预检，见 [selector-preflight-v2.json](selector-preflight-v2.json)。预检两次调用独立于正式基线统计。v2 运行后的新疑点仍需 Claude 差异复核，不沿用 v1 的“确认新增经历事实 0”当作本轮结论。

导入场景只读诊断：[import-intake-diagnosis-v2.json](import-intake-diagnosis-v2.json)。旧解析器不识别该用例的简写栏目；此前完整简历测试使用支持的栏目格式并带显式生成指令。该差异留给 PR4 处理。

Claude C 中关于 import-01 的 T6 存在描述偏差：T6 是“本地手测、没有性能测试或用户数据”，并未声明没有排查记录。模拟器仅返回这些原有事实，不编造“没有排查记录”，具体记录见 v2 transcript。
