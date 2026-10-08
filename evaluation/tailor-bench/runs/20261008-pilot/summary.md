# Tailor PR0 · 旧链路基线

运行时间：2026-10-08T18:35:41.973322+08:00。
业务源码快照：`a74210030bede74b76f693d5eaa3258e87dbabc6`；分支 `overhaul/tailor`。

用例全部为虚构草案，truth 与模型疑点均待 Claude 复核。没有宣称事实安全门槛通过。
每次内部 checkpoint 文稿变化与每次 SQL 提交变化均保留；只有 user_visible=true 表示已提交给用户。

| 用例 | 运行 | 用户轮数 | 内部及可见版本 | 可见版本 | 首稿轮数 | 平均轮延迟/秒 |
|---|---|---:|---:|---:|---:|---:|
| ai-pm-01 | completed | 5 | 5 | 5 | 5 | 10.901 |

## 评分与验收边界

- `scores.json` 逐版本保留确定性疑点、语义事实核验、五维质量与覆盖率；首稿和终稿 ID 见 `meta.json`。
- 数字、词表命中和模型指控均是待复核疑点；确认新增事实数量暂为 null，不能写成零。
- 编辑指令逐条保留 before/after 与指令遵循判断；无实质 diff 不计执行成功。
- 本次是基线，没有新版对手，pairwise 胜率为不适用；双向盲评能力在 judge.py 中提供。
- 逻辑模型调用与实际报告的 token 已记录；SDK 内部重试次数未知。费用无核实费率表时为 null。
- 旧链路没有新 guard，guard_fallbacks/误杀率为未观测，不伪记为零。
- 独立临时加密库和随机临时密钥随运行清理，合成 transcript 与稿件作为本地评测证据保留。

## 交接

逐例检查 `transcript.md`、`versions.json`、`scores.json`；先审 truth 再确认疑点。PR1 尚未开始。
