# PR8 P2：栏目与数据保真验收

日期：2026-10-11。分支：`overhaul/tailor`。仅实施 B1–B4，保留已提交的 P1；未实施 P3/P4，未 commit、push 或部署。

## 根因与结果

- **B1**：抽取、档案、writer 与 canonical 没有开源栏目，编辑操作也不能移动条目，导致贡献被塞进项目并沿用错误标题；列表完整性依赖模型输出，漏掉第二条后没有补救。新增 `open_source`，每个 PR 独立条目，按仓库名作标题，显式列表按原话补齐；`move_item` 保留条目 ID、正文、事实绑定和历史。
- **B2**：没有结构化荣誉类型，档案与输出链路缺少接收位置，部分导入别名只能进入旧 certificates。新增 `awards`，按名称、级别/名次、可选时间存取，多条奖项分别保留；旧 certificates 保持兼容。
- **B3**：抽取校验丢弃 `fact.field`，确定性教育解析不识别“专业紧接本科”及日期区间，education overlay 又只重建字段、漏掉正文中的奖学金；HTML 本来就有专业/学历/日期的渲染槽位，主要损失发生在上游，旧 Word 固定槽位还有额外截断。页头虽然曾接受 github，但 canonical/schema/模板/Word 没有完整出口；现在保留学校、专业、学历、起止时间，奖学金统一为 `education.highlights`，并贯通 links/availability。
- **B4**：原 fact guard 比较数字、技术词与职责，不比较数字的计量单位/对象；“20 次调用”没有新增数字，因而漏检。writer、抽取与修复提示词约束原单位，词法 guard 检查人/次/个/条以及调用/请求的替换，失败回退原事实。

## 数据与兼容性

- `ResumeData.open_source`、`awards`、`BasicInfo.links`、`availability` 均有空默认值，新字段为空时不改变旧序列化字段集合。
- 使用已有会话 JSON、加密档案 category/field 和服务端 projection payload；没有新增 SQL 列、表或 schema 版本，`security_migrate.py` 无需改动或执行。
- 同仓库多个 PR 的导入、重导入和编辑器事实绑定按仓库名 + PR 区分，不合并不同 PR 的 ID。
- 用户明确移动栏目时，服务端更新该 ID 的栏目注册，保留旧栏目历史及正文来源绑定；普通客户端不能凭空挪动有绑定的条目。
- 旧会话没有新字段仍可载入；当前手工栏目的顺序、标题、隐藏状态和删除行为继续生效。
- 所有新增测试仅用示例学校、StarBoat/CloudNote、example.test 等虚构材料以及 fake/mock 模型；未读取或打印 `.env` 凭证，未真实调用模型。

## 验证

