"""15d: reported short labels + synthetic pages; no live provider/model calls."""
import asyncio
import copy
import json
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

import test_batch15a_job_intel as base
from app.agents import resume_graph as graph
from app.services.job_intel import background, clustering, service
from app.services.job_intel.extraction import (
    Evidence, JobExtraction, SampleExtraction, SampleJob, job_card, usable_title,
)
from app.services.role_profile import direction_focus


# First six are the reported labels. Remaining variants/pages are synthetic
# fixtures to reproduce the reported twelve singleton duties across ten jobs.
BACKEND_DUTIES = [
    "公有云核心系统后端开发", "Java后端开发", "开发Java WEB应用前后端",
    "协助核心产品后端开发与迭代", "接口开发与数据库设计优化", "业务模块设计开发与Bug修正",
    "服务端功能开发", "后端服务维护", "后端业务功能实现", "后端接口维护",
    "参与后端模块开发", "后端业务系统迭代",
]
MEDIA_TOOLS = ["剪映/PR/AE/PS", "剪映/PR/达芬奇剪辑", "Canva/PS设计"]


def fixture(media=False, repeated_company=False):
    hits, jobs = [], []
    for i in range(10):
        company = f"样例企业{0 if repeated_company and i == 1 else i}"
        title = ("新媒体运营实习生" if media else "Java后端开发实习") + ("（平台方向）" if i == 1 else "")
        duties = ([f"新媒体内容运营与发布{i}"] if media else
                  BACKEND_DUTIES[i:i + 1] + (BACKEND_DUTIES[10 + i:11 + i] if i < 2 else []))
        skills = (MEDIA_TOOLS[i:i + 1] if media else
                  [name for name, count in [("MySQL", 4), ("Java", 3), ("Spring Boot", 3), ("MyBatis", 2), ("Redis", 2)] if i < count])
        bonuses = ["相关专业优先"] if media and i < 3 else []
        body = f"公司：{company}\n岗位：{title}\n岗位职责\n" + "\n".join(duties) + "\n任职要求\n" + "\n".join(skills) + "\n加分项\n" + "\n".join(bonuses)
        url = f"https://jobs.example.org/{i}"
        hits.append(base.SearchHit(title, url, body))
        jobs.append(SampleJob(url=url, is_job=True, company=company, job_title=title,
                              **{field: [Evidence(text=text, quote=text) for text in values]
                                 for field, values in [("responsibilities", duties), ("skills", skills), ("bonuses", bonuses)]}))
    return hits, SampleExtraction(jobs=jobs)


def partition(payload):
    classes = []
    for field, rows in payload.items():
        if field == "responsibilities" and rows:
            label = "内容运营" if "新媒体" in rows[0]["text"] else "后端开发"
            classes.append({"field": field, "label": label, "members": [r["id"] for r in rows]})
        elif field == "skills" and rows and rows[0]["text"] in MEDIA_TOOLS:
            classes.append({"field": field, "label": "剪辑与设计工具", "members": [r["id"] for r in rows]})
        else:
            classes += [{"field": field, "label": r["text"], "members": [r["id"]]} for r in rows]
    return {"classes": classes}


class ModelStub:
    def __init__(self, extracted, transform=None, error=None, hang=False):
        self.extracted, self.transform, self.error, self.hang = extracted, transform, error, hang
        self.calls = []
        self.cancelled = False

    def with_structured_output(self, schema):
        parent = self

        class Chain:
            async def ainvoke(self, messages):
                payload = json.loads(messages[-1].content)
                parent.calls.append((schema, payload))
                if schema is SampleExtraction:
                    urls = {row["url"] for row in payload["sources"]}
                    return SampleExtraction(jobs=[job for job in parent.extracted.jobs if job.url in urls])
                if parent.hang:
                    try:
                        await asyncio.Event().wait()
                    finally:
                        parent.cancelled = True
                if parent.error:
                    raise parent.error
                result = partition(payload)
                return parent.transform(result) if parent.transform else result
        return Chain()


