"""Keep structured output requests compatible with the selected LLM endpoint."""

from typing import Any
from urllib.parse import urlsplit

from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel


_DEEPSEEK_MODELS = {
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-flash",
    "deepseek-v4-pro",
}


def _endpoint_host(llm: ChatOpenAI) -> str:
    base_url = llm.openai_api_base
    if base_url:
        return (urlsplit(str(base_url)).hostname or "").lower()
    for client in (llm.root_async_client, llm.root_client):
        client_url = getattr(client, "base_url", None)
        if client_url:
            return (urlsplit(str(client_url)).hostname or "").lower()
    return ""


def _deepseek_model_name(name: str) -> bool:
    folded = (name or "").lower()
    return folded.startswith("deepseek") or folded.startswith("vanchin/deepseek")


def _is_deepseek(llm: ChatOpenAI) -> bool:
    """Official DeepSeek and DeepSeek-named models, including Bailian and Vanchin."""
    host = _endpoint_host(llm)
    if host == "api.deepseek.com" or _deepseek_model_name(llm.model_name):
        return True
    return llm.model_name.lower() in _DEEPSEEK_MODELS


def _disable_thinking(host: str) -> dict:
    # DashScope rejects the official DeepSeek thinking switch and uses its own flag.
    if host == "dashscope.aliyuncs.com":
        return {"enable_thinking": False}
    return {"thinking": {"type": "disabled"}}


def with_structured_output(
    llm: ChatOpenAI,
    schema: type[BaseModel] | dict[str, Any],
) -> Runnable:
    """Use DeepSeek tool calls without changing the original chat model.

    DeepSeek accepts tool calling, but not OpenAI's ``json_schema`` response
    format. A forced tool choice also requires its thinking mode to be disabled.
    Keep these settings on a copy, since the same LLM is used for ordinary chat.
    Other providers and lightweight test doubles retain the library default.
    """
    if not isinstance(llm, ChatOpenAI) or not _is_deepseek(llm):
        return llm.with_structured_output(schema)

    extra_body = {**(llm.extra_body or {})}
    extra_body.pop("thinking", None)
    extra_body.pop("enable_thinking", None)
    extra_body.update(_disable_thinking(_endpoint_host(llm)))
    structured_llm = llm.model_copy(update={"extra_body": extra_body})
    return structured_llm.with_structured_output(
        schema, method="function_calling", strict=False
    )
