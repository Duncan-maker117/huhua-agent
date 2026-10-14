"""Conservative literal labels and resume prose; never add candidate claims."""

import re


PLACEHOLDER_NAMES = {
    "work_experience": "工作经历（待补公司/岗位名）",
    "internship": "实习经历（待补公司/岗位名）",
    "projects": "项目（待补名称）",
    "campus": "校园经历（待补组织名）",
    "open_source": "开源贡献（待补名称）",
    "awards": "荣誉（待补名称）",
    "education": "教育经历（待补学校名）",
}
_CAMPUS = re.compile(r"协会|社团|学生会|学生组织|班委|志愿|宣传部|校园经历|校园活动")
_PROSE_NAME = re.compile(r"^(?:我|本人|负责|运用|使用|对接|完成|参与|做过|做了|整理了|处理了)|^\d+(?:家|人|张)|[，,。；;？！?!\n]|时候|这些|那些|添加了|处理了|公司名字|工作内容|主要为|希望|不知道|我(?:们|的|在|做|参与)|(?:^|的)工作(?:在|$)")
_NON_FACT = re.compile(r"[？?]|(?:我|个人|自己)(?:认为|觉得|感觉|希望|想知道|想问|打算|计划)|"
                       r"^(?:计划|打算|希望|准备|以后|将来)|不知道|哪些岗位|什么方向|能力尚浅|希望.{0,12}(?:工作|职业)|可以接单|有自信|有信心")


def non_fact(text: str) -> bool:
    return bool(_NON_FACT.search(text))


def placeholder_name(value: str) -> bool:
    return value in PLACEHOLDER_NAMES.values() or value in {"课程作业（待补名称）", "个人练习（待补名称）"}


def safe_objective(value: str) -> str:
    value = str(value or "").strip()
    if (not value or len(value) > 20 or re.search(r"我|你|他|她|不知道|不清楚|不确定|适合|希望|想|兴趣|"
                                                  r"[？?。！!；;\n]|什么|哪些|怎么|是否|职业方向", value)):
        return ""
    # A short sentence is not necessarily a job title.
    return value if re.search(r"设计|美工|助理|工程师|开发|产品|运营|行政|采购|销售|客服|财务|会计|"
                              r"编辑|策划|教师|经理|专员|分析|测试|研究|人事|文员|顾问|秘书|"
                              r"前端|后端|算法|数据|运维|UI|UX|PM|SRE|HR", value, re.I) else ""


def safe_major(value: str) -> bool:
    value = str(value or "").strip()
    return bool(2 <= len(value) <= 30 and not re.search(
        r"协会|社团|学生会|宣传部|担任|参与|时候|工作|我|读者|专业能力|^专业$|[，,。；;？?]", value))


def safe_item_name(value: str) -> bool:
    value = str(value or "").strip()
    return bool(value and len(value) <= 36 and not re.search(r"^[了的在]|[了的在]$", value)
                and not _PROSE_NAME.search(value))


def campus_evidence(text: str) -> bool:
    # A technical project *for* an association is still a project.
    return bool(_CAMPUS.search(text) and not re.search(r"开源|github|PR\s*#?\d|开发.{0,12}(?:系统|网站|小程序)", text, re.I))


def coursework_evidence(text: str) -> bool:
    return bool(re.search(r"作业|课程|课上|摄影课|大学[^，。；;\n]{0,12}课", text) and not _CAMPUS.search(text))


def literal_item_name(text: str, section: str) -> str:
    """Extract only explicit naming constructions or complete organization spans."""
    patterns = [r"(?:名称|名字|公司名|项目名|组织名)(?:是|为|叫做|叫|[：:])\s*[“「\"']?([^，,。；;\n”」\"']{1,36})",
                r"[“「\"']([^”」\"'\n]{1,36})[”」\"']\s*(?:项目|活动)"]
    patterns.insert(0, r"(?:项目|公司|组织|社团)(?:名称|名字)?(?:是|为|叫做|叫|名为)\s*[“「\"']?([^，,。；;\n”」\"']{1,36})")
    suffix = (r"(?:公司|事务所|工作室)" if section in {"work_experience", "internship"} else
              r"(?:协会|社团|学生会|志愿者队|部)" if section == "campus" else "")
    if suffix:
        # Consume verbs and their aspect particles before capturing the noun.
        patterns += [r"(?:在|加入|参加|参与|就职于|入职)(?:了|过)?\s*"
                     r"([A-Za-z\u4e00-\u9fff0-9·]{2,28}?" + suffix + r")",
                     r"(?:^|[，,。；;\n])\s*([A-Za-z\u4e00-\u9fff0-9·]{2,28}?" + suffix + r")"]
    if section == "projects":
        if coursework_evidence(text):
            match = re.search(r"(?:作业|课程设计)(?:是|为|叫|[：:])\s*([^，,。；;\n]{2,30})", text)
            if match and safe_item_name(match[1]):
                return match[1]
        patterns += [r"(?:做过|做|在|参与|负责|开发)(?:了|过)?\s*([A-Za-z\u4e00-\u9fff0-9_-]{1,30})项目"]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = match[1].strip()
            if safe_item_name(name):
                return name
    return ""


def resume_bullet(text: str, *, name: str = "", role: str = "") -> str:
    """Deletion-only fallback: strip speech, questions and header echoes, retain limits."""
    clauses, separators = [], []
    pieces = re.split(r"([，,。；;\n])", str(text or ""))
    for index in range(0, len(pieces), 2):
        clause = pieces[index]
        clause = clause.strip(" -•\t")
        if not clause or _NON_FACT.search(clause):
            continue
        clause = re.sub(r"^(?:(?:大学|在校|上学|读书)(?:的)?(?:时候|时)|毕业后|当时|那时候|然后|但是|而且|目前|补充[:：])*", "", clause)
        clause = re.sub(r"^(?:是)?(?:我(?!们)|本人)(?:还|也|又|就)?(?:主要)?", "", clause)
        clause = re.sub(r"^(?:工作内容(?:是|为)|主要(?:是|为))", "", clause).strip()
        clause = re.sub(r"^(独立完成)的$", r"\1", clause)
        if not clause or any(label and clause == label for label in PLACEHOLDER_NAMES.values()):
            continue
        if name:
            clause = re.sub(r"^(?:在)?" + re.escape(name) + r"(?:中)?(?:的)?", "", clause).strip()
            if re.fullmatch(r"(?:参与|加入|参加)(?:了)?" + re.escape(name), clause):
                continue
        if role and re.fullmatch(r"(?:在.{1,16}(?:中)?)?(?:担任|任)(?:了)?" + re.escape(role), clause):
            continue
        if clause and clause not in clauses:
            clauses.append(clause)
            separators.append(pieces[index + 1] if index + 1 < len(pieces) else "")
    return "".join(clause + sep for clause, sep in zip(clauses, separators)).rstrip("，,；;\n")
