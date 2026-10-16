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
                       r"^(?:计划|打算|希望|准备|以后|将来)|不知道|哪些岗位|什么方向|能力尚浅|希望.{0,12}(?:工作|职业)|可以接单|有自信|有信心|"
                       r"^(?:请|帮我|给我|不要|不能|不写成|保留|突出)|(?:把|将).{0,30}(?:润色|写成|改写)|材料.{0,3}给全|直接生成|"
                       r"^(?:这是|以下.*是)?虚构测试|^(?:我叫|姓名[:：]?)|"
                       r"(?:属于|都是|是)这?同一(?:段|个)(?:实习|工作|经历|(?=[，,。；;]|$))|"
                       r"(?:不是|并非|非|不属于)(?:个人练习|个人项目|项目)(?:经历)?(?=$|[，,。；;\s]|而是|里的事)")


def literal_employment(text: str) -> tuple[str, str]:
    """Only a named organization followed by an explicit position, never a place."""
    for match in re.finditer(r"在\s*([A-Za-z\u4e00-\u9fff0-9·]{2,12}?)\s*(?:做|当|任)\s*"
                             r"([^，,。；;\n]{2,24})", text):
        company, title = match[1], match[2].strip()
        if (safe_item_name(company) and not re.search(r'大学$|学校$', company)
                and not re.match(r"大学|学校|家|校内|校外|一家|某|一个|做|当|任|学习|工作|参与|负责|使用|进行|这里|那里", company)
                and re.search(r"实习生|助理|工程师|开发|客服|行政|运营|设计师|专员|经理|顾问|文员|会计|销售", title)):
            return company, title
    return "", ""


def non_fact(text: str) -> bool:
    return bool(_NON_FACT.search(text)) or editorial_absence(text)


def editorial_absence(text: str) -> bool:
    """Missing-input notes constrain writing; they are not candidate evidence."""
    return bool(re.match(r'^\s*(?:未|没有)(?:提供|填写|披露).{0,30}(?:绩点|GPA|排名|奖学金|成绩)', text, re.I))


def personal_header(text: str) -> bool:
    return bool(re.search(r'^(?:我叫|姓名|邮箱|电话|手机|学校[:：]|专业[:：]|学历[:：])|'
                          r'(?:大学|学院).{0,24}(?:本科|大专|专科|硕士|博士)', text.strip()))


_WORDING_LIMIT = re.compile(
    r"(?:没有|无|没|不具备).{0,8}(?:后台权限|数据|阅读量|播放量)|"
    r"(?:没|未|没有).{0,6}统计|不知道.{0,8}(?:播放量|阅读量|数据)|"
    r"(?:不是|并非|不担任).{0,8}(?:负责人|账号负责人)|"
    r"(?:选题|文案).{0,4}由.{1,12}(?:定|决定|提供|给)|"
    r"(?:店长|部长|主管|同事).{0,4}(?:给|提供)(?:的)?文案")


def wording_constraint(text: str) -> bool:
    """An ownership/data limit constrains prose; it is not a delivery."""
    return bool(_WORDING_LIMIT.search(text or ""))


def constraint_only(text: str) -> bool:
    clauses = [part.strip() for part in re.split(r"[，,。；;\n]", text or "") if part.strip()]

    def only_limit(clause):
        if editorial_absence(clause):
            return True
        if re.match(r'^(?:也)?(?:没有管理团队|(?:没有|无)(?:真实用户|线上测试|生产部署|并发|模型训练))', clause):
            return True
        if (re.match(r'^(?:我|本人)?(?:没有|未|不曾|不)(?:负责|参与|主导)', clause)
                and not re.search(r'但|却|而', clause)):
            return True
        limit = _WORDING_LIMIT.search(clause)
        if not limit:
            return False
        # “按部长给的文案制作过 6 张海报” contains an actual delivery
        # after the ownership limit. Removing that clause would lose the count.
        return not re.match(r'(?:(?:用|使用)[^，,。；;没有未不]{1,60}?)?(?:制作|绘制|排版|设计|完成|发布)',
                            clause[limit.end():].lstrip())

    return bool(clauses) and all(only_limit(part) for part in clauses)


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
        r"协会|社团|学生会|宣传部|担任|参与|时候|工作|我|读者|专业能力|^专业$|"
        r"请|把|润色|写得|写成|写为|更|一点|经历|简历|表达|措辞|竞争力|专业化|[，,。；;？?]", value))


