# Huhua Agent 交接

## 目标
本轮修复 iPhone 首次聊天输入框不可达，以及首页进入后多次后退问题。用户要求只本地修改并写 handoff，不推送、不部署。上轮上下文压缩待 Claude 审查。

## 已完成
- 上轮基于最新 batch19a/6fdae0a；原代码已推 origin/batch19a，上下文策略已推 codex/context-memory/7125db9。原聊天目录 overhaul/tailor 是旧代码，没有覆盖。
- 上下文策略：完整有效经历、原始引文、否定/分工/测试限制与未覆盖原文；工具后刷新，旧撤回来源禁止重新入库；输入超限明确停止并保留已完成更新。详细设计见 docs/development/2026-10-22-context-memory.md。
- 本轮移除 h-screen/100vh 冲突，VisualViewport 同步工作台可见高度/偏移，输入常驻底部，消息与问题卡内部滚动；手机16px输入、安全区留白、短键盘视口适配，不丢草稿和阅读位置。
- 修复模板预览 iframe 的 srcdoc 导航增加联合历史：脱离DOM更新后原位挂回，保留 sandbox 与双缓冲，空帧不重复重置。主/编辑器资源版本均更新。
- 新增手机布局及后退浏览器回归；更新模板预览DOM回归。

## 未完成
- 本轮尚未提交/推送/部署，全部在工作树未提交差异中，含3个新增文件。
- 实体 iPhone Safari/Chrome 复核；Claude 审查；上下文策略真实模型长对话验收；合并发布均未执行。

## 失败做法
- 只看原聊天目录会误判最新代码；接手必须先切正确工作树。
- 标签 body 的100dvh覆盖不了类h-screen；仅改dvh不够，键盘还需VisualViewport。
- 单独fixed输入区会破坏消息占位；约束整个工作台并保留flex滚动。
- 隐藏iframe也参与浏览器历史，改顶层replaceState无效；需消除子frame导航历史。
- 上下文只留最近几轮/前三句会丢限制；仅在提示隐藏撤回记录挡不住工具重新抽取。

## 关键决策与理由
- 手机视口更新不主动聚焦/滚动；scale不为1时不跟随重排，允许用户缩放。
- iframe保留DOM元素和opaque sandbox，仅重建子浏览上下文，保持既有双缓冲协议。
- 本轮仅前端，测试覆盖实际布局/点击、历史导航和相关DOM行为，不重跑无关后端业务。

## 当前状态
- 工作树：/Users/yikuaibanz1/.codex/worktrees/huhua-context/huhua agent
- 分支 codex/context-memory；HEAD7125db9（已推的上轮）。本轮web/tests/mmr未提交，未push，未部署。
- 验证：手机WebKit/Chromium各19检查；导航两引擎各5检查；模板DOM12、嵌入编辑3、重复操作12通过。均合成API，键盘/工具栏几何模拟，不冒充实体机。
- 上轮全量2403项：2401通过、2跳过；本轮未重新声明该全量结果。
- 用户指定 handoff 已追加到 /Users/yikuaibanz1/Desktop/sth/huhua agent/handoff.md（原文保留，最新小节含准确代码位置与复现）。旧交接归档在mmr-archive.md。

## 接手步骤
1. 到上述工作树核对git status，读取handoff最新小节；git diff审本轮，新增文件也要读。
2. 上轮上下文差异用git diff 6fdae0a...7125db9；本轮测试命令在新增browser.js文件头。
3. 先审实现和实体手机体验；按用户新的明确指示决定提交/合并/部署。

## 进行中记录
- 2026-10-23：在 huhua-rel 保留 Claude 未提交改动，完成工具上限回归及空对话过滤/复用；has_messages 沿现有加密状态保存，旧会话按状态和更新时间兼容。浏览器历史/游客验证通过，全量复跑中；不提交、不推送、不部署。

## 2026-10-23 工具次数与对话生命周期收尾（huhua-rel）
- 工作树：`/Users/yikuaibanz1/.codex/worktrees/huhua-rel`。保留开场已有 Claude 未提交改动；未 commit、push，未操作 deploy。
- 工具循环保持 7 次模型 / 6 步工具；预算相关回归改用常量并实际耗尽预算，保留最后一轮禁用工具、卡片附加、协议回退/DSML 不重放等断言；新增收尾系统提示不含额度耗尽文案测试。
- 无 session 的 /chat 默认打开空对话；显式 session 和刷新恢复原对话，继续仅用 replaceState 写 URL。当前空对话的新建按钮不重复请求，并保留未发送输入。后端复用本人的有效空对话、隐藏无消息且无简历的记录，提交即标记，生成失败也能保留历史；标记随加密状态和 canonical 保存保留。旧记录按状态/时间戳保守兼容。静态版本 `20261023-lifecycle`。
- 验证：`.venv/bin/python scripts/run_tests.py` 共 2410 项，2408 通过、2 个既有私有材料测试跳过（115.343s），无失败；浏览器共 198 检查：生命周期 Chromium/WebKit 各 38、导航各 5、历史模拟 43、游客登录衔接 28、真实 SQLite/API 历史 14、Claude 原有简历持久化 27，全部通过。Node 语法检查及 `git diff --check` 通过。
- 边界：使用隔离临时数据库及合成内容，未调用真实模型，未核验线上旧库、PostgreSQL 多进程并发或实体 iPhone。后续发布前可复核这些环境；本轮无需新增数据库字段或迁移。

