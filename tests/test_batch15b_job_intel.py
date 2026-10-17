"""15b: realistic provider shapes; all HTTP/model calls are stubs."""
import asyncio
import copy
import json
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from langchain_core.messages import HumanMessage

import test_batch15a_job_intel as base
import test_product_security_flow as harness
from app.agents import resume_graph as graph_module
from app.api import chat
from app.services import web_research as web
from app.services.chat_turns import current_turn
from app.services.job_intel import providers, service, integration, background
from app.services.job_intel.company import supported_paraphrase
from app.services.job_intel.extraction import (
    CompanyExtraction, CompanyField, JobExtraction, Evidence, job_card, simple_job,
)
from app.services.session_store import session_lock


def provider_row(title, url, summary="", snippet="", content="", site_name=""):
    return {"title": title, "url": url, "summary": summary, "snippet": snippet,
            "content": content, "site_name": site_name, "site_icon": "https://example.org/icon.png",
            "authority": 0.8, "rerank_score": 0.9, "date": "2026-10-17"}


PROFILE = {"source": "market_sample", "direction": "AI产品经理实习", "sample_count": 6,
           "fetched_at": base.PAGE["fetched_at"], "skills": [{"text": "RAG", "count": 6}],
           "sources": [{"url": base.URL}], "responsibilities": [], "bonuses": []}
RESULT = {"status": "ok", "profile": PROFILE}


