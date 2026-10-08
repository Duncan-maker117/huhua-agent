"""Keep active experience limits visible when writing or trimming a document."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Mapping, Sequence

from app.services.fact_guard import normalize_text
from app.services.resume_facts import active_facts_for_writer


_STATUS_LIMIT = re.compile(r"尚未|从未|并未|没有|不曾|未曾|不负责|未(?:上线|发布|完成|部署|实现|验证|参与)|"
                           r"计划(?:中|使用|开展|开发|实现|部署|验证)|原型|模拟|"
                           r"\b(?:demo|mock|prototype|planned|not|never)\b", re.I)


def _is_limit(fact: dict) -> bool:
    # Legacy imports default to kind=action. Their explicit limits are still
    # binding; a classifier label cannot decide whether a denial is retained.
    return (not fact.get("field") or fact["field"] in {"description", "highlights"}) and (
        fact.get("kind") == "status_limit" or bool(_STATUS_LIMIT.search(fact.get("text", ""))))


def preserve_item_limits(data: dict, meta: dict, collected_info: dict, *,
                         item_ids: Sequence[str], bullet_indices: Mapping[str, set[int]] | None = None,
                         reason: str = "missing_item_status_limit") -> tuple[dict, dict, list[dict]]:
    """Append an uncited limit verbatim to one authorized bullet, at most once.

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
            limits = [fact for fact in source_items.get(identifier, {}).get("facts", [])
                      if _is_limit(fact) and fact.get("id") and fact.get("text")]
            if not limits:
                continue
            prior = records.setdefault(identifier, [])
            prior.extend({} for _ in range(max(0, len(bullets) - len(prior))))
            supported = set()
            for index, text in enumerate(bullets):
                row = prior[index]
                if row.get("text_hash") == hashlib.sha256(text.encode()).hexdigest():
                    supported.update(row.get("fact_ids") or [])
            missing = [fact for fact in limits if fact["id"] not in supported and not any(
                normalize_text(fact["text"]).rstrip("。；;.") in normalize_text(text)
                for text in bullets)]
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
                              if fact.get("id") and normalize_text(fact.get("text", "")) == normalize_text(before)]
                if exact_refs:
                    row = {"fact_ids": exact_refs}
                    sourced_before = True
            bullets[index] = "；".join([before.rstrip("。；;"), *(fact["text"].strip() for fact in missing)])
            prior[index] = {**row, "fact_ids": list(dict.fromkeys([*(row.get("fact_ids") or []),
                                                                    *(fact["id"] for fact in missing)])),
                            "text_hash": hashlib.sha256(bullets[index].encode()).hexdigest() if sourced_before else ""}
            fallbacks.append({"item_id": identifier, "bullet_index": index, "reason": reason,
                              "fact_ids": [fact["id"] for fact in missing]})
    return result, metadata, fallbacks