## 进行中记录
- 2026-10-23（huhua-rel，AI 导入与批量确认）：查明 import-memory → propose_to_inbox → /api/account/mcp/inbox 共用队列是逐条确认根因。主动导入改为明确内容直接入档，归一化重复跳过，冲突/uncertain/空占位待确认；加密保留 evidence 与批次，支持单条更正/删除和批次撤销（仅本批新增，后续更正保留）。新增 /api/profile/confirmations/batch，逐项 revision、savepoint 和失败结果；前端全选/分组选、批量确认/不要、准确红点；旧导入队列保留来源识别。排除导入来源被旧后台补偿重新入队，无数据库迁移。静态版本 20261023-memory-batch。全量 2422 项：2420 通过、2 既有跳过（111.928s）；真实临时 SQLite/API/MCP 浏览器 Chromium/WebKit 各 35 项，含 99 条单请求、部分失败、撤销、更正/删除及 390px 布局；99 条混合单测为 60 直接/15 uncertain/10 冲突/14 重复。保留 Claude/上轮 Codex 未提交改动，无 commit/push/deploy。未核验线上实际 99 条数据、真实模型自然语言提取、PostgreSQL 多进程或实体手机；不确定标记采用规则识别。

### 2026-10-23：quality-18d 简历质量修复（本地）
- 当前分支 codex/quality-18d；完成合并重复、技术栈源头过滤、联系方式/日期/PR 短写、口语与重复短句预检、假修改收据、已答维度过滤及七模板标题换行。原始事实不改写，合并来源、引用撤回及撤销快照均有回归。
- 旧代码虚构复现：合并请求附带一页约束时只执行 set_constraint，返回 unchanged 并保留 7 条经历；当前实际合并为 3 条，重复执行才返回 unchanged。模型改述不能授权删除/合并。
- 验证：全量 unittest 2429 项，2427 通过、2 项原有跳过，0 失败/错误；新增质量回归 25 项，含七模板实际 PDF 坐标和前端 DOM；git diff --check 通过。新夹具/文档使用虚构身份及 example.invalid 联系方式。
- 未 commit、未 push、未触碰 deploy；未调用真实写稿模型或验证线上登录会话。语义近义项目、未知中文技术名仍采用保守规则。接手先看 docs/development/2026-10-23-quality-18d.md 的根因、完整文件清单及复现边界，再审未提交差异。

### 2026-10-23：quality-18e 检查工具、只读预算与写稿超时（本地）
- 承接 quality-18d 全部未提交改动；注册无参数 check_resume，复用确定性预检返回十类结构化问题，不修改稿件/事实。write_draft 与 edit_resume 成功（含 partial/unchanged）后保存 resume_meta.precheck 并返回 counts；已清理的日期、联系方式、PR 链接不重复报错。
- 清单绑定 data_hash 与 context_hash；现有 GET /api/resume/current 及 SSE meta 的 workspace.tailor.resume_meta.precheck 可直接读取，正文/JD/事实变化后标记 stale 并清空旧问题。核对页新展示未做。
- read_jd/read_profile/check_layout/check_resume/search_company/use_skill 不计业务次数；同轮相同有效参数复用结果，不重放状态更新。写稿/改稿自动检查会更新 check_resume 缓存。移除收尾 DSML 重试突破模型硬上限的例外；MAX_MODEL_CALLS、MAX_TOOL_STEPS 数值未改，预算回归引用常量名。
- WRITE_DRAFT_TIMEOUT_SECONDS 默认 150 秒，其余工具及编排模型 90 秒；CHAT_TIMEOUT_SECONDS 默认 360 秒，loop 的有效整轮预算取 max(配置值, 写稿超时+180)，兼容旧 150 秒配置（有效 330 秒）。写稿超过 60 秒只记一次耗时/经历条数 warning，无正文。内部写稿单次 60 秒、事实校验 45 秒、压缩保真 30 秒保留。
- SSE 增加 15 秒注释心跳，保持断连后完成与显式取消语义；前端写稿进度保留等待秒数，虚拟时钟到 180 秒不误报失败、不 abort，随后能接收最终回复。仓库 Caddy 未配置响应/流超时，Uvicorn 的 5 秒 keep-alive 只在响应结束后计时；未修改 deploy/，未探测线上宿主反代/CDN。
- 验证：全量 `.venv/bin/python scripts/run_tests.py` 2452 项，2450 通过、2 原有跳过，0 失败/错误（109.531 秒）；新增 Quality18E 回归 23 项；git diff --check 通过。首轮四处失败均为旧预算/skill 回执/unchanged 元数据断言，已按新契约更新。
- 边界：标题长度是风险提示，真实溢出仍由 check_layout 测量；JD 缺口依据字面匹配和有效事实引用，不承诺理解所有近义表达。未调用真实模型、未验证线上会话；本地 AGENT_MODE 仍为 off，测试显式启用 loop。未 commit、未 push、未部署；接手查看 tests/test_quality_18e.py 与本轮未提交差异。

