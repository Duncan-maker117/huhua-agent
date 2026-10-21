# 第十九批 a：简历预览「每句可溯源」

日期：2026-10-22（Asia/Shanghai）。工作树 `huhua-b18a`，分支 `batch19a`，基准 HEAD `99abf96`。本批仅本地修改；没有 commit、push、部署、真实模型调用，也没有启动或访问 8833。

## 已完成

主工作台的 A4 预览现在可以点击要点、技术栈行查看原话、对应岗位要求及待确认说明。新增常驻依据条、按会话保存的开关、待确认项逐条定位；卡片支持引用去重与折叠、草稿安全预填、原有「写简历」定位、键盘关闭与焦点归还。窄屏使用底部抽屉。

### 改动文件

| 文件 | 内容 |
| --- | --- |
| `backend/app/services/resume_workspace.py` | 从校验后的当前元数据生成只读依据索引 |
| `web/index.html` | 依据条、父页面卡片容器；预览交换时接入独立桥接脚本 |
| `web/resume-workspace.js` | 同步已显示稿件与依据；复用 STATUS_LABEL、locate 和输入框草稿逻辑 |
| `web/resume-evidence.js` | 状态统计、会话开关、卡片内容/定位/焦点、消息来源校验 |
| `web/resume-evidence-preview.js` | 仅主工作台 iframe 使用的字段点击、状态标记与定位桥接 |
| `web/resume-workspace.css` | 复用工作台颜色 token、字体及按钮；卡片、toggle、窄屏抽屉和打印隐藏规则 |
| `tests/test_batch19a.py` | 18 项后端、导出基线和前端 DOM 回归 |
| `tests/batch19a.dom.js` | 执行生产控制器与 iframe 脚本的 7 组 DOM 回归 |
| `tests/fixtures/batch19a-render-baseline.json` | 改动前固定 ResumeData、基准提交及 14 份 HTML 的字节哈希 |
| `tests/batch19a.browser.js` | 1440×960、390×844 的合成浏览器验收及截图脚本 |
| `tests/prepare_batch19a_browser.py` | 用真实模板生成浏览器合成数据，输出到临时目录 |
| `batch19a-report.md` | 本报告 |
| `mmr.md` | 仅末尾追加本批交接记录 |

开场已有的未跟踪文件 `docs/development/codex-tasks/prompt-batch19a.md` 保留，未修改。

## 交互方案与边界

采用**仅在主工作台装载 HTML 时注入独立轻量桥接脚本**的方案。核实发现：非 interactive 模板原本也输出 `data-field-path`，项目要点路径为 `/projects/{index}/polished_bullets/{bullet_index}`；其他经历为 `/{section}/{index}/bullets/{bullet_index}`；技术栈已有整行路径 `/{section}/{index}/tech_stack`。因此不需要修改渲染接口、Jinja 模板或编辑器的 `resume-preview.js`。

