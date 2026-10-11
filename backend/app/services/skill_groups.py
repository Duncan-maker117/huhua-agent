"""Deterministic skill-area cleanup: split, dedupe, fixed categories, JD ordering.

Facts and the source skill list are never edited; only the displayed groups are.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Mapping, Sequence
from app.services.resume_field_hygiene import trim_name_punctuation

CATEGORIES = ("产品方法", "AI 与 Agent", "开发", "工具", "内容运营")
MAX_PER_GROUP = 8
MAX_OTHER = 3

_VOCABULARY: tuple[tuple[str, re.Pattern], ...] = (
    ("工具", re.compile(r"^(?:claude\s*code|codex|cursor|chatgpt|gemini|figma|google\s*stitch|openclaw|notion|xmind|excel|"
                        r"copilot|axure|墨刀|飞书|jira|trae|windsurf|midjourney|stable\s*diffusion)$", re.I)),
    ("AI 与 Agent", re.compile(r"llm|rag|agent|mcp|prompt|skill|langgraph|langchain|function\s*calling|tool\s*use|embedding|"
                              r"大模型|工具调用|多\s*agent|微调|向量", re.I)),
    ("开发", re.compile(r"python|java(?!script)|javascript|typescript|spring|mysql|sql|fastapi|flask|django|git|github|redis|"
                       r"docker|linux|c\+\+|golang|\bgo\b|react|vue|node|html|css|后端|前端|接口|数据库|pytorch|rust", re.I)),
    ("内容运营", re.compile(r"抖音|短视频|内容运营|文案|新媒体|社群|小红书|公众号|体验报告|运营", re.I)),
    ("产品方法", re.compile(r"prd|竞品|用户调研|用户研究|需求|优先级|交互|原型|产品|数据分析|项目管理|调研|流程", re.I)),
)
_GROUP_ALIASES = {
    "产品能力": "产品方法", "产品与设计": "产品方法", "数据分析": "产品方法", "产品工具": "工具", "设计工具": "工具",
    "分析工具": "工具", "办公工具": "工具", "协作工具": "工具", "AI 工具": "工具", "AI工具": "工具",
    "AI与数据": "AI 与 Agent", "技术": "开发", "技术栈": "开发", "编程语言": "开发", "开发工具": "开发",
    "开发与工具": "开发", "前端": "开发", "后端": "开发", "数据库": "开发", "框架": "开发",
}
_SUFFIX = re.compile(r"(?:概念与应用场景|概念及应用|应用场景|开发经验|项目经验|辅助开发|生产级使用|熟练使用|经验|使用)$")
_PREFIX = re.compile(r"^(?:熟练使用|熟悉|掌握|使用|用(?!户))\s*")
_BRACKET = re.compile(r"[（(][^）)]*[）)]")


def _key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).casefold()


def split_skills(values: Iterable[str]) -> list[str]:
    """「类别：A / B、C 开发经验」→ ['A', 'B', 'C']; decorations such as （生产级使用） are dropped."""
    output: list[str] = []
    for raw in values:
        text = trim_name_punctuation(unicodedata.normalize("NFKC", str(raw or "")))
        if "：" in text or ":" in text:
            head, tail = re.split(r"[:：]", text, maxsplit=1)
            if len(head) <= 8 and tail.strip():
                text = tail
        text = _BRACKET.sub("", text)
        for part in re.split(r"[/、,，;；·|]|\s+及\s+|\s+和\s+", text):
            part = _PREFIX.sub("", trim_name_punctuation(part))
            part = _SUFFIX.sub("", part).strip()
            part = _SUFFIX.sub("", part).strip()
            if part:
                output.append(part)
    return output


def _category(skill: str, model_group: str) -> str:
    for name, pattern in _VOCABULARY:
        if pattern.search(skill):
            return name
    if model_group in CATEGORIES:
        return model_group
    return _GROUP_ALIASES.get(model_group, "其他")


def _relevance(skill: str, terms: Sequence[str]) -> int:
    value = _key(skill)
    return sum(1 for term in terms if term and (value in term or (len(term) >= 2 and term in value)))


def normalize_skill_groups(groups: Mapping[str, Sequence[str]], extra: Iterable[str] = (),
                           jd_terms: Iterable[str] = ()) -> dict[str, list[str]]:
    """Fixed categories, deduped, JD-ordered, ≤8 per group and ≤3 in 其他."""
    seen: dict[str, tuple[str, str]] = {}
    for name, values in groups.items():
        for skill in split_skills(values):
            seen.setdefault(_key(skill), (skill, _category(skill, name)))
    for skill in split_skills(extra):
        seen.setdefault(_key(skill), (skill, _category(skill, "")))
    terms = [_key(term) for term in jd_terms if isinstance(term, str)]
    grouped: dict[str, list[tuple[int, int, str]]] = {}
    for order, (skill, category) in enumerate(seen.values()):
        grouped.setdefault(category, []).append((-_relevance(skill, terms), order, skill))
    result: dict[str, list[str]] = {}
    for category in (*CATEGORIES, "其他"):
        rows = sorted(grouped.get(category, []))
        limit = MAX_OTHER if category == "其他" else MAX_PER_GROUP
        if rows:
            result[category] = [skill for _, _, skill in rows[:limit]]
    return result


def jd_terms_from_profile(profile: Mapping | None) -> list[str]:
    profile = profile or {}
    terms = [*(profile.get("required_skills") or []), *(profile.get("jd_language") or [])]
    terms += [row.get("signal", "") for row in profile.get("core_signals") or [] if isinstance(row, dict)]
    return [term for term in terms if isinstance(term, str)]


def sync_flat_skills(data: dict) -> bool:
    """有分组时，平铺 skills 由分组按顺序展开（去重），不再保留旧的整句。返回是否有改动。"""
    groups = data.get("skill_groups")
    if not isinstance(groups, dict) or not any(isinstance(v, list) and v for v in groups.values()):
        return False
    flat: list[str] = []
    seen: set[str] = set()
    for values in groups.values():
        for value in values if isinstance(values, list) else ():
            text = value.get("name", "") if isinstance(value, dict) else str(value)
            key = _key(text)
            if key and key not in seen:
                seen.add(key)
                flat.append(text.strip())
    changed = data.get("skills") != flat
    data["skills"] = flat
    return changed
