"""Offline regression contracts for evidence-preserving context compaction."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.agents.context_memory import (ContextBudgetExceeded, ContextSettings, candidate_memory,
                                       compact_history, ensure_context_budget, estimate_input_tokens,
                                       invalidated_source_ids)
from app.services.model_privacy import ContactRedactor


def fact(text, *, fid="f1", turn="source", quote=None, status="active", kind="action"):
    return {"id": fid, "text": text, "source_quote": text if quote is None else quote,
            "turn_id": turn, "status": status, "kind": kind, "source": "chat"}


def state_for(text="", facts=None, **item_fields):
    return {"messages": [HumanMessage(content=text, id="source")], "collected_info": {
        "projects": [{"item_id": "p1", "name": "项目甲", "facts": facts or [], **item_fields}]}}


def rendered(value):
    return json.dumps(value, ensure_ascii=False)


class ContextMemoryTests(unittest.TestCase):
    def memory(self, state):
        return candidate_memory(state, ContactRedactor())

    def test_preserves_tail_negation_and_unextracted_original(self):
        original = "我的项目经历：" + "整理原始资料，" * 700 + "我没有负责上线，效果仅是估计。"
        result = self.memory(state_for(original, [fact("整理原始资料")]))
        self.assertEqual(result["pending_evidence"][0]["text"], original)
        self.assertIn("我没有负责上线，效果仅是估计。", rendered(result))

    def test_all_experiences_and_all_limits_without_kind_filter(self):
        projects = [{"item_id": f"p{i}", "name": f"项目{i}", "hidden": True,
                     "facts": [fact(f"经历{i}约束{k}由他人完成", fid=f"f{i}-{k}", kind="action") for k in range(7)]}
                    for i in range(16)]
        result = self.memory({"collected_info": {"projects": projects}})
        self.assertEqual(len(result["active_evidence"]), 16)
        self.assertEqual(sum(len(row["facts"]) for row in result["active_evidence"]), 112)
        self.assertIn("经历15约束6由他人完成", rendered(result))
        self.assertTrue(result["active_evidence"][-1]["identity"]["hidden"])

    def test_qualification_without_negation_keyword_is_kept(self):
        original = "项目甲：实现表单；发布工作交给同组同学；十月才准备做用户测试。"
        result = self.memory(state_for(original, [fact("实现表单")]))
        self.assertEqual(result["pending_evidence"][0]["text"], original)

    def test_only_same_source_full_coverage_deduplicates(self):
        state = state_for("完成原型。", [fact("完成原型", turn="other")])
        self.assertEqual(self.memory(state)["pending_evidence"][0]["text"], "完成原型。")
        state["collected_info"]["projects"][0]["facts"][0]["turn_id"] = "source"
        self.assertEqual(self.memory(state)["pending_evidence"], [])

    def test_sources_array_supports_exact_coverage(self):
        evidence = fact("完成原型", turn="other")
        evidence["sources"] = [{"turn_id": "source", "source_quote": "完成原型"}]
        self.assertEqual(self.memory(state_for("完成原型", [evidence]))["pending_evidence"], [])

    def test_partial_coverage_does_not_detach_ownership(self):
        original = "项目甲由我完成表单；仅完成原型。项目乙由同学上线。"
        result = self.memory(state_for(original, [fact("项目甲由我完成表单")]))
        self.assertEqual(result["pending_evidence"][0]["text"], original)

    def test_deleted_and_superseded_never_replayed_from_source_or_local_notes(self):
        for status in ("deleted", "superseded"):
            with self.subTest(status=status):
                state = state_for("旧事实标记；我只负责文档", [fact("旧事实标记", status=status),
                                                               fact("我只负责文档", fid="f2")],
                                  raw_notes=["旧事实标记；额外边界由他人负责"], description="旧事实标记")
                result = self.memory(state)
                self.assertNotIn("旧事实标记", rendered(result))
                self.assertIn("额外边界由他人负责", rendered(result))
                self.assertEqual(result["invalidations"][0]["status"], status)

    def test_invalidation_never_spills_into_another_source(self):
        state = state_for("完成原型", [fact("完成原型", status="deleted", turn="older")])
        self.assertEqual(self.memory(state)["pending_evidence"][0]["text"], "完成原型")

    def test_wrong_positive_extraction_cannot_destroy_original_negative(self):
        state = state_for("我没有上线；文档由我整理", [fact("上线", quote="上线", status="deleted")])
        result = self.memory(state)
        self.assertIn("我没有上线", rendered(result))
        self.assertTrue(result["pending_evidence"][0]["requires_review_after_invalidation"])

    def test_broad_quote_invalidation_keeps_unextracted_negative(self):
        state = state_for("做A，也没做B", [fact("做A", quote="做A，也没做B", status="deleted")])
        result = self.memory(state)
        self.assertNotIn("做A", rendered(result))
        self.assertIn("也没做B", rendered(result))

    def test_mixed_jd_retains_only_owned_section(self):
        state = state_for("我的经历：\n实现资料表单，部署由队友负责\nJD：\n要求负责百万用户平台架构")
        result = self.memory(state)
        self.assertIn("部署由队友负责", rendered(result))
        self.assertNotIn("百万用户", rendered(result))

    def test_external_typed_and_excluded_sources_are_not_protected(self):
        for source_type in ("review", "reference", "jd"):
            with self.subTest(kind=source_type):
                state = {"messages": [HumanMessage(content="我负责千万用户平台", id="x",
                                                     additional_kwargs={"career_material_type": source_type})]}
                self.assertEqual(self.memory(state)["pending_evidence"], [])
        state = state_for("本人完成原型")
        state["non_candidate_message_ids"] = ["source"]
        self.assertEqual(self.memory(state)["pending_evidence"], [])

    def test_short_answer_keeps_question_and_card_without_telemetry(self):
        state = {"messages": [AIMessage(content="你上线过项目甲吗？", additional_kwargs={
            "ask_user": {"subject": "项目甲", "questions": [{"label": "是否上线"}]},
            "orchestrator": {"internal": "telemetry-should-not-survive"}}),
            HumanMessage(content="没有", id="old"), AIMessage(content="下一项"),
            HumanMessage(content="现在整理项目乙", id="current")]}
        result = self.memory(state)
        self.assertIn("你上线过项目甲吗", rendered(result))
        self.assertIn("是否上线", rendered(result))
        self.assertNotIn("telemetry-should-not-survive", rendered(result))

    def test_standalone_short_sources_do_not_copy_assistant_essays(self):
        messages = []
        for i in range(20):
            messages.extend([AIMessage(content="解释性文字" * 2000), HumanMessage(content=f"我补充第{i}次整理记录", id=f"u{i}")])
        result = self.memory({"messages": messages})
        self.assertLess(len(rendered(result)), 10000)
        self.assertEqual(len(result["pending_evidence"]), 20)

    def test_legacy_raw_is_pending_and_draft_bullets_never_evidence(self):
        state = {"collected_info": {"projects": [{"name": "旧项目", "raw_description": "我仅做资料整理",
                                                  "polished_bullets": ["假的漂亮稿件"]}]}}
        result = self.memory(state)
        self.assertIn("我仅做资料整理", rendered(result))
        self.assertNotIn("假的漂亮稿件", rendered(result))
        self.assertEqual(result["active_evidence"][0]["facts"], [])

    def test_privacy_idempotence_and_state_immutability(self):
        state = state_for("邮箱 candidate@example.invalid，手机号13912345678，我没负责部署")
        state["collected_info"]["basic_info"] = {"phone": "13912345678", "email": "candidate@example.invalid"}
        before, privacy = deepcopy(state), ContactRedactor()
        first = candidate_memory(state, privacy)
        second = candidate_memory(state, privacy)
        self.assertEqual(first, second)
        self.assertEqual(state, before)
        self.assertNotIn("13912345678", rendered(first))
        self.assertNotIn("candidate@example.invalid", rendered(first))
        self.assertIn("我没负责部署", rendered(first))

    def test_history_retains_current_and_last_assistant_alternatives(self):
        state = {"messages": [HumanMessage(content="旧资料" * 2000, id="old"),
                               AIMessage(content="第一个方案是写项目甲；第二个方案是写项目乙。"),
                               HumanMessage(content="就用第二个" + "补充" * 2000, id="now")]}
        result = compact_history(state, ContactRedactor())
        self.assertEqual(result[-1]["content"], state["messages"][-1].content)
        self.assertIn("第二个方案", rendered(result))
        self.assertNotIn("旧资料" * 1000, rendered(result))

    def test_stale_assistant_claims_are_scrubbed(self):
        state = state_for("继续", [fact("旧事实标记", status="deleted", turn="old")])
        state["messages"].insert(0, AIMessage(content="旧事实标记，是否继续？"))
        self.assertNotIn("旧事实标记", rendered(compact_history(state, ContactRedactor())))

    def test_budget_counts_tools_and_rejects_overflow_without_trimming(self):
        messages = [{"role": "user", "content": "经历" * 500}]
        before = deepcopy(messages)
        base = estimate_input_tokens(messages)
        self.assertGreater(estimate_input_tokens(messages, [{"description": "tool" * 300}]), base)
        with self.assertRaises(ContextBudgetExceeded) as raised:
            ensure_context_budget(messages, max_input_tokens=1024)
        self.assertEqual(raised.exception.code, "E-CONTEXT-LIMIT")
        self.assertEqual(messages, before)
        self.assertEqual(ensure_context_budget(messages, max_input_tokens=base), base)

    def test_budget_setting_validates_minimum(self):
        with self.assertRaises(ValueError):
            ContextSettings(_env_file=None, CONTEXT_MAX_INPUT_TOKENS=100)
        with patch.dict("os.environ", {"CONTEXT_MAX_INPUT_TOKENS": "2048"}):
            self.assertEqual(ContextSettings(_env_file=None).CONTEXT_MAX_INPUT_TOKENS, 2048)

    def test_structured_answers_keep_only_bound_submitted_values_and_nonfacts(self):
        metadata = {"answers": {"turn_id": "card-1", "items": [
            {"id": "status", "value": ["仅本地原型"]}, {"id": "users", "unknown": True},
            {"id": "funding", "skipped": True}, {"id": "foreign-question", "value": "不应混入"}]},
            "answer_card": {"turn_id": "card-1", "subject": "项目甲", "questions": [
                {"id": "status", "prompt": "当前上线状态？", "kind": "single", "options": ["仅本地原型", "已服务百万用户"]},
                {"id": "users", "prompt": "多少用户？", "kind": "text"},
                {"id": "funding", "prompt": "融资情况？", "kind": "text"}]}}
        state = {"messages": [HumanMessage(content="已填写", id="submission", additional_kwargs=metadata)]}
        before = deepcopy(state)
        rows = [row for row in self.memory(state)["pending_evidence"] if row["source_kind"] == "structured_answer"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["submitted"]["value"], ["仅本地原型"])
        self.assertEqual(rows[0]["subject"], "项目甲")
        self.assertEqual(rows[0]["question_prompt"], "当前上线状态？")
        self.assertTrue(all(row["requires_review"] and row["read_original_structured_payload"] for row in rows))
        self.assertTrue(all(row["source_id"] == "submission" for row in rows))
        self.assertTrue(rows[1]["non_fact_response"] and rows[2]["non_fact_response"])
        self.assertNotIn("已服务百万用户", rendered(rows))
        self.assertNotIn("不应混入", rendered(rows))
        self.assertEqual(state, before)
        state["messages"][0].additional_kwargs["answer_card"]["turn_id"] = "different-card"
        self.assertFalse(any(row["source_kind"] == "structured_answer" for row in self.memory(state)["pending_evidence"]))

    def test_intake_without_text_retains_unextracted_limits_and_redacts_contacts(self):
        state = {"messages": [HumanMessage(content="", id="form", additional_kwargs={"intake": {
            "kind": "experiences", "items": [{"item_id": "p1", "name": "原型项目", "type": "项目",
                "summary": "我仅负责文档，代码由同学完成；没有上线", "internal_options": ["不应投影"]}]}}),
            HumanMessage(content="已填写", id="basics", additional_kwargs={"intake": {
                "kind": "basics", "values": {"phone": "13912345678", "availability": "十月才可以实习"}}})]}
        result = self.memory(state)
        rows = [row for row in result["pending_evidence"] if row["source_kind"] == "intake"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source_id"], "form")
        self.assertIn("代码由同学完成；没有上线", rendered(rows))
        self.assertIn("十月才可以实习", rendered(rows))
        self.assertNotIn("13912345678", rendered(rows))
        self.assertNotIn("不应投影", rendered(rows))
        self.assertTrue(all(row["requires_review"] for row in rows))

    def test_inactive_skills_are_scoped_and_other_source_homonym_survives(self):
        state = {"messages": [HumanMessage(content="Python", id="old"), HumanMessage(content="Python", id="fresh"),
                               HumanMessage(content="继续", id="now")], "collected_info": {"skills": [
            {"id": "skill-1", "name": "Python", "source_quote": "Python", "turn_id": "old", "status": "deleted"}]}}
        result = self.memory(state)
        self.assertEqual(result["skills"], [])
        self.assertFalse(any(row.get("source_id") == "old" for row in result["pending_evidence"]))
        self.assertTrue(any(row.get("source_id") == "fresh" and row["text"] == "Python" for row in result["pending_evidence"]))
        self.assertEqual(invalidated_source_ids(state), {"old"})

    def test_basic_info_fact_versions_expose_only_active_values(self):
        old = {**fact("旧城市标记", turn="old", status="superseded"), "field": "location"}
        new = {**fact("新城市", turn="fresh", fid="basic-new"), "field": "location"}
        state = {"messages": [HumanMessage(content="旧城市标记", id="old"), HumanMessage(content="新城市", id="fresh")],
                 "collected_info": {"basic_info": {"location": "新城市"}, "basic_info_facts": [old, new]}}
        result = self.memory(state)
        self.assertNotIn("旧城市标记", rendered(result))
        self.assertEqual(result["basic_info_facts"], [new])
        self.assertEqual(result["basic_info"]["location"], "新城市")
        self.assertNotIn("basic_info_facts", result["session_constraints"])
        self.assertEqual(invalidated_source_ids(state), {"old"})

    def test_known_external_legacy_duplicates_are_excluded_unknown_notes_reviewed(self):
        for kind in ("reference", "jd", "review", "excluded"):
            with self.subTest(kind=kind):
                external = "外部材料独有标记"
                message = HumanMessage(content=external, id="outside", additional_kwargs={"career_material_type": kind})
                state = {"messages": [message], "collected_info": {"projects": [{"item_id": "p1", "name": "旧项目",
                    "raw_notes": [external, "来源暂不明确的原句"], "description": external}],
                    "raw_notes": [external], "metadata_context": [{"source": "example", "text": external}]}}
                if kind == "excluded":
                    state["non_candidate_message_ids"] = ["outside"]
                result = self.memory(state)
                self.assertNotIn(external, rendered(result))
                unknown = next(row for row in result["pending_evidence"] if row.get("text") == "来源暂不明确的原句")
                self.assertEqual(unknown["source_kind"], "unverified_legacy")
                self.assertTrue(unknown["requires_review"])
                self.assertNotIn("source_id", unknown)
        state["messages"].append(HumanMessage(content=external, id="own"))
        self.assertTrue(any(row.get("source_id") == "own" for row in self.memory(state)["pending_evidence"]))

    def test_unbound_invalidation_quarantines_old_quote_but_allows_fresh_confirmation(self):
        state = state_for("旧经历原句", [fact("旧经历原句", turn="", status="deleted")])
        state["messages"] = [HumanMessage(content="旧经历原句", id="old"),
                             HumanMessage(content="我重新确认：旧经历原句", id="current")]
        self.assertEqual(invalidated_source_ids(state), {"old"})
        old = next(row for row in self.memory(state)["pending_evidence"] if row.get("source_id") == "old")
        self.assertTrue(old["requires_review_after_invalidation"])
        fresh = next(row for row in self.memory(state)["pending_evidence"] if row.get("source_id") == "current")
        self.assertNotIn("requires_review_after_invalidation", fresh)

    def test_invalidated_structured_value_does_not_reappear(self):
        state = state_for("已填写", [fact("旧上线断言", status="deleted")])
        state["messages"][0].additional_kwargs = {"answers": {"turn_id": "card", "items": [
            {"id": "status", "value": ["旧上线断言", "部署由他人负责"]}]},
            "answer_card": {"turn_id": "card", "subject": "项目甲", "questions": [
                {"id": "status", "prompt": "上线情况", "kind": "multi"}]}}
        result = self.memory(state)
        self.assertNotIn("旧上线断言", rendered(result))
        answer = next(row for row in result["pending_evidence"] if row["source_kind"] == "structured_answer")
        self.assertEqual(answer["submitted"]["value"], ["部署由他人负责"])
        self.assertTrue(answer["requires_review_after_invalidation"])
        self.assertEqual(invalidated_source_ids(state), {"source"})

    def test_unbound_invalidation_checks_only_bound_submitted_answer_values(self):
        def answer_message(identifier, value="已选值", *, card_id="card", question_id="status"):
            return HumanMessage(content="已填写", id=identifier, additional_kwargs={
                "answers": {"turn_id": "card", "items": [{"id": question_id, "value": [value]}]},
                "answer_card": {"turn_id": card_id, "subject": "项目甲", "questions": [
                    {"id": "status", "prompt": "旧失效值是否适用？", "options": ["旧失效值", "已选值"]}]}})
        state = state_for("", [fact("旧失效值", turn="", status="deleted")])
        state["messages"] = [answer_message("old", "旧失效值"), answer_message("options-only"),
                             answer_message("wrong-card", "旧失效值", card_id="other"),
                             answer_message("wrong-question", "旧失效值", question_id="other"),
                             answer_message("fresh", "旧失效值")]
        self.assertEqual(invalidated_source_ids(state), {"old"})
        rows = [row for row in self.memory(state)["pending_evidence"] if row["source_kind"] == "structured_answer"]
        self.assertTrue(next(row for row in rows if row["source_id"] == "old")["requires_review_after_invalidation"])
        self.assertNotIn("requires_review_after_invalidation", next(row for row in rows if row["source_id"] == "fresh"))

    def test_unbound_invalidation_checks_legal_intake_fields_not_extra_metadata(self):
        state = state_for("", [fact("旧表单断言", turn="", status="superseded")])
        state["messages"] = [
            HumanMessage(content="已填写", id="old-experience", additional_kwargs={"intake": {
                "kind": "experiences", "items": [{"name": "项目甲", "summary": "旧表单断言"}]}}),
            HumanMessage(content="已填写", id="old-basic", additional_kwargs={"intake": {
                "kind": "basics", "values": {"availability": "旧表单断言"}}}),
            HumanMessage(content="已填写", id="extra-only", additional_kwargs={"intake": {
                "kind": "experiences", "items": [{"name": "项目乙", "suggested_summary": "旧表单断言"}],
                "options": ["旧表单断言"]}}),
            HumanMessage(content="已填写", id="fresh", additional_kwargs={"intake": {
                "kind": "experiences", "items": [{"name": "项目甲", "summary": "旧表单断言"}]}})]
        self.assertEqual(invalidated_source_ids(state), {"old-experience", "old-basic"})
        rows = [row for row in self.memory(state)["pending_evidence"] if row["source_kind"] == "intake"]
        self.assertTrue(all(row["requires_review_after_invalidation"] for row in rows
                            if row["source_id"] in {"old-experience", "old-basic"}))
        self.assertNotIn("requires_review_after_invalidation", next(row for row in rows if row["source_id"] == "fresh"))


if __name__ == "__main__":
    unittest.main()
