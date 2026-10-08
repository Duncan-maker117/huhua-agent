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
    def preserve(self, bullets, limits, **kwargs):
        collected = source()
        collected["projects"][0]["facts"] = [collected["projects"][0]["facts"][0], *limits]
        return preserve_item_limits(doc(bullets), {}, collected, item_ids=["p1"], **kwargs)

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

    def test_nonempty_quote_overrides_invented_negative_status_in_fact_text(self):
        result, _, fallbacks = self.preserve(["实现接口"], [
            {"id": "l", "kind": "status_limit", "text": "项目未上线，未做量化统计",
             "source_quote": "负责接口开发，并核对返回字段。"}])
        self.assertEqual(result, doc(["实现接口"]))
        self.assertEqual(fallbacks, [])

    def test_supported_quote_limit_survives_even_when_fact_text_omits_it(self):
        result, _, _ = self.preserve(["实现接口"], [
            {"id": "l", "kind": "action", "text": "完成接口开发",
             "source_quote": "实现接口，支付模块尚未接入真实交易。"}])
        self.assertEqual(result, doc(["实现接口；支付模块尚未接入真实交易"]))

    def test_legacy_missing_quote_retains_explicit_limit(self):
        for quote in ({}, {"source_quote": ""}):
            with self.subTest(quote=quote):
                result, _, _ = self.preserve(["实现接口"], [
                    {"id": "l", "kind": "action", "text": "支付接口尚未上线", **quote}])
                self.assertEqual(result, doc(["实现接口；支付接口尚未上线"]))

    def test_existing_prototype_marker_does_not_repeat_imported_action_paragraphs(self):
        limits = [
            {"id": "l1", "kind": "status_limit", "text": "个人项目 · 产品方案与原型实现",
             "source_quote": "个人项目 · 产品方案与原型实现"},
            {"id": "l2", "kind": "status_limit",
             "text": "负责产品方案与原型实现，将输入、预览和确认步骤放在同一页面，支持添加与删除条目。",
             "source_quote": "负责产品方案与原型实现，将输入、预览和确认步骤放在同一页面，支持添加与删除条目。"}]
        bullets = ["梳理输入信息，设计确认步骤（原型）"]
        result, _, fallbacks = self.preserve(bullets, limits)
        self.assertEqual(result, doc(bullets))
        self.assertEqual(fallbacks, [])

    def test_missing_phase_appends_only_an_intact_source_clause_once(self):
        limits = [
            {"id": "l1", "text": "这是交互原型，完成输入表单和确认页面，支持条目编辑。",
             "source_quote": "这是交互原型，完成输入表单和确认页面，支持条目编辑。"},
            {"id": "l2", "text": "负责产品方案与原型实现，将多个步骤放在同一页面。",
             "source_quote": "负责产品方案与原型实现，将多个步骤放在同一页面。"}]
        result, metadata, _ = self.preserve(["实现接口"], limits)
        self.assertEqual(result, doc(["实现接口；这是交互原型"]))
        self.assertEqual(metadata["bullets"]["p1"][0]["fact_ids"], ["a", "l1"])

    def test_phase_marker_never_discharges_distinct_negation_or_future_plan(self):
        result, _, _ = self.preserve(["完成交互原型"], [
            {"id": "l", "text": "这是交互原型，支付接口尚未上线，计划增加支付结果核对功能。",
             "source_quote": "这是交互原型，支付接口尚未上线，计划增加支付结果核对功能。"}])
        self.assertEqual(result, doc(["完成交互原型；支付接口尚未上线；计划增加支付结果核对功能"]))

    def test_existing_limit_with_same_action_and_object_is_not_duplicated(self):
        result, _, fallbacks = self.preserve(["实现接口，支付模块未上线"], [
            {"id": "l", "text": "支付模块尚未上线", "source_quote": "支付模块尚未上线"}])
        self.assertEqual(result, doc(["实现接口，支付模块未上线"]))
        self.assertEqual(fallbacks, [])

    def test_different_objects_remain_separate_limits(self):
        result, _, _ = self.preserve(["支付模块未上线"], [
            {"id": "l", "text": "搜索模块尚未上线", "source_quote": "搜索模块尚未上线"}])
        self.assertEqual(result, doc(["支付模块未上线；搜索模块尚未上线"]))

    def test_comma_separated_subject_and_conditional_scope_survive(self):
        result, _, _ = self.preserve(["实现接口"], [
            {"id": "l", "text": "支付模块，尚未上线；若审批通过，计划部署正式环境。",
             "source_quote": "支付模块，尚未上线；若审批通过，计划部署正式环境。"}])
        self.assertEqual(result, doc(["实现接口；支付模块，尚未上线；若审批通过，计划部署正式环境"]))

    def test_chained_and_postposed_conditions_are_not_detached_from_plans(self):
        for statement in ("若预算批准，且接口验收通过，计划部署正式环境",
                          "计划部署正式环境，前提是预算批准"):
            with self.subTest(statement=statement):
                result, _, _ = self.preserve(["实现接口"], [
                    {"id": "l", "text": statement, "source_quote": statement}])
                self.assertEqual(result, doc(["实现接口；" + statement]))

    def test_condition_inside_clause_keeps_full_plan_sentence(self):
        statement = "项目若通过验收，计划部署"
        result, _, _ = self.preserve(["实现接口"], [
            {"id": "l", "text": statement, "source_quote": statement}])
        self.assertEqual(result, doc(["实现接口；" + statement]))

    def test_postposed_waiting_or_approval_hint_keeps_full_plan_sentence(self):
        statement = "计划部署，但要等预算批准"
        result, _, _ = self.preserve(["实现接口"], [
            {"id": "l", "text": statement, "source_quote": statement}])
        self.assertEqual(result, doc(["实现接口；" + statement]))

    def test_nonaffirmative_prototype_mention_cannot_discharge_current_stage(self):
        for statement in ("计划开发交互原型", "并非原型，属于正式产品"):
            with self.subTest(statement=statement):
                result, _, _ = self.preserve([statement], [
                    {"id": "l", "text": "这是交互原型", "source_quote": "这是交互原型"}])
                self.assertEqual(result, doc([statement + "；这是交互原型"]))

    def test_mock_clause_keeps_its_object_and_omits_unrelated_narrative(self):
        result, _, _ = self.preserve(["登录模块使用 mock 数据"], [
            {"id": "l", "text": "我整理按钮文案，支付结果使用 mock 数据，支持页面切换和条目编辑。",
             "source_quote": "我整理按钮文案，支付结果使用 mock 数据，支持页面切换和条目编辑。"}])
        self.assertEqual(result, doc(["登录模块使用 mock 数据；支付结果使用 mock 数据"]))

    def test_local_scope_and_inactive_fact_boundaries_remain_intact(self):
        limits = [
            {"id": "l", "text": "支付模块尚未上线", "source_quote": "支付模块尚未上线", "status": "active"},
            {"id": "d", "text": "计划采用旧框架", "source_quote": "计划采用旧框架", "status": "deleted"},
            {"id": "s", "text": "准备迁移旧数据库", "source_quote": "准备迁移旧数据库", "status": "superseded"}]
        result, _, _ = self.preserve(["第一条保持不动", "实现接口"], limits,
                                     bullet_indices={"p1": {1}})
        self.assertEqual(result, doc(["第一条保持不动", "实现接口；支付模块尚未上线"]))
        skipped, _, fallbacks = self.preserve(["实现接口"], limits, bullet_indices={"p1": set()})
        self.assertEqual(skipped, doc(["实现接口"]))
        self.assertEqual(fallbacks, [])

    def test_summary_text_does_not_gain_verified_hash_from_unsupported_fact_text(self):
        result, metadata, _ = self.preserve(["主导实现整个系统"], [
            {"id": "overstated", "text": "主导实现整个系统", "source_quote": "我核对接口返回字段"},
            {"id": "l", "text": "项目尚未上线", "source_quote": "项目尚未上线"}])
        self.assertEqual(result, doc(["主导实现整个系统；项目尚未上线"]))
        self.assertEqual(metadata["bullets"]["p1"][0]["text_hash"], "")
        self.assertEqual(metadata["bullets"]["p1"][0]["fact_ids"], ["l"])


if __name__ == "__main__":
    unittest.main()
