"""Opt-in token streaming for user-visible prose, never internal LLM work.

Nodes retain one complete AIMessage for checkpointing. Custom events carry only
text deltas and its stable reply id; they do not expose tools, reasoning, usage,
or the normal LangGraph model-message stream.
"""

import asyncio
import logging
import re
from typing import Callable
from uuid import uuid4

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.config import get_config, get_stream_writer

from app.services.llm_compat import label_run
from app.services.model_privacy import ContactTokenStream, redact_model_messages

logger = logging.getLogger(__name__)
PUBLIC_REPLY_EVENT = "public_reply_delta"
PUBLIC_REPLY_INTERRUPTED = "\n\n本次回复中断，请重试；以上内容可能不完整。"


class EmptyPublicReplyError(ValueError):
    """The provider completed successfully without public text."""


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
    single_question: bool = False,
    ask_state: dict | None = None,
    publish: bool = True,
) -> AIMessage:
    """Stream an explicitly public call and return its completed checkpoint text.

    Direct node calls outside a running graph still work. Non-streaming test or
    legacy adapters use one ainvoke result; real chat models use astream.
    Cancellation propagates and closes the upstream iterator. A midstream model
    failure is closed with a clear interruption notice, not retried into an
    already visible response.
    """
    from app.services.ask_user import AskUser, can_ask_user, question_context, validate_card
    enabled = ask_state is not None
    tools_available = callable(getattr(llm, "bind_tools", None))
    if enabled:
        messages = [*messages, SystemMessage(content=question_context(ask_state, tools_available=tools_available))]
        if tools_available and can_ask_user(ask_state):
            tool = convert_to_openai_tool(AskUser)
            tool['function'].update(name='ask_user', description='用结构化问题卡收集用户补充信息。')
            llm = llm.bind_tools([tool], tool_choice="auto")
        # 预算在生成前约束；包括无工具适配器和表单轮，均不事后裁剪正文。
        single_question = False
    messages = redact_model_messages(messages)
    llm = label_run(llm, "public_reply")
    reply_id = str(uuid4())
    try:
        writer = get_stream_writer()
        node = get_config().get("metadata", {}).get("langgraph_node", "")
    except (RuntimeError, KeyError):
        writer = None
        node = ""
    if not publish:
        writer = None
    parts: list[str] = []
    contact_text = ContactTokenStream()
    question_tail: list[str] = []
    asked = False
    tool_parts: dict = {}
    completed_tools: list = []

    def collect_tools(message):
        # OpenAI 兼容流按 index 拼接名称与 JSON；不要提前解析未完成的参数。
        chunks = getattr(message, "tool_call_chunks", None)
        if chunks:
            for chunk in chunks:
                entry = tool_parts.setdefault(chunk.get("index", 0), {"name": "", "args": ""})
                entry["name"] += chunk.get("name") or ""
                entry["args"] += chunk.get("args") or ""
        else:
            completed_tools.extend(getattr(message, "tool_calls", None) or [])

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

    def emit_public(text: str) -> None:
        nonlocal asked
        if not single_question:
            emit(text)
        elif asked:
            question_tail.append(text)
        elif match := re.search(r"[？?]", text):
            emit(text[:match.end()])
            question_tail.append(text[match.end():])
            asked = True
        else:
            emit(text)

    async def consume() -> None:
        stream = getattr(llm, "astream", None)
        if not callable(stream):
            response = await llm.ainvoke(messages)
            collect_tools(response)
            emit_public(contact_text.feed(_public_text(response.content)))
            return
        iterator = stream(messages)
        try:
            async for chunk in iterator:
                collect_tools(chunk)
                emit_public(contact_text.feed(_public_text(chunk.content)))
        finally:
            close = getattr(iterator, "aclose", None)
            if callable(close):
                await close()

    interrupted = False
    try:
        async with asyncio.timeout(timeout):
            await consume()
        emit_public(contact_text.finish())
        if question_tail:
            emit("".join(part for part in re.split(r"(?<=[。！？!?])", "".join(question_tail))
                         if not re.search(r"[？?]", part)))
        if not "".join(parts).strip() and not (tool_parts or completed_tools):
            raise EmptyPublicReplyError("Empty public reply")
    except Exception as exc:
        emit(contact_text.finish())
        if not parts or isinstance(exc, EmptyPublicReplyError):
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
    card = {}
    if enabled and tools_available and not interrupted:
        for call in [*tool_parts.values(), *completed_tools]:
            if call.get("name") == "ask_user":
                card = validate_card(call.get("args"), ask_state, reply_id)
                break
    return AIMessage(
        content="".join(parts),
        id=reply_id,
        additional_kwargs={"public_reply_interrupted": interrupted,
                           **({"ask_user_enabled": True} if enabled else {}),
                           **({"ask_user": card} if card else {})},
    )
