"""Opt-in token streaming for user-visible prose, never internal LLM work.

Nodes retain one complete AIMessage for checkpointing. Custom events carry only
text deltas and its stable reply id; they do not expose tools, reasoning, usage,
or the normal LangGraph model-message stream.
"""

import asyncio
import logging
import json
import re
from typing import Callable
from uuid import uuid4

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
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
    _profile_round: int = 0,
) -> AIMessage:
    """Stream an explicitly public call and return its completed checkpoint text.

    Direct node calls outside a running graph still work. Non-streaming test or
    legacy adapters use one ainvoke result; real chat models use astream.
    Cancellation propagates and closes the upstream iterator. A midstream model
    failure is closed with a clear interruption notice, not retried into an
    already visible response.
    """
    from app.services.ask_user import AskUser, can_ask_user, question_context, validate_card
    from app.services.job_intel.integration import SearchCompany, COMPANY_CONTRACT, company_tool, company_reply
    from app.services.job_intel import search_company
    from app.services.profile_tools import ReadProfile, UseProfileItems, tools_enabled, profile_contract, execute_profile_tool
    original_llm = llm
    profile_enabled = ask_state is not None and tools_enabled(ask_state) and _profile_round < 2
    enabled = ask_state is not None
    tools_available = callable(getattr(llm, "bind_tools", None))
    if enabled:
        messages = [*messages, SystemMessage(content=COMPANY_CONTRACT + "\n" + question_context(ask_state, tools_available=tools_available))]
        if tools_available:
            tools = []
            if can_ask_user(ask_state):
                tool = convert_to_openai_tool(AskUser)
                tool['function'].update(name='ask_user', description='用结构化问题卡收集用户补充信息。')
                tools.append(tool)
            company = convert_to_openai_tool(SearchCompany)
            company['function'].update(name='search_company', description='按公司名查公开背景，附来源；每轮至多一次。')
            tools.append(company)
            if profile_enabled:
                for schema, name, description in ((ReadProfile, "read_profile", "读取本人档案经历目录，按岗位相关度排序。"),
                                                   (UseProfileItems, "use_profile_items", "将目录中的经历导入当前对话，必须说明导入了哪几段。")):
                    profile_tool = convert_to_openai_tool(schema)
                    profile_tool["function"].update(name=name, description=description)
                    tools.append(profile_tool)
            llm = llm.bind_tools(tools, tool_choice="auto")
        # 预算在生成前约束；包括无工具适配器和表单轮，均不事后裁剪正文。
        single_question = False
    if profile_enabled:
        messages = [*messages, SystemMessage(content=profile_contract(ask_state))]
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
                entry["id"] = entry.get("id") or chunk.get("id") or ""
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
    profile_update, imported, profile_card = {}, [], {}
    if profile_enabled and tools_available and not interrupted:
        calls = [call for call in [*tool_parts.values(), *completed_tools]
                 if call.get("name") in {"read_profile", "use_profile_items"}][:2]
        history = list(messages)
        working = dict(ask_state)
        for call in calls:
            try:
                result, update = await execute_profile_tool(call["name"], call.get("args"), working)
            except (ValueError, TypeError):
                result, update = {"status": "invalid_arguments", "message": "请使用目录中的条目 ID。"}, {}
            working.update(update)
            profile_update.update(update)
            imported.extend(result.get("imported") or [])
            arguments = call.get("args") or {}
            try:
                arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            except ValueError:
                arguments = {}
            # DeepSeek 思考模式按模型生成的调用 ID 找回 reasoning；自造 ID 会被拒（400）。
            call_id = call.get("id") or str(uuid4())
            history.extend([AIMessage(content="", tool_calls=[{"id": call_id, "name": call["name"], "args": arguments}]),
                            ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call_id)])
        if calls:
            # 续写关闭思考：DeepSeek 思考模式要求回传上一轮 reasoning_content，而 LangChain 不保留它。
            from app.services.llm_compat import without_thinking
            continuation = await stream_public_reply(without_thinking(original_llm), history, ask_state=working,
                timeout=timeout, publish=False, _profile_round=_profile_round + 1)
            # 模型已逐一说明导入了哪几段时，不再重复确定性回执。
            if imported and not all(name in continuation.content for name in imported):
                emit(("\n\n" if parts else "") + "已从档案导入：" + "、".join(imported) + "。")
            emit(("\n\n" if parts else "") + continuation.content)
            profile_update.update(continuation.additional_kwargs.get("profile_update") or {})
            profile_card = continuation.additional_kwargs.get("ask_user") or {}
    intel_company = {}
    if enabled and tools_available and not interrupted:
        # 同一输出即使携带多个公司调用，也只执行第一个；不启动自主工具循环。
        call = next((call for call in [*tool_parts.values(), *completed_tools]
                     if call.get("name") == "search_company"), None)
        if call:
            try:
                parsed = await company_tool(call.get("args"), ask_state)
                result = parsed if isinstance(parsed, dict) else await search_company(parsed.name, llm=original_llm)
            except Exception:
                result = {"status": "unavailable", "message": "暂未查到可核对的公司资料。"}
            intel_company = result.get("company") or {}
            emit(("\n\n" if parts else "") + company_reply(result))
    if not interrupted:
        emit(suffix)
    if transform is not None:
        # Receipt corrections must precede public deltas, not only checkpointing.
        parts = [transform("".join(parts))]
        if writer is not None:
            writer({"type": PUBLIC_REPLY_EVENT, "node": node, "reply_id": reply_id, "content": parts[0]})
    card = profile_card
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
                           **({"profile_update": profile_update} if profile_update else {}),
                           **({"intel_company": intel_company} if intel_company else {}),
                           **({"ask_user": card} if card else {})},
    )
