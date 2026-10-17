"""第十五批 a：全部合成资料、MockTransport 和结构化模型桩。"""

import asyncio
import copy
import json
from datetime import timedelta
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402
from app.services import web_research as web  # noqa: E402
from app.services.job_intel import (  # noqa: E402
    JobIntel,
    DeepSeekProvider,
    TavilyProvider,
    SearchHit,
    FetchedPage,
)  # noqa: E402
from app.services.job_intel import providers, service, integration  # noqa: E402
from app.services.job_intel.storage import Store, IntelCache, IntelUsage, today  # noqa: E402
from app.services.job_intel.extraction import (  # noqa: E402
    SampleExtraction,
    SampleJob,
    Evidence,
    CompanyExtraction,
    CompanyField,
)  # noqa: E402
from app.services.web_tool_intent import infer_web_tool  # noqa: E402
from app.services.resume_strategy import has_job_description  # noqa: E402
from test_web_research import response  # noqa: E402
import test_product_security_flow as harness  # noqa: E402

URL = "https://careers.example.org/jobs/1"
TEXT = "公司：纸舟科技\n岗位：AI产品经理实习\n工作地点：深圳\n薪资：200元/天\n岗位职责\n负责需求调研和产品设计。\n任职要求\n熟悉 RAG 和 Python，能够完成检索问答评估。\n本科及以上，有产品实习经历优先。"
PAGE = {
    "title": "AI产品经理实习",
    "url": URL,
    "content": TEXT,
    "kind": "job_page",
    "fetched_at": "2026-10-17T01:00:00Z",
}


def settings(**kwargs):
    return Settings(
        _env_file=None,
        **{
            "LLM_API_KEY": "",
            "TAVILY_API_KEY": "",
            "DEEPSEEK_TOOLS_API_KEY": "",
            **kwargs,
        },
    )


class ProviderStub:
    name = "deepseek"
    available = True

    def __init__(self, hits=None, page=None):
        self.search = AsyncMock(return_value=hits or [])
        self.fetch = AsyncMock(
            return_value=page or FetchedPage(TEXT, PAGE["title"], URL, "deepseek")
        )


class StructuredStub:
    def __init__(self, value):
        self.value, self.calls = value, []

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.value


def sample_fixture():
    hits, jobs = [], []
    for i in range(7):
        company = f"纸舟{i}科技" if i != 6 else "纸舟0科技"
        text = TEXT.replace("纸舟科技", company)
        url = f"https://careers.example.org/jobs/{i}"
        hits.append(SearchHit(PAGE["title"], url, text))
        jobs.append(
            SampleJob(
                url=url,
                is_job=True,
                company=company,
                job_title=PAGE["title"],
                skills=[
                    Evidence(text="RAG", quote="熟悉 RAG 和 Python"),
                    Evidence(text="RAG", quote="熟悉 RAG 和 Python"),
                    Evidence(text="虚构技能", quote="根本不存在的证据"),
                ],
                responsibilities=[
                    Evidence(text="需求调研", quote="负责需求调研和产品设计。")
                ],
                bonuses=[Evidence(text="产品实习经历", quote="有产品实习经历优先")],
                requirements=[Evidence(text="本科", quote="本科及以上")],
            )
        )
    hits += [
        SearchHit(PAGE["title"], hits[0].url + "?utm_source=x", hits[0].content),
        SearchHit("RAG课程介绍", "https://example.org/course", "这是一门技术课程"),
        SearchHit("GitHub岗位职责", "https://github.com/example/jobs", TEXT),
    ]
    return hits, SampleExtraction(jobs=jobs)


class IntelTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        IntelCache.__table__.create(self.engine)
        IntelUsage.__table__.create(self.engine)
        self.store = Store(sessionmaker(bind=self.engine))
        self.addCleanup(self.engine.dispose)
        self.dns = patch.object(
            web, "_resolve_public", AsyncMock(return_value="93.184.215.14")
        )
        self.dns.start()
        self.addCleanup(self.dns.stop)
        self.network = patch.object(
            httpx,
            "AsyncHTTPTransport",
            side_effect=AssertionError("测试禁止真实外部 HTTP"),
        )
        self.network.start()
        self.addCleanup(self.network.stop)

    def intel(self, **kwargs):
        return JobIntel(
            store=self.store,
            settings=kwargs.pop("settings", settings()),
            session=kwargs.pop("session", "s1"),
            **kwargs,
        )

    async def test_deepseek_request_fields_and_parse_summary(self):
        seen = []

        def handler(req):
            seen.append(req)
            if req.url.path.endswith("/search"):
                return response(
                    json.dumps(
                        {
                            "results": [
                                {
                                    "title": PAGE["title"],
                                    "site_name": "纸舟招聘",
                                    "site_icon": "ignored",
                                    "authority": 1,
                                    "rerank_score": 0.9,
                                    "date": "2026-10-01",
                                    "url": URL,
                                    "summary": TEXT,
                                    "snippet": "短摘要",
                                    "content": "",
                                }
                            ]
                        }
                    ).encode()
                )
            return response(
                json.dumps({"content": TEXT, "title": PAGE["title"]}).encode()
            )

        with patch.object(
            httpx,
            "AsyncHTTPTransport",
            side_effect=lambda **kw: httpx.MockTransport(handler),
        ):
            provider = DeepSeekProvider(
                settings(DEEPSEEK_TOOLS_API_KEY="offline-placeholder")
            )
            hits = await provider.search(
                "AI产品经理 lang:zh", count=3, after="2026-04-17", site="example.org"
            )
            page = await provider.fetch(URL)
        self.assertEqual(hits[0].content, TEXT)
        self.assertEqual(hits[0].site_name, "纸舟招聘")
        self.assertEqual(page.content, TEXT)
        for req in seen:
            self.assertEqual(req.method, "POST")
            self.assertEqual(req.headers["Authorization"], "Bearer offline-placeholder")
            self.assertEqual(set(req.extensions["timeout"].values()), {15.0})
        body = json.loads(seen[0].content)
        self.assertEqual(
            body,
            {
                "query": "AI产品经理 lang:zh after:2026-04-17 site:example.org",
                "count": 3,
                "need_content": True,
            },
        )
        self.assertEqual(json.loads(seen[1].content), {"url": URL})

    async def test_query_count_bounds_and_key_origin(self):
        p = DeepSeekProvider(
            settings(
                LLM_PROVIDER="deepseek",
                LLM_BASE_URL="https://api.deepseek.com",
                LLM_API_KEY="offline-placeholder",
            )
        )
        self.assertTrue(p.available)
        for base in (
            "https://api.deepseek.com.evil.org",
            "http://api.deepseek.com",
            "https://user@api.deepseek.com",
        ):
            self.assertFalse(
                DeepSeekProvider(
                    settings(
                        LLM_PROVIDER="deepseek",
                        LLM_BASE_URL=base,
                        LLM_API_KEY="offline-placeholder",
                    )
                ).available
            )
        self.assertTrue(
            DeepSeekProvider(settings(DEEPSEEK_TOOLS_API_KEY="override")).available
        )
        with patch.object(
            providers, "post_json", AsyncMock(return_value={"results": []})
        ) as post:
            await p.search("词" * 200, count=90, after="2026-04-17")
        self.assertLessEqual(len(post.call_args.args[2]["query"]), 128)
        self.assertEqual(post.call_args.args[2]["count"], 50)
        self.assertEqual(
            [
                p.name
                for p in providers.configured_providers(
                    settings(JOB_INTEL_PROVIDERS="tavily,deepseek,bailian")
                )
            ],
            ["tavily", "deepseek"],
        )

    async def test_tavily_wraps_existing_search_and_extract(self):
        p = TavilyProvider(settings(TAVILY_API_KEY="offline-placeholder"))
        with patch.object(
            web,
            "_search_response",
            AsyncMock(
                return_value={
                    "results": [{"title": "岗位", "url": URL, "content": TEXT}]
                }
            ),
        ) as existing:
            self.assertEqual(len(await p.search("AI", count=8)), 1)
        self.assertEqual(existing.call_args.kwargs["count"], 8)
        with patch.object(
            httpx,
            "AsyncHTTPTransport",
            side_effect=lambda **kw: httpx.MockTransport(
                lambda req: response(
                    json.dumps(
                        {"results": [{"url": URL, "raw_content": TEXT}]}
                    ).encode()
                )
            ),
        ):
            self.assertEqual((await p.fetch(URL)).content, TEXT)

    async def test_error_timeout_and_empty_fall_back_to_tavily(self):
        for failure in ("error", "timeout", "empty"):
            requests = []

            def handler(req):
                requests.append(req.url.host)
                if req.url.host == "api.deepseek.com":
                    if failure == "timeout":
                        raise httpx.ReadTimeout("offline timeout")
                    return response(
                        b'{"results":[]}', status=503 if failure == "error" else 200
                    )
                return response(
                    json.dumps(
                        {"results": [{"title": "招聘", "url": URL, "content": TEXT}]}
                    ).encode()
                )

            intel = self.intel(
                settings=settings(
                    DEEPSEEK_TOOLS_API_KEY="offline", TAVILY_API_KEY="offline"
                )
            )
            with patch.object(
                httpx,
                "AsyncHTTPTransport",
                side_effect=lambda **kw: httpx.MockTransport(handler),
            ):
                result = await intel._providers("search", "AI", count=3)
            self.assertEqual(result[0].provider, "tavily")
            self.assertEqual(requests, ["api.deepseek.com", "api.tavily.com"])

    async def test_missing_key_skips_and_both_failed_are_safe(self):
        first, second = ProviderStub(), ProviderStub()
        second.name = "tavily"
        first.available = False
        second.search.side_effect = httpx.ConnectError("private secret exception")
        intel = self.intel(providers=[first, second])
        result = await intel.sample_jobs("AI产品经理")
        self.assertEqual(result["status"], "insufficient")
        self.assertIn("具体 JD", result["message"])
        first.search.assert_not_called()
        self.assertNotIn("secret", str(result))

    async def test_self_fetch_success_does_not_call_provider(self):
        p = ProviderStub()
        with patch.object(web, "read_job_url", AsyncMock(return_value=PAGE)):
            result = await self.intel(providers=[p]).read_job_url(URL)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["card"]["company"], "纸舟科技")
        self.assertEqual(result["card"]["location"], "深圳")
        self.assertEqual(result["card"]["provider"], "self_fetch")
        p.fetch.assert_not_called()

    async def test_blocked_or_short_self_fetch_uses_provider(self):
        for self_result in (
            web.WebResearchError("该网站要求登录、验证或限制读取。"),
            {**PAGE, "content": "太短"},
        ):
            p = ProviderStub()
            mock = (
                AsyncMock(side_effect=self_result)
                if isinstance(self_result, Exception)
                else AsyncMock(return_value=self_result)
            )
            with patch.object(web, "read_job_url", mock):
                result = await self.intel(
                    providers=[p], session=str(id(mock))
                ).read_job_url(URL + "?case=" + str(id(mock)))
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["card"]["provider"], "deepseek_fetch")
            p.fetch.assert_awaited_once()

    async def test_illegal_and_private_urls_never_reach_either_reader(self):
        p = ProviderStub()
        with patch.object(web, "read_job_url", AsyncMock()) as read:
            for url in (
                "http://127.0.0.1",
                "http://10.0.0.1",
                "file:///etc/passwd",
                "https://user:password@example.org",
            ):
                self.assertEqual(
                    (await self.intel(providers=[p]).read_job_url(url))["status"],
                    "rejected",
                )
            with patch.object(
                web,
                "_resolve_public",
                AsyncMock(side_effect=web.WebResearchError("不是可读取的公开网页")),
            ):
                self.assertEqual(
                    (await self.intel(providers=[p]).read_job_url(URL))["status"],
                    "rejected",
                )
        read.assert_not_called()
        p.fetch.assert_not_called()

    async def test_provider_fetch_itself_rejects_private_and_redirect_safety_does_not_fallback(
        self,
    ):
        for cls in (DeepSeekProvider, TavilyProvider):
            with self.assertRaises(web.WebResearchError):
                await cls(settings()).fetch("http://127.0.0.1")
        p = ProviderStub()
        with patch.object(
            web,
            "read_job_url",
            AsyncMock(
                side_effect=web.WebResearchError(
                    "仅支持不含登录凭证的公开 HTTP 或 HTTPS 网页链接。"
                )
            ),
        ):
            result = await self.intel(providers=[p]).read_job_url(URL)
        self.assertEqual(result["status"], "rejected")
        p.fetch.assert_not_called()

    async def test_login_sites_and_wall_need_manual(self):
        p = ProviderStub(page=FetchedPage("登录后查看" * 100, "登录", URL, "deepseek"))
        with patch.object(
            web, "read_job_url", AsyncMock(side_effect=web.WebResearchError("被拦"))
        ):
            intel = self.intel(providers=[p])
            for host in ("www.zhipin.com", "www.liepin.com", "www.lagou.com"):
                result = await intel.read_job_url("https://" + host + "/jobs/1")
                self.assertEqual(result["status"], "needs_manual")
            self.assertEqual((await intel.read_job_url(URL))["status"], "needs_manual")

    async def test_github_and_personal_page_are_references(self):
        p = ProviderStub()
        with patch.object(
            web,
            "read_public_url",
            AsyncMock(return_value={**PAGE, "kind": "public_page"}),
        ) as read:
            result = await self.intel(providers=[p]).read_job_url(
                "https://github.com/example/repo"
            )
        self.assertEqual(result["status"], "public_page")
        read.assert_awaited_once()
        p.fetch.assert_not_called()
        with patch.object(
            web,
            "read_job_url",
            AsyncMock(return_value={**PAGE, "content": "个人作品介绍和项目链接" * 20}),
        ):
            result = await self.intel(providers=[p]).read_job_url(URL)
        self.assertEqual(result["status"], "public_page")

    async def test_sample_dedup_filter_statistics_and_sources(self):
        hits, extracted = sample_fixture()
        p, model = ProviderStub(hits), StructuredStub(extracted)
        result = await self.intel(providers=[p], llm=model).sample_jobs("AI产品经理")
        self.assertEqual(result["status"], "ok", result)
        profile = result["profile"]
        self.assertEqual(profile["sample_count"], 6)
        self.assertEqual(profile["skills"][0]["count"], 6)
        self.assertEqual(len(profile["skills"][0]["urls"]), 6)
        self.assertNotIn("虚构技能", str(profile))
        self.assertEqual(p.search.await_count, 3)
        for call in p.search.call_args_list:
            self.assertIn("lang:zh", call.args[0])
            self.assertIn("after", call.kwargs)
        # 提炼按 5 条一批并发，合计覆盖全部来源。
        self.assertEqual(sum(len(json.loads(call[-1].content)["sources"]) for call in model.calls), 7)
        self.assertTrue(all(len(json.loads(call[-1].content)["sources"]) <= 5 for call in model.calls))
        self.assertIn("requirements", profile)

    async def test_cache_hits_and_expiry_and_session_limits(self):
        hits, extracted = sample_fixture()
        p = ProviderStub(hits)
        intel = self.intel(providers=[p], llm=StructuredStub(extracted))
        with patch("app.services.job_intel.storage.today", return_value=today()):
            first = await intel.sample_jobs("AI产品经理")
        second = await intel.sample_jobs("ai产品经理")
        self.assertTrue(second["cached"])
        self.assertEqual(p.search.await_count, 3)
        self.assertEqual(first["profile"]["sources"], second["profile"]["sources"])
        await intel.sample_jobs("产品经理实习")
        result = await intel.sample_jobs("产品经理校招")
        self.assertEqual(result["status"], "limited")
        with patch(
            "app.services.job_intel.storage.today",
            return_value=today() + timedelta(days=7),
        ):
            self.assertIsNone(self.store.get("sample", "ai产品经理", 7))

    async def test_company_cache_30_days_and_missing_fields_not_invented(self):
        hit = SearchHit(
            "纸舟科技官网",
            "https://example.org/",
            "纸舟科技是一家软件公司，官网 https://example.org/",
        )
        model = StructuredStub(
            CompanyExtraction(
                industry=CompanyField(text="软件", quote="软件公司", url=hit.url),
                description=CompanyField(
                    text="造假的成立年份", quote="不存在", url=hit.url
                ),
                official_site=CompanyField(
                    text=hit.url, quote="官网 https://example.org/", url=hit.url
                ),
            )
        )
        p = ProviderStub([hit])
        intel = self.intel(providers=[p], llm=model)
        result = await intel.search_company("纸舟科技")
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("description", result["company"])
        self.assertEqual(result["company"]["industry"]["url"], hit.url)
        self.assertTrue((await intel.search_company("纸舟科技"))["cached"])
        self.assertEqual(p.search.await_count, 1)
        with patch(
            "app.services.job_intel.storage.today",
            return_value=today() + timedelta(days=29),
        ):
            self.assertIsNotNone(self.store.get("company", "纸舟科技", 30))
        with patch(
            "app.services.job_intel.storage.today",
            return_value=today() + timedelta(days=30),
        ):
            self.assertIsNone(self.store.get("company", "纸舟科技", 30))

    async def test_global_request_budget_and_concurrency(self):
        p = ProviderStub([SearchHit("招聘", URL, TEXT)])
        intel = self.intel(providers=[p], settings=settings(JOB_INTEL_DAILY_LIMIT=2))
        await asyncio.gather(
            *(intel._providers("search", "AI", count=1) for _ in range(5))
        )
        self.assertEqual(p.search.await_count, 2)
        active = peak = 0

        async def fetch(*args):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            await asyncio.sleep(0.02)
            active -= 1
            return FetchedPage(TEXT)

        p.fetch = fetch
        intel.settings.JOB_INTEL_DAILY_LIMIT = 100
        await asyncio.gather(*(intel._providers("fetch", URL) for _ in range(8)))
        self.assertLessEqual(peak, 3)

    async def test_logs_have_provider_billing_duration_without_key_or_body(self):
        p = ProviderStub()
        with self.assertLogs(service.logger, "INFO") as logs:
            await self.intel(providers=[p])._providers("fetch", URL)
        message = "\n".join(logs.output)
        self.assertIn("provider=deepseek", message)
        self.assertIn("billed=True", message)
        self.assertIn("elapsed_ms=", message)
        self.assertNotIn(TEXT, message)
        self.assertNotIn(URL, message)

    async def test_direction_is_merged_into_question_context_not_facts(self):
        from app.agents import resume_graph as graph
        from app.services.ask_user import question_context

        state = {
            **graph._init_state(),
            "intake_stage": "target",
            "messages": [HumanMessage(content="AI产品经理实习")],
        }
        profile = {
            "source": "market_sample",
            "direction": "AI产品经理实习",
            "sample_count": 6,
            "fetched_at": PAGE["fetched_at"],
            "skills": [{"text": "RAG", "count": 6}],
            "sources": [{"url": URL}],
        }
        before = copy.deepcopy(state["collected_info"])
        with patch.object(
            integration.background,
            "cached_sample",
            return_value={"status": "ok", "profile": profile},
        ) as sample:
            result = await graph.jd_input_node(state, object())
        self.assertEqual(result["jd_info"]["role_profile"]["source"], "market_sample")
        self.assertEqual(state["collected_info"], before)
        self.assertNotIn("collected_info", result)
        self.assertIn(
            "市场上的岗位通常看重：RAG（来源：6 条真实岗位）",
            question_context({**state, **result}),
        )
        self.assertFalse(has_job_description(result["jd_info"]))
        sample.assert_called_once()
        with patch.object(integration, "sample_jobs", AsyncMock()) as sample:
            self.assertEqual(
                await integration.enrich_direction(
                    {
                        **state,
                        "jd_text": TEXT,
                        "jd_info": {"job_title": "原岗位", "role_direction": "产品"},
                    },
                    object(),
                ),
                {},
            )
            sample.assert_not_called()

    async def test_writer_fact_view_and_skill_output_do_not_gain_rag(self):
        from app.agents.resume_writer import run_resume_writer
        from app.services.resume_facts import active_facts_for_writer
        from test_resume_writer import FakeModel, source, item, draft

        facts = source()
        before = copy.deepcopy(facts)
        profile = {
            "source": "market_sample",
            "role_family": "pm",
            "skills": [{"text": "RAG", "count": 6}],
            "requirements": [],
        }
        model = FakeModel(
            [
                (
                    "OnePassOutput",
                    {
                        "match_plan": {},
                        "writer": draft(
                            [item("p2", "projects", [("整理用户反馈并分类", ["f3"])])],
                            skill_groups={"技术": ["Python", "RAG"]},
                        ),
                    },
                )
            ]
        )
        result = await run_resume_writer(facts, profile, model)
        self.assertEqual(facts, before)
        self.assertNotIn("RAG", str(active_facts_for_writer(facts)))
        payload = json.loads(model.calls[0][1][-1].content)
        self.assertNotIn("RAG", str(payload["evidence"]))
        self.assertNotIn("RAG", str(result["resume_data"].get("skills")))
        self.assertNotIn("RAG", str(result["resume_data"].get("skill_groups")))

    async def test_company_tool_auto_once_and_persist_only_jd(self):
        from app.agents.public_reply import stream_public_reply
        from app.agents import resume_graph as graph
        from app.services.chat_turns import ChatTurn, current_turn

        class Model:
            def bind_tools(self, tools, **kwargs):
                self.tools = tools
                self.choice = kwargs
                return self

            async def ainvoke(self, messages):
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": str(i),
                            "name": "search_company",
                            "args": {"name": "纸舟科技"},
                        }
                        for i in range(2)
                    ],
                )

        company = {
            "name": "纸舟科技",
            "source": "company_search",
            "industry": {"text": "软件", "url": URL},
        }
        model = Model()
        turn = current_turn.set(ChatTurn("s1", "t1", "owner"))
        try:
            with patch(
                "app.services.job_intel.search_company",
                AsyncMock(return_value={"status": "ok", "company": company}),
            ) as search:
                reply = await stream_public_reply(model, [], ask_state={})
                await stream_public_reply(model, [], ask_state={})
            search.assert_awaited_once()
        finally:
            current_turn.reset(turn)
        self.assertEqual(model.choice, {"tool_choice": "auto"})
        self.assertEqual(
            {x["function"]["name"] for x in model.tools}, {"ask_user", "search_company"}
        )
        self.assertIn("[来源]", reply.content)

        @integration.intel_result
        async def node(state):
            return {"messages": [reply]}

        state = graph._init_state()
        before = copy.deepcopy(state)
        result = await node(state)
        self.assertEqual(result["jd_info"]["company"], company)
        self.assertEqual(state, before)
        self.assertNotIn("collected_info", result)

    async def test_url_route_keeps_job_card_and_target_completed(self):
        from app.api import chat
        from app.schemas.chat import ReadJobURL
        from app.agents import resume_graph as graph

        with patch.object(web, "read_job_url", AsyncMock(return_value=PAGE)):
            value = await self.intel(providers=[]).read_job_url(URL)
        source = {**PAGE, "job_card": value["card"]}
        req = "我想投这个岗位 " + URL
        self.assertEqual(infer_web_tool(req)["action"], "read_url")
        messages, task = chat._web_turn(
            [{"role": "user", "content": req}],
            ReadJobURL(action="read_url", url=URL),
            [source],
        )
        state = {
            **graph._init_state(),
            "messages": [
                HumanMessage(
                    content=messages[0]["content"],
                    additional_kwargs={"career_material_type": "jd"},
                )
            ],
            "requested_task": task,
            "web_sources": [source],
            "intake_progress": {"basics": "skipped"},
        }
        with patch.object(
            graph,
            "_run_decoder_and_build_reply",
            AsyncMock(
                return_value=(
                    {"job_title": PAGE["title"], "required_skills": ["RAG"]},
                    "已读取岗位。",
                )
            ),
        ):
            result = await graph.skill_task_node(state, object())
        self.assertEqual(result["jd_info"]["source"], "job_url")
        self.assertEqual(result["jd_info"]["job_card"]["url"], URL)
        self.assertNotIn("collected_info", result)
        from app.services.intake import intake_update

        self.assertNotEqual(
            intake_update({**state, **result})["intake_stage"], "target"
        )

    def test_dom_contract_and_deleted_entrypoints(self):
        result = subprocess.run(
            ["node", str(ROOT / "tests/intel.dom.js")], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    async def test_read_cache_one_day_and_each_session_quota(self):
        intel = self.intel(providers=[], settings=settings(JOB_INTEL_READ_LIMIT=1))
        with patch.object(web, "read_job_url", AsyncMock(return_value=PAGE)) as read:
            self.assertEqual((await intel.read_job_url(URL))["status"], "ok")
            self.assertTrue((await intel.read_job_url(URL))["cached"])
            self.assertEqual(
                (await intel.read_job_url(URL + "?job=2"))["status"], "limited"
            )
        read.assert_awaited_once()
        with patch(
            "app.services.job_intel.storage.today",
            return_value=today() + timedelta(days=1),
        ):
            self.assertIsNone(self.store.get("read_url", URL, 1))

    async def test_same_key_inflight_coalesces_and_cache_survives_removed_key(self):
        hits, extracted = sample_fixture()
        p = ProviderStub(hits)
        intel = self.intel(providers=[p], llm=StructuredStub(extracted))
        one, two = await asyncio.gather(
            intel.sample_jobs("产品实习"), intel.sample_jobs("产品实习")
        )
        self.assertEqual(one["status"], "ok")
        self.assertTrue(two["cached"])
        self.assertEqual(p.search.await_count, 3)
        p.available = False
        self.assertTrue((await intel.sample_jobs("产品实习"))["cached"])

    async def test_zero_global_budget_blocks_self_fetch_and_company_quota_persists(
        self,
    ):
        with patch.object(web, "read_job_url", AsyncMock(return_value=PAGE)) as read:
            self.assertEqual(
                (
                    await self.intel(
                        providers=[], settings=settings(JOB_INTEL_DAILY_LIMIT=0)
                    ).read_job_url(URL)
                )["status"],
                "limited",
            )
        read.assert_not_called()
        p = ProviderStub()
        first = self.intel(providers=[p], settings=settings(JOB_INTEL_COMPANY_LIMIT=1))
        await first.search_company("纸舟")
        second = self.intel(providers=[p], settings=settings(JOB_INTEL_COMPANY_LIMIT=1))
        self.assertEqual(
            (await second.search_company("另一家公司"))["status"], "limited"
        )

    async def test_login_wall_without_provider_and_extraction_failure_are_nonblocking(
        self,
    ):
        with patch.object(
            web,
            "read_job_url",
            AsyncMock(side_effect=web.WebResearchError("网页需要登录")),
        ):
            result = await self.intel(providers=[]).read_job_url(URL)
        self.assertEqual(result["status"], "needs_manual")
        self.assertIn("截图", result["message"])
        hits, _ = sample_fixture()
        with patch.object(
            service, "extract", AsyncMock(side_effect=ValueError("模型异常详情"))
        ):
            result = await self.intel(
                providers=[ProviderStub(hits)], llm=object()
            ).sample_jobs("AI产品")
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("异常详情", str(result))

    async def test_collecting_public_model_sees_market_context_before_followup(self):
        from app.agents import resume_graph as graph
        from app.agents.public_reply import stream_public_reply
        from test_batch14a_ask_user import project_state, ToolModel

        state = project_state()
        state["jd_info"] = {}
        state["jd_text"] = ""
        state["messages"] = [HumanMessage(content="想投 AI 产品经理实习")]
        profile = {
            "source": "market_sample",
            "direction": "AI 产品经理实习",
            "sample_count": 5,
            "skills": [{"text": "RAG", "count": 5}],
            "sources": [{"url": URL}],
            "fetched_at": PAGE["fetched_at"],
        }
        model = ToolModel(questions=False)

        async def collecting(working, llm):
            return {
                "messages": [await stream_public_reply(llm, [], ask_state=working)],
                "stage": "COLLECTING",
            }

        with (
            patch.object(
                graph,
                "_recover_candidate_history",
                AsyncMock(return_value=state["collected_info"]),
            ),
            patch.object(graph, "_collecting_turn_node", collecting),
            patch.object(
                integration.background,
                "cached_sample",
                return_value={"status": "ok", "profile": profile},
            ),
        ):
            result = await graph.collecting_node(state, model)
        self.assertEqual(result["jd_info"]["role_profile"]["sample_count"], 5)
        self.assertIn("市场上的岗位通常看重：RAG", str(model.messages))
        self.assertNotIn("RAG", str(result.get("collected_info")))

    def test_additive_migration_registers_independent_version_without_personal_writes(
        self,
    ):
        from app.services.schema_migrations import (
            SchemaVersion,
            require_current_schema,
            record_schema_version,
        )

        SchemaVersion.__table__.create(self.engine)
        record_schema_version(self.engine)
        require_current_schema(self.engine)
        record_schema_version(self.engine)
        with self.engine.connect() as db:
            versions = dict(
                db.execute(select(SchemaVersion.component, SchemaVersion.version)).all()
            )
        self.assertEqual(versions["job_intel"], 1)
        self.assertEqual(versions["product_profile"], 2)

    async def test_new_pasted_jd_does_not_reuse_previous_url_card(self):
        from app.services.job_intel.extraction import job_card, simple_job

        card = job_card(simple_job(PAGE), PAGE)
        state = {
            "web_sources": [{**PAGE, "job_card": card}],
            "jd_info": {"job_card": card},
        }

        @integration.intel_result
        async def node(state):
            return {
                "jd_text": "新岗位：数据分析，岗位职责：统计报表",
                "jd_info": {"job_title": "数据分析"},
                "messages": [],
            }

        result = await node(state)
        self.assertNotIn("job_card", result["jd_info"])
        self.assertEqual(result["messages"], [])

    def test_generic_read_request_still_classifies_recruitment_page(self):
        for prefix in ("帮我看看这个岗位 ", "请查看 ", "看看 "):
            self.assertEqual(infer_web_tool(prefix + URL)["action"], "read_url")

    def test_jsonld_location_salary_and_inline_requirements_are_preserved(self):
        from app.services.job_intel.extraction import job_card, simple_job

        job = {
            "@type": "JobPosting",
            "title": PAGE["title"],
            "description": TEXT,
            "hiringOrganization": {"name": "纸舟科技"},
            "jobLocation": {"address": {"addressLocality": "深圳"}},
            "baseSalary": {
                "currency": "CNY",
                "value": {"value": 200, "unitText": "DAY"},
            },
        }
        title, body, _ = web._extract(
            (
                '<script type="application/ld+json">' + json.dumps(job) + "</script>"
            ).encode(),
            "text/html",
        )
        card = job_card(
            simple_job({**PAGE, "title": title, "content": body}),
            {**PAGE, "title": title, "content": body},
        )
        self.assertEqual(card["location"], "深圳")
        self.assertIn("200", card["salary"])
        inline = {
            **PAGE,
            "content": TEXT.replace("岗位职责\n", "岗位职责：").replace(
                "任职要求\n", "任职要求："
            ),
        }
        self.assertTrue(simple_job(inline).responsibilities)
        self.assertTrue(simple_job(inline).requirements)

    async def test_public_read_and_structured_extraction_share_three_slots(self):
        active = peak = 0

        async def bounded(*args):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return {**PAGE, "kind": "public_page"}

        intel = self.intel(providers=[])
        with (
            patch.object(web, "read_public_url", bounded),
            patch.object(service, "extract", bounded),
        ):
            await asyncio.gather(
                *(
                    intel.read_job_url(f"https://github.com/example/repo{i}")
                    for i in range(5)
                ),
                *(intel._extract(object, {}) for _ in range(5)),
            )
        self.assertEqual(peak, 3)


class IntelAPITest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = harness.ProductSecurityFlow.asyncSetUp
    cleanup = harness.ProductSecurityFlow.cleanup
    login = harness.ProductSecurityFlow.login
    fixture = harness.ProductSecurityFlow.fixture

    async def test_auto_job_link_is_persisted_as_jd_and_never_as_personal_facts(self):
        from app.api import chat
        from app.agents import resume_graph as graph
        from app.services.job_intel.extraction import job_card, simple_job
        from writer_double import SourceWriter

        self.graph = graph.build_graph(SourceWriter(), checkpointer=self.saver)
        sid, original = await self.fixture()
        card = job_card(simple_job(PAGE), PAGE)
        with (
            patch.object(chat, "_get_llm", return_value=object()),
            patch.object(graph, "get_graph", return_value=self.graph),
            patch.object(
                chat,
                "_execute_web_tool",
                AsyncMock(return_value=[{**PAGE, "job_card": card}]),
            ),
            patch.object(
                graph,
                "_run_decoder_and_build_reply",
                AsyncMock(
                    return_value=(
                        {"job_title": PAGE["title"], "required_skills": ["RAG"]},
                        "已读到岗位。",
                    )
                ),
            ),
        ):
            result = await self.a.post(
                "/api/chat/stream",
                json={
                    "session_id": sid,
                    "messages": [{"role": "user", "content": "想试试这个岗位 " + URL}],
                },
            )
        self.assertNotIn('"error"', result.text)
        self.assertIn("已读到岗位", result.text)
        state = (
            await self.graph.aget_state({"configurable": {"thread_id": sid}})
        ).values
        self.assertEqual(state["jd_info"]["source"], "job_url")
        self.assertNotIn("RAG", str(state["collected_info"]))
        self.assertNotIn("RAG", str(state["resume_data"].get("skills")))
        history = await self.a.get("/api/chat/conversations/" + sid)
        self.assertEqual(
            history.json()["workspace"]["jd"]["info"]["job_card"]["url"], URL
        )

    async def test_needs_manual_is_normal_reply_and_saved_history_not_error(self):
        from app.api import chat

        sid, original = await self.fixture()
        with (
            patch.object(chat, "_get_llm", return_value=object()),
            patch.object(
                chat,
                "_execute_web_tool",
                AsyncMock(
                    return_value=[{"kind": "intel_notice", "content": service.MANUAL}]
                ),
            ),
            patch.object(chat, "stream_agent") as stream,
        ):
            result = await self.a.post(
                "/api/chat/stream",
                json={
                    "session_id": sid,
                    "messages": [
                        {"role": "user", "content": "https://www.zhipin.com/job/1"}
                    ],
                },
            )
        self.assertIn("截图", result.text)
        self.assertNotIn('"error"', result.text)
        stream.assert_not_called()
        history = await self.a.get("/api/chat/conversations/" + sid)
        self.assertIn(service.MANUAL, str(history.json()))
        current = await self.a.get("/api/resume/current", params={"session_id": sid})
        self.assertEqual(current.json()["data"], original)

    async def test_non_recruitment_auto_url_routes_to_public_reference(self):
        from app.api import chat

        sid, _ = await self.fixture()
        captured = {}

        async def stream(messages, session, llm, **kwargs):
            captured.update(kwargs)
            yield "公开作品资料。"

        with (
            patch.object(chat, "_get_llm", return_value=object()),
            patch.object(
                chat,
                "_execute_web_tool",
                AsyncMock(return_value=[{**PAGE, "kind": "public_page"}]),
            ),
            patch.object(chat, "stream_agent", stream),
        ):
            await self.a.post(
                "/api/chat/stream",
                json={
                    "session_id": sid,
                    "messages": [
                        {
                            "role": "user",
                            "content": "这是作品 https://example.org/portfolio",
                        }
                    ],
                },
            )
        self.assertEqual(captured["task"], "research_job")
