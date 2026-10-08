# PublicBetaSmokeTest 隔离诊断

结论：这两项失败来自旧 smoke fixture 的配置隔离缺失，已在禁读 `.env` 的受控子进程精确复现；不需要更改生产鉴权。仅生成 `candidate.patch`，未改 MAIN 或 integration 源码。

## 401

`test_product_security_flow.py` 等旧测试在 `patch("app.config.get_settings", ...)` 期间导入 API。`app.api.resume` 的 `from app.config import get_settings` 因此可以永久持有当时的 MagicMock。PublicBeta 只清真实 getter 的缓存、设置环境变量，无法更换该别名。

受控重放：把 REQUIRE_ACCOUNT 设置 true 后导入 product_security_flow，再导入 public_beta（由其恢复 false）。可观测 config/main getter 为真实缓存函数且 require=false，resume getter 为独立 MagicMock 且 require=true；DOCX 导出精确返回 401，其余两项通过。此行为由测试导入顺序和早期受控配置决定，不是运行时间随机波动。没有修改生产授权规则。

## 启动加密错误

`main.lifespan` 在 REQUIRE_ACCOUNT 或 ACCOUNT_SECRET 非空时初始化 AccountService。PublicBeta 已强制清空加密密钥，却未清空 ACCOUNT_SECRET。使用只在测试脚本内构造的有效非秘密测试密钥，可精确重放两个测试的 `Accounts require encrypted storage, even in local mode`。配置模型没有 ACCOUNT_ENABLED 字段。

## 最小补丁

仅 `tests/test_public_beta.py`：

- import-time 和 setUp 明确清空 ACCOUNT_SECRET。
- setUp 将 database、main、session_store、runtime_limits、chat、conversations、resume 的 get_settings 绑定该 fixture 的真实 getter；tearDown 复用原 patch 回收机制恢复此前绑定。
- 不跳过断言，不放宽接口鉴权，不修改任何业务源码。

## 离线证据

`reproduce.py` 在导入应用前将 Settings.model_config.env_file 设为 None；所有相关配置均由脚本控制，不读取或输出任何 `.env` 值。不调用外部模型、邮件或网络服务。

| 场景 | 原 fixture | 补丁 fixture |
|---|---|---|
| 独立导入，干净本地配置 | 3/3 通过 | 无须重复 |
| 先导入账户要求为 true 的 product_security_flow | 1 failure：相同 DOCX 401 | 3/3 通过 |
| 非空受控 ACCOUNT_SECRET | 2 errors：相同加密错误 | 3/3 通过 |

日志分别为 `isolated.log`、`product_first-before.log`、`product_first-after.log`、`secret-before.log`、`secret-after.log`。`git apply --check` 已在 integration 副本通过。完整 866/887 项全套由 root 在应用补丁后终验。

说明：通过静态路径与受控重放确认机制，没有读取原机器私有配置来断言具体 secret 来自 `.env` 还是进程环境。
