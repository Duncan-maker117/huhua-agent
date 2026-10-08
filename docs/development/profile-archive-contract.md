# 个人档案实现与接入契约

更新日期：2026-10-05。对应产品报告 P2 及项目审视修复。本说明记录本地实现，不代表生产数据已迁移、真实模型质量已验收或线上已发布。

## 数据与安全

`PersonalProfile.account_id` 唯一，一个账号一个档案。个人事实、偏好、来源原文、冲突内容、岗位名称与事实引用、任务详情、失效排除标记均以 `DataCrypto` 密文保存；明文列只保存随机 ID、稳定分类、状态、修订号和时间。事实槽位使用独立账号密钥 HMAC 索引，数据加密密钥轮换不改变去重结果。

事实始终标记 `source_type=user_provided`，不冒充外部核实。档案 API 的 `expected_revision` 指事实修订号；冲突卡片绑定的是原事实修订号。共享档案写入同时通过 `PersonalProfile.revision` 的数据库条件更新串行化；更正、删除和岗位改名另有记录级条件更新，不能由过期页面覆盖。

账号认证、CSRF、稳定加密密钥必须就绪。即使允许旧匿名本地数据不加密，新增个人档案仍拒绝明文保存。

## 持久事件

调用方在成功保存用户输入的 SQL 事务中执行：

```python
enqueue_archive_event(
    db, account_id, source_id=human_message.id, session_id=session_id,
    event_type="human_message",
    payload={
        "human_text": user_text,
        "source_kind": "self",
        "collected_info_delta": {"basic_info": basic_fields_from_this_input},
        "subject_ids": selected_fact_ids,
    },
)
# 由调用者和业务资料一并 commit；函数不自行 commit。
```

`source_id` 必须是可靠保存的消息或编辑事件 ID，同 ID 内容不可变。`event_type` 为 `human_message`、`manual_fact` 或用户认领后使用的 `claimed_history`。`source_kind` 为 `self`、`manual`、`jd`、`reference`、`ai`、`unknown`；后四种不自动写事实。表单改字默认属于当前简历，只有明确请求归档才登记 `manual_fact`。

正常情况下来源与任务原子提交；`compensate_archive_events(db)` 修复持久来源有记录、outbox 缺失的旧接入情况，不凭未提交的图状态恢复事实。任务通过数据库租约抢占，过期租约可恢复；失败退避，自动最多尝试 5 次，之后由用户重试。重放消息不会生成重复事实，重复提及只增加来源与最后提及时间，不提高真实性或事实修订号。

后台调用 `await process_pending_events(session_factory, extractor, limit=10)`；`make_archivist(llm)` 返回兼容现有 structured-output 的异步提取器。模型调用发生在数据库事务外，回写前重新检查来源禁用、租约及修订。任务调度由应用 lifespan 负责；服务函数本身不暗示存在调度器。

生产接线必须传 `budget_reserver=lambda account_id: reserve_turn('account:' + account_id)`，在每次实际提取调用前消耗账号持久配额。用户重试同样检查预算，429 记为 `budget_exhausted`，自动重试推迟到下一个 UTC 配额日；账号 ID 只给配额服务，不送给模型。测试可注入替身或省略该 hook。

模型未配置时仍可调用 `process_pending_events(SessionLocal, extractor=None)`：确定性基本字段先保存，自由文本事件继续显示 `failed/model_unavailable`，不能把未解析项目当作已完成。相同无模型配置下后续扫描跳过这些任务，不消耗重试次数；传入可用 extractor 后自动继续。显式手工 `confirmed_facts` 全部通过校验的任务可以离线完成。

## 提取与上下文

确定性路径只接收本轮原话中存在的基本信息值，或显式手工确认的 `confirmed_facts`。模型输出经过受限 schema、本人归属、原文证据和时间校验；未、仅、计划等限定不能被短引文裁掉，岗位要求、他人信息、假设和 AI 建议不收录。档案模型的整个出站请求通过 `ContactRedactor` 脱敏，包括用户原话及项目描述、项目名称内嵌的手机号和邮箱。响应只在本地还原同一次调用的占位，再对原始资料验证 literal evidence；来源 ID 与档案 ID不送给模型。临时表达要求不作为长期偏好。

提取器只读取默认基本资料、长期偏好、用户选择的事实，以及本轮明确提及的项目对应记录。未知时间留空；迟到的旧事件不能覆盖新更正，较早的有效状态可保留在用户可看的历史中，但不进入日常模型上下文。无依据的“更正”操作标签降级为冲突提案，不能静默改写。

`get_context(db, account_id, subject_ids=[fact_id, ...])` 是显式导入协议，返回 `facts` 和 `fact_refs`。默认无 IDs 时仅返回非联系方式的基本事实和长期偏好。项目必须选择后导入当前简历。`context_to_collected_info(context, current)` 按原 schema 填空、合并选中项目，保留当前手动编辑；偏好不写成个人经历。

