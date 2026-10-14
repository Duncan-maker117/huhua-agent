"""Check the delivered text, not merely the IDs a writer chose to cite."""
import re
from collections import Counter

from app.schemas.facts import FACT_SECTIONS
from app.services.candidate_language import resume_bullet
from app.services.fact_guard import duplicate_key, lexical_fact_errors, normalize_text, strip_absence
from app.services.resume_facts import active_facts_for_writer
from app.services.resume_versions import text_hash


def text_covered(text: str, bullets: list[str]) -> bool:
    from app.agents.fact_extractor import _clause_covered
    def normalized(value):
        value = duplicate_key(value)
        return re.sub(r"(?<=[做用写查改])了", "", value)
    clauses = [normalized(part) for part in re.split(r"[，,。；;\n、]", text) if normalize_text(part)]
    quotes = [normalized(value) for value in bullets if value]
    # _clause_covered's reverse-substring rule is useful during extraction but
    # cannot prove a whole responsibility survived a shorter written fragment.
    return bool(clauses) and all(any(
        _clause_covered(clause, [quote]) and not (quote in clause and quote != clause)
        and not lexical_fact_errors(clause, quote)
        for quote in quotes) for clause in clauses)


def ensure_fact_coverage(data: dict, meta: dict, collected: dict, *, repair_ids=(), withheld=None, caps=None) -> dict:
    """Restore uncovered body facts, or record an explicit per-fact omission.

    A caller may protect an explicit count/backup choice by supplying withheld
    reasons. No LLM inference, cross-item matching, or new claims occur here.
    """
    repair_ids, withheld, caps = set(repair_ids), withheld or {}, caps or {}
    prior_omissions = {row["fact_id"]: row["reason"] for row in (meta.get("fact_coverage") or {}).get("facts", [])
                       if row.get("status") == "omitted" and row.get("reason")}
    source = active_facts_for_writer(collected)
    id_counts = Counter(fact["id"] for section in FACT_SECTIONS for item in source.get(section) or []
                        for fact in item.get("facts") or [])
    rows, restored = [], 0
    visible_sections = {row["kind"] for row in data["sections"]} if data.get("sections") is not None else None
    for source_section in FACT_SECTIONS:
        section = "work_experience" if source_section == "internship" else source_section
        for original in source.get(source_section) or []:
            item_id = original["item_id"]
            item = next((row for row in data.get(section) or [] if row.get("item_id") == item_id), None)
            field = "polished_bullets" if section == "projects" else "bullets"
            hidden = item is None or item.get("hidden") or (visible_sections is not None and section not in visible_sections)
            facts = original.get("facts") or []
            for fact in facts:
                text = resume_bullet(strip_absence(fact["text"]), name=original.get("name") or original.get("company") or "",
                                     role=(item or {}).get("role") or (item or {}).get("title") or "")
                fact_field = fact.get("field")
                body = list((item or {}).get(field) or [])
                displayed_body = body or [str((item or {}).get("description") or "")]
                headers = [str((item or {}).get(key) or "") for key in
                           ("name", "company", "school", "role", "title", "start_date", "end_date", "major", "degree", "summary", "pr", "level", "date", "highlights")]
                if section == "education" or fact_field:
                    covered = not hidden and text_covered(text or fact["text"], headers + displayed_body)
                else:
                    covered = not hidden and text_covered(text, displayed_body)
                reason = ""
                if not covered:
                    if hidden:
                        reason = withheld.get(item_id) or "经历或栏目设为备用，不在本版展示"
                    elif not text:
                        reason = "自评、提问或未发生事项，仅保留在事实记录"
                    elif id_counts[fact["id"]] > 1:
                        reason = "事实标识冲突，待核对后展示"
                    elif text_covered(text, headers):
                        covered = True
                    elif item_id in withheld:
                        reason = withheld[item_id]
                    elif item_id in caps and len(body) >= caps[item_id]:
                        reason = "本版条数上限，未覆盖的职责保留为备用"
                    elif not fact_field and section != "education" and item_id in repair_ids:
                        # A compound fact can cover several existing fragments.
                        # Keep the complete literal rewrite once, with all IDs.
                        records = meta.setdefault("bullets", {}).setdefault(item_id, [])
                        records.extend({} for _ in range(max(0, len(body) - len(records))))
                        subsumed = [i for i, value in enumerate(body) if text_covered(value, [text])]
                        refs = list(dict.fromkeys([fact["id"], *(fid for i in subsumed for fid in records[i].get("fact_ids", []))]))
                        body = [value for i, value in enumerate(body) if i not in subsumed]
                        records = [record for i, record in enumerate(records) if i not in subsumed]
                        body.append(text)
                        records.append({"fact_ids": refs, "req_ids": [], "flags": [], "needs_metric": False,
                                        "metric_question": "", "text_hash": text_hash(text)})
                        item[field], meta["bullets"][item_id] = body, records
                        covered, restored = True, restored + 1
                    else:
                        reason = prior_omissions.get(fact["id"]) or "本次编辑范围或篇幅取舍，保留为备用事实"
                rows.append({"fact_id": fact["id"], "item_id": item_id,
                             "text": fact["text"],
                             "status": "covered" if covered else "omitted", **({"reason": reason} if reason else {})})
    covered = sum(row["status"] == "covered" for row in rows)
    report = {"total": len(rows), "covered": covered, "coverage_rate": covered / len(rows) if rows else 1.0,
              "restored": restored, "facts": rows}
    meta["fact_coverage"] = report
    return report


def coverage_notice(report: dict) -> str:
    omitted = [row for row in report.get("facts", []) if row["status"] == "omitted"]
    reasons = {}
    for row in omitted:
        reasons.setdefault(row["reason"], []).append(row.get("text") or row["fact_id"])
    details = [reason + "（" + "；".join(dict.fromkeys(texts)) + "）" for reason, texts in reasons.items()]
    return f"{len(omitted)} 条已确认事实保留为备用、不展示：{'；'.join(details)}。" if omitted else ""
