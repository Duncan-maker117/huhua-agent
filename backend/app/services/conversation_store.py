"""Private conversation catalog owned by an opaque browser cookie.

The catalog never copies messages or candidate facts. Those remain in durable
LangGraph checkpoints, with ResumeSession holding the canonical resume payload.
"""

import base64
import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.legacy_suggestions import ResumeSuggestion
from app.models.models import Conversation, ResumeSession
from app.services.session_store import DELETED_STAGE, _is_expired, resume_data_has_content

WORKSPACE_COOKIE = "huhua_workspace"
GUEST_COOKIE = "huhua_guest"
WORKSPACE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60
DEFAULT_TITLE = "新对话"
_COOKIE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


class ConversationNotFound(Exception):
    pass


def guest_identity(request, response=None) -> str | None:
    """A separate short-lived browser capability, never a legacy-history token.

    The cookie ends with the browser session; server expiry is independently
    enforced on each session. Only its SHA-256 digest is used as an owner.
    """
    token = getattr(request.state, "huhua_guest_token", None)
    if token is None:
        token = request.cookies.get(GUEST_COOKIE, "")
        if not _COOKIE_PATTERN.fullmatch(token):
            if response is None:
                return None
            token = secrets.token_urlsafe(32)
        request.state.huhua_guest_token = token
    if response is not None:
        from app.config import get_settings
        settings = get_settings()
        response.set_cookie(
            GUEST_COOKIE, token, httponly=True,
            secure=(getattr(settings, "APP_ENV", "local") == "production"
                    or getattr(settings, "AUTH_COOKIE_SECURE", True)),
            samesite="lax", path="/",
        )
    # Base64 preserves all 256 digest bits while fitting the 64-character owner
    # column together with the explicit guest namespace.
    return "guest:" + base64.urlsafe_b64encode(hashlib.sha256(token.encode()).digest()).decode().rstrip("=")


