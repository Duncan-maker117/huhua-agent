# 第十四批 c7：c6 回放剩余三处

范围：`batch14 / 8a341da`，保留接手前 c5+c6 未提交修改。所有模型为本地桩；不 commit/push/部署，不访问 8833/8834。`runs/` 只读。

## 1. tech 量化事实在后段改写中丢失

- c5/c6 `02-polish.json` 均为 plain，云舟科技 `target_bullets=3`。c6 首轮保留“编写了 12 条接口测试用例”，润色轮事实层仍有该 fact，但正文与引用消失，coverage 把它标成“本版条数上限”的备用。同轮 `metric_repair=attempted`、`metric_appended=1`，没有压缩动作，页面为 1/1 页。
- 与 HEAD 的 AST 对照显示 `_missing_metric_facts`、`_metric_retention`、`_append_metric_bullets`、`_polish_rows`、`_apply_edit_contract` 在 c5+c6 中均未改。plain 不走 labeled 槽位选材；原代码已经保护带数字的引用不被早期“最低信息量”替换。因此不能把本次回放差异归因于 c6 新增选材逻辑。
- 实际漏洞：量化补回在 guard、polish、编辑契约修复等步骤之前；后续合法但不完整的改写仍能删去量化事实。最后的覆盖修复在条数满额时直接跳过，只有备用提示，没有合并保留。
- 新回归使用该轮真实输入、事实/引用与 3 条可见正文，重建未保存的 fact.kind/source_quote；本地桩让后段编辑契约修复返回该轮可见正文。禁用新末端门时复现“12 条”消失；启用后仍为 3 条，12 条接口测试、Redis 缓存与联调、订单查询、420→170ms 及导师/测试环境/未线上压测均保留，随后 170→190 更正也不丢 12 条。
- 修复：在 plain 最终正文去重后复用量化覆盖检查；遗漏的 active fact 先做词法/数字/归属校验，再在原上限内合并补回，更新引用、hash 和覆盖率。`final_metric_restored` 记录补回 ID。备用、brief、零条、范围外与 labeled 槽位仍遵循原计划。
- 证据边界：原回放没有 plain 分阶段原始响应，不能断言当次删句的是 polish 还是编辑契约修复；对照桩证明的是可到达的后段丢失路径。

## 2. 分工限定补回重复

`resume_limits._limit_key` 原本只归一“是…写的→由…编写”，不能识别“由组内另一位同学实现”。新增窄范围等价：模块不变、执行者不变、完成动作等价才视为已覆盖，再决定是否补回。比较完整子句，保留否定、计划、协助、部分实现等区别；分工句不再走字符集合近似匹配。回归检查补回幂等性、正文/hash 与不同模块/同学或同事/本人/否定/计划的反例。

## 3. aipm 照搬来自模型

证据位于 c6 `aipm/05-plan_confirm.json` 的 `workspace.tailor.resume_meta.writer_diagnostic.slot_lines[项目ID:问题]`：

- `writer_output` 就是“问题：学生难以梳理自己的经历，需要通过对话挖掘可写进简历的事实。”
- 只有一次 `stage=model`，`retry_count=0`，`final_handling=model`；没有确定性兜底。

在实际传给主 writer 的槽位合同中补充：概括为简历语言，不能整句照搬；保留需求，不改成已经实现的成果。示例“学生难以梳理自身经历；需借助对话挖掘可写进简历的事实”在本地桩中通过原事实门，最长公共子串 12≤24，引用及 hash 正确。未放宽事实校验，也未把这次问题误报为 c6 兜底导致。

## 验证与交接

新增 `tests/test_batch14c7_replay.py` 7 项，冻结证据投影在 `tests/fixtures/batch14c7-replay.json`。未修改旧测试、原回放、检查器或阈值。

- 定向：7/7，`/private/tmp/huhua-b14c7/target-final.log`。
- 全量命令：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py`；最终日志 `/private/tmp/huhua-b14c7/full-final.log`。
- c7 独立源码差异：`/private/tmp/huhua-b14c7/c7-only.patch`；tech 端到端桩产物 `tech-stub.json`；源码与 500 个历史回放完整性记录 `integrity.json`。
- 最终全量数与完整性结果同步追加到 `mmr.md`。真实模型是否遵从概括提示、真实回放分数与视觉分页未重新验证，不将桩结果称为真实回放通过率。
