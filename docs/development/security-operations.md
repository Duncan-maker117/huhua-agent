# 账号与加密存取运维说明

本说明描述代码的账号、游客和加密存取约定。自动化安全测试使用随机密钥、临时 SQLite、内存邮件运输器和合成资料；实际部署版本与目标环境验证状态见 [服务器交接](2026-10-05-server-deployment.md)。

## 1 安全边界

一个账号对应一个人的资料。`Conversation.owner_hash` 是当前访问权限归属，账号值为 `account:<uuid>`，临时游客值为 `guest:<浏览器凭证摘要>`。当前稿读写先验证账号或浏览器凭证，再检查会话归属；长期历史、档案与产品导出要求账号。请求正文中的 `session_id` 不是授权凭证。

`ResumeSession.owner_key` 是创建时确定的存储绑定，供简历和检查点的认证加密使用。它不随会话认领而改变。认领转移当前目录的访问权限，并按新归属重新加密对应标题和改写建议；保留稳定存储绑定，避免应用数据库和检查点数据库分步重加密时发生中断锁死。旧浏览器即使知道 session ID，也不能绕过新的归属检查。

服务端为了处理资料会短暂解密。这不是端到端加密。数据库字段、磁盘备份、网络传输、访问权限和模型上下文最小化分别承担不同保护责任。操作系统管理员和运行进程权限仍需按生产环境管理。

## 2 配置约定

| 配置 | 用途与约束 |
| --- | --- |
| `APP_ENV=production` | 禁止明文兼容；必须使用 HTTPS 来源和安全账号 Cookie |
| `REQUIRE_ACCOUNT=true` | 生产保持开启；历史、长期档案和导出要求账号，允许独立配置游客体验 |
| `ALLOW_GUEST_EXPERIENCE=true` | 默认开放免登录模板预览、聊天和当前稿编辑；false 可关闭游客体验 |
| `GUEST_RETENTION_HOURS=24` | 游客当前会话默认 24 小时未更新后过期，独立于账号保留期限 |
| `GUEST_DAILY_TURN_LIMIT=20` | 每个游客身份每日生成/核对操作额度，计数持久化，不含聊天正文 |
| `DATA_ENCRYPTION_KEYS` | JSON 对象，key ID 对应 Base64 编码的 32 字节随机密钥 |
| `DATA_ENCRYPTION_ACTIVE_KEY` | 新写入使用的 key ID，必须存在于 keyring |
| `ACCOUNT_SECRET` | 独立、稳定、至少 32 字节的 Base64 随机值，生成邮箱 HMAC 索引和 OTP 校验摘要 |
| `APP_ORIGIN` | 正式应用的完整 HTTPS origin，不含路径，例如 `https://resume.example.com` |
| `AUTH_COOKIE_SECURE=true` | 正式服务必须保持 true；仅本地 HTTP 验证时显式设 false |
| `SMTP_HOST` `SMTP_PORT` | 已授权邮件服务；当前运输器采用 SMTP STARTTLS，默认端口 587 |
| `SMTP_FROM` | 已配置的发件地址 |
| `SMTP_USERNAME` `SMTP_PASSWORD` | 邮件认证配置，通过运行环境注入 |
| `SMTP_STARTTLS=true` | 必须启用证书验证的 TLS，关闭时登录发送不可用 |
| `ALLOW_INSECURE_LOCAL_STORAGE=true` | 仅用于显式选择的本地旧数据兼容，生产忽略；有账号时仍须配置加密 |

密钥由密码管理器、密钥托管服务或受控运行环境注入，不放入源码、前端、数据库、测试报告、终端命令参数或公开日志。数据密钥、`ACCOUNT_SECRET` 和加密数据库备份分别保存，记录恢复责任人及访问范围。本说明没有替操作者生成或落盘正式密钥。

`ACCOUNT_SECRET` 与轮换的数据密钥用途不同，不能直接换一个值当作普通轮换，否则邮箱和档案去重索引无法按旧值定位。它的更换需要单独的索引重建、验证码失效与恢复流程；当前数据轮换命令不会修改它。

未配置邮件时，`GET /api/account/me` 返回 `login_available=false`；登录请求返回 503。产品没有返回验证码的开发后门。测试运输器只存在于独立测试中，不是运行配置选项。

## 3 登录与会话

验证码 10 分钟有效、最多验证 5 次，成功一次即消费。数据库保存验证码的加密密钥摘要、有效期、尝试次数和消费时间，不保存验证码原文；并发验证通过条件更新确保至多一次成功。

发送限额同时绑定邮箱和来源 IP，验证也限制 IP；计数持久化，重启不会清零。邮箱查找使用独立 HMAC 索引，邮箱显示值使用认证加密。登录会话使用随机 token，只保存 SHA-256 摘要，Cookie 为 HttpOnly、SameSite=Lax，30 天到期；退出删除服务端记录并清除 Cookie。部署需只信任已配置反向代理的来源 IP，不能直接信任请求自行填写的 `X-Forwarded-For`。

