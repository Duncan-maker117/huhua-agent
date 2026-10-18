"""Deterministic, model-only summaries; canonical evidence stays in tool state."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from pydantic_settings import BaseSettings

from app.schemas.facts import FACT_SECTIONS

RECENT_USER_TURNS = 3
HISTORY_CHARS = 5000
STATE_CHARS = 4800
TOOL_RESULT_CHARS = 3200


class OrchestratorSettings(BaseSettings):
    # Decisions still think; a forced text-only receipt needs no further plan.
    AGENT_FINAL_MODE: Literal["thinking", "off"] = "off"
    model_config = {"env_file": str(Path(__file__).resolve().parents[2] / ".env"),
                    "env_file_encoding": "utf-8", "extra": "ignore"}


def safe_data(value, privacy):
    # Redact before shortening, including dictionaries resembling opaque media.
    return json.loads(privacy.redact(json.dumps(privacy.redact(value), ensure_ascii=False)))


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _text(value, limit=180):
    value = str(value or "")
    if len(value) <= limit:
        return value
    marker = f"…[截断，原长{len(value)}字符]"
    return value[:max(0, limit - len(marker))] + marker


def _bounded(value, limit, depth=0):
    """Bound serialized size, retaining valid JSON and explicit omission markers."""
    if isinstance(value, str):
        text = _text(value, min(360, limit - 40))
        while len(_json(text)) > limit:
            text = _text(text, max(24, len(text) // 2))
        return text
    if not isinstance(value, (dict, list)):
        return value
    if depth >= 6:
        return {"_omitted": len(value)}
    result = {} if isinstance(value, dict) else []
    entries = list(value.items()) if isinstance(value, dict) else list(enumerate(value))
    for index, (key, item) in enumerate(entries):
        remaining = limit - len(_json(result)) - len(_json(key)) - 64
        if remaining < 100 or index >= 30:
            break
        child = _bounded(item, remaining, depth + 1)
        if isinstance(result, dict):
            result[_text(key, 80)] = child
        else:
            result.append(child)
    omitted = len(entries) - len(result)
    if omitted:
        if isinstance(result, dict):
            result["_omitted_fields"] = omitted
        else:
            result.append({"_omitted_items": omitted})
    return result


def _pick(value, keys):
    return {key: value[key] for key in keys if isinstance(value, dict) and key in value}


def _sentences(values, count=3):
    rows = [_text(re.split(r"(?<=[。！？!?])|\n", str(value), maxsplit=1)[0], 140)
            for value in values[:count]]
    if len(values) > count:
        rows.append(f"[省略{len(values) - count}条]")
    return rows


def _items(data, *, facts=False):
    rows = []
    for section in FACT_SECTIONS:
        for item in data.get(section) or []:
            if not isinstance(item, dict):
                continue
            row = {"section": section, **_pick(item, (
                "name", "company", "school", "role", "title", "major", "degree",
                "start_date", "end_date", "hidden"))}
            active = [f for f in item.get("facts") or [] if isinstance(f, dict) and f.get("status", "active") == "active"]
            points = [f.get("text", "") for f in active] if facts else list(item.get("bullets") or [])
            if not points:
                points = [item[key] for key in ("description", "summary", "highlights") if item.get(key)]
            row.update(point_count=len(points), first_sentences=_sentences(points))
            limits = [f.get("text", "") for f in active if f.get("kind") == "status_limit"]
            if limits:
                row["scope_limits"] = _sentences(limits)
            rows.append(row)
    return {"item_count": len(rows), "items": rows[:12], "omitted_items": max(0, len(rows) - 12)}


def _facts(data):
    basic = data.get("basic_info") or {}
    return {"basic_info": _pick(basic, ("name", "objective", "location", "availability")),
            "contacts_present": {key: bool(basic.get(key)) for key in ("phone", "email")},
            "no_more_questions": bool(data.get("no_more_questions")), **_items(data, facts=True),
            "skills": data.get("skills") or [], "verification_notes": data.get("verification_notes") or []}


def _document(data):
    return {"has_draft": bool(data), **_items(data), "skills": data.get("skills") or []}


def _job(data):
    profile = data.get("role_profile") or {}
    return {**_pick(data, ("role_direction", "job_title", "company", "industry")),
            **_pick(profile, ("role_family", "seniority")),
            "signals": [row.get("signal") for row in profile.get("core_signals") or []],
            "requirements": [row.get("text") for row in profile.get("requirements") or []]}


def _page(data):
    return _pick(data, ("status", "pages", "page_limit", "within_page_limit", "overflow_lines", "code"))


def _plan(data):
    return {**_pick(data, ("label", "thesis", "positioning", "bullet_style", "section_order")),
            **({"recommended": _plan(data["recommended"])} if isinstance(data.get("recommended"), dict) else {}),
            "alternatives": [_plan(row) for row in data.get("alternatives") or [] if isinstance(row, dict)]}


def project_tool_result(name, result, privacy):
    result = safe_data(result, privacy)
    # Decision/status fields come first so large optional diagnostics cannot crowd them out.
    projected = _pick(result, ("status", "code", "error_type", "changed", "restored", "version_id",
        "missing", "contacts_missing", "contacts_requested", "basics_complete", "imported", "message",
        "followup", "followup_attached",
        "uncovered", "incomplete", "rejected_count", "source_kind", "candidate_facts"))
    transforms = {"page_check": _page, "jd_info": _job, "collected_info": _facts,
                  "resume_data": _document, "plan": _plan}
    for key, transform in transforms.items():
        if isinstance(result.get(key), dict):
            projected[key] = _bounded(transform(result[key]), 1800)
    if "facts" in result:
        projected["fact_count"] = len(result["facts"] or [])
    for key, value in result.items():
        if key not in projected and key not in {*transforms, "facts"}:
            projected[key] = _bounded(value, 500)
    if name == "read_profile" and isinstance(result.get("items"), list):
        # These IDs are required for use_profile_items, unlike provenance/fact IDs.
        projected["items"] = [_pick(row, ("id", "category", "name", "role", "start", "end", "summary"))
                              for row in result["items"]]
    return _bounded(projected, TOOL_RESULT_CHARS)


def _asked(state):
    from app.services.ask_user import question_dimension
    rows = []
    for message in state.get("messages") or []:
        if not isinstance(message, AIMessage):
            continue
        card = message.additional_kwargs.get("ask_user") or {}
        for question in card.get("questions") or []:
            row = {"subject": card.get("subject", ""),
                   "dimension": question_dimension(question.get("id", ""), question.get("prompt", ""))}
            if row not in rows:
                rows.append(row)
    return rows


def input_context(state, sources, privacy):
    from app.agents.loop_followup import MAX_FOLLOWUP_ROUNDS, question_rounds, questions_allowed
    messages = [(index, message) for index, message in enumerate(state.get("messages") or [])
                if isinstance(message, (HumanMessage, AIMessage))]
    user_indices = [index for index, message in messages if isinstance(message, HumanMessage)]
    start = user_indices[-RECENT_USER_TURNS] if len(user_indices) >= RECENT_USER_TURNS else 0
    history, remaining = [], HISTORY_CHARS
    for index, message in reversed(messages):
        if index < start or remaining < 160:
            break
        content = safe_data(message.content, privacy)
        if isinstance(content, str):
            content = _text(content, min(remaining - 120, 3200 if not history else 1200))
            while len(_json(content)) > remaining - 120:
                content = _text(content, len(content) // 2)
        else:
            content = _bounded(content, min(remaining - 120, 1200))
        row = {"role": "user" if isinstance(message, HumanMessage) else "assistant", "content": content}
        if isinstance(message, HumanMessage):
            row["source_id"] = message.id or f"user-{index}"
        remaining -= len(_json(row))
        history.append(row)
    history.reverse()
    recent_ids = {row.get("source_id") for row in history}
    source_index = {"current": {"kind": sources["current"]["kind"]}} if "current" in sources else {}
    indexed_sources = [(key, value) for key, value in sources.items() if key != "current"][-12:]
    for identifier, source in indexed_sources:
        row = {"kind": source["kind"]}
        if identifier not in recent_ids and identifier != "current":
            row["preview"] = _text(safe_data(source["text"], privacy), 100)
        source_index[identifier] = row
    collected, document = state.get("collected_info") or {}, state.get("resume_data") or {}
    summary = {"omitted_messages": len(messages) - len(history),
               "direction": (state.get("jd_info") or {}).get("role_direction") or
                            (state.get("jd_info") or {}).get("job_title") or
                            (collected.get("basic_info") or {}).get("objective", ""),
               "version_id": state.get("version_id"), "has_draft": bool(document),
               "recorded_experiences": [item.get("name") or item.get("company") or item.get("school")
                    for section in FACT_SECTIONS for item in collected.get(section) or [] if isinstance(item, dict)],
               "asked_dimensions": _asked(state), "closed_questions": state.get("closed_questions") or []}
    data = {"question_budget": {"used": question_rounds(state), "limit": MAX_FOLLOWUP_ROUNDS,
                               "allowed": questions_allowed(state)},
            "summary": summary, "session_constraints": state.get("session_constraints") or {},
            "profile_summary": state.get("profile_summary") or {}, "intake_account": bool(state.get("intake_account")),
            "pending_plan": _plan(state.get("pending_plan") or {}),
            "confirmed_plan": _plan(state.get("confirmed_plan") or {}),
            "page_check": _page(state.get("page_check") or {}),
            "collected_info": _facts(safe_data(collected, privacy)),
            "resume_data": _document(safe_data(document, privacy)),
            "jd_info": _job(safe_data(state.get("jd_info") or {}, privacy))}
    limits = {"question_budget": 180, "summary": 850, "session_constraints": 300, "profile_summary": 200, "intake_account": 100,
              "pending_plan": 250, "confirmed_plan": 250, "page_check": 200,
              "collected_info": 1200, "resume_data": 700, "jd_info": 400}
    data = {key: _bounded(value, limits[key]) for key, value in safe_data(data, privacy).items()}
    return {"state": _bounded(data, STATE_CHARS), "source_count": len(sources) - int("current" in sources),
            "omitted_sources": max(0, len(sources) - int("current" in sources) - len(indexed_sources)),
            "sources": _bounded(safe_data(source_index, privacy), 1800), "history": history}
