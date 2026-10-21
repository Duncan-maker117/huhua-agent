"""Shared authorization for every session-derived private endpoint."""

from fastapi import HTTPException

from app.services.conversation_store import ConversationNotFound, assert_session_owner, session_owner

OTHER_ACCOUNT_MESSAGE = "这份简历属于另一个账号。请退出当前账号，用生成它的邮箱登录后再打开此链接。"


def explain_other_account_link(request, owner, session_id):
    """Disclose only existence, only for authenticated MCP edit-link reads."""
    if not (owner or "").startswith("account:") or request.query_params.get("from") != "mcp":
        return
    try:
        actual = session_owner(session_id)
    except ConversationNotFound:
        return
    if actual.startswith("account:") and actual != owner:
        raise HTTPException(403, detail={"code": "conversation_other_account", "message": OTHER_ACCOUNT_MESSAGE},
                            headers={"Cache-Control": "no-store"})


def authorize_session(request, session_id, *, allow_guest=True, edit_link=False):
    from app.services.account_service import resolve_owner
    owner = resolve_owner(request, allow_guest=allow_guest)
    try:
        assert_session_owner(owner, session_id)
    except ConversationNotFound:
        if edit_link:
            explain_other_account_link(request, owner, session_id)
        raise HTTPException(404, "对话不存在或无权访问") from None
    return owner
