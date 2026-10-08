"""Bounded public-web material. Output is reference material, never candidate facts.

The requested host is resolved once per hop. The socket connects to that validated
IP while Host and TLS SNI retain the original name. Redirects are handled here,
not by a client; environment proxies and cookies are deliberately absent.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit
import zlib

import httpx

from app.config import get_settings

MAX_BODY_BYTES = 1_048_576
TOTAL_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3
READ_CONTENT_LIMIT = 12_000
SEARCH_CONTENT_LIMIT = 1_800
_FALLBACK = "请直接粘贴岗位正文，或上传招聘页面截图。"
_PUBLIC_FALLBACK = "请粘贴需要核对的公开页面正文，或上传截图。"
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_BLOCKED_NETS = tuple(ipaddress.ip_network(network) for network in (
    "192.0.0.0/24", "64:ff9b::/96", "64:ff9b:1::/48", "2001::/23", "2002::/16",
))


class WebResearchError(Exception):
    """Only fixed, user-safe messages cross the API boundary."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if (not address.is_global or address.is_multicast or address.is_reserved
            or address.is_unspecified or address.is_loopback or address.is_link_local
            or getattr(address, "ipv4_mapped", None) is not None):
        return False
    return not any(address in network for network in _BLOCKED_NETS
                   if address.version == network.version)


def _normalize_url(value: str) -> tuple[str, str, int]:
    if (not isinstance(value, str) or len(value) > 2048
            or re.search(r"[\x00-\x20\x7f\\]", value)):
        raise WebResearchError("请输入完整的公开招聘网页链接。")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme.lower() == "https" else 80)
        if (port != (443 if parsed.scheme.lower() == "https" else 80)
                or "%" in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal"))):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if ("." not in host or len(host) > 253
                    or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                           for label in host.split("."))):
                raise ValueError
        else:
            if not _public_ip(host):
                raise ValueError
        authority = f"[{host}]" if ":" in host else host
        normalized = urlunsplit((parsed.scheme.lower(), authority, parsed.path or "/", parsed.query, ""))
        # Let httpx canonicalize IDNA/path encoding, before DNS or requests.
        normalized = str(httpx.URL(normalized))
    except (ValueError, UnicodeError, httpx.InvalidURL):
        raise WebResearchError("仅支持不含登录凭证的公开 HTTP 或 HTTPS 网页链接。") from None
    return normalized, host, port


