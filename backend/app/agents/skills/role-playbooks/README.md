# 岗位手册（role playbooks）

运行时按 `role_profile.role_family` 加载**一份**手册，注入 match_planner / resume_writer / interviewer 三个节点。
未知岗位加载 `general.md`，并依赖 JD 解码出的 `role_profile.core_signals` 补足。

| role_family | 文件 | 常见 JD 标题 |
|---|---|---|
| ai_pm | ai-pm.md | AI 产品经理、大模型产品、AIGC 产品、Agent 产品 |
| pm | product-manager.md | 产品经理、产品助理、策略产品、B 端/C 端产品 |
| backend | backend.md | 后端开发、Java/Go/Python 开发、服务端、平台开发 |
| frontend | frontend.md | 前端开发、Web 开发、客户端（H5/小程序） |
| algorithm | algorithm.md | 算法工程师、机器学习、NLP/CV、大模型算法、推荐算法 |
| data | data-analyst.md | 数据分析、商业分析、BI、数据运营 |
| ops | operations.md | 运营、内容运营、用户运营、增长、新媒体、活动运营 |
| design | design.md | UI/UX 设计、交互设计、视觉设计、用户研究 |
| other | general.md | 其他所有 |

每份手册结构固定：筛选者看什么（按权重）→ 学生能拿出的证据 → 成果口径（用于追问）→ 表达 → 改写示例 → 高价值追问 → 常见坑。

**示例里的"原话"与"改写"只演示方法，绝不能把示例中的事实、数字、项目名写进用户简历。**
手册是方法知识，不是用户事实；任何从手册来的词，只有在用户事实里有对应依据时才能出现在简历中。
