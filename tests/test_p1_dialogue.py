"""P1 dialogue regressions use fictional candidates and scripted model responses."""

import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents import resume_graph as rg
from app.agents.fact_extractor import extract_facts_patch, split_incomplete_tail
from app.agents.router import route_intents, start_route_call
from app.agents.wording_advice import wording_advice
from app.services.resume_facts import new_fact


def state(text="你好", stage="JD_INPUT", with_draft=True):
    result = rg._init_state()
    result.update(stage=stage, candidate_history_reconciled=True,
                  messages=[HumanMessage(content=text, id="synthetic-turn")],
                  collected_info={"projects": [{"item_id": "p1", "name": "项目甲", "facts": [
                      {**new_fact("整理反馈并分类", quote="我整理反馈并分类"), "id": "f1"}]}]})
    if with_draft:
        result.update(resume_data={"projects": [{"item_id": "p1", "name": "项目甲",
                                                "polished_bullets": ["整理反馈并分类"]}]},
                      resume_draft="原稿", version_id="version-before",
                      resume_versions=[{"version_id": "version-before", "resume_data": {"projects": []}}])
    return result


OPTIONS = [{"text": "整理反馈并分类", "style": "concise", "fact_ids": ["f1"]},
           {"text": "对反馈进行整理与分类", "style": "action", "fact_ids": ["f1"]}]


class FakeModel:
    def __init__(self, *, options=None, extraction=None, failure=False, fail_verification=False):
        self.options = options if options is not None else copy.deepcopy(OPTIONS)
        self.extraction = extraction or {}
        self.failure = failure
        self.fail_verification = fail_verification
        self.calls = []

    def with_structured_output(self, schema):
        async def invoke(messages):
            self.calls.append((schema.__name__, messages))
            if self.failure:
                raise RuntimeError("synthetic offline model")
            if schema.__name__ == "WordingAdvice":
                return {"options": self.options}
            if schema.__name__ == "SemanticBatch":
                pairs = json.loads(messages[-1].content)
                return {"decisions": [{"id": row["id"], "subject_ok": True, "actions_supported": True,
                                       "objects_supported": True, "results_supported": True, "limits_kept": True,
                                       "unsupported_spans": [], "verdict": "fail" if self.fail_verification else "pass"}
                                      for row in pairs]}
            return {"intents": ["advice"], "edit": {}, "edit_plan": []}
        return SimpleNamespace(ainvoke=invoke)

    async def ainvoke(self, messages):
        self.calls.append(("extraction", messages))
        if self.failure:
            raise RuntimeError("synthetic offline model")
        return AIMessage(content=json.dumps(self.extraction, ensure_ascii=False))


