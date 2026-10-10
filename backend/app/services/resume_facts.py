"""Fact master migration and the narrow bridge for manual editor statements."""
from __future__ import annotations

import copy
import re
import uuid

from app.schemas.facts import FACT_KINDS, FACT_SECTIONS, FACT_SOURCES, FACT_STATUSES


def new_fact(text: str, *, kind: str = "action", quote: str | None = None,
             source: str = "chat", turn_id: str = "", source_name: str = "") -> dict:
    quote = (quote if quote is not None else text).strip()
    fact = {"id": f"f_{uuid.uuid4().hex}", "kind": kind if kind in FACT_KINDS else "context",
            "text": text.strip(), "source_quote": quote, "turn_id": turn_id,
            "status": "active", "source": source if source in FACT_SOURCES else "chat",
            "sources": [{"source": source if source in FACT_SOURCES else "chat",
                         "source_quote": quote, "turn_id": turn_id, **({"name": source_name} if source_name else {})}]}
    return fact


def _lines(value: str) -> list[str]:
    return [part.strip(" \t-*•▸") for part in re.split(r"\n+", value) if part.strip(" \t-*•▸")]


def _normalized_fact(fact: dict) -> dict | None:
    if not isinstance(fact, dict) or not str(fact.get("text", "")).strip():
        return None
    result = copy.deepcopy(fact)
    result.setdefault("id", f"f_{uuid.uuid4().hex}")
    result["kind"] = result.get("kind") if result.get("kind") in FACT_KINDS else "context"
    result["status"] = result.get("status") if result.get("status") in FACT_STATUSES else "active"
    result["source"] = result.get("source") if result.get("source") in FACT_SOURCES else "chat"
    result.setdefault("source_quote", result["text"])
    result.setdefault("turn_id", "")
    result.setdefault("sources", [{"source": result["source"], "source_quote": result["source_quote"],
                                   "turn_id": result["turn_id"]}])
    return result


