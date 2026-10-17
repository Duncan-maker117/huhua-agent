"""真实回放暴露的提问冲突与角色预填；仅使用公开合成材料和桩模型。"""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from test_batch14b_intake import QUESTIONS, graph, state_with_experiences
from app.agents.public_reply import stream_public_reply
from app.services.ask_user import can_ask_user, question_context, validate_card
from app.services.intake import intake_guidance, intake_update
from app.services.resume_workspace import build_workspace


def form_states():
    experiences = state_with_experiences()
    experiences["intake_stage"] = "basics"
    experiences["intake_progress"] = {}
    item = experiences["collected_info"]["projects"][0]
    item.pop("start_date")
    item.pop("end_date")
    legacy = deepcopy(experiences)
    legacy.pop("intake_stage")
    legacy.pop("intake_progress")
    deferred = state_with_experiences()
    deferred["intake_progress"]["basics"] = "deferred"
    deferred["intake_progress"]["deepen"]["p0"].update(complete=True, rounds=1)
    return [("basics", graph._init_state()), ("experiences", experiences),
            ("legacy_experiences", legacy), ("deferred_basics", deferred)]


class UnsolicitedToolModel:
    """故意忽略工具是否提供，模拟仍返回 ask_user 的兼容模型。"""

    def __init__(self):
        self.bindings = []
        self.messages = []
        self.body = "请先确认卡片中的信息。"

    def bind_tools(self, tools, **kwargs):
        self.bindings.append(tools)
        return self

    async def astream(self, messages):
        self.messages = messages
        yield AIMessageChunk(content=self.body, tool_call_chunks=[{
            "index": 0, "id": "unexpected", "name": "ask_user",
            "args": json.dumps({"subject": "胡话简历", "questions": QUESTIONS}, ensure_ascii=False),
        }])


class IntakePrefillRegressionTest(unittest.TestCase):
    def test_only_identity_fields_prefill_role_without_mutating_facts(self):
        for fields, facts, expected in (
            ({}, [{"kind": "role", "text": "独立完成AI简历助手「胡话简历」从需求到开发的全流程"}], ""),
            ({}, [{"field": "role", "kind": "role", "text": "独立完成AI简历助手从需求到开发的全流程"}], ""),
            ({"role": "负责开发"}, [], ""),
            ({"role": "完成公众号运营"}, [], ""),
            ({"role": "拍摄短视频并运营"}, [], ""),
            ({"role": "在校园读书协会帮忙"}, [], ""),
            ({"title": "在咖啡店做兼职"}, [], ""),
            ({"role": "独立开发者"}, [], "独立开发者"),
            ({"role": "产品实习生"}, [], "产品实习生"),
            ({}, [{"field": "role", "text": "负责人"}], "负责人"),
            ({"title": "产品实习生"}, [{"kind": "role", "text": "独立完成需求分析和原型设计"}], "产品实习生"),
            ({"role": "旧负责人"}, [{"field": "role", "text": "产品实习生", "status": "active"},
                                    {"field": "role", "text": "负责人", "status": "superseded"}], "产品实习生"),
        ):
            with self.subTest(fields=fields, facts=facts):
                state = form_states()[1][1]
                item = state["collected_info"]["projects"][0]
                item.update(fields, facts=facts)
                before = deepcopy(state)
                self.assertEqual(intake_guidance(state)["items"][0]["role"], expected)
                self.assertEqual(state, before)

    def test_ops_initial_needs_experience_skeleton_card(self):
        fixtures = Path(__file__).resolve().parents[1] / "evaluation/persona-ux-2026-10-15/fixtures.json"
        text = json.loads(fixtures.read_text())["ops"]["initial"]
        # 与冻结首轮一致：基本信息/方向已知，两段经历没有日期骨架。
        state = {**graph._init_state(), "stage": "COLLECTING",
                 "messages": [HumanMessage(content=text)],
                 "jd_info": {"job_title": "新媒体运营"},
                 "collected_info": {"basic_info": {"name": "陈夏"},
                                    "work_experience": [{"company": "工作经历（待补公司/岗位名）",
                                                         "title": "在咖啡店做兼职"}],
                                    "campus": [{"name": "校园读书协会", "role": "在校园读书协会帮忙"}]}}
        state.update(intake_update(state))
        self.assertEqual(state["intake_stage"], "experiences")
        self.assertEqual(state["intake_progress"]["basics"], "provided")
        view = build_workspace(state)
        self.assertEqual(view["guidance"]["kind"], "intake_experiences")
        self.assertEqual(len(view["guidance"]["items"]), 2)
        self.assertIn("本轮正文提问预算：0 个问句", question_context(state))
        self.assertIn("本轮卡片已在收集经历清单", question_context(state))


