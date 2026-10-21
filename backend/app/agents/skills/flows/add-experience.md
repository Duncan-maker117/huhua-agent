---
name: add-experience
title: 新增经历
when: 用户补充了一段稿子里还没有的实习、工作、项目、校园或比赛经历（哪怕只有一句）
---

# 新增经历

1. record_facts（source_id=current）记下原话。
2. 稿子里还没有这段经历 → **write_draft**，不要用 edit_resume。edit_resume 只改已有条目，遇到新经历会返回 new_experience_requires_write_draft。
3. write_draft 时用 emphasis 说明「保留已有经历的要点与技术栈，新增 <经历名>」，避免重写把旧要点挤掉。
4. 收尾前看工具结果：write_draft 返回的稿件条目（或 edit_resume 的 document_changes）里确实有这段经历，才能说「已加进稿子」；只在 change_summary 里提到不算。没有就如实说没加上及原因。uncovered_facts 里的内容不能说成已写入。
5. 新经历缺名称、起止时间或本人角色时，出稿后用一张 ask_user 卡补齐，一次问完，不追数字。
