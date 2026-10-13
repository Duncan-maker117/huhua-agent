"""档案短字段的保守等价规则；纯函数，不读取数据库或模型。"""

import re
from datetime import date
from typing import Literal


Equivalence = Literal["same", "new_more_specific", "old_more_specific", "different"]

SKILL_ALIASES = {
    "py": "Python", "python": "Python", "js": "JavaScript", "javascript": "JavaScript",
    "ts": "TypeScript", "typescript": "TypeScript", "java": "Java", "go": "Go",
    "golang": "Go", "rust": "Rust", "c": "C", "c++": "C++", "c#": "C#",
    "node.js": "Node.js", "nodejs": "Node.js", "react": "React", "vue": "Vue",
    "next.js": "Next.js", "nextjs": "Next.js", "fastapi": "FastAPI", "django": "Django",
    "flask": "Flask", "langgraph": "LangGraph", "langchain": "LangChain",
    "mysql": "MySQL", "pg": "PostgreSQL", "postgres": "PostgreSQL", "postgresql": "PostgreSQL",
    "sqlite": "SQLite", "redis": "Redis", "mongodb": "MongoDB", "docker": "Docker",
    "k8s": "Kubernetes", "kubernetes": "Kubernetes", "git": "Git", "linux": "Linux",
    "llm": "LLM", "rag": "RAG", "mcp": "MCP", "sql": "SQL", "html": "HTML",
    "css": "CSS", "pytorch": "PyTorch", "tensorflow": "TensorFlow", "ci/cd": "CI/CD",
}
# 先保护技术专名，再拆分分隔符；不要把 C++ 的加号和 CI/CD 的斜线拆开。
SKILL_PROTECTED_NAMES = ("C++", "C#", "F#", "Node.js", "Next.js", "Vue.js", "CI/CD", "TCP/IP", ".NET")
PROFICIENCY_WORDS = ("使用过", "精通", "熟练", "熟悉", "掌握", "了解", "会")
_NEGATION = r"不会|不熟|不掌握|不了解|未|没|并非|不是|不能|不再|无"
_SKILL_NEGATION = r"不会|不熟|不掌握|不了解|未(?:曾)?(?:使用|掌握|接触|学习)|没(?:有)?(?:使用|掌握|接触|学过|学习)|并非|不是|不能|不再"


def normalize_skill(value: str) -> str:
    compact = re.sub(r"\s+", "", value).casefold()
    return re.sub(r"\s+", "", SKILL_ALIASES.get(compact, compact)).casefold()


def split_skill_values(value: str, *, deduplicate=True) -> list[dict]:
    # 否定陈述不转成正向技能，也不触发删除；只接受已有显式删除入口。
    if re.search(_SKILL_NEGATION, value):
        return []
    protected = {}

    def protect(match):
        token = f"\ue000{len(protected)}\ue001"
        protected[token] = match.group()
        return token

    def separate_conjunction(match):
        # 在保护专名前检查原文，保留中文词组；C++、.NET 等也算 ASCII 技能。
        left = re.search(r"[A-Za-z][A-Za-z0-9_.#-]*(?:\+{1,2})?[^\S\r\n]*\Z", value[:match.start()])
        right = re.match(r"[^\S\r\n]*\.?[A-Za-z]", value[match.end():])
        return ";" if left or right else match.group()

    text = re.sub(r"以及|[和及与]", separate_conjunction, value)
    # 每行只移除开头的短分组标签，不跨技能分隔符匹配。
    text = "\n".join(re.sub(r"^[^:：/、,，；;+\r\n]{1,8}[:：]\s*", "", line.strip())
                     for line in text.splitlines())
    names = "|".join(re.escape(name) for name in SKILL_PROTECTED_NAMES)
    names += r"|A[^\S\r\n]*/[^\S\r\n]*B[^\S\r\n]*(?:测试|Test)"
    pattern = r"(?<![a-z0-9])(?:" + names + r")(?![a-z0-9])"
    text = re.sub(pattern, protect, text, flags=re.I)
    result, proficiency = [], None
    for part in re.split(r"[/、,，；;+\n]", text):
        for token, original in protected.items():
            part = part.replace(token, original)
        part = part.strip()
        match = re.match(r"^(" + "|".join(PROFICIENCY_WORDS) + r")\s*(?:使用\s*)?", part)
        if match and part[match.end():].strip():
            following = part[len(match[1]):]
            if match[1] != "会" and following.startswith("使用"):
                following = following[2:]
            # 熟练度须有空白或 ASCII 技能边界，避免吞掉「会议」「熟练度」。
            if re.match(r"\s|[A-Za-z]|\.[A-Za-z]", following):
                proficiency = match[1]
                part = part[match.end():].strip()
        suffix = re.search(r"(?:\s+|[（(])(" + "|".join(PROFICIENCY_WORDS) + r")[）)]?$", part)
        if suffix and part[:suffix.start()].strip():
            proficiency = suffix[1]
            part = part[:suffix.start()].strip()
        if not part:
            continue
        canonical = SKILL_ALIASES.get(re.sub(r"\s+", "", part).casefold(), part)
        result.append({"value": canonical, "proficiency": proficiency})
    return list({normalize_skill(item["value"]): item for item in result}.values()) if deduplicate else result


