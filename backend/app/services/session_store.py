"""Persistence and lifecycle rules for private resume sessions."""

import asyncio
import logging
import weakref
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import object_session

from app.config import get_settings
from app.database import SessionLocal
from app.models.models import Conversation, ResumeSession

logger = logging.getLogger(__name__)

# Keep a private-data-free marker so an in-flight stream cannot recreate a
# session after its checkpoint and payload have been deleted.
DELETED_STAGE = "__DELETED__"


class SessionStorageUnavailable(Exception):
    """A caller must not report a successful save after a failed commit."""

_session_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def session_lock(session_id: str) -> asyncio.Lock:
    """Serialize stream, explicit deletion, and expiry cleanup in this worker."""
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


def resume_data_has_content(resume_data: dict | None) -> bool:
    if not resume_data:
        return False
    basic = resume_data.get("basic_info") or {}
    return bool(
        resume_data.get("work_experience")
        or resume_data.get("projects")
        or resume_data.get("education")
        or any(value for key, value in basic.items() if key != "objective")
        # A JD-derived objective alone is not candidate content; explicit
        # editor drafts carry section metadata, even when their body is empty.
        or (basic.get("objective") and resume_data.get("sections") is not None)
        or resume_data.get("skills")
        or any((resume_data.get("skill_groups") or {}).values())
        or resume_data.get("certificates")
        or any(
            section.get("kind") == "custom" and section.get("content", "").strip()
            for section in resume_data.get("sections") or []
        )
        or resume_data.get("self_evaluation")
    )


def _cutoff(retention_days: int | None = None) -> datetime:
    days = (
        retention_days
        if retention_days is not None
        else get_settings().SESSION_RETENTION_DAYS
    )
    if days <= 0:
        return datetime.min
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=max(1, days))


def _guest_cutoff() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(
        hours=getattr(get_settings(), "GUEST_RETENTION_HOURS", 24))


def _is_expired(row: ResumeSession, cutoff: datetime | None = None) -> bool:
    updated_at = row.updated_at
    if updated_at is None:
        return True
    if updated_at.tzinfo is not None:
        updated_at = updated_at.astimezone(UTC).replace(tzinfo=None)
    cutoff = cutoff or _cutoff()
    # owner_key is immutable checkpoint AAD, so a claimed guest keeps that key.
    # Current catalog ownership, not encryption ownership, controls retention.
    db = object_session(row)
    if db is not None:
        conversation = db.get(Conversation, row.session_id)
    else:
        with SessionLocal() as lookup:
            conversation = lookup.get(Conversation, row.session_id)
    owner = conversation.owner_hash if conversation else (row.owner_key or "")
    if owner.startswith("guest:"):
        cutoff = max(cutoff, _guest_cutoff())
    return updated_at < cutoff


def session_is_blocked(session_id: str) -> bool:
    """An old or deleted ID must not start another graph run."""
    if not session_id:
        return True
    db = SessionLocal()
    try:
        row = db.get(ResumeSession, session_id)
        return bool(row and (row.stage == DELETED_STAGE or _is_expired(row)))
    except Exception:
        logger.error("session status read failed")
        return True
    finally:
        db.close()


def session_can_read_checkpoint(session_id: str) -> bool:
    """Permit graph reads only for a current, undeleted persisted session."""
    if not session_id:
        return False
    db = SessionLocal()
    try:
        row = db.get(ResumeSession, session_id)
        return bool(row and row.stage != DELETED_STAGE and not _is_expired(row))
    except Exception:
        logger.error("session checkpoint permission read failed")
        return False
    finally:
        db.close()


def session_needs_checkpoint_cleanup(session_id: str, retention_days: int) -> bool:
    """Recheck expiry or deletion under the lock before removing a checkpoint."""
    db = SessionLocal()
    try:
        row = db.get(ResumeSession, session_id)
        return bool(
            row and (row.stage == DELETED_STAGE or _is_expired(row, _cutoff(retention_days)))
        )
    finally:
        db.close()


def ensure_resume_session(session_id: str, owner_key: str = "") -> bool:
    """Track a new graph thread before its first checkpoint is written."""
    db = SessionLocal()
    try:
        row = db.get(ResumeSession, session_id)
        if row is not None:
            return row.stage != DELETED_STAGE and not _is_expired(row)
        db.add(ResumeSession(session_id=session_id, owner_key=owner_key, resume_data={}, stage="JD_INPUT"))
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.error("session initialization failed")
        return False
    finally:
        db.close()


