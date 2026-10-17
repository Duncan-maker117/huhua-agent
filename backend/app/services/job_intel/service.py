"""三个有界公开情报能力；缓存命中免费，异常只产生可读提示。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from weakref import WeakValueDictionary

from app.config import get_settings
from app.services import web_research as web
from .providers import configured_providers, public_url
from .storage import Store, today
from .company import matches, official_score, supported_paraphrase, evidence_field
from .extraction import (
    CompanyExtraction,
    JobExtraction,
    SampleExtraction,
    extract,
    is_job_page,
    job_card,
    simple_job,
    compact_job_text,
    company_key,
    normalized_job_title,
    usable_title,
)

logger = logging.getLogger(__name__)
MANUAL = (
    "这个招聘页面需要登录或验证。请上传岗位截图，或复制岗位正文发来，我会继续解读。"
)
UNAVAILABLE = "这次未取得可用的公开资料。可以直接粘贴岗位正文或上传截图，继续整理简历。"
LOGIN = re.compile(
    r"登录后(?:才能|可|方可)?(?:查看|访问|见)|请(?:先)?登录|扫码登录|安全验证|人机验证|verify you are human|access denied",
    re.I,
)
BLOCKED_SITES = ("zhipin.com", "liepin.com", "lagou.com", "lagou.jobs")
_slots = None
_loop = None
_locks = WeakValueDictionary()
_rate_locks = {}
_last_request = {}
CALL_TIMEOUT = 15
SAMPLE_TIMEOUT = 60


def direction_key(direction):
    return " ".join(direction.casefold().split())


def now():
    return datetime.now(timezone.utc).isoformat()


def session_id():
    from app.services.chat_turns import current_turn

    turn = current_turn.get()
    if turn:
        return turn.session_id
    try:
        from langgraph.config import get_config

        return get_config().get("configurable", {}).get("thread_id") or "standalone"
    except (RuntimeError, KeyError):
        return "standalone"


def canonical_url(url):
    url, _, _ = web._normalize_url(url)
    parts = urlsplit(url)
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")
            and k.lower() not in {"spm", "from", "ref"}
        )
    )
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", query, "")
    )


def slots():
    global _slots, _loop, _rate_locks, _last_request
    loop = asyncio.get_running_loop()
    if loop is not _loop:
        _loop, _slots = loop, asyncio.Semaphore(3)
        _rate_locks, _last_request = {}, {}
    return _slots


class JobIntel:
    def __init__(
        self, *, providers=None, store=None, settings=None, llm=None, session=None
    ):
        self.settings = settings or get_settings()
        self.providers = (
            configured_providers(self.settings) if providers is None else providers
        )
        self.store = store or Store()
        self.llm = llm
        self.session = session or session_id()

    @property
    def available(self):
        return any(p.available for p in self.providers)

    async def _request(self, provider, method, *args, **kwargs):
        if not self.store.reserve(
            "global", "requests", self.settings.JOB_INTEL_DAILY_LIMIT, daily=True
        ):
            return None
        start, billed, outcome = time.monotonic(), False, "failed"
        try:
            async with slots():
                # 同一进程内每个接口低于 5 QPS；失败不重试，留出下一个 provider 的时间。
                key = (provider.name, method)
                lock = _rate_locks.setdefault(key, asyncio.Lock())
                async with lock:
                    await asyncio.sleep(
                        max(0, 0.21 - (time.monotonic() - _last_request.get(key, 0)))
                    )
                    _last_request[key] = time.monotonic()
                async with asyncio.timeout(CALL_TIMEOUT):
                    result = await getattr(provider, method)(*args, **kwargs)
                present = bool(result if isinstance(result, list) else result.content)
                billed, outcome = present, "success" if present else "empty"
                return result if present else None
        except Exception:
            return None
        finally:
            logger.info(
                "job_intel_call provider=%s operation=%s billed=%s outcome=%s elapsed_ms=%d",
                provider.name,
                method,
                billed,
                outcome,
                int((time.monotonic() - start) * 1000),
            )

    async def _providers(self, method, *args, **kwargs):
        for provider in self.providers:
            if not provider.available:
                continue
            result = await self._request(provider, method, *args, **kwargs)
            if result:
                return result
        return None

    async def _extract(self, schema, payload):
        # 公开页、provider 和情报结构化抽取共用同一并发预算。
        async with slots(), asyncio.timeout(CALL_TIMEOUT):
            return await extract(self.llm, schema, payload)

    async def _run(self, kind, key, days, limit, work, *, timeout_seconds=60):
        lock_key = (id(asyncio.get_running_loop()), kind, key)
        lock = _locks.setdefault(lock_key, asyncio.Lock())
        try:
            async with asyncio.timeout(timeout_seconds):
                async with lock:
                    cached = self.store.get(kind, key, days)
                    if cached:
                        return {**cached, "cached": True}
                    if kind != "read_url" and not self.available:
                        return {"status": "unavailable", "message": UNAVAILABLE}
                    if not self.store.reserve(self.session, kind, limit):
                        return {
                            "status": "limited",
                            "message": "本会话这类岗位情报查询已达上限；可以直接粘贴正文或截图继续。",
                        }
                    if not self.store.reserve(
                        "global",
                        "operations",
                        self.settings.JOB_INTEL_DAILY_LIMIT,
                        daily=True,
                    ):
                        return {
                            "status": "limited",
                            "message": "今天的岗位情报查询已达上限，可以复制正文或上传截图继续。",
                        }
                    result = await work()
                    if result.get("status") in {"ok", "public_page", "needs_manual"}:
                        self.store.put(kind, key, result)
                    return result
        except Exception as error:
            logger.info(
                "job_intel_unavailable kind=%s error_type=%s",
                kind,
                type(error).__name__,
            )
            return {"status": "unavailable", "message": UNAVAILABLE}

    async def read_job_url(self, url):
        try:
            # 缓存和第三方代读同样先过公网 DNS 检查；绝不因自抓拒绝内网而绕过。
            async with asyncio.timeout(15):
                url = await public_url(url)
        except Exception:
            return {
                "status": "rejected",
                "message": "仅支持可验证的公网 HTTP/HTTPS 网页。请复制岗位正文或上传截图。",
            }

        async def work():
            host = urlsplit(url).hostname
            if any(host == site or host.endswith("." + site) for site in BLOCKED_SITES):
                return {"status": "needs_manual", "message": MANUAL}
            if host in {"github.com", "www.github.com", "gist.github.com"}:
                async with slots(), asyncio.timeout(CALL_TIMEOUT):
                    page = await web.read_public_url(url)
                return {"status": "public_page", "page": page}
            page = None
            login_wall = False
            start = time.monotonic()
            try:
                async with slots(), asyncio.timeout(CALL_TIMEOUT):
                    page = await web.read_job_url(url)
                login_wall = bool(LOGIN.search(page.get("content", "")))
                if len(page.get("content", "")) < 80 or login_wall:
                    page = None
                if page:
                    page = {**page, "provider": "self_fetch"}
            except web.WebResearchError as error:
                login_wall = "登录" in error.message
                # 跳转到内网、非法 URL、体积限制等安全拒绝不能触发代读。
                if any(
                    word in error.message
                    for word in (
                        "不是可读取的公开",
                        "仅支持",
                        "请输入完整",
                        "内容过大",
                        "无法解压",
                        "压缩格式",
                        "跳转过多",
                        "内容不完整",
                    )
                ):
                    return {
                        "status": "rejected",
                        "message": "该链接未通过安全读取检查，请复制正文或上传截图。",
                    }
            except (TimeoutError, OSError):
                pass
            finally:
                logger.info(
                    "job_intel_call provider=self_fetch operation=fetch billed=false elapsed_ms=%d",
                    int((time.monotonic() - start) * 1000),
                )
            if page is None:
                fetched = await self._providers("fetch", url)
                if not fetched and login_wall:
                    return {"status": "needs_manual", "message": MANUAL}
                if not fetched:
                    return {"status": "unavailable", "message": UNAVAILABLE}
                if LOGIN.search(fetched.content):
                    return {"status": "needs_manual", "message": MANUAL}
                if len(fetched.content.strip()) < 80:
                    return {"status": "unavailable", "message": UNAVAILABLE}
                page = {
                    "title": fetched.title,
                    "url": url,
                    "content": fetched.content,
                    "fetched_at": now(),
                    "kind": "job_page",
                    "provider": fetched.provider + "_fetch",
                    "site_name": fetched.site_name,
                    "content_truncated": len(fetched.content) >= web.READ_CONTENT_LIMIT,
                }
            if not is_job_page(page["title"], page["content"], page["url"]):
                # 自抓内容已经在同一安全边界取得；复用正文进入旧公开参考路径。
                return {
                    "status": "public_page",
                    "page": {
                        **page,
                        "kind": "public_page",
                        "read_scope": "public_page_text",
                    },
                }
            extracted = simple_job(page)
            if self.llm is not None:
                try:
                    extracted = await self._extract(JobExtraction, page)
                except Exception:
                    pass
            if not extracted.is_job:
                return {
                    "status": "public_page",
                    "page": {**page, "kind": "public_page"},
                }
            card = job_card(extracted, page)
            return {"status": "ok", "source": "job_url", "card": card, "page": page}

        result = await self._run(
            "read_url",
            url,
            1,
            self.settings.JOB_INTEL_READ_LIMIT,
            work,
            timeout_seconds=60,
        )
        if result.get("cached") and result.get("status") == "ok" and result.get("page"):
            # Apply deterministic corrections to yesterday's cards without another fetch/LLM bill.
            value = JobExtraction.model_validate(result["card"])
            result = {**result, "card": job_card(value, result["page"])}
        return result

    async def sample_jobs(self, direction, *, on_progress=None):
        try:
            web._search_query("", direction)
        except web.WebResearchError:
            return {"status": "rejected", "message": "请提供简短的岗位方向。"}
        key = direction_key(direction)

        async def work():
            after = (today() - timedelta(days=183)).isoformat()
            templates = (
                "招聘 岗位职责",
                "实习 招聘 任职要求",
                "校招 招聘 岗位基本要求",
            )
            batches = await asyncio.gather(
                *(
                    self._providers(
                        "search",
                        f"{direction[:60]} {template} lang:zh",
                        # 按请求计费、与条数无关；多取些结果，去重和过滤后才够 5 条。
                        count=10,
                        after=after,
                    )
                    for template in templates
                )
            )
            hits = {}
            for batch in batches:
                for hit in batch or []:
                    try:
                        url = canonical_url(hit.url)
                        async with asyncio.timeout(CALL_TIMEOUT):
                            await public_url(url)
                    except web.WebResearchError:
                        continue
                    if url in hits or not is_job_page(hit.title, hit.evidence, url):
                        continue
                    # 有明确旧日期时丢弃；未标日期的搜索结果不伪造发布日期。
                    published = web._published(hit.date)
                    if published and published[:10] < after:
                        continue
                    hits[url] = {**asdict(hit), "content": hit.evidence, "url": url}
            if len(hits) < 3:
                return {
                    "status": "insufficient",
                    "message": f"只找到 {len(hits)} 条可核对岗位，未生成市场画像。可以补充具体 JD。",
                }
            # 抽取最多 10 条候选；3–4 条仍生成带小样本提示的画像。
            hits = dict(list(hits.items())[:10])
            if on_progress:
                on_progress(len(hits))
            # One compressed call: no duplicated summaries, icons, scores or full pages.
            inputs = []
            for hit in hits.values():
                fields = simple_job(hit)
                inputs.append({"url": hit["url"], "job_title": fields.job_title,
                               "company": fields.company,
                               "content": compact_job_text(hit["content"], limit=1000)})
            # 单次提炼 10 条会超过 15 秒单调用上限；按 5 条一批并发提炼，各自独立计时。
            batches = await asyncio.gather(*(
                self._extract(SampleExtraction, {"direction": direction, "sources": inputs[i:i + 5]})
                for i in range(0, len(inputs), 5)
            ), return_exceptions=True)
            extracted_jobs = [job for batch in batches if not isinstance(batch, BaseException) for job in batch.jobs]
            if not extracted_jobs and batches and isinstance(batches[0], BaseException):
                raise batches[0]
            jobs, seen, seen_urls = [], set(), set()
            for job in extracted_jobs:
                hit = hits.get(job.url)
                if not hit or not job.is_job or job.url in seen_urls:
                    continue
                card = job_card(job, {**hit, "fetched_at": now()})
                pair = (company_key(card), normalized_job_title(card["job_title"]))
                if not usable_title(card["job_title"]) or not pair[1] or pair in seen:
                    continue
                seen.add(pair)
                seen_urls.add(job.url)
                jobs.append(card)
                if len(jobs) == 10:
                    break
            if len(jobs) < 3:
                return {
                    "status": "insufficient",
                    "message": f"核对并去重后只有 {len(jobs)} 条真实岗位，暂不生成画像。",
                }
            groups = {}
            company_keys = {job["url"]: company_key(job) for job in jobs}
            company_count = len(set(company_keys.values()))
            for field in ("responsibilities", "skills", "bonuses", "requirements"):
                counts = defaultdict(dict)
                companies = defaultdict(set)
                labels = {}
                for job in jobs:
                    for item in job[field]:
                        label = re.sub(r"\s+", "", item["text"]).casefold()
                        labels.setdefault(label, item["text"])
                        counts[label][job["url"]] = item["quote"]
                        companies[label].add(company_keys[job["url"]])
                groups[field] = [
                    {
                        "text": labels[label],
                        "count": len(companies[label]),
                        "total": company_count,
                        "urls": list(sources),
                        "evidence": [
                            {"url": url, "quote": quote}
                            for url, quote in sources.items()
                        ],
                    }
                    for label, sources in sorted(
                        counts.items(), key=lambda item: -len(companies[item[0]])
                    )
                ][:12]
            return {
                "status": "ok",
                "profile": {
                    "source": "market_sample",
                    "direction": direction,
                    "sample_count": len(jobs),
                    "low_sample": len(jobs) < 5,
                    "sample_note": f"仅基于 {len(jobs)} 条岗位" if len(jobs) < 5 else "",
                    "company_count": company_count,
                    "frequency_basis": "company",
                    "weighting_note": "频次按公司统计，同一公司对同一项最多计 1 次；公司未知时按域名归组，来源保留全部去重岗位。",
                    "fetched_at": now(),
                    **groups,
                    "sources": [
                        {k: j[k] for k in ("company", "company_inferred_from", "job_title", "url", "fetched_at") if k in j}
                        for j in jobs
                    ],
                },
            }

        return await self._run(
            "sample", key, 7, self.settings.JOB_INTEL_SAMPLE_LIMIT, work,
            timeout_seconds=SAMPLE_TIMEOUT,
        )

    async def search_company(self, name):
        try:
            web._search_query(name, "")
        except web.WebResearchError:
            return {"status": "rejected", "message": "请提供简短的公司名。"}
        key = " ".join(name.lower().split())

        async def work():
            hits = await self._providers(
                "search", f"{name} 官网 公司简介 行业 lang:zh", count=5
            )
            sources = {}
            for hit in hits or []:
                try:
                    await public_url(hit.url)
                    if matches(name, hit):
                        sources[hit.url] = hit
                except web.WebResearchError:
                    continue
            # A bounded site query can disambiguate an otherwise plausible site.
            if sources and not any(official_score(name, hit) for hit in sources.values()):
                from .company import source_type
                candidate = next((hit for hit in sources.values() if source_type(hit) != "百科"), None)
                site = "meituan.com" if name.strip() == "美团" else (urlsplit(candidate.url).hostname if candidate else None)
                if site:
                    extra = await self._providers("search", f"{name} 官网 官方网站", count=3,
                                                  site=site)
                    for hit in extra or []:
                        try:
                            await public_url(hit.url)
                            if matches(name, hit):
                                sources[hit.url] = hit
                        except web.WebResearchError:
                            continue
            if not sources:
                return {
                    "status": "unavailable",
                    "message": "暂未查到可核对的公司资料。",
                }
            try:
                extracted = await self._extract(
                    CompanyExtraction,
                    {"name": name, "sources": [{"title": hit.title, "url": hit.url,
                     "site_name": hit.site_name, "content": hit.evidence} for hit in sources.values()]},
                )
            except Exception:
                extracted = CompanyExtraction()  # the verified official hit is still useful
            company = {"name": name, "fetched_at": now(), "source": "company_search"}
            for field in ("official_site", "industry", "description"):
                value = getattr(extracted, field)
                hit = sources.get(value.url)
                if (
                    not hit
                    or not value.text
                    or not value.quote
                    or value.quote not in hit.title + "\n" + hit.evidence
                ):
                    continue
                if field != "official_site" and not supported_paraphrase(value.text, value.quote):
                    continue
                if field == "official_site":
                    try:
                        site = await public_url(value.text)
                    except web.WebResearchError:
                        continue
                    if (site.rstrip("/") not in (hit.evidence + " " + hit.url)
                            or not official_score(name, hit)):
                        continue
                company[field] = evidence_field(hit, value.text, value.quote)
            ranked = sorted(sources.values(), key=lambda hit: official_score(name, hit), reverse=True)
            if ranked and official_score(name, ranked[0]):
                hit = ranked[0]
                # Search result itself supplies the URL; never invent a hostname.
                parts = urlsplit(hit.url)
                site = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
                company["official_site"] = evidence_field(hit, site, hit.title)
            if not any(
                field in company
                for field in ("official_site", "industry", "description")
            ):
                return {
                    "status": "unavailable",
                    "message": "暂未查到有原文依据的公司资料。",
                }
            return {"status": "ok", "company": company}

        return await self._run(
            "company", key, 30, self.settings.JOB_INTEL_COMPANY_LIMIT, work
        )
