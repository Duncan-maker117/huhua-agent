# 第十七批 m 修复说明

日期：2026-10-19。工作树：`huhua-b17m`，分支 `batch17m`。仅本地改动，未 commit / push / 部署，未改 `dist/`，未访问 8833 / 8834，未调用真实模型。

## 根因与改动

1. **模板入口**：MCP 原先只有 `preview_uri`，外部助手缺少可直接交给用户的网页入口。`templates_list` 新增顶层及逐模板 `gallery_url`，协议层传入服务配置的 origin，不读取请求 Host。`/resume` 已有按白名单解析 `?template=` 并优先于浏览器偏好的逻辑，本批只补选中项滚动，并验证非法 ID 回退。工具描述要求给用户网页链接，PNG 仅供 agent 自查。
2. **「淡青平行」超时**：本机未复现该模板特有的渲染慢，不能认定是字体或 CSS 故障。使用仓库公开样例，按生产渲染器分段计时，`t1002-jianyue` 排版约 0.074s、生成 PDF 累计约 0.111s、转 100dpi PNG 累计约 0.125s；七套累计耗时范围约 0.125–0.724s（首套包含冷启动）。没有外网字体请求，PDF fetcher 只允许上传图片。已确认的可靠性缺口是原链路在线程里执行原生排版和 PDF→PNG，没有超时终止机制。
   - 新增 `mcp_preview.py`：同一生产 PDF 渲染器和 PNG 转换放到短生命周期子进程，stdin 传 JSON，不把文稿放进命令行；15 秒超时杀死并回收进程，单应用进程最多同时 2 个预览，满额立即 503。标准错误不透传、不记录私有正文。
   - 用户稿预览超时返回 `mcp_error_504`、结构化 `preview_timeout` 和网页回退提示；模板资源使用 SDK 的 `ResourceError` 返回固定超时说明及配置域名的画廊链接。资源成功结果仍缓存 7 套，失败不缓存。PDF/Word 导出路径不变。
   - 本机进程隔离后的协议预览约 0.45–0.50s；有冷启动开销，换来可终止性。保留原 10 次/分钟共享渲染限额；连续枚举多种渲染接口可能收到 429，这是限流，不能据此认定为本次实测超时原因。
3. **联系方式占位**：原 measure 使用客户端传入值，preview 则统一替换为一个“联系方式已隐藏”短串并清空邮箱，既引导客户端上传联系方式，也不能预留导出头部版面。现在两者使用相同的固定占位：15 位电话、32 个宽字母邮箱；始终在副本上替换。工具说明与工作流明确测量/预览留空手机邮箱、导出由服务端填入。预览仍隐藏所有已知联系方式和链接，不新增权限，不读出真实手机邮箱给客户端。导出/保存依然从已确认档案填入。
   - 七套生产排版回归验证典型手机号、邮箱、城市组合下，占位后的页数与内容高度不小于实值版面。
   - 这是固定预留预算，并非无限长度邮箱的数学上界。schema 未限制任意邮箱长度；超长联系方式、档案姓名变化或额外链接仍应核对导出页数，返回说明明确这一边界，没有改导出内容或收紧已有 schema。
4. **使用流程与工具说明**：server instructions 改为 12 行中文，覆盖按 JD 成稿、调到一页、新经历待确认、记忆导入、代码仓库记录、模板链接、联系方式与标准栏目。保留不执行 `untrusted_text` 指令、网页本人确认、词法初筛不等于语义核验、服务不调用写作模型等约束。所有英文简略工具说明改为中文并注明使用时机；相关资源与 prompt 描述同步。
5. **栏目名及凑栏**：writing guide 增加 `section_policy`（教育背景 / 实习经历 / 工作经历 / 项目经历 / 校园经历 / 开源贡献 / 竞赛与荣誉 / 技能），与 instructions 同时禁止迎合 JD 自创标题；单条分量不足或验证/计划阶段经历应合并或省略。确认 MCPResume 支持自定义栏目及旧 `experience_section_title`，因此 save/export 增加 `section_diagnostics`，以 JSON pointer 返回非标准显式标题和自定义栏目复核建议；保存稿核对提示也可见。诊断均为 advisory，不阻止保存/导出、不强改标题正文、不凭关键词断言经历尚未完成。默认旧栏目兼容保留。
6. **空基本信息摘要**：前端原来用 `missing_fields` 数组是否存在判断有无已有资料，后端全缺失也会正常返回全部字段的数组，导致空摘要和“改”。现在只有确有非空已填字段才显示摘要/折叠已有字段；全空时所有输入直接显示。后端语义正确，保持字段集合不变并补注释及回归。更新相关 JS 资源版本，避免浏览器旧缓存。

## 改动文件