def save_resume_session(
    session_id: str,
    resume_data: dict,
    resume_draft: str = "",
    stage: str = "",
    archive_event: dict | None = None,
) -> None:
    if not session_id or (not resume_data_has_content(resume_data) and not stage):
        return

    db = SessionLocal()
    try:
        row = db.get(ResumeSession, session_id)
        if row is not None and (row.stage == DELETED_STAGE or _is_expired(row)):
            raise SessionStorageUnavailable("Session is no longer active")
        previous_data = row.resume_data if row is not None else {}
        if row is None:
            row = ResumeSession(session_id=session_id)
            db.add(row)
        row.resume_data = resume_data
        row.resume_draft = resume_draft or row.resume_draft or ""
        row.stage = stage or row.stage or ""
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
        from app.models.models import Conversation
        conversation = db.get(Conversation, session_id)
        owner = conversation.owner_hash if conversation else ""
        if owner.startswith("account:"):
            from app.services.profile_bridge import protect_data
            from app.services.resume_provenance import validate_item_ids
            from app.services.resume_review import resume_to_text
            validate_item_ids(db, owner.split(":", 1)[1], session_id, previous_data, resume_data)
            row.resume_data = protect_data(owner, row.resume_data, db=db)
            has_bindings = any(item.get("item_id") for group in ("projects", "education", "work_experience")
                               for item in (row.resume_data.get(group) or []))
            row.resume_draft = (resume_to_text(row.resume_data) if has_bindings
                                else protect_data(owner, row.resume_draft, db=db))
        if archive_event and owner.startswith("account:"):
            from app.services.profile_service import enqueue_archive_event
            enqueue_archive_event(db, account_id=owner.split(":", 1)[1],
                                  session_id=session_id, **archive_event)
        db.commit()
    except Exception:
        db.rollback()
        logger.error("session save failed")
        raise SessionStorageUnavailable("Unable to save session") from None
    finally:
        db.close()


def load_resume_session(session_id: str) -> dict | None:
    if not session_id:
        return None

    db = SessionLocal()
    try:
        row = db.get(ResumeSession, session_id)
        if row is None or row.stage == DELETED_STAGE or _is_expired(row):
            return None
        payload = row.resume_data or {}
        return {
            "session_id": row.session_id,
            "resume_data": payload,
            "resume_draft": row.resume_draft or "",
            "stage": row.stage or "",
            "has_data": resume_data_has_content(payload),
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        }
    except Exception:
        logger.error("session load failed")
        raise SessionStorageUnavailable("Unable to read session") from None
    finally:
        db.close()


def delete_resume_session(session_id: str) -> None:
    """Clear personal content and persist a temporary non-reusable marker."""
    if not session_id:
        return
    db = SessionLocal()
    try:
        row = db.get(ResumeSession, session_id)
        if row is None:
            row = ResumeSession(session_id=session_id)
            db.add(row)
        row.resume_data = {}
        row.resume_draft = ""
        row.stage = DELETED_STAGE
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
    except Exception:
        db.rollback()
        logger.error("session delete failed")
        raise
    finally:
        db.close()


def list_sessions_needing_checkpoint_cleanup(retention_days: int) -> list[str]:
    """List expired or deleted IDs; never discard a failed-cleanup marker."""
    db = SessionLocal()
    try:
        rows = (
            db.query(ResumeSession.session_id)
            .outerjoin(Conversation, Conversation.session_id == ResumeSession.session_id)
            .filter(
                or_(
                    ResumeSession.updated_at < _cutoff(retention_days),
                    ResumeSession.stage == DELETED_STAGE,
                    and_(
                        or_(Conversation.owner_hash.startswith("guest:"),
                            and_(Conversation.owner_hash.is_(None),
                                 ResumeSession.owner_key.startswith("guest:"))),
                        ResumeSession.updated_at < _guest_cutoff(),
                    ),
                )
            )
            .all()
        )
        return [session_id for (session_id,) in rows]
    finally:
        db.close()


def purge_expired_resume_session(session_id: str, retention_days: int) -> None:
    """Purge only if the session is still expired after its checkpoint is gone."""
    db = SessionLocal()
    try:
        row = db.get(ResumeSession, session_id)
        if row is not None and _is_expired(row, _cutoff(retention_days)):
            db.delete(row)
            db.commit()
    finally:
        db.close()
