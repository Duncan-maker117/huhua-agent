"""Narrow field checks shared by intake and legacy resume presentation."""

import re
import unicodedata


def _punctuation(char: str) -> bool:
    return unicodedata.category(char).startswith("P") or char in "|｜"


def trim_name_punctuation(value: str) -> str:
    value = str(value or "").strip()
    while value and _punctuation(value[0]):
        value = value[1:].lstrip()
    while value and _punctuation(value[-1]):
        value = value[:-1].rstrip()
    return value


def _compact(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", str(value or "")).casefold()
                   if not char.isspace() and not _punctuation(char))


def is_project_status(value: str) -> bool:
    """Match pure phase labels, never a role such as 原型设计负责人."""
    return bool(re.fullmatch(
        r"(?:(?:课程原型|产品原型|原型|demo|prototype|mvp|未上线|尚未上线|没上线|已上线|"
        r"上线中|开发中|测试中|内测中|公测中|已发布|未发布|已开源|未开源)(?:版|阶段)?)+",
        _compact(value),
    ))


def project_role(value: str) -> str:
    return "" if is_project_status(value) else value


def display_bullets(item: dict, kind: str) -> list[tuple[int, str]]:
    """Hide header echoes while preserving canonical bullet indices for editing."""
    headers = set()
    if kind == "awards":
        name, level = item.get("name") or "", item.get("level") or ""
        headers = {_compact(name), _compact(level), _compact(name + level)} - {""}
    return [(index, bullet) for index, bullet in enumerate(item.get("bullets") or [])
            if _compact(bullet) not in headers]
