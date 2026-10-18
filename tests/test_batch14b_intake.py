import shutil
"""第十四批 b：阶段、事实来源、真实图/SSE 与 DOM；所有模型为桩。"""

import json
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import test_conversations as history_fixture  # noqa: E402
from app.agents import resume_graph as graph  # noqa: E402
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch  # noqa: E402
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.schemas.chat import ChatRequest  # noqa: E402
from app.services.ask_user import close_answers, validate_card  # noqa: E402
from app.services.intake import (  # noqa: E402
    apply_submission,
    close_free_reply,
    current_experience,
    deepen_context,
    intake_guidance,
    intake_update,
    record_questions,
)
from app.services.resume_facts import new_fact, normalize_fact_store  # noqa: E402
from app.services.resume_workspace import build_workspace  # noqa: E402
from app.services.structure_plan import plan_guidance  # noqa: E402
from test_campus_and_naming import EchoWriter, ExtractorStub, raw, semantic_stub  # noqa: E402
import test_structure_plan as plan_fixture  # noqa: E402

FIRST = "我想投AI产品经理实习。我自己做了一个AI简历助手，叫胡话简历，从需求到开发都是我一个人做的，现在已经上线了，能通过对话帮学生挖经历写简历。"
QUESTIONS = [
    {"id": "decision", "prompt": "关键产品决策是什么？", "kind": "text"},
    {"id": "evaluation", "prompt": "怎么评测输出好不好？", "kind": "text"},
]
PAGES = {"status": "rendered", "pages": 1, "page_limit": 1, "within_page_limit": True}


def state_with_experiences(count=1):
    state = {
        **graph._init_state(),
        "stage": "COLLECTING",
        "candidate_history_reconciled": True,
        "jd_info": {
            "job_title": "AI产品经理实习",
            "role_profile": {"role_family": "ai_pm"},
        },
        "collected_info": normalize_fact_store(
            {
                "projects": [
                    {
                        "item_id": f"p{i}",
                        "name": "胡话简历" if i == 0 else f"项目{i}",
                        "start_date": "2026-07",
                        "end_date": "至今",
                        "facts": [new_fact("独立开发简历助手并上线")],
                    }
                    for i in range(count)
                ]
            }
        ),
        "intake_progress": {"basics": "skipped", "experiences": "confirmed"},
    }
    return {**state, **intake_update(state)}


