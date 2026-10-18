# 第十六批 a 修复说明

日期：2026-10-18。工作分支：`batch16a`。范围：规格 A / B / C / D；不含 E 记忆导入。

## 根因与修复

### A：基本信息档案优先

原链路把档案当作表单预填来源，未把“档案已有足够基本信息”当作完成状态；联系方式同时被 intake 白名单排除，因此模板虽然支持手机、邮箱，却收不到数据。

- `prepare_graph_context` 确定性沿用基本信息、第一条教育、手机、邮箱和链接，保留当前简历已填写的值，并记录档案绑定。姓名 + 学校 / 专业 / 学历任一满足时，basics 标为 `from_profile`，不再出现基本信息卡。
- 第一次公开回复附带“已沿用档案”回执，进度标志防止逐轮重复；只有问候的新会话也更新简历预览。
- 部分缺失时只展开缺项，已有值显示只读摘要和“改”。新增可选手机、邮箱；到岗时间文案为“到岗 / 可实习时间”，提示“找实习再填，全职可留空”。
- 手机、邮箱只参与确定性存储、投影和用户界面。没有修改 `model_privacy`、`ContactTokenStream` 或 MCP PNG 联系方式占位机制。七个模板已有头部渲染能力，无须改模板文件。

### B：档案质量、迁移与失败分类

原抽取器没有基本信息字段的语义校验，基本信息 subject 不统一；结构化表单消息仍可能被模型整体解释，同一冲突也会按不同 subject / 来源重复建立。

- 新增共享确定性校验：基本信息统一为“本人”；location 中的 URL / 邮箱 / 手机转入相应字段；姓名拒绝 URL、邮箱和含冒号的键值串；字段值拒绝吞并已识别的其他键值。手动编辑和冲突替换同样校验。
- “基本信息：键：值……”按中文 / 英文别名拆分，教育字段归入教育；归档 worker 对这种消息跳过模型抽取。基本单值按归一化值合并，链接允许多个不同 URL，同一当前修订的重复冲突不再新增。
- 新增按账号运行的幂等迁移：清理错误 location、拆分混合 availability、合并重复基本事实和冲突；旧事实保留为 `superseded`，不硬删除。调用入口覆盖档案读取、投影及归档。迁移后的 ID 必须提交事务再供后续调用使用。
- worker 记录 `phase=read_source/model_call/write_archive` 和异常类型名，不写异常正文或用户内容。新增 `archive_model_error`、`archive_decryption_error`、`archive_database_error`；保留超时、预算、修订冲突和无效响应分类及重试入口。

线上 4 条旧 `archive_unavailable` 的确切原因不能从现有状态码恢复。本批未访问线上数据库或日志，也未调用真实模型。可解释这些旧状态的代码路径包括模型网络 / 鉴权 / SDK 异常、密钥配置或密文解密异常、数据库锁或完整性错误；新日志和分类使再次失败时可辨别这些情况。完整 DB 不可用时，写入失败状态本身也可能失败，此时依赖安全日志和已有租约恢复，不能保证立即显示新状态码。

迁移恢复：仅在隔离测试数据库执行过迁移。上线前应按现有运维方式保留数据库快照；需要恢复时优先停写并还原快照。逐条修复可参考旧行的 `migration_previous`（原 slot / status）、新行的 `migration_from`、冲突的原绑定及保留 payload，但必须同时核对来源合并和投影引用，且暂停迁移入口，避免读取时再次迁移。没有新增数据库表或部署脚本。

### C：从档案选择经历

原 intake 的经历阶段只识别本会话 collected_info，不提供档案目录，因此老用户仍看到空白必填行。

- 目录按经历主体聚合，显示名称、类型、日期、短摘要；模型可见目录先脱敏。已知岗位按词重叠与类型排序，最多预选三条正相关经历；未知岗位不预选。
- 有目录时不自动创建空白行，点击“再加一段新的”才展开。无档案的新用户继续使用原表单，也可在聊天中讲述。
- 复选项经服务器重新验证归属，再按 fact IDs 进入 `prepare_graph_context` 共用导入路径；保留每条事实的 profile_refs 与投影绑定。拒绝失效或别人的 ID。档案已提供的职责、技术、状态等维度不重复追问。

### D：对话工具与 returning 回放