class IntelCorrectionsTest(unittest.IsolatedAsyncioTestCase):
    setUp = base.IntelTest.setUp
    intel = base.IntelTest.intel

    def test_meituan_generic_title_sections_and_safe_company_inference(self):
        page = {**base.PAGE, "title": "职位详情", "site_name": "美团招聘",
                "url": "https://zhaopin.meituan.com/web/position/detail?jobUnionId=4687739175",
                "content": "AI产品经理实习-日常实习\n岗位职责\n负责需求调研。\n任职要求\n熟悉数据分析。\n具备以下条件优先\n有产品实习经验。\n岗位亮点\n导师指导。"}
        card = job_card(simple_job(page), page)
        self.assertEqual(card["company"], "美团")
        self.assertEqual(card["job_title"], "AI产品经理实习-日常实习")
        self.assertEqual([i["text"] for i in card["requirements"]], ["熟悉数据分析。"])
        self.assertEqual([i["text"] for i in card["bonuses"]], ["有产品实习经验。"])
        self.assertNotIn("导师", str(card["requirements"]))
        # The same corrections apply even when the structured model misclassifies lines.
        model = JobExtraction(is_job=True, job_title="职位详情", requirements=[
            Evidence(text=line, quote=line) for line in
            ("熟悉数据分析。", "具备以下条件优先", "有产品实习经验。", "岗位亮点", "导师指导。")])
        corrected = job_card(model, page)
        self.assertEqual(corrected["job_title"], card["job_title"])
        self.assertEqual(corrected["requirements"], card["requirements"])
        self.assertEqual(corrected["bonuses"], card["bonuses"])
        self.assertEqual(simple_job({**page, "site_name": ""}).company, "美团")
        unknown = {**page, "url": base.URL, "site_name": "Boss直聘"}
        self.assertEqual(simple_job(unknown).company, "")
        self.assertEqual(simple_job({**unknown, "content": "部门 / 公司：纸舟科技\n" + page["content"]}).company, "纸舟科技")

    def test_generic_titles_and_jsonld_company_title(self):
        for title in ("岗位详情", "招聘", "Job Detail", "Job Details | Careers", "职位详情 - 美团招聘"):
            with self.subTest(title=title):
                page = {**base.PAGE, "title": title, "content": "AI产品经理实习\n岗位职责\n做需求分析。\n任职要求\n熟悉Python"}
                self.assertEqual(job_card(JobExtraction(job_title=title), page)["job_title"], "AI产品经理实习")
        data = {"@type": "JobPosting", "title": "AI产品经理实习", "description": base.TEXT,
                "hiringOrganization": {"name": "纸舟科技"}}
        title, content, _ = web._extract(('<script type="application/ld+json">' + json.dumps(data) + '</script>').encode(), "text/html")
        card = job_card(simple_job({**base.PAGE, "title": title, "content": content}), {**base.PAGE, "title": title, "content": content})
        self.assertEqual((card["job_title"], card["company"]), ("AI产品经理实习", "纸舟科技"))
        data.pop("description")
        data.update(responsibilities="负责产品调研和用户访谈，整理功能需求并跟踪产品迭代进度。", qualifications="熟悉数据分析方法，能够使用数据工具进行分析。具有良好的沟通能力。")
        title, content, _ = web._extract(('<script type="application/ld+json">' + json.dumps(data) + '</script>').encode(), "text/html")
        self.assertTrue(service.is_job_page(title, content, base.URL))
        self.assertTrue(simple_job({**base.PAGE, "title": title, "content": content}).requirements)

    async def test_fetch_metadata_reaches_job_card(self):
        fetched = providers.FetchedPage(base.TEXT.replace("公司：纸舟科技\n", ""), "职位详情", base.URL, "deepseek", "纸舟科技招聘")
        with patch.object(web, "read_job_url", AsyncMock(side_effect=web.WebResearchError("公开页暂不可用"))):
            result = await self.intel(providers=[base.ProviderStub(page=fetched)]).read_job_url(base.URL)
        self.assertEqual(result["card"]["company"], "纸舟科技")
        self.assertEqual(result["card"]["job_title"], "AI产品经理实习")

    async def test_old_cached_card_is_repaired_without_an_external_call(self):
        url = "https://zhaopin.meituan.com/web/position/detail?jobUnionId=4687739175"
        page = {**base.PAGE, "url": url, "title": "职位详情", "content": "AI产品经理实习\n岗位职责\n负责产品调研\n任职要求\n熟悉Python\n加分项\n有实习经验"}
        old = {"status": "ok", "page": page, "card": {"company": "", "job_title": "职位详情", "requirements": [{"text": "加分项", "quote": "加分项"}, {"text": "有实习经验", "quote": "有实习经验"}]}}
        self.store.put("read_url", url, old)
        with patch.object(web, "read_job_url", AsyncMock()) as fetch:
            result = await self.intel(providers=[]).read_job_url(url)
        self.assertTrue(result["cached"])
        self.assertEqual((result["card"]["company"], result["card"]["job_title"]), ("美团", "AI产品经理实习"))
        self.assertFalse(result["card"]["requirements"])
        self.assertEqual(result["card"]["bonuses"][0]["text"], "有实习经验")
        fetch.assert_not_called()

    async def test_mixed_company_aliases_summary_snippet_and_paraphrase(self):
        url = "https://natureselect.example.org/about"
        rows = [provider_row("Nature Select 官方网站", url,
                summary="Nature Select 是一家提供人工智能软件服务的企业。",
                snippet="自然选择专注于人工智能产品研发。", site_name="Nature Select")]
        hit = providers.parse_hits({"results": rows}, "deepseek", 5)[0]
        self.assertIn("自然选择", hit.evidence)
        self.assertEqual(hit.rerank_score, 0.9)
        model = base.StructuredStub(CompanyExtraction(
            industry=CompanyField(text="人工智能软件服务行业", quote="提供人工智能软件服务的企业", url=url),
            description=CompanyField(text="人工智能产品研发公司", quote="自然选择专注于人工智能产品研发。", url=url)))
        p = base.ProviderStub([hit])
        result = await self.intel(providers=[p], llm=model).search_company("自然选择 Nature Select")
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(set(result["company"]) & {"industry", "description", "official_site"}, {"industry", "description", "official_site"})
        self.assertEqual(result["company"]["official_site"]["text"], "https://natureselect.example.org/")
        self.assertIn("自然选择", model.calls[0][-1].content)
        p.search.assert_awaited_once()

    async def test_meituan_encyclopedia_description_and_official_search_hit(self):
        encyclopedia = "https://baike.baidu.com/item/meituan"
        official = "https://www.meituan.com/about"
        rows = [provider_row("美团", encyclopedia, snippet="美团是一家提供本地生活服务的科技企业。", site_name="百度百科"),
                provider_row("美团官方网站", official, summary="美团提供本地生活服务。")]
        hits = providers.parse_hits({"results": rows}, "deepseek", 5)
        model = base.StructuredStub(CompanyExtraction(
            industry=CompanyField(text="本地生活服务行业", quote="提供本地生活服务的科技企业", url=encyclopedia),
            description=CompanyField(text="提供本地生活服务的科技公司", quote="提供本地生活服务的科技企业", url=encyclopedia)))
        result = await self.intel(providers=[base.ProviderStub(hits)], llm=model).search_company("美团")
        company = result["company"]
        self.assertEqual(company["official_site"]["text"], "https://www.meituan.com/")
        self.assertEqual(company["description"]["source_type"], "百科")
        self.assertIn("百科来源", integration.company_reply(result))

    async def test_company_mismatch_fabricated_quote_and_semantic_claim_rejected(self):
        url = "https://example.org/about"
        hit = providers.SearchHit("纸舟科技", url, "纸舟科技是一家软件服务企业。")
        model = base.StructuredStub(CompanyExtraction(
            industry=CompanyField(text="生物制药", quote="软件服务企业", url=url),
            description=CompanyField(text="软件公司", quote="不存在的原文", url=url)))
        p = base.ProviderStub([hit])
        self.assertEqual((await self.intel(providers=[p], llm=model).search_company("纸舟科技"))["status"], "unavailable")
        self.assertEqual((await self.intel(providers=[p], llm=model).search_company("另一家公司 Other Firm"))["status"], "unavailable")
        for text in ("2020年成立的软件公司", "最大的人工智能公司", "提供软件服务"):
            self.assertFalse(supported_paraphrase(text, "不提供软件服务"))

    async def test_bounded_site_query_finds_official_source(self):
        initial = providers.SearchHit("纸舟科技", "https://paper.example.org/about", "纸舟科技提供软件服务")
        official = providers.SearchHit("纸舟科技官网", "https://paper.example.org/", "纸舟科技提供软件服务")
        p = base.ProviderStub()
        p.search = AsyncMock(side_effect=[[initial], [official]])
        result = await self.intel(providers=[p], llm=base.StructuredStub(CompanyExtraction())).search_company("纸舟科技")
        self.assertEqual(result["company"]["official_site"]["url"], official.url)
        self.assertEqual(p.search.call_args.kwargs["site"], "paper.example.org")
        self.assertEqual(p.search.await_count, 2)

    async def test_encyclopedia_only_meituan_uses_known_job_domain_and_survives_model_failure(self):
        p = base.ProviderStub()
        p.search = AsyncMock(side_effect=[
            [providers.SearchHit("美团", "https://baike.baidu.com/item/m", "美团提供本地生活服务", "百度百科")],
            [providers.SearchHit("美团官方网站", "https://www.meituan.com/", "美团提供本地生活服务")]])
        with patch.object(service, "extract", AsyncMock(side_effect=TimeoutError())):
            result = await self.intel(providers=[p], llm=object()).search_company("美团")
        self.assertEqual(p.search.call_args.kwargs["site"], "meituan.com")
        self.assertEqual(result["company"]["official_site"]["text"], "https://www.meituan.com/")

    async def test_sample_uses_summary_and_compressed_sections_only(self):
        hits, extracted = base.sample_fixture()
        rows = [provider_row(hit.title, hit.url, summary=hit.content + "\n公司介绍\n" + "冗长广告" * 3000) for hit in hits[:7]]
        model = base.StructuredStub(extracted)
        result = await self.intel(providers=[base.ProviderStub(providers.parse_hits({"results": rows}, "deepseek", 10))], llm=model).sample_jobs("AI产品经理")
        self.assertEqual(result["status"], "ok", result)
        sources = json.loads(model.calls[0][-1].content)["sources"]
        self.assertTrue(all(len(row["content"]) <= 1500 for row in sources))
        self.assertNotIn("冗长广告", str(sources))
        self.assertNotIn("site_icon", str(sources))
        self.assertIn("岗位职责", sources[0]["content"])

    async def test_per_call_deadline_and_total_budget_are_distinct(self):
        hits, extracted = base.sample_fixture()
        p = base.ProviderStub(hits)
        model = base.StructuredStub(extracted)
        real_timeout = asyncio.timeout
        durations = []

        def record(seconds):
            durations.append(seconds)
            return real_timeout(seconds)

        with patch.object(service.asyncio, "timeout", side_effect=record):
            result = await self.intel(providers=[p], llm=model).sample_jobs("AI产品经理")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(durations[0], 60)
        self.assertTrue(all(value == 15 for value in durations[1:]), durations)
        slow = AsyncMock(side_effect=lambda *args: None)

        async def hang(*args, **kwargs):
            await asyncio.Event().wait()

        p.search = hang
        with patch.object(service, "CALL_TIMEOUT", 0.01):
            self.assertIsNone(await self.intel(providers=[p])._request(p, "search", "query", count=1))
            with patch.object(service, "extract", side_effect=hang):
                with self.assertRaises(TimeoutError):
                    await self.intel(providers=[], llm=slow)._extract(JobExtraction, {})


