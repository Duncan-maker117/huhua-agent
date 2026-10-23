"""Literal education values shared by intake, legacy reads and rendering."""
from copy import deepcopy
import re


FIELDS = {"school", "major", "degree", "start_date", "end_date"}
_LABELS = {
    "school": r"学校(?:名称|名字)?|毕业院校|就读院校|就读于|毕业于",
    "major": r"所学专业|专业名称|专业",
    "degree": r"最高学历|学历|学位",
    "start_date": r"入学(?:年份|时间|日期)?|开始(?:时间|日期)?",
    "end_date": r"毕业(?:年份|时间|日期)?|毕业于|结束(?:时间|日期)?",
}


def clean_education_value(field: str, value: str) -> str:
    if field in {'highlights', 'description'} and isinstance(value, str):
        from app.services.candidate_language import editorial_absence
        return ''.join(part for part in re.split(r'(?<=[。；;\n])', value) if not editorial_absence(part))
    if field not in FIELDS or not isinstance(value, str):
        return value
    value = value.strip()
    value = re.sub(r"^(?:我的|本人)?(?:" + _LABELS[field] + r")(?:为|是|于)?\s*[：:]?\s*", "", value)
    value = re.sub(r"^(?:为|是)\s*", "", value).strip(" 。；;")
    if field == 'school':
        value = re.sub(r'^在(?=.{2,}(?:大学|学院)$)', '', value)
    if field in {"start_date", "end_date"}:
        value = re.sub(r"(?:毕业|入学)$", "", value).strip()
        match = re.fullmatch(r"(\d{4})年(?:(\d{1,2})月)?", value)
        if match:
            value = match[1] + (f".{int(match[2]):02d}" if match[2] else "")
    return value


def clean_education_item(item: dict) -> dict:
    return {key: clean_education_value(key, value) for key, value in item.items()}


def recover_education_identity(item: dict) -> None:
    """Recover a literal school/major/degree header retained as a single fact."""
    school = item.get('school')
    if not school:
        return
    for fact in list(item.get('facts') or []):
        if fact.get('status', 'active') != 'active' or fact.get('field'):
            continue
        match = re.search(re.escape(school) + r'\s+([\w与和]{2,30})\s+(本科|硕士|博士|大专|专科)(?=\s|$)', fact['text'])
        if not match:
            continue
        for field, value in (('major', match[1]), ('degree', match[2])):
            if not item.get(field):
                item[field] = value
                item['facts'].append({**deepcopy(fact), 'id': fact['id'] + '__' + field,
                                      'field': field, 'kind': 'context', 'text': value})


def clean_resume_education(data: dict) -> dict:
    if "education" not in data:
        return data
    return {**data, "education": [clean_education_item(item) if isinstance(item, dict) else item
                                  for item in data.get("education") or []]}