- 渲染接口及预取缓存仍保存原始 HTML；只在 `canvasBuffer.show` 前装饰当前预览。原有 `applyHighlight` / `highlightBullet` 保留；卡片的 locate 操作在重绘完成后还按字段路径定位，避免技术栈中间的 `<strong>` 标签或重复文案导致找错位置。
- 双缓冲交换后绑定当前 `#live-sheet`，拒绝来自隐藏旧 iframe 或其他窗口的消息。最新 workspace 的版本与已显示稿不一致时暂停依据，避免把新依据贴到旧句子上。
- iframe 只传路径、状态及矩形，不传引文。父页面按 iframe 实际缩放换算位置；优先放右侧，否则下方，视口底部空间不足时向上翻转，卡片内部可滚动。用户滚动页面/iframe、调整窗口、切模板或更新稿件时关闭；卡片内部滚动保留打开状态。
- `<768px` 为底部抽屉，最大 `70vh`（支持时使用 `70dvh`）。Esc、外部点击、再次点击同一要点均关闭；焦点回预览区域。卡片内有键盘循环，Esc 不会同时关闭手机工作区。
- 技术栈沿用整行路径，合并这一行各技术的元数据及引用；其中混有手改项时提示核对。没有拆写模板。
- 统计只计模板实际显示的要点和技术栈行，一行技术栈计一条；确认状态优先，正常有依据的计入「能对上你的原话」，待确认与混合稿中的手改项计入「待你确认」。因此三个数字按互斥状态汇总，不重复计数。点后者从第一条开始，重复点击依次定位。
- 有有效元数据时默认开启；纯手写/旧稿没有元数据时禁用。用户偏好键为 `huhua_resume_evidence:{session_id}`，读写均 try/catch。
- 所有引文、岗位要求、说明按文本节点输出。未知内部代码不直接展示。
- 「在对话里改这句」和「回答这个问题」只预填并聚焦输入框，复用现有 `fillInput`：已有草稿后换行追加，附件和草稿不发送。回复仍在生成时也允许预填。
- PDF、DOCX、非工作台 HTML 与编辑器行为没有改动。依据标记、临时定位标记及父页面依据控件在打印媒体下隐藏。

## evidence 载荷

入口：`workspace.tailor.evidence`。由现有 `tailor_metadata` 生成，因此复用该 helper 的响应也携带同一索引。

```json
{
  "facts": {
    "<fact_id>": {
      "item_id": "<item_id>",
      "kind": "action",
      "text": "规范化陈述",
      "source_quote": "用户原话",
      "active": true
    }
  }
}
```

先调用现有 `valid_bullet_metadata`，再收集有效 `bullets` / `tech_stack` 引用的 ID。手改导致的 `{}` 不贡献引用；无其他有效引用的事实不会下发。缺失 ID 不补造，返回索引中没有该项；被更正/删除但仍被引用的事实保留并标 `active:false`。存储中的真实标识字段是 `facts[].id`，本批也兼容 `fact_id` 键；未显式写 status 的旧事实沿用现有 `active` 默认约定。

新增投影不调用模型、不访问数据库、不修改输入、不写 checkpoint。HTTP GET 的游客分支通过离线桩验证了没有 commit、flush、canonical save 或 `aupdate_state`。现有 GET 中与岗位画像过期修复、账号资料读取相关的旧流程未修改；本结论限定为依据投影没有新增写入行为，不把旧 GET 的其他路径宣称成全局无副作用。

## flags 中文映射

已核对 `backend/app/agents/resume_writer.py` 的三个写作入口：写入元数据的 flags 均只保留 `transferable`。schema 接受字符串数组，所以展示端仍对历史/未知值做兜底。

| 值 | 展示 |
| --- | --- |
| `transferable` | 这句借用了你的相关经历，确认一下这样说是否准确。 |
| 未识别值 | 这句还有待核对的地方，可以在对话里补充或改一下。（不显示原代码） |

`needs_metric` 独立显示「可以补一个数字：{metric_question}」与「回答这个问题」；事实失效显示「依据已更新，待确认」及「你后来更正过这里的说法，建议核对这句」；缺失事实显示「未找到依据」。无原始引文而使用 fact text 时明确标注「整理自你的材料」。

## 隐私规则核实

`build_workspace` 复制工作区 basic_info；`renderExperiences` 直接展示电话、邮箱，当前工作区不对它们新增遮罩。`profile_bridge` 的删除/更正保护是已有数据边界，并非通用联系方式脱敏。本批 source_quote 沿用当前工作区规则，保留用户原话中的原始电话、邮箱；仅下发有效元数据引用到的事实，不附带未引用事实、raw_notes 或整份 collected_info。相应回归使用合成联系方式，验证工作区与引文保留一致。

## 验证结果

