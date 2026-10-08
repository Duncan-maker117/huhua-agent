"""Per-call contact minimization at text model boundaries.

Mappings are short-lived process memory only: never persist or log a redactor.
This is contact minimization, not complete anonymization. Image/file content is
opaque: direct vision OCR still sends the original image to its provider and
cannot promise pre-OCR redaction. Restore only at an existing source-validation
boundary; a restored value is not, by itself, evidence for a new fact.
"""

from copy import deepcopy
import re
import secrets
import string

from langchain_core.messages import BaseMessage, SystemMessage

CONTACT_PRIVACY_NOTICE = (
    "联系方式隐私规则：⟦邮箱:…⟧、⟦电话:…⟧是本次调用的联系方式占位，"
    "表示原材料已提供对应联系方式，不视为缺失，也不要追问真实号码或邮箱。"
    "不猜测占位内容；结构化提取或引用原句时逐字保留占位，应用会在本地还原并核对来源。"
    "占位不代表已验证可联系；仍保留材料中的否定、用途与归属。"
)

_EMAIL = re.compile(
    r"(?<![A-Za-z0-9_.+-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+"
    r"(?![A-Za-z0-9_-])"
)
_LABELLED_PHONE = re.compile(
    r"(?P<label>(?<![A-Za-z_])(?:联系电话|联系手机|手机号码|电话号码|联系方式|手机号|电话|手机|座机|"
    r"phone(?:_number)?|mobile(?:_number)?|telephone|tel)"
    r"[\"'’]?\s*(?:[:：=]|是|为)?\s*[\"'‘]?\s*)"
    r"(?P<value>\+?\d[\d \t()（）\-－–]{4,}\d)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_MOBILE = re.compile(
    r"(?<![A-Za-z0-9_])(?:(?:\+86|0086)[ \t-]?)?"
    r"1[3-9]\d[ \t-]?\d{4}[ \t-]?\d{4}(?![A-Za-z0-9_])"
)
_NONCONTACT_PREFIX = re.compile(
    r"(?:订单(?:号)?|编号|流水号|学号|身份证(?:号)?|单号|交易号|工号|编号|"
    r"order(?:_id)?|id|sku)\s*[:：=是为]?\s*[\"']?\s*$",
    re.IGNORECASE,
)
_METRIC_SUFFIX = re.compile(
    r"^\s*(?:[%％]|(?:条|次|个|元|人|行|字节|件|笔|台|份|万|亿)|"
    r"(?:tokens?|requests?|bytes?|ms|seconds?)\b)", re.IGNORECASE
)
_OPAQUE_TYPES = {"image_url", "input_image", "image", "file", "input_file", "audio", "input_audio", "video"}
_PHONE_FIELDS = {"phone", "phone_number", "mobile", "mobile_number", "telephone", "tel", "电话", "手机", "手机号", "联系电话"}
_CONTACT_TOKEN = re.compile(r"⟦(?P<kind>邮箱|电话):[a-z]{6}:[A-Z]+⟧")


class ContactRedactor:
    """Redact/restore copies of JSON-shaped data with one mapping per model call."""

    def __init__(self):
        self._nonce = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))
        self._originals: dict[str, str] = {}
        self._tokens: dict[tuple[str, str], str] = {}

    @property
    def has_contacts(self) -> bool:
        return bool(self._originals)

    def _token(self, kind: str, value: str) -> str:
        key = (kind, value)
        if key not in self._tokens:
            # Alphabetic counters avoid introducing fake metrics into model inputs.
            number, suffix = len(self._tokens), ""
            while True:
                suffix = string.ascii_uppercase[number % 26] + suffix
                number = number // 26 - 1
                if number < 0:
                    break
            token = f"⟦{kind}:{self._nonce}:{suffix}⟧"
            self._tokens[key] = token
            self._originals[token] = value
        return self._tokens[key]

    def _redact_text(self, text: str) -> str:
        text = _EMAIL.sub(lambda match: self._token("邮箱", match.group()), text)

        def labelled(match):
            value = match.group("value")
            digits = re.sub(r"\D", "", value)
            if not 7 <= len(digits) <= 15 or re.fullmatch(r"\d{4}[- ]\d{1,2}[- ]\d{1,2}", value):
                return match.group()
            return match.group("label") + self._token("电话", value)

        text = _LABELLED_PHONE.sub(labelled, text)

        def mobile(match):
            if _NONCONTACT_PREFIX.search(text[max(0, match.start() - 28):match.start()]):
                return match.group()
            if _METRIC_SUFFIX.match(text[match.end():]):
                return match.group()
            if re.match(r"[.,]\d", text[match.end():]):
                return match.group()
            return self._token("电话", match.group())

        return _MOBILE.sub(mobile, text)

    def _walk(self, value, transform):
        if isinstance(value, str):
            # Binary data URLs are never interpreted as ordinary text.
            return value if value.startswith("data:") else transform(value)
        if isinstance(value, list):
            return [self._walk(item, transform) for item in value]
        if isinstance(value, tuple):
            return tuple(self._walk(item, transform) for item in value)
        if isinstance(value, dict):
            if isinstance(value.get("type"), str) and value["type"] in _OPAQUE_TYPES:
                return deepcopy(value)
            result = {}
            for key, item in value.items():
                phone_field = isinstance(key, str) and key.casefold() in _PHONE_FIELDS
                phone_fact = key == "value" and isinstance(value.get("field"), str) and value["field"] in _PHONE_FIELDS
                if isinstance(item, str) and (phone_field or phone_fact):
                    copied = transform("电话: " + item)[len("电话: "):]
                else:
                    copied = self._walk(item, transform)
                result[transform(key) if isinstance(key, str) else key] = copied
            return result
        return deepcopy(value)

    def redact(self, value):
        return self._walk(value, self._redact_text)

    def restore(self, value):
        def restore_text(text):
            # Only the exact tokens created by this instance can be restored.
            return re.sub(r"⟦(?:邮箱|电话):[a-z]+:[A-Z]+⟧", lambda m: self._originals.get(m.group(), m.group()), text)
        return self._walk(value, restore_text)


