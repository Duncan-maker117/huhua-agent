"""Shared authorization for every session-derived private endpoint."""

from fastapi import HTTPException

from app.services.conversation_store import ConversationNotFound, assert_session_owner


def authorize_session(request, session_id, *, allow_guest=True):
    from app.services.account_service import resolve_owner
    owner = resolve_owner(request, allow_guest=allow_guest)
    try:
        assert_session_owner(owner, session_id)
    except ConversationNotFound:
        raise HTTPException(404, "对话不存在或无权访问") from None
    return owner