class P1RouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_greeting_intent_is_deterministic_without_model(self):
        model = FakeModel(failure=True)
        for text in ("你好", "在吗？", "hi", "Hello!", "你好呀", "嗨，你好"):
            with self.subTest(text=text):
                result = await route_intents(text, state(), model)
                self.assertEqual(result["intents"], ["greeting"])
                self.assertEqual(result["edit_plan"], [])
        self.assertEqual(model.calls, [])

    async def test_advice_intent_cannot_become_edit_on_question_verbs_or_model_failure(self):
        model = FakeModel(failure=True)
        for text in ("你觉得怎么说更好", "这样写好吗", "哪个更好", "你觉得呢", "怎么改更好",
                     "你觉得把项目甲改成独立完成好吗", "你觉得出一版好吗"):
            with self.subTest(text=text):
                result = await route_intents(text, state(), model)
                self.assertEqual(result["intents"], ["advice"])
                self.assertEqual(result["edit_plan"], [])
        self.assertEqual(model.calls, [])

    async def test_explicit_edit_intent_keeps_writer_plan(self):
        result = await route_intents("把项目甲精简一点", state(), FakeModel())
        self.assertIn("edit", result["intents"])
        self.assertTrue(result["edit_plan"])

    async def test_new_fact_and_advice_are_kept_without_edit(self):
        text = "我还负责Agent设计，你觉得怎么说更好"
        result = await route_intents(text, state(), FakeModel())
        self.assertEqual(result["intents"], ["experience", "advice"])
        self.assertEqual(result["edit_plan"], [])

    async def test_non_action_fact_with_advice_is_not_lost_and_quoted_option_is_not_a_fact(self):
        result = await route_intents("项目甲是三个人的团队，你觉得怎么说更好", state(), FakeModel())
        self.assertEqual(result["intents"], ["experience", "advice"])
        quoted = await route_intents('「我负责Agent设计」这样写好吗', state(), FakeModel())
        self.assertEqual(quoted["intents"], ["advice"])

    async def test_new_fact_advice_and_explicit_edit_are_all_kept(self):
        text = "我还负责Agent设计，你觉得怎么说更好；先把项目甲精简一点"
        result = await route_intents(text, state(), FakeModel())
        self.assertEqual(set(result["intents"]), {"experience", "advice", "edit"})
        self.assertTrue(result["edit_plan"])

    async def test_prefetched_advice_route_matches_direct_route(self):
        model = FakeModel(failure=True)
        current = state()
        direct = await route_intents("怎么改更好", current, model)
        prefetched = await route_intents("怎么改更好", current, model,
                                        prefetched=start_route_call("怎么改更好", current, model))
        self.assertEqual(direct, prefetched)

    async def test_failed_prefetch_cannot_turn_advice_into_edit(self):
        async def failed():
            raise RuntimeError("synthetic router failure")
        result = await route_intents("你觉得怎么改更好", state(), FakeModel(), prefetched=failed())
        self.assertEqual(result["intents"], ["advice"])
        self.assertEqual(result["edit_plan"], [])

    async def test_polite_edit_requests_accompanying_advice_are_explicit(self):
        for text in ("你觉得哪个好，顺便帮我改稿", "你觉得哪个好并帮我改稿", "你觉得哪个好，能不能帮我改稿"):
            with self.subTest(text=text):
                result = await route_intents(text, state(), FakeModel())
                self.assertIn("edit", result["intents"])


