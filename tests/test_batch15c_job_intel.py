"""15c: reported live-result shapes, with synthetic bodies and offline model/provider stubs."""
import json
import unittest
from unittest.mock import AsyncMock, patch

import test_batch15a_job_intel as base
from app.services import web_research as web
from app.services.job_intel import background, integration
from app.services.job_intel.extraction import (
    Evidence, JobExtraction, SampleExtraction, SampleJob, job_card,
    normalized_job_title, simple_job, unescape_markdown, usable_title,
)


# These headers reproduce the reported ten results; bodies below are test data,
# not claims about these employers' actual requirements.
ROWS = [
    ("美团", r"AI产品经理实习\-日常实习", "美团招聘", "zhaopin.meituan.com"),
    ("", "MEG星海计划-AI产品经理实习生(J98102)", "zhiye.com", "kunlunxin.zhiye.com"),
    ("", "AI 产品经理实习生(J103757)", "zhiye.com", "kunlunxin.zhiye.com"),
    ("", "AI产品经理实习生(J103322)", "zhiye.com", "kunlunxin.zhiye.com"),
    ("自然选择（深圳）智能有限公司", "复旦大学就业指导与生涯发展处", "复旦大学就业指导与生涯发展服务中心", "career.fudan.edu.cn"),
    ("美团", "AI产品经理实习生（智能学习方向）", "猎聘", "liepin.com"),
    ("小米智能科技", "Ai产品经理实习", "实习僧", "shixiseng.com"),
    ("", "AI 产品经理实习生（C 端 / 招聘业务）", "牛客网", "nowcoder.com"),
    ("", "AI 产品经理实习生（软件方向）", "quanzhi.com", "quanzhi.com"),
    ("伊莉丝（深圳）智能科技有限公司", "AI产品实习生-EVE", "北京大学就业信息网", "scc.pku.edu.cn"),
]


def reported_fixture():
    hits, jobs = [], []
    for i, (company, title, site, domain) in enumerate(ROWS):
        url = f"https://{domain}/jobs/{i}"
        role = "AI产品经理实习生（智能产品方向）" if i == 4 else title
        body = (f"公司：{company}\n" if company else "") + (
            f"岗位：{role}\n岗位职责\n负责需求调研。\n任职要求\n熟悉 Python。\n"
            "本科及以上。\n加分项\n有产品实习经验。"
        )
        skills = [Evidence(text="Python", quote="熟悉 Python。")]
        if domain == "kunlunxin.zhiye.com":
            body = body.replace("本科及以上。", "本科及以上。\n了解模型评估。")
            skills.insert(0, Evidence(text="模型评估", quote="了解模型评估。"))
        hits.append(base.SearchHit(title, url, body, site_name=site))
        jobs.append(SampleJob(
            url=url, is_job=True, company=company, job_title=title, skills=skills,
            responsibilities=[Evidence(text="需求调研", quote="负责需求调研。")],
            requirements=[Evidence(text="本科", quote="本科及以上。")],
            bonuses=[Evidence(text="产品实习经验", quote="有产品实习经验。")],
        ))
    return hits, SampleExtraction(jobs=jobs)


