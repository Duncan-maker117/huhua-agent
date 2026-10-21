"""Apply profile provenance and invalidation rules at existing product boundaries."""

import copy
import hashlib
import re
from difflib import SequenceMatcher
import logging

from fastapi import HTTPException
from langchain_core.messages import HumanMessage, RemoveMessage
from sqlalchemy import Column, String, Integer

from app.database import Base, SessionLocal
from app.models.models import Conversation, ResumeSession
from app.services.profile_service import (
    context_to_collected_info, get_context, get_projection_guard, sanitize_projection,
)


class ClaimedHistoryImport(Base):
    __tablename__ = "claimed_history_imports"
    session_id = Column(String(128), primary_key=True)
    owner = Column(String(128), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    error_code = Column(String(64), nullable=False, default="")


async def import_claimed_history(checkpointer):
    from app.services.profile_service import enqueue_archive_event
    with SessionLocal() as db:
        jobs = [(row.session_id, row.owner) for row in db.query(ClaimedHistoryImport).filter_by(status="pending").limit(10)]
    for session_id, owner in jobs:
        try:
            snapshot = await checkpointer.aget_tuple({"configurable": {"thread_id": session_id}})
            state = (snapshot.checkpoint.get("channel_values") if snapshot else {}) or {}
            with SessionLocal() as db:
                row = db.get(ClaimedHistoryImport, session_id)
                conversation = db.get(Conversation, session_id)
                if not conversation or conversation.owner_hash != owner:
                    row.status = "skipped"
                    db.commit()
                    continue
                for message in state.get("messages") or []:
                    if not isinstance(message, HumanMessage) or not message.id:
                        continue
                    event = archive_event_for_message(message, state)
                    event["event_type"] = "claimed_history"
                    enqueue_archive_event(db, account_id(owner), session_id=session_id, **event)
                row.status = "completed"
                row.error_code = ""
                db.commit()
        except Exception as error:
            with SessionLocal() as db:
                row = db.get(ClaimedHistoryImport, session_id)
                row.attempts += 1
                row.error_code = type(error).__name__
                row.status = "failed" if row.attempts >= 3 else "pending"
                db.commit()
            logging.getLogger(__name__).warning("claimed_history_import_failed error=%s", type(error).__name__)


def account_id(owner):
    return owner.split(":", 1)[1] if owner and owner.startswith("account:") else None


def intake_profile_state(owner, *, db=None):
    """读取账号基本信息与经历目录，模型边界继续统一脱敏。"""
    account = account_id(owner)
    if not account:
        return {"intake_account": False, "intake_profile": {}}
    from app.services.profile_service import get_intake_context

    def read(session):
        from app.services.profile_tools import profile_catalog
        profile = context_to_collected_info(get_intake_context(session, account))
        return {"intake_account": True, "profile_items": profile_catalog(session, account), "intake_profile": {
            "basic_info": profile.get("basic_info") or {},
            "education": profile.get("education", [])[:1],
        }}
    if db is not None:
        return read(db)
    with SessionLocal() as session:
        result = read(session)
        session.commit()
        return result


def protect_data(owner, data, *, reject=False, db=None):
    account = account_id(owner)
    if not account:
        return sanitize_fact_history(copy.deepcopy(data))
    from app.services.resume_provenance import sanitize_bound_fields

    def clean(session):
        scoped, changed = sanitize_projection(session, account, data)
        cleaned, bound_changed = sanitize_bound_fields(session, account, scoped)
        history = sanitize_fact_history(cleaned, original=data)
        return history, changed or bound_changed or history != cleaned

    if db is None:
        with SessionLocal() as session:
            cleaned, changed = clean(session)
    else:
        cleaned, changed = clean(db)
    if changed and reject:
        raise HTTPException(409, "资料含已经更正或删除的旧内容，请载入当前版本再操作")
    return cleaned


def protect_state(owner, state):
    account = account_id(owner)
    if not account:
        return state
    with SessionLocal() as db:
        guard = get_projection_guard(db, account)
        cleaned = protect_data(owner, {k: v for k, v in state.items() if k != "messages"}, db=db)
        messages = []
        for message in state.get("messages") or []:
            if message.id and message.id in guard["blocked_source_ids"]:
                continue
            content, changed = sanitize_projection(db, account, message.content)
            if changed and not content:
                continue
            messages.append(message.model_copy(update={"content": content}) if changed else message)
        cleaned["messages"] = messages
    return cleaned


async def prepare_graph_context(owner, session_id, graph, *, fact_ids=None, context=None, current_state=None):
    """Sanitize stored context, then import explicitly selected profile facts."""
    account = account_id(owner)
    config = {"configurable": {"thread_id": session_id}}
    if current_state is not None:
        with SessionLocal() as db:
            conversation = db.get(Conversation, session_id)
            if not account or not conversation or conversation.owner_hash != owner:
                raise HTTPException(404, "会话不存在")
            context = get_context(db, account, subject_ids=fact_ids, limit=500, include_contacts=False)
            if len(context["facts"]) != len(set(fact_ids or [])):
                raise HTTPException(409, "档案条目已变化")
            bindings = []
            collected = context_to_collected_info(context, protect_data(owner, current_state.get("collected_info") or {}, db=db),
                                                  projection_bindings=bindings)
            from app.services.resume_provenance import update_bindings
            update_bindings(db, account, session_id, collected, bindings=bindings)
            from app.services.profile_service import merge_job_version_import
            merge_job_version_import(db, account, session_id, context["fact_refs"])
            db.commit()
        return {"context": context, "update": {"collected_info": collected}}
    snapshot = await graph.aget_state(config)
    previous = (snapshot.values if snapshot else {}) or {}
    values = protect_state(owner, previous)
    with SessionLocal() as db:
        if account:
            from app.services.profile_service import migrate_legacy_basic_facts
            migrate_legacy_basic_facts(db, account)
            values["collected_info"] = protect_data(owner, values.get("collected_info") or {}, db=db)
        stored = db.get(ResumeSession, session_id)
        if stored is None:
            raise HTTPException(404, "会话不存在")
        # Repair a checkpoint left ahead by a failed/crashed two-store edit.
        # Raw user messages remain available; editable facts always begin with
        # the acknowledged SQL version rather than a failed editor projection.
        stored_state = protect_data(owner, {**(stored.resume_state or {}), "resume_data": stored.resume_data}, db=db)
        canonical = stored_state.pop("resume_data")
        from app.services.resume_review import resume_to_text
        values["resume_data"] = canonical
        values["resume_draft"] = resume_to_text(canonical)
        if stored_state.get("authoritative"):
            for key, default in (("collected_info", {}), ("resume_meta", {}), ("resume_versions", []), ("session_constraints", {})):
                values[key] = copy.deepcopy(stored_state.get(key, default))
        if context is None:
            context = get_context(db, account, subject_ids=fact_ids, limit=100, include_contacts=False) if account else {"facts": [], "fact_refs": []}
        from app.services.profile_service import get_profile_summary
        summary = get_profile_summary(db, account) if account else {}
        # 基本信息与第一条教育确定性沿用，经历仍由用户或工具明确选择。
        intake_profile = intake_profile_state(owner, db=db)
        collected = (context_to_collected_info(context, values.get("collected_info"))
                     if context["facts"] else values.get("collected_info") or {})
        if account:
            from app.services.profile_service import get_intake_context
            basic_context = get_intake_context(db, account)
            education = next((fact["subject"] for fact in basic_context["facts"] if fact["category"] == "education"), None)
            basic_context["facts"] = [f for f in basic_context["facts"] if f["category"] != "education" or f["subject"] == education]
            if basic_context["facts"]:
                bindings = []
                collected = context_to_collected_info(basic_context, collected, projection_bindings=bindings)
                from app.services.resume_provenance import update_bindings
                update_bindings(db, account, session_id, collected, bindings=bindings)
        db.commit()
    update = {k: v for k, v in values.items() if k != "messages"}
    old_ids = {m.id for m in previous.get("messages") or [] if m.id}
    new_ids = {m.id for m in values.get("messages") or [] if m.id}
    update["messages"] = [RemoveMessage(id=item) for item in old_ids - new_ids] + values.get("messages", [])
    update["collected_info"] = collected
    update["profile_summary"] = summary
    update.update(intake_profile)
    from app.services.intake import intake_update
    update.update(intake_update({**values, **update}))
    if previous or context["facts"] or summary.get("has_facts") or account:
        await graph.aupdate_state(config, update, as_node="building")
    return context


async def purge_invalidated_copies(owner, graph):
    """Remove prohibited online derived content while retaining source chat policy."""
    if not account_id(owner):
        return
    from app.services.session_store import session_lock
    with SessionLocal() as db:
        ids = [r.session_id for r in db.query(Conversation).filter(Conversation.owner_hash == owner)]
    for session_id in ids:
        async with session_lock(session_id):
            await prepare_graph_context(owner, session_id, graph)
            with SessionLocal() as db:
                row = db.get(ResumeSession, session_id)
                if not row:
                    continue
                clean = protect_data(owner, {**(row.resume_state or {}), "resume_data": row.resume_data}, db=db)
                row.resume_data = clean.pop("resume_data")
                row.resume_state = clean
                # Rebuild the derived prose from its scoped structured source;
                # a raw date string cannot identify which fact it came from.
                from app.services.resume_review import resume_to_text
                row.resume_draft = resume_to_text(row.resume_data)
                conversation = db.get(Conversation, session_id)
                if conversation:
                    conversation.title = protect_data(owner, conversation.title) or "新对话"
                db.commit()


def archive_event_for_message(message, state):
    """Only the authoritative human source is an archive input, never AI text."""
    kind = message.additional_kwargs.get("career_material_type", "candidate")
    excluded = state.get("non_candidate_message_ids") or []
    kind = "self" if kind == "candidate" and message.id not in excluded else "jd" if kind == "jd" else "reference"
    return {"source_id": message.id, "event_type": "human_message", "payload": {
        "human_text": message.content, "source_kind": kind,
        "collected_info_delta": {"basic_info": (state.get("collected_info") or {}).get("basic_info") or {}},
    }}


def sanitize_fact_history(state, *, original=None):
    """Keep inactive evidence out of drafts, including legacy versions without metadata."""
    if not isinstance(state, dict) or "collected_info" not in state:
        return state
    result = copy.deepcopy(state)
    sections = ("projects", "education", "work_experience", "internship", "campus", "open_source", "awards")
    active = {fact.get("id") for section in sections
              for item in (result.get("collected_info") or {}).get(section, [])
              for fact in item.get("facts", []) if fact.get("status", "active") == "active"}
    active_fields = {item.get("item_id"): {fact.get("field"): fact.get("text")
                     for fact in item.get("facts", []) if fact.get("status", "active") == "active" and fact.get("field")}
                     for section in sections for item in (result.get("collected_info") or {}).get(section, [])}
    original = original if isinstance(original, dict) else state
    obsolete = {item.get("item_id"): [fact for fact in item.get("facts", []) if fact.get("id") not in active]
                for section in sections for item in (original.get("collected_info") or {}).get(section, [])}

    all_obsolete = [fact for rows in obsolete.values() for fact in rows]
    replacements = {fact['replaces']: fact for section in sections
                    for item in (result.get('collected_info') or {}).get(section, [])
                    for fact in item.get('facts', []) if fact.get('id') in active and fact.get('replaces')}

    def normalized(text):
        return re.sub(r"[\W_]+", "", text).casefold()

    def unsupported(text, facts, field):
        if not isinstance(text, str) or not text.strip():
            return False
        target = normalized(text)
        for fact in facts:
            replacement = replacements.get(fact.get('id'))
            if replacement:
                from app.services.candidate_language import resume_bullet
                # Exact live correction wins over the old fuzzy similarity
                # test (18 -> 12 differs by only one character). Audit quotes
                # and merely swapping a citation do not authorize old prose.
                live = replacement.get('text', '')
                if target in {normalized(live), normalized(resume_bullet(live))}:
                    continue
                # A corrected fact can be a clause inside a longer sourced
                # bullet. The old quote may include its action and qualifiers,
                # so whole-line fuzzy matching would erase the valid new value.
                old = normalized(fact.get('text') or '')
                new = normalized(live)
                # Compare complete numbers: 170 -> 190 must not treat an
                # unrelated 17 (or 1700) elsewhere as the obsolete value.
                old_tokens, new_tokens = (re.findall(r"\d+|\D", value) for value in (old, new))
                removed = [''.join(old_tokens[a:b]) for op, a, b, _, _ in
                           SequenceMatcher(None, old_tokens, new_tokens, autojunk=False).get_opcodes()
                           if op in {'replace', 'delete'} and old_tokens[a:b]]
                if (new and new in target and removed and old not in target
                        and not any(re.search((r'(?<!\d)' if part[0].isdigit() else '') + re.escape(part)
                                              + (r'(?!\d)' if part[-1].isdigit() else ''), target.replace(new, ''))
                                    for part in removed)):
                    continue
            # Dates and scalar identity fields are scoped to their original slot;
            # all prose fields can contain literal or near-literal copies.
            if field not in {"description", "raw_description", "bullets", "polished_bullets", "highlights", "self_evaluation", "personal_summary"}:
                if fact.get("field") and fact["field"] != field:
                    continue
            for quote in (fact.get("text"), fact.get("source_quote")):
                if not isinstance(quote, str) or not quote.strip():
                    continue
                token = normalized(quote)
                if token and (token == target or (len(token) >= 4 and token in target)
                              or (min(len(token), len(target)) >= 5 and
                                  SequenceMatcher(None, token, target, autojunk=False).ratio() >= 0.85)):
                    return True
        return False

    def clean_version(version):
        meta = version.get("resume_meta") or {}
        bullets = meta.get("bullets") or {}
        draft = version.get("resume_data") or {}
        before = copy.deepcopy(draft)
        hashes = {}
        summary_field = "summary" if "summary" in draft else "self_evaluation"
        summary = draft.get(summary_field) or ""
        summary_meta = meta.get("summary") or {}
        summary_refs = summary_meta.get("fact_ids") or []
        summary_hash = hashlib.sha256(summary.encode("utf-8")).hexdigest()
        summary_matches = bool(summary_meta) and summary_meta.get("text_hash") == summary_hash
        stale_summary = bool(summary_meta) and (not summary_refs or bool(set(summary_refs) - active))
        if unsupported(summary, all_obsolete, "self_evaluation") or (summary_matches and stale_summary):
            draft[summary_field] = ""
        if summary_field == "summary" and unsupported(draft.get("self_evaluation"), all_obsolete, "self_evaluation"):
            draft["self_evaluation"] = ""
        if summary_meta and (stale_summary or ("resume_data" in version and (
                not summary_matches or draft.get(summary_field) != summary))):
            meta.pop("summary", None)
        for section in sections:
            for item in draft.get(section) or []:
                if section == 'projects' and 'role' in item:
                    from app.services.resume_field_hygiene import project_role
                    item['role'] = project_role(item['role'])
                item_id = item.get("item_id")
                records = bullets.get(item_id) or []
                stale_hashes = {entry.get("text_hash") for entry in records if set(entry.get("fact_ids") or []) - active}
                facts = obsolete.get(item_id, [])
                for field in ("name", "school", "company", "degree", "major", "role", "title", "start_date",
                              "end_date", "duration", "summary", "pr", "level", "date", "description", "raw_description", "highlights", "bullets", "polished_bullets", "tech_stack"):
                    value = item.get(field)
                    # A literal active replacement owns its scalar slot. E.g.
                    # 专业「计算机科学与技术」 is also a near-match to the superseded
                    # extraction「计算机科学与技术本科」, but is not stale prose.
                    supported = active_fields.get(item_id, {}).get(field)
                    if field not in {"description", "raw_description", "highlights", "bullets", "polished_bullets"} and supported and value == supported:
                        continue
                    if isinstance(value, list):
                        item[field] = [text for text in value if not unsupported(text, facts, field)
                                       and (not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() not in stale_hashes)]
                    elif unsupported(value, facts, field):
                        item[field] = ""
                tech_records = meta.get('tech_stack', {}).get(item_id, [])
                if tech_records and item.get('tech_stack'):
                    from app.services.tech_stack import supporting_ids
                    own_facts = [f for group in sections for row in (result.get('collected_info') or {}).get(group, [])
                                 if row.get('item_id') == item_id for f in row.get('facts', [])]
                    item['tech_stack'] = [name for name in item['tech_stack'] if supporting_ids(name, own_facts)]
                visible = item.get("polished_bullets") if section == "projects" else item.get("bullets")
                hashes[item_id] = {hashlib.sha256(line.encode()).hexdigest() for line in visible or [] if isinstance(line, str)}
        for item_id, records in list(bullets.items()):
            bullets[item_id] = [entry for entry in records if not (set(entry.get("fact_ids") or []) - active)
                                and ("resume_data" not in version or entry.get("text_hash") in hashes.get(item_id, set()))]
        if draft != before and "resume_draft" in version:
            from app.services.resume_review import resume_to_text
            version["resume_draft"] = resume_to_text(draft)
    # Legacy summaries may also survive in the fact-master compatibility slots;
    # removing these copies prevents the serializer from recreating old prose.
    collected = result.get("collected_info") or {}
    for field in ("personal_summary", "self_evaluation"):
        if unsupported(collected.get(field), all_obsolete, field):
            collected[field] = ""
    clean_version(result)
    for version in result.get("resume_versions") or []:
        clean_version(version)
    return result