生产所有 Cookie 写操作必须通过同源检查，拒绝跨站及缺失 Origin 的写请求。正式 `APP_ORIGIN` 独立于请求 Host，防止把攻击者提供的 Host 当作同源基准。当前接口也不接受通过第三方站点触发自动登录或认领。

临时游客使用独立的 `huhua_guest` HttpOnly、SameSite=Lax 会话 Cookie，生产启用 Secure；服务端只用摘要标识归属，不复用旧 `huhua_workspace` 历史凭证。当前稿和图状态仍加密存储，但不为游客写入长期档案。默认 24 小时未更新即不可访问；启动及周期清理同时移除过期会话、checkpoint 和包含正文的改写建议。Cookie 丢失后，不能只凭会话 ID 找回临时内容。

登录成功后，前端调用 `POST /api/account/claim-guest`，凭登录账号、原游客 Cookie 和当前 `session_id` 只认领这一段会话。服务端在会话锁内再次检查归属和过期时间，成功后清除游客 Cookie；同一账号重试可幂等返回，其他账号不能据此认领。认领后的用户消息进入已有档案归档流程，保留来源规则；其他临时对话及旧浏览器历史不会自动迁入。保留期限按当前目录归属判断，因此已认领会话不因原游客加密绑定而过期。退出账号同时清除游客 Cookie，下一次体验使用新身份。

模板和个人当前稿可免登录预览。产品的 PDF / Word 导出入口要求登录；这项产品限制无法阻止用户自行复制可见内容或调用浏览器打印，不构成防复制保护。

## 4 加密范围

数据采用成熟库的 AES-256-GCM，每次写入使用新的 12 字节随机 nonce。认证附加数据包含版本、存储归属、记录 ID 和字段名；密文被复制到别人的记录、另一字段或另一会话时会校验失败。缺少旧密钥、密文篡改或严格模式读取旧明文时明确报错，不静默返回空简历。

应用数据的加密字段包括简历 JSON、简历正文、对话标题、账号邮箱和档案 payload。索引、随机 ID、状态、版本、时间等必要数据库元数据仍可见，不声称整个数据库文件已做全盘加密。

LangGraph 包装器加密完整检查点、完整 metadata 和每个 pending write 的值，并仅向底层 saver 传递路由所需配置。不能仅更换 LangGraph 的 serializer，因为底层 saver 会把 metadata 单独写为 JSON。检查点的 thread ID、namespace、checkpoint ID、静态写通道和任务路由元数据仍是可见索引。包装器的 SQLite 真实 LangGraph 恢复已覆盖测试；PostgreSQL 路径按已安装 saver 接口适配，生产连接、迁移与故障恢复仍须在目标环境验证。

## 5 显式离线工具

工具入口是 `backend/scripts/security_migrate.py`，只能指定源路径和一个尚不存在的目标文件。它从环境读配置，不隐式加载开发者 `.env`，不默认读取真实数据库，不切换运行服务，不删除原文件。目标文件权限为 0600。

```text
python backend/scripts/security_migrate.py check-keys
python backend/scripts/security_migrate.py backup --source APP_COPY.sqlite3 --destination APP_BACKUP.encrypted
python backend/scripts/security_migrate.py backup --source CHECKPOINT_COPY.sqlite3 --destination CHECKPOINT_BACKUP.encrypted --application-state APP_COPY.sqlite3
python backend/scripts/security_migrate.py privacy-export --source LATEST_APP_COPY.sqlite3 --destination LATEST_PRIVACY.encrypted
python backend/scripts/security_migrate.py restore --source APP_BACKUP.encrypted --destination RESTORED_APP.sqlite3 --privacy-state LATEST_PRIVACY.encrypted --privacy-sha256 TRUSTED_LATEST_SHA256
python backend/scripts/security_migrate.py restore --source CHECKPOINT_BACKUP.encrypted --destination RESTORED_CHECKPOINTS.sqlite3 --privacy-state LATEST_PRIVACY.encrypted --privacy-sha256 TRUSTED_LATEST_SHA256
python backend/scripts/security_migrate.py application-migrate --source APP_COPY.sqlite3 --destination ENCRYPTED_APP.sqlite3 --owner-map STORAGE_OWNERS.json
python backend/scripts/security_migrate.py checkpoint-migrate --source CHECKPOINT_COPY.sqlite3 --destination ENCRYPTED_CHECKPOINTS.sqlite3 --owner-map STORAGE_OWNERS.json
```

以上路径是操作示例；应替换为经确认的离线副本。`STORAGE_OWNERS.json` 是 thread/session ID 到已核实存储归属的映射。应用迁移优先沿用已有存储绑定或目录归属；只有缺少归属的旧简历需要显式映射。它不会根据姓名或裸 session ID 自动替用户认领历史。

备份通过 SQLite 一致性备份 API 取快照，在内存中序列化，整体加密后才写备份文件。应用备份自动记录当时的账号、事实版本、失效来源、删除屏障和会话版本基线；检查点备份必须用 `--application-state` 绑定同一维护窗口的应用副本，才能可靠保留不受影响的历史。基线加密并绑定数据库快照摘要，不能把另一份备份的合法基线拼接过来绕过删除检查。

