# 第十九批 a：简历预览「每句可溯源」

仓库：胡话简历。工作树 `~/Desktop/sth/huhua-b18a`，分支 `batch19a`（从 batch18b `99abf96` 切出，已切好）。直接在当前分支改，**不要 commit/push/部署，不要调用真实模型，不要启动或调用 8833 端口**。

## 目标（产品层面）

产品卖点是「不编造、每句话都有出处」，但现在依据只出现在右侧「读岗位」面板的「原句依据」区块（`web/resume-workspace.js` 约 268 行）和「岗位要求 · 你的证据」对照表，用户在简历预览上看不到。本批要做到：**用户在主工作台的 A4 预览上点任意一条要点，就能看到这句话来自自己说过的哪句原话、对应 JD 的哪条要求、还有什么待确认。** 这是面试演示和比赛演示的核心「哇」时刻，交互要做得精致，不要做成调试面板。

## 现状（已核实，动手前自己再确认一遍）

- 要点元数据：`workspace.tailor.resume_meta.bullets[item_id][i]`，与可见要点**按位置对齐**，每条形如 `{fact_ids, req_ids, flags, needs_metric, metric_question, polish, text_hash}`；手改过的要点由 `backend/app/services/resume_versions.py: valid_bullet_metadata` 置为 `{}`。技术栈同理在 `resume_meta.tech_stack[item_id][i]`。
- 字段：projects 用 `polished_bullets`，work_experience/campus/open_source/awards 用 `bullets`（见 `resume-workspace.js: draftBullets()`）。
- 事实：`collected_info` 各经历 `facts[]`，含 `fact_id/kind/text/source_quote/status`（见 `fact_extractor.py` 的输出格式；`status != active` 的是被更正或删除的）。**当前 `build_workspace`（`backend/app/services/resume_workspace.py`）没有把 fact_id → source_quote 下发给前端**，只给了 fact text。
- 岗位要求：`workspace.jd.info.role_profile.requirements[{id,text}]`；匹配状态：`workspace.tailor.match_plan.requirements[{req_id,status,fact_ids,angle}]`。
- 预览：主工作台 `web/index.html` 的 `#live-sheet` iframe（`sandbox="allow-scripts"`），通过 `POST /api/resume/render/{template}` 获取 HTML，**目前是非 interactive 渲染**，没有加载 `web/resume-preview.js`。编辑器页 `web/resume.html` 用的是 interactive 渲染 + `resume-preview.js` + `data-field-path`（要点路径形如 `/{section}/{index}/bullets/{bullet_index}`，projects 的路径以模板 `_macros.html.j2` 实际输出为准）。
- 现有「定位」：`index.html: applyHighlight / highlightBullet`，通过在 HTML 里插 `<mark>` 实现。

## 要做

### 1. 后端：下发依据索引（只读、不调模型）

在 workspace 载荷（`tailor_metadata` 或 `build_workspace`，选改动最小且语义合适的位置）新增 `tailor.evidence`：

```json
{"facts": {"<fact_id>": {"item_id": "...", "kind": "action", "text": "规范化陈述", "source_quote": "用户原话", "active": true}}}
```

- 只包含当前有效 bullet/tech_stack 元数据实际引用到的 fact_id，不要把整个 collected_info 下发。
- 被引用但已非 active 的事实：`active:false`，前端显示为「依据已更新，待确认」。被引用但找不到的 fact_id：不进 facts，前端按「未找到依据」处理。
- 联系方式、隐私：如果现有聊天展示/工作区对电话邮箱有脱敏或保留规则，source_quote 遵循**工作区**的同一规则（工作区当前保留原始电话/邮箱），不要新造规则；在报告里说明你核实的结论。
- 游客会话同样可用（数据就在当前会话里）。
- GET workspace 不得因此写库、不得改 checkpoint。

### 2. 预览可交互（仅主工作台预览）

- `#live-sheet` 需要能识别「点了哪条要点」。可以复用 interactive 渲染的 `data-field-path` 和 `resume-preview.js` 的 postMessage 通道，或新增一个专门的轻量模式，你选改动最小、风险最低的方案并在报告说明理由。
- **硬约束**：PDF / DOCX 导出、编辑器页 `resume.html` 的现有行为、非工作台渲染输出**完全不变**（写测试：同一份数据，导出用 HTML 渲染结果在改动前后逐字节一致）。打印媒体下任何依据标记都不显示。
- 预览双缓冲（`canvasBuffer`）、模板切换、`highlightBullet` 定位、预取都要继续正常工作。

### 3. 交互与视觉（这是本批重点，按下面规格做，不要自由发挥成别的样子）

**a) 预览上方的依据条（常驻）**
- 位置：live-sheet 上方、模板切换区附近，一行。
- 内容：`查看依据` 开关（toggle，带 aria-pressed）+ 一句统计：`12 条要点 · 10 条能对上你的原话 · 2 条待你确认`。没有任何元数据时（如纯手写、旧会话）显示 `这份稿是手动编辑的，暂无可追溯的原话`，开关禁用。
- 「待你确认」那段文字可点击：打开依据模式并依次定位到第一条待确认要点。
- 开关默认：当前稿存在任一有效元数据时默认开启；用户手动切换后存 localStorage（键带 session id，读写都 try/catch）。

