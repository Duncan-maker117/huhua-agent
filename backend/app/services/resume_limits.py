"""Keep active experience limits visible when writing or trimming a document."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Mapping, Sequence

from app.services.fact_guard import (
    _experience_negation_text, _source_quote, absence_printed, contradicts_limit,
    normalize_text, strip_absence,
)
from app.services.resume_facts import active_facts_for_writer


_ASSERTED_LIMIT = re.compile(
    r"尚未|从未|并未|没有|不曾|未曾|不负责|不是|并非|不属于|"
    r"(?:未|没)(?:上线|发布|完成|部署|实现|验证|参与|测试|统计|做|测)|"
    r"计划|准备|打算|仅(?:负责|参与|完成)|只(?:负责|参与|完成)|"
    r"\b(?:planned|not|never|without)\b", re.I)
_PHASE_LIMITS = (
    re.compile(r"原型|\bprototype\b", re.I),
    re.compile(r"\bdemo\b", re.I),
    re.compile(r"模拟|\bmock\b", re.I),
)
_STATUS_LIMIT = re.compile(
    _ASSERTED_LIMIT.pattern + r"|原型|模拟|\b(?:demo|mock|prototype)\b", re.I)
_SENTENCE_BREAK = re.compile(r"[。；;！？!?\n]+")
_COMMA_BREAK = re.compile(r"[，]|,(?!\d)")
_CLAUSE_BREAK = re.compile(r"[。；;！？!?\n]+|[，]|,(?!\d)")
_CONDITION_HINT = re.compile(
    r"如果|若|除非|只有|前提|条件|取决于|等待|要等|须经|批准|审批|验收|"
    r"在[^，,；;。]*(?:时|情况下)")
_BARE_LIMIT = re.compile(r"^(?:尚未|从未|并未|没有|不曾|未曾|未|没|计划|准备|打算)")
_SUBJECT_END = re.compile(r"(?:模块|功能|接口|系统|项目|页面|版本|环境|方案|服务|数据|统计|测试|流程|评估|工作)$")


def _limit_clauses(fact: dict) -> list[str]:
    """Extract intact source clauses, never a limitation invented by fact.text.

    The guard's legacy fallback applies only when the original quote is absent.
    Kind is not evidence: imported action prose can be tagged status_limit just
    because it mentions a prototype. Keep only the relevant original clauses.
    """
    if fact.get("field") and fact["field"] not in {"description", "highlights"}:
        return []
    source = _source_quote(fact).strip()
    if not source or not _STATUS_LIMIT.search(_experience_negation_text(source)):
        return []
    limits = []
    for sentence in _SENTENCE_BREAK.split(source):
        clauses = [part.strip() for part in _COMMA_BREAK.split(sentence) if part.strip()]
        if any(_STATUS_LIMIT.search(_experience_negation_text(clause)) for clause in clauses) and _CONDITION_HINT.search(sentence):
            # Do not detach a plan from prerequisites, including a condition
            # inside a clause or after the action. Approval/acceptance/waiting
            # hints are deliberately conservative: ambiguity retains the full
            # sentence instead of making a conditional action unconditional.
            limits.append(sentence.strip())
            continue
        for index, clause in enumerate(clauses):
            if not _STATUS_LIMIT.search(_experience_negation_text(clause)):
                continue
            # “支付模块，尚未上线” and “若审批通过，计划部署” must not
            # become a claim about the entire project or an unconditional plan.
            start = index
            if index:
                previous = clauses[index - 1]
                subject_fragment = (_BARE_LIMIT.search(clause) and len(previous) <= 40
                                    and _SUBJECT_END.search(previous))
                if subject_fragment:
                    start -= 1
            limits.append("，".join(clauses[start:index + 1]))
    return list(dict.fromkeys(limits))


def _phase_markers(text: str) -> set[int]:
    """Visible phase markers count only as affirmative, current statements."""
    phases = set()
    for clause in _CLAUSE_BREAK.split(text):
        for number, pattern in enumerate(_PHASE_LIMITS):
            for match in pattern.finditer(clause):
                prefix = clause[:match.start()]
                if _ASSERTED_LIMIT.search(prefix):
                    continue
                phases.add(number)
    return phases


def _limit_key(text: str) -> str:
    # Only a narrow grammatical equivalence, preserving the action and object.
    return re.sub(r"尚未|并未|还未|没有", "未", normalize_text(text)).strip("。；;.,，")


def _already_visible(clause: str, texts: Sequence[str]) -> bool:
    key = _limit_key(clause)
    if key and any(key in _limit_key(text) for text in texts):
        return True
    # A prototype stage need not repeat whole imported action paragraphs. This
    # shortcut never discharges a negation, future plan, or responsibility limit.
    if not _ASSERTED_LIMIT.search(clause) and not _CONDITION_HINT.search(clause):
        wanted = _phase_markers(clause)
        # Mock/demo can qualify individual data or interfaces; seeing the word
        # elsewhere is insufficient. Explicit subsystem prototype scope is also
        # retained, even if another part of the same item already says 原型.
        if wanted != {0} or re.search(r"模块|接口|页面|功能|环境|数据|服务", clause):
            return False
        visible = set().union(*(_phase_markers(text) for text in texts))
        return bool(wanted) and wanted <= visible
    return False


_PHASES = (
    ("课程原型", re.compile(r"课程原型")),
    ("原型", re.compile(r"原型|prototype", re.I)),
    ("Demo", re.compile(r"\bdemo\b", re.I)),
    ("模拟数据", re.compile(r"模拟数据|\bmock\b", re.I)),
    ("小组作业", re.compile(r"小组作业")),
)


def _phase_label(text: str) -> str:
    """Current stage word. A plan or a denial does not count as the stage."""
    for clause in re.split(r"[，,。；;\n]", text or ""):
        if re.search(r"计划|准备|打算|并非|不是", clause):
            continue
        for label, pattern in _PHASES:
            if pattern.search(clause):
                return label
    return ""


_STAGE_PHRASE = re.compile(
    r"[，,；;]?\s*(?:在|以|作为|基于)(?:这个|该|此)?(?:课程原型|原型|[Dd]emo|模拟数据|小组作业)(?:项目)?"
    r"(?:中|里|形式|下|阶段)?(?:的)?")


def strip_stage_phrases(text: str) -> str:
    """去掉与标题行重复的阶段短语（「…，在课程原型中实现行程推荐」→「…，实现行程推荐」）。"""
    cleaned = _STAGE_PHRASE.sub(lambda m: "，" if m.group(0)[:1] in "，,；;" else "", text or "")
    return re.sub(r"^[，,；;\s]+|[，,；;\s]+$", "", re.sub(r"[，,]{2,}", "，", cleaned))


def preserve_item_limits(data: dict, meta: dict, collected_info: dict, *,
                         item_ids: Sequence[str], bullet_indices: Mapping[str, set[int]] | None = None,
                         reason: str = "contradicted_status_limit") -> tuple[dict, dict, list[dict]]:
    """Keep limits as prohibitions. Do not paste absence or plan sentences into bullets.

    A stage word is written once on the role line when neither the title nor a
    bullet already states it. A bullet that asserts the denied outcome is
    recorded; the missing sentence is not appended.
    """
    result, metadata = deepcopy(data), deepcopy(meta)
    source = active_facts_for_writer(collected_info)
    source_items = {item.get("item_id"): item for section in ("projects", "work_experience", "internship")
                    for item in source.get(section, []) if isinstance(item, dict)}
    allowed = set(item_ids)
    fallbacks = []
    for section in ("projects", "work_experience"):
        field = "polished_bullets" if section == "projects" else "bullets"
        for item in result.get(section, []):
            identifier = item.get("item_id")
            if identifier not in allowed or item.get("hidden"):
                continue
            facts = [fact for fact in source_items.get(identifier, {}).get("facts", [])
                     if fact.get("status", "active") == "active"]
            quotes = "\n".join(_source_quote(fact) for fact in facts)
            phase = _phase_label(quotes)
            bullets = [cleaned for text in (item.get(field) or [])
                       if isinstance(text, str) and (cleaned := strip_absence(text))]
            item[field] = bullets
            if isinstance(item.get("description"), str):
                item["description"] = "\n".join(
                    cleaned for line in item["description"].splitlines() if (cleaned := strip_absence(line)))
            visible = "\n".join([str(item.get("name") or ""), str(item.get("company") or ""),
                                 str(item.get("role") or ""), *bullets])
            strippable = any(isinstance(text, str) and strip_stage_phrases(text) != text for text in bullets)
            if phase and not _phase_label(" ".join(str(item.get(key) or "") for key in ("name", "company", "role"))) \
                    and (strippable or not _phase_label(visible)):
                role = str(item.get("role") or "").strip()
                item["role"] = f"{role} · {phase}".strip(" ·")
            authorized = None if bullet_indices is None else {
                index for index in bullet_indices.get(identifier, set()) if isinstance(index, int)}
            header = " ".join(str(item.get(key) or "") for key in ("name", "company", "role"))
            if _phase_label(header):
                # 标题行已表达阶段，bullet 里的「在课程原型中…」「以原型形式…」重复短语去掉
                bullets = [strip_stage_phrases(text) if isinstance(text, str) and (
                    authorized is None or index in authorized) else text for index, text in enumerate(bullets)]
                bullets = [text for text in bullets if not isinstance(text, str) or text.strip()]
                item[field] = bullets
            for index, text in enumerate(bullets):
                if not isinstance(text, str):
                    continue
                if authorized is not None and index not in authorized:
                    continue
                if contradicts_limit(text, quotes):
                    fallbacks.append({"item_id": identifier, "bullet_index": index, "reason": reason,
                                      "fact_ids": [fact["id"] for fact in facts if fact.get("id")][:4]})
    return result, metadata, fallbacks