def redact_model_messages(messages: list, privacy: ContactRedactor | None = None) -> list:
    """Clone actual outbound messages, including dynamic contracts/tool arguments.

    Identifiers, roles and other non-content message metadata remain unchanged.
    LangChain and dictionary chat messages are both accepted. Never mutate the
    canonical message history in order to apply model-only minimization.
    """
    privacy = privacy if privacy is not None else ContactRedactor()
    safe = []
    for message in messages:
        if isinstance(message, BaseMessage):
            update = {"content": privacy.redact(message.content)}
            for key in ("additional_kwargs", "tool_calls", "invalid_tool_calls"):
                if hasattr(message, key):
                    update[key] = privacy.redact(getattr(message, key))
            safe.append(message.model_copy(deep=True, update=update))
        elif isinstance(message, dict):
            cloned = deepcopy(message)
            for key in ("content", "function_call", "tool_calls"):
                if key in cloned:
                    cloned[key] = privacy.redact(cloned[key])
            safe.append(cloned)
        else:
            raise TypeError("Model messages must be chat message objects")
    if privacy.has_contacts:
        # Append to an existing system message so callers relying on the first
        # human data message retain the same shape. Never promote user content.
        for index, message in enumerate(safe):
            if isinstance(message, SystemMessage) and isinstance(message.content, str):
                if CONTACT_PRIVACY_NOTICE not in message.content:
                    safe[index] = message.model_copy(update={"content": message.content + "\n\n" + CONTACT_PRIVACY_NOTICE})
                break
            if isinstance(message, dict) and message.get("role") == "system" and isinstance(message.get("content"), str):
                if CONTACT_PRIVACY_NOTICE not in message["content"]:
                    message["content"] += "\n\n" + CONTACT_PRIVACY_NOTICE
                break
        else:
            safe.insert(0, SystemMessage(content=CONTACT_PRIVACY_NOTICE))
    return safe


class ContactTokenStream:
    """Render internal contact placeholders without exposing their random nonce.

    A public call can receive messages already redacted by career_messages, so
    it need not own the reversible mapping. Public prose uses readable labels;
    it never infers or restores unknown contact values. Only a possible token
    suffix is buffered; ordinary SSE text passes through immediately.
    """

    def __init__(self):
        self._pending = ""

    def feed(self, text: str) -> str:
        self._pending += text
        result = []
        while self._pending:
            start = self._pending.find("⟦")
            if start < 0:
                result.append(self._pending)
                self._pending = ""
                break
            result.append(self._pending[:start])
            self._pending = self._pending[start:]
            end = self._pending.find("⟧")
            if end >= 0:
                token = self._pending[:end + 1]
                match = _CONTACT_TOKEN.fullmatch(token)
                result.append(f"（{match['kind']}已提供）" if match else token)
                self._pending = self._pending[end + 1:]
                continue
            partial = self._pending
            is_prefix = any(prefix.startswith(partial) for prefix in ("⟦邮箱:", "⟦电话:"))
            is_prefix = is_prefix or bool(re.fullmatch(r"⟦(?:邮箱|电话):[a-z]{0,6}(?::[A-Z]*)?", partial))
            if is_prefix and len(partial) < 96:
                break
            result.append(self._pending[0])
            self._pending = self._pending[1:]
        return "".join(result)

    def finish(self) -> str:
        pending, self._pending = self._pending, ""
        # Interrupted tokens should not leave opaque identifiers in the UI.
        for kind in ("邮箱", "电话"):
            if pending.startswith(f"⟦{kind}:"):
                return f"（{kind}已提供）"
        return pending
