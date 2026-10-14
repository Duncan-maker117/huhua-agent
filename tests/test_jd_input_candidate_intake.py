"""JD intake cannot acknowledge personal evidence without collecting it."""

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.resume_graph import _init_state, build_graph, jd_input_node, stream_agent  # noqa: E402
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402


SOURCE = "我在课程项目画了提交和确认流程，是个未开发上线的原型。"


def wrap():
    # The decision's shortened snippet must not become the extraction source.
    return TriageDecision(
        action=TriageAction.WRAP_EXPERIENCE,
        reason="合成本人经历",
        experience_snippet="我在课程项目画了提交和确认流程",
    )


class JdInputCandidateIntakeTests(unittest.IsolatedAsyncioTestCase):
    def model_patches(self):
        return (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=object()),
            patch("app.agents.resume_graph.run_triage", AsyncMock(side_effect=[wrap()])),
            patch("app.agents.resume_graph._extract_info_from_message", AsyncMock(side_effect=lambda text, facts, model: facts)),
            patch("app.agents.resume_graph.stream_public_reply", AsyncMock(return_value=AIMessage(content="已整理本人材料。", id="receipt"))),
        )

    async def test_wrap_collects_full_source_once_and_keeps_jd_state(self):
        state = _init_state()
        state["messages"] = [HumanMessage(content=SOURCE, id="human")]
        before = copy.deepcopy(state)
        make, triage_patch, extract_patch, public = self.model_patches()
        with make, triage_patch as triage, extract_patch as extract, public:
            result = await jd_input_node(state, object())
        triage.assert_awaited_once()
        extract.assert_awaited_once()
        self.assertEqual(extract.await_args.args[0], SOURCE)
        self.assertEqual(result["stage"], "COLLECTING")
        self.assertEqual(state, before)
        self.assertNotIn("requested_task", result)
        self.assertEqual(result.get("jd_info", state["jd_info"]), state["jd_info"])
        self.assertEqual(result.get("jd_skipped", state["jd_skipped"]), state["jd_skipped"])
        self.assertFalse(result.get("jd_text"))
        facts = [fact for item in result["collected_info"]["projects"] for fact in item["facts"]]
        self.assertEqual([fact["source_quote"] for fact in facts], [SOURCE])
        self.assertIn("未开发上线", result["resume_draft"])

    async def test_non_candidate_sources_never_enter_collecting_even_if_triage_wraps(self):
        sources = [(SOURCE, kind) for kind in ("jd", "review", "reference")]
        sources += [
            ("岗位职责：负责产品设计。" + SOURCE, None),
            ("参考材料：\n" + SOURCE, None),
            ("他人简历：\n" + SOURCE, None),
            ("帮我编造一段项目经历。", None),
        ]
        for text, kind in sources:
            with self.subTest(kind=kind, text=text):
                state = _init_state()
                state["messages"] = [HumanMessage(content=text, additional_kwargs={"career_material_type": kind} if kind else {})]
                with (
                    patch("app.agents.resume_graph._make_non_streaming_llm", return_value=object()),
                    patch("app.agents.resume_graph.run_triage", AsyncMock(return_value=wrap())),
                    patch("app.agents.resume_graph.collecting_node", AsyncMock(side_effect=AssertionError("non-candidate intake"))) as collect,
                    patch("app.agents.resume_graph.stream_public_reply", AsyncMock(return_value=AIMessage(content="请提供本人经历。"))),
                ):
                    result = await jd_input_node(state, object())
                collect.assert_not_awaited()
                self.assertNotIn("collected_info", result)
                self.assertNotIn("resume_data", result)

    async def test_other_triage_actions_keep_existing_behavior(self):
        for action in (TriageAction.ASK_JD, TriageAction.ASK_CLARIFY, TriageAction.ASK_EXPERIENCE):
            with self.subTest(action=action):
                state = {**_init_state(), "messages": [HumanMessage(content="还没有想好先说哪段。") ]}
                with (
                    patch("app.agents.resume_graph._make_non_streaming_llm", return_value=object()),
                    patch("app.agents.resume_graph.run_triage", AsyncMock(return_value=TriageDecision(action=action, reason="合成"))),
                    patch("app.agents.resume_graph.collecting_node", AsyncMock(side_effect=AssertionError("not WRAP"))) as collect,
                    patch("app.agents.resume_graph.stream_public_reply", AsyncMock(return_value=AIMessage(content="请补充。"))),
                ):
                    result = await jd_input_node(state, object())
                collect.assert_not_awaited()
                self.assertNotIn("collected_info", result)

    async def test_collecting_build_request_finishes_in_same_turn(self):
        state = {**_init_state(), "messages": [HumanMessage(content=SOURCE)]}
        collected = {"projects": [{"name": "合成课程项目", "description": SOURCE}]}
        built = {"stage": "EVALUATING", "resume_data": {"projects": [{"name": "合成课程项目"}]}}
        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=object()),
            patch("app.agents.resume_graph.run_triage", AsyncMock(side_effect=[wrap()])),
            patch("app.agents.resume_graph.collecting_node", AsyncMock(return_value={"stage": "BUILDING", "collected_info": collected})),
            patch("app.agents.resume_graph.building_node", AsyncMock(return_value=built)) as building,
        ):
            result = await jd_input_node(state, object())
        building.assert_awaited_once()
        build_state = building.await_args.args[0]
        self.assertEqual(build_state["collected_info"], collected)
        self.assertEqual(build_state["requested_task"], "auto")
        self.assertEqual(build_state["jd_info"], state["jd_info"])
        self.assertEqual(result["stage"], "EVALUATING")
        self.assertEqual(result["resume_data"], built["resume_data"])

    async def test_stream_uses_existing_canonical_save_before_receipt(self):
        graph = build_graph(object())
        events = []
        saved = []

        def save(**kwargs):
            saved.append(copy.deepcopy(kwargs))
            events.append("saved")

        make, triage_patch, extract, public = self.model_patches()
        with (
            make, triage_patch as triage, extract, public,
            patch("app.agents.resume_graph.get_graph", return_value=graph),
            patch("app.services.session_store.save_candidate_intake"),
            patch("app.services.session_store.save_resume_session", side_effect=save),
        ):
            async for chunk in stream_agent([{"content": SOURCE}], "synthetic-jd-intake", object()):
                events.append(chunk)
        triage.assert_awaited_once()
        self.assertEqual(events, ["saved", "已整理本人材料。"])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["stage"], "COLLECTING")
        facts = [fact for item in saved[0]["collected_info"]["projects"] for fact in item["facts"]]
        self.assertEqual([fact["source_quote"] for fact in facts], [SOURCE])
        self.assertIn("未开发上线", saved[0]["resume_draft"])
        checkpoint = await graph.aget_state({"configurable": {"thread_id": "synthetic-jd-intake"}})
        self.assertEqual(checkpoint.values["requested_task"], "auto")
        self.assertFalse(checkpoint.values.get("jd_info"))
        self.assertFalse(checkpoint.values.get("jd_skipped"))

    async def test_stream_save_failure_does_not_emit_a_saved_receipt(self):
        graph = build_graph(object())
        chunks = []
        make, triage, extract, public = self.model_patches()
        with (
            make, triage, extract, public,
            patch("app.agents.resume_graph.get_graph", return_value=graph),
            patch("app.services.session_store.save_candidate_intake"),
            patch("app.services.session_store.save_resume_session", side_effect=RuntimeError("synthetic storage failure")),
        ):
            with self.assertRaises(RuntimeError):
                async for chunk in stream_agent([{"content": SOURCE}], "synthetic-jd-intake-failure", object()):
                    chunks.append(chunk)
        self.assertEqual(chunks, [])
        checkpoint = await graph.aget_state({"configurable": {"thread_id": "synthetic-jd-intake-failure"}})
        self.assertTrue(checkpoint.values["messages"][-1].additional_kwargs["resume_save_failed"])


if __name__ == "__main__":
    unittest.main()
