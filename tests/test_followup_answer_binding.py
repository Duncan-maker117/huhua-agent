"""Short follow-up answers retain their unique experience and clear stale receipts."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents import resume_graph as graph  # noqa: E402
from app.agents.fact_extractor import extract_facts_patch  # noqa: E402
from app.services.resume_facts import new_fact  # noqa: E402
from app.services.followup_context import latest_followup
from app.services.resume_workspace import build_workspace  # noqa: E402


QUESTION = "采购对接的是几家客户或供应商？考勤和办公用品管理覆盖多少人？有具体范围，这段才不空。"
ANSWER = "目前我手上采购主要对接的是2家客户，考勤和办公用品管理覆盖20余人"
CLAUSES = ANSWER.split("，")


def store():
    return {"work_experience": [{"item_id": "work-1", "company": "星禾科技", "facts": [
        new_fact("参与采购对接"), new_fact("管理考勤和办公用品")], "raw_notes": []}]}


def targeted_store():
    data = store()
    data["followup_target"] = {"item_id": "work-1", "section": "work_experience",
                               "asked_hash": graph._hash_text(latest_followup("需要你补充：" + QUESTION))}
    return data


def item_patch(name="星禾科技", **kwargs):
    return {"items": [{"section": "work_experience", "name": name, "facts": [
        {"kind": "scope_scale", "text": clause, "source_quote": clause} for clause in CLAUSES], **kwargs}]}


class FakeLLM:
    def __init__(self, value):
        self.value = value
        self.payload = None

    async def ainvoke(self, messages):
        self.payload = json.loads(messages[-1].content)
        return SimpleNamespace(content=json.dumps(self.value, ensure_ascii=False))


class FollowupAnswerBindingTest(unittest.IsolatedAsyncioTestCase):
    async def test_two_turn_collection_binds_unnamed_question_and_answer(self):
        before = store()
        # A second item ensures binding is based on this turn, not list position.
        before["projects"] = [{"item_id": "other", "name": "预约工具", "facts": [new_fact("开发预约工具")]}]
        initial = "我整理了办公用品台账"
        llm = FakeLLM({"items": [{"section": "work_experience", "item_id": "work-1", "facts": [
            {"text": initial, "source_quote": initial}]}]})
        state = {"collected_info": before, "messages": [HumanMessage(content=initial)],
                 "requested_task": "rewrite_experience"}
        with (patch.object(graph, "_make_non_streaming_llm", return_value=llm),
              patch.object(graph, "_live_resume_update", return_value={}),
              patch.object(graph, "stream_public_reply", AsyncMock(return_value=AIMessage(content="需要你补充：" + QUESTION)))):
            first = await graph._collecting_turn_node(state, object())
        self.assertEqual(first["collected_info"]["followup_target"]["item_id"], "work-1")
        self.assertEqual(set(first["collected_info"]["followup_target"]), {"item_id", "section", "asked_hash"})
        for extracted in (item_patch("行政采购经历"), {}):
            with self.subTest(extracted=bool(extracted)):
                llm = FakeLLM(extracted)
                state.update(collected_info=first["collected_info"], messages=state["messages"] + first["messages"] + [HumanMessage(content=ANSWER)])
                with (patch.object(graph, "_make_non_streaming_llm", return_value=llm),
                      patch.object(graph, "_live_resume_update", return_value={}),
                      patch.object(graph, "stream_public_reply", AsyncMock(return_value=AIMessage(content="已记下，右侧草稿会同步更新。")))):
                    result = await graph._collecting_turn_node(state, object())
                data = result["collected_info"]
                quotes = [f["source_quote"] for f in data["work_experience"][0]["facts"]]
                self.assertTrue(all(clause in quotes for clause in CLAUSES))
                self.assertEqual(len(data["work_experience"]), 1)
                self.assertEqual(len(data["projects"]), 1)
                self.assertNotIn("unrecorded", data)
                self.assertNotIn("followup_target", data)
                self.assertNotIn("没记下来", "".join(m.content for m in result["messages"]))
                self.assertEqual(llm.payload["followup_target"], {"item_id": "work-1", "section": "work_experience", "name": "星禾科技"})

    async def test_unique_normalized_name_match_does_not_require_name_in_answer(self):
        for name in (" 星禾科技 ", "星禾—科技", "星禾　科技"):
            with self.subTest(name=name):
                result = await extract_facts_patch(ANSWER, store(), FakeLLM(item_patch(name)))
                self.assertEqual(result["rejected"], [])
                self.assertEqual(result["uncovered"], [])
                self.assertEqual(result["items"][0]["item_id"], "work-1")

    async def test_ambiguous_name_cannot_be_resolved_by_followup_target(self):
        data = targeted_store()
        data["work_experience"][0]["title"] = "采购助理"
        data["work_experience"].append({"item_id": "work-2", "company": "星禾科技", "title": "行政助理", "facts": []})
        result = await extract_facts_patch(ANSWER, data, FakeLLM(item_patch()))
        self.assertFalse(result["items"])
        self.assertIn("item_name_not_in_candidate_message", [r["reason"] for r in result["rejected"]])
        self.assertEqual(result["uncovered"], CLAUSES)

    async def test_new_or_other_experience_never_uses_implicit_target(self):
        for signal in ("另一个项目", "另外一个项目", "新项目", "新的工作", "另外"):
            for extracted in ({}, item_patch(), item_patch(item_id="work-1")):
                with self.subTest(signal=signal, extracted=bool(extracted)):
                    message = f"我在{signal}对接2家客户，考勤和办公用品管理覆盖20余人"
                    result = await extract_facts_patch(message, targeted_store(), FakeLLM(extracted))
                    self.assertFalse(any(item["item_id"] == "work-1" for item in result["items"]))

    async def test_named_other_item_and_deleted_target_do_not_inherit_followup(self):
        data = targeted_store()
        data["projects"] = [{"item_id": "other", "name": "预约工具", "facts": []}]
        for message in ("我在预约工具对接2家客户",):
            result = await extract_facts_patch(message, data, FakeLLM({}))
            self.assertFalse(result["items"])
        data["work_experience"] = []
        result = await extract_facts_patch(ANSWER, data, FakeLLM({}))
        self.assertFalse(result["items"])

    async def test_new_named_project_and_mixed_clause_do_not_inherit_followup(self):
        for message in ("我在星河项目对接2家客户", "我参与了“星河”项目，对接2家客户", "我做了一个项目，叫星河，对接2家客户"):
            with self.subTest(message=message):
                result = await extract_facts_patch(message, targeted_store(), FakeLLM({}))
                self.assertFalse(result["items"])
        message = "我在星禾科技对接2家客户，另一个项目我开发了表单"
        raw = {"items": [{"section": "work_experience", "item_id": "work-1", "name": "星禾科技",
                          "facts": [{"text": message.split("，")[0], "source_quote": message.split("，")[0]}]}]}
        result = await extract_facts_patch(message, targeted_store(), FakeLLM(raw))
        self.assertEqual(len(result["items"][0]["facts"]), 1)
        self.assertEqual(result["uncovered"], [message.split("，")[1]])

    async def test_stale_question_hash_cannot_bind_a_later_answer(self):
        result = await graph._extract_with_previous_assistant(
            ANSWER, targeted_store(), FakeLLM({}), "你还有其他项目吗？")
        self.assertEqual(len(result["work_experience"][0]["facts"]), 2)
        self.assertNotIn("followup_target", result)
        self.assertNotIn("item_id", result["unrecorded"])

    async def test_invented_number_and_responsibility_still_rejected(self):
        for invented, reason in (("采购对接200家客户", "unsupported_number"),
                                 ("负责采购对接2家客户", "unsupported_responsibility_or_status")):
            with self.subTest(invented=invented):
                raw = item_patch()
                raw["items"][0]["facts"][0]["text"] = invented
                result = await extract_facts_patch(ANSWER, targeted_store(), FakeLLM(raw))
                self.assertTrue(any(reason in str(row["reason"]) for row in result["rejected"]))
                facts = result["items"][0]["facts"]
                self.assertNotIn(invented, [fact["text"] for fact in facts])
                self.assertTrue(all(clause in [fact["source_quote"] for fact in facts] for clause in CLAUSES))
                self.assertEqual(result["uncovered"], [])

    async def test_covered_legacy_note_cleared_and_saved_draft_cannot_restore_it(self):
        data = targeted_store()
        notes = ["这句没有记下来：" + clause for clause in CLAUSES]
        data["verification_notes"] = notes + ["请核对经历日期"]
        result = await graph._extract_info_from_message(ANSWER, data, FakeLLM({}))
        self.assertEqual(result["verification_notes"], ["请核对经历日期"])
        saved = {"verification_notes": notes + ["请核对学校全称"]}
        merged = graph._preserve_saved_resume_metadata(result, saved)
        self.assertEqual(merged["verification_notes"], ["请核对经历日期", "请核对学校全称"])
        self.assertNotIn("followup_target", result)
        view = build_workspace({"collected_info": result}, {**saved, "work_experience": [{"company": "星禾科技", "bullets": ["参与采购"]}]})
        self.assertFalse(any(note.startswith("这句没有记下来：") for note in view["experiences"]["verification_notes"]))

    async def test_reworded_answer_clears_only_previous_uncovered_for_same_target(self):
        data = targeted_store()
        old = ["我跟两家买方联系", "公司二十多个人的打卡和文具是我管"]
        notes = ["这句没有记下来：" + clause for clause in old]
        other = "这句没有记下来：我为另一个项目完成了培训"
        data["verification_notes"] = notes + [other]
        data["unrecorded"] = {"source": "previous", "item_id": "work-1", "clauses": old}
        result = await graph._extract_info_from_message(ANSWER, data, FakeLLM({}))
        self.assertEqual(result["verification_notes"], [other])
        self.assertNotIn("unrecorded", result)
        data["unrecorded"]["item_id"] = "work-2"
        result = await graph._extract_info_from_message(ANSWER, data, FakeLLM({}))
        self.assertEqual(result["verification_notes"], notes + [other])

    async def test_new_experience_uncovered_is_not_tagged_with_old_target(self):
        result = await graph._extract_info_from_message(
            "我在另一个项目对接2家客户", targeted_store(), FakeLLM({}))
        self.assertNotIn("item_id", result["unrecorded"])

    async def test_partial_retry_does_not_clear_unresolved_previous_notes(self):
        data = targeted_store()
        data["unrecorded"] = {"source": "previous", "item_id": "work-1", "clauses": ["旧的采购答复"]}
        data["verification_notes"] = ["这句没有记下来：旧的采购答复"]
        message = "我在星禾科技对接2家客户。另一个项目我开发了表单"
        raw = {"items": [{"section": "work_experience", "item_id": "work-1", "name": "星禾科技", "facts": [
            {"text": message.split("。")[0], "source_quote": message.split("。")[0]}]}]}
        result = await graph._extract_info_from_message(message, data, FakeLLM(raw))
        self.assertIn(data["verification_notes"][0], result["verification_notes"])

    async def test_inactive_fact_and_different_number_do_not_clear_notes(self):
        data = store()
        data["work_experience"][0]["facts"].extend([
            {**new_fact(CLAUSES[0]), "status": "deleted"}, new_fact(CLAUSES[1].replace("20", "200"))])
        data["verification_notes"] = ["这句没有记下来：" + clause for clause in CLAUSES]
        result = await graph._extract_info_from_message("继续", data, FakeLLM({}))
        self.assertEqual(result["verification_notes"], data["verification_notes"])

    async def test_partial_receipt_is_corrected_before_any_public_delta(self):
        class PublicLLM:
            async def astream(self, messages):
                for part in ("已记", "下，右侧草稿会同步更新。", "\n\n需要你补充：" + QUESTION):
                    yield AIMessageChunk(content=part)

        data = store()
        data["work_experience"][0]["facts"].append(new_fact(CLAUSES[0]))
        data["unrecorded"] = {"source": graph._hash_text(ANSWER), "clauses": [CLAUSES[1]]}
        events = []
        with (patch("app.agents.public_reply.get_stream_writer", return_value=events.append),
              patch("app.agents.public_reply.get_config", return_value={})):
            reply = await graph._collection_reply(PublicLLM(), [], data, ANSWER)
        self.assertTrue(reply.content.startswith("部分已记下"))
        self.assertEqual("".join(row["content"] for row in events), reply.content)
        self.assertEqual(len(events), 1)

    async def test_no_recorded_fact_does_not_claim_partial_success(self):
        class PublicLLM:
            async def ainvoke(self, messages):
                return AIMessage(content="已记下，右侧草稿会同步更新。")

        data = {"unrecorded": {"source": graph._hash_text(ANSWER), "clauses": CLAUSES}}
        reply = await graph._collection_reply(PublicLLM(), [], data, ANSWER)
        self.assertNotIn("已记下", reply.content)
        self.assertNotIn("会同步更新", reply.content)


class FollowupQuestionTest(unittest.TestCase):
    def test_notice_is_not_current_question_even_in_separate_message(self):
        question = "需要你补充：" + QUESTION
        notice = f"这句我没记下来：「{CLAUSES[0]}」，能换个说法吗？\n「包括」后面还没说完，可以补充一下吗？"
        for separator in ("\n\n", " "):
            parsed = latest_followup(question + separator + notice)
            self.assertIn("采购", parsed)
            self.assertNotIn("没记下来", parsed)
            self.assertNotIn("后面还没说完", parsed)
        self.assertEqual(latest_followup(notice), "")
        state = {"collected_info": store(), "messages": [HumanMessage(content=ANSWER), AIMessage(content=question), AIMessage(content=notice)]}
        guidance = build_workspace(state, {})["guidance"]
        self.assertEqual(guidance['kind'], 'intake_experiences')  # 有经历即继续收集，不阻塞于未知方向。
        self.assertNotIn('questions', guidance)  # 正文归属解析仍不生成问题卡。
        self.assertIn(QUESTION, graph._latest_previous_assistant(state["messages"] + [HumanMessage(content="换个说法")]))

    def test_question_target_requires_unique_context_and_expires(self):
        before = store()
        after = copy.deepcopy(before)
        after["work_experience"][0]["facts"].append(new_fact("我整理了台账"))
        reply = "需要你补充：" + QUESTION
        bound = graph._bind_followup_target(before, after, reply)
        self.assertEqual(bound["followup_target"]["item_id"], "work-1")
        self.assertNotIn("followup_target", graph._bind_followup_target(before, before, reply))
        self.assertEqual(graph._bind_followup_target(bound, bound, reply)["followup_target"], bound["followup_target"])
        self.assertNotIn("followup_target", graph._bind_followup_target(bound, bound, "好，接下来生成草稿吗？"))
        self.assertNotIn("followup_target", graph._bind_followup_target(before, after, "需要你补充：还做过什么项目？"))
        after["projects"] = [{"item_id": "other", "name": "预约工具", "facts": [new_fact("我做了表单")]}]
        self.assertNotIn("followup_target", graph._bind_followup_target(before, after, reply))
        self.assertNotIn("followup_target", graph._bind_followup_target(before, after, "需要你补充：星禾科技和预约工具分别覆盖多少人？"))
        known = graph._bind_followup_target(before, after, reply, focus_ids=["work-1"])
        self.assertEqual(known["followup_target"]["item_id"], "work-1")
        self.assertNotIn("followup_target", graph._bind_followup_target(before, after, "1. 采购对接几家客户？\n2. 预约工具用了几个人？"))


if __name__ == "__main__":
    unittest.main()
