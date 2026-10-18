"""基本信息的确定性字段边界；表单、归档和存量迁移共用。"""

import re

ALIASES = {
    "姓名": "name", "name": "name", "所在城市": "location", "所在地": "location", "城市": "location", "location": "location",
    "手机": "phone", "电话": "phone", "手机号": "phone", "phone": "phone", "邮箱": "email", "email": "email",
    "到岗 / 可实习时间": "availability", "可实习时间": "availability", "到岗时间": "availability", "availability": "availability",
    "学校": "school", "school": "school", "专业": "major", "major": "major", "学历": "degree", "degree": "degree",
    "毕业时间": "end_date", "graduation": "end_date", "链接": "link", "GitHub": "link", "个人主页": "link",
}
EDUCATION_FIELDS = {"school", "major", "degree", "end_date"}
KEY_VALUE = re.compile(r"(?:^|[，,；;\n])\s*(" + "|".join(map(re.escape, sorted(ALIASES, key=len, reverse=True))) + r")\s*[:：]\s*", re.I)
URL = re.compile(r"^(?:https?://|www\.)\S+$", re.I)
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE = re.compile(r"^\+?[\d\s()（）-]{7,20}$")


def split_fields(text):
    matches = list(KEY_VALUE.finditer(text))
    return [(next(value for key, value in ALIASES.items() if key.casefold() == m[1].casefold()), text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip().rstrip("，,；;"))
            for i, m in enumerate(matches)]


def structured_basics(text):
    match = re.fullmatch(r"\s*基本信息[:：]\s*(.*)", text, re.S)
    return split_fields(match[1]) if match else []


def clean_basic(field, value):
    field = ALIASES.get(field, field)
    value = value.strip()
    if field in {"github", "website"}:
        field = "link"
    if field == "location":
        if URL.fullmatch(value):
            return "link", value
        if EMAIL.fullmatch(value):
            return "email", value
        if PHONE.fullmatch(value):
            return "phone", value
    if field == "name" and (URL.fullmatch(value) or EMAIL.fullmatch(value) or re.search(r"[:：\n]", value)):
        raise ValueError("invalid_basic_name")
    if field == "location" and re.search(r"https?://|www\.|@|\d{7,}|[:：\n]", value, re.I):
        raise ValueError("invalid_basic_location")
    if KEY_VALUE.search(value) or KEY_VALUE.search("," + value):
        raise ValueError("mixed_basic_fields")
    return field, value


def basic_subject(field, subject=""):
    return "本人"


def value_key(value):
    return re.sub(r"\s+", "", value).casefold()
