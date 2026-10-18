"""P2l same-message identity joins and unresolved split delivery, entirely offline."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
from app.agents import orchestrator as loop, orchestrator_tools as tools, resume_graph as graph  # noqa: E402
from app.config import Settings  # noqa: E402
from app.schemas.facts import FACT_LABELS  # noqa: E402
from app.services.ask_user import pending_card  # noqa: E402
from app.services.candidate_language import PLACEHOLDER_NAMES  # noqa: E402
from app.services.fact_corrections import merge_new_experience_identities  # noqa: E402
from app.services.resume_facts import new_fact  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from test_orchestrator import Model, call, state  # noqa: E402
from test_orchestrator_tools import Writer, measured  # noqa: E402


def snapshot():
    return json.loads((ROOT / "evaluation/agent-loop-spike/p2-cold-split-state.json").read_text())


def split_case():
    frozen = snapshot()
    facts = frozen["collected_info"]
    previous = deepcopy(facts)
    previous["campus"] = []
    message = frozen["human_messages"][2]
    turn_id = facts["campus"][0]["facts"][0]["turn_id"]
    return facts, previous, message, turn_id


def extracted_patch(facts):
    return {"items": [{"section": "campus", **deepcopy(row)} for row in facts["campus"]]}


class P2lTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch("app.config.get_settings", return_value=Settings(_env_file=None, AGENT_MODE="loop")))
        self.enterContext(patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured))
        self.enterContext(patch("app.services.resume_capacity.measure_rendered_pages", side_effect=measured))

    def assert_private(self, value):
        basic = snapshot()["collected_info"]["basic_info"]
        for key in ("phone", "email"):
            self.assertNotIn(basic[key], str(value))

    def assert_merged(self, collected, original, message, turn_id):
        self.assertEqual(len(collected["campus"]), 1)
        item = collected["campus"][0]
        source, target = original["campus"]
        self.assertEqual((item["name"], item["item_id"]), (target["name"], target["item_id"]))
        self.assertEqual((item["start_date"], item["end_date"]), ("2026.03", "2026.04"))
        self.assertEqual({f["id"]: f for f in item["facts"]},
                         {f["id"]: f for row in original["campus"] for f in row["facts"]})
        self.assertEqual(sum(f["kind"] == "status_limit" for f in item["facts"]), 3)
        self.assertEqual(set(item["raw_notes"]), {n for row in original["campus"] for n in row["raw_notes"]})
        self.assertEqual(item["merged_from"], [{"item_id": source["item_id"], "section": "campus",
            "name": source["name"], "source_quote": message, "turn_id": turn_id}])

    def test_snapshot_merge_preserves_every_fact_source_limit_and_audit(self):
        facts, previous, message, turn_id = split_case()
        original = deepcopy(facts)
        merge_new_experience_identities(facts, previous, message, turn_id)
        self.assert_merged(facts, original, message, turn_id)
        once = deepcopy(facts)
        merge_new_experience_identities(facts, previous, message, turn_id)
        self.assertEqual(facts, once)

    def test_identical_placeholder_dates_and_links_are_preserved(self):
        facts, previous, message, turn_id = split_case()
        source, target = facts["campus"]
        for fact in target["facts"]:
            if fact.get("field") in {"start_date", "end_date"}:
                source["facts"].append({**deepcopy(fact), "id": "source-" + fact["id"]})
                source[fact["field"]] = fact["text"]
        source["links"] = ["https://example.invalid/source"]
        target["links"] = ["https://example.invalid/target"]
        original = deepcopy(facts)
        merge_new_experience_identities(facts, previous, message, turn_id)
        self.assert_merged(facts, original, message, turn_id)
        self.assertEqual(set(facts["campus"][0]["links"]),
                         {"https://example.invalid/source", "https://example.invalid/target"})

    def test_same_rule_supports_other_experience_sections_without_cross_section_join(self):
        for section in ("projects", "work_experience", "internship", "open_source", "awards"):
            with self.subTest(section=section):
                facts, _, message, turn_id = split_case()
                source, target = facts.pop("campus")
                source.pop("name")
                source[FACT_LABELS[section]] = PLACEHOLDER_NAMES[section]
                target[FACT_LABELS[section]] = target.pop("name")
                facts[section] = [source, target]
                merge_new_experience_identities(facts, {}, message, turn_id)
                self.assertEqual(len(facts[section]), 1)
                self.assertEqual(facts[section][0]["item_id"], target["item_id"])
                self.assertEqual(facts[section][0]["merged_from"][0]["section"], section)

    def test_ambiguous_historical_conflicting_and_ungrounded_pairs_never_merge(self):
        variants = ("extra_named", "extra_placeholder", "old_other_candidate", "old_source", "old_target",
                    "other_turn", "mixed_turn", "mixed_sources", "imported", "missing_turn", "no_turn",
                    "different_start", "different_end", "conflicting_field", "missing_target_date",
                    "name_absent", "named_source", "cross_section", "empty_facts")
        for variant in variants:
            with self.subTest(variant=variant):
                facts, previous, message, turn_id = split_case()
                source, target = facts["campus"]
                if variant in {"extra_named", "extra_placeholder", "old_other_candidate"}:
                    extra = deepcopy(source if variant == "extra_placeholder" else target)
                    extra["item_id"] = "another-item"
                    facts["campus"].append(extra)
                    if variant == "old_other_candidate":
                        previous["campus"].append(deepcopy(extra))
                if variant in {"old_source", "old_target"}:
                    previous["campus"].append(deepcopy(source if variant == "old_source" else target))
                if variant == "other_turn":
                    for fact in target["facts"]:
                        fact["turn_id"] = "earlier"
                if variant in {"mixed_turn", "missing_turn"}:
                    source["facts"][1]["turn_id"] = "earlier" if variant == "mixed_turn" else ""
                if variant == "mixed_sources":
                    source["facts"][1]["sources"].append({"turn_id": "earlier", "source": "chat"})
                if variant == "imported":
                    source["facts"][1]["source"] = "import"
                if variant == "no_turn":
                    turn_id = ""
                if variant in {"different_start", "different_end"}:
                    source["start_date" if variant == "different_start" else "end_date"] = "2025.01"
                if variant == "conflicting_field":
                    source["facts"].append({**new_fact("2025.01", kind="context", turn_id=turn_id), "field": "start_date"})
                if variant == "missing_target_date":
                    source["date"] = "2025.01"
                if variant == "name_absent":
                    message = message.replace(target["name"], "一个社团")
                if variant == "named_source":
                    source["name"] = "另一个独立社团"
                if variant == "cross_section":
                    facts["projects"] = [facts["campus"].pop(0)]
                if variant == "empty_facts":
                    target["facts"] = []
                before = deepcopy(facts)
                merge_new_experience_identities(facts, previous, message, turn_id)
                self.assertEqual(facts, before)

    async def record_snapshot(self):
        facts, previous, message, turn_id = split_case()
        value = state(collected_info=previous, messages=[HumanMessage(content=message, id=turn_id)])
        saver = AsyncMock()
        token = graph._intake_saver.set(saver)
        try:
            with patch("app.agents.fact_extractor.extract_facts_patch", AsyncMock(return_value=extracted_patch(facts))):
                outcome = await tools.record_facts(value, {"source_id": "current"}, tools.ToolContext(llm=object()))
        finally:
            graph._intake_saver.reset(token)
        self.assertEqual(outcome.result["status"], "ok")
        self.assert_merged(outcome.update["collected_info"], facts, message, turn_id)
        self.assert_merged(saver.await_args.args[0]["collected_info"], facts, message, turn_id)
        self.assert_private(outcome.result)
        return {**value, **outcome.update}

    async def test_record_snapshot_then_real_writer_pipeline_with_offline_writer(self):
        recorded = await self.record_snapshot()
        for invented in (False, True):
            with self.subTest(invented=invented):
                model = Writer(invented=invented)
                value = {**recorded, "jd_info": {"role_direction": "数据运营实习", "role_profile": {"role_family": "data"}},
                         "confirmed_plan": {"bullet_style": "plain"}}
                outcome = await tools.write_draft(value, {}, tools.ToolContext(llm=model))
                self.assertIn(outcome.result["status"], {"ok", "partial"})
                rows = outcome.update["resume_data"]["campus"]
                self.assertEqual(len(rows), 1)
                item = rows[0]
                self.assertEqual(item["name"], "校园读书社")
                self.assertEqual((item["start_date"], item["end_date"]), ("2026.03", "2026.04"))
                self.assertFalse(item.get("hidden"))
                body = " ".join(item["bullets"])
                for text in ("Excel", "核对", "28条", "2张", "汇总表", "社长"):
                    self.assertIn(text, body)
                self.assertNotIn("900万", body)
                self.assertNotIn("增长率", body)
                self.assertTrue(outcome.update["resume_draft"].strip())
                original = {f["id"]: f for f in recorded["collected_info"]["campus"][0]["facts"]}
                records = outcome.update["resume_meta"]["bullets"][item["item_id"]]
                self.assertEqual(len(records), len(item["bullets"]))
                for text, record in zip(item["bullets"], records):
                    self.assertEqual(record["text_hash"], text_hash(text))
                    self.assertTrue(record["fact_ids"])
                    self.assertTrue(set(record["fact_ids"]) <= original.keys())
                self.assert_private(model.requests)
                self.assert_private(outcome.result)
                self.assertNotIn("FactSlots", [name for name, _ in model.requests])

    async def test_old_collecting_path_uses_same_message_join_and_fresh_turn(self):
        facts, previous, message, _ = split_case()
        calls = []

        async def extract(text, current, llm, **kwargs):
            calls.append(kwargs["turn_id"])
            value = extracted_patch(facts)
            for row in value["items"]:
                for fact in row["facts"]:
                    fact["turn_id"] = kwargs["turn_id"]
                    for origin in fact["sources"]:
                        origin["turn_id"] = kwargs["turn_id"]
            return value

        with patch("app.agents.fact_extractor.extract_facts_patch", side_effect=extract):
            for _ in range(2):
                result = await graph._extract_info_from_message(message, previous, object())
                self.assertEqual(len(result["campus"]), 1)
                self.assertEqual(result["campus"][0]["merged_from"][0]["turn_id"], calls[-1])
                self.assertEqual(len(result["campus"][0]["facts"]), 8)
        self.assertNotEqual(calls[0], calls[1])

    async def test_record_entry_does_not_join_old_items_or_name_outside_current_message(self):
        for variant in ("old_source", "other_message", "name_absent", "extra_candidate", "different_period"):
            with self.subTest(variant=variant):
                facts, previous, message, turn_id = split_case()
                if variant == "old_source":
                    previous["campus"] = [deepcopy(facts["campus"][0])]
                if variant == "other_message":
                    turn_id = "later-message"
                if variant == "name_absent":
                    message = "补充我在社团核对资料的经历。"
                if variant == "extra_candidate":
                    facts["campus"].append({**deepcopy(facts["campus"][1]), "item_id": "another"})
                if variant == "different_period":
                    facts["campus"][0]["facts"].append({**new_fact("2025.01", kind="context", turn_id=turn_id), "field": "start_date"})
                value = state(collected_info=previous, messages=[HumanMessage(content=message, id=turn_id)])
                with patch("app.agents.fact_extractor.extract_facts_patch", AsyncMock(return_value=extracted_patch(facts))):
                    outcome = await tools.record_facts(value, {"source_id": "current"}, tools.ToolContext(llm=object()))
                self.assertEqual(outcome.result["status"], "ok")
                self.assertEqual(len(outcome.update["collected_info"]["campus"]), len(facts["campus"]))

    async def test_collecting_rejects_old_items_and_name_only_in_external_material(self):
        for variant in ("old_source", "name_absent", "external_name", "conflicting_dates"):
            with self.subTest(variant=variant):
                facts, previous, message, _ = split_case()
                name = facts["campus"][1]["name"]
                if variant == "old_source":
                    previous["campus"] = [deepcopy(facts["campus"][0])]
                if variant in {"name_absent", "external_name"}:
                    message = message.replace(name, "一个社团")
                if variant == "external_name":
                    message += "\n参考材料：\n" + name

                async def extract(text, current, llm, **kwargs):
                    value = extracted_patch(facts)
                    for row in value["items"]:
                        for fact in row["facts"]:
                            fact["turn_id"] = kwargs["turn_id"]
                            for origin in fact["sources"]:
                                origin["turn_id"] = kwargs["turn_id"]
                    if variant == "conflicting_dates":
                        value["items"][0]["facts"].append({**new_fact("2025.01", kind="context",
                            turn_id=kwargs["turn_id"]), "field": "start_date"})
                    return value

                with patch("app.agents.fact_extractor.extract_facts_patch", side_effect=extract):
                    result = await graph._extract_info_from_message(message, previous, object())
                self.assertEqual(len(result["campus"]), 2)

    async def test_unresolved_split_returns_reason_and_one_card_without_writer(self):
        facts, _, _, _ = split_case()
        for variant in ("split", "no_named_facts", "hidden_placeholder", "multiple_candidates"):
            with self.subTest(variant=variant):
                value = state(collected_info=deepcopy(facts))
                if variant == "no_named_facts":
                    value["collected_info"]["campus"][1]["facts"] = []
                if variant == "hidden_placeholder":
                    value["resume_data"] = {"campus": [{"item_id": facts["campus"][0]["item_id"], "hidden": True}]}
                if variant == "multiple_candidates":
                    value["collected_info"]["campus"].append({**deepcopy(facts["campus"][1]), "item_id": "another"})
                before = deepcopy(value)
                with patch.object(tools, "_write", AsyncMock(side_effect=AssertionError("unresolved owner"))) as writer:
                    outcome = await tools.write_draft(value, {}, tools.ToolContext())
                writer.assert_not_awaited()
                self.assertEqual(value, before)
                self.assertEqual(outcome.result["status"], "insufficient")
                self.assertEqual(outcome.result["code"], "experience_identity_unresolved")
                self.assertIn("尚不能确认", outcome.result["message"])
                self.assertTrue(outcome.result["followup_attached"])
                self.assertTrue(outcome.stop)
                self.assertNotIn("resume_data", outcome.update)
                card = pending_card({**value, **outcome.update})
                self.assertEqual(len(card["questions"]), 1)
                self.assertIn("同一段经历", card["questions"][0]["prompt"])
                self.assert_private(outcome.result)

    async def test_unresolved_card_reaches_final_reply_even_when_model_fails(self):
        facts, _, _, _ = split_case()
        for final in ({"content": "请先确认经历归属。"}, RuntimeError("offline final failure")):
            with self.subTest(final=final):
                value = state(collected_info=facts)
                model = Model([call("write_draft"), final])
                events = []
                with patch.object(tools, "_write", AsyncMock(side_effect=AssertionError("unresolved owner"))):
                    result = await loop.run_orchestrator(value, model, registry=tools.TOOLS, emit=events.append)
                cards = [e["guidance"] for e in events if e["type"] == "guidance"]
                self.assertEqual(len(cards), 1)
                self.assertEqual(cards[0], result["messages"][-1].additional_kwargs["ask_user"])
                self.assertEqual(cards[0], pending_card({**value, **result}))
                self.assertIn("insufficient", str(model.requests))
                self.assertIn("experience_identity_unresolved", str(model.requests))
                self.assert_private(model.requests)

    async def test_disabled_or_closed_questions_keep_insufficient_reason_without_reasking(self):
        facts, _, _, _ = split_case()
        for variant in ("stopped", "budget", "closed", "already_asked", "pending_plan"):
            with self.subTest(variant=variant):
                value = state(collected_info=deepcopy(facts))
                ctx = tools.ToolContext()
                if variant == "stopped":
                    value["collected_info"]["no_more_questions"] = True
                if variant == "budget":
                    value["session_constraints"] = {"questions_finished": True}
                if variant == "closed":
                    value["closed_questions"] = [{"subject": "", "id": "experience_identity", "dimension": "experience_identity"}]
                if variant == "already_asked":
                    ctx.ask_used = True
                if variant == "pending_plan":
                    value["pending_plan"] = {"ready": True}
                outcome = await tools.write_draft(value, {}, ctx)
                self.assertEqual(outcome.result["status"], "insufficient")
                self.assertEqual(outcome.result["code"], "experience_identity_unresolved")
                self.assertFalse(outcome.result["followup_attached"])
                self.assertTrue(outcome.result["followup_unavailable_reason"])
                self.assertFalse(any(e["type"] == "guidance" for e in outcome.events))

    def test_complete_unrelated_hidden_or_deleted_facts_do_not_trigger_clarification(self):
        for variant in ("complete", "different_section", "hidden_target", "deleted", "only_limits"):
            with self.subTest(variant=variant):
                facts, _, _, _ = split_case()
                value = state(collected_info=facts)
                source, target = facts["campus"]
                if variant == "complete":
                    target["facts"].append(new_fact("整理值班表", kind="action"))
                if variant == "different_section":
                    facts["projects"] = [facts["campus"].pop(0)]
                if variant == "hidden_target":
                    value["resume_data"] = {"campus": [{"item_id": target["item_id"], "hidden": True}]}
                if variant in {"deleted", "only_limits"}:
                    for fact in source["facts"]:
                        if variant == "deleted":
                            fact["status"] = "deleted"
                        else:
                            fact["kind"] = "status_limit"
                self.assertEqual(tools._split_identity_clarification(value), {})


if __name__ == "__main__":
    unittest.main()