async def _resolve_public(host: str, port: int) -> str:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            answers = await asyncio.get_running_loop().getaddrinfo(
                host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except (OSError, UnicodeError):
            raise WebResearchError("无法找到这个网页。" + _FALLBACK, 502) from None
        addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    else:
        addresses = [host]
    # Reject mixed public/private records as well as a private first address.
    if not addresses or not all(_public_ip(address) for address in addresses):
        raise WebResearchError("这个链接不是可读取的公开网页。" + _FALLBACK)
    return next((address for address in addresses if ":" not in address), addresses[0])


@asynccontextmanager
async def _public_response(url: str, address: str, *, accept: str = "text/html,application/xhtml+xml,text/plain;q=0.9"):
    original = httpx.URL(url)
    request = httpx.Request(
        "GET", original.copy_with(host=address),
        headers={
            "Host": original.netloc.decode("ascii"),
            "User-Agent": "HuhuaResume/1.0 (public job page reader)",
            "Accept": accept,
            "Accept-Encoding": "gzip, deflate",
        },
        extensions={
            "sni_hostname": original.host,
            "timeout": {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0},
        },
    )
    # Direct transport avoids AsyncClient's INFO log containing user URLs.
    async with httpx.AsyncHTTPTransport(trust_env=False, retries=0) as transport:
        response = await transport.handle_async_request(request)
        try:
            yield response
        finally:
            await response.aclose()


async def _bounded_body(response: httpx.Response) -> bytes:
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise WebResearchError("网页内容过大，暂时无法读取。" + _FALLBACK)
    encoding = response.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in {"identity", "", "gzip", "deflate"}:
        raise WebResearchError("网页使用了暂不支持的压缩格式。" + _FALLBACK)
    decoder = (zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip"
               else zlib.decompressobj() if encoding == "deflate" else None)
    raw_size = 0
    output = bytearray()
    try:
        async for chunk in response.aiter_raw():
            raw_size += len(chunk)
            if raw_size > MAX_BODY_BYTES:
                raise WebResearchError("网页内容过大，暂时无法读取。" + _FALLBACK)
            if decoder is None:
                output.extend(chunk)
            else:
                output.extend(decoder.decompress(chunk, MAX_BODY_BYTES + 1 - len(output)))
                if decoder.unconsumed_tail:
                    raise WebResearchError("网页内容过大，暂时无法读取。" + _FALLBACK)
            if len(output) > MAX_BODY_BYTES:
                raise WebResearchError("网页内容过大，暂时无法读取。" + _FALLBACK)
        if decoder is not None:
            # No unbounded flush(): max_length above bounds allocation even for
            # highly compressed responses. Reject truncated/concatenated data.
            if not decoder.eof or decoder.unused_data:
                raise WebResearchError("网页内容不完整，暂时无法读取。" + _FALLBACK)
    except zlib.error:
        raise WebResearchError("网页内容无法解压。" + _FALLBACK) from None
    return bytes(output)


_BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "main", "tr", "ul", "ol"}
_SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "form", "button", "svg", "iframe", "noscript", "template", "head"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def _clean(value: str, limit: int) -> str:
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", unescape(value))
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)[:limit]


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.parts: list[str] = []
        self.main: list[str] = []
        self.title: list[str] = []
        self.json_ld: list[str] = []
        self._json_parts: list[str] | None = None
        self._title_depth = 0
        self._main_depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        parent_hidden = bool(self.stack and self.stack[-1][1])
        hidden = parent_hidden or tag in _SKIP_TAGS or "hidden" in attributes or attributes.get("aria-hidden") == "true"
        if tag == "script" and (attributes.get("type") or "").split(";")[0].strip().lower() == "application/ld+json":
            self._json_parts = []
        if tag not in _VOID_TAGS:
            if len(self.stack) >= 128:
                raise WebResearchError("网页结构过于复杂，暂时无法读取。" + _FALLBACK)
            self.stack.append((tag, hidden))
            self._title_depth += tag == "title"
            self._main_depth += tag in {"main", "article"}
        if tag in _BLOCK_TAGS and not hidden:
            self._append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "script" and self._json_parts is not None:
            self.json_ld.append("".join(self._json_parts))
            self._json_parts = None
        for position in range(len(self.stack) - 1, -1, -1):
            if self.stack[position][0] == tag:
                for removed, _ in self.stack[position:]:
                    self._title_depth -= removed == "title"
                    self._main_depth -= removed in {"main", "article"}
                del self.stack[position:]
                break
        if tag in _BLOCK_TAGS and not (self.stack and self.stack[-1][1]):
            self._append("\n")

    def handle_data(self, data):
        if self._json_parts is not None:
            self._json_parts.append(data)
        if self._title_depth:
            self.title.append(data)
        if not (self.stack and self.stack[-1][1]):
            self._append(data)

    def _append(self, text):
        self.parts.append(text)
        if self._main_depth:
            self.main.append(text)


def _html_text(value: str, limit: int = READ_CONTENT_LIMIT) -> str:
    parser = _PageText()
    parser.feed(value)
    parser.close()
    return _clean("".join(parser.parts), limit)