- 2026-10-23 15:00（18f）：修复标题卡名称原样落库、两位年份解析失败后转普通要点的两个根因；新增 experience_fields 确定性规范化入口，覆盖卡片、record_facts、档案/整稿导入和事实存储，统一名称去口语与已有经历合并、YYYY.MM/至今日期、角色表达；source_quote/19a 溯源保留原话，无法解析的日期进入字段待确认并最多补问一次，不落 bullet。写稿提示、oral_phrase 和既有改写/降级同步约束“原话是依据不是成品”，不扩张事实或参与程度。新增 29 项回归（含原样三答、日期表驱动、同名合并、导入撤销、原话溯源、失败重问、旧数据无 ID 兼容）；旧代码原样复现 3/3 失败，最终全量 unittest 2481 项通过（2479 通过、2 跳过，113.654s），git diff --check 通过。相对日期按录入时 Asia/Shanghai 日期解析；未做真实模型/线上验证。保留此前未提交改动，未 commit、push 或触碰 deploy。

### 2026-10-23（18h）：疑似重复先问用户、混合 JD 消息、空洞引导句（huhua-rel）
- 疑似重复：笼统抱怨（「有重复」）不再借 names_similar 合并，只处理确定重复（同档案条目/名称归一后相同）；点名共同名称（如「合并重复的 mtagent」）或点名两条才合并。edit_resume 在质量类请求后若仍有疑似对（排除已确认「不是」与已关闭的题），经现有 ask_user 返回确认卡（题 id `dup-…`，选项「是，合并成一条」/「不是，分开保留」），无改动时结果 status=needs_confirmation 带 candidates，不删任何条目；合并后条目数异常减少（非 merged_items 解释）则拒绝并不改稿。答案由编排器代码直接处理（duplicate_answer_update）：是→confirmed_pairs 合并并入新版本（可撤销），不→collected_info.distinct_experiences 记一对 ID，check_resume/后续合并均不再提。
- merge_conflicts/merged_items 在 valid_bullet_metadata 中随实际状态清理（被并入条目重新出现在稿中即作废）；check_resume 的 role_conflict 只对仍存在合并的条目。
- read_jd：消息含 JD 正文关键词且去掉链接后有 ≥30 字时直接解析全文，忽略候选人材料里的链接；仅链接消息保持读链接/multiple_urls。
- 空洞引导句：candidate_language.without_empty_lead_in；non_fact 视单独引导句为非事实，strip_oral_prefixes/clean_prose 统一用它，事实抽取 validated() 去引导句只留冒号后具体内容。
- 旧 18d 四个测试把「笼统抱怨合并相近名称」当契约，已按新契约改为点名请求（并将 mtagent 单点名的预期由 3 改 5 条）。新增 tests/test_quality_18h.py 15 项。全量 2536 项，2 跳过，0 失败（128s）；git diff --check 通过。未调用真实模型、未验证线上；未 commit/push/deploy。边界：确认卡仅 AGENT_MODE=loop；「PR PR #6」重复前缀属既有 compact_code_links 小瑕疵，未动。

- 2026-10-23（18h 续）：①疑似重复确认卡改为系统保证：本轮用户原话是质量抱怨且有未处理疑似对（已证明重复的不问）时，check_resume 自动附系统 dup 卡（结果 confirmation_attached=true，不 stop）；ToolContext.duplicate_card 记录已附；同轮模型再调 ask_user 问重复（提示含重复/同一项目/合并且非 dup- 题）则返回 duplicate_card_already_attached，若尚未附卡则直接改用系统卡；edit_resume 见已附卡则不重复出卡，返回 needs_confirmation。系统提示同步。②read_jd 根因：真实消息 JD 用「职责：/要求：」无「岗位职责/任职要求」，_has_jd_text 不命中，上轮的判断只覆盖带前缀关键词的夹具，_source_parts 也拆不出，于是 3 个不同 URL 走读链接分支；现 _source_parts 增加「同一段内含 职责：与 要求： 行标签」的 JD 段落拆分（其余段落归候选人），read_jd 只解析 JD 段，候选段留给 record_facts。新增 4 项测试（真实原文夹具、check_resume 附卡、模型自编卡被系统卡取代并答「不是」写 distinct_experiences、已附卡后 edit 不重复）。全量 2541 项，2 跳过，0 失败（117s）；git diff --check 见回报。未调用真实模型。
