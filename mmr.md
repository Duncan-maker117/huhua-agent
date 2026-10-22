# Huhua Agent 交接

## 目标
本轮修复 iPhone 首次聊天输入框不可达，以及首页进入后多次后退问题。用户要求只本地修改并写 handoff，不推送、不部署。上轮上下文压缩待 Claude 审查。

## 已完成
- 上轮基于最新 batch19a/6fdae0a；原代码已推 origin/batch19a，上下文策略已推 codex/context-memory/7125db9。原聊天目录 overhaul/tailor 是旧代码，没有覆盖。
- 上下文策略：完整有效经历、原始引文、否定/分工/测试限制与未覆盖原文；工具后刷新，旧撤回来源禁止重新入库；输入超限明确停止并保留已完成更新。详细设计见 docs/development/2026-10-22-context-memory.md。
- 本轮移除 h-screen/100vh 冲突，VisualViewport 同步工作台可见高度/偏移，输入常驻底部，消息与问题卡内部滚动；手机16px输入、安全区留白、短键盘视口适配，不丢草稿和阅读位置。
- 修复模板预览 iframe 的 srcdoc 导航增加联合历史：脱离DOM更新后原位挂回，保留 sandbox 与双缓冲，空帧不重复重置。主/编辑器资源版本均更新。
- 新增手机布局及后退浏览器回归；更新模板预览DOM回归。

## 未完成
- 本轮尚未提交/推送/部署，全部在工作树未提交差异中，含3个新增文件。
- 实体 iPhone Safari/Chrome 复核；Claude 审查；上下文策略真实模型长对话验收；合并发布均未执行。

## 失败做法
- 只看原聊天目录会误判最新代码；接手必须先切正确工作树。
- 标签 body 的100dvh覆盖不了类h-screen；仅改dvh不够，键盘还需VisualViewport。
- 单独fixed输入区会破坏消息占位；约束整个工作台并保留flex滚动。
- 隐藏iframe也参与浏览器历史，改顶层replaceState无效；需消除子frame导航历史。
- 上下文只留最近几轮/前三句会丢限制；仅在提示隐藏撤回记录挡不住工具重新抽取。

## 关键决策与理由
- 手机视口更新不主动聚焦/滚动；scale不为1时不跟随重排，允许用户缩放。
- iframe保留DOM元素和opaque sandbox，仅重建子浏览上下文，保持既有双缓冲协议。
- 本轮仅前端，测试覆盖实际布局/点击、历史导航和相关DOM行为，不重跑无关后端业务。

## 当前状态
- 工作树：/Users/yikuaibanz1/.codex/worktrees/huhua-context/huhua agent
- 分支 codex/context-memory；HEAD7125db9（已推的上轮）。本轮web/tests/mmr未提交，未push，未部署。
- 验证：手机WebKit/Chromium各19检查；导航两引擎各5检查；模板DOM12、嵌入编辑3、重复操作12通过。均合成API，键盘/工具栏几何模拟，不冒充实体机。
- 上轮全量2403项：2401通过、2跳过；本轮未重新声明该全量结果。
- 用户指定 handoff 已追加到 /Users/yikuaibanz1/Desktop/sth/huhua agent/handoff.md（原文保留，最新小节含准确代码位置与复现）。旧交接归档在mmr-archive.md。

## 接手步骤
1. 到上述工作树核对git status，读取handoff最新小节；git diff审本轮，新增文件也要读。
2. 上轮上下文差异用git diff 6fdae0a...7125db9；本轮测试命令在新增browser.js文件头。
3. 先审实现和实体手机体验；按用户新的明确指示决定提交/合并/部署。

## 进行中记录
