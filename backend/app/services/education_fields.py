"""Literal education values shared by intake, legacy reads and rendering."""
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


def clean_resume_education(data: dict) -> dict:
    if "education" not in data:
        return data
    return {**data, "education": [clean_education_item(item) if isinstance(item, dict) else item
                                  for item in data.get("education") or []]}