class SampleCorrectionsTest(unittest.IsolatedAsyncioTestCase):
    setUp = base.IntelTest.setUp
    intel = base.IntelTest.intel

    async def test_reported_ten_rows_keep_all_valid_jobs_then_dedup_to_nine(self):
        hits, extracted = reported_fixture()
        cards = [job_card(job, {**base.PAGE, "url": hit.url, "title": hit.title,
                               "content": hit.content, "site_name": hit.site_name})
                 for hit, job in zip(hits, extracted.jobs)]
        self.assertEqual(len(cards), 10)
        self.assertTrue(all(usable_title(card["job_title"]) for card in cards))
        self.assertEqual(cards[4]["job_title"], "AI产品经理实习生（智能产品方向）")
        provider, model = base.ProviderStub(hits), base.StructuredStub(extracted)
        progress = []
        result = await self.intel(providers=[provider], llm=model).sample_jobs(
            "AI产品经理实习", on_progress=progress.append)
        self.assertEqual(result["status"], "ok", result)
        profile = result["profile"]
        self.assertEqual(progress, [10])
        self.assertEqual(profile["sample_count"], 9)
        self.assertFalse(profile["low_sample"])
        self.assertEqual(profile["company_count"], 7)
        self.assertEqual(profile["frequency_basis"], "company")
        self.assertIn("同一公司对同一项最多计 1 次", profile["weighting_note"])
        self.assertIn("公司未知时按域名归组", profile["weighting_note"])
        self.assertEqual({row["url"] for row in profile["sources"]},
                         {hit.url for i, hit in enumerate(hits) if i != 3})
        kunlun = [row for row in profile["sources"] if row["company"] == "kunlunxin"]
        self.assertEqual(len(kunlun), 2)
        self.assertTrue(all(row["company_inferred_from"] == "domain" for row in kunlun))
        self.assertEqual(sum(not row["company"] for row in profile["sources"]), 2)
        self.assertEqual(profile["sources"][0]["job_title"], "AI产品经理实习-日常实习")
        # Weight and ordering use distinct companies, while all supporting URLs remain.
        self.assertEqual([item["text"] for item in profile["skills"]], ["Python", "模型评估"])
        for field in ("responsibilities", "skills", "requirements", "bonuses"):
            item = profile[field][0]
            self.assertEqual((item["count"], item["total"]), (7, 7))
            self.assertEqual(len(item["urls"]), 9)
            self.assertEqual(len(item["evidence"]), 9)
        self.assertEqual(profile["skills"][1]["count"], 1)
        self.assertEqual(len(profile["skills"][1]["urls"]), 2)
        self.assertEqual(provider.search.await_count, 3)
        self.assertTrue(all(call.kwargs["count"] == 10 for call in provider.search.call_args_list))
        self.assertEqual([len(json.loads(call[-1].content)["sources"]) for call in model.calls
                          if "sources" in json.loads(call[-1].content)], [5, 5])
        self.assertEqual(len(model.calls), 3)  # two extractions and one merge
        provider.fetch.assert_not_awaited()

    def test_recruitment_subdomains_and_company_owned_site_are_labelled(self):
        for domain in ("zhiye.com", "mokahr.com", "hotjob.cn", "hotjob.com", "feishu.cn", "jobs.feishu.cn"):
            with self.subTest(domain=domain):
                page = {**base.PAGE, "content": base.TEXT.replace("公司：纸舟科技\n", ""),
                        "url": f"https://kunlunxin.{domain}/jobs/1", "site_name": domain}
                card = job_card(JobExtraction(job_title=base.PAGE["title"]), page)
                self.assertEqual((card["company"], card["company_inferred_from"]), ("kunlunxin", "domain"))
        page.update(url=base.URL, site_name="美团招聘")
        card = job_card(simple_job(page), page)
        self.assertEqual((card["company"], card["company_inferred_from"]), ("美团", "site_name"))
        page["content"] = "公司：明确公司\n" + page["content"]
        card = job_card(simple_job(page), page)
        self.assertEqual(card["company"], "明确公司")
        self.assertNotIn("company_inferred_from", card)

    def test_shared_domains_and_misleading_suffixes_do_not_invent_company(self):
        for domain in ("zhiye.com", "www.zhiye.com", "jobs.feishu.cn", "www.mokahr.com",
                       "kunlunxin.zhiye.com.evil.org", "nowcoder.com", "quanzhi.com"):
            with self.subTest(domain=domain):
                page = {**base.PAGE, "content": base.TEXT.replace("公司：纸舟科技\n", ""),
                        "url": f"https://{domain}/jobs/1", "site_name": "复旦大学就业服务中心"}
                card = job_card(simple_job(page), page)
                self.assertEqual(card["company"], "")
                self.assertNotIn("company_inferred_from", card)

    def test_title_normalization_removes_ids_but_keeps_role_qualifiers(self):
        expected = "ai产品经理实习生"
        for title in ("AI 产品经理实习生(J103757)", "AI产品经理实习生（J103322）",
                      "Ai产品经理实习生 (岗位编号：J103322)"):
            self.assertEqual(normalized_job_title(title), expected)
        for title in ("MEG星海计划-AI产品经理实习生(J98102)",
                      "AI产品经理实习生（软件方向）", "AI产品经理实习生（智能学习方向）"):
            self.assertNotEqual(normalized_job_title(title), expected)

    def test_institution_titles_fall_back_to_model_or_body_role(self):
        for title in ("复旦大学就业指导与生涯发展处", "人才就业中心", "某大学", "就业指导", "某招聘网"):
            with self.subTest(title=title):
                self.assertFalse(usable_title(title))
                page = {**base.PAGE, "title": title, "content": "AI产品经理实习生\n岗位职责\n负责调研"}
                self.assertEqual(job_card(JobExtraction(job_title=title), page)["job_title"], "AI产品经理实习生")
                self.assertEqual(job_card(JobExtraction(job_title="AI产品经理实习生"), page)["job_title"], "AI产品经理实习生")
                page["content"] = "岗位职责\n负责调研。\n任职要求\n本科。"
                self.assertEqual(job_card(JobExtraction(job_title=title), page)["job_title"], "")
        self.assertTrue(usable_title("大学就业中心产品经理实习生"))

    async def test_unrecoverable_institution_title_is_dropped(self):
        hits, extracted = reported_fixture()
        bad = hits[4]
        hits[4] = base.SearchHit(bad.title, bad.url, "公司：自然选择（深圳）智能有限公司\n岗位职责\n负责需求调研。\n任职要求\n本科及以上。", site_name=bad.site_name)
        result = await self.intel(providers=[base.ProviderStub(hits)], llm=base.StructuredStub(extracted)).sample_jobs("AI产品经理实习")
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["profile"]["sample_count"], 8)
        self.assertNotIn(bad.url, [row["url"] for row in result["profile"]["sources"]])

    async def test_fetch_markdown_is_unescaped_before_fields_and_evidence_validation(self):
        title = r"AI产品经理实习\-日常实习"
        body = "公司：纸舟\\#科技\n岗位：" + title + "\n工作地点：深圳\\/北京\n薪资：200元\\/天\n岗位职责\n负责需求调研和产品设计。\n任职要求\n熟悉 C\\# 和 Python，能够完成检索问答评估。\n本科及以上，有产品实习经历优先。"
        model = base.StructuredStub(JobExtraction(
            is_job=True, company="纸舟#科技", job_title="AI产品经理实习-日常实习",
            location="深圳/北京", salary="200元/天",
            skills=[Evidence(text="C#", quote="熟悉 C# 和 Python"),
                    Evidence(text="虚构技能", quote="不存在的证据")]))
        fetched = base.FetchedPage(body, title, base.URL, "deepseek")
        with patch.object(web, "read_job_url", AsyncMock(side_effect=web.WebResearchError("unavailable"))):
            result = await self.intel(providers=[base.ProviderStub(page=fetched)], llm=model).read_job_url(base.URL)
        self.assertEqual(result["status"], "ok", result)
        card = result["card"]
        self.assertEqual((card["company"], card["job_title"], card["location"], card["salary"]),
                         ("纸舟#科技", "AI产品经理实习-日常实习", "深圳/北京", "200元/天"))
        self.assertEqual(card["skills"], [{"text": "C#", "quote": "熟悉 C# 和 Python"}])
        self.assertEqual(card["raw_text"], body)
        self.assertEqual(unescape_markdown(r"C:\new\folder\n\u4e00"), r"C:\new\folder\n\u4e00")

    async def test_three_and_four_candidates_generate_low_sample_and_cache(self):
        for n in (3, 4):
            with self.subTest(n=n):
                hits, extracted = base.sample_fixture()
                provider = base.ProviderStub(hits[:n])
                intel = self.intel(providers=[provider], llm=base.StructuredStub(SampleExtraction(jobs=extracted.jobs[:n])))
                result = await intel.sample_jobs(f"产品经理{n}")
                self.assertEqual(result["status"], "ok", result)
                profile = result["profile"]
                self.assertEqual(profile["sample_count"], n)
                self.assertTrue(profile["low_sample"])
                self.assertEqual(profile["sample_note"], f"仅基于 {n} 条岗位")
                info = background.completed_info({"role_profile": {"status": "pending"}}, result)
                self.assertEqual(info["role_profile"]["status"], "ready")
                context = integration.market_context({"jd_info": info})
                self.assertIn(f"仅基于 {n} 条岗位", context)
                self.assertIn("不得变成简历事实", context)
                cached = await intel.sample_jobs(f"产品经理{n}")
                self.assertTrue(cached["cached"])
                self.assertEqual(cached["profile"], profile)
                self.assertEqual(provider.search.await_count, 3)

    async def test_three_or_four_jobs_after_validation_still_generate(self):
        for n in (3, 4):
            with self.subTest(n=n):
                hits, extracted = base.sample_fixture()
                for i, job in enumerate(extracted.jobs):
                    job.is_job = i < n
                result = await self.intel(providers=[base.ProviderStub(hits)], llm=base.StructuredStub(extracted)).sample_jobs(f"产品{n}")
                self.assertEqual(result["status"], "ok", result)
                self.assertEqual(result["profile"]["sample_count"], n)
                self.assertTrue(result["profile"]["low_sample"])

    async def test_under_three_candidates_skip_model(self):
        hits, extracted = base.sample_fixture()
        model = base.StructuredStub(extracted)
        result = await self.intel(providers=[base.ProviderStub(hits[:2])], llm=model).sample_jobs("产品经理")
        self.assertEqual(result["status"], "insufficient")
        self.assertIn("2 条", result["message"])
        self.assertEqual(model.calls, [])

    async def test_under_three_after_normalized_dedup_is_insufficient(self):
        hits, extracted = reported_fixture()
        result = await self.intel(providers=[base.ProviderStub(hits[1:4])],
                                  llm=base.StructuredStub(SampleExtraction(jobs=extracted.jobs[1:4]))).sample_jobs("AI产品经理实习")
        self.assertEqual(result["status"], "insufficient", result)
        self.assertIn("2 条", result["message"])

    async def test_unknown_company_uses_domain_for_dedup_and_frequency(self):
        hits, extracted = reported_fixture()
        first, second = hits[7], hits[8]
        third_url = "https://nowcoder.com/jobs/another"
        hits = [first, second, base.SearchHit(first.title, third_url, first.content),
                base.SearchHit("AI产品经理实习生（算法方向）", "https://nowcoder.com/jobs/algorithm",
                               first.content.replace(first.title, "AI产品经理实习生（算法方向）"))]
        jobs = [extracted.jobs[7], extracted.jobs[8], extracted.jobs[7].model_copy(update={"url": third_url}),
                extracted.jobs[7].model_copy(update={"url": hits[3].url, "job_title": hits[3].title})]
        result = await self.intel(providers=[base.ProviderStub(hits)], llm=base.StructuredStub(SampleExtraction(jobs=jobs))).sample_jobs("AI产品经理实习")
        self.assertEqual(result["status"], "ok", result)
        profile = result["profile"]
        self.assertEqual((profile["sample_count"], profile["company_count"]), (3, 2))
        self.assertTrue(all(row["company"] == "" for row in profile["sources"]))
        self.assertEqual((profile["skills"][0]["count"], profile["skills"][0]["total"]), (2, 2))


if __name__ == "__main__":
    unittest.main()
