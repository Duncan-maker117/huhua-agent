# 胡话简历交接

## 目标

把用户真实经历整理成可核对、可编辑、可导出的简历，事实有出处，账号隔离。当前批次仅交付输入框 next_hint 与 MCP edit_url 跨账号提示；不扩大重构。

## 已完成

2026-10-21，分支 `batch18a`，HEAD `627a06f`。

- loop 在原模型调用正文尾部附可选提示，跨 token 剥离；13 句通用意图白名单，数字/链接/超长/空/非白名单/问卡均拒绝。保存后 SSE 下发，历史不回放。输入框支持 Tab 采用、移动端文案及输入/发送/切换/取消时清除。
- 新 edit_url 带 `from=mcp`；仅带标记的已登录 GET 读取可得 `403 conversation_other_account`，返回固定说明。编辑页/聊天页提供退出按钮，复用清缓存与账号重置，保留原链接走登录接续。普通访问/写操作不变。
- 静态资源版本 `20261021-1`。新增 19 项离线回归；相关 32 项通过。最终全量 2240 项：2238 通过、2 原有跳过，0 失败/错误，104.967s。11 个修改 Python 文件 Ruff、JS 语法、diff 检查通过。

## 未完成

无本批本地交付阻塞。按要求未调用真实模型、未做真实账号邮件/浏览器人工联调；未 commit、push 或部署。模型提示选择质量与真实设备体验待后续授权验证。旧无来源标记链接仍保持原行为。

## 失败做法

首轮全量先读来源参数，旧非账号 Request 缺 query_string 导致 3 个子场景错误；改为先检查账号身份，旧断言未改，最终全过。首次定向运行早于 DOM 文件写完，有 4 个缺文件错误，补齐后通过。

## 关键决策与理由

- 不增加模型调用；采用可选结构化尾部，保留现有正文流和工具预算。白名单限制表达范围，但可确定性阻止无数字的虚构事实。
- 来源参数仅控制错误说明，不是授权凭证；允许已登录者探测已知 UUID 的存在性，不泄露内容/邮箱。
- 保留原退出确认和普通退出目的地；仅跨账号按钮回到原链接。

## 当前状态

实现、测试、报告均未提交。开场已有 `prompt-batch18a.md` 保留未改。完整旧交接及本轮进行中记录已逐字节归档 `mmr-archive.md`；旧记录中的运行/部署状态以当次核验为准。测试进程已退出，未启动应用服务。

## 接手步骤

1. 读 `batch18a-report.md`，核对 git diff；后端入口为 `agents/next_hint.py`、`agents/orchestrator.py`、`agents/resume_graph.py`、`services/access_control.py`（均在 backend/app 下）。前端为 index、conversation-history、resume-editor、account-profile。
2. 回归为 `tests/test_batch18a.py`、`tests/batch18a.dom.js`。完整命令见报告；日志 `/private/tmp/huhua-b18a-full-final.log`，相关日志 `/private/tmp/huhua-b18a-targeted-final.log`。
3. 本批已完成本地验收，后续提交/部署/真实模型验证需按新的用户授权进行。
