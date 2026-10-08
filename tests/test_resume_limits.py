"""Status restrictions survive uncited writer output, local edits and trimming."""
import asyncio
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.agents.resume_writer import run_resume_writer  # noqa: E402
from app.agents.tailor_pipeline import run_tailor_pipeline  # noqa: E402
from app.services.resume_limits import preserve_item_limits  # noqa: E402


def source():
    return {"projects": [{"item_id": "p1", "name": "接口项目", "facts": [
        {"id": "a", "text": "实现接口", "source_quote": "实现接口", "kind": "action", "status": "active"},
        {"id": "l", "text": "这是未上线原型", "source_quote": "这是未上线原型", "kind": "status_limit", "status": "active"},
        {"id": "d", "text": "计划使用旧框架", "kind": "status_limit", "status": "deleted"}]}]}


def doc(bullets):
    return {"projects": [{"item_id": "p1", "name": "接口项目", "polished_bullets": bullets}]}


class Model:
    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        return {"match_plan": {"experience_plan": [{"item_id": "p1", "treatment": "keep"}]},
                "writer": {"items": [{"item_id": "p1", "section": "projects", "bullets": [
                    {"text": "实现接口", "fact_ids": ["a"]}]}]}}


class ResumeLimitsTest(unittest.TestCase):
    def test_writer_cannot_omit_uncited_same_item_limit(self):
        original = source()
        result = asyncio.run(run_resume_writer(original, {}, Model()))
        bullet = result["resume_data"]["projects"][0]["polished_bullets"][0]
        self.assertEqual(bullet, "实现接口；这是未上线原型")
        self.assertEqual(result["resume_meta"]["bullets"]["p1"][0]["fact_ids"], ["a", "l"])
        self.assertEqual(result["guard_fallbacks"][0]["reason"], "missing_item_status_limit")
        self.assertEqual(original, source())

    def test_local_edit_keeps_unrelated_bullets_and_items(self):
        data = doc(["第一条不动", "第二条要改"])
        data["projects"].append({"item_id": "p2", "polished_bullets": ["无关项目"]})
        result = asyncio.run(run_resume_writer(source(), {}, Model(), current_data=data,
            scope="bullet", targets=["/projects/0/polished_bullets/1"]))
        self.assertEqual(result["resume_data"]["projects"][0]["polished_bullets"],
                         ["第一条不动", "实现接口；这是未上线原型"])
        self.assertEqual(result["resume_data"]["projects"][1], data["projects"][1])

    def test_legacy_action_classification_does_not_erase_explicit_limit(self):
        collected = source()
        collected["projects"][0]["facts"][1]["kind"] = "action"
        result = asyncio.run(run_resume_writer(collected, {}, Model()))
        self.assertIn("未上线原型", result["resume_data"]["projects"][0]["polished_bullets"][0])

    def test_compression_retains_limit_without_restoring_deleted_bullet(self):
        data = doc(["实现接口", "这是未上线原型"])
        meta = {"bullets": {"p1": [{"text_hash": hashlib.sha256(text.encode()).hexdigest(), "fact_ids": [fid]}
                                   for text, fid in zip(data["projects"][0]["polished_bullets"], ["a", "l"])]}}
        state = {"resume_data": deepcopy(data), "resume_meta": meta, "collected_info": source()}
        written = {"resume_data": data, "resume_meta": meta, "match_plan": {
            "experience_plan": [{"item_id": "p1", "treatment": "keep"}]}}
        seen = []

        def measure(data, constraints):
            seen.append(deepcopy(data))
            return {"pages": 2 if len(seen) == 1 else 1, "within_page_limit": len(seen) > 1}

        with patch("app.agents.tailor_pipeline.run_resume_writer", return_value=written), \
                patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measure):
            result = asyncio.run(run_tailor_pipeline(state, data, object()))
        self.assertEqual(result["resume_data"]["projects"][0]["polished_bullets"], ["实现接口；这是未上线原型"])
        self.assertEqual(seen[-1], result["resume_data"])
        self.assertEqual(result["resume_meta"]["bullets"]["p1"][0]["fact_ids"], ["a", "l"])
        self.assertEqual(result["guard_fallbacks"][0]["reason"], "compression_preserved_status_limit")

    def test_existing_limit_not_duplicated_and_stale_meta_not_promoted(self):
        data = doc(["手工未核对正文"])
        revised, meta, _ = preserve_item_limits(data, {}, source(), item_ids=["p1"])
        self.assertEqual(meta["bullets"]["p1"][0]["text_hash"], "")
        twice, _, fallbacks = preserve_item_limits(revised, meta, source(), item_ids=["p1"])
        self.assertEqual(twice, revised)
        self.assertEqual(fallbacks, [])
        self.assertNotIn("旧框架", str(twice))


if __name__ == "__main__":
    unittest.main()
