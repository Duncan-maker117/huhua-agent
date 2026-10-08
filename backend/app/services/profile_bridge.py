"""Apply profile provenance and invalidation rules at existing product boundaries."""

import copy
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


def protect_data(owner, data, *, reject=False, db=None):
    account = account_id(owner)
    if not account:
        return copy.deepcopy(data)
    from app.services.resume_provenance import sanitize_bound_fields

    def clean(session):
        scoped, changed = sanitize_projection(session, account, data)
        cleaned, bound_changed = sanitize_bound_fields(session, account, scoped)
        return cleaned, changed or bound_changed

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


async def prepare_graph_context(owner, session_id, graph, *, fact_ids=None, context=None):
    """Sanitize stored context, then import explicitly selected profile facts."""
    account = account_id(owner)
    config = {"configurable": {"thread_id": session_id}}
    snapshot = await graph.aget_state(config)
    previous = (snapshot.values if snapshot else {}) or {}
    values = protect_state(owner, previous)
    with SessionLocal() as db:
        stored = db.get(ResumeSession, session_id)
        if stored is None:
            raise HTTPException(404, "会话不存在")
        # Repair a checkpoint left ahead by a failed/crashed two-store edit.
        # Raw user messages remain available; editable facts always begin with
        # the acknowledged SQL version rather than a failed editor projection.
        canonical = protect_data(owner, stored.resume_data, db=db)
        from app.services.canonical_resume import editor_facts
        from app.services.resume_review import resume_to_text
        checkpoint_differs = values.get("resume_data") != canonical
        values["resume_data"] = canonical
        values["resume_draft"] = resume_to_text(canonical)
        if checkpoint_differs:
            values["collected_info"] = editor_facts(canonical, values.get("collected_info"))
        if context is None:
            context = get_context(db, account, subject_ids=fact_ids, limit=100, include_contacts=False) if account else {"facts": [], "fact_refs": []}
        collected = (context_to_collected_info(context, values.get("collected_info"))
                     if context["facts"] else values.get("collected_info") or {})
    update = {k: v for k, v in values.items() if k != "messages"}
    old_ids = {m.id for m in previous.get("messages") or [] if m.id}
    new_ids = {m.id for m in values.get("messages") or [] if m.id}
    update["messages"] = [RemoveMessage(id=item) for item in old_ids - new_ids] + values.get("messages", [])
    update["collected_info"] = collected
    if previous or context["facts"]:
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
                row.resume_data = protect_data(owner, row.resume_data, db=db)
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
