"""Deterministic contract for JD-focus / compress / keep-role edits.

The model writes; this module only decides what must survive, how rows are
ordered, and whether an edit changed anything at all.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Iterable, Mapping, Sequence

from app.services.fact_guard import normalize_text, strip_absence

_JD_FOCUS = re.compile(r"按\s*JD|JD\s*(?:再)?改|突出|最相关|侧重|对口|贴合|更符合岗位")
_COMPRESS = re.compile(r"(?:描述|内容|bullet|经历)[^。；;]{0,8}(?:精简|压缩|压成|缩短)|精简成一条|合并成一条|压成一条")
_KEEP_ROLES = re.compile(r"保留[^。；;]{0,16}(?:团队分工|分工|本人工作|状态限制)")
SUBSTANTIVE = {"action", "method_tool", "deliverable", "result_metric", "result_qualitative"}
NOOP_SIMILARITY = 0.9


def edit_modes(instruction: str) -> dict[str, bool]:
    text = instruction or ""
    return {"jd_focus": bool(_JD_FOCUS.search(text)), "compress": bool(_COMPRESS.search(text)),
            "keep_roles": bool(_KEEP_ROLES.search(text))}


def active(modes: Mapping[str, bool]) -> bool:
    return any(modes.values())


def jd_terms(profile: Mapping | None) -> list[str]:
    profile = profile or {}
    terms = [*(profile.get("jd_language") or []), *(profile.get("required_skills") or [])]
    for row in profile.get("core_signals") or []:
        if isinstance(row, dict):
            terms += [row.get("signal") or "", *(row.get("jd_quotes") or [])]
    for row in profile.get("requirements") or []:
        if isinstance(row, dict):
            terms += [row.get("text") or "", *(row.get("jd_quotes") or [])]
    return [term.strip() for term in terms if isinstance(term, str) and len(term.strip()) >= 2]


def _keywords(terms: Iterable[str]) -> set[str]:
    words = set()
    for term in terms:
        for part in re.split(r"[\s,，、;；/（）()：:。]+", term):
            if len(part) >= 2:
                words.add(normalize_text(part))
                if re.search(r"[一-鿿]", part) and len(part) >= 4:
                    words.update(normalize_text(part[i:i + 2]) for i in range(len(part) - 1))
    return {word for word in words if word}


def relevance(text: str, terms: Sequence[str]) -> int:
    """How many JD keywords (and 2-char pieces of JD phrases) a text speaks to."""
    value = normalize_text(text)
    return sum(1 for word in _keywords(terms) if word in value)


def fact_req_ids(fact_text: str, profile: Mapping | None) -> list[str]:
    """Requirement / signal ids a fact speaks to (keyword overlap, no model)."""
    ids = []
    for row in (profile or {}).get("requirements") or []:
        if isinstance(row, dict) and row.get("id") and relevance(fact_text, [row.get("text") or "", *(row.get("jd_quotes") or [])]) >= 2:
            ids.append(row["id"])
    for row in (profile or {}).get("core_signals") or []:
        if isinstance(row, dict) and row.get("id") and relevance(fact_text, [row.get("signal") or "", *(row.get("jd_quotes") or [])]) >= 2:
            ids.append(row["id"])
    return ids


def required_fact_ids(item_facts: Sequence[dict], prior_records: Sequence[dict], profile: Mapping | None,
                      modes: Mapping[str, bool]) -> set[str]:
    """Facts the pre-edit draft cited that the edit may reword or merge but must still cite."""
    by_id = {fact.get("id"): fact for fact in item_facts if fact.get("id")}
    required: set[str] = set()
    cited = {fid for record in prior_records if isinstance(record, dict) for fid in record.get("fact_ids") or []}
    if modes.get("jd_focus") or modes.get("compress"):
        terms = jd_terms(profile)
        exact = [term for term in [*(profile or {}).get("jd_language", []), *(profile or {}).get("required_skills", [])]
                 if isinstance(term, str)]
        for record in prior_records:
            if not isinstance(record, dict):
                continue
            for fid in record.get("fact_ids") or []:
                fact = by_id.get(fid)
                if fact and fact.get("kind") in SUBSTANTIVE | {"role", "team"}:
                    text = fact.get("text") or ""
                    if relevance(text, exact) >= 1 or relevance(text, terms) >= 2 or fact_req_ids(text, profile):
                        required.add(fid)
    if modes.get("keep_roles"):
        for fid, fact in by_id.items():
            if fact.get("kind") in {"role", "team"} and strip_absence(fact.get("text") or "") and (fid in cited or True):
                required.add(fid)
    return {fid for fid in required if fid in by_id}


def order_rows(rows: list[dict], facts: Mapping[str, dict], profile: Mapping | None) -> list[dict]:
    """The bullet that speaks most to the JD goes first; ties keep the writer's order."""
    terms = jd_terms(profile)

    def score(row):
        fact_score = sum(relevance(facts.get(fid, {}).get("text") or "", terms) for fid in row.get("fact_ids") or [])
        return relevance(row.get("text", ""), terms) * 2 + fact_score + 3 * bool(row.get("req_ids"))

    scored = [(-score(row), index, row) for index, row in enumerate(rows)]
    return [row for _, _, row in sorted(scored, key=lambda value: (value[0], value[1]))]


def is_noop(prior_texts: Sequence[str], new_texts: Sequence[str]) -> bool:
    if not prior_texts or not new_texts:
        return False
    before = normalize_text("".join(prior_texts))
    after = normalize_text("".join(new_texts))
    same_first = normalize_text(prior_texts[0]) == normalize_text(new_texts[0]) or SequenceMatcher(
        None, normalize_text(prior_texts[0]), normalize_text(new_texts[0])).ratio() >= NOOP_SIMILARITY
    return same_first and SequenceMatcher(None, before, after).ratio() >= NOOP_SIMILARITY


def retry_plan(rows: Sequence[dict], facts: Mapping[str, dict], profile: Mapping | None) -> str:
    """A concrete plan for the one retry: lead with the most relevant fact and use JD wording."""
    terms = jd_terms(profile)
    best = max(rows, key=lambda row: sum(relevance(facts.get(fid, {}).get("text") or "", terms)
                                         for fid in row.get("fact_ids") or []), default=None)
    lead = ""
    if best:
        lead = next((facts[fid]["text"] for fid in best.get("fact_ids") or [] if fid in facts), "")
    wording = [term for term in (profile or {}).get("jd_language") or [] if isinstance(term, str)][:4]
    return (f"请以「{lead}」对应的 bullet 开头；" if lead else "") + (
        f"用 JD 词「{'、'.join(wording)}」描述同一事实（来源里已有的动作与产出，不新增事实）；" if wording else "") + \
        "不要只换同义词，必须调整排序或详略。"
