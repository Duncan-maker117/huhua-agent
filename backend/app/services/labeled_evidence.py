"""Narrow equivalent wording for labeled facts; never fuzzy-match claims."""
import re

from app.services.fact_guard import normalize_text

# Only these equivalent manner/degree forms are folded. No removal of 否定,
# 仅/约/至少, units, 虚拟/本地, disjunctions, or result/frequency upgrades.
PAIN_EQUIVALENTS = (
    (r'一个一个|逐个|逐一', '逐项'),
    (r'繁杂|低效', '繁琐'),
    (r'复制粘体', '复制粘贴'),
)


def equivalent_wording(text: str, slot: str) -> str:
    value = str(text or '')
    if slot == '问题':
        for pattern, replacement in PAIN_EQUIVALENTS:
            value = re.sub(pattern, replacement, value)
    return value


def clauses(text: str) -> list[str]:
    return [part.strip() for part in re.split(r'[，,；;。\n]', text) if part.strip()]


def literal_clause(clause: str, sources: list[str], slot: str, *, retention: bool = False) -> bool:
    """Whole source clauses only: a substring may remove a negation/limit."""
    def key(value):
        if retention:
            value = re.sub(r'甚至|非常', '', value)
        return normalize_text(equivalent_wording(value, slot)).strip('。；; ')
    return any(key(clause) == key(part) for source in sources for part in clauses(source))