def _jobs(value, depth=0):
    if depth > 16:
        return
    if isinstance(value, dict):
        types = value.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if any(isinstance(item, str) and item.rsplit("/", 1)[-1] == "JobPosting" for item in types):
            yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _jobs(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _jobs(child, depth + 1)


def _published(value) -> str | None:
    if not isinstance(value, str) or len(value) > 50:
        return None
    try:
        # Keep a supplied date's precision and timezone; do not invent either.
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


class _CharsetSniffer(HTMLParser):
    """Inspect a bounded header prefix; script/comment text is not metadata."""

    def __init__(self):
        super().__init__()
        self.charset: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag != "meta" or self.charset:
            return
        attributes = dict(attrs)
        label = (attributes.get("charset") or "").strip()
        if not label and (attributes.get("http-equiv") or "").strip().lower() == "content-type":
            match = re.search(r"charset\s*=\s*[\"']?([\w-]+)", attributes.get("content") or "", re.I)
            label = match.group(1) if match else ""
        if label and re.fullmatch(r"[\w-]{1,40}", label):
            self.charset = label


def _require_readable_encoding(text: str) -> str:
    replacements = text.count("\ufffd")
    if replacements >= 3 and replacements / max(len(text), 1) > 0.01:
        raise WebResearchError("网页文字编码无法可靠识别。" + _FALLBACK)
    return text


def _decode_page(body: bytes, content_type: str) -> str:
    charset = re.search(r"charset\s*=\s*[\"']?([\w-]+)", content_type, re.I)
    if body.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    elif body.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif charset:
        encoding = charset.group(1)
    else:
        encoding = "utf-8"
        if not content_type.lower().startswith("text/plain"):
            sniffer = _CharsetSniffer()
            # Charset labels are ASCII. Do not parse or guess over a full body.
            sniffer.feed(body[:8192].decode("ascii", errors="replace"))
            encoding = sniffer.charset or encoding
    # Many older Chinese pages label GBK/GB18030 text as GB2312.
    if encoding.lower().replace("-", "").replace("_", "") in {"gb2312", "gbk", "cp936"}:
        encoding = "gb18030"
    try:
        text = body.decode(encoding, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    return _require_readable_encoding(text)


def _extract(
    body: bytes, content_type: str, *, content_limit: int = READ_CONTENT_LIMIT,
    prefer_job_posting: bool = True,
) -> tuple[str, str, str | None]:
    text = _decode_page(body, content_type)
    if content_type.lower().startswith("text/plain"):
        return "招聘页面", _require_readable_encoding(_clean(text, content_limit)), None
    page = _PageText()
    page.feed(text)
    page.close()
    title = _clean("".join(page.title), 200) or "招聘页面"
    for raw in page.json_ld if prefer_job_posting else []:
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        for job in _jobs(data):
            fields = []
            for key in ("title", "description", "responsibilities", "qualifications", "skills", "educationRequirements", "experienceRequirements", "jobBenefits"):
                value = job.get(key)
                if isinstance(value, str):
                    fields.append(_html_text(value, content_limit))
            company = job.get("hiringOrganization")
            if isinstance(company, dict) and isinstance(company.get("name"), str):
                fields.insert(0, "公司：" + _html_text(company["name"], 200))
            content = _clean("\n".join(fields), content_limit)
            if len(content) >= 80:
                _require_readable_encoding(content)
                job_title = job.get("title")
                return (_html_text(job_title, 200) if isinstance(job_title, str) and job_title else title,
                        content, _published(job.get("datePosted")))
    main = _clean("".join(page.main), content_limit)
    content = main if len(main) >= (80 if prefer_job_posting else 30) else _clean("".join(page.parts), content_limit)
    return title, _require_readable_encoding(content), None


async def _read_web_url(url: str, *, public_reference: bool = False) -> dict:
    """Shared pinned public-page fetch; never executes scripts or authenticates."""
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
            current, host, port = _normalize_url(url)
            for hop in range(MAX_REDIRECTS + 1):
                address = await _resolve_public(host, port)
                async with _public_response(current, address) as response:
                    if response.status_code in _REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location or hop == MAX_REDIRECTS:
                            raise WebResearchError("网页跳转过多，暂时无法读取。" + _FALLBACK, 502)
                        current, host, port = _normalize_url(urljoin(current, location))
                        continue
                    if response.status_code in {401, 403, 429}:
                        raise WebResearchError("该网站要求登录、验证或限制读取。" + _FALLBACK, 422)
                    if response.status_code < 200 or response.status_code >= 300:
                        raise WebResearchError("招聘页面暂时无法访问。" + _FALLBACK, 502)
                    content_type = response.headers.get("content-type", "").lower()
                    if content_type.split(";", 1)[0].strip() not in {"text/html", "application/xhtml+xml", "text/plain"}:
                        raise WebResearchError("链接没有返回可读取的网页正文。" + _FALLBACK)
                    body = await _bounded_body(response)
                # Preserve one extra cleaned character to distinguish an exact
                # fit from truncation, including a single JSON-LD description.
                # This does not claim complete access to a dynamic/login page.
                title, content, published = _extract(
                    body, content_type, content_limit=READ_CONTENT_LIMIT + 1,
                    prefer_job_posting=not public_reference,
                )
                content_truncated = len(content) > READ_CONTENT_LIMIT
                content = content[:READ_CONTENT_LIMIT]
                if (len(content) < (30 if public_reference else 80) or (len(content) < 800 and re.search(
                        r"请(?:先)?登录(?:后)?(?:查看|访问)|登录后可(?:见|查看)|enable javascript|verify you are human|access denied",
                        content, re.I))):
                    raise WebResearchError("未读到完整岗位正文，页面可能需要登录或动态加载。" + _FALLBACK)
                result = {"title": title, "url": current, "fetched_at": _now(), "content": content,
                          "kind": "public_page" if public_reference else "job_page", "content_truncated": content_truncated}
                if public_reference:
                    result.update(read_scope="public_page_text", request_count=hop + 1)
                    if title == "招聘页面":
                        result["title"] = "公开网页"
                if published:
                    result["published_at"] = published
                return result
    except WebResearchError:
        raise
    except (TimeoutError, httpx.TimeoutException):
        raise WebResearchError("读取网页超时。" + _FALLBACK, 504) from None
    except (httpx.HTTPError, OSError, ValueError, UnicodeError):
        raise WebResearchError("暂时无法读取这个网页。" + _FALLBACK, 502) from None
    raise WebResearchError("暂时无法读取这个网页。" + _FALLBACK, 502)


async def read_job_url(url: str) -> dict:
    """Read a job page as JD material. Public references use a separate entry."""
    return await _read_web_url(url)


_GITHUB_USER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_GITHUB_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_GITHUB_RESERVED = {"about", "apps", "collections", "contact", "enterprise", "events", "explore",
                    "features", "issues", "join", "login", "logout", "marketplace", "new", "notifications",
                    "organizations", "orgs", "pricing", "pulls", "search", "security", "settings", "site",
                    "sponsors", "topics", "trending"}
_GITHUB_REPO_LIMIT = 5


def _github_target(url: str) -> tuple[str, str | None] | None:
    parsed = urlsplit(url)
    if parsed.hostname not in {"github.com", "www.github.com"}:
        return None
    # A file/issue/tree URL or a different tab must retain its actual page scope.
    if parsed.query and parsed.query != "tab=repositories":
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) not in {1, 2} or not _GITHUB_USER.fullmatch(parts[0]):
        return None
    if parts[0].lower() in _GITHUB_RESERVED:
        return None
    repo = parts[1] if len(parts) == 2 else None
    if repo is not None and (not _GITHUB_REPO.fullmatch(repo) or repo in {".", ".."} or parsed.query):
        return None
    return parts[0], repo


async def _github_json(path: str):
    # Only internally constructed endpoint paths enter here. The caller cannot
    # supply an API host, query, auth token, cookies, or a redirect destination.
    url = "https://api.github.com" + path
    address = await _resolve_public("api.github.com", 443)
    async with _public_response(url, address, accept="application/vnd.github+json") as response:
        if response.status_code == 404:
            raise WebResearchError("未找到这个公开 GitHub 账号或仓库；它可能不存在、已更名或不是公开内容。", 404)
        if response.status_code in {403, 429}:
            raise WebResearchError("GitHub 暂时限制了公开读取，请稍后再试，或粘贴需要核对的内容。", 503)
        if response.status_code != 200:
            raise WebResearchError("GitHub 公开信息暂时无法读取，请检查链接或稍后再试。", 502)
        data = await _bounded_body(response)
    try:
        return json.loads(data)
    except (ValueError, RecursionError):
        raise WebResearchError("GitHub 没有返回可核对的公开信息，请稍后再试。", 502) from None


def _github_label(value, limit=500) -> str:
    return _html_text(value, limit) if isinstance(value, str) else ""


def _github_count(value) -> str:
    return str(value) if type(value) is int and value >= 0 else "未提供"


def _public_repository(data, owner: str, name: str | None = None) -> bool:
    if not isinstance(data, dict) or data.get("private") is not False:
        return False
    login = data.get("owner", {}).get("login") if isinstance(data.get("owner"), dict) else None
    repo_name = data.get("name")
    return (isinstance(login, str) and login.lower() == owner.lower()
            and isinstance(repo_name, str) and _GITHUB_REPO.fullmatch(repo_name) is not None
            and repo_name not in {".", ".."}
            and (name is None or repo_name.lower() == name.lower())
            and isinstance(data.get("full_name"), str)
            and data["full_name"].lower() == f"{owner}/{repo_name}".lower())


def _repository_lines(data: dict) -> list[str]:
    full_name = data["full_name"]
    lines = [f"仓库：{full_name}", f"仓库链接：https://github.com/{full_name}",
             f"Stars：{_github_count(data.get('stargazers_count'))}；Forks：{_github_count(data.get('forks_count'))}",
             "简介：" + (_github_label(data.get("description")) or "未提供"),
             "主要语言：" + (_github_label(data.get("language"), 80) or "未提供"),
             "是否 Fork：" + ("是" if data.get("fork") is True else "否" if data.get("fork") is False else "未提供")]
    updated = _published(data.get("updated_at"))
    if updated:
        lines.append("仓库元数据更新时间（不是 Stars 统计时间）：" + updated)
    return lines


async def _read_github_metadata(url: str, owner: str, repo: str | None) -> dict:
    scope = "github_repository_metadata" if repo else "github_profile_and_public_repositories"
    lines = ["来源：GitHub 官方公开 REST API；仅公开元数据，不是代码、README 或提交历史的完整审查。",
             "归属边界：账号名、仓库名和公开所有者仅描述这个页面，不证明当前使用者拥有该账号、参与过项目或完成过其中工作。"]
    if repo:
        data = await _github_json(f"/repos/{owner}/{repo}")
        if not _public_repository(data, owner, repo):
            raise WebResearchError("GitHub 返回的公开仓库与链接不一致，暂时不能据此核对。", 502)
        title = "GitHub 公开仓库：" + data["full_name"]
        lines.extend(_repository_lines(data))
        request_count = 1
    else:
        data = await _github_json(f"/users/{owner}")
        if (not isinstance(data, dict) or not isinstance(data.get("login"), str)
                or data["login"].lower() != owner.lower()):
            raise WebResearchError("GitHub 返回的公开账号与链接不一致，暂时不能据此核对。", 502)
        login = data["login"]
        repos = await _github_json(f"/users/{owner}/repos?type=owner&sort=updated&direction=desc&per_page={_GITHUB_REPO_LIMIT}&page=1")
        if not isinstance(repos, list):
            raise WebResearchError("GitHub 没有返回可核对的公开仓库列表，请稍后再试。", 502)
        public_repos = [row for row in repos[:_GITHUB_REPO_LIMIT] if _public_repository(row, owner)]
        title = "GitHub 公开主页：" + login
        lines.extend([f"账号：{login}", "公开名称：" + (_github_label(data.get("name"), 100) or "未提供"),
                      "公开简介：" + (_github_label(data.get("bio")) or "未提供"),
                      "公开仓库数（API public_repos）：" + _github_count(data.get("public_repos")),
                      f"读取范围：最多 {_GITHUB_REPO_LIMIT} 个按更新时间排序的公开自有仓库（含 Fork），本次展示 {len(public_repos)} 个；未读取后续分页，不能当成完整仓库清单。"])
        for row in public_repos:
            lines.extend(["", *_repository_lines(row)])
        request_count = 2
    fetched_at = _now()
    lines.insert(1, "本次获取时间（Stars/Forks 为此时 GitHub API 返回值，可能随后变化）：" + fetched_at)
    content = _clean("\n".join(lines), READ_CONTENT_LIMIT + 1)
    return {"title": title, "url": url, "content": content[:READ_CONTENT_LIMIT], "fetched_at": fetched_at,
            "kind": "public_page", "content_truncated": len(content) > READ_CONTENT_LIMIT,
            "read_scope": scope, "request_count": request_count}


async def read_public_url(url: str) -> dict:
    """Read a public reference, never treating it as JD or candidate evidence."""
    if isinstance(url, str) and re.match(r"^(?:www\.)?github\.com(?:/|$)", url, re.I):
        url = "https://" + url
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
            normalized, _, _ = _normalize_url(url)
            github = _github_target(normalized)
            if github:
                return await _read_github_metadata(normalized, *github)
            return await _read_web_url(normalized, public_reference=True)
    except WebResearchError as exc:
        message = exc.message.replace(_FALLBACK, _PUBLIC_FALLBACK).replace("招聘页面", "公开页面").replace("岗位正文", "页面正文")
        raise WebResearchError(message, exc.status_code) from None
    except (TimeoutError, httpx.TimeoutException):
        raise WebResearchError("读取公开页面超时。" + _PUBLIC_FALLBACK, 504) from None
    except (httpx.HTTPError, OSError, ValueError, UnicodeError):
        raise WebResearchError("暂时无法读取这个公开页面。" + _PUBLIC_FALLBACK, 502) from None


def _search_query(company: str, role: str) -> str:
    values = []
    for value in (company, role):
        if not isinstance(value, str) or len(value) > 80:
            raise WebResearchError("搜索仅接受简短的公司名和岗位名，各不超过 80 字。")
        if (re.search(r"[\r\n\x00-\x1f\x7f@\\]|[a-z][a-z0-9+.-]*://|www\.|(?:mailto|data|file|https?):", value, re.I)
                or len(re.sub(r"\D", "", value)) >= 7):
            raise WebResearchError("搜索只需公司名和岗位名，请移除联系方式、链接和个人经历。")
        values.append(value.strip())
    if not any(values):
        raise WebResearchError("请填写公司名或岗位名再搜索。")
    return " ".join(value for value in values if value) + " 岗位职责"


async def _search_response(query: str, key: str) -> dict:
    # Fixed provider endpoint; no user-supplied URL or redirect can receive key.
    request = httpx.Request(
        "POST", "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {key}", "Accept-Encoding": "gzip, deflate"},
        json={"query": query, "search_depth": "basic", "max_results": 4, "topic": "general",
              "include_answer": False, "include_raw_content": False, "include_images": False,
              "auto_parameters": False},
        extensions={"timeout": {"connect": 5.0, "read": 10.0, "write": 5.0, "pool": 5.0}},
    )
    async with httpx.AsyncHTTPTransport(trust_env=False, retries=0) as transport:
        response = await transport.handle_async_request(request)
        try:
            if response.status_code in {401, 403}:
                raise WebResearchError("联网搜索配置暂时不可用，请稍后再试。", 503)
            if response.status_code in {429, 432, 433}:
                raise WebResearchError("联网搜索额度暂时不足，请稍后再试；仍可直接读取招聘链接。", 503)
            if response.status_code != 200:
                raise WebResearchError("联网搜索服务暂时不可用，请稍后再试。", 502)
            body = await _bounded_body(response)
        finally:
            await response.aclose()
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise WebResearchError("联网搜索没有返回有效结果，请稍后再试。", 502) from None
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise WebResearchError("联网搜索没有返回有效结果，请稍后再试。", 502)
    return data


