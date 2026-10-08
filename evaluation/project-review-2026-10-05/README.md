# 项目审视后的验证记录

本目录使用虚构材料与临时数据库，不含真实用户数据或凭证。不同类型的验证分别记录，不能合并成真实用户端到端成功率。

- `suggestion-browser.json`：浏览器真实交互，业务 API 使用替身，覆盖生成、编辑后失效、采用/撤销、错误重试、版本变更与手机布局。
- `provenance-browser.json`：业务 API 使用替身，覆盖稳定 ID、删除记录、保存期间继续输入、个人预览/导出的会话参数、样例与新建草稿。
- `real-browser.json`：真实账号、加密数据库、档案、保存、建议采用、渲染和 Word 下载；仅邮件运输替为内存邮箱，没有调用模型。
- `live-rewrite.json`：真实模型对六个固定虚构原句的候选生成与核对，隔离临时加密数据库，不经过浏览器，不验证跨对话档案。
- `semantic-review.json`：Codex 对原句与候选的逐项比较；3 条可采用、2 条被拦截、1 条保留原句。不是人工用户试用，不能据单次六例估计总体成功率。
- `live-rewrite-sandbox-attempt.json`：首次网络受限的未完成尝试；保留失败记录，不计入成功案例。`live-rewrite-single-case.json` 是随后一次单例连通检查，不与六例重复相加。

离线回归：

```sh
.venv/bin/python scripts/run_tests.py -q
```

浏览器验收使用项目已有的 `playwright-cli`。先启动仅绑定本机、退出即清理数据库的真实后端夹具：

```sh
.venv/bin/python tests/product_live_server.py --port 8893
```

在另一个终端中执行：

```sh
playwright-cli -s=huhua-review open http://127.0.0.1:8893/
playwright-cli -s=huhua-review run-code --filename=tests/suggestion_generation.browser.js
playwright-cli -s=huhua-review run-code --filename=tests/resume_provenance.browser.js
playwright-cli -s=huhua-review close
playwright-cli -s=huhua-real open http://127.0.0.1:8893/
playwright-cli -s=huhua-real run-code --filename=evaluation/project-review-2026-10-05/run-real-browser.js
playwright-cli -s=huhua-real close
```

真实模型检查默认仅显示计划。`--live` 会消耗已配置提供商的模型额度，默认只跑一例，每例最多两次调用；不可用则停止，不自动重试：

```sh
.venv/bin/python scripts/evaluate_rewrites.py --max-cases 6
.venv/bin/python scripts/evaluate_rewrites.py --live --max-cases 6
```

主结论与最终验证汇总见 `docs/development/2026-10-05-project-review-and-improvements.md`。生产邮件、公开部署、目标 PostgreSQL 恢复与真实用户收益不在这些结果的证明范围内。