macOS 本机已有 Pango 库，运行时使用既有库目录，不修改环境配置文件：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/run_tests.py
```

结果：**1106 项，22.109 秒，全部通过，无跳过**（P1 后基线 1073 项，本次新增 33 项）。

新增测试覆盖：模型只收第一条的补齐、同仓库多 PR、参考材料排除、教育完整字段及奖学金、无冒号个人主页、active facts 到 writer、遗漏 PR 原文回退、单位替换拦截、纯栏目纠正不调用 writer、混合移动与精简、P1 advice 只读边界、加密档案存取、显式档案导入/保存/重新读取、移动后的失效传播、旧 schema、六款 HTML、真实 PDF 文本及两种 Word 路径。

原有 TLS 测试在本沙箱不能监听端口；测试夹具仅在 `PermissionError` 时用已连接的 socket pair 替代最低层 TCP 拨号，仍运行真实 HTTPX、TLS 握手、SNI、证书验证、错误证书拒绝及 gzip 正文读取，生产联网实现未改。

改动 Python 的 Ruff、编译、前端 JS 语法、`git diff --check` 通过；Ruff 延续原有 E402 例外，并单独排除 `resume_limits.py` 已存在的两个未使用 import。

## 逐文件说明

路径均相对仓库根目录。

| 文件 | 改动说明 |
|---|---|
| `backend/app/schemas/facts.py` | 定义新事实栏目及各栏目结构字段白名单。 |
| `backend/app/schemas/editor.py` | 增加 canonical 开源/荣誉条目与可选页头字段。 |
| `backend/app/schemas/writer.py` | 允许 writer 返回开源贡献条目。 |
| `backend/app/agents/fact_extractor.py` | 保留结构字段、页头链接及单位，并逐条补齐显式列表。 |
| `backend/app/services/candidate_sections.py` | 新增保守的原话栏目、PR/奖项及页头解析器。 |
| `backend/app/services/candidate_material.py` | 批量导入新栏目并保留完整教育与页头字段。 |
| `backend/app/services/resume_facts.py` | 贯通编辑器与 active facts，区分同仓库不同 PR 的事实身份。 |
| `backend/app/agents/resume_graph.py` | 序列化新字段、保留导入身份并承接移动后的事实和版本。 |
| `backend/app/agents/resume_writer.py` | 写入开源条目，确定性保留教育/荣誉/页头并约束原单位。 |
| `backend/app/agents/router.py` | 增加移动计划的路由合同并保持 P1 建议意图只读。 |
| `backend/app/agents/turn_actions.py` | 补齐教育解析，识别显式移动并保留其他独立编辑请求。 |
| `backend/app/services/edit_plan.py` | 实现经原话授权的 move_item、标题修正及正文保留。 |
| `backend/app/agents/tailor_pipeline.py` | 支持开源编辑范围并正确记录确定性移动的前后版本。 |
| `backend/app/services/fact_guard.py` | 检出相同数字被替换为不同计量单位或调用/请求对象。 |
| `backend/app/agents/profile_archivist.py` | 增加新档案类别、结构字段、逐 PR 归档和来源核验。 |
| `backend/app/services/profile_service.py` | 支持新档案存取、显式投影及页头链接失效清理。 |
| `backend/app/services/profile_bridge.py` | 让新栏目参与事实失效和旧历史清理。 |
| `backend/app/services/canonical_resume.py` | 将新栏目纳入编辑器的 canonical 事实桥接。 |
| `backend/app/services/session_store.py` | 持久化新栏目并注册服务端明确执行的条目移动。 |
| `backend/app/services/resume_provenance.py` | 保留移动条目的服务端身份、旧栏目与正文绑定。 |
| `backend/app/services/resume_versions.py` | 将新栏目纳入文档差异及 bullet 元数据校验。 |
| `backend/app/services/resume_limits.py` | 让开源条目保留已有贡献范围和状态限制。 |
| `backend/app/services/resume_sections.py` | 将开源贡献与竞赛荣誉加入默认栏目。 |
| `backend/app/services/resume_workspace.py` | 在聊天工作区展示新栏目且不追问其项目角色/时间。 |
| `backend/app/services/resume_review.py` | 文本预览和核对内容包含新栏目及页头，认可开源经历。 |
| `backend/app/services/renderer.py` | 支持新栏目可见项并校验可点击链接的协议。 |
| `data/jianlimoban/html-template/_macros.html.j2` | 共用页头链接、实习时间与新栏目渲染及编辑字段路径。 |
| `data/jianlimoban/html-template/t001-jianyue.html.j2` | 接入开源贡献与竞赛荣誉共用渲染。 |
| `data/jianlimoban/html-template/t002-jianyue.html.j2` | 接入开源贡献与竞赛荣誉共用渲染。 |
| `data/jianlimoban/html-template/t004-jianyue.html.j2` | 接入开源贡献与竞赛荣誉共用渲染。 |
| `data/jianlimoban/html-template/t1000.html.j2` | 接入开源贡献与竞赛荣誉共用渲染。 |
| `data/jianlimoban/html-template/t1001.html.j2` | 接入开源贡献与竞赛荣誉共用渲染。 |
| `data/jianlimoban/html-template/t1002-jianyue.html.j2` | 接入开源贡献与竞赛荣誉共用渲染。 |
| `backend/app/tools/resume_data_docx.py` | 输出新栏目、链接、实习时间及开源日期。 |
| `backend/app/tools/docx_template_filler.py` | 固定模板不能容纳新字段时使用完整的结构化 Word 导出。 |
| `web/resume-editor.js` | 增加新栏目和页头字段的显示、编辑、新增、删除与稳定 ID 管理。 |
| `web/account-profile.js` | 增加档案类别、字段选项及中文标签。 |
| `web/resume-workspace.js` | 展示开源正文、荣誉及页头信息。 |
| `tests/test_p2_data_fidelity.py` | 新增 28 项虚构材料/fake-model 的 B1–B4 回归。 |
| `tests/test_p2_profile_fidelity.py` | 新增 5 项加密档案、保存读取和来源失效集成回归。 |
| `tests/test_resume_sections.py` | 更新默认八栏目的期望。 |
| `tests/test_writer_schema_structure.py` | 更新包含开源类型的 writer schema 期望。 |
| `tests/test_web_research.py` | 让原有真实 TLS 测试在禁监听的沙箱保持原验证强度。 |
| `tests/resume_p2.browser.js` | 提供针对虚构 P2 资料的手工浏览器回归场景，尚未运行。 |
| `docs/development/2026-10-11-pr8-mainline-flow.md` | 追加 P2 的本地实施和验证记录。 |
| `docs/development/2026-10-11-pr8-p2-verification.md` | 记录根因、兼容性、验证证据、逐文件说明和限制。 |
| `mmr.md` | 更新当前 P2 状态及后续审阅边界。 |

## 剩余问题与边界

- **浏览器交互尚未验收**：Playwright 默认缓存目录不可写，改用临时目录后 Chrome 又被沙箱终止；浏览器工具禁止 `file:` 协议且明确不允许绕过，已停止尝试。现有证据是 HTML 字段路径、实际 PDF/Word 内容和 JS 语法检查，不能称为浏览器点击验收通过。
- 未运行真实模型或写作质量 benchmark，因此本次证明离线数据保真和边界，不代表线上真人试用效果或所有自由格式材料的抽取成功率。
- 旧会话中已丢失且没有保留原始来源的资料无法凭空恢复；没有批量重写旧档案或旧稿。
- 当前公开的六款 HTML/PDF 模板支持新字段；未启用的旧模板未扩展，重新启用前需补齐。
- 旧 DOCX 的固定示例槽位遇到新栏目/完整教育字段时采用统一 Word 排版，而非原二进制模板样式；内容保真由回归验证。
- P3 定方案、B6 主线取舍和 P4 老用户快速路径按用户范围保留未实施。
