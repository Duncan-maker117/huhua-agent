"""List and reopen persisted chats without constructing or calling an LLM."""

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from app.agents.public_reply import _public_text
from app.agents.resume_graph import _serialize_to_resume_data
from app.config import get_settings
from app.services.canonical_resume import current_canonical
from app.services.conversation_store import (
    ConversationNotFound,
    DEFAULT_TITLE,
    create_conversation,
    list_conversations,
    load_conversation,
    update_conversation_title,
)
from app.services.account_service import resolve_owner
from app.services.profile_bridge import protect_data, protect_state
from app.services.session_store import resume_data_has_content, session_lock
from app.services.resume_workspace import build_workspace

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateConversationRequest(BaseModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


def _history_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="暂时无法读取历史对话，请稍后重试")


@router.get("/conversations")
async def conversations(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    owner_hash = resolve_owner(request, response)
    try:
        recovery_ids = []
        items = list_conversations(owner_hash, title_recovery_ids=recovery_ids)
        checkpointer = getattr(request.app.state, "checkpointer", None)
        for item in items:
            session_id = item["session_id"]
            if session_id not in recovery_ids or checkpointer is None:
                continue
            lock = session_lock(session_id)
            if lock.locked():
                continue
            try:
                async with lock:
                    snapshot = await checkpointer.aget_tuple({"configurable": {"thread_id": session_id}})
                    values = (snapshot.checkpoint.get("channel_values") if snapshot else {}) or {}
                    item["title"] = update_conversation_title(owner_hash, session_id, values, legacy_only=True)
            except Exception:
                logger.warning("Legacy conversation title recovery failed")
        return {
            "conversations": items,
            "retention_days": get_settings().SESSION_RETENTION_DAYS,
        }
    except Exception:
        logger.error("conversation catalog read failed")
        raise _history_unavailable() from None


@router.post("/conversations")
async def new_conversation(request: Request, response: Response, body: CreateConversationRequest | None = None):
    response.headers["Cache-Control"] = "no-store"
    owner_hash = resolve_owner(request, response, allow_guest=True)
    session_id = body.session_id if body else None
    try:
        if session_id:
            async with session_lock(session_id):
                metadata = create_conversation(owner_hash, session_id)
                checkpointer = getattr(request.app.state, "checkpointer", None)
                if metadata["title"] == DEFAULT_TITLE and checkpointer is not None:
                    try:
                        snapshot = await checkpointer.aget_tuple({"configurable": {"thread_id": session_id}})
                        values = (snapshot.checkpoint.get("channel_values") if snapshot else {}) or {}
                        metadata["title"] = update_conversation_title(owner_hash, session_id, values)
                    except Exception:
                        # Recovering a label is optional; keep the successful
                        # claim and let the detail endpoint report read errors.
                        logger.warning("legacy conversation title recovery failed")
                return metadata
        return create_conversation(owner_hash)
    except ConversationNotFound:
        raise HTTPException(status_code=404, detail="对话不存在或已删除") from None
    except Exception:
        logger.error("conversation creation failed")
        raise HTTPException(status_code=503, detail="暂时无法保存对话，请稍后重试") from None


def _public_messages(values: dict) -> list[dict]:
    messages = []
    for message in values.get("messages") or []:
        if isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            # Tool-calling assistant messages are internal work, not replies.
            if message.tool_calls or message.additional_kwargs.get("tool_calls"):
                continue
            role = "assistant"
        else:
            continue
        content = _public_text(message.content)
        if content:
            messages.append({"role": role, "content": content})
    return messages


@router.get("/conversations/{session_id}")
async def conversation_detail(session_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    owner = resolve_owner(request, allow_guest=True)
    async with session_lock(session_id):
        try:
            stored = load_conversation(owner, session_id)
        except ConversationNotFound:
            raise HTTPException(status_code=404, detail="对话不存在或已删除") from None
        except Exception:
            logger.error("conversation metadata read failed")
            raise _history_unavailable() from None
        checkpointer = getattr(request.app.state, "checkpointer", None)
        if checkpointer is None:
            raise _history_unavailable()
        try:
            snapshot = await checkpointer.aget_tuple({"configurable": {"thread_id": session_id}})
            values = protect_state(owner, (snapshot.checkpoint.get("channel_values") if snapshot else {}) or {})
            if not values and (stored["stage"] != "JD_INPUT" or stored["has_data"] or stored["resume_draft"]):
                raise RuntimeError("Nonempty conversation checkpoint is missing")
            canonical = protect_data(owner, current_canonical(values, stored, _serialize_to_resume_data))
            return {
                "session_id": session_id,
                "title": stored["title"],
                "messages": _public_messages(values),
                "jd_text": values.get("jd_text") or "",
                "jd_info": values.get("jd_info") or {},
                "collected_info": values.get("collected_info") or {},
                "stage": values.get("stage") or stored["stage"],
                "resume_data": canonical,
                "workspace": build_workspace(values, canonical),
                "has_data": resume_data_has_content(canonical),
                "updated_at": stored["updated_at"],
            }
        except Exception:
            logger.error("conversation checkpoint read failed")
            raise _history_unavailable() from None
