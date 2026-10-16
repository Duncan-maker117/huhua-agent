"""Map model/provider failures to short user-facing codes.

User messages never contain provider names, raw error text, keys or URLs.
Logs should record only ``code``, the exception class name and status code.
"""

import json
from typing import Any

import httpx
import openai

QUOTA, AUTH, RATE = "E-MODEL-QUOTA", "E-MODEL-AUTH", "E-MODEL-RATE"
TIMEOUT, NETWORK, UPSTREAM = "E-MODEL-TIMEOUT", "E-MODEL-NETWORK", "E-MODEL-UPSTREAM"
INTERNAL = "E-INTERNAL"
SESSION_ENDED, HISTORY_UNAVAILABLE = "E-SESSION-ENDED", "E-HISTORY-UNAVAILABLE"

MESSAGES = {
    QUOTA: "模型服务暂不可用（额度问题），已保存的内容仍在，请稍后再试",
    AUTH: "模型服务配置异常，已保存的内容仍在，请稍后再试",
    RATE: "当前使用人数较多，请稍等几秒再试",
    TIMEOUT: "本次整理超时，已保存的内容仍在，请稍后重试",
    NETWORK: "连接模型服务失败，请检查网络后重试",
    UPSTREAM: "模型服务暂时异常，已保存的内容仍在，请稍后重试",
    INTERNAL: "生成失败，请稍后重试",
    SESSION_ENDED: "会话已结束，请新建对话",
    HISTORY_UNAVAILABLE: "历史对话暂时无法恢复，请稍后重试",
}

_QUOTA_WORDS = ("arrearage", "insufficient_balance", "insufficient balance", "insufficient_quota",
                "quota", "billing", "overdue", "out of credit", "欠费", "余额不足", "额度")


class ChatTurnError(RuntimeError):
    """A chat turn failed; ``message`` is safe to show to the user."""

    def __init__(self, code: str, message: str | None = None, *, error_type: str = "",
                 status_code: int | None = None):
        self.code = code
        self.message = message or MESSAGES.get(code, MESSAGES[INTERNAL])
        self.error_type = error_type
        self.status_code = status_code
        super().__init__(self.message)


def _body_text(exc: BaseException) -> str:
    parts: list[Any] = []
    if isinstance(exc, openai.APIStatusError):
        parts += [exc.body, getattr(exc, "code", None), getattr(exc, "type", None)]
    elif isinstance(exc, httpx.HTTPStatusError):
        try:
            parts.append(exc.response.text)
        except Exception:
            pass
    text = ""
    for part in parts:
        if part is None:
            continue
        text += " " + (part if isinstance(part, str) else json.dumps(part, ensure_ascii=False, default=str))
    return text.lower()


def _status(exc: BaseException) -> int | None:
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def _classify_one(exc: BaseException) -> str | None:
    status = _status(exc)
    if status is not None:
        if status == 402 or any(word in _body_text(exc) for word in _QUOTA_WORDS):
            return QUOTA
        if status in (401, 403):
            return AUTH
        if status == 429:
            return RATE
        return UPSTREAM
    if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException, TimeoutError)):
        return TIMEOUT
    if isinstance(exc, (openai.APIConnectionError, httpx.TransportError, ConnectionError)):
        return NETWORK
    if isinstance(exc, openai.OpenAIError):
        return UPSTREAM
    return None


def _walk(exc: BaseException):
    seen: set[int] = set()
    queue = [exc]
    while queue and len(seen) < 20:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        queue += [e for e in (current.__cause__, current.__context__) if e is not None]


def _classify(exc: BaseException) -> tuple[str, BaseException, int | None]:
    for current in _walk(exc):
        if isinstance(current, ChatTurnError):
            return current.code, current, current.status_code
        code = _classify_one(current)
        if code:
            return code, current, _status(current)
    return INTERNAL, exc, None


def classify_error(exc: BaseException) -> tuple[str, str]:
    """Return ``(code, user_message)`` for any exception, following its cause chain."""
    code, found, _ = _classify(exc)
    if isinstance(found, ChatTurnError):
        return code, found.message
    return code, MESSAGES[code]


def error_log_fields(exc: BaseException) -> tuple[str, str, int | None]:
    """Return ``(code, exception class name, status code)``: the only data safe to log."""
    code, found, status = _classify(exc)
    if isinstance(found, ChatTurnError):
        return code, found.error_type or type(found).__name__, status
    return code, type(found).__name__, status


def to_turn_error(exc: BaseException) -> ChatTurnError:
    code, error_type, status = error_log_fields(exc)
    return ChatTurnError(code, classify_error(exc)[1], error_type=error_type, status_code=status)


MATERIAL_RETRY_MESSAGE = "模型服务暂时没有响应，这轮材料已收到但还没整理完成，已有草稿保持不变。请稍后点重试或重新发送。"


def require_model_response(response: Any) -> None:
    """Distinguish an empty transport response from a valid empty fact patch."""
    content = getattr(response, 'content', response)
    if isinstance(content, list) and all(isinstance(block, dict) for block in content):
        content = ''.join(block.get('text', '') for block in content if block.get('type') == 'text')
    if content is None or isinstance(content, (str, list)) and not (
        content.strip() if isinstance(content, str) else content
    ):
        raise ChatTurnError(UPSTREAM, MATERIAL_RETRY_MESSAGE, error_type='EmptyModelResponse')


def raise_model_failure(error: BaseException) -> None:
    """Promote primary-call outages only; secondary callers keep local fallback."""
    failure = to_turn_error(error)
    if failure.code.startswith('E-MODEL-'):
        raise ChatTurnError(failure.code, MATERIAL_RETRY_MESSAGE, error_type=failure.error_type,
                            status_code=failure.status_code) from None