原公开回复只有本轮素材，无法读取账号经历；事实遗漏检测又把“看看我的经历有什么能用”当作未抽取事实。

- 为登录且有档案内容的会话绑定 `read_profile`、`use_profile_items`。读取最多三十条目录并返回基本信息完整度，导入沿用 C 的路径；导入名称由确定性回执展示。
- 解析流式分片及完整工具调用，追加工具结果后继续生成回复，最多两次工具后续轮次，支持 read → use → 回复。工具结果中的联系方式仍经统一模型边界脱敏。
- 查询档案的请求不进入“这句没记下来”；真实经历陈述仍保留原事实检测。工具导入结果显式合并进图状态、预览和持久化，不只停留在回复文本。
- 新增合成老用户 `returning`：预置基本信息、教育、两个开发项目及一段校园经历。首句固定为规格中的请求，随后明确岗位、导入、生成草稿。人物数据只在 evaluation / tests，不写入系统提示词或岗位手册。

## 改动文件

| 文件 | 用途 |
| --- | --- |
| `backend/app/services/profile_basics.py`（新） | 基本信息别名、拆分、校验与 subject 归一 |
| `backend/app/agents/profile_archivist.py` | 确定性表单归档、抽取写入校验 |
| `backend/app/services/profile_service.py` | 合并、迁移、联系方式投影、provenance、错误分类 |
| `backend/app/services/profile_bridge.py` | 基本信息沿用、目录状态、共用经历导入 |
| `backend/app/services/profile_tools.py`（新） | 目录、排序、工具执行、一次性回执与状态提交 |
| `backend/app/services/intake.py` | 部分缺项、可选联系方式、选择经历、已知维度 |
| `backend/app/agents/public_reply.py` | 工具绑定、解析与有界后续回复 |
| `backend/app/agents/resume_graph.py` | 查询路由、表单选择导入、遗漏误判修复 |
| `backend/app/services/candidate_language.py` | 正常档案请求分类 |
| `backend/app/services/ask_user.py` | 基本信息表单描述 |
| `backend/app/api/resume_changes.py` | 导入读取时提交迁移，稳定后续引用 ID |
| `web/resume-workspace.js` | 缺项表单、摘要编辑、联系方式、档案复选目录 |
| `web/account-profile.js` | 到岗时间名称 |
| `evaluation/persona-ux/returning.py`（新）、`run_persona.py` | 人物预置、回放步骤、检查、运行参数 |
| `tests/test_batch16a_profile.py`（新） | 十八项离线回归 |
| `tests/intake.dom.js`、`test_batch14b_intake.py`、`test_p1_profile_welcome.py`、`test_profile_archive.py` | 新 DOM 行为及被规格替代的旧预期 |

`web/index.html` 已具备 intake 传输接口，未改；未改 CSS、dist、部署脚本、写作 / 槽位 / 校验链路和 E 的入口。

## 验证

新增十八项 Python 回归覆盖：完整 / 部分档案；七模板联系方式及到岗时间留空；已知 / 未知岗位排序；确认两条经历及 provenance；不重问已有维度；工具分片与完整调用；访客无工具；真实 LangGraph 配离线模型读档案、导入、写稿；结构化表单跳过模型；字段校验与跨来源去重；截图形态脏数据的账号隔离 / 幂等迁移；同事件冲突唯一约束；安全错误日志与重试；合成人物账号初始化；正常请求分类；runner 的参数、预置、回放与 fixture hash。

其中 HTTP 回归使用 ASGI、临时 SQLite 和现有安全 checkpointer，分别验证新会话问候 / 档案请求的 SSE 回执、七模板投影相关基础数据、SQL 保存及回读、导入事实引用和模型消息脱敏。所有模型为离线桩；没有连接 8833 / 8834。

最终全量命令：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

最终全量：`Ran 1979 tests in 81.871s — OK (skipped=2)`，即 1977 通过、0 失败；两项跳过是已有私有 tailor bench fixture 缺失（`cases-private/real-01.json`）。最终日志为系统临时目录中的 `huhua-b16a-final-tests.log`，未把调试产物或凭证加入仓库。

另外通过：`node tests/intake.dom.js`、两个改动 JS 的 `node --check`、`git diff --check`，以及新增 / 改动 Python 的 Ruff 检查（`test_batch14b_intake.py` 除外；该文件原有第一行 import 位于模块文档之前导致十条 E402，本批未移动原代码）。

