# 第十四批 c2：真实回放故障复现与回放器加固

2026-10-17。只在当前 worktree 修改；没有 commit、push、部署、真实模型调用或访问 8833/8834。`runs/after-b14c/`、`runs/after-b14b2/` 只读，91 个原产物文件 SHA-256 前后相同。

## tech：丢失发生在 writer 之前

`after-b14c/tech/01-initial.json` 中不仅 `resume_data.work_experience` 为空，`workspace.experiences.items`、`fact_coverage.facts` 和已验证的 `confirmed_plan.experience_plan` 都没有云舟科技。计划仅剩校园二手交易系统的 keep；“实习主线型（实习 lead + 课程项目 keep）”是残留的模型方案 label，不是实际保留的计划条目。实习事实不存在，所以后续 item 润色找不到栏目，170ms 更正也找不到事实。

**可复现的根因是抽取漏掉整段经历时，确定性主体恢复只支持带标签/编号的经历，不支持本轮这种连续口述。** `explicit_subject_spans` 没有建立云舟科技身份；`_cover_dropped_clauses` 找不到事实归属，留下三条 uncovered，而不是恢复可供 writer 使用的事实。

对照实验：使用真实首轮输入，抽取桩只返回课程项目和教育，将旧主体函数与修复后的函数分别接到同一抽取链。旧函数产生空实习，以及与真实产物完全相同的三条“没有记下来”：实习公司/职务、订单接口职责、12 条测试。新函数恢复云舟科技、日期、团队、导师、测试环境、420/170ms、12 条测试和联调，uncovered 为空。日志：`/private/tmp/huhua-b14c2-root-cause.log`。

**不能把这次失败归因于某个已确认的 14c writer 改动。** 原产物未保存原始 extractor 响应及其逐项拒绝详情；漏抽、未知 item_id 或事实被拒导致身份丢失，无法从现有文件进一步唯一判定。上述旧主体函数在本轮开始时未修改，与 HEAD 相同，缺口早于本批；14b2 成功说明那次模型结果完整，不证明确定性恢复能处理漏项。14c 反向蕴含检查发生在 writer 后，不能解释事实母版和计划本身没有实习；`delivery_date_repair` 仅用于最终交付指令；project heading 也不负责创建/删除事实母版中的实习。桩复现定位的是可验证故障路径，未冒充真实模型调用栈。

修复位于事实入口：

- 明确的“在某公司做/当/任某岗位”先建立主体、角色和事实归属，再逐条接收/校验材料；不是在空正文上回填整段原话。按句界、下一公司和具名项目截断归属，排除未来计划、否定及第三人经历。
- 该主体范围内的团队、工具、导师、索引、联调、压测等短子句参与现有事实覆盖检查；原有限定、数字校验和日期字段恢复继续生效。
- writer 原有逐条 guard/repair 路径保留。新增最终交付核对：lead/keep 条目无可用正文或隐藏时，`writer_diagnostic.undelivered_items`、回复变更说明及 `verification_notes` 都点名说明，不把整段缺失掩饰成普通备用信息。

新增 `Batch14c2TechTests.test_real_input_missing_extractor_item_reaches_writer_and_correction` 使用真实输入和原计划的配置/意图（原产物的实习 ID 已不存在，按本轮事实 ID 绑定 lead/keep）。writer 桩包含 plain/labeled 要点、标题/日期/正文混合引用、日期独立行、项目定位，以及故意违规的一条要点。验证整段实习、限定与数字仍在，日期只在字段，违规只影响该要点，170→190ms 更正保留 420、12、4。另测无法成稿必须明示、第三人/计划拒绝、同句公司和项目切换不串归属。

## 为什么离线五人物 71/71 没发现

`tests/persona_support.py::golden_data/golden_turns` 预先给定完整正确简历；`tests/test_persona_runner.py` 的 HTTP 桩直接返回这些数据，并不经过真实抽取器或 writer。71/71 证明回放器与断言能处理预制成功稿，不能证明应用从材料生成了成功稿。

另一个真实代码链测试的 `fixture_patch('tech')` 也总是返回云舟科技和完整职责，`PersonaModel/EchoWriter` 主要逐事实照写，语义桩默认通过。它没覆盖“整段实习未进入抽取响应”，也没覆盖真实 writer 的混合引用和不完整输出组合。新回归主动删除抽取桩里的实习条目后再走真实抽取/事实恢复/writer/更正链，能抓住这个缺口；没有改五人物原断言来放过缺失。

## aipm：动态卡片、实际答案与成稿门槛