class PublicQuestionBudgetTest(unittest.IsolatedAsyncioTestCase):
    async def test_intake_card_blocks_binding_and_unsolicited_tool_results(self):
        for name, state in form_states():
            with self.subTest(stage=name):
                expected = intake_guidance(state)
                model = UnsolicitedToolModel()
                reply = await stream_public_reply(model, [], ask_state=state)
                self.assertFalse(model.bindings)
                self.assertFalse(can_ask_user(state))
                self.assertNotIn("ask_user", reply.additional_kwargs)
                self.assertEqual(reply.content, model.body)
                prompt = model.messages[-1].content
                self.assertIn("本轮正文提问预算：0 个问句", prompt)
                self.assertIn("本轮卡片已在收集", prompt)
                self.assertIn("正文只写一句过渡语，不要提问", prompt)
                self.assertIn("本轮不提供 ask_user", prompt)
                self.assertIn("基本信息" if "basics" in name else "经历清单", prompt)
                self.assertEqual(validate_card({"subject": "胡话简历", "questions": QUESTIONS}, state, "bad"), {})
                finished = graph._finish_followup_turn(state, {"messages": [reply]})
                self.assertEqual([m.content for m in finished["messages"]], [model.body])
                self.assertEqual(build_workspace({**state, **finished})["guidance"], expected)
                preview = {"projects": [{"name": "胡话简历", "polished_bullets": ["开发简历助手"]}]}
                self.assertEqual(build_workspace({**state, **finished}, preview)["guidance"], expected)

    async def test_no_card_has_one_question_budget_and_two_questions_use_tool(self):
        for stage in ("deepen", "ready"):
            with self.subTest(stage=stage):
                state = state_with_experiences()
                state["intake_stage"] = stage
                self.assertIsNone(intake_guidance(state))
                model = UnsolicitedToolModel()
                reply = await stream_public_reply(model, [], ask_state=state)
                self.assertEqual(len(model.bindings), 1)
                self.assertEqual(len(reply.additional_kwargs["ask_user"]["questions"]), 2)
                self.assertIn("本轮正文提问预算：最多 1 个问句、只问 1 件事", model.messages[-1].content)
                self.assertIn("需要问两个及以上问题时必须用 ask_user", model.messages[-1].content)
                self.assertIn("调用时正文只写一句过渡语，不提问", model.messages[-1].content)

    async def test_target_without_card_asks_only_direction_and_exposes_no_tool(self):
        state = {**graph._init_state(), "intake_progress": {"basics": "skipped"}}
        state.update(intake_update(state))
        self.assertEqual(state["intake_stage"], "target")
        self.assertIsNone(intake_guidance(state))
        model = UnsolicitedToolModel()
        reply = await stream_public_reply(model, [], ask_state=state)
        self.assertFalse(model.bindings)
        self.assertNotIn("ask_user", reply.additional_kwargs)
        self.assertIn("本轮正文提问预算：最多 1 个问句", model.messages[-1].content)
        self.assertIn("target 阶段只在正文开放询问岗位方向", model.messages[-1].content)

    async def test_no_tool_adapter_still_receives_budget_and_body_is_not_rewritten(self):
        class PlainModel:
            async def ainvoke(self, messages):
                self.messages = messages
                return AIMessage(content="故意违规的桩：第一问？第二问？", tool_calls=[{
                    "name": "ask_user", "args": {"subject": "胡话简历", "questions": QUESTIONS}, "id": "call",
                }])

        for state in (graph._init_state(), state_with_experiences()):
            with self.subTest(stage=state["intake_stage"]):
                model = PlainModel()
                reply = await stream_public_reply(model, [], ask_state=state, single_question=True)
                self.assertEqual(reply.content, "故意违规的桩：第一问？第二问？")
                finished = graph._finish_followup_turn(state, {"messages": [reply]})
                self.assertEqual(finished["messages"][0].content, reply.content)
                self.assertIn("本轮正文提问预算", model.messages[-1].content)
                if intake_guidance(state):
                    self.assertNotIn("ask_user", reply.additional_kwargs)
                    self.assertIn("本轮卡片已在收集基本信息", model.messages[-1].content)
                else:
                    self.assertIn("本轮 ask_user 不可用，只挑一个最有价值的问题", model.messages[-1].content)
                    self.assertNotIn("ask_user", reply.additional_kwargs)


if __name__ == "__main__":
    unittest.main()
