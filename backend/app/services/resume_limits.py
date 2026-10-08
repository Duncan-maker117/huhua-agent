"""Keep active experience limits visible when writing or trimming a document."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Mapping, Sequence

from app.services.fact_guard import _source_quote, _experience_negation_text, normalize_text
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


def preserve_item_limits(data: dict, meta: dict, collected_info: dict, *,
                         item_ids: Sequence[str], bullet_indices: Mapping[str, set[int]] | None = None,
                         reason: str = "missing_item_status_limit") -> tuple[dict, dict, list[dict]]:
    """Append missing source limitation clauses to one authorized bullet.

    A hash-matching citation means the writer guard already checked that text.
    A local edit can change only its selected bullet; other items and bullets
    remain byte-for-byte unchanged. This never creates facts or asserts fit.
    """
    result, metadata = deepcopy(data), deepcopy(meta)
    source = active_facts_for_writer(collected_info)
    source_items = {item.get("item_id"): item for section in ("projects", "work_experience", "internship")
                    for item in source.get(section, []) if isinstance(item, dict)}
    allowed = set(item_ids)
    fallbacks = []
    records = metadata.setdefault("bullets", {})
    for section in ("projects", "work_experience"):
        field = "polished_bullets" if section == "projects" else "bullets"
        for item in result.get(section, []):
            identifier = item.get("item_id")
            if identifier not in allowed or item.get("hidden"):
                continue
            bullets = item.get(field) or []
            if not bullets:
                continue
            limits = [(fact, clauses) for fact in source_items.get(identifier, {}).get("facts", [])
                      if fact.get("id") and (clauses := _limit_clauses(fact))]
            if not limits:
                continue
            prior = records.setdefault(identifier, [])
            prior.extend({} for _ in range(max(0, len(bullets) - len(prior))))
            supported = set()
            for index, text in enumerate(bullets):
                row = prior[index]
                if row.get("text_hash") == hashlib.sha256(text.encode()).hexdigest():
                    supported.update(row.get("fact_ids") or [])
            missing = []
            visible = list(bullets)
            for fact, clauses in limits:
                # A valid citation identifies the source, not every preserved
                # clause. A composite fact can retain "not launched" while
                # dropping "no outcome measurement" despite a guard pass.
                # Phase-only prose can still use the guard's approved rewrite.
                if fact["id"] in supported and not any(
                        _ASSERTED_LIMIT.search(clause) or _CONDITION_HINT.search(clause) for clause in clauses):
                    continue
                for clause in clauses:
                    if not _already_visible(clause, visible):
                        missing.append((fact["id"], clause))
                        visible.append(clause)
            if not missing:
                continue
            authorized = sorted(bullet_indices.get(identifier, set())) if bullet_indices is not None else list(range(len(bullets)))
            authorized = [index for index in authorized if 0 <= index < len(bullets)]
            if not authorized:
                continue
            index = authorized[-1]
            before = bullets[index]
            row = prior[index]
            sourced_before = row.get("text_hash") == hashlib.sha256(before.encode()).hexdigest() and bool(row.get("fact_ids"))
            if not sourced_before:
                # Manual or stale metadata cannot be reused for new provenance.
                row = {}
                exact_refs = [fact["id"] for fact in source_items.get(identifier, {}).get("facts", [])
                              if fact.get("id") and normalize_text(_source_quote(fact)) == normalize_text(before)]
                if exact_refs:
                    row = {"fact_ids": exact_refs}
                    sourced_before = True
            missing_ids = list(dict.fromkeys(identifier for identifier, _ in missing))
            bullets[index] = "；".join([before.rstrip("。；;"), *(clause for _, clause in missing)])
            prior[index] = {**row, "fact_ids": list(dict.fromkeys([*(row.get("fact_ids") or []),
                                                                    *missing_ids])),
                            "text_hash": hashlib.sha256(bullets[index].encode()).hexdigest() if sourced_before else ""}
            fallbacks.append({"item_id": identifier, "bullet_index": index, "reason": reason,
                              "fact_ids": missing_ids})
    return result, metadata, fallbacks
