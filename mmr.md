# 胡话简历交接

## 目标
第十八批 b 修复轮 2：修复 run2 新增经历假成功、首稿技术罗列及残留连接词；查清旧版归因和排版错误，完成离线验证。

## 已完成
- 只读 load_resume_session 与 checkpoint 核对 run2；导出虚构 fixture `tests/fixtures/batch18b_run2.json`，不依赖原库或凭据。
- `627a06f` 独立源码离线复现 ok/changed=true 但工作经历为空；A 是 batch17b 已有问题。旧 item 范围只编辑命中的旧项目，未验证新增经历交付。
- 本轮新经历或后续点名补入未写条目时，edit_resume 返回 insufficient + write_draft 路由，失败不改稿。所有成功编辑出口按真实 diff 生成回执，无 diff 为 unchanged。
- 首稿路径实际经过清理；漏点是「并可通过」与「搭建 agent 能力」不匹配。已补正则、连接词/标点清理及具体动作边界，保留引用/hash/coverage 和幂等。
- 原首稿口述出稿功能已被 coverage 标为 omitted；新增 uncovered_facts 回执及压缩优先级。完整写稿桩回放清理后恢复该功能要点。
- 排版错误复现为 WeasyPrint 无法加载 libgobject-2.0-0；设置 DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib 后 run2 最终稿可测量。依赖失败明确返回 layout_renderer_unavailable，无页数或稿件写回。
- 新增 16 项回归；batch18b 78 项通过。最终全量 2307 项：2305 通过、2 项既有私人材料跳过、0 失败；6 个 Python 文件 Ruff 与 git diff --check 通过。

## 未完成
本轮授权的本地修复和离线验证已完成；真实模型的新行为尚未重跑，未 commit / push / 部署。

## 失败做法
- 只凭项目发生变化就返回 ok，会掩盖用户要求新增但未写入的经历。
- 上轮 fixture 措辞与真实稿件不同，漏掉「并可」和空泛 agent 能力结尾；必须保留真实原句回归。
- 仅提示遗漏数量不能阻止回复声称功能已写入；需明确列出未覆盖事实。
- 首轮全量仅旧回执字典严格相等断言失败；已更新实际 diff 契约检查，保留不得重写和保存次数等断言。

## 关键决策与理由
- 新增经历统一转 write_draft，避免局部编辑默默重写无关条目；保留事实供同轮继续调用。
- 技术清单只在已完整被技术栈覆盖时删除，具体动作继续留正文。单纯技术栈增删仍逐字保留已有要点，防止轮 1 数据丢失回归。
- 原模型参数没有保存在 checkpoint；旧版离线复现指令只证明同类缺陷，不冒充原始调用。

## 当前状态
基线 HEAD 88f777e；本轮改动未提交，开场两个未跟踪 prompt 文件保留。`batch18b-report.md` 末尾「修复轮 2」含根因、历史证据和验证。原回放库未改写且保持 gitignore。最终日志 `/private/tmp/huhua-b18b-round2-final.log`，无本轮运行中的测试/服务。

## 接手步骤
1. 核对 git 状态及报告；原 test_batch18b.py 和修复轮 1 回归保持不变。
2. 后续若获授权再跑真实模型，核对新增经历路由、实际正文/版本与回执，不以对话宣称代替稿件。
3. 本地排版进程需设置上述原生库路径；不要自动提交、推送或部署。
