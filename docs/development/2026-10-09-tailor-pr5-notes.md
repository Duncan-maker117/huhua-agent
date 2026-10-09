# PR5 交接（给 Claude 评审）

本地 `overhaul/tailor`，未 push、未部署。半成品 `router.py` / `edit_plan.py` / `interviewer.py` / `advisor.py` 是续写，没有删掉重来。

## P1-7 核实

不是 §3.5 回归。`save_canonical_resume(source=writer)` 不重建事实母版；`test_fact_draft_storage` 仍在。挖经历卡在有文稿时读了 `resume_data` 的 polished bullet，所以「抖音推广」会从卡片上消失，事实还在 `collected_info`。现已改为：有 active facts 时，卡片展示事实原文和 active 技能，文稿继续只用于预览。

## 已接上的行为

- 有稿时的修改走 `route_intents` + `edit_plan`。回复按每个 op 对照实际 diff 写 ✅ / ⚠ / ❌，不再用「调整了 N 段经历」代替未完成的请求。
- 教育句写入 `education` 的 school / major / degree / grade；简称不扩写，并追问全称。更正会 supersede 旧字段。
- 上一条助手问题会传给抽取（不作为引文）。短答里的职责句写成 `kind=role`，同一职责问题不再追问。
- 「出一版 / 先给我出」算生成。尚无经历正文、且已有岗位和至少两条事实时，同一轮出首稿。
- 近重复 bullet（含「频繁/经常」「调用/用」）在 writer 落地前丢掉后一条。
- JD 技能括号短语按词匹配，简历里已有 Agent 不再把整句算缺失。
- 有经历后，读岗位摘要里「只给了 JD / 没有个人材料」会被拿掉。

## 请评审的取舍（规格没写死，没有改成更保守的产品行为）

1. **持久化 stage 仍是 `EVALUATING`，没有改名 `DRAFTED`。** API 交接写明前端用 `has_data`，现有会话和测试也认 `EVALUATING`。行为按「有稿可反复改」实现。
2. **路由模型失败时，能确定经历名称或序号就局部改，否则才整稿。** §4.1 写的超时兜底是整稿。整稿会改到用户没点名的经历，所以有确定目标时不用整稿。
3. **`COLLECTING_*` 和 `triage_chain` 还在无稿追问路径里。** 安全测试把「非候选人材料不得入库」和「公开流式回复」钉在这条路径上。有稿修改、首稿条件和教育/职责绑定不再依赖 triage 的动作名。整段删掉会把这些测试的桩一起拆掉，需要单独评审。
4. **显式 `task=review_resume` 仍走原来的流式 `run_resume_review`。** 取消和半截回复的测试依赖它逐 token 输出。评估阶段里的「请检查」走 advisor，不写正文，并给出「直接按这些改」按钮。
5. **`change_summary` 仍最多 5 条；聊天回复逐条列出全部 op。** §3.4 和 §10.3 在这里撞车，用户可见的是逐条回报。
6. **handson-01 的 truth 是待审，不是 `approved_by_claude`。** 姓名、学校、项目已虚构（江商大 / 途记 / 工坊集）。断言仍是抖音推广和 Claude Code 进稿。原 12 例的审定计数没有改。
7. **lead/keep 没有在超过条数上限时强制塞进每一条已披露事实。** 条数上限仍按 §10.1。未进稿的已披露事实留在事实母版和挖经历卡上，由 handson-01 的覆盖率去抓。

## 这次实测

- 公开：`evaluation/tailor-bench/runs/20261009-pr5-v1/summary.md`。13 例里只有先跑完的 3 例有稿；其余在 JD 或开场遇到模型 `402`。不能当验收。
- 私有：`evaluation/tailor-bench/runs-private/20261009-pr5-real-01/summary.md`。图跑完两轮，6/8 目标通过，求职意向未写成指定方向，页数因本机 WeasyPrint `OSError` 记为未知。语义评分按私有规则未跑。
