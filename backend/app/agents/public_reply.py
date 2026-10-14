"""Opt-in token streaming for user-visible prose, never internal LLM work.

Nodes retain one complete AIMessage for checkpointing. Custom events carry only
text deltas and its stable reply id; they do not expose tools, reasoning, usage,
or the normal LangGraph model-message stream.
"""

import asyncio
import logging
from typing import Callable
from uuid import uuid4

from langchain_core.messages import AIMessage
from langgraph.config import get_config, get_stream_writer

from app.services.llm_compat import label_run
from app.services.model_privacy import ContactTokenStream, redact_model_messages

logger = logging.getLogger(__name__)
PUBLIC_REPLY_EVENT = "public_reply_delta"
PUBLIC_REPLY_INTERRUPTED = "\n\n本次回复中断，请重试；以上内容可能不完整。"


def _public_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Standard text content blocks only. Reasoning/tool blocks stay private.
        return "".join(
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
    return ""


async def stream_public_reply(
    llm, messages: list, *, suffix: str = "", timeout: float | None = None,
    transform: Callable[[str], str] | None = None,
) -> AIMessage:
    """Stream an explicitly public call and return its completed checkpoint text.

    Direct node calls outside a running graph still work. Non-streaming test or
    legacy adapters use one ainvoke result; real chat models use astream.
    Cancellation propagates and closes the upstream iterator. A midstream model
    failure is closed with a clear interruption notice, not retried into an
    already visible response.
    """
    messages = redact_model_messages(messages)
    llm = label_run(llm, "public_reply")
    reply_id = str(uuid4())
    try:
        writer = get_stream_writer()
        node = get_config().get("metadata", {}).get("langgraph_node", "")
    except (RuntimeError, KeyError):
        writer = None
        node = ""
    parts: list[str] = []
    contact_text = ContactTokenStream()

    def emit(text: str) -> None:
        if not text:
            return
        parts.append(text)
        if writer is not None and transform is None:
            writer(
                {
                    "type": PUBLIC_REPLY_EVENT,
                    "node": node,
                    "reply_id": reply_id,
                    "content": text,
                }
            )

    async def consume() -> None:
        stream = getattr(llm, "astream", None)
        if not callable(stream):
            response = await llm.ainvoke(messages)
            emit(contact_text.feed(_public_text(response.content)))
            return
        iterator = stream(messages)
        try:
            async for chunk in iterator:
                emit(contact_text.feed(_public_text(chunk.content)))
        finally:
            close = getattr(iterator, "aclose", None)
            if callable(close):
                await close()

    interrupted = False
    try:
        async with asyncio.timeout(timeout):
            await consume()
        emit(contact_text.finish())
        if not "".join(parts).strip():
            raise ValueError("Empty public reply")
    except Exception as exc:
        emit(contact_text.finish())
        if not parts:
            raise
        logger.warning("Public reply interrupted: %s", type(exc).__name__)
        interrupted = True
        emit(PUBLIC_REPLY_INTERRUPTED)
    if not interrupted:
        emit(suffix)
    if transform is not None:
        # Receipt corrections must precede public deltas, not only checkpointing.
        parts = [transform("".join(parts))]
        if writer is not None:
            writer({"type": PUBLIC_REPLY_EVENT, "node": node, "reply_id": reply_id, "content": parts[0]})
    return AIMessage(
        content="".join(parts),
        id=reply_id,
        additional_kwargs={"public_reply_interrupted": interrupted},
    )