恢复强制要求 `--privacy-state` 和独立可信位置提供的 `--privacy-sha256`。缺失、不匹配、缺少解密密钥、快照比备份更早，均在生成目标文件前失败。恢复先重放隐私状态，再 VACUUM 压实内存数据库，确保写入新文件时没有被删除内容的废页，然后验证完整性。原始数据库若仍有旧明文，恢复出来的旧结构和保留字段仍需继续显式迁移，不能因为整体备份已加密就直接上线。

应用迁移新建目标数据库，并在插入每一行前加密，避免对旧文件原地 UPDATE 后在 freelist/WAL 留下旧正文。迁移检查列值、行数与数据库完整性，兼容旧简历 JSON 的 null 和空正文。旧 `users`、`wrapper_records`、`decode_records` 如果存在数据，或存在未知的非空表，会停止要求单独归属迁移策略，不复制私有明文，也不丢弃资料。

检查点迁移保留 checkpoint ID、父级关系和 pending writes，对每条内容做解密回读校验。两类迁移都会使用 active key 重写；因此也用于已有密文的数据密钥轮换。轮换时 keyring 同时保留旧 key 和新 key，新 key 设为 active。两份数据库均通过恢复与业务回读后，再按备份期限决定何时撤下旧 key，不能先删除还在备份中使用的 key。

## 6 切换与恢复要求

正式操作前先暂停写入，取得同一维护窗口的应用库与检查点库配对快照。工具的一次执行不会提供跨两个数据库的原子切换；操作者需要记录原路径、目标路径、key IDs、文件摘要和迁移结果，再一次性调整服务指向。失败目标保留供排查，但不能切换到未通过校验的文件。

回滚必须恢复配对的数据库与对应密钥，不能仅回滚代码或其中一份库。现在的恢复命令会在目标文件可用之前完成以下动作：

1. 用可信最新隐私快照替换旧备份里的账号和全部档案表，保留当前事实、更正结果、删除 tombstone 和来源失效记录。
2. 对存在事实更正/删除、来源失效或账号撤销的账号，丢弃旧备份中的相关会话及建议；会话归属、正文摘要或版本变化，或会话已删除，也会丢弃对应旧会话。未受影响的其他账号会话可以保留。
3. 检查点恢复使用相同规则删除对应历史 checkpoint 和 pending writes，阻止原始消息或待写入结果把旧信息带回来。没有可靠应用基线的旧检查点备份会清空全部旧对话，并在结果中给出 `discarded_conversations`、`discarded_rows` 和 `recovery_policy`；也可显式传 `--discard-all-conversations` 选择保守清空。
4. 撤销旧登录会话和验证码，清空旧认领导入任务；已丢弃会话的资料来源会禁用并清除原文副本，其档案任务设为 skipped。最新已经确认的档案事实仍保留，可新开对话重建简历。

这是首期保守恢复：受影响账号的旧对话可能整体舍弃，而非只删一个字段；它不声称完整还原旧聊天。必须检查命令输出的保留/丢弃数量、`affected_accounts` 与任务停用数量，再确认是否切换。应用和检查点库分别恢复时，应使用同一可信隐私快照；缺基线导致检查点全清时，应用恢复也建议加 `--discard-all-conversations`，避免保留缺少历史上下文的旧目录。

**最新状态的可信性依赖独立运维锚点。** 每次接受删除或更正后，维护者必须从确认完整的最新应用状态生成隐私导出，并在独立受控位置更新其最新 SHA-256，不能把摘要只放在同一份可回退的旧备份目录。该导出目前是显式离线命令，没有假装已经部署自动外部同步。灾难恢复时如果最新快照或独立摘要丢失、无法确认是否最新，应停止恢复，不可用一个“能解密的旧快照”代替。工具能证明提供的快照匹配这个可信摘要，无法自动证明操作者提供的摘要真的最新；输出明确包含 `automatic_latest_proof=false`。直接拷贝数据库或绕过恢复工具的人工操作也不受本协议保证。

备份保留期限与撤销策略由实际部署配置确定。旧明文源文件、旧备份、浏览器存储和用户自行导出的文件不因加密迁移自动消失；需明确保留位置和清理责任。对真实资料的删除或迁移另行确认后执行。本轮开发没有读取、覆盖或删除真实用户数据库。

## 7 本地验证

运行 `python -m unittest discover -s tests -p test_account_security.py -v` 和 `python -m unittest discover -s tests -p test_backup_privacy_restore.py -v`。覆盖加密随机性与字段绑定、篡改和缺 key、旧 key 读取与轮换、验证码重放/过期/次数/并发、持久限流、Cookie/退出、同源写保护、显式浏览器认领、完整 checkpoint/metadata/pending writes、真实 LangGraph 恢复、应用/检查点新文件迁移与轮换，以及删除/更正重放、受影响账号历史移除、无关账号保留、旧任务停用、摘要缺失或不匹配拒绝、已知过时快照拒绝、基线拼接拒绝、无基线的明确全清。

这些验证不代表邮件送达、公开部署、生产 PostgreSQL、高负载或跨地域灾备已经通过。目标环境仍需验证 TLS、邮件账号、数据库权限、备份期限与恢复演练。