## 旧断言逐条调整理由

1. `test_batch14b_intake.py` 的完整档案用例：原“仍有确认基本信息卡且卡内无联系方式”改为“无卡，basics=from_profile”。这是 A 明确替代的行为。
2. 同文件 schema 用例：原拒绝 phone 改为验证可选 phone 被接受；空经历名、空经历列表及非法月份仍拒绝，没有放宽其他校验。
3. 同文件账号 prefill 用例：原整个预填状态无联系方式改为基本信息含正确手机 / 邮箱；原整个状态不可有项目改为项目仅在目录、不进入自动基本信息投影。保留他人资料隔离，并继续检查学校和毕业时间；实际投影另由新增图 / HTTP 回归覆盖。
4. `intake.dom.js`：原 phone / email 输入框数量为零改为二，增加到岗时间提示及提交 payload 断言；增加摘要“改”和经历复选交互。
5. `test_p1_profile_welcome.py`：原整个状态不能含经历资料，改为 `collected_info` 仍无自动导入项目，同时目录包含该项目。C / D 要求目录可见，未取消“未选择不自动写入简历”的断言。
6. `test_profile_archive.py` fixture 查找：basic subject 预期统一为“本人”；多个链接按 value 找到确切条目，避免误取另一链接。这对应 B 的 subject 归一和多个有效链接共存。
7. 同文件模型失败用例：`archive_unavailable` 改为 `archive_model_error`；重试、幂等及错误详情不泄漏断言仍保留。

## 调试中失败的做法与修正

- 仅改变基本信息自动完成条件，会使旧“必须出卡 / 不得有联系方式”断言失败。按 A 逐条替换预期，同时增加真正的投影与隐私测试，没有把失败断言简单删除。
- `subject_ids=[]` 若按 falsy 处理，会意外退回默认 basic 查询。现在区分 None 和空选择，空选择不导入任何事实。
- 迁移在未提交的读取事务内产生新 ID，会在后续投影 / 归档时引用回滚后的事实。读取迁移后提交，并在查找显式 ID 前迁移。
- 同事件的旧重复冲突直接改指向同一个 fact，会违反唯一约束。现在先检测碰撞，保留旧行并标 superseded。
- subject 统一为“本人”后，链接显示文字仍可能是 GitHub；旧失效过滤按两者不相等跳过，导致已删除链接留在预览。基本信息按类别 / 字段 / 值处理失效，保留既有删除回归。
- 初版工具导入先持久化成 self 来源，节点返回时才把档案查询标成非本人事实，同一消息随后以另一来源类型保存而触发 `source_id_reused`。现在调用工具前确定来源分类；新增 HTTP 回归要求 saved=true、SQL 回读及引用存在。
- 不把联系方式写入通用事实文本数组，避免额外增加模型提示中的原始联系方式来源；确定性 basic_info 投影仍完整，原有隐私测试继续执行。

## returning 的后续真实回放

交给 Claude 在单独的本地回放服务运行。服务需已初始化隔离 SQLite；runner 和服务使用相同的加密 / 密钥配置；禁止指向生产环境或真实用户数据库。`REPLAY_DB` 指向该隔离数据库的绝对路径，例如服务运行在 18888：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" evaluation/persona-ux/run_persona.py --base http://127.0.0.1:18888 --persona returning --returning-db "$REPLAY_DB"
```

runner 会新建随机合成账号、预置人物档案、生成两小时测试会话，并在开始聊天前通过 `/api/profile` 核对服务读到同一份预置资料。凭证只留在内存 cookie jar，不通过邮件 OTP、不保存明文 token。缺少数据库参数会在聊天前拒绝运行；结果目录记录 fixture hash。反复回放会在该隔离库新建不同合成账号。

## 未完成与边界

- 真实模型是否稳定主动 read → use、推荐质量与最终文案尚未验证，按分工由 Claude 回放。
- UI 仅做可用结构和语义 class；视觉整理由 Claude 接手。
- 线上四条旧失败的确切根因及存量迁移结果未验证，需要实际环境日志 / 数据库证据。
- E 记忆导入由另一个 worktree 实现，本批未触碰。
- 未 commit、push、部署，未访问 8833 / 8834，未调用真实模型。