class BackgroundIntelTest(unittest.IsolatedAsyncioTestCase):
    cleanup = harness.ProductSecurityFlow.cleanup
    login = harness.ProductSecurityFlow.login
    fixture = harness.ProductSecurityFlow.fixture

    async def asyncSetUp(self):
        await harness.ProductSecurityFlow.asyncSetUp(self)
        self.addAsyncCleanup(self.drain)
        for p in (patch.object(background, "cached_sample", return_value=None),
                  patch.object(httpx, "AsyncHTTPTransport", side_effect=AssertionError("禁止真实外部 HTTP"))):
            p.start()
            self.patches.append(p)

    async def drain(self):
        tasks = [task for task, _ in background._tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def values(self, sid):
        return (await self.graph.aget_state({"configurable": {"thread_id": sid}})).values

    async def seed(self):
        sid, data = await self.fixture()
        values = await self.values(sid)
        values.update(jd_text="", jd_info={"role_direction": PROFILE["direction"], "role_profile": {"source": "direction"}})
        await self.graph.aupdate_state({"configurable": {"thread_id": sid}}, values, as_node="dialogue")
        return sid, values, data

    async def start(self, sid, values):
        async with session_lock(sid):
            result = await integration.enrich_direction(values, object(), graph=self.graph, session=sid)
            await self.graph.aupdate_state({"configurable": {"thread_id": sid}}, result, as_node="dialogue")
        return result

    async def finish(self):
        await asyncio.wait_for(asyncio.gather(*(task for task, _ in list(background._tasks.values()))), 2)

    async def test_real_target_sse_finishes_before_sampling_and_current_shows_completion(self):
        gate, started = asyncio.Event(), asyncio.Event()

        async def sample(*args, **kwargs):
            self.assertIsNone(current_turn.get())
            started.set()
            kwargs["on_progress"](6)
            await gate.wait()
            return RESULT

        created = await self.a.post("/api/chat/conversations")
        sid = created.json()["session_id"]
        with patch.object(integration, "sample_jobs", side_effect=sample) as sampler, patch.object(chat, "_get_llm", return_value=object()), patch.object(graph_module, "get_graph", return_value=self.graph):
            response = await asyncio.wait_for(self.a.post("/api/chat/stream", json={"session_id": sid, "messages": [{"role": "user", "content": PROFILE["direction"]}]}), 2)
            self.assertNotIn('"error"', response.text, response.text)
            self.assertIn('[DONE]', response.text)
            await asyncio.wait_for(started.wait(), 1)
            self.assertFalse(gate.is_set())
            values = await self.values(sid)
            self.assertEqual(values["jd_info"]["role_profile"]["status"], "pending")
            self.assertEqual(integration.market_context(values), "")
            gate.set()
            await self.finish()
        current = await self.a.get(f"/api/resume/current?session_id={sid}")
        profile = current.json()["workspace"]["jd"]["info"]["role_profile"]
        self.assertEqual((profile["status"], profile["sample_count"]), ("ready", 6))
        self.assertIn("RAG", integration.market_context(await self.values(sid)))
        self.assertNotIn("RAG", str((await self.values(sid))["collected_info"]))
        sampler.assert_awaited_once()
        from test_batch14a_ask_user import ToolModel
        from app.agents.public_reply import stream_public_reply
        model = ToolModel(questions=False)
        latest = await self.values(sid)

        async def next_reply(working, llm):
            return {"messages": [await stream_public_reply(llm, [], ask_state=working)], "stage": "COLLECTING"}

        with patch.object(graph_module, "_recover_candidate_history", AsyncMock(return_value=latest["collected_info"])), patch.object(graph_module, "_collecting_turn_node", next_reply), patch.object(integration, "sample_jobs", AsyncMock()) as repeat:
            await graph_module.collecting_node(latest, model)
        self.assertIn("市场上的岗位通常看重：RAG", str(model.messages))
        repeat.assert_not_called()

    async def test_concurrent_user_message_keeps_facts_messages_company_and_resume(self):
        sid, values, original = await self.seed()
        gate = asyncio.Event()

        async def sample(*args, **kwargs):
            await gate.wait()
            return RESULT

        with patch.object(integration, "sample_jobs", side_effect=sample):
            await self.start(sid, values)
            async with session_lock(sid):
                gate.set()
                await asyncio.sleep(0.01)
                newest = await self.values(sid)
                info = {**newest["jd_info"], "company": {"source": "company_search", "name": "新公司"}}
                facts = copy.deepcopy(newest["collected_info"])
                facts["basic_info"]["name"] = "新姓名"
                await self.graph.aupdate_state({"configurable": {"thread_id": sid}}, {
                    "jd_info": info, "collected_info": facts, "session_constraints": {"keep": "用户新要求"},
                    "messages": [HumanMessage(content="新消息不能丢失", id="latest")]}, as_node="dialogue")
            await self.finish()
        latest = await self.values(sid)
        self.assertEqual(latest["collected_info"], facts)
        self.assertEqual(latest["resume_data"], original)
        self.assertEqual(latest["session_constraints"], {"keep": "用户新要求"})
        self.assertTrue(any(m.id == "latest" for m in latest["messages"]))
        self.assertEqual(latest["jd_info"]["company"]["name"], "新公司")
        self.assertEqual(latest["jd_info"]["role_profile"]["status"], "ready")

    async def test_timeout_and_exception_become_failed(self):
        async def hang(*args, **kwargs):
            await asyncio.Event().wait()

        for sampler in (hang, AsyncMock(side_effect=ValueError("private stack trace"))):
            sid, values, _ = await self.seed()
            with patch.object(background, "BUDGET_SECONDS", 0.02), patch.object(integration, "sample_jobs", side_effect=sampler):
                await self.start(sid, values)
                await self.finish()
            profile = (await self.values(sid))["jd_info"]["role_profile"]
            self.assertEqual(profile["status"], "failed")
            self.assertNotIn("private", profile["message"])

    async def test_restart_expired_pending_repairs_on_current_without_resampling(self):
        sid, values, _ = await self.seed()
        values["jd_info"]["role_profile"].update(status="pending", task_id="lost", deadline_at=time.time()-1)
        await self.graph.aupdate_state({"configurable": {"thread_id": sid}}, {"jd_info": values["jd_info"]}, as_node="dialogue")
        with patch.object(integration, "sample_jobs", AsyncMock()) as sample:
            response = await self.a.get(f"/api/resume/current?session_id={sid}")
        self.assertEqual(response.json()["workspace"]["jd"]["info"]["role_profile"]["status"], "failed")
        self.assertEqual((await self.values(sid))["jd_info"]["role_profile"]["status"], "failed")
        sample.assert_not_called()

    async def test_expired_current_does_not_wait_for_chat_lock_and_sse_repairs(self):
        sid, values, _ = await self.seed()
        values["jd_info"]["role_profile"].update(status="pending", task_id="lost", deadline_at=time.time()-1)
        await self.graph.aupdate_state({"configurable": {"thread_id": sid}}, {"jd_info": values["jd_info"]}, as_node="dialogue")
        async with session_lock(sid):
            response = await asyncio.wait_for(self.a.get(f"/api/resume/current?session_id={sid}"), 1)
            self.assertEqual(response.json()["workspace"]["jd"]["info"]["role_profile"]["status"], "failed")
            meta = await chat._session_meta(sid, object())
            self.assertEqual(meta["workspace"]["jd"]["info"]["role_profile"]["status"], "failed")
        self.assertEqual((await self.values(sid))["jd_info"]["role_profile"]["status"], "failed")

    async def test_duplicate_trigger_coalesces_and_cache_is_immediately_ready(self):
        sid, values, _ = await self.seed()
        gate = asyncio.Event()

        async def sample(*args, **kwargs):
            await gate.wait()
            return RESULT

        with patch.object(integration, "sample_jobs", side_effect=sample) as sampler:
            first = await self.start(sid, values)
            again = await self.start(sid, values)
            self.assertEqual(first["jd_info"]["role_profile"]["task_id"], again["jd_info"]["role_profile"]["task_id"])
            self.assertEqual(await integration.enrich_direction({**values, **again}, object(), graph=self.graph, session=sid), {})
            gate.set()
            await self.finish()
            sampler.assert_awaited_once()
        with patch.object(background, "cached_sample", return_value=RESULT), patch.object(integration, "sample_jobs", AsyncMock()) as sampler:
            result = await integration.enrich_direction(values, object(), graph=self.graph, session="different-session")
            recovered = await integration.enrich_direction({**values, **first}, object(), graph=self.graph, session=sid)
        self.assertEqual(result["jd_info"]["role_profile"]["status"], "ready")
        self.assertEqual(recovered["jd_info"]["role_profile"]["status"], "ready")
        sampler.assert_not_called()

    async def test_direction_or_jd_change_prevents_stale_write_and_deletion_stays_deleted(self):
        for replacement in ({"jd_info": {"role_direction": "数据分析"}}, {"jd_text": "用户新提供的具体岗位"}, "delete"):
            sid, values, _ = await self.seed()
            gate = asyncio.Event()

            async def sample(*args, **kwargs):
                await gate.wait()
                return RESULT

            with patch.object(integration, "sample_jobs", side_effect=sample):
                await self.start(sid, values)
                if replacement == "delete":
                    response = await self.a.delete(f"/api/chat/session/{sid}")
                    self.assertEqual(response.status_code, 200)
                else:
                    async with session_lock(sid):
                        await self.graph.aupdate_state({"configurable": {"thread_id": sid}}, replacement, as_node="dialogue")
                gate.set()
                await self.finish()
            latest = await self.values(sid)
            self.assertNotEqual((latest.get("jd_info") or {}).get("source"), "market_sample")
            if replacement == "delete":
                self.assertFalse(latest)