class MergeTests(unittest.IsolatedAsyncioTestCase):
    setUp = base.IntelTest.setUp
    intel = base.IntelTest.intel

    async def sample(self, *, media=False, repeated_company=False, **kwargs):
        hits, extracted = fixture(media, repeated_company)
        model = ModelStub(extracted, **kwargs)
        result = await self.intel(providers=[base.ProviderStub(hits)], llm=model).sample_jobs(
            "新媒体运营实习生" if media else "Java后端开发实习")
        self.assertEqual(result["status"], "ok", result)
        return result["profile"], model

    async def test_java_synonyms_merge_and_skills_keep_real_frequencies(self):
        profile, model = await self.sample()
        self.assertEqual(profile["merge_status"], "merged")
        self.assertEqual(len(profile["responsibilities"]), 1)
        duty = profile["responsibilities"][0]
        self.assertEqual((duty["text"], duty["count"], duty["total"]), ("后端开发", 10, 10))
        self.assertEqual(len(duty["members"]), 12)
        self.assertEqual(len(duty["urls"]), 10)
        self.assertEqual(len(duty["evidence"]), 12)  # two distinct quotes on one URL survive
        self.assertEqual({e["quote"] for e in duty["evidence"]}, set(BACKEND_DUTIES))
        self.assertEqual([(r["text"], r["count"]) for r in profile["skills"]],
                         [("MySQL", 4), ("Java", 3), ("Spring Boot", 3), ("MyBatis", 2), ("Redis", 2)])
        self.assertEqual([schema for schema, _ in model.calls], [SampleExtraction, SampleExtraction, clustering.Clusters])

    async def test_media_tools_keep_names_and_major_bonus(self):
        profile, _ = await self.sample(media=True)
        self.assertEqual(profile["merge_status"], "merged")
        self.assertEqual([len(profile[f]) for f in ("responsibilities", "skills", "bonuses")], [1, 1, 1])
        self.assertEqual(profile["responsibilities"][0]["count"], 10)
        tools = profile["skills"][0]
        self.assertEqual(tools["count"], 3)
        self.assertEqual(tools["members"], ["剪映", "PR", "AE", "PS", "达芬奇", "Canva"])
        self.assertEqual({e["text"] for e in tools["evidence"]}, set(MEDIA_TOOLS))
        self.assertEqual((profile["bonuses"][0]["text"], profile["bonuses"][0]["count"]), ("相关专业优先", 3))

    async def test_one_company_has_one_vote_and_keeps_every_quote(self):
        profile, _ = await self.sample(repeated_company=True)
        duty = profile["responsibilities"][0]
        self.assertEqual((profile["sample_count"], profile["company_count"]), (10, 9))
        self.assertEqual((duty["count"], duty["total"], len(duty["urls"]), len(duty["evidence"])), (9, 9, 10, 12))
        self.assertEqual(profile["skills"][0]["count"], 3)

    async def test_merge_payload_is_only_short_text_ids_and_fields(self):
        _, model = await self.sample()
        payload = model.calls[-1][1]
        self.assertEqual(set(payload), set(clustering.FIELDS))
        for rows in payload.values():
            for row in rows:
                self.assertEqual(set(row), {"id", "text"})
                self.assertLessEqual(len(row["text"]), 40)
        self.assertNotIn("https://", json.dumps(payload))
        self.assertNotIn("样例企业", str(payload))

    async def test_novel_label_rejects_whole_merge(self):
        def inject(result):
            result["classes"][0]["label"] = "Kafka后端开发"
            return result
        profile, _ = await self.sample(transform=inject)
        self.assertEqual(profile["merge_status"], "fallback")
        self.assertEqual(len(profile["responsibilities"]), 12)
        self.assertTrue(all(row["count"] == 1 for row in profile["responsibilities"]))
        self.assertNotIn("Kafka", str(profile))

    async def test_merge_error_does_not_fail_profile(self):
        profile, _ = await self.sample(error=RuntimeError("private error"))
        self.assertEqual(profile["merge_status"], "fallback")
        self.assertEqual(len(profile["responsibilities"]), 12)
        self.assertNotIn("private error", str(profile))

    async def test_timeout_cancels_merge_and_returns_unmerged_profile(self):
        with patch.object(service, "CALL_TIMEOUT", 0.02):
            profile, model = await self.sample(hang=True)
        self.assertTrue(model.cancelled)
        self.assertEqual(profile["merge_status"], "fallback")
        self.assertEqual(profile["skills"][0]["count"], 4)

    async def test_merge_leaves_time_for_fallback_inside_total_budget(self):
        hits, extracted = fixture()
        model = ModelStub(extracted, hang=True)
        intel = self.intel(providers=[base.ProviderStub(hits)], llm=model)
        with patch.object(intel, "_providers", AsyncMock(return_value=hits)), patch.object(service, "SAMPLE_TIMEOUT", 0.3):
            # No network/rate-limit delays; merger uses only the remaining
            # budget minus the return margin, not a fresh fifteen seconds.
            result = await intel.sample_jobs("Java后端开发实习")
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["profile"]["merge_status"], "fallback")
        self.assertTrue(model.cancelled)

    async def test_cached_merged_profile_does_not_call_model_again(self):
        hits, extracted = fixture()
        model = ModelStub(extracted)
        intel = self.intel(providers=[base.ProviderStub(hits)], llm=model)
        first = await intel.sample_jobs("Java后端开发实习")
        second = await intel.sample_jobs("Java后端开发实习")
        self.assertTrue(second["cached"])
        self.assertEqual(first["profile"], second["profile"])
        self.assertEqual(len(model.calls), 3)

    def test_label_guard_rejects_new_chinese_names_tokens_and_requirements(self):
        for label, texts in [("飞书工具", ["剪映/PR/AE"]), ("JavaScript", ["Java"]),
                             ("SQL", ["MySQL"]), ("精通MySQL", ["了解MySQL"]),
                             ("三年后端开发", ["Java后端开发"]), ("分布式开发", ["后端开发"]),
                             ("剪辑工具", ["MySQL"]), ("剪辑工具", ["Programming"]),
                             ("剪辑与设计工具", ["剪映"]), ("快手运营", ["快速学习", "熟悉手工", "运营"]),
                             ("后端开发岗位核心职责概括标签", ["后端开发"])]:
            with self.subTest(label=label):
                self.assertFalse(clustering.supported_label(label, texts))
        self.assertTrue(clustering.supported_label("剪辑工具", ["剪映/PR/AE/达芬奇"]))
        self.assertTrue(clustering.supported_label("Java后端开发", ["Java WEB应用开发"]))

    def test_partition_rejects_missing_duplicate_cross_field_and_unknown_ids(self):
        entries = [{"id": 0, "field": "skills", "text": "Java"},
                   {"id": 1, "field": "responsibilities", "text": "后端开发"}]
        valid = {"classes": [{"field": e["field"], "label": e["text"], "members": [e["id"]]} for e in entries]}
        variants = [copy.deepcopy(valid) for _ in range(6)]
        variants[0]["classes"].pop()
        variants[1]["classes"][0]["members"] = [0, 0]
        variants[2]["classes"][0]["members"] = [0, 1]
        variants[3]["classes"][0]["members"] = [999]
        variants[4]["classes"][0]["members"] = [False]
        variants[5]["classes"][0]["members"] = ["0"]
        for value in variants:
            with self.assertRaises(ValueError):
                clustering.validate_clusters(value, entries)

    def test_one_bad_cluster_does_not_discard_the_valid_ones(self):
        # 真实模型常有一两类不合规（超长标签、重复编号、漏项）；只拆回这些类，合格的类保留。
        entries = [{"id": 0, "field": "skills", "text": "剪映、PR、AE、PS"},
                   {"id": 1, "field": "skills", "text": "PR、剪映剪辑与字幕包装"},
                   {"id": 2, "field": "skills", "text": "Excel"},
                   {"id": 3, "field": "skills", "text": "PPT"},
                   {"id": 4, "field": "bonuses", "text": "相关专业优先"}]
        value = {"classes": [
            {"field": "skills", "label": "剪辑工具", "members": [0, 1]},
            {"field": "skills", "label": "办公软件与数据整理工具的熟练使用", "members": [2, 3]},
        ]}
        classes = clustering.validate_clusters(value, entries)
        groups = sorted((c.field, c.label, c.members) for c in classes)
        self.assertIn(("skills", "剪辑工具", [0, 1]), groups)
        self.assertIn(("skills", "Excel", [2]), groups)
        self.assertIn(("skills", "PPT", [3]), groups)
        self.assertIn(("bonuses", "相关专业优先", [4]), groups)

    def test_company_title_uses_body_role_or_is_invalid(self):
        for company in ("天津开发区先特网络系统有限公司", "产品研发集团", "某科技研究院", "纸舟", "Java University"):
            self.assertFalse(usable_title(company, company))
            for body_role in ("Java后端开发实习", ""):
                page = {**base.PAGE, "title": company,
                        "content": f"公司：{company}\n{body_role}\n岗位职责\n后端开发\n任职要求\nMySQL"}
                card = job_card(JobExtraction(company=company, job_title=company), page)
                # With no actual title, a short duty must not be mistaken for a heading.
                self.assertEqual(card["job_title"], body_role)
        self.assertTrue(usable_title("大学就业中心产品经理实习生"))
        self.assertTrue(usable_title("天津开发区先特网络系统有限公司 Java开发实习"))

    async def test_invalid_company_named_sample_is_dropped(self):
        hits, extracted = fixture()
        company = "天津开发区先特网络系统有限公司"
        hits[0] = base.SearchHit(company, hits[0].url, f"公司：{company}\n岗位职责\n负责开发工作。\n任职要求\nMySQL")
        extracted.jobs[0] = SampleJob(url=hits[0].url, is_job=True, company=company, job_title=company)
        result = await self.intel(providers=[base.ProviderStub(hits)], llm=ModelStub(extracted)).sample_jobs("Java")
        self.assertEqual(result["profile"]["sample_count"], 9)
        self.assertNotIn(hits[0].url, [s["url"] for s in result["profile"]["sources"]])