**b) 依据模式下的 A4 标记（克制，A4 必须保持干净可读）**
- 三种状态：
  - **有依据**（有 fact_ids 且至少一条能解析到 active 事实的 source_quote 或 text）：平时不加标记；悬停时浅紫背景 + 虚线外框（沿用 `resume-preview.js` 现有的 #8b5cf6 样式），光标为手型。
  - **待确认**（flags 非空，或 needs_metric，或引用的事实非 active / 找不到）：琥珀色波浪下划线（`text-decoration: underline wavy #d97706`，偏移 3px，粗细 1px）。
  - **手动编辑**（元数据为 `{}`）：不加标记，可点击，弹层说明「这句是你手动改的，没有关联原话」。
- 技术栈行同样可点（用 tech_stack 元数据），状态规则相同。
- 依据模式关闭时：预览完全回到现状（点击无弹层、无任何标记）。

**c) 点击要点 → 依据卡片（在父页面渲染，不在 iframe 里）**
- 定位：iframe 把被点元素的 rect 发给父页面，父页面按当前缩放比例换算后，卡片出现在要点右侧或下方，不遮挡该要点，不超出可视区；滚动或窗口尺寸变化时跟随或关闭（选一种，行为一致即可）。
- 宽度约 320px，白底、1px `#e5e7eb` 边框、圆角 12px、轻阴影；字号与工作台面板一致，与现有 `resume-workspace.css` 的配色和字体保持一致（先读这些 CSS，复用已有 token/类名）。
- 内容自上而下：
  1. 标题行：`这句的依据` + 状态胶囊（`有原话依据` 绿 / `待你确认` 琥珀 / `手动编辑` 灰）。
  2. `你说过的`：每条事实一个引用块（左侧 3px 竖线，引号内为 source_quote；没有 source_quote 时显示事实 text 并标注「整理自你的材料」）。去重；超过 3 条折叠为「再看 N 条」。
  3. `对应岗位要求`（有 req_ids 才显示）：每条一行，岗位要求原文 + 状态小标（直接证据 / 可迁移，沿用 `STATUS_LABEL`）。
  4. 待确认说明（待确认状态才显示）：needs_metric 时显示 `可以补一个数字：{metric_question}` + 按钮「回答这个问题」；事实非 active 时显示「你后来更正过这里的说法，建议核对这句」；flags 用人话翻译（先查 flags 的实际取值集合，给出中文映射，未知 flag 不显示原始英文代码）。
  5. 底部操作：「在对话里改这句」（把 `把这句改一下：「{要点原文}」` 填进聊天输入框并聚焦，**不自动发送**，保留已有草稿时先确认或追加到末尾——按现有输入框的草稿保护逻辑处理）；「定位到写简历」（复用现有 locate）。
- 关闭：Esc、点卡片外、再次点击同一要点。打开时焦点移入卡片，关闭后焦点回到预览区域；卡片 `role="dialog"`、有可读的 aria-label。
- 窄屏（< 768px）：卡片改为底部抽屉（bottom sheet），最大高度 70vh，可滚动。

**d) 文案语气**：口语、短句，和产品现有文案一致；不出现 fact_id、req_id、flag 等内部字段名。

### 4. 不做的事
- 不改写稿/抽取/编排逻辑，不改 prompt，不改模板 j2 的导出样式。
- 不做「一键补缺口」重写（下一批做），本批「回答这个问题」只预填输入框。
- 不动 `resume.html` 编辑器页的点击定位行为。

## 测试

- 后端：evidence 只含被引用的事实；非 active / 缺失 fact_id；手改要点后元数据失效对应的事实不再下发；游客会话；GET 不写库。
- 导出不变：同一份 ResumeData 在多个模板下，PDF 用的 HTML 渲染改动前后逐字节一致（先在改动前生成基线再比较，或在测试里对照非 interactive 渲染）。
- 前端 DOM 测试（参考 `tests/*.dom.js` 现有写法）：统计文案三种情况；开关状态与 localStorage（含 localStorage 抛错）；三种状态标记；点击 → 卡片内容（引用、岗位要求、待确认说明、flags 中文化、未知 flag 隐藏）；「在对话里改这句」不自动发送且不覆盖草稿；Esc/外部点击关闭与焦点归还；依据模式关闭时点击无卡片；模板切换后标记与卡片仍正确。
- 浏览器尺寸：尝试用现有 `tests/*.browser.js` 方式跑 1440px 与 390px 两个尺寸的截图到 `/private/tmp/huhua-19a-*.png`；若本机权限不允许启动浏览器，在报告里如实写明，不要伪造（Claude 会另行做视觉验收）。
- 全量：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py`，基线 2334 全过，改后必须全过；改动的 Python 文件 Ruff（`/opt/homebrew/bin/ruff`）、`git diff --check` 通过。

## 报告

写 `batch19a-report.md`（仓库根目录）：改动文件清单、预览交互方案的选择与理由、evidence 载荷格式、flags 中文映射表、隐私规则核实结论、测试数与日志路径、未完成或不确定之处。另在 `mmr.md` 末尾追加一节简短记录（不要改写已有内容）。
