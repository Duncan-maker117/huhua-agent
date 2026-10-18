# 人物回放对比

注意：fixtures 哈希或 recovery 设置不同，对比不是同脚本修复前后验收。

## 两模式与人物对比

通过率按当前检查器重评，未改写旧产物；两模式总断言数不同，另列共同断言。
耗时/调用为平均 / 最大（已记录轮数/总轮数）；总秒含 SSE 与 canonical 回读，编排秒包含工具执行。
编排 token 仅含编排 SDK，不含工具内部模型；P/C/R/H = prompt/completion/reasoning/cache-hit。缺失保留 N/A，不能当作 0。
旧版 HTTP 计数若全为 0，不能据此认定没有模型调用或隐私检查已覆盖；需新回放核对。

| 人物 | Run / 模式 | 通过/总数（率） | 共同断言 | 未过项 | 每轮总秒 均/最大 | 编排秒 均/最大 | 编排调用 均/最大 | 编排 token P/C/R/H | 单次 prompt 中位/最大 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 合计 | p1-loop-all-5 / loop | 147/168 (87.5%) | 147/168 | 21 项（下表分人物） | 24.066 / 72.959 (36/36) | N/A (0/36) | N/A (0/36) | N/A / N/A / N/A / N/A | N/A |
| 合计 | p2-loop-all-1 / loop | 143/168 (85.1%) | 143/168 | 25 项（下表分人物） | 20.690 / 48.567 (36/36) | 21.000 / 48.483 (34/36) | 3.265 / 5.000 (34/36) | 377686 / 41009 / 25961 / 271872 | 3256 / 5876 (111/111) |
| cold | p1-loop-all-5 / loop | 16/16 (100.0%) | 16/16 | — | 15.705 / 27.550 (4/4) | N/A (0/4) | N/A (0/4) | N/A / N/A / N/A / N/A | N/A |
| cold | p2-loop-all-1 / loop | 8/16 (50.0%) | 8/16 | common.first_draft、contacts_late、facts.retained、facts.scope、facts.no_extra_experience、facts.no_new_tools、facts.no_new_numbers、loop.first_draft_by_turn3 | 12.729 / 27.415 (4/4) | 12.659 / 27.341 (4/4) | 2.750 / 4.000 (4/4) | 36646 / 3370 / 1793 / 24192 | 3268 / 4292 (11/11) |
| upload | p1-loop-all-5 / loop | 14/15 (93.3%) | 14/15 | facts.no_extra_experience | 19.105 / 23.681 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| upload | p2-loop-all-1 / loop | 15/15 (100.0%) | 15/15 | — | 23.544 / 27.857 (3/3) | 23.462 / 27.780 (3/3) | 4.000 / 5.000 (3/3) | 37055 / 3742 / 2311 / 26496 | 2964.5 / 4429 (12/12) |
| returning | p1-loop-all-5 / loop | 11/11 (100.0%) | 11/11 | — | 22.349 / 23.442 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| returning | p2-loop-all-1 / loop | 10/11 (90.9%) | 10/11 | profile.import_receipt | 18.834 / 26.629 (3/3) | 18.677 / 26.463 (3/3) | 3.667 / 5.000 (3/3) | 34757 / 3487 / 2099 / 26112 | 3217 / 3922 (11/11) |
| tech | p1-loop-all-5 / loop | 21/22 (95.5%) | 21/22 | correction_190 | 37.036 / 51.554 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| tech | p2-loop-all-1 / loop | 21/22 (95.5%) | 21/22 | polish_identity | 23.186 / 41.273 (3/3) | 23.104 / 41.206 (3/3) | 3.333 / 4.000 (3/3) | 38090 / 3438 / 1738 / 27904 | 3749 / 5444 (10/10) |
| ops | p1-loop-all-5 / loop | 18/18 (100.0%) | 18/18 | — | 34.164 / 43.434 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| ops | p2-loop-all-1 / loop | 18/18 (100.0%) | 18/18 | — | 30.583 / 34.156 (3/3) | 30.505 / 34.094 (3/3) | 4.333 / 5.000 (3/3) | 51210 / 4865 / 2910 / 41728 | 3875 / 5876 (13/13) |
| career | p1-loop-all-5 / loop | 16/18 (88.9%) | 16/18 | correction_four、loop.contacts_once | 32.491 / 44.052 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| career | p2-loop-all-1 / loop | 18/18 (100.0%) | 18/18 | — | 20.185 / 34.050 (3/3) | 20.112 / 33.992 (3/3) | 3.333 / 4.000 (3/3) | 34567 / 3544 / 2047 / 23296 | 3328.5 / 5291 (10/10) |
| service | p1-loop-all-5 / loop | 19/19 (100.0%) | 19/19 | — | 25.937 / 27.416 (2/2) | N/A (0/2) | N/A (0/2) | N/A / N/A / N/A / N/A | N/A |
| service | p2-loop-all-1 / loop | 19/19 (100.0%) | 19/19 | — | 22.261 / 27.831 (2/2) | 22.194 / 27.772 (2/2) | 4.000 / 4.000 (2/2) | 24177 / 2504 / 1602 / 18304 | 3034.5 / 4317 (8/8) |
| design | p1-loop-all-5 / loop | 18/19 (94.7%) | 18/19 | loop.contacts_once | 44.425 / 72.959 (3/3) | N/A (0/3) | N/A (0/3) | N/A / N/A / N/A / N/A | N/A |
| design | p2-loop-all-1 / loop | 19/19 (100.0%) | 19/19 | — | 20.740 / 32.415 (3/3) | 20.659 / 32.349 (3/3) | 2.667 / 4.000 (3/3) | 26902 / 3483 / 2183 / 17920 | 3220 / 4882 (8/8) |
| aipm | p1-loop-all-5 / loop | 10/14 (71.4%) | 10/14 | heading、labels、answers_used、no_repeated_dimension | 25.267 / 25.267 (1/1) | N/A (0/1) | N/A (0/1) | N/A / N/A / N/A / N/A | N/A |
| aipm | p2-loop-all-1 / loop | 10/14 (71.4%) | 10/14 | heading、labels、answers_used、no_repeated_dimension | 36.324 / 36.324 (1/1) | 36.267 / 36.267 (1/1) | 4.000 / 4.000 (1/1) | 8901 / 933 / 600 / 7296 | 2141 / 2984 (4/4) |
| aipm_real | p1-loop-all-5 / loop | 4/16 (25.0%) | 4/16 | common.rounds_complete、heading、labels、real_pains、mcp_decision、adoption_unit_and_owner、no_placeholder、rewritten、no_invented_metrics、depth_within_limit、loop.first_draft_by_turn3、loop.contacts_once | 14.336 / 41.037 (11/11) | N/A (0/11) | N/A (0/11) | N/A / N/A / N/A / N/A | N/A |
| aipm_real | p2-loop-all-1 / loop | 5/16 (31.2%) | 5/16 | common.rounds_complete、heading、labels、real_pains、mcp_decision、adoption_unit_and_owner、no_placeholder、rewritten、no_invented_metrics、depth_within_limit、loop.first_draft_by_turn3 | 18.352 / 48.567 (11/11) | 19.241 / 48.483 (9/11) | 2.667 / 4.000 (9/11) | 85381 / 11643 / 8678 / 58624 | 3466 / 5513 (24/24) |
