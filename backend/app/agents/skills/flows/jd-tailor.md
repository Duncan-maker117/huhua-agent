---
name: jd-tailor
title: 按岗位定制
when: 用户贴了岗位描述（JD）或招聘链接，或说「按这个岗位改」「投 XX 岗」
---

# 按岗位定制

1. 有 JD 正文或链接 → read_jd（source_id 指向那条消息）；只给公司名/方向且需要了解公司时 search_company，每轮至多一次。
2. JD 里的要求是筛选标准，不是用户的经历；不能因为 JD 要 SQL 就给用户写 SQL。
3. 已有事实足够 → write_draft，direction 写岗位名，emphasis 写 JD 最看重的 2–3 个信号；事实太少 → 先用 ask_user 问最能证明核心要求的那段经历。
4. 回复说明：哪几条要求有直接证据、哪几条是可迁移表达、哪几条目前没有（gap）——gap 只提示，不编。
5. 用户只是换投递方向时，用 write_draft 重新排序和取舍，不删用户的事实。
