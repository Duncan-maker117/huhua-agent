# 邮箱验证码接通与免费额度保护

本说明对应 2026-10-04 的本地实现。应用保留自己的账号、验证码和会话逻辑，外部邮件服务只负责投递验证码。无需为了发送邮件另换一套账号数据库。

## 使用 Resend HTTPS（本次本机接通方式）

本机的 SMTP 587 连接探测出现断开，因此本次改用官方 HTTPS 发送接口。账号、验证码、加密和应用额度逻辑不变，只切换发信运输器。代码默认 `EMAIL_PROVIDER=smtp` 保持旧部署兼容；本次运行环境显式配置为 `resend`：

```dotenv
EMAIL_PROVIDER=resend
RESEND_API_KEY=<仅在服务端本地填写 sending-access API key>
RESEND_FROM=onboarding@resend.dev
AUTH_EMAIL_DAILY_LIMIT=90
AUTH_EMAIL_MONTHLY_LIMIT=2800
```

`onboarding@resend.dev` 仅用于发送给 Resend 账号注册邮箱的个人测试。对外开放前，仍须把 `RESEND_FROM` 改为已验证域名下的地址。HTTPS 不会绕过测试域限制、发送权限或免费额度。

运输器固定向 `https://api.resend.com/emails` 发送一次请求，启用 TLS 证书验证、10 秒超时、不跟随重定向；不接受配置自定义 API host，不做 SMTP/HTTPS 自动回退或重复发送。只有响应是 2xx 且包含有效邮件 UUID 才记作服务商接受；401、403、429、5xx、网络失败或异常 2xx 均返回去敏的 503。不会把服务商原始响应、请求正文、收件地址、密钥或验证码写进接口错误和日志。[官方发送 API](https://resend.com/docs/api-reference/emails/send-email)

`EMAIL_PROVIDER=resend` 时只要求 `RESEND_API_KEY`、`RESEND_FROM`；SMTP 字段不参与可用性判断。Sending access 只授予发信权限，可额外限制发件域，不需要 full access。[官方 API key 说明](https://resend.com/docs/create-an-api-key)

## SMTP 兼容配置

在自己持有的 Resend 账号中创建用于发送邮件的 API key。需要对外给其他用户发验证码时，先验证自己管理的发信域名，然后使用该域名下的发件地址。域名可以与网站使用同一主域下的子域；具体 DNS 值以服务商控制台显示为准，不覆盖已有记录。

将配置填写到受控服务端环境或本机 `backend/.env`，不要提交代码或发到聊天中：

```dotenv
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USERNAME=resend
SMTP_PASSWORD=<本地填写 API key>
SMTP_FROM=login@<已验证发信域名>
SMTP_STARTTLS=true
AUTH_EMAIL_DAILY_LIMIT=90
AUTH_EMAIL_MONTHLY_LIMIT=2800
```

SMTP host、用户名、API key 用作密码以及 587 端口的 STARTTLS 方式来自 [Resend SMTP 官方文档](https://resend.com/docs/send-with-smtp)。运输器始终先校验 TLS 证书并升级连接，再认证和发送；未配置密码或关闭 TLS 时不开放发送。

如果暂时没有域名，可以先使用 `onboarding@resend.dev` 向 **Resend 账号自己的注册邮箱** 做个人联调。该测试身份不能用来开放任意邮箱注册；这是 [Resend 测试域名限制](https://resend.com/docs/knowledge-base/403-error-resend-dev-domain)。配置项存在不代表域名已验证或服务商已经批准发送。

注册保持免费套餐，不启用 Transactional Overages，不开通付费附加项。当前 [Resend 价格页](https://resend.com/pricing)列出免费套餐每日 100 封，并说明超额按量付费需要额外启用。实际账号额度以控制台为准；每次启用新服务商时核对免费额度、重置周期和是否共享给其他应用。

## 应用自己的额度保护

应用给全部用户合计设置 **每日 90 次、每个自然月 2800 次发送尝试**。两个上限都必须是正整数，0 或负数使配置失败，不能表示无限。

- 日界线：UTC 00:00，即北京时间 08:00。
- 月界线：每月 1 日 UTC 00:00，即北京时间每月 1 日 08:00。
- 在联系邮件服务前，邮箱/IP 限流、日/月额度及验证码记录在同一个数据库事务中预留；多个进程并发通过条件更新争用同一额度，重启服务不会清零。切换 SMTP/HTTPS 不会重置额度。
- 邮件服务超时、拒绝或其他发送失败仍消耗一次尝试。超时不等于服务商没有收到邮件，保守计数可以避免重试绕过预算。失败的验证码记录会删除。
- 任一上限耗尽即返回 429 和 `Retry-After` 秒数；提示包含对应 UTC 重置时刻。被额度拦截的请求不会再联系邮件服务，也不会消耗另一个额度。
- 同邮箱每分钟 1 次、每小时 5 次，以及同 IP 每小时 20 次的原有限流继续生效。

额度键通过独立用途的 HMAC 子密钥计算，计数保存在已有 `account_auth_rate_buckets` 表中，不新增明文邮箱索引。`ACCOUNT_SECRET` 必须稳定并独立备份；更换它会改变账号索引与额度标识，不能通过随意换密钥重置限额。

这份预算只覆盖本应用的验证码请求，不包含同一邮件账号被其他应用/人工使用的发送量，也不能控制服务商后台被人工切换到付费。上线时应给此应用使用独立发送身份并保持免费服务商硬限额；两边重置周期不同时采用更低额度。

## 无秘密配置诊断

已有 `AccountService` 实例的 `mail_configuration_status()` 只返回是否配置完整、缺少或不合法的字段名、应用上限及 UTC 定义；两个运输器的 `configuration_status()` 返回各自配置状态及 provider。均不返回 host、用户名、密码、发件地址、验证码或账号密钥。

例如：

```json
{"available": false, "missing": ["RESEND_API_KEY"], "invalid": [], "transport": "resend_https", "provider": "resend", "daily_limit": 90, "monthly_limit": 2800, "quota_timezone": "UTC", "counts": "send_attempts"}
```

诊断不主动连接外部服务，也不发送邮件。`GET /api/account/me` 的 `login_available` 保持原契约，只说明配置可尝试发送。

## 真实验收

配置后在登录页向本人授权的邮箱请求一次验证码，确认实际收件，然后完成登录、刷新、退出和重新登录。用另一账号验证无法读取首个账号资料。联调报告分别记录“邮件服务接受”“邮箱收到”“验证码登录成功”，不能只凭 HTTP 200 声称收件成功。

发送接口成功返回 `delivery_status=provider_accepted`。兼容字段 `sent=true` 也仅表示邮件服务接受；产品提示“已提交邮件服务，请检查收件箱或垃圾邮件”。不会在接口、网页、日志或配置诊断中显示验证码。服务商拒绝时返回经去敏的 503，不原样展示邮件服务响应。

自动回归命令：

```text
.venv/bin/python -m unittest discover -s tests -p test_email_delivery_budget.py -v
.venv/bin/python -m unittest discover -s tests -p test_resend_transport.py -v
.venv/bin/python -m unittest discover -s tests -p test_account_security.py -v
```

自动测试使用临时 SQLite、随机密钥和假的邮件运输器，不会向外部地址发信。覆盖日/月并发额度、重启持久性、UTC 月份/年份/闰日边界、失败占额、运输器切换不重置配额、无秘密诊断、TLS 顺序、HTTPS 固定端点与禁止重定向、权限/额度/服务器/网络错误和异常成功响应；它们不能替代真实收件验收。