async def search_job_context(company: str, role: str) -> list[dict]:
    """Send only deliberately supplied company/role labels, never chat history."""
    query = _search_query(company, role)
    key = get_settings().TAVILY_API_KEY.strip()
    if not key:
        raise WebResearchError("联网搜索尚未配置；可以先读取招聘链接，或粘贴岗位正文。", 503)
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
            data = await _search_response(query, key)
            fetched_at = _now()
            results, seen = [], set()
            # Bound processing even if a provider unexpectedly returns more rows.
            for item in data["results"][:12]:
                if not isinstance(item, dict):
                    continue
                try:
                    url, host, port = _normalize_url(item.get("url"))
                    if url in seen:
                        continue
                    await _resolve_public(host, port)
                except WebResearchError:
                    continue
                if not isinstance(item.get("content"), str) or not isinstance(item.get("title"), str):
                    continue
                content = _html_text(item["content"], SEARCH_CONTENT_LIMIT)
                if not content:
                    continue
                result = {"title": _html_text(item["title"], 200) or "搜索结果", "url": url,
                          "fetched_at": fetched_at, "content": content, "kind": "search_result"}
                published = _published(item.get("published_date"))
                if published:
                    result["published_at"] = published
                results.append(result)
                seen.add(url)
                if len(results) == 4:
                    break
            return results
    except WebResearchError:
        raise
    except (TimeoutError, httpx.TimeoutException):
        raise WebResearchError("联网搜索超时，请稍后再试。", 504) from None
    except (httpx.HTTPError, OSError, ValueError, UnicodeError):
        raise WebResearchError("联网搜索服务暂时不可用，请稍后再试。", 502) from None
