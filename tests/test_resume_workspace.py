"""The canvas, guidance and refresh all project the same isolated session."""

import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Request
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api import chat, resume
from app.services.resume_workspace import _question_options, _reply_question, bounded_web_sources, build_workspace


class WorkspaceProjectionTest(unittest.TestCase):
    def setUp(self):
        self.data = {
            "basic_info": {"name": "虚构同学", "email": "demo@example.com"},
            "projects": [{"name": "PDF 工具", "role": "AI 辅助实现", "polished_bullets": ["实现页面拆分，本地演示。"]}],
            "skills": ["Python"],
        }

    def test_jd_has_own_panel_without_candidate_facts(self):
        values = {"jd_info": {"job_title": "AI 产品", "required_skills": ["Figma"]}, "jd_text": "岗位职责：制作原型", "stage": "COLLECTING",
                  "messages": [HumanMessage(content="岗位职责：制作原型", additional_kwargs={"career_material_type": "jd"})]}
        view = build_workspace(values, {})
        self.assertEqual(view["focus"], "jd")
        self.assertEqual(view["jd"]["info"]["required_skills"], ["Figma"])
        self.assertEqual(view["experiences"]["items"], [])
        self.assertFalse(view["resume"]["has_data"])

    def test_initial_guidance_allows_no_jd(self):
        view = build_workspace({}, {})
        self.assertEqual(len(view["guidance"]["options"]), 3)
        self.assertTrue(view["guidance"]["allow_free_text"])
        self.assertEqual(view["guidance"]["options"][-1]["value"], "我想从零开始聊自己的经历。")
        self.assertNotIn("没有 JD", str(view["guidance"]["options"]))

    def test_projection_is_read_only_and_never_uses_assistant_as_candidate(self):
        values = {"collected_info": self.data, "messages": [AIMessage(content="建议编写高并发架构，效率提高 99%。")]}
        before = copy.deepcopy(values)
        view = build_workspace(values, self.data)
        self.assertEqual(values, before)
        self.assertNotIn("99%", str(view["experiences"]))
        view["experiences"]["basic_info"]["name"] = "修改显示副本"
        self.assertEqual(self.data["basic_info"]["name"], "虚构同学")

    def test_deleted_experience_does_not_reappear_in_panel(self):
        canonical = {"basic_info": {}, "projects": [], "sections": []}
        view = build_workspace({"collected_info": self.data}, canonical)
        self.assertEqual(view["experiences"]["items"], [])
        self.assertFalse(view["resume"]["has_data"])

    def test_new_resume_version_changes_and_unchanged_version_stable(self):
        first = build_workspace({}, self.data)["resume"]["version"]
        self.assertEqual(first, build_workspace({}, self.data)["resume"]["version"])
        self.data["projects"][0]["polished_bullets"].append("补充：由一位用户持续使用。")
        self.assertNotEqual(first, build_workspace({}, self.data)["resume"]["version"])

    def test_guidance_follows_named_project_not_first_missing_date(self):
        self.data["projects"].insert(0, {"name": "旧项目", "role": "负责实现", "polished_bullets": ["本地验证。"]})
        values = {"messages": [HumanMessage(content="补充 PDF 工具的使用情况：一直在用"), AIMessage(content="已更新右侧简历。") ]}
        view = build_workspace(values, self.data)
        self.assertIn("PDF 工具", view["guidance"]["question"])
        self.assertNotIn("旧项目", view["guidance"]["question"])

    def test_skill_groups_match_editor_display_after_deletion(self):
        self.data["skills"] = ["Python", "Java"]
        self.data["skill_groups"] = {"技术": ["Python"]}
        self.assertEqual(build_workspace({}, self.data)["experiences"]["skills"], ["Python"])

    def test_explicit_question_has_specific_choices_but_no_fact_mutation(self):
        values = {"messages": [HumanMessage(content="这个怎么说"), AIMessage(content="**我的建议**\n保留本地演示的边界。\n\n**需要你补充**\n「PDF 工具」具体是怎么实现的？")]}
        view = build_workspace(values, self.data)
        self.assertEqual(view["guidance"]["question"], "「PDF 工具」具体是怎么实现的？")
        self.assertEqual(view["guidance"]["options"][0]["label"], "AI 编程工具辅助")
        self.assertIn("PDF 工具", view["guidance"]["options"][0]["value"])
        self.assertEqual(view["suggestions"][0]["detail"], "保留本地演示的边界。")
        self.assertNotIn("具体工具", str(view["experiences"]))

    def test_old_question_does_not_return_after_next_user_turn(self):
        values = {"messages": [AIMessage(content="**需要你补充**\n请说旧问题？"), HumanMessage(content="我已经补充了") ]}
        self.assertNotEqual(build_workspace(values, self.data)["guidance"]["question"], "请说旧问题？")

    def test_free_text_fallback_for_unknown_question(self):
        values = {"messages": [HumanMessage(content="细节"), AIMessage(content="**需要你补充**\n你当时为什么删掉推荐学习功能？")]}
        view = build_workspace(values, self.data)
        self.assertEqual(view["guidance"]["options"], [])
        self.assertTrue(view["guidance"]["allow_free_text"])

    def test_natural_next_step_overrides_missing_role_without_changing_facts(self):
        self.data["projects"][0]["role"] = ""
        before = copy.deepcopy(self.data)
        question = "还想补充什么，还是先生成草稿？"
        values = {"messages": [HumanMessage(content="这些就是我的材料"), AIMessage(content="已经整理了你的资料。\n\n" + question)]}
        guidance = build_workspace(values, self.data)["guidance"]
        self.assertEqual(guidance["question"], question)
        self.assertEqual(guidance["kind"], "next_action")
        self.assertEqual([option["label"] for option in guidance["options"]], ["先生成草稿", "继续补充"])
        self.assertEqual(self.data, before)
        self.assertIn("缺失信息保留待核对", guidance["options"][0]["value"])

    def test_detailed_and_compound_questions_do_not_get_canned_scope_options(self):
        for question in (
            "你具体负责哪一步？", "你负责哪部分，比如设计还是测试？",
            "你具体做了什么，以及使用了哪些工具？", "是怎么实现的？有没有实际上线？",
            "是否上线并有实际使用？", "你是独立完成还是团队协作，怎么实现的？",
            "你有没有使用 Docker？", "你使用什么算法？", "你当时遇到的难点是什么？",
            "为什么现在想生成简历？",
        ):
            with self.subTest(question=question):
                values = {"messages": [HumanMessage(content="补充"), AIMessage(content=question)]}
                guidance = build_workspace(values, self.data)["guidance"]
                self.assertEqual(guidance["question"], question)
                self.assertEqual(guidance["options"], [])
                self.assertTrue(guidance["allow_free_text"])

    def test_consecutive_questions_stay_compound_instead_of_selecting_one(self):
        reply = "已整理。\n你是独立完成的吗？\n有没有真实用户使用？"
        question = _reply_question(reply)
        self.assertIn("独立", question)
        self.assertIn("用户", question)
        self.assertEqual(_question_options(question, "PDF 工具"), [])

    def test_before_generation_fact_question_is_not_a_generate_action(self):
        options = dict(_question_options("生成草稿之前，你是否上线了这个工具？", "PDF 工具"))
        self.assertIn("已上线", options)
        self.assertNotIn("先生成草稿", options)

    def test_reply_question_ignores_examples_quotes_and_code(self):
        reply = '你具体负责哪部分？\n\n> 是否上线？\n\n例如：有没有实际使用？\n\n```text\n怎么实现的？\n```\n\n“是否跑通？”'
        self.assertEqual(_reply_question(reply), "你具体负责哪部分？")
        self.assertEqual(_reply_question("请核对项目日期。"), "请核对项目日期")

    def test_description_can_already_state_role_without_filling_role_field(self):
        for description in ("独立开发者，完成页面拆分。", "我独立完成了页面拆分。", "我是独立开发者，工具仅供自己使用。", "在小组中，我负责测试和反馈整理。"):
            with self.subTest(description=description):
                self.data["projects"][0].update(role="", description=description)
                view = build_workspace({}, self.data)
                self.assertNotIn("你的职责与分工", view["experiences"]["items"][0]["missing"])
                self.assertEqual(view["experiences"]["items"][0]["role"], "")
                self.assertNotIn("独立完成", [option["label"] for option in view["guidance"]["options"]])
                self.assertEqual(self.data["projects"][0]["role"], "")

    def test_negated_or_other_persons_ownership_does_not_fill_missing_role(self):
        for description in ("项目并非我负责，个人职责待补充。", "他人独立完成了页面拆分。", "我不是独立开发者，职责还未描述。"):
            with self.subTest(description=description):
                self.data["projects"][0].update(role="", description=description)
                self.assertIn("你的职责与分工", build_workspace({}, self.data)["experiences"]["items"][0]["missing"])

    def test_unnamed_current_turn_does_not_select_last_of_many_experiences(self):
        self.data["projects"].append({"name": "访谈整理器", "description": "整理访谈笔记。"})
        guidance = build_workspace({"messages": [HumanMessage(content="继续"), AIMessage(content="已整理当前资料。") ]}, self.data)["guidance"]
        self.assertNotIn("访谈整理器", guidance["question"])
        self.assertNotIn("PDF 工具", guidance["question"])
        self.assertEqual([option["label"] for option in guidance["options"]], ["先生成草稿", "继续补充"])

    def test_completed_material_or_draft_intent_does_not_backtrack_to_missing_role(self):
        self.data["projects"][0]["role"] = ""
        for request in ("请生成简历草稿", "没有更多补充了", "资料就这些"):
            with self.subTest(request=request):
                guidance = build_workspace({"messages": [HumanMessage(content=request), AIMessage(content="已收到。") ]}, self.data)["guidance"]
                self.assertEqual([option["label"] for option in guidance["options"]], ["先生成草稿", "继续补充"])
        guidance = build_workspace({"messages": [HumanMessage(content="先别生成简历，我想补充细节") ]}, self.data)["guidance"]
        self.assertNotEqual(guidance["kind"], "next_action")

    def test_repeated_question_has_a_new_turn_identity_but_refresh_is_stable(self):
        values = {"messages": [HumanMessage(content="补充"), AIMessage(content="是怎么实现的？")]}
        first = build_workspace(values, self.data)["guidance"]
        self.assertEqual(first, build_workspace(values, self.data)["guidance"])
        values["messages"] += [HumanMessage(content="请再问一次"), AIMessage(content="是怎么实现的？")]
        second = build_workspace(values, self.data)["guidance"]
        self.assertEqual(first["question"], second["question"])
        self.assertNotEqual(first["turn_id"], second["turn_id"])

    def test_imported_skills_certificates_and_verification_notes_are_visible(self):
        self.data.update(certificates=["虚构比赛二等奖"], verification_notes=["PDF 工具日期在两份文件中不同，待本人核对。"])
        view = build_workspace({}, self.data)["experiences"]
        self.assertEqual(view["skills"], ["Python"])
        self.assertEqual(view["certificates"], ["虚构比赛二等奖"])
        self.assertEqual(view["verification_notes"], self.data["verification_notes"])
        view["verification_notes"].append("修改副本")
        self.assertEqual(len(self.data["verification_notes"]), 1)
        canonical = {"basic_info": {}, "skills": [], "certificates": [], "verification_notes": []}
        deleted = build_workspace({"collected_info": self.data}, canonical)["experiences"]
        self.assertEqual(deleted["skills"], [])
        self.assertEqual(deleted["certificates"], [])
        self.assertEqual(deleted["verification_notes"], [])

    def test_public_page_source_keeps_bounded_scope_without_becoming_candidate_facts(self):
        public = {"title": "公开主页", "kind": "public_page", "url": "https://example.invalid/profile", "content": "某公开仓库使用 Go", "read_scope": "github_profile_and_public_repositories", "request_count": 2, "content_truncated": False}
        view = build_workspace({"web_sources": [public]}, self.data)
        self.assertEqual(view["web_sources"][0]["kind"], "public_page")
        self.assertEqual(view["web_sources"][0]["read_scope"], public["read_scope"])
        self.assertEqual(view["web_sources"][0]["request_count"], 2)
        self.assertFalse(view["web_sources"][0]["content_truncated"])
        self.assertNotIn("Go", str(view["experiences"]))
        invalid = bounded_web_sources([{**public, "request_count": True, "read_scope": "arbitrary", "content_truncated": "true"}])[0]
        self.assertNotIn("request_count", invalid)
        self.assertNotIn("read_scope", invalid)
        self.assertNotIn("content_truncated", invalid)
        self.assertNotIn("read_scope", bounded_web_sources([{**public, "read_scope": []}])[0])
        self.assertEqual(bounded_web_sources([{**public, "kind": []}]), [])

    def test_role_answers_only_confirm_the_selected_contribution_scope(self):
        self.data["projects"][0]["role"] = ""
        options = build_workspace({}, self.data)["guidance"]["options"]
        by_label = {option["label"]: option["value"] for option in options}
        self.assertEqual(by_label["独立完成"], "在「PDF 工具」里，我是独立完成的。")
        self.assertEqual(by_label["团队中负责一部分"], "在「PDF 工具」里，我只负责团队中的一部分工作。")
        self.assertNotIn("AI 辅助实现", by_label)
        for value in by_label.values():
            self.assertNotIn("整个项目", value)
            self.assertNotIn("架构", value)
            self.assertNotIn("主导", value)

    def test_implementation_answers_do_not_invent_tool_names_or_ownership(self):
        options = dict(_question_options("「PDF 工具」是怎么实现的？", "PDF 工具"))
        self.assertEqual(options["AI 编程工具辅助"], "在「PDF 工具」里，我使用 AI 编程工具辅助实现。")
        self.assertEqual(options["自己编写代码"], "在「PDF 工具」里，我自己编写了代码。")
        self.assertEqual(options["现成工具组合"], "在「PDF 工具」里，我用现成工具组合完成。")
        for value in options.values():
            for unselected_claim in ("独立", "全程", "负责", "Cursor", "Codex", "Figma", "Python", "上线"):
                self.assertNotIn(unselected_claim, value)

    def test_status_answers_match_question_instead_of_implying_other_milestones(self):
        cases = [
            ("「PDF 工具」的页面拆分是否上线？", "已上线", "上线", ("实际使用", "验证", "开发")),
            ("「PDF 工具」有没有实际使用？", "已有实际使用", "实际使用", ("上线", "验证", "开发")),
            ("「PDF 工具」是否做过验证？", "已经验证", "验证", ("上线", "实际使用", "开发")),
            ("「PDF 工具」有没有跑通？", "已经跑通", "跑通", ("上线", "实际使用", "开发")),
        ]
        for question, label, expected, unrelated in cases:
            with self.subTest(question=question):
                options = dict(_question_options(question, "PDF 工具"))
                self.assertIn(label, options)
                self.assertIn(expected, options[label])
                for value in options.values():
                    self.assertIn("PDF 工具", value)
                    self.assertIn("刚问到的这部分", value)
                    for unselected_claim in unrelated:
                        self.assertNotIn(unselected_claim, value)

    def test_all_exported_options_are_complete_sentences_without_placeholders(self):
        states = [({}, {}), ({"jd_skipped": True}, {}), ({"jd_info": {"job_title": "产品"}}, {})]
        for role, bullets in (("", []), ("负责实现", []), ("负责实现", ["完成本地演示。"])):
            data = copy.deepcopy(self.data)
            data["projects"][0].update(role=role, polished_bullets=bullets)
            states.append(({}, data))
        questions = ["「PDF 工具」如何实现？", "「PDF 工具」你负责哪部分？", "「PDF 工具」有没有实际使用？", "「PDF 工具」是否上线？", "「PDF 工具」是否验证？", "「PDF 工具」有没有跑通？", "「PDF 工具」做到哪一步？", "你当时为什么删掉推荐学习功能？"]
        for question in questions:
            states.append(({"messages": [HumanMessage(content="补充"), AIMessage(content="**需要你补充**\n" + question)]}, self.data))
        for state, data in states:
            view = build_workspace(state, data)
            self.assertTrue(view["guidance"]["allow_free_text"])
            for option in view["guidance"]["options"]:
                with self.subTest(question=view["guidance"]["question"], label=option["label"]):
                    self.assertTrue(option["value"].endswith("。"), option)
                    self.assertNotRegex(option["value"], r"[:：]$|具体负责[:：]|具体是[:：]|补充是[:：]|待填写|待填入|填写这里|具体工具和我的工作是")

    def test_deliverable_choice_does_not_add_a_specific_artifact(self):
        self.data["projects"][0]["polished_bullets"] = []
        options = {option["label"]: option["value"] for option in build_workspace({}, self.data)["guidance"]["options"]}
        self.assertEqual(options["功能 / 工具"], "「PDF 工具」做出了功能或工具。")
        self.assertEqual(options["文档 / 原型"], "「PDF 工具」交付了文档或原型。")
        self.assertEqual(options["还在进行"], "「PDF 工具」还在进行中。")

    def test_explicit_question_options_stay_with_the_named_project(self):
        self.data["projects"].append({"name": "访谈整理器", "role": "负责实现", "description": "整理访谈笔记。"})
        values = {"messages": [HumanMessage(content="继续补充访谈整理器"), AIMessage(content="**需要你补充**\n「PDF 工具」是怎么实现的？")]}
        options = build_workspace(values, self.data)["guidance"]["options"]
        self.assertTrue(all("PDF 工具" in option["value"] for option in options))
        self.assertTrue(all("访谈整理器" not in option["value"] for option in options))

    def test_quoted_phrase_is_not_invented_project_name(self):
        values = {"messages": [HumanMessage(content="补充"), AIMessage(content="**需要你补充**\n关于「本地演示」：有没有给真实用户实际使用？")]}
        choices = build_workspace(values, self.data)["guidance"]["options"]
        self.assertTrue(all("在「本地演示」" not in option["value"] for option in choices))

    def test_review_projects_read_only_results(self):
        values = {"messages": [HumanMessage(content="检查简历", additional_kwargs={"career_material_type": "review"}), AIMessage(content="请核对项目日期。") ]}
        view = build_workspace(values, self.data)
        self.assertEqual(view["focus"], "review")
        self.assertEqual(view["review"]["reply"], "请核对项目日期。")
        self.assertTrue(view["review"]["items"])


class WorkspaceApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        # The projection comparison has no persistence side effects. Scope
        # authorization is exercised by API integration tests separately.
        self.auth = patch.object(resume, "authorize_session", return_value="unit-browser-owner")
        self.owner = patch("app.services.conversation_store.session_owner", return_value="unit-browser-owner")
        self.auth.start()
        self.owner.start()
        self.addCleanup(self.auth.stop)
        self.addCleanup(self.owner.stop)

    async def test_end_meta_and_current_refresh_share_workspace(self):
        values = {"stage": "COLLECTING", "jd_info": {"job_title": "AI 产品"}, "jd_text": "产品岗位", "collected_info": {}, "messages": []}
        graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values=values)))
        stored = {"stage": "COLLECTING", "has_data": False, "resume_data": {}}
        with patch.object(chat, "session_can_read_checkpoint", return_value=True), patch.object(chat, "get_graph", return_value=graph), patch.object(chat, "load_resume_session", return_value=stored):
            meta = await chat._session_meta("one-session", object())
        with patch.object(resume, "session_can_read_checkpoint", return_value=True), patch.object(resume, "get_graph", return_value=graph), patch.object(resume, "_llm_for_graph", return_value=object()), patch.object(resume, "load_resume_session", return_value=stored):
            current = await resume.current_resume(self.request, "one-session")
        self.assertEqual(meta["workspace"], current["workspace"])
        self.assertEqual(meta["workspace"]["jd"]["info"]["job_title"], "AI 产品")

    async def test_deleted_session_meta_is_empty(self):
        with patch.object(chat, "session_can_read_checkpoint", return_value=False):
            meta = await chat._session_meta("deleted", object())
        self.assertFalse(meta["workspace"]["resume"]["has_data"])
        self.assertEqual(meta["workspace"]["experiences"]["items"], [])


if __name__ == "__main__":
    unittest.main()
