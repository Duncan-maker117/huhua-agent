# 人物回放对比

## 两模式与人物对比

通过率按当前检查器重评，未改写旧产物；两模式总断言数不同，另列共同断言。
耗时/调用为平均 / 最大（已记录轮数/总轮数）；总秒含 SSE 与 canonical 回读，编排秒包含工具执行。
编排 token 仅含编排 SDK，不含工具内部模型；P/C/R/H = prompt/completion/reasoning/cache-hit。缺失保留 N/A，不能当作 0。
旧版 HTTP 计数若全为 0，不能据此认定没有模型调用或隐私检查已覆盖；需新回放核对。

| 人物 | Run / 模式 | 通过/总数（率） | 共同断言 | 未过项 | 每轮总秒 均/最大 | 编排秒 均/最大 | 编排调用 均/最大 | 编排 token P/C/R/H | 单次 prompt 中位/最大 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 合计 | p1-off-all-5 / off | 113/118 (95.8%) | 113/118 | 5 项（下表分人物） | 11.132 / 43.590 (42/42) | N/A (0/42) | N/A (0/42) | N/A / N/A / N/A / N/A | N/A |
| 合计 | p1-loop-all-5 / loop | 147/168 (87.5%) | 101/118 | 21 项（下表分人物） | 24.066 / 72.959 (36/36) | N/A (0/36) | N/A (0/36) | N/A / N/A / N/A / N/A | N/A |
| cold | p1-off-all-5 / off | 9/11 (81.8%) | 9/11 | common.first_draft、contacts_late | 3.378 / 4.825 (4/4) | N/A (0/4) | N/A (0/4) | N/A / N/A / N/A / N/A | N/A |
| cold | p1-loop-all-5 / loop | 16/16 (100.0%) | 11/11 | — | 15.705 / 27.550 (4/4) | N/A (0/4) | N/A (0/4) | N/A / N/A / N/A / N/A | N/A |
| upload | p1-off-all-5 / off | 8/10 (80.0%) | 8/10 | contacts_not_repeated、facts.no_extra_experience | 7.858 / 18.085 (4/4) | N/A (0/4) | N/A (0/4) | N/A / N/A / N/A / N/A | N/A |
| upload | p1-loop-all-5 / loop | 14/15 (93.3%) | 9/10 | facts.no_extra_experience | 19.105 / 23.681 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| returning | p1-off-all-5 / off | 6/6 (100.0%) | 6/6 | — | 9.367 / 18.292 (4/4) | N/A (0/4) | N/A (0/4) | N/A / N/A / N/A / N/A | N/A |
| returning | p1-loop-all-5 / loop | 11/11 (100.0%) | 6/6 | — | 22.349 / 23.442 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| tech | p1-off-all-5 / off | 17/17 (100.0%) | 17/17 | — | 20.829 / 43.590 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| tech | p1-loop-all-5 / loop | 21/22 (95.5%) | 16/17 | correction_190 | 37.036 / 51.554 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| ops | p1-off-all-5 / off | 13/13 (100.0%) | 13/13 | — | 14.682 / 28.900 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| ops | p1-loop-all-5 / loop | 18/18 (100.0%) | 13/13 | — | 34.164 / 43.434 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| career | p1-off-all-5 / off | 13/13 (100.0%) | 13/13 | — | 11.188 / 15.897 (4/4) | N/A (0/4) | N/A (0/4) | N/A / N/A / N/A / N/A | N/A |
| career | p1-loop-all-5 / loop | 16/18 (88.9%) | 12/13 | correction_four、loop.contacts_once | 32.491 / 44.052 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| service | p1-off-all-5 / off | 14/14 (100.0%) | 14/14 | — | 14.942 / 19.716 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| service | p1-loop-all-5 / loop | 19/19 (100.0%) | 14/14 | — | 25.937 / 27.416 (2/2) | N/A (0/2) | N/A (0/2) | N/A / N/A / N/A / N/A | N/A |
| design | p1-off-all-5 / off | 14/14 (100.0%) | 14/14 | — | 21.359 / 27.445 (4/4) | N/A (0/4) | N/A (0/4) | N/A / N/A / N/A / N/A | N/A |
| design | p1-loop-all-5 / loop | 18/19 (94.7%) | 14/14 | loop.contacts_once | 44.425 / 72.959 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| aipm | p1-off-all-5 / off | 8/9 (88.9%) | 8/9 | rewritten | 8.848 / 24.429 (5/5) | N/A (0/5) | N/A (0/5) | N/A / N/A / N/A / N/A | N/A |
| aipm | p1-loop-all-5 / loop | 10/14 (71.4%) | 5/9 | heading、labels、answers_used、no_repeated_dimension | 25.267 / 25.267 (1/1) | N/A (0/1) | N/A (0/1) | N/A / N/A / N/A / N/A | N/A |
| aipm_real | p1-off-all-5 / off | 11/11 (100.0%) | 11/11 | — | 7.418 / 30.754 (8/8) | N/A (0/8) | N/A (0/8) | N/A / N/A / N/A / N/A | N/A |
| aipm_real | p1-loop-all-5 / loop | 4/16 (25.0%) | 1/11 | common.rounds_complete、heading、labels、real_pains、mcp_decision、adoption_unit_and_owner、no_placeholder、rewritten、no_invented_metrics、depth_within_limit、loop.first_draft_by_turn3、loop.contacts_once | 14.336 / 41.037 (11/11) | N/A (0/11) | N/A (0/11) | N/A / N/A / N/A / N/A | N/A |