class P1DialogueTests(unittest.IsolatedAsyncioTestCase):
    async def test_greeting_at_every_stage_preserves_draft_and_versions_without_model_or_writer(self):
        for stage in rg.STAGES:
            for with_draft in (False, True):
                with self.subTest(stage=stage, with_draft=with_draft):
                    model = FakeModel(failure=True)
                    current = state("你好", stage, with_draft)
                    before = copy.deepcopy(current)
                    with patch.object(rg, "_write_resume_update", new_callable=AsyncMock) as writer, \
                         patch.object(rg, "_extract_info_from_message", new_callable=AsyncMock) as extract:
                        result = await rg.build_graph(model).ainvoke(current, {"configurable": {"thread_id": stage}})
                    writer.assert_not_awaited()
                    extract.assert_not_awaited()
                    self.assertEqual(model.calls, [])
                    for key in ("stage", "resume_data", "resume_draft", "version_id", "resume_versions", "collected_info"):
                        self.assertEqual(result[key], before[key])
                    reply = result["messages"][-1].content
                    for token in ("胡话简历", "读 JD", "挖经历", "一页简历", "核对事实", "PDF", "Word", "上传", "聊经历"):
                        self.assertIn(token, reply)
                    self.assertNotIn("请把目标岗位的招聘JD粘贴给我", reply)

    async def test_jd_input_direct_greeting_and_empty_start_are_friendly(self):
        model = FakeModel(failure=True)
        for messages in ([HumanMessage(content="在吗")], []):
            result = await rg.jd_input_node({**state(with_draft=False), "messages": messages}, model)
            self.assertIn("没有 JD 也能开始", result["messages"][0].content)
        self.assertEqual(model.calls, [])

    async def test_returning_user_sees_name_and_count_without_private_fact_details(self):
        current = state()
        current["profile_summary"] = {"has_facts": True, "name": "虚构小林", "experience_count": 3}
        reply = (await rg.dialogue_node(current, FakeModel(failure=True)))["messages"][0].content
        self.assertIn("虚构小林，欢迎回来", reply)
        self.assertIn("档案里有 3 段经历", reply)
        self.assertIn("贴新 JD", reply)
        self.assertNotIn("整理反馈", reply)

    async def test_advice_at_every_stage_keeps_draft_versions_and_stage(self):
        for stage in rg.STAGES:
            with self.subTest(stage=stage):
                current = state("你觉得怎么说更好", stage)
                before = copy.deepcopy(current)
                with patch.object(rg, "_write_resume_update", new_callable=AsyncMock) as writer:
                    result = await rg.build_graph(FakeModel()).ainvoke(current, {"configurable": {"thread_id": stage}})
                writer.assert_not_awaited()
                for key in ("stage", "resume_data", "resume_draft", "version_id", "resume_versions", "collected_info"):
                    self.assertEqual(result[key], before[key])
                reply = result["messages"][-1].content
                self.assertIn("整理反馈并分类", reply)
                self.assertIn("对反馈进行整理与分类", reply)
                self.assertIn("适合", reply)
                self.assertIn("选一个，或自己改", reply)

    async def test_new_fact_with_advice_is_extracted_but_not_written(self):
        text = "在项目甲我负责Agent设计，你觉得怎么说更好"
        model = FakeModel(extraction={"items": [{"section": "projects", "item_id": "p1", "facts": [
            {"kind": "role", "text": "我负责Agent设计", "source_quote": "我负责Agent设计"}]}]})
        current = state(text, "COLLECTING")
        before = copy.deepcopy(current)
        with patch.object(rg, "_write_resume_update", new_callable=AsyncMock) as writer:
            result = await rg.build_graph(model).ainvoke(current, {"configurable": {"thread_id": "new-fact-advice"}})
        writer.assert_not_awaited()
        self.assertIn("我负责Agent设计", [fact["text"] for fact in result["collected_info"]["projects"][0]["facts"]])
        for key in ("resume_data", "resume_versions", "version_id"):
            self.assertEqual(result[key], before[key])
        self.assertNotIn("synthetic-turn", result["non_candidate_message_ids"])

    async def test_team_scale_with_advice_is_extracted_and_keeps_archive_source(self):
        text = "项目甲是三个人的团队，你觉得怎么说更好"
        model = FakeModel(extraction={"items": [{"section": "projects", "item_id": "p1", "facts": [
            {"kind": "team", "text": "三个人的团队", "source_quote": "三个人的团队"}]}]})
        current = state(text)
        result = await rg.dialogue_node(current, model)
        self.assertIn("三个人的团队", [fact["text"] for fact in result["collected_info"]["projects"][0]["facts"]])
        self.assertNotIn("non_candidate_message_ids", result)
        self.assertNotIn("resume_data", result)

    async def test_stream_does_not_serialize_empty_draft_for_greeting_or_advice(self):
        for text in ("你好", "你觉得怎么说更好", "我负责Agent设计，你觉得怎么说更好"):
            with self.subTest(text=text):
                graph = rg.build_graph(FakeModel())
                with patch.object(rg, "get_graph", return_value=graph), \
                     patch.object(rg, "_serialize_to_resume_data", side_effect=AssertionError("read-only turn")), \
                     patch("app.services.session_store.save_resume_session") as save:
                    chunks = [chunk async for chunk in rg.stream_agent([{"content": text}], "synthetic-stream", FakeModel())]
                self.assertTrue("".join(chunks))
                self.assertEqual(save.call_args.kwargs["resume_data"], {})
                self.assertEqual(save.call_args.kwargs["resume_versions"], [])

    async def test_advice_with_explicit_edit_invokes_writer_and_also_returns_options(self):
        current = state("你觉得怎么说更好；把项目甲精简一点", "EVALUATING")
        written = {"resume_data": current["resume_data"], "collected_info": current["collected_info"],
                   "resume_meta": {}, "resume_versions": [{"version_id": "new-version"}]}
        with patch.object(rg, "_router_model", return_value=FakeModel()), \
             patch.object(rg, "_write_resume_update", new=AsyncMock(return_value=written)) as writer:
            result = await rg.evaluating_node(current, FakeModel())
        writer.assert_awaited_once()
        self.assertIn("可以考虑这几种说法", result["messages"][0].content)
        self.assertEqual(result["resume_versions"], written["resume_versions"])


