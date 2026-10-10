"""Save editor drafts to the same canonical resume read by the chat graph."""

import asyncio
import copy
import hashlib
import json
import logging
import uuid
from fastapi import HTTPException
from datetime import UTC, datetime
from sqlalchemy.orm.exc import StaleDataError

from app.database import SessionLocal
from app.models.models import ResumeSession
from app.services.resume_review import resume_to_text
from app.services.session_store import DELETED_STAGE, _is_expired, resume_data_has_content, make_resume_state

logger = logging.getLogger(__name__)


class InvalidResumeSession(Exception):
    pass


class ResumeRevisionConflict(Exception):
    def __init__(self, revision: str):
        self.revision = revision


class ResumeSaveUnavailable(Exception):
    pass


def assert_active_resume_session(session_id: str) -> None:
    """Distinguish deletion from a temporary storage failure before clearing backups."""
    db = None
    try:
        db = SessionLocal()
        row = db.get(ResumeSession, session_id)
        if row is None or row.stage == DELETED_STAGE or _is_expired(row):
            raise InvalidResumeSession()
    except InvalidResumeSession:
        raise
    except Exception as error:
        raise ResumeSaveUnavailable() from error
    finally:
        if db is not None:
            db.close()


def resume_revision(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_has_content(data: dict | None) -> bool:
    """Share the content boundary used when persisting completed graph turns."""
    return resume_data_has_content(data)


def current_canonical(values: dict, stored: dict | None, serialize) -> dict:
    # The SQL row is the acknowledged committed version. A checkpoint may be
    # ahead after a crash between stores and must not masquerade as a saved edit.
    if stored is not None and isinstance(stored.get("resume_data"), dict):
        return stored["resume_data"]
    # A nonempty canonical object can intentionally contain no personal content.
    # Never revive removed fields from collected_info or an older session row.
    canonical = values.get("resume_data")
    if isinstance(canonical, dict) and canonical:
        return canonical
    if values:
        rebuilt = serialize(values)
        if canonical_has_content(rebuilt):
            return rebuilt
    return (stored or {}).get("resume_data") or {}


def editor_facts(data: dict, previous: dict | None = None) -> dict:
    """Explicit editor values replace candidate facts; polished text is current text."""
    facts = copy.deepcopy(previous or {})
    groups = copy.deepcopy(data.get("skill_groups") or {})
    # Templates and the editor display groups when present. The legacy flat
    # list can still contain removed skills, so derive facts from visible text.
    skills = (
        [skill for values in groups.values() for skill in values if skill.strip()]
        if groups
        else copy.deepcopy(data.get("skills") or [])
    )
    facts.update({
        "basic_info": copy.deepcopy(data.get("basic_info") or {}),
        "education": copy.deepcopy(data.get("education") or []),
        "work_experience": copy.deepcopy(data.get("work_experience") or []),
        "internship": [],
        "projects": copy.deepcopy(data.get("projects") or []),
        "skills": skills,
        "skill_groups": groups,
        "certificates": copy.deepcopy(data.get("certificates") or []),
        "personal_summary": data.get("self_evaluation") or "",
        "self_evaluation": data.get("self_evaluation") or "",
        "verification_notes": copy.deepcopy(data.get("verification_notes") or []),
    })
    for item in facts["projects"]:
        if item.get("polished_bullets"):
            item["description"] = "\n".join(item["polished_bullets"])
    return facts


async def save_canonical_resume(session_id: str, expected_revision: str, data: dict, graph, serialize, *, after_save=None, archive_facts=False, removed_item_ids=(), provenance_bindings=(), source="editor", collected_info=None, resume_meta=None, resume_versions=None, session_constraints=None) -> dict:
    """Caller holds session_lock, shared with streams/deletion/expiry in this worker.

    The stores have separate transactions. A failed row commit restores graph values
    before reporting failure; the caller never receives a successful partial save.
    """
    if source not in {"editor", "writer", "restore", "import"}:
        raise ValueError("Unknown resume save source")
    db = SessionLocal()
    config = {"configurable": {"thread_id": session_id}}
    previous_values = None
    checkpoint_written = False
    try:
        row = db.get(ResumeSession, session_id)
        if row is None or row.stage == DELETED_STAGE or _is_expired(row):
            raise InvalidResumeSession()
        snapshot = await graph.aget_state(config)
        previous_values = (snapshot.values if snapshot else {}) or {}
        stored_state = row.resume_state or {}
        if not previous_values and not stored_state.get("authoritative") and (row.resume_data or row.stage not in ("", "JD_INPUT")):
            # A fresh empty conversation can start in the editor. A previously
            # used conversation must not silently lose its JD and source facts.
            raise ResumeSaveUnavailable()
        stored = {"resume_data": row.resume_data or {}}
        current = current_canonical(previous_values, stored, serialize)
        from app.models.models import Conversation
        conversation = db.get(Conversation, session_id)
        owner = conversation.owner_hash if conversation else ""
        from app.services.profile_bridge import protect_data
        current = protect_data(owner, current, db=db)
        revision = resume_revision(current)
        if expected_revision != revision:
            raise ResumeRevisionConflict(revision)
        authoritative = stored_state if stored_state.get("authoritative") else previous_values
        facts = protect_data(owner, authoritative.get("collected_info") or {}, db=db)
        canonical = copy.deepcopy(data)
        from app.services.skill_groups import sync_flat_skills
        sync_flat_skills(canonical)
        if owner.startswith("account:"):
            from app.services.resume_provenance import validate_item_ids, update_bindings, register_fact_items
            account = owner.split(":", 1)[1]
            if source == "import":
                register_fact_items(db, account, session_id, collected_info or {}, canonical)
            elif source in {"writer", "restore"}:
                register_fact_items(db, account, session_id, facts, canonical)
            validate_item_ids(db, account, session_id, current, canonical,
                              removed_item_ids=removed_item_ids, bindings=provenance_bindings)
            update_bindings(db, account, session_id, canonical,
                            bindings=provenance_bindings, removed_item_ids=removed_item_ids)
        protect_data(owner, canonical, reject=True, db=db)
        # Strategy is generated by the server, not editable candidate evidence.
        if current.get("resume_strategy"):
            canonical["resume_strategy"] = copy.deepcopy(current["resume_strategy"])
        from app.services.resume_facts import append_editor_facts
        if source == "editor":
            facts = append_editor_facts(facts, current, canonical, "editor:" + str(uuid.uuid4()))
            if owner.startswith("account:"):
                register_fact_items(db, account, session_id, facts, canonical)
        elif source == "import" and collected_info is not None:
            facts = copy.deepcopy(collected_info)
        state = make_resume_state(
            facts, resume_meta if resume_meta is not None else authoritative.get("resume_meta"),
            resume_versions if resume_versions is not None else authoritative.get("resume_versions"),
            session_constraints if session_constraints is not None else authoritative.get("session_constraints"))
        from app.services.resume_versions import valid_bullet_metadata
        if "bullets" in state["resume_meta"]:
            state["resume_meta"] = valid_bullet_metadata(canonical, state["resume_meta"])
        pre_sanitization = copy.deepcopy(canonical)
        protected = protect_data(owner, {**state, "resume_data": canonical}, db=db)
        canonical = protected.pop("resume_data")
        state = protected
        from app.services.resume_capacity import revalidate_committed_page_check, resume_data_hash
        state["resume_meta"] = await asyncio.to_thread(
            revalidate_committed_page_check, canonical, state["resume_meta"],
            state.get("session_constraints"), content_changed=canonical != pre_sanitization,
            pre_sanitization_hash=resume_data_hash(pre_sanitization))
        draft = resume_to_text(canonical)
        updates = {
            "resume_data": canonical,
            "resume_draft": draft,
            "collected_info": state["collected_info"],
            "resume_meta": state["resume_meta"],
            "resume_versions": state["resume_versions"],
            "session_constraints": state["session_constraints"],
            "stage": "EVALUATING",
            "requested_task": "auto",
        }
        await graph.aupdate_state(config, updates, as_node="building")
        checkpoint_written = True
        row.resume_state = state
        row.resume_data = canonical
        row.resume_draft = draft
        row.stage = "EVALUATING"
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
        if archive_facts and source == "editor" and owner.startswith("account:"):
            from app.services.profile_service import enqueue_archive_event
            enqueue_archive_event(db, owner.split(":", 1)[1], str(uuid.uuid4()), session_id,
                                  {"human_text": draft, "source_kind": "manual",
                                   "collected_info_delta": {"basic_info": canonical.get("basic_info") or {}}},
                                  event_type="manual_fact")
        if after_save is not None:
            after_save(db, current, canonical)
        db.commit()
        return {"saved": True, "revision": resume_revision(canonical), "data": canonical,
                "page_check": copy.deepcopy(state["resume_meta"].get("page_check") or {}),
                "stage": "EVALUATING"}
    except Exception as error:
        db.rollback()
        if checkpoint_written and previous_values is not None:
            try:
                restored = {key: copy.deepcopy(previous_values.get(key)) for key in (
                    "resume_data", "resume_draft", "collected_info", "resume_meta", "resume_versions", "session_constraints", "stage", "requested_task"
                )}
                await graph.aupdate_state(config, restored, as_node="building")
            except Exception:
                logger.error("editor checkpoint restoration failed")
        if isinstance(error, (InvalidResumeSession, ResumeRevisionConflict, HTTPException)):
            raise
        if isinstance(error, StaleDataError):
            with SessionLocal() as current_db:
                latest = current_db.get(ResumeSession, session_id)
                if latest is None or latest.stage == DELETED_STAGE:
                    raise InvalidResumeSession() from None
                latest_data = protect_data(owner, latest.resume_data)
            raise ResumeRevisionConflict(resume_revision(latest_data)) from None
        logger.error("editor canonical save failed")
        raise ResumeSaveUnavailable() from error
    finally:
        db.close()