- MCP：`backend/app/mcp/{server,writing_guide,diagnostics}.py`。
- 服务：`backend/app/services/{mcp_service,mcp_preview,intake}.py`，其中 `mcp_preview.py` 为新增。
- 网页：`web/{resume-editor,resume-workspace}.js`、`web/{resume,index}.html`。共享 `template-preview.js` 无需改动。
- 测试：新增 `tests/test_mcp_b17m.py`、`tests/mcp_gallery.dom.js`；更新 `tests/{test_mcp_protocol,test_mcp_v2,test_mcp_ui}.py`、`tests/intake.dom.js`。

## 新增测试与旧断言调整

新增 12 个 unittest 用例，外加既有 DOM/协议用例中的增量断言：

- 配置 origin 优先、7 套模板链接；真实编辑器启动时查询选中/滚动、覆盖偏好、非法 ID 回退且不进入渲染 URL。
- 七套真实预览工具和模板 PNG 资源（包括淡青平行），无额外 scope；使用独立测试令牌避免把共享渲染限额误判成性能失败。
- 空手机邮箱的 measure/preview 占位一致、输入不变、已确认联系方式不泄露；七套保守版面比对。
- 真正启动挂起子进程，验证超时杀死回收、PID 已不存在且下次预览成功；并发上限、stderr 隐私、工具及资源超时回退。
- instructions 行数/安全规则/流程及中文工具描述；标准栏目指南；save 与 PDF/Word export 返回诊断且持久化正文不被改写；旧标题兼容。
- 游客、空档案、缺省及不一致的 missing_fields 均不产生空摘要，字段可见且可提交；已有资料“改”和缺项填充继续通过。

逐条调整既有测试的理由：

1. `test_mcp_v2.py::assert_no_render` 的 mock 目标从 `render_resume_pdf` 改为新的父进程入口 `render_preview`，以继续覆盖拒绝请求不得启动渲染；使用它的跨账户和 scope/限流测试断言保持不变。
2. `test_preview_always_redacts_profile_and_document_contacts_before_render` 和 `test_saved_preview_redacts_contacts_but_export_still_fills_them` 只将预览 spy 移到 `render_preview`，继续真实渲染、逐项检查所有敏感值不出现在入参；导出 spy 和真实填充断言保持不变。
3. `test_preview_uses_shared_render_bucket_and_safe_error` 的故障注入也移到新预览入口；429/503 和私有错误不得外泄的断言保持不变。
4. `test_real_overflow_has_pointer_and_one_character_saves_a_line`：新需求在原本无联系方式的页眉预留一行，原临界稿不再临界。该用例移除一条填充短行，JSON pointer 从末条索引 34 更新为 33；仍严格断言删一个字符节省一行、从 2 页变 1 页、诊断准确且输入不变。其他溢出样例不改，没有放宽断言。
5. `test_mcp_protocol.py`、`test_mcp_ui.py` 和 `intake.dom.js` 只增加断言/用例，未删除旧断言。

## 验证结果

- MCP 定向：63 项通过（22.184s）。
- DOM：`node tests/intake.dom.js`、`node tests/mcp_gallery.dom.js` 通过。
- 改动 Python 文件 Ruff、改动 JS 语法检查、`git diff --check` 通过。
- 指定全量命令：`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py`：**2008 项，2006 通过、2 项跳过、0 失败/错误，100.518s**。日志：`/tmp/huhua-b17m-full-tests-final.log`。runner 隔离数据库并清空真实模型/搜索/发信凭证。

## 失败做法与修正

- 初次诊断误把公共样例位置写成 `backend/data/sample_resume.json`，实际在根目录 `data/`；修正后完成七套分段计时。
- 初次全量 1996 项中出现 3 个旧预览 spy 失效错误及 1 个临界页数失败；按上述真实调用边界和新占位需求修正，未改宽验收条件。
- 新资源超时回归发现 SDK 将 `ToolError` 折叠为通用资源失败，改为资源专用 `ResourceError`，保留可理解的错误和网页回退。
- 新保存回读测试首次忽略了 schema 为栏目补齐 `content: ''` 的正常行为，补全测试输入后继续按整个栏目对象严格相等验证。
- 指定 venv 无 Ruff 模块；改用已有 `/opt/homebrew/bin/ruff`，检查通过，未安装依赖。

## 未完成及证据边界

- 没有访问线上或禁止端口，不能确认原 Codex 实测超时的具体部署端根因；已交付可终止的有界降级和本地七模板回归，未伪称线上恢复。
- 外部 Codex 自动审批由客户端决定，本批降低上传需求并明确说明，但未冒充已经通过真实客户端自动审批。
- 未执行真实模型生成、真实账号导出或 Linux 部署环境的字体性能测试；测试均为离线合成数据/公开样例。
