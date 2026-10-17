"""公开情报数据源；只接收查询词和公开 URL，不接收简历或会话。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.services import web_research as web

TIMEOUT = 15.0


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    content: str
    site_name: str = ""
    date: str = ""
    provider: str = ""
    summary: str = ""
    snippet: str = ""
    site_icon: str = ""
    authority: object = None
    rerank_score: object = None

    @property
    def evidence(self):
        return "\n".join(dict.fromkeys(value.strip() for value in
                        (self.content, self.summary, self.snippet) if value.strip()))


@dataclass(frozen=True)
class FetchedPage:
    content: str
    title: str = ""
    url: str = ""
    provider: str = ""
    site_name: str = ""


class Provider(Protocol):
    # 百炼等后续数据源只需实现此接口和 available，不改变业务层。
    name: str
    available: bool

    async def search(
        self,
        query: str,
        *,
        count: int,
        after: str | None = None,
        site: str | None = None,
    ) -> list[SearchHit]: ...

    async def fetch(self, url: str) -> FetchedPage: ...


async def public_url(url: str) -> str:
    normalized, host, port = web._normalize_url(url)
    await web._resolve_public(host, port)
    return normalized


def query_text(query: str, after=None, site=None) -> str:
    modifiers = "".join(
        f" {key}:{value}" for key, value in (("after", after), ("site", site)) if value
    )
    return query[: max(0, 128 - len(modifiers))] + modifiers


async def post_json(endpoint: str, key: str, body: dict) -> dict:
    # 固定端点、禁用代理/重定向；沿用有界响应读取，避免正文或凭证进入 HTTP 日志。
    request = httpx.Request(
        "POST",
        endpoint,
        headers={"Authorization": f"Bearer {key}", "Accept-Encoding": "gzip, deflate"},
        json=body,
        extensions={
            "timeout": dict.fromkeys(("connect", "read", "write", "pool"), TIMEOUT)
        },
    )
    async with asyncio.timeout(TIMEOUT):
        async with httpx.AsyncHTTPTransport(trust_env=False, retries=0) as transport:
            response = await transport.handle_async_request(request)
            try:
                if response.status_code != 200:
                    raise web.WebResearchError("公开情报服务暂时不可用。", 502)
                raw = await web._bounded_body(response)
            finally:
                await response.aclose()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("invalid provider response")
    return data


def parse_hits(data: dict, provider: str, count: int) -> list[SearchHit]:
    result = []
    rows = data.get("results")
    if not isinstance(rows, list):
        return result
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        try:
            url, _, _ = web._normalize_url(row.get("url"))
        except web.WebResearchError:
            continue
        body = {key: web._html_text(row[key], web.READ_CONTENT_LIMIT)
                if isinstance(row.get(key), str) else ""
                for key in ("content", "summary", "snippet")}
        if not any(body.values()) or not isinstance(row.get("title"), str):
            continue
        result.append(
            SearchHit(
                web._html_text(row["title"], 240),
                url,
                body["content"] or body["summary"] or body["snippet"],
                str(row.get("site_name") or "")[:200],
                str(row.get("date") or row.get("published_date") or "")[:50],
                provider,
                summary=body["summary"], snippet=body["snippet"],
                site_icon=str(row.get("site_icon") or "")[:500],
                authority=row.get("authority"), rerank_score=row.get("rerank_score"),
            )
        )
        if len(result) >= count:
            break
    return result


class DeepSeekProvider:
    name = "deepseek"

    def __init__(self, settings=None):
        settings = settings or get_settings()
        key = settings.DEEPSEEK_TOOLS_API_KEY.strip()
        base = urlsplit(settings.LLM_BASE_URL or "")
        if (
            not key
            and settings.LLM_PROVIDER.lower() == "deepseek"
            and base.scheme == "https"
            and base.netloc == "api.deepseek.com"
            and base.path.rstrip("/") in {"", "/v1"}
            and not base.query
            and not base.fragment
        ):
            key = settings.LLM_API_KEY.strip()
        self._key = key
        self.available = bool(key)

    async def search(self, query, *, count, after=None, site=None):
        if not self.available:
            return []
        data = await post_json(
            "https://api.deepseek.com/v1/tools/search",
            self._key,
            {
                "query": query_text(query, after, site),
                "count": min(50, max(1, count)),
                "need_content": True,
            },
        )
        return parse_hits(data, self.name, min(50, max(1, count)))

    async def fetch(self, url):
        url = await public_url(url)
        if not self.available:
            return FetchedPage("")
        data = await post_json(
            "https://api.deepseek.com/v1/tools/fetch", self._key, {"url": url}
        )
        content = data.get("content")
        return FetchedPage(
            content[: web.READ_CONTENT_LIMIT] if isinstance(content, str) else "",
            str(data.get("title") or "")[:240],
            url,
            self.name,
            str(data.get("site_name") or "")[:200],
        )


class TavilyProvider:
    name = "tavily"

    def __init__(self, settings=None):
        self._key = (settings or get_settings()).TAVILY_API_KEY.strip()
        self.available = bool(self._key)

    async def search(self, query, *, count, after=None, site=None):
        if not self.available:
            return []
        # 复用原 Tavily 请求实现，兼容旧入口及其有界响应检查。
        async with asyncio.timeout(TIMEOUT):
            data = await web._search_response(
                query_text(query, after, site), self._key, count=count, timeout=TIMEOUT
            )
        return parse_hits(data, self.name, count)

    async def fetch(self, url):
        url = await public_url(url)
        if not self.available:
            return FetchedPage("")
        data = await post_json(
            "https://api.tavily.com/extract",
            self._key,
            {"urls": [url], "extract_depth": "basic", "format": "markdown"},
        )
        for row in data.get("results", [])[:1]:
            if (
                isinstance(row, dict)
                and row.get("url") == url
                and isinstance(row.get("raw_content"), str)
            ):
                return FetchedPage(
                    row["raw_content"][: web.READ_CONTENT_LIMIT],
                    str(row.get("title") or "")[:240],
                    url,
                    self.name,
                )
        return FetchedPage("")


def configured_providers(settings=None) -> list[Provider]:
    settings = settings or get_settings()
    registry = {"deepseek": DeepSeekProvider, "tavily": TavilyProvider}
    return [
        registry[name](settings)
        for name in dict.fromkeys(
            item.strip().lower() for item in settings.JOB_INTEL_PROVIDERS.split(",")
        )
        if name in registry
    ]