- 新增 **18 项**回归全部通过：引用范围、非 active/缺失事实、手改失效、位置洞/重排、只读投影、联系方式规则、游客 GET、HTML 基线及 7 组 DOM 行为。
- 全量命令：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py`。**2352 项：2350 通过、2 项既有跳过、0 失败**（原 2334 + 本批 18）。完整日志：`/private/tmp/huhua-19a-full.log`。
- 定向日志：`/private/tmp/huhua-19a-targeted.log`。DOM 覆盖统计三类情况、storage 失败/会话隔离、三种标记、引用去重折叠/安全输出、岗位状态、中文 flags、未知代码隐藏、技术栈、草稿不覆盖/不发送、流式时预填、关闭/焦点/键盘、待确认循环定位、模板交换和版本错位保护。
- 动手前保存了 **7 个模板 × 普通/interactive 两种模式 = 14 份 HTML**，位于 `/private/tmp/huhua-19a-baseline/`。改后直接执行 bytes 相等比较，**14/14 逐字节相同**；日志 `/private/tmp/huhua-19a-export-bytes.log`。仓库中的固定输入/哈希回归可持续重跑，不依赖该临时目录。
- 所有改动 Python 文件 Ruff 通过：`/private/tmp/huhua-19a-ruff.log`。新增 JS 的 `node --check` 及 `git diff --check` 通过。

## 未完成：真实浏览器视觉验收

没有生成或伪造截图。CLI 启动失败：无法写入 `~/Library/Caches/ms-playwright/daemon/.../huhua-19a.err`（EPERM），日志 `/private/tmp/huhua-19a-browser-launch.log`。补试直接启动本机 Chrome，进程立即 SIGABRT 退出，日志 `/private/tmp/huhua-19a-browser-direct.log`。本轮没有启动应用服务，失败的 Chrome 启动日志也已确认进程退出。

因此 1440px/390px 的真实布局、缩放定位和触屏观感尚未通过浏览器验收；DOM 与 CSS 检查不能替代此项。两个预期截图路径 `/private/tmp/huhua-19a-1440.png`、`/private/tmp/huhua-19a-390.png` 当前均不存在。

Claude 可在具备浏览器权限的环境从仓库根目录重跑（脚本将请求全部拦截到本地文件/合成数据，无需运行后端或访问 8833）：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" tests/prepare_batch19a_browser.py
playwright-cli -s=huhua-19a open about:blank
playwright-cli -s=huhua-19a run-code --filename=tests/batch19a.browser.js
playwright-cli -s=huhua-19a close
```

脚本已写入两种尺寸、桌面卡片不遮挡/不溢出、底部抽屉、模板切换、键盘关闭、草稿预填和打印隐藏断言；因启动阻塞，本轮未执行这些浏览器断言。当前实现的剩余验收项仅此视觉/真实浏览器检查。

## Claude 验收补丁（2026-10-22）

- **真实点击时卡片立即消失（已修）**：卡片打开时焦点从 iframe 回到父窗口，触发 `index.html` 的 `window.focus → refreshCanvas` 重绘，`attach()` 和 workspace 更新随之把卡片关掉。DOM 测试没有真实焦点事件，所以没覆盖到。修法：`HuhuaEvidence.isOpen()`；卡片打开期间窗口获得焦点时不刷新。
- **统计口径**：手动写的要点不算「待你确认」，改为单独显示「N 条是你手动写的」；「待你确认」链接只在 N>0 时出现，循环定位只走 pending。
- **待确认兜底文案**：「这句还有待核对的地方…」只在没有其他具体说明时显示。
- **浏览器脚本**：`run-code` 环境没有 `URL` 全局，补了解析函数；缩放 iframe 内 Playwright 命中测试有误，改为按缩放换算坐标后用真实鼠标点击，并新增 `card-survives-focus-return` 断言。
- 验证：浏览器 16/16 通过（1440、390 截图 `/private/tmp/huhua-19a-1440.png`、`/private/tmp/huhua-19a-390.png`）；DOM 7 组通过；全量 2352 项通过（2 项既有跳过）；`git diff --check` 通过。