class DirectionWordingTests(unittest.IsolatedAsyncioTestCase):
    async def reply(self, profile=None):
        state = graph._init_state()
        state["messages"] = [HumanMessage(content="我想投Java后端开发实习")]
        before = copy.deepcopy(state["collected_info"])
        cached = {"status": "ok", "profile": profile} if profile else None
        with patch.object(background, "cached_sample", return_value=cached), patch.object(graph, "run_triage") as triage:
            result = await graph.jd_input_node(state, object())
        triage.assert_not_called()
        self.assertEqual(state["collected_info"], before)
        self.assertNotIn("collected_info", result)
        return result["messages"][0].content

    async def test_direction_only_uses_handbook_without_inventing_experience(self):
        reply = await self.reply()
        self.assertIn("Java后端开发实习", reply)
        self.assertIn("实际用过的语言、框架或数据库", reply)
        self.assertIn("自己实现过的模块或接口", reply)
        self.assertNotIn("我会优先证明：后端", reply)
        self.assertNotIn("你已经", reply)

    async def test_ready_cached_profile_supplies_top_two_capabilities(self):
        reply = await self.reply({"source": "market_sample", "direction": "Java后端开发实习",
                                  "fetched_at": base.PAGE["fetched_at"], "sources": [],
                                  "skills": [{"text": "Redis", "count": 2}, {"text": "Java", "count": 3},
                                             {"text": "MySQL", "count": 4}], "responsibilities": []})
        self.assertIn("MySQL / Java 实战能力", reply)
        self.assertNotIn("Redis", reply)
        self.assertNotIn("岗位手册", reply)

    def test_pending_failed_stale_and_singletons_use_handbook(self):
        for profile in ({"status": "pending"}, {"status": "failed"}, {"direction": "数据分析"},
                        {"skills": [{"text": "Kubernetes", "count": 1}]}):
            info = {"role_profile": {"source": "market_sample", "skills": [{"text": "Kubernetes", "count": 5}], **profile}}
            reply = direction_focus(info, "Java后端开发实习")
            self.assertIn("岗位手册", reply)
            self.assertNotIn("Kubernetes", reply)

    def test_ready_duties_are_used_when_skills_have_no_frequent_items(self):
        reply = direction_focus({"role_profile": {"source": "market_sample", "status": "ready",
                                                  "responsibilities": [{"text": "后端开发", "count": 5}]}},
                                "Java后端开发实习")
        self.assertIn("后端开发 实战能力", reply)


if __name__ == "__main__":
    unittest.main()