答案库按 `ask_user.question_dimension` 组织，覆盖 tech_stack、decision、iteration/badcase、evaluation/eval、status、links、problem、my_work；补共享维度对 eval、评估、仓库的识别。链接/现状回答“公网可访问的链接”。按实际选项及保守同义归一匹配；无对应选项但允许“其他”时提交自填值，不照抄未选选项。无对应合成素材答 unknown。

`aipm.replay` 按当前 guidance 继续提交 ask_user / 经历清单 / 基础信息，绑定实际 turn_id 和 item_id；方案卡出现才发送其“按推荐写”值。确认后若仍无成稿且有新卡，会继续答。首轮之后最多 6 轮，达到上限发送一次“直接写”，记录 `depth_limit_exceeded`，单独断言 `aipm.depth_within_limit=fail`，即使后来成稿也不抹掉该失败。已验证成稿后停止，不被成稿后残留的补充卡无限拖住。

全部正文质量断言先要求成稿：EVALUATING/EXPORT、revision、writer 完成或已确认方案，以及当前项目正文与非空事实引用/hash 完整对应；预览 revision、仅选方案、过期 metadata 均不足以通过。使用最终轮，不借早先成功稿掩盖后续丢失。

答案入稿从实际提交过的非 unknown、非 skipped 值计算，至少 3 项，不足 3 项则全部；去重后用有限、可检查的同义规则匹配正文。不会因模型没问技术栈而硬扣一项。旧日志没有 answers payload 时，按前一张卡的真实题干从 input 提取实际答案，不用现有答案库反推历史回答。无虚构数字只允许实际答案里的数字，题干或 unknown 中的数字不能授权成稿数字。标签断言同时拒绝“迭代：评测：”这种重复标签。

### 真实文件与任务描述有一处差异

冻结目录的 `05-basics_confirm.json` 已发送“按推荐写”，stage=EVALUATING，存在 confirmed_plan、`writer_diagnostic.status=model_completed`、有事实引用/hash 的 `polished_bullets`。因此完整五轮不是“从未进 writer”。回复仍说“开写前”，且 description 保留收集原话，确实容易造成该判断；本批没有把这份已成稿产物硬判成未成稿。

测试从原文件复制必要字段到 `tests/fixtures/batch14c2-replay.json`，不改原产物：

| 桩/冻结数据 | 新断言 | 依据 |
| --- | --- | --- |
| 真实第 1–4 轮（只有预览/方案） | 2/9，交付及全部 6 条正文质量均失败 | 没有 writer 成稿 |
| 真实完整 5 轮 | 8/9，labels 失败 | 已成稿，但含“迭代：评测：” |
| 相同真实问答卡、正确 writer 成稿桩 | 9/9 | 动态答 links、实际答案入稿、完成交付 |

静态重评日志：`/private/tmp/huhua-b14c2-aipm-audit.json`。这些数字是冻结产物重评和桩结果，不是修复后真实模型回放通过率。

## 收集预览与成稿的边界（本批不改）

`resume_graph._serialize_to_resume_data` 的 `_active_item` 把 active facts 的 text 经轻量清理后拼成 `description`/`bullets`；结构化回答现在直接成为事实，因此“现在已经上线”“换模型或调参数”会出现在收集预览。它尚未执行 writer，不代表润色结果。

`web/resume-editor.js` 和默认 `t001-jianyue.html.j2` 优先显示 `polished_bullets`，为空才显示 description；DOCX 也采用这一优先顺序。真实第 1–4 轮没有 polished_bullets，用户右侧自然看到接近原话的描述；第 5 轮虽然 description 仍在，默认成稿视图应显示 writer 要点。**这是“要点照搬原句”的一个明确可能来源，但不能证明所有该反馈都来自预览。** 另有旧模板（例如 `t003-jianyue.html.j2`）直接渲染 description，边界并非所有模板完全一致；本批按要求不改预览或模板。

## 验证与边界

- 新增 12 个测试；与原 14c 定向测试合计 **37/37 通过**，日志 `/private/tmp/huhua-b14c2-targeted.log`。
- 最终全量 **1780 项，1778 通过、2 项原有私有样例跳过、0 失败，73.163s，退出码 0**。执行命令：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib '/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python' scripts/run_tests.py`。最终日志 `/private/tmp/huhua-b14c2-full-final.log`。
- 本批独立修改文件 Ruff 与 `git diff --check` 通过；现有 14c 未提交改动保留。原始回放 91 个文件 hash 核对未变。
- 只验证桩与本地确定性链路。没有宣称修复后 deepseek-flash 的 tech 已恢复 17/17；新问题题干的任意语义匹配仍受合成答案库与保守规则限制。