class FlowModel(EchoWriter):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.context = {}
        self.public_messages = []

    def bind_tools(self, *args, **kwargs):
        return self

    async def astream(self, messages):
        self.public_messages.append(messages)
        last = messages[-1].content
        if "分阶段规则优先于旧候选：\n" in last:
            self.context = json.loads(last.split("分阶段规则优先于旧候选：\n")[1])
        yield AIMessageChunk(content="继续整理这段经历。")
        if self.context.get("subject"):
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "index": 0,
                        "id": "call",
                        "name": "ask_user",
                        "args": json.dumps(
                            {
                                "subject": self.context["subject"],
                                "questions": QUESTIONS,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            )

    def with_structured_output(self, schema):
        async def invoke(messages):
            self.calls.append(schema.__name__)
            if schema.__name__ == "StructurePlan":
                return {
                    "recommended": {
                        "label": "项目实践",
                        "section_order": list(
                            plan_fixture.card()["recommended"]["section_order"]
                        ),
                        "experience_plan": [],
                        "positioning": "",
                        "thesis": "",
                    },
                    "alternatives": [],
                }
            if schema.__name__ == "RepairOutput":
                return {"bullets": []}
            result = await EchoWriter.ainvoke(self, messages)
            return result["writer"] if schema.__name__ == "WriterDraft" else result

        return SimpleNamespace(ainvoke=invoke)


async def extract_stub(message, current, llm):
    if "叫胡话简历" in message:
        candidate = {
            "items": [
                {
                    "section": "projects",
                    "name": "胡话简历",
                    "facts": [
                        raw("从需求到开发都是我一个人做的", kind="role"),
                        raw("现在已经上线了", kind="status_limit"),
                        raw("能通过对话帮学生挖经历写简历"),
                    ],
                    "raw_notes": [FIRST],
                }
            ]
        }
    else:
        candidate = {"items": []}
    return apply_fact_patch(
        current, await extract_facts_patch(message, current, ExtractorStub(candidate))
    )


class IntakeUnitTest(unittest.TestCase):
    def test_guest_basics_and_user_provenance(self):
        state = graph._init_state()
        card = build_workspace(state)["guidance"]
        self.assertEqual(card["kind"], "intake_basics")
        data = {
            "kind": "basics",
            "values": {
                "name": "张三",
                "school": "测试大学",
                "major": "计算机",
                "degree": "本科",
                "graduation": "2027-06",
                "location": "上海",
                "availability": "每周4天，3个月",
            },
        }
        message = HumanMessage(
            content="基本信息：张三，测试大学，计算机，本科，2027-06，上海，每周4天，3个月",
            id="self-1",
        )
        state.update(apply_submission(state, data, message))
        state.update(intake_update(state))
        self.assertEqual(state["intake_stage"], "target")
        facts = state["collected_info"]
        self.assertEqual(facts["basic_info"]["availability"], "每周4天，3个月")
        self.assertEqual(facts["education"][0]["end_date"], "2027-06")
        for fact in facts["basic_info_facts"] + facts["education"][0]["facts"]:
            self.assertEqual(fact["turn_id"], "self-1")
            self.assertEqual(fact["source"], "chat")
            self.assertEqual(fact["sources"][0]["name"], "用户本人填写")
            self.assertIn(fact["source_quote"], message.content)
        self.assertIsNone(intake_guidance(state))

    def test_skip_basics_is_permanent_and_complete_profile_needs_no_card(self):
        state = {
            **graph._init_state(),
            "intake_account": True,
            "intake_profile": {
                "basic_info": {
                    "name": "张三",
                    "phone": "13900000000",
                    "email": "private@example.test",
                },
                "education": [
                    {"school": "测试大学", "degree": "本科", "end_date": "2027.06"}
                ],
            },
        }
        card = intake_guidance(state)
        self.assertIsNone(card)
        self.assertEqual(intake_update(state)["intake_progress"]["basics"], "from_profile")
        free = {
            **state,
            "collected_info": {"basic_info": {"name": "张三"}},
            "intake_progress": {"basics": "deferred"},
            "messages": [HumanMessage(content="我叫张三。")],
        }
        self.assertEqual(intake_update(free)["intake_progress"]["basics"], "provided")
        state.update(
            apply_submission(
                state,
                {"kind": "basics", "skipped": True},
                HumanMessage(content="跳过基本信息", id="skip"),
            )
        )
        for _ in range(3):
            state.update(intake_update(state))
            self.assertIsNone(intake_guidance(state))
        self.assertFalse(state["collected_info"].get("basic_info", {}).get("phone"))

    def test_experiences_merge_identity_and_summary_is_sourced_fact(self):
        state = state_with_experiences()
        payload = {
            "kind": "experiences",
            "items": [
                {
                    "item_id": "p0",
                    "name": "胡话简历",
                    "type": "项目",
                    "start": "2026-07",
                    "end": "至今",
                    "role": "独立开发",
                    "summary": "需要抽取的原话",
                },
                {
                    "name": "测试竞赛",
                    "type": "竞赛",
                    "start": "2026-08",
                    "end": "2026-09",
                    "role": "参赛者",
                    "summary": "",
                },
            ],
        }
        message = HumanMessage(content="经历清单：胡话简历，测试竞赛", id="form")
        state.update(apply_submission(state, payload, message))
        state.update(apply_submission(state, payload, message))
        self.assertEqual(len(state["collected_info"]["projects"]), 1)
        self.assertEqual(len(state["collected_info"]["awards"]), 1)
        item = state["collected_info"]["projects"][0]
        self.assertEqual(item["item_id"], "p0")
        self.assertEqual(item["end_date"], "至今")
        self.assertEqual(len([f for f in item["facts"] if f.get("text") == "需要抽取的原话" and not f.get("field")]), 1)
        self.assertIn("需要抽取的原话", item["raw_notes"])
        self.assertTrue(
            all(f["turn_id"] == "form" for f in item["facts"] if f.get("field"))
        )

    def test_schema_accepts_contacts_rejects_empty_names_and_invalid_months(self):
        base = {"messages": [{"role": "user", "content": "表单"}]}
        accepted = ChatRequest.model_validate({**base, "intake": {"kind": "basics", "values": {"phone": "13900000000"}}})
        self.assertEqual(accepted.intake.values.phone, "13900000000")
        for intake in (
            {"kind": "basics", "values": {"graduation": "2027-19"}},
            {"kind": "experiences", "items": [{"name": " ", "type": "项目"}]},
            {"kind": "experiences", "items": []},
        ):
            with self.subTest(intake=intake), self.assertRaises(ValidationError):
                ChatRequest.model_validate({**base, "intake": intake})

    def test_legacy_checkpoint_infers_without_regressing(self):
        state = state_with_experiences()
        state.pop("intake_stage")
        state.pop("intake_progress")
        state["collected_info"]["basic_info"] = {"name": "张三"}
        self.assertEqual(intake_update(state)["intake_stage"], "deepen")
        answered = {
            **state,
            "closed_questions": [
                {
                    "subject": "p0",
                    "dimension": dimension,
                    "reason": "answered",
                    "turn_id": "old-turn",
                }
                for dimension in ("decision", "evaluation")
            ],
        }
        self.assertEqual(intake_update(answered)["intake_stage"], "ready")
        for stage in ("BUILDING", "EVALUATING", "EXPORT"):
            old = {**state, "stage": stage}
            self.assertEqual(intake_update(old)["intake_stage"], "ready")
            self.assertIsNone(intake_guidance(old))
        self.assertEqual(
            intake_update({**state, "intake_stage": "deepen", "jd_info": {}})[
                "intake_stage"
            ],
            "deepen",
        )

    def test_two_experiences_are_deepened_sequentially_and_closed(self):
        state = state_with_experiences(2)
        for index in range(2):
            section, item = current_experience(state)
            self.assertEqual(item["item_id"], f"p{index}")
            context = deepen_context(state)
            self.assertIn("评测方式", str(context))
            self.assertIn("AI 产品经理", context["playbook"])
            self.assertIn("可选", context["dimensions"]["adoption"])
            self.assertIn("个人开发项目不必问用户数", context["instruction"])
            self.assertFalse(
                validate_card(
                    {"subject": "不相关经历", "questions": QUESTIONS}, state, "bad"
                )
            )
            card = validate_card(
                {"subject": item["name"], "questions": QUESTIONS}, state, f"ask{index}"
            )
            reply = AIMessage(
                content="补充两点。", additional_kwargs={"ask_user": card}
            )
            state.update(record_questions(state, [reply]))
            state["messages"] = [reply]
            state["closed_questions"] = close_answers(
                state,
                "都跳过",
                {
                    "turn_id": card["turn_id"],
                    "items": [{"id": q["id"], "skipped": True} for q in QUESTIONS],
                },
            )
            state.update(intake_update(state))
            self.assertTrue(state["intake_progress"]["deepen"][f"p{index}"]["complete"])
        self.assertEqual(state["intake_stage"], "ready")

    def test_direct_write_and_full_skip_bypass_intake(self):
        for text in ("直接写", "先出一版", "跳过"):
            self.assertEqual(
                intake_update(
                    {**graph._init_state(), "messages": [HumanMessage(content=text)]}
                )["intake_stage"],
                "ready",
            )
        self.assertNotEqual(
            intake_update(
                {
                    **graph._init_state(),
                    "messages": [HumanMessage(content="先别生成简历")],
                }
            )["intake_stage"],
            "ready",
        )
        self.assertNotEqual(
            intake_update(
                {
                    **graph._init_state(),
                    "messages": [HumanMessage(content="不要直接写")],
                }
            )["intake_stage"],
            "ready",
        )
        self.assertFalse(graph._explicit_generate_requested(FIRST))

    def test_no_time_no_plan_even_after_deepening_and_other_topics_do_not_close(self):
        state = state_with_experiences()
        item = state["collected_info"]["projects"][0]
        item.pop("start_date")
        item.pop("end_date")
        card = validate_card(
            {"subject": "胡话简历", "questions": QUESTIONS}, state, "asked"
        )
        reply = AIMessage(content="补充两点。", additional_kwargs={"ask_user": card})
        state.update(record_questions(state, [reply]))
        state["messages"] = [reply]
        self.assertEqual(close_free_reply(state, "我还有另一个项目", []), [])
        self.assertEqual(close_free_reply(state, "你好", []), [])
        state["closed_questions"] = close_free_reply(state, "都不知道", [])
        state.update(intake_update(state))
        self.assertEqual(state["intake_stage"], "deepen")
        self.assertEqual(intake_guidance(state)["kind"], "intake_experiences")

    def test_generic_playbooks_expose_stable_ids_and_at_most_four_dimensions(self):
        state = state_with_experiences()
        state["jd_info"]["role_profile"]["role_family"] = "backend"
        context = deepen_context(state)
        for dimension in context["dimensions"]:
            self.assertRegex(dimension, r"^[a-z][a-z0-9_-]*$")
        self.assertIn("后端", context["playbook"])
        state = state_with_experiences()
        state["intake_progress"]["deepen"]["p0"]["asked_dimensions"] = [
            "problem",
            "my_work",
            "tech_stack",
        ]
        card = validate_card(
            {"subject": "胡话简历", "questions": QUESTIONS}, state, "limit"
        )
        self.assertEqual(len(card["questions"]), 1)

    def test_plan_shows_only_present_or_explicitly_retained_sections(self):
        state = state_with_experiences()
        card = plan_fixture.card()
        guidance = plan_guidance(
            card, state["collected_info"], retained_sections=["education"]
        )
        self.assertEqual(
            guidance["structure_plan"]["recommended"]["section_order"],
            ["projects", "education"],
        )
        state.update(pending_plan=card, messages=[HumanMessage(content="保留证书栏目")])
        self.assertIn(
            "certificates",
            build_workspace(state)["guidance"]["structure_plan"]["recommended"][
                "section_order"
            ],
        )

    @unittest.skipUnless(shutil.which('node'), 'node is not installed')

    def test_dom(self):
        result = subprocess.run(
            ["node", str(ROOT / "tests/intake.dom.js")], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class IntakeFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.model = FlowModel()
        self.compiled = graph.build_graph(self.model)
        for context in (
            patch.object(graph, "get_graph", return_value=self.compiled),
            patch.object(
                graph,
                "_make_non_streaming_llm",
                side_effect=lambda model, **kwargs: model,
            ),
            patch.object(graph, "_extract_info_from_message", side_effect=extract_stub),
            patch.object(
                graph,
                "run_triage",
                AsyncMock(
                    return_value=TriageDecision(
                        action=TriageAction.READY_TO_BUILD,
                        reason="故意过早成稿的路由桩",
                    )
                ),
            ),
            patch("app.services.session_store.save_candidate_intake"),
            patch("app.services.session_store.save_resume_session"),
            patch(
                "app.agents.tailor_pipeline.measure_rendered_pages", return_value=PAGES
            ),
            patch("app.services.fact_guard.verify_semantics", semantic_stub),
            patch.object(get_settings(), "LLM_PLAN_CONFIRM", True),
        ):
            self.enterContext(context)

    async def turn(self, text, **payload):
        async for _ in graph.stream_agent(
            [{"role": "user", "content": text}], "intake-flow", self.model, **payload
        ):
            pass
        return (
            await self.compiled.aget_state(
                {"configurable": {"thread_id": "intake-flow"}}
            )
        ).values

    async def test_plan_gate_also_covers_the_editing_writer_entry(self):
        state = state_with_experiences()
        state["messages"] = [HumanMessage(content="请把简历整体润色得专业一点")]
        result = await graph._write_resume_update(state, self.model)
        self.assertTrue(result["intake_pending"])
        self.assertFalse(result.get("pending_plan"))
        self.assertEqual(self.model.calls, [])

    async def test_reported_first_turn_then_form_deepening_plan_and_named_draft(self):
        state = await self.turn(FIRST)
        self.assertFalse(state.get("pending_plan"))
        self.assertNotIn("StructurePlan", self.model.calls)
        card = build_workspace(state)["guidance"]
        self.assertEqual(card["kind"], "intake_experiences")
        self.assertEqual(card["items"][0]["name"], "胡话简历")
        self.assertEqual(card["items"][0]["role"], "")
        self.assertIn("本轮正文提问预算：0 个问句", self.model.public_messages[-1][-1].content)
        self.assertIn("本轮卡片已在收集经历清单", self.model.public_messages[-1][-1].content)
        item = card["items"][0]
        state = await self.turn(
            "经历清单：胡话简历，2026-07 至 至今，独立开发",
            intake={
                "kind": "experiences",
                "items": [
                    {
                        **item,
                        "start": "2026-07",
                        "end": "至今",
                        "role": "独立开发",
                        "summary": "",
                    }
                ],
                "skipped": False,
            },
        )
        self.assertEqual(state["intake_stage"], "deepen")
        card = build_workspace(state)["guidance"]
        self.assertEqual(card["kind"], "ask_user")
        self.assertEqual(card["subject"], "胡话简历")
        state = await self.turn(
            "关键产品决策：不知道；评测方式：跳过",
            answers={
                "turn_id": card["turn_id"],
                "items": [
                    {"id": "decision", "unknown": True},
                    {"id": "evaluation", "skipped": True},
                ],
            },
        )
        self.assertFalse(state.get("pending_plan"))
        self.assertEqual(build_workspace(state)["guidance"]["kind"], "intake_basics")
        state = await self.turn(
            "跳过基本信息，继续。", intake={"kind": "basics", "skipped": True}
        )
        self.assertEqual(state["intake_stage"], "ready")
        card = build_workspace(state)["guidance"]
        self.assertEqual(card["kind"], "structure_plan")
        self.assertEqual(
            card["structure_plan"]["recommended"]["section_order"], ["projects"]
        )
        state = await self.turn(
            "按推荐写", plan_choice={"option": "按推荐写", "bullet_style": "plain"}
        )
        item = state["resume_data"]["projects"][0]
        self.assertEqual(item["name"], "胡话简历")
        self.assertEqual(item["start_date"], "2026-07")
        self.assertEqual(item["end_date"], "至今")
        self.assertNotIn("[待补]", item["name"])
        self.assertEqual(len(state["collected_info"]["projects"]), 1)

    async def test_free_text_persona_fixture_reaches_draft_without_touching_cards(self):
        from test_persona_regressions import FIXTURES, facts_for

        facts = await facts_for("service")
        self.enterContext(
            patch.object(
                graph, "_extract_info_from_message", AsyncMock(return_value=facts)
            )
        )
        state = await self.turn(FIXTURES["service"]["initial"])
        self.assertTrue(state["collected_info"]["work_experience"])
        # 旧 fixture 的纯文字成稿请求必须继续可用，不要求点表单。
        state = await self.turn("先出一版简历")
        self.assertTrue(state["resume_data"]["work_experience"])
        self.assertEqual(state["intake_stage"], "ready")
        body = str(state["resume_data"]["work_experience"])
        self.assertIn("禾木家居", body)
        self.assertIn("800", body)

    async def test_free_text_can_complete_all_stages_without_direct_write(self):
        async def dated(message, current, llm):
            if "2026年7月" not in message:
                return await extract_stub(message, current, llm)
            result = deepcopy(current)
            item = result["projects"][0]
            item.update(start_date="2026-07", end_date="至今")
            item["facts"] += [
                {**new_fact("2026-07"), "field": "start_date"},
                {**new_fact("至今"), "field": "end_date"},
            ]
            return result

        self.enterContext(
            patch.object(graph, "_extract_info_from_message", side_effect=dated)
        )
        state = await self.turn(FIRST)
        self.assertEqual(
            build_workspace(state)["guidance"]["kind"], "intake_experiences"
        )
        state = await self.turn("胡话简历是2026年7月开始，到现在还在做。")
        self.assertEqual(state["intake_stage"], "deepen")
        self.assertEqual(build_workspace(state)["guidance"]["subject"], "胡话简历")
        state = await self.turn("关键决策和评测方式都暂时不知道。")
        self.assertEqual(build_workspace(state)["guidance"]["kind"], "intake_basics")
        state = await self.turn("继续")
        self.assertEqual(build_workspace(state)["guidance"]["kind"], "structure_plan")
        state = await self.turn("按推荐写")
        self.assertTrue(state["resume_versions"])
        self.assertFalse(
            any(
                m.additional_kwargs.get("intake")
                for m in state["messages"]
                if isinstance(m, HumanMessage)
            )
        )

    async def test_summary_is_direct_fact_and_full_skip_writes_immediately(self):
        state = await self.turn(FIRST)
        item = build_workspace(state)["guidance"]["items"][0]
        with patch.object(
            graph, "_extract_info_from_message", side_effect=extract_stub
        ) as extract:
            state = await self.turn(
                "经历清单：胡话简历，简介：通过对话帮助学生整理经历",
                intake={
                    "kind": "experiences",
                    "items": [
                        {
                            **item,
                            "start": "2026-07",
                            "end": "至今",
                            "role": "独立开发",
                            "summary": "通过对话帮助学生整理经历",
                        }
                    ],
                },
            )
        extract.assert_not_called()
        self.assertTrue(any(f.get("text") == "通过对话帮助学生整理经历" and f.get("question_id") == "summary"
                            for f in state["collected_info"]["projects"][0]["facts"]))
        self.assertEqual(len(state["collected_info"]["projects"]), 1)
        state = await self.turn("跳过")
        self.assertFalse(state.get("pending_plan"))
        self.assertTrue(state["resume_data"]["projects"])
        self.assertEqual(state["intake_stage"], "ready")

    async def test_failure_preserves_form_fields_and_retry_merges(self):
        state = await self.turn(FIRST)
        item = build_workspace(state)["guidance"]["items"][0]
        payload = {
            "kind": "experiences",
            "items": [
                {
                    **item,
                    "start": "2026-07",
                    "end": "至今",
                    "role": "独立开发",
                    "summary": "",
                }
            ],
        }
        # 骨架持久化发生在公开回复之前。
        with (
            patch.object(
                graph,
                "_collection_reply",
                AsyncMock(side_effect=RuntimeError("synthetic failure")),
            ),
            patch.object(
                graph, "_persist_intake", wraps=graph._persist_intake
            ) as persist,
        ):
            with self.assertRaises(Exception):
                await self.turn("经历清单：胡话简历", intake=payload)
            saved = persist.call_args.args[1]
        self.assertEqual(saved["projects"][0]["start_date"], "2026-07")
        state = await self.turn("经历清单：胡话简历", intake=payload)
        self.assertEqual(len(state["collected_info"]["projects"]), 1)


class IntakeHistoryTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = history_fixture.ConversationPersistenceTest.asyncSetUp
    open_checkpointer = history_fixture.ConversationPersistenceTest.open_checkpointer
    cleanup = history_fixture.ConversationPersistenceTest.cleanup
    create = history_fixture.ConversationPersistenceTest.create
    checkpoint = history_fixture.ConversationPersistenceTest.checkpoint

    async def test_sse_basics_provenance_and_checkpoint_reopen(self):
        model = FlowModel()
        self.graph = graph.build_graph(model, checkpointer=self.saver)
        sid = await self.create()
        await self.checkpoint(sid, **graph._init_state())
        with (
            patch("app.api.chat._get_llm", return_value=model),
            patch.object(graph, "get_graph", return_value=self.graph),
            patch("app.api.chat.get_graph", return_value=self.graph),
        ):
            response = await self.client.post(
                "/api/chat/stream",
                json={
                    "session_id": sid,
                    "messages": [{"role": "user", "content": "基本信息：张三，上海"}],
                    "intake": {
                        "kind": "basics",
                        "values": {"name": "张三", "location": "上海"},
                    },
                },
            )
        self.assertNotIn('"error"', response.text)
        await self.saver_context.__aexit__(None, None, None)
        await self.open_checkpointer()
        detail = (await self.client.get("/api/chat/conversations/" + sid)).json()
        self.assertEqual(detail["workspace"]["intake_stage"], "target")
        state = (
            await self.graph.aget_state({"configurable": {"thread_id": sid}})
        ).values
        message = next(m for m in state["messages"] if isinstance(m, HumanMessage))
        self.assertEqual(
            state["collected_info"]["basic_info_facts"][0]["turn_id"], message.id
        )
        self.assertEqual(state["intake_progress"]["basics"], "confirmed")


import test_profile_archive as profile_fixture  # noqa: E402


class IntakeProfileTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = profile_fixture.ArchiveTests.asyncSetUp
    asyncTearDown = profile_fixture.ArchiveTests.asyncTearDown
    add = profile_fixture.ArchiveTests.add

    async def test_real_profile_service_prefills_only_this_accounts_basics_and_education(
        self,
    ):
        from app.services import profile_bridge

        self.add(category="basic", subject="本人", field="name", value="张三")
        self.add(category="basic", subject="本人", field="phone", value="13900000000")
        self.add(
            category="basic",
            subject="本人",
            field="email",
            value="private@example.test",
        )
        self.add(
            category="education", subject="测试大学", field="major", value="计算机"
        )
        self.add(category="education", subject="测试大学", field="degree", value="本科")
        self.add(
            category="education", subject="测试大学", field="end_date", value="2027.06"
        )
        self.add(
            category="project",
            subject="不自动导入的项目",
            field="description",
            value="不自动导入的内容",
        )
        self.add(
            account="b", category="basic", subject="本人", field="name", value="其他人"
        )
        with patch.object(profile_bridge, "SessionLocal", self.factory):
            prefill = profile_bridge.intake_profile_state("account:a")
        self.assertEqual(prefill["intake_profile"]["basic_info"]["phone"], "13900000000")
        self.assertEqual(prefill["intake_profile"]["basic_info"]["email"], "private@example.test")
        self.assertNotIn("不自动导入", str(prefill["intake_profile"]))
        self.assertEqual(prefill["profile_items"][0]["name"], "不自动导入的项目")
        self.assertNotIn("其他人", str(prefill))
        state = {**graph._init_state(), **prefill}
        self.assertNotEqual((build_workspace(state).get("guidance") or {}).get("kind"), "intake_basics")
        self.assertEqual(intake_update(state)["intake_progress"]["basics"], "from_profile")
        from app.services.intake import basics_values
        values = basics_values(prefill["intake_profile"])
        self.assertEqual(values["school"], "测试大学")
        self.assertEqual(values["graduation"], "2027-06")
