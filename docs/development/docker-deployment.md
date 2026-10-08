# Docker 单机部署

本方案用于**一台 Linux 服务器上的全新安装**：Caddy 提供 HTTPS，应用容器运行一个 Uvicorn worker，两份 SQLite 数据库存入同一持久卷。

`resume.yikuaibanz.cn` 已于 2026-10-05 在服务器完成构建、启动、HTTPS 与邮件域验证；容器内 358 项隔离测试通过，正式发件地址已加载，真实收件与登录全流程仍待验收。该服务器已有宿主机 Caddy，使用 `deploy/compose.host-caddy.yaml` 与 `sudo`；**维护这个实例请直接使用 [实际服务器交接](2026-10-05-server-deployment.md) 的双配置命令**。下文是自带 Caddy 的全新服务器通用流程，不能直接照搬到已有实例。

已有本机聊天和档案需要另走配对数据库迁移：保留原数据密钥与 `ACCOUNT_SECRET`，不能先按新安装生成密钥再复制旧库。参见 [账号与加密运维说明](security-operations.md)。

## 1. 服务器准备

- 安装 Docker Engine、Buildx 和 Compose 插件；本配置使用 `env_file.format: raw`，需要 **Docker Compose 2.30 或更新版**。在服务器检查 `docker version`、`docker compose version`。Ubuntu 安装步骤以 [Docker 官方说明](https://docs.docker.com/engine/install/ubuntu/) 为准。下文假设当前账号已有 Docker 使用权限；否则为 Docker 命令加 `sudo`。
- 准备域名，例如 `resume.example.com`，A 记录指向服务器；只有确实启用 IPv6 时才配置 AAAA。开放 TCP 80/443 并保留自己的 SSH 入口，确保没有其他程序占用 80/443。本方案由 Caddy 直接接收公网流量。
- 准备可用的模型 API key，以及已经授权、发件域已验证的邮件服务配置。账号登录依赖真实收件；仅有模型 key 不能让用户登录。不要把这些值发到聊天中。

Caddy 在域名解析正确、端口可达且证书目录持久化时自动管理 HTTPS；见 [自动 HTTPS 文档](https://caddyserver.com/docs/automatic-https)。如果服务器已有 Nginx/宝塔/其他代理，应沿用既有入口并调整这份拓扑，不要直接抢占其端口。

## 2. 本机打包，上传源码包

在项目根目录执行：

```sh
python3 scripts/package_deploy.py
scp dist/huhua-deploy.tar.gz YOUR_USER@YOUR_SERVER:/tmp/huhua-deploy.tar.gz
```

此脚本打包**当前工作区文件**，包含尚未提交的新模块。它使用允许清单，排除 `.env`、数据库、个人简历、测试证据、备份与开发缓存；不会把本机配置和历史数据带上服务器。输出 SHA-256 可供上传后校对。不要用 `tar` 直接打整个项目目录，也不要误以为只克隆远程仓库就能取得当前未提交实现。

在服务器选择一个全新的目录：

```sh
sudo mkdir -p /opt/huhua
sudo chown "$(id -u):$(id -g)" /opt/huhua
cd /opt/huhua
tar -xzf /tmp/huhua-deploy.tar.gz
```

上述目录若已有部署，先按“更新”部分操作，不能当作新安装覆盖运行配置。

## 3. 在服务器生成配置

```sh
cp -n deploy/compose.env.example deploy/compose.env
python3 deploy/init_env.py
chmod 600 deploy/compose.env deploy/app.env
nano deploy/compose.env
nano deploy/app.env
```

`init_env.py` 只为新安装创建 `deploy/app.env`，生成两份独立随机密钥，权限 0600，不打印密钥；文件已存在会拒绝覆盖。以后更新代码时**不要重新生成这些密钥**。将此文件中的数据密钥和账号密钥在受控位置单独备份，不能只留在服务器硬盘上。

`deploy/compose.env` 中填写：

```dotenv
HUHUA_DOMAIN=你的实际域名
HUHUA_IMAGE_TAG=v1
```

域名不带 `https://`、路径或结尾斜杠。`deploy/app.env` 中保留生成的密钥，补齐：

| 配置 | 填写内容 |
| --- | --- |
| `LLM_PROVIDER` | OpenAI 兼容接口通常为 `openai`；项目的 DeepSeek 专用适配为 `deepseek` |
| `LLM_API_KEY`、`LLM_BASE_URL` | 服务商 key 与 OpenAI 兼容入口；不自动读取本机 `.env` |
| `LLM_MODEL`、`LLM_STRUCTURED_MODEL` | 账号实际可用的主模型、支持结构化输出的模型；需要时配置视觉模型 |
| `EMAIL_PROVIDER=resend` | 使用项目已有 Resend HTTPS 运输器 |
| `RESEND_API_KEY`、`RESEND_FROM` | 发送凭证及已验证域名的发件地址，如 `Huhua <login@你的发信域名>` |

也可将 `EMAIL_PROVIDER` 改为 `smtp`，填写 SMTP 主机、端口、账号、密码和发件地址，并保持 `SMTP_STARTTLS=true`。邮件额度按实际服务商额度配置；默认值只是项目配置，不代表承诺免费或无限发送。

保持生产配置 `REQUIRE_ACCOUNT=true`，它与游客体验并不冲突。以下三项控制临时体验，未填写时使用所示默认值：

```dotenv
ALLOW_GUEST_EXPERIENCE=true
GUEST_RETENTION_HOURS=24
GUEST_DAILY_TURN_LIMIT=20
```

首次访问可看模板、聊天、编辑和预览当前简历。游客内容使用独立浏览器凭证访问、加密临时存储，24 小时未更新后过期，不写入长期档案。登录后仅认领当前会话，随后可导出、保留历史和使用长期记忆。账号历史仍由 `SESSION_RETENTION_DAYS` 控制；关闭游客体验用 `ALLOW_GUEST_EXPERIENCE=false`，不要关闭生产加密或安全 Cookie。产品导出入口的登录要求不能阻止用户自行复制可见预览或使用浏览器打印。

`app.env` 使用 Compose 的 raw 格式：每行 `KEY=VALUE`，**不要给值额外套引号或加行尾注释**，避免密码中的 `$` 被展开。该格式与版本要求见 [Compose env_file 文档](https://docs.docker.com/reference/compose-file/services/#env_file)。

## 4. 构建镜像并启动

在服务器项目根目录执行：

```sh
docker compose --env-file deploy/compose.env config --quiet
docker compose --env-file deploy/compose.env build app
docker compose --env-file deploy/compose.env up -d --no-build
docker compose --env-file deploy/compose.env ps
docker compose --env-file deploy/compose.env logs --tail=100 app caddy
```

`config --quiet` 校验配置而不展开打印密钥。`build app` 把程序与依赖打成镜像；`up` 创建容器与持久卷。服务器原生构建可避免 Mac ARM 与常见 Linux x86 镜像架构不匹配。应用以 UID/GID 10001 运行，不发布 8765 到公网；只开放 Caddy 的 80/443。

数据库路径固定为 `/var/lib/huhua/huhua.db` 和 `/var/lib/huhua/checkpoints.sqlite3`，均由 `huhua_app_data` 命名卷保存。Caddy 的证书也有持久卷。替换容器保留这些卷，**不要运行 `docker compose down -v`**。

代理信任范围依赖这份拓扑：只有 Caddy 与应用在该 Compose 网络，应用没有宿主机端口映射，因此信任网络内的转发头。不要同时把应用端口暴露出去，也不要随意把不可信容器接入网络。若使用另一层代理，应重新核对真实来源 IP 与请求头信任关系。Caddy 默认会流式转发 `text/event-stream`，无需关闭客户端断线取消；见 [reverse_proxy 文档](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#streaming)。

目前依赖使用版本下限，首次 build 会解析当时可用的依赖；一次成功构建后应保存该镜像及部署版本，不能假设未来重建必定得到相同版本。单 worker/单副本是本项目当前并发约束，不要直接 `--scale app=2`。

## 5. 上线检查

```sh
curl --fail https://你的实际域名/healthz
curl --fail https://你的实际域名/api/account/me
```

随后用新浏览器会话检查免登录模板预览、虚构材料的聊天流式输出和当前稿编辑；游客点击导出应提示登录，历史目录和长期档案仍要求账号。用你已授权的测试邮箱完成“收到验证码 → 登录 → 接续原会话 → Word 导出”，确认当前稿及未发送输入没有丢失。刷新后应仍登录，重启 `app` 后确认已认领的测试记录仍存在；另一个浏览器不能读取或认领该会话。

`healthz` 只确认应用存储与 checkpoint 可用，**不验证模型调用、邮件送达和备份恢复**；`login_available=true` 也不能替代真实收件。看到容器 `healthy` 还不能直接宣称公开 beta 验收完成。

没有域名或 80/443 不通时，这份生产配置不能照搬为公开 HTTP。先准备 HTTPS 入口，不要将生产安全 Cookie 关闭来绕过登录问题。

## 6. 更新与备份

更新前暂停写入，在同一维护窗口备份应用库和 checkpoint，并导出最新隐私状态及独立可信摘要。具体加密备份与恢复命令见 [运维说明第 5、6 节](security-operations.md)。数据卷只解决容器重建后的保留，不是异机备份；简单覆盖旧数据库可能复活已删除资料。

上传新版源码包；包中不含 `deploy/app.env`、`deploy/compose.env`，因此不会覆盖服务器运行配置。修改 `compose.env` 的镜像标签，例如 `v2`，然后执行：

```sh
docker compose --env-file deploy/compose.env build app
docker compose --env-file deploy/compose.env up -d --no-build app
docker compose --env-file deploy/compose.env ps
docker compose --env-file deploy/compose.env logs --tail=100 app
```

保持目录、Compose 项目名和数据卷不变，重新做登录、保存、导出检查。只有确认数据库格式兼容时才能切回旧镜像；涉及数据库更改的恢复必须按配对库及最新隐私状态恢复流程执行，不能只回退一份数据库或密钥。

## 可选：在有 Docker 的电脑上构建镜像再上传

推荐先在服务器原生构建；如果本机已经装 Docker，可在确认服务器 `uname -m` 后使用下列方式。`x86_64` 对应 `linux/amd64`，`aarch64` 对应 `linux/arm64`：

```sh
docker buildx build --platform linux/amd64 --load -t huhua-agent:v1 .
docker save -o dist/huhua-agent-v1.tar huhua-agent:v1
scp dist/huhua-agent-v1.tar YOUR_USER@YOUR_SERVER:/tmp/huhua-agent-v1.tar
```

服务器仍需本包中的 Compose、Caddy 和运行配置，然后执行：

```sh
docker load -i /tmp/huhua-agent-v1.tar
docker compose --env-file deploy/compose.env up -d --no-build
```

`HUHUA_IMAGE_TAG` 必须与导入镜像的 `v1` 一致。该镜像不包含运行密钥与数据库；Caddy 镜像仍需从仓库拉取。这条“本机构建再上传镜像”的可选流程未实际执行；本次实例是在服务器原生构建。
