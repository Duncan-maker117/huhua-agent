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
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.legacy_suggestions import ResumeSuggestion
from app.models.models import Conversation, ResumeSession
from app.services.session_store import DELETED_STAGE, _is_expired, resume_data_has_content

WORKSPACE_COOKIE = "huhua_workspace"
GUEST_COOKIE = "huhua_guest"
WORKSPACE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60
DEFAULT_TITLE = "新对话"
_COOKIE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_TITLE_WORD = re.compile(r"[^\W\u3400-\u9fff]+(?:[.+#'-][^\W\u3400-\u9fff]+)*(?:\+\+|#)?")


def _short_title(value: str, limit: int = 24) -> str:
    """CJK characters can wrap individually; Latin words must stay whole."""
    value = " ".join(value.split())
    end = min(len(value), limit)
    for word in _TITLE_WORD.finditer(value):
        if word.start() < end < word.end():
            end = word.start()
            break
    return value[:end].rstrip(" /·,，;；-:：")


def derive_conversation_title(state_values: dict) -> str | None:
    """Use structured job/candidate data only, never the opening utterance."""
    values = state_values or {}
    jd = values.get("jd_info") or {}
    role = jd.get("job_title")
    if isinstance(role, str) and role.strip():
        company = jd.get("company") or ""
        return _short_title(f"{company} · {role}" if company.strip() else role) or None
    sources = [values.get("collected_info") or {}, values.get("resume_data") or {}, values]
    # 简历头部的求职意向已按「本会话方向优先于档案旧方向」投影，标题与之保持一致。
    ordered = [values.get("resume_data") or {}, values.get("collected_info") or {}, values]
    direction = next((source.get("basic_info", {}).get("objective") for source in ordered
                      if (source.get("basic_info") or {}).get("objective")), None)
    direction = direction or values.get("role_direction") or jd.get("role_direction")
    if isinstance(direction, str) and direction.strip():
        direction = direction.strip().removesuffix("简历")
        shortened = _short_title(direction, 22)
        return f"{shortened}简历" if shortened else None
    names = []
    for source in sources:
        for group in ("projects", "work_experience", "internship", "campus", "open_source", "education"):
            for item in source.get(group) or []:
                name = item.get("name") or item.get("company") or item.get("school")
                if isinstance(name, str) and name.strip() and name.strip() not in names:
                    names.append(name.strip())
                if len(names) == 2:
                    return _short_title(" / ".join(names)) or None
        if names:
            break
    return _short_title(" / ".join(names)) or None


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


def _has_messages(conversation: Conversation, row: ResumeSession) -> bool:
    state = row.resume_state or {}
    if "has_messages" in state:
        return bool(state["has_messages"])
    # Before the explicit marker, touch_conversation advanced updated_at on
    # submission (including failed/cancelled turns). An untouched row was
    # flushed BEFORE its catalog entry was created. Treat other legacy writes
    # conservatively as activity so old conversations cannot be reused as blank.
    return bool(row.stage != "JD_INPUT" or state.get("authoritative")
                or (row.updated_at and conversation.created_at
                    and row.updated_at > conversation.created_at))


def _is_empty(conversation: Conversation, row: ResumeSession) -> bool:
    return (not _has_messages(conversation, row)
            and not resume_data_has_content(row.resume_data)
            and not (row.resume_draft or "").strip())


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
        "has_messages": _has_messages(conversation, row),
    }


def list_conversations(owner_hash: str, *, title_recovery_ids: list[str] | None = None) -> list[dict]:
    with SessionLocal() as db:
        rows = (
            db.query(Conversation, ResumeSession)
            .join(ResumeSession, ResumeSession.session_id == Conversation.session_id)
            .filter(Conversation.owner_hash == owner_hash, ResumeSession.stage != DELETED_STAGE)
            .order_by(ResumeSession.updated_at.desc(), Conversation.created_at.desc())
            .all()
        )
        result = []
        for conversation, row in rows:
            if not _active(row) or _is_empty(conversation, row):
                continue
            result.append(_metadata(conversation, row))
            if title_recovery_ids is not None:
                try:
                    if not (row.resume_state or {}).get("title_source"):
                        title_recovery_ids.append(row.session_id)
                except Exception:
                    # Optional label metadata must not break the catalog read.
                    pass
        return result


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
            candidates = (db.query(Conversation, ResumeSession)
                          .join(ResumeSession, ResumeSession.session_id == Conversation.session_id)
                          .filter(Conversation.owner_hash == owner_hash, ResumeSession.stage != DELETED_STAGE)
                          .order_by(Conversation.created_at.desc()).all())
            for conversation, row in candidates:
                if _active(row) and _is_empty(conversation, row):
                    return _metadata(conversation, row)
            session_id = str(uuid.uuid4())
            row = ResumeSession(session_id=session_id, owner_key=owner_hash, resume_data={}, stage="JD_INPUT",
                                resume_state={"title_source": "auto", "auto_title": DEFAULT_TITLE,
                                              "has_messages": False})
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
    """Compatibility entry point: an opening utterance is never a title."""
    with SessionLocal() as db:
        conversation = db.get(Conversation, session_id)
        if not conversation or conversation.owner_hash != owner_hash:
            raise ConversationNotFound()
        return conversation.title


def update_conversation_title(owner_hash: str, session_id: str, state_values: dict,
                              *, legacy_only: bool = False) -> str:
    """Update automatic labels using the same encrypted ORM fields as before.

    Source and the last automatic value live in the existing encrypted state.
    The value comparison also protects direct/manual title edits, even though
    the current API does not expose a conversation rename endpoint.
    """
    from app.services.profile_bridge import protect_data, protect_state
    from langchain_core.messages import HumanMessage

    with SessionLocal() as db:
        conversation = db.get(Conversation, session_id)
        row = db.get(ResumeSession, session_id)
        if not conversation or conversation.owner_hash != owner_hash or not _active(row):
            raise ConversationNotFound()
        title = conversation.title
        metadata = row.resume_state or {}
        source = metadata.get("title_source")
        if source not in (None, "auto") or (legacy_only and source):
            return title
        if source == "auto" and title != metadata.get("auto_title", DEFAULT_TITLE):
            metadata = {**metadata, "title_source": "manual"}
        elif source is None and title != DEFAULT_TITLE:
            first = next((message for message in state_values.get("messages") or []
                          if isinstance(message, HumanMessage)), None)
            first_text = first.content if first and isinstance(first.content, str) else ""
            old_title = " ".join(first_text.split())[:40]
            if not old_title:
                return title
            if title != old_title:
                # Unmarked custom labels are conservatively treated as manual.
                metadata = {**metadata, "title_source": "manual"}
        if metadata.get("title_source") != "manual":
            values = state_values
            if metadata.get("authoritative"):
                values = {**values, "collected_info": metadata.get("collected_info") or {},
                          "resume_data": row.resume_data or {}}
            derived = derive_conversation_title(protect_state(owner_hash, values))
            if not derived:
                return title
            title = protect_data(owner_hash, derived, db=db) or DEFAULT_TITLE
            metadata = {**metadata, "title_source": "auto", "auto_title": title}
        if conversation.title != title or row.resume_state != metadata:
            conversation.title = title
            # A lazy title repair must not reorder historical conversations.
            updated_at = row.updated_at
            row.resume_state = metadata
            row.updated_at = updated_at
            flag_modified(row, "updated_at")
            db.commit()
        return title


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
        row.resume_state = {**(row.resume_state or {}), "has_messages": True}
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