def _fold_value(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _education_values(store: dict) -> set[str]:
    """学校/专业/学历/年级的取值不是技能（专业「计算机科学与技术」不能出现在技能栏）。"""
    values = set()
    for item in store.get("education") or []:
        if not isinstance(item, dict):
            continue
        values.update(_fold_value(item.get(key)) for key in ("school", "major", "degree", "grade"))
        for fact in item.get("facts") or []:
            if isinstance(fact, dict) and fact.get("field") in {"school", "major", "degree", "grade"}:
                values.add(_fold_value(fact.get("text")))
    values.discard("")
    return values


def normalize_fact_store(collected: dict | None) -> dict:
    """Upgrade legacy raw descriptions without interpreting polished draft text as evidence."""
    result = copy.deepcopy(collected or {})
    for section in FACT_SECTIONS:
        items = result.get(section)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if not item.get("item_id"):
                item["item_id"] = str(uuid.uuid4())
            had_fact_field = "facts" in item
            facts = [normalized for fact in item.get("facts", [])
                     if (normalized := _normalized_fact(fact))]
            polished = "\n".join(item.get("polished_bullets") or [])
            description = item.get("description") or ""
            raw = item.get("raw_description") or (description if description.strip() != polished.strip() else "")
            # A legacy item may have both a source description and a rendered draft.
            # Only the source field is eligible for migration.
            if not had_fact_field and isinstance(raw, str):
                source = "import" if result.get("imported_documents") else "chat"
                facts = [new_fact(line, quote=line, source=source) for line in _lines(raw)]
                for field, kind in (("role", "role"), ("title", "role"), ("degree", "context"),
                                    ("major", "context"), ("start_date", "context"), ("end_date", "context"),
                                    ("duration", "context"), ("highlights", "action")):
                    value = item.get(field)
                    if isinstance(value, str) and value.strip() and value.strip() not in {fact["text"] for fact in facts}:
                        fact = new_fact(value, kind=kind, quote=value, source=source)
                        fact["field"] = field
                        facts.append(fact)
                for fact in facts:
                    for key in ("profile_refs", "profile_fact_refs", "source_ids", "source_id", "profile_fact_id"):
                        if item.get(key):
                            fact[key] = copy.deepcopy(item[key])
            item["facts"] = facts
            item["raw_notes"] = list(dict.fromkeys(note for note in item.get("raw_notes", [])
                                                   if isinstance(note, str) and note.strip()))
            if not had_fact_field and not item["raw_notes"] and raw:
                item["raw_notes"] = [raw]
    skills = result.get("skills", [])
    if isinstance(skills, list):
        education_values = _education_values(result)
        normalized_skills = []
        for skill in skills:
            if isinstance(skill, str):
                skill = {"name": skill, "source_quote": skill, "source": "chat", "status": "active"}
            elif isinstance(skill, dict):
                skill = copy.deepcopy(skill)
                skill.setdefault("source_quote", skill.get("name", ""))
                skill.setdefault("source", "chat")
                skill.setdefault("status", "active")
            if isinstance(skill, dict) and skill.get("name") and _fold_value(skill["name"]) not in education_values:
                normalized_skills.append(skill)
        result["skills"] = normalized_skills
    return result


def _editor_texts(item: dict, section: str) -> list[str]:
    if section == "projects":
        bullets = item.get("polished_bullets") or []
    elif section in {"work_experience", "internship"}:
        bullets = item.get("bullets") or []
    else:
        bullets = item.get("highlights") or []
    if isinstance(bullets, str):
        return _lines(bullets)
    return [str(value.get("text", "") if isinstance(value, dict) else value).strip()
            for value in bullets if str(value.get("text", "") if isinstance(value, dict) else value).strip()]


def _editor_statements(item: dict, section: str) -> list[str]:
    statements = _editor_texts(item, section)
    for field in ("description", "role", "title", "start_date", "end_date", "duration", "highlights"):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            statements.extend(_lines(value))
    return list(dict.fromkeys(statements))


def _editor_skills(draft: dict) -> list[str]:
    groups = draft.get("skill_groups") or {}
    values = [skill for group in groups.values() for skill in group] if isinstance(groups, dict) and groups else draft.get("skills") or []
    return [str(skill.get("name", "") if isinstance(skill, dict) else skill).strip() for skill in values if skill]


def append_editor_facts(previous_facts: dict, old_draft: dict, new_draft: dict,
                        turn_id: str) -> dict:
    """Append only newly typed or changed editor bullets; deletion is draft only."""
    result = normalize_fact_store(previous_facts)
    basic = result.setdefault("basic_info", {})
    for key, value in (new_draft.get("basic_info") or {}).items():
        if isinstance(value, (str, int, float)):
            basic[key] = value
    old_skills = {skill.casefold() for skill in _editor_skills(old_draft)}
    known_skills = {skill["name"].casefold() for skill in result.get("skills", [])}
    for skill in _editor_skills(new_draft):
        if skill.casefold() not in old_skills and skill.casefold() not in known_skills:
            result.setdefault("skills", []).append({"name": skill, "source_quote": skill,
                                                    "source": "editor", "turn_id": turn_id, "status": "active"})
            known_skills.add(skill.casefold())
    for section in FACT_SECTIONS:
        old_items = old_draft.get(section) or []
        old_by_id = {item.get("item_id"): item for item in old_items if isinstance(item, dict) and item.get("item_id")}
        def identity(value: dict) -> str:
            return str(value.get("name") or value.get("company") or value.get("school") or "").strip().casefold()
        old_by_identity = {identity(item): item for item in old_items if isinstance(item, dict) and identity(item)}
        new_items = new_draft.get(section) or []
        stored = result.setdefault(section, [])
        by_id = {item.get("item_id"): item for item in stored if isinstance(item, dict)}
        for index, item in enumerate(new_items):
            if not isinstance(item, dict):
                continue
            old = old_by_id.get(item.get("item_id")) if item.get("item_id") else None
            if old is None and identity(item):
                old = old_by_identity.get(identity(item))
            if old is None and index < len(old_items) and isinstance(old_items[index], dict) and identity(old_items[index]) == identity(item):
                old = old_items[index]
            old = old or {}
            item_id = item.get("item_id") or old.get("item_id")
            target = by_id.get(item_id) if item_id else None
            if target is None:
                label = item.get("name") or item.get("company") or item.get("school")
                target = next((candidate for candidate in stored if isinstance(candidate, dict)
                               and label and label == (candidate.get("name") or candidate.get("company") or candidate.get("school"))), None)
                if target:
                    item_id = target.get("item_id")
            if target is None and index < len(stored) and isinstance(stored[index], dict) and not item_id and identity(stored[index]) == identity(item):
                target = stored[index]
                item_id = target.get("item_id")
            item_id = item_id or str(uuid.uuid4())
            item["item_id"] = item_id
            if target is None:
                if not identity(item) and not _editor_statements(item, section):
                    continue
                label_key = {"projects": "name", "education": "school", "internship": "company", "work_experience": "company"}[section]
                target = {"item_id": item_id, label_key: item.get(label_key, ""), "facts": [], "raw_notes": []}
                stored.append(target)
            by_id[item_id] = target
            old_texts = set(_editor_statements(old, section))
            already = {fact.get("text") for fact in target.get("facts", []) if fact.get("status", "active") == "active"}
            for value in _editor_statements(item, section):
                if value not in old_texts and value not in already:
                    target.setdefault("facts", []).append(new_fact(value, quote=value, source="editor", turn_id=turn_id))
                    already.add(value)
    return result


def active_facts_for_writer(collected: dict) -> dict:
    """Expose current evidence, never raw notes or obsolete descriptive fields."""
    source = normalize_fact_store(collected)
    result = {key: copy.deepcopy(source[key]) for key in ("basic_info", "certificates") if key in source}
    if "skills" in source:
        result["skills"] = [copy.deepcopy(skill) for skill in source["skills"] if skill.get("status") == "active"]
    for section in FACT_SECTIONS:
        if section not in source:
            continue
        result[section] = []
        for item in source[section]:
            if not isinstance(item, dict):
                continue
            active = [{**copy.deepcopy(fact), "item_id": item["item_id"]} for fact in item.get("facts", [])
                      if fact.get("status") == "active"]
            if not active:
                continue
            result[section].append({key: copy.deepcopy(item[key]) for key in ("item_id", "name", "company", "school", "hidden") if key in item}
                                   | {"facts": active})
    return result