def discipline_name(value: str) -> bool:
    """Unlabelled ‘X专业’ needs a recognizable discipline, not an adjective."""
    return safe_major(value) and bool(re.search(
        r"学|工程|技术|设计|管理|计算机|软件|电子|商务|营销|会计|金融|经济|语言|英语|中文|护理|艺术|传播|计科|信管", value))


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
    if section in {"work_experience", "internship"} and (employment := literal_employment(text))[0]:
        return employment[0]
    patterns = [r"(?:名称|名字|公司名|项目名|组织名)(?:是|为|叫做|叫|[：:])\s*[“「\"']?([^，,。；;\n”」\"']{1,36})",
                r"[“「\"']([^”」\"'\n]{1,36})[”」\"']\s*(?:项目|活动)"]
    patterns.insert(0, r"(?:项目|公司|咖啡店|组织|社团)(?:名称|名字)?(?:是|为|叫做|叫|名为)\s*[“「\"']?([^，,。；;\n”」\"']{1,36})")
    suffix = (r"(?:公司|事务所|工作室|咖啡店)" if section in {"work_experience", "internship"} else
              r"(?:协会|社团|学生会|志愿者队|部(?!长))" if section == "campus" else "")
    if suffix:
        # Consume verbs and their aspect particles before capturing the noun.
        patterns += [r"(?:在|加入|参加|参与|就职于|入职)(?:了|过)?\s*"
                     r"([A-Za-z\u4e00-\u9fff0-9·]{2,28}?" + suffix + r")",
                     r"(?:^|[，,。；;\n])\s*([A-Za-z\u4e00-\u9fff0-9·]{2,28}?" + suffix + r")"]
    if section == "projects":
        patterns += [r'课程项目(?:名称)?[:：]\s*([^，,。；;\n]{2,30})',
                     r'(?:绘制|提交)了([^，,。；;\n]{2,24}原型)(?:界面|链接)']
        if coursework_evidence(text):
            match = re.search(r"(?:作业|课程设计)(?:是|为|叫|[：:])\s*([^，,。；;\n]{2,30})", text)
            if match and safe_item_name(match[1]):
                return match[1]
        patterns += [r"(?:做过|做|在|参与|负责|开发)(?:了|过)?\s*([A-Za-z\u4e00-\u9fff0-9_-]{1,30})\s*项目"]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = match[1].strip()
            if section == 'projects' and name in {'新', '另一个', '另外一个', '其他', '别的'}:
                continue
            if safe_item_name(name) and not re.fullmatch(r"(?:还在|在)?(?:一家|一个|某家|某个)?(?:咖啡店|公司)", name):
                return name
    return ""


def resume_bullet(text: str, *, name: str = "", role: str = "") -> str:
    """Deletion-only fallback: strip speech, questions and header echoes, retain limits."""
    clauses, separators = [], []
    pieces = re.split(r"([，,。；;\n])", str(text or ""))
    for index in range(0, len(pieces), 2):
        clause = pieces[index]
        clause = clause.strip(" -•\t")
        if not clause or _NON_FACT.search(clause) or constraint_only(clause):
            continue
        clause = re.sub(r"^(?:(?:大学|在校|上学|读书)(?:的)?(?:时候|时)|毕业后|当时|那时候|然后|但是|而且|目前|补充[:：])*", "", clause)
        clause = re.sub(r"^大[一二三四](?=在)", "", clause)
        clause = re.sub(r"^其中\s*(\d+)\s*篇的?初稿是我写的$", r"撰写\1篇初稿", clause)
        clause = re.sub(r"^(?:是)?(?:我(?!们)|本人)(?:还|也|又|就)?(?:主要)?", "", clause)
        clause = re.sub(r"^(?:工作内容(?:是|为)|主要(?:是|为))", "", clause).strip()
        clause = re.sub(r"^(独立完成)的$", r"\1", clause)
        if not clause or any(label and clause == label for label in PLACEHOLDER_NAMES.values()):
            continue
        if name:
            clause = re.sub(r"^(?:在)?" + re.escape(name) + r"(?:中)?(?:的)?", "", clause).strip()
            if re.fullmatch(r"(?:参与|加入|参加)(?:了)?" + re.escape(name), clause):
                continue
        if role and (clause == role or re.fullmatch(r"(?:在.{1,16}(?:中)?)?(?:担任|任)(?:了)?" + re.escape(role), clause)):
            continue
        clause = re.sub(r"^(?:也|还|又)", "", clause)
        clause = re.sub(r"^帮忙做过?(?=公众号排版)", "协助", clause)
        clause = re.sub(r"^帮(?:忙)?(?:(.{1,8}?)做|做)", lambda m: "协助" + (m[1] or "") + "制作", clause)
        clause = re.sub(r"^(?:用|使用)(.{1,12}?)拍过", r"使用\1拍摄", clause)
        clause = re.sub(r"^(拍)(?:过|了)?", "拍摄", clause) if not clause.startswith("拍摄") else clause
        clause = re.sub(r"^写(?:过|了)?", "撰写", clause)
        clause = re.sub(r"^做(?:过|了)?", "完成", clause)
        clause = re.sub(r"(?<=[成写摄理作版计查用])过(?!程)", "", clause)
        clause = re.sub(r"[过了]$", "", clause)
        if clause and clause not in clauses:
            clauses.append(clause)
            separators.append(pieces[index + 1] if index + 1 < len(pieces) else "")
    return "".join(clause + sep for clause, sep in zip(clauses, separators)).rstrip("，,；;\n")
