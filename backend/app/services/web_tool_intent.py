"""Conservative URL intent matching; never searches or interprets attachments.

Call with the latest user-authored composer text, not assembled model context.
Validation here is syntactic only. The reader still enforces public DNS/IP rules.
"""
from __future__ import annotations

import re
from app.services.web_research import WebResearchError, _normalize_url

_URL = re.compile(
    r"https?://[^\s<>\"'，。；！？、（）【】]+|(?<![A-Za-z0-9_./@-])(?:www\.)?github\.com"
    r"(?=$|[/\s<>\"'，。；！？、（）【】])(?:/[^\s<>\"'，。；！？、（）【】]*)?",
    re.I,
)
_READ_REQUEST = re.compile(
    r"查看|核对|查(?:看|一下|一查|下)|看看|看一下|帮我看|你看|检查|访问|打开|读(?:取|一下|一读|下)|"
    r"\b(?:read|check|review|inspect|visit|open)\b|\blook\s+at\b",
    re.I,
)
_JD_READ_REQUEST = re.compile(
    r"(?:读取|读一下|解读|分析|拆解|查看|读懂|解析|检查|核对|看看|看一下)"
    r"(?:(?:这个|这份|这条|下列|以下|一下|目标|新的?|一份|这|该|个|份|条)|[\s,:：，]){0,8}"
    r"(?:招聘(?:链接|网页|页面|信息|职位|岗位)?|JD(?![a-z0-9_])|岗位(?:要求|职责|说明|描述|链接|信息)|职位(?:要求|描述|说明|链接|信息))"
    r"|\b(?:read|review|analy[sz]e|decode)(?:\s+(?:this|the|following|new|target))?\s+(?:JD\b|job description\b|job posting\b)",
    re.I,
)
_NO_READ = re.compile(
    r"(?:不要|别|不用|无需|暂不|先不|不必|禁止|(?<!能)不能|不想)[^。！？\n]{0,24}"
    r"(?:联网|上网|访问|打开|读取|查看|检查|解读|分析|拆解|解析|读懂|看|查|搜索)|"
    r"\b(?:do\s+not|don['’]?t|never|without)\b[^\n]{0,40}\b(?:read|check|review|inspect|visit|open|browse|fetch|search)\b",
    re.I,
)
_ATTACHMENT = re.compile(r"\[(?:文件|附件|file|attachment)\s*[:：]|```", re.I)
_REQUEST_PREFIX = re.compile(
    r"(?:请|帮我|麻烦(?:你)?|能否|能不能|你(?:能不能|可以|能|帮我)?|给我|替我)"
    r"(?:(?:先|直接|再|去|现在|顺便|认真|实际|联网|上网|帮我|看)\s*){0,4}$|"
    r"\b(?:please|can you|could you|would you|help me)\s*$", re.I,
)


def _trim_url(value: str) -> str:
    value = value.rstrip(".,;:!?，。；：！？")
    while value.endswith(")") and value.count(")") > value.count("("):
        value = value[:-1]
    return value


def _is_explicit_request(match: re.Match | None, text: str) -> bool:
    if match is None:
        return False
    prefix = text[:match.start()]
    return not prefix.strip() or _REQUEST_PREFIX.search(prefix) is not None


def infer_web_tool(text: str) -> dict | None:
    """自动识别一条用户链接；招聘与普通网页在读取后再区分。

    GitHub 和明确的公开作品请求沿用参考路径；否定、附件/代码材料和
    多链接继续交给用户明确对象，不将附件内的 URL 视作读取指令。
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        return None
    if _ATTACHMENT.search(text) or _NO_READ.search(text):
        return None
    matches = list(_URL.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    candidate = _trim_url(match.group())
    if not re.match(r"https?://", candidate, re.I):
        candidate = "https://" + candidate
    try:
        normalized, host, _ = _normalize_url(candidate)
    except WebResearchError:
        return None
    # A URL in an email address or a larger URI-like token is not an instruction.
    if match.start() and text[match.start() - 1] in "@/\\":
        return None
    remainder = (text[:match.start()] + text[match.end():]).strip(" \t\r\n()（）<>，。；：！？.,;:!?")
    github = host in {"github.com", "www.github.com"}
    if not remainder:
        return {"action": "read_public_url" if github else "read_url", "url": normalized}
    # The requested object must directly follow the read/analysis verb. Merely
    # mentioning a JD elsewhere in a portfolio request must not replace it.
    if _is_explicit_request(_JD_READ_REQUEST.search(remainder), remainder):
        return {"action": "read_public_url" if github else "read_url", "url": normalized}
    request = _READ_REQUEST.search(remainder)
    if _is_explicit_request(request, remainder) and (github or re.search(
            r"作品集|仓库|主页|\bportfolio\b|/project(?:[/?#]|$)", remainder + " " + normalized, re.I)):
        return {"action": "read_public_url", "url": normalized}
    # 招聘链接无需另点按钮；最终是否为 JD 由安全读取后的正文决定。
    return {"action": "read_public_url" if github else "read_url", "url": normalized}