def workspace_identity(request, response=None) -> str | None:
    """Use HttpOnly cookie as a browser capability; store only its hash."""
    token = request.cookies.get(WORKSPACE_COOKIE, "")
    if not _COOKIE_PATTERN.fullmatch(token):
        if response is None:
            return None
        token = secrets.token_urlsafe(32)
    if response is not None:
        response.set_cookie(
            WORKSPACE_COOKIE,
            token,
            max_age=WORKSPACE_COOKIE_MAX_AGE,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _active(row: ResumeSession | None) -> bool:
    return bool(row and row.stage != DELETED_STAGE and not _is_expired(row))


def _metadata(conversation: Conversation, row: ResumeSession) -> dict:
    updated = row.updated_at
    if updated and updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return {
        "session_id": row.session_id,
        "title": conversation.title or DEFAULT_TITLE,
        "updated_at": updated.isoformat() if updated else "",
        "stage": row.stage or "JD_INPUT",
        "has_data": resume_data_has_content(row.resume_data),
    }


def list_conversations(owner_hash: str) -> list[dict]:
    with SessionLocal() as db:
        rows = (
            db.query(Conversation, ResumeSession)
            .join(ResumeSession, ResumeSession.session_id == Conversation.session_id)
            .filter(Conversation.owner_hash == owner_hash, ResumeSession.stage != DELETED_STAGE)
            .order_by(ResumeSession.updated_at.desc(), Conversation.created_at.desc())
            .all()
        )
        return [_metadata(conversation, row) for conversation, row in rows if _active(row)]


def create_conversation(owner_hash: str, session_id: str | None = None) -> dict:
    """Create an owned session; an ID alone never authorizes legacy claiming."""
    if not owner_hash:
        raise ConversationNotFound()
    with SessionLocal() as db:
        if session_id:
            row = db.get(ResumeSession, session_id)
            if not _active(row):
                raise ConversationNotFound()
            conversation = db.get(Conversation, session_id)
            if conversation is None:
                raise ConversationNotFound()
            if conversation:
                if conversation.owner_hash != owner_hash:
                    raise ConversationNotFound()
                return _metadata(conversation, row)
        else:
            session_id = str(uuid.uuid4())
            row = ResumeSession(session_id=session_id, owner_key=owner_hash, resume_data={}, stage="JD_INPUT")
            db.add(row)
            # Keep insertion order valid on databases with foreign keys enabled.
            db.flush()
        conversation = Conversation(session_id=session_id, owner_hash=owner_hash, title=DEFAULT_TITLE)
        db.add(conversation)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # The unique session key also prevents competing legacy claims.
            existing = db.get(Conversation, session_id)
            row = db.get(ResumeSession, session_id)
            if existing and existing.owner_hash == owner_hash and _active(row):
                return _metadata(existing, row)
            raise ConversationNotFound() from None
        return _metadata(conversation, row)


def load_conversation(owner_hash: str | None, session_id: str) -> dict:
    if not owner_hash:
        raise ConversationNotFound()
    with SessionLocal() as db:
        conversation = db.get(Conversation, session_id)
        row = db.get(ResumeSession, session_id)
        if not conversation or conversation.owner_hash != owner_hash or not _active(row):
            raise ConversationNotFound()
        return {
            **_metadata(conversation, row),
            "resume_data": row.resume_data or {},
            "resume_draft": row.resume_draft or "",
        }


def set_initial_title(owner_hash: str, session_id: str, first_input: str) -> str:
    """Name migrated chats without changing their original activity time."""
    with SessionLocal() as db:
        conversation = db.get(Conversation, session_id)
        if not conversation or conversation.owner_hash != owner_hash:
            raise ConversationNotFound()
        if conversation.title == DEFAULT_TITLE:
            conversation.title = " ".join(first_input.split())[:40] or DEFAULT_TITLE
            db.commit()
        return conversation.title


def touch_conversation(session_id: str, first_input: str, owner_hash: str | None = None) -> None:
    """Record submitted work even when model generation fails or is cancelled."""
    with SessionLocal() as db:
        row = db.get(ResumeSession, session_id)
        if not _active(row):
            raise ConversationNotFound()
        conversation = db.get(Conversation, session_id)
        if conversation and (not owner_hash or conversation.owner_hash != owner_hash):
            raise ConversationNotFound()
        if conversation is None and owner_hash:
            conversation = Conversation(session_id=session_id, owner_hash=owner_hash, title=DEFAULT_TITLE)
            db.add(conversation)
        if conversation and conversation.title == DEFAULT_TITLE:
            conversation.title = " ".join(first_input.split())[:40] or DEFAULT_TITLE
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()


def session_owner(session_id: str) -> str:
    """Resolve only ownership metadata, without decrypting any private content."""
    with SessionLocal() as db:
        row = db.get(ResumeSession, session_id)
        conversation = db.get(Conversation, session_id)
        if not _active(row) or not conversation or not row.owner_key:
            raise ConversationNotFound()
        return conversation.owner_hash


def checkpoint_owner(session_id: str) -> str:
    """Immutable encryption binding; authorization uses session_owner instead.

    Keeping this binding stable permits an atomic browser-to-account claim in
    the application DB without a dangerous cross-database re-encryption window.
    """
    with SessionLocal() as db:
        row = db.get(ResumeSession, session_id)
        if row is None or not row.owner_key:
            raise ConversationNotFound()
        return row.owner_key


async def claim_browser(old_owner: str, new_owner: str) -> int:
    """Transfer the catalog with the authenticated browser capability only."""
    if not old_owner or not new_owner.startswith("account:") or old_owner.startswith("account:"):
        raise ConversationNotFound()
    with SessionLocal() as db:
        rows = db.query(Conversation).filter(Conversation.owner_hash == old_owner).with_for_update().all()
        for conversation in rows:
            title = conversation.title
            conversation.owner_hash = new_owner
            conversation.title = title
            from app.services.profile_bridge import ClaimedHistoryImport
            db.add(ClaimedHistoryImport(session_id=conversation.session_id, owner=new_owner, status="pending"))
        db.commit()
        return len(rows)


async def claim_guest(old_owner: str | None, new_owner: str, session_id: str) -> dict:
    """Claim only the selected active draft; preserve immutable crypto AAD.

    Ownership is checked again under the same lock used by chat/edit/cleanup.
    Same-account retries work after the successful response removed the cookie.
    A session ID alone cannot transfer any session to another account.
    """
    if not new_owner.startswith("account:"):
        raise ConversationNotFound()
    from app.services.session_store import session_lock
    from app.services.profile_bridge import ClaimedHistoryImport

    async with session_lock(session_id):
        with SessionLocal() as db:
            conversation = db.get(Conversation, session_id)
            row = db.get(ResumeSession, session_id)
            if not conversation or not _active(row) or not row.owner_key.startswith("guest:"):
                raise ConversationNotFound()
            if conversation.owner_hash == new_owner:
                return {"claimed": 0, "session_id": session_id}
            if not old_owner or not old_owner.startswith("guest:") or conversation.owner_hash != old_owner:
                raise ConversationNotFound()
            title = conversation.title
            conversation.owner_hash = new_owner
            conversation.title = title
            for suggestion in db.query(ResumeSuggestion).filter_by(session_id=session_id, owner=old_owner):
                payload = suggestion.payload
                suggestion.owner = new_owner
                suggestion.payload = payload
            db.add(ClaimedHistoryImport(session_id=session_id, owner=new_owner, status="pending"))
            db.commit()
    return {"claimed": 1, "session_id": session_id}


def assert_session_owner(owner: str | None, session_id: str) -> None:
    if not owner or session_owner(session_id) != owner:
        raise ConversationNotFound()


def remove_conversation(session_id: str) -> None:
    with SessionLocal() as db:
        db.query(ResumeSuggestion).filter_by(session_id=session_id).delete(synchronize_session=False)
        row = db.get(Conversation, session_id)
        if row is not None:
            db.delete(row)
        db.commit()