连续导入的岗位引用由 `merge_job_version_import(db, account_id, session_id, fact_refs)` 在同一个 canonical 保存事务中合并：保留用户岗位名称、有效的已有引用和新引用，同一事实去重并使用本次修订。过期旧引用移到 `outdated_refs`，持续保留 `stale` 提示；仅凭重新选择一条事实不能证明所有旧简历表述都已核对，因此该 helper 不自动清除原有风险提示。

## 更正 删除与旧副本

事实更正会建立旧值失效标记，禁止旧源消息再次归档，相关岗位版本标为 `stale`。删除事实清除事实正文与档案来源副本，保留不含正文的事实槽位墓碑。旧任务或重新导入旧聊天不能恢复它；用户在档案里明确重新填写则可建立新修订。

`get_projection_guard` 返回源消息禁用 ID、事实 ID、修订、类别、所属经历、字段及旧值排除资料，只能在服务端使用。`sanitize_projection(db, account_id, projection)` 返回清理副本与是否发生清理，供历史续聊、checkpoint、canonical、预览、保存与导出统一执行。普通旧值按主体和字段范围匹配；英文词边界避免 Go 误伤 Google，完整联系方式另外处理空格、括号和中国手机号国家码。复杂 LangChain 消息应由调用方用消息 ID 和 content 适配此接口。

实际从档案填入教育、工作或项目字段时，条目得到稳定 `item_id`；对应事实 ID、修订和字段映射保存在已有 `ProfileJobVersion.payload.projection_v1` 加密字段，不能由客户端提交事实映射。已有手工字段若没有被档案填入，不建立虚假的引用。条目改名、移动或改措辞不会改变关联；更正或删除原事实时，关联字段被清理。只改当前稿不会自动更正全局档案。

保存当前稿和未保存预览都校验稳定 ID，丢弃、重复或换成其他会话 ID 会被拒绝。删除整个关联条目必须明确提交 `removed_item_ids`；条目删除后仍保留服务端映射的删除标记。旧内容没有稳定 ID 和字段映射时，只能使用主体、字段和句子的保守检查；任意改名改写的历史内容不能完整追溯，不根据旧文本编造新值。

为了过滤没有 fact_refs 的旧副本，失效表仍保留加密的最小旧值排除 token；该 token 不作为档案事实展示，不进入模型。这属于“删除档案并禁止未来使用”，原始聊天是否同时清除是独立操作。备份恢复必须先重放最新的墓碑、失效与来源禁用记录，再开放读取和后台任务；具体保留期限仍属于部署前待确定项。

## HTTP 接口

前缀 `/api/profile`。所有接口要求登录，变更请求检查来源。

| 接口 | 参数与含义 |
| --- | --- |
| GET `/api/profile` | 返回 profile_id、revision、facts、preferences、conflicts、jobs、archive_status、import_status |
| POST `/facts` | category、subject、field、value、可选 effective_at；来源由服务器标为手工输入 |
| PATCH `/facts/{id}` | value、expected_revision、可选 effective_at |
| DELETE `/facts/{id}` | 查询参数 expected_revision |
| POST `/conflicts/{id}/resolve` | choice 为 keep、replace、custom；expected_revision；custom 另传 value |
| POST `/tasks/{id}/retry` | 仅重试本账号未完成且来源有效的任务 |
| POST `/jobs` | session_id、name、可选 fact_refs；校验对话归属 |
| PATCH `/jobs/{id}` | name、expected_revision |
| POST `/context` | fact_ids、可选 include_contacts；仅返回本账号选中事实 |

记录不存在或不属于账号返回 404，过期修订返回 409，无效资料返回 422，安全配置或存储不可用返回 503。错误内容不包含原文或底层异常详情。

`import_status` 单独显示认领历史的 pending、running、failed、completed 计数与本账号任务的 session_id、status、attempts、error_code、reason_type，不包含聊天正文。它与 `archive_status` 的逐消息归档任务不同，客户端不能把历史导入的 session_id 传给归档任务重试接口。

`archive_status.tasks` 同时提供 `reason_type`、中文 `message` 与 `retryable`。模型未配置和当天额度耗尽时提示等待可用条件，客户端应显示说明并隐藏无效的重复重试按钮。

个人简历的 `PUT /api/resume/current` 接受 `removed_item_ids`（默认空数组，最多 300 个）。个人预览与导出需要 `session_id` 查询参数并校验会话归属：`render/{template}?interactive=true` 验证未保存表单及重复查询参数 `removed_item_ids`；非交互渲染（打印 PDF）和 Word 导出读取服务端已保存的当前稿。前端必须先完成保存再正式导出。账号模式没有会话时只允许原始服务器样例，样例编辑需先新建个人草稿；显式本地免账号模式保留旧的任意正文渲染行为。

## 隔离验证

`tests/test_profile_archive.py` 使用虚构资料、临时 SQLite、真实 AES 和模型替身。覆盖账号隔离、密文与错误绑定、同一来源不可变、业务回滚、重复幂等、来源边界、事实冲突及旧卡片、显式更正、时间状态、删除期间任务并发、过期修订、任务超时重试、租约恢复、补偿、限定上下文、岗位引用、10 组来源质量子例及联系方式最小化。固定案例通过不等于真实模型在任意材料中都准确。
