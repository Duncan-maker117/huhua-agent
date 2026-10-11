"""Narrow field checks shared by intake and legacy resume presentation."""

import re
import unicodedata


def _punctuation(char: str) -> bool:
    return unicodedata.category(char).startswith("P") or char in "|｜"


def trim_name_punctuation(value: str) -> str:
    value = str(value or "").strip()
    pairs = {"(": ")", "（": "）", "[": "]", "【": "】", "「": "」", "『": "』", "“": "”", "‘": "’"}
    stack, matched = [], set()
    for index, char in enumerate(value):
        if char in pairs:
            stack.append((index, char))
        elif stack and char == pairs.get(stack[-1][1], stack[-1][1]):
            matched.update((stack.pop()[0], index))
        elif char in {'"', "'"}:
            if stack and stack[-1][1] == char:
                matched.update((stack.pop()[0], index))
            else:
                stack.append((index, char))
    brackets = set(pairs) | set(pairs.values())
    value = "".join(char for index, char in enumerate(value) if char not in brackets or index in matched)
    return value.strip().strip("。.，,；;！!？?、").strip()


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


def strip_pr_prefix(text: str, pr: str) -> str:
    """Remove only a leading echo of this contribution's title PR number."""
    number = re.fullmatch(r"(?:PR\s*)?#?\s*(\d+)", str(pr or "").strip(), re.I)
    if not number:
        return text
    return re.sub(r"^\s*(?:PR\s*#?\s*|#\s*)" + re.escape(number[1]) + r"(?!\d)(?:\s*[：:、|｜—–-]\s*|\s+)",
                  "", text, count=1, flags=re.I)


def contribution_title(item: dict) -> str:
    name = item.get("name") or ""
    if item.get("summary"):
        name += "（" + item["summary"] + "）"
    return name + ("｜ " + item["pr"] if item.get("pr") else "")


def award_label(item: dict) -> str:
    return " ".join(value for value in (item.get("name"), item.get("level"), item.get("date")) if value)


def display_bullets(item: dict, kind: str) -> list[tuple[int, str]]:
    """Hide header echoes while preserving canonical bullet indices for editing."""
    headers = set()
    if kind == "awards":
        name, level = item.get("name") or "", item.get("level") or ""
        headers = {_compact(name), _compact(level), _compact(name + level)} - {""}
    rows = []
    for index, bullet in enumerate(item.get("bullets") or []):
        if kind == "open_source":
            bullet = strip_pr_prefix(bullet, item.get("pr"))
        if bullet.strip() and _compact(bullet) not in headers:
            rows.append((index, bullet))
    return rows