class P1AdviceGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_facts_and_raw_notes_are_excluded_from_model_context(self):
        current = state()
        current["collected_info"]["projects"][0]["facts"].append(
            {"id": "old", "text": "旧事实标记", "source_quote": "旧事实标记", "status": "deleted"})
        current["resume_data"]["projects"][0]["raw_notes"] = ["原始备注标记"]
        model = FakeModel()
        await wording_advice(current, "这样写好吗", model)
        payload = model.calls[0][1][-1].content
        self.assertNotIn("旧事实标记", payload)
        self.assertNotIn("原始备注标记", payload)

    async def test_unsupported_numbers_tools_and_inactive_fact_references_are_not_suggested(self):
        current = state()
        current["collected_info"]["projects"][0]["facts"].append(
            {"id": "old", "text": "旧事实标记", "source_quote": "旧事实标记", "status": "deleted"})
        for options in (
            [{"text": "提升转化100%", "style": "action", "fact_ids": ["f1"]},
             {"text": "使用Kubernetes上线", "style": "role", "fact_ids": ["f1"]}],
            [{"text": "旧事实标记", "style": "action", "fact_ids": ["old"]}, OPTIONS[0]],
        ):
            reply = await wording_advice(current, "哪个更好", FakeModel(options=options))
            self.assertNotIn("100%", reply)
            self.assertNotIn("Kubernetes", reply)
            self.assertNotIn("旧事实标记", reply)
            self.assertIn("我整理反馈并分类", reply)

    async def test_semantic_failure_or_model_failure_uses_grounded_literal_options(self):
        for model in (FakeModel(fail_verification=True), FakeModel(failure=True)):
            reply = await wording_advice(state(), "哪个更好", model)
            self.assertIn("1.「我整理反馈并分类」", reply)
            self.assertIn("2.「项目甲：我整理反馈并分类」", reply)

    async def test_no_facts_returns_entry_choices_without_inventing_experience(self):
        model = FakeModel(failure=True)
        reply = await wording_advice({}, "你觉得呢", model)
        self.assertIn("还没有足够的本人事实", reply)
        self.assertIn("1.", reply)
        self.assertIn("2.", reply)
        self.assertEqual(model.calls, [])


HALF_SENTENCE = "三个人的团队 有一个设计前端 我负责agent设计 还有一个负责后端还有沙箱 分别是"


class P1IncompleteSentenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_supported_prefix_survives_even_when_model_only_extracts_personal_role(self):
        model = FakeModel(extraction={"items": [{"section": "projects", "item_id": "p1", "facts": [
            {"kind": "role", "text": "我负责agent设计", "source_quote": "我负责agent设计"}]}]})
        result = await rg._extract_info_from_message(HALF_SENTENCE, state()["collected_info"], model)
        texts = [fact["text"] for fact in result["projects"][0]["facts"]]
        self.assertIn("三个人的团队", texts)
        self.assertIn("我负责agent设计", texts)
        self.assertEqual(result["unrecorded"]["clauses"], [])
        self.assertEqual(result["unrecorded"]["incomplete"], ["分别是"])
        self.assertFalse(any("这句没有记下来" in note for note in result["verification_notes"]))
        notice = rg.unrecorded_notice(result, HALF_SENTENCE)
        self.assertIn("「分别是」后面还没说完", notice)
        self.assertNotIn("三个人", notice)
        self.assertEqual(rg.unrecorded_notice(result, "下一轮"), "")
        payload = json.loads(model.calls[0][1][-1].content)
        self.assertNotIn("分别是", payload["message"])

    async def test_empty_model_patch_recovers_prefix_only_when_previous_question_identifies_owner(self):
        token = rg._previous_assistant.set("项目甲的团队有几人，你负责什么？")
        try:
            result = await rg._extract_info_from_message(HALF_SENTENCE, state()["collected_info"], FakeModel())
        finally:
            rg._previous_assistant.reset(token)
        texts = [fact["text"] for fact in result["projects"][0]["facts"]]
        self.assertIn("三个人的团队", texts)
        self.assertIn("负责agent设计", texts)
        self.assertFalse(any("分别是" in text for text in texts))

    async def test_ambiguous_owner_is_not_guessed_and_complete_tail_is_untouched(self):
        current = state()["collected_info"]
        current["projects"].append({"item_id": "p2", "name": "项目乙", "facts": []})
        result = await extract_facts_patch(HALF_SENTENCE, current, FakeModel(),
                                           previous_assistant="项目甲和项目乙分别是什么分工？")
        self.assertEqual(result["items"], [])
        self.assertIn("我负责agent设计", result["uncovered"])
        complete = "三个人的团队，分别是设计、开发和测试"
        self.assertEqual(split_incomplete_tail(complete), (complete, ""))


if __name__ == "__main__":
    unittest.main()