def _parse_date(value):
    text = re.sub(r"\s+", "", value)
    if text in {"至今", "现在"}:
        return ("present", None, None), "none"
    if re.search(_NEGATION, text):
        return None
    match = re.search(r"(?<!\d)(\d{4})(?:年(?:(\d{1,2})月(?:(\d{1,2})日?)?)?|[./-](\d{1,2})(?:[./-](\d{1,2}))?)?(?!\d)", text)
    if not match:
        return None
    year = int(match[1])
    month = int(match[2] or match[4]) if match[2] or match[4] else None
    day = int(match[3] or match[5]) if match[3] or match[5] else None
    try:
        date(year, month if month is not None else 1, day if day is not None else 1)
    except ValueError:
        return None
    remainder = text[:match.start()] + text[match.end():]
    # 只容许时间语气和字段标签；未知修饰、区间或额外数字一律不猜。
    remainder = re.sub(r"预计|将于|计划|已经|已|于|毕业时间|毕业日期|开始时间|结束时间|毕业|入学|开始|结束|时间|日期", "", remainder)
    if remainder:
        return None
    planned = bool(re.search(r"预计|将于|计划", text))
    done = bool(re.search(r"已", text) or (not planned and re.search(r"于.*毕业", text)))
    if planned and done:
        return None
    return (year, month, day), "planned" if planned else "done" if done else "none"


_DEGREES = {
    "本科": "bachelor", "学士": "bachelor", "bachelor": "bachelor", "bs": "bachelor", "be": "bachelor",
    "硕士": "master", "研究生": "master", "master": "master", "ms": "master",
    "博士": "phd", "phd": "phd", "专科": "associate", "大专": "associate",
}
# 简称只允许明确映射，不能凭子序列把北大匹配到北京交通大学。
SCHOOL_ALIASES = {"哈商大": "哈尔滨商业大学", "北大": "北京大学", "清华": "清华大学",
                  "复旦": "复旦大学", "哈工大": "哈尔滨工业大学", "北交大": "北京交通大学"}


def _school(value):
    text = re.sub(r"\s+", "", value).casefold()
    return re.sub(r"[（(][^()（）]*校区[）)]", "", text)


def equivalent_value(category: str, field: str, old: str, new: str) -> Equivalence:
    if "date" in field.casefold() or (category in {"project", "work"} and field in {"start", "end"}):
        a, b = _parse_date(old), _parse_date(new)
        if not a or not b:
            return "different"
        if any(x is not None and y is not None and x != y for x, y in zip(a[0], b[0])):
            return "different"
        mood = {"none": 0, "planned": 1, "done": 2}
        directions = {1 if y else -1 for x, y in zip(a[0], b[0]) if (x is None) != (y is None)}
        if a[1] != b[1]:
            directions.add(1 if mood[b[1]] > mood[a[1]] else -1)
        if len(directions) > 1:
            return "different"
        return "new_more_specific" if directions == {1} else "old_more_specific" if directions == {-1} else "same"
    if category == "education" and field == "degree":
        a, b = (re.sub(r"[.\s]+", "", value).casefold() for value in (old, new))
        if a in _DEGREES and _DEGREES.get(a) == _DEGREES.get(b):
            return "same"
    if category == "education" and field == "school":
        a, b = _school(old), _school(new)
        if a == b:
            return "same"
        if SCHOOL_ALIASES.get(a) == b:
            return "new_more_specific"
        if SCHOOL_ALIASES.get(b) == a:
            return "old_more_specific"
        return "different"
    # 标点去除前守住数值、工具名和正负语义，避免 1.5/15、C++/C# 被吞掉。
    for pattern in (r"[+-]?\d+(?:\.\d+)?%?", r"[a-z][a-z0-9]*(?:\+{1,2}|#)?(?:[-./][a-z0-9]+)*", _NEGATION):
        if re.findall(pattern, old.casefold()) != re.findall(pattern, new.casefold()):
            return "different"
    def compact(value):
        return re.sub(r"[\W_]+", "", value.casefold())
    return "same" if compact(old) == compact(new) else "different"
