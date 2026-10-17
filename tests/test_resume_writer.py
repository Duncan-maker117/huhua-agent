"""Writer contract tests use local structured doubles, never a model endpoint."""

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.resume_writer import run_resume_writer  # noqa: E402


def fact(identifier, text, *, status="active", kind="action"):
    return {"id": identifier, "text": text, "source_quote": text,
            "kind": kind, "status": status, "source": "chat"}


def source():
    return {
        "basic_info": {"name": "旧页眉名", "objective": "旧页眉目标", "phone": "13900000000"},
        "projects": [
            {"item_id": "p1", "name": "原型项目", "raw_notes": ["不能进入模型的旧备注"],
             "description": "不可回写的原始说明", "facts": [
                 fact("f1", "做了原型", kind="status_limit"),
                 fact("f2", "旧成果1000用户", status="deleted"),
             ]},
            {"item_id": "p2", "name": "数据项目", "facts": [fact("f3", "整理用户反馈并分类")]},
        ],
        "work_experience": [
            {"item_id": "w1", "company": "实习单位", "facts": [fact("f4", "核对重复记录")]},
        ],
        "skills": [{"name": "Python", "status": "active"}, {"name": "Kubernetes", "status": "deleted"}],
    }


ROLE = {"role_family": "pm", "seniority": "intern",
        "requirements": [{"id": "r1", "text": "用户研究"}], "required_skills": ["Python"]}


def source_echo_model(collected):
    """A successful writer double for intake tests; emits exact source quotes."""
    from app.agents.resume_writer import _body_fact
    rows = []
    for section in ('projects', 'work_experience'):
        for source_item in collected.get(section) or []:
            rows.append({'item_id': source_item['item_id'], 'section': section,
                         'bullets': [{'text': fact.get('source_quote') or fact['text'],
                                      'fact_ids': [fact['id']]}
                                     for fact in source_item.get('facts') or []
                                     if fact.get('status', 'active') == 'active' and _body_fact(fact)]})
    class EchoModel(FakeModel):
        async def ainvoke(self, messages):
            import json
            payload = json.loads(messages[-1].content)
            if self.schema.__name__ == 'FactSlots':
                from app.services.labeled_writer import rule_slot
                self.calls.append((self.schema.__name__, messages))
                return {'assignments': [{'fact_id': f['id'], 'slot': rule_slot(f) or '技术'}
                                        for f in payload['facts']]}
            if self.schema.__name__ == 'SemanticBatch':
                from test_fact_guard import decision
                self.calls.append((self.schema.__name__, messages))
                return {'decisions': [decision(row['id']) for row in payload]}
            return await super().ainvoke(messages)
    return EchoModel([('OnePassOutput', {'match_plan': {}, 'writer': {'items': rows}})])


def draft(items, **extra):
    return {"objective": "", "summary": "", "items": items, "skill_groups": {},
            "omitted": [], "change_summary": [], **extra}


def item(identifier, section, bullets, title=None):
    return {"item_id": identifier, "section": section, "title": title or {},
            "bullets": [{"text": text, "fact_ids": refs} for text, refs in bullets]}


def plan(treatments=None):
    return {"requirements": [{"req_id": "r1", "status": "direct", "fact_ids": ["f3"]}],
            "experience_plan": [{"item_id": identifier, "treatment": treatment}
                                for identifier, treatment in (treatments or {}).items()],
            "section_order": ["education", "projects", "work_experience"]}


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        self.calls.append((self.schema.__name__, messages))
        expected, response = self.responses.pop(0)
        assert self.schema.__name__ == expected, (self.schema.__name__, expected)
        if isinstance(response, Exception):
            raise response
        return response


def run(*args, **kwargs):
    return asyncio.run(run_resume_writer(*args, **kwargs))


class ResumeWriterTest(unittest.TestCase):
    def test_one_pass_writing_uses_main_model_not_structured_model(self):
        writer = FakeModel([("OnePassOutput", {"match_plan": plan({"p2": "lead"}),
                                               "writer": draft([item("p2", "projects", [
                                                   ("整理用户反馈并分类", ["f3"])])])})])
        structured = FakeModel([])
        result = run(source(), ROLE, writer, structured_llm=structured, mode="one_pass")
        selected = next(row for row in result["resume_data"]["projects"] if row["item_id"] == "p2")
        self.assertIn("整理用户反馈并分类", selected["polished_bullets"])
        # Exact source echoes and genuinely omitted facts each get a local polish.
        self.assertEqual([schema for schema, _ in writer.calls], ["OnePassOutput", "RepairOutput"])
        self.assertEqual(structured.calls, [])

    def test_two_pass_plans_with_structured_and_writes_with_main_model(self):
        planner = FakeModel([("MatchPlan", plan({"p2": "lead"}))])
        writer = FakeModel([("WriterDraft", draft([item("p2", "projects", [
            ("整理用户反馈并分类", ["f3"])])]))])
        result = run(source(), ROLE, writer, structured_llm=planner, mode="two_pass")
        selected = next(row for row in result["resume_data"]["projects"] if row["item_id"] == "p2")
        self.assertIn("整理用户反馈并分类", selected["polished_bullets"])
        self.assertEqual([schema for schema, _ in planner.calls], ["MatchPlan"])
        self.assertEqual([schema for schema, _ in writer.calls], ["WriterDraft", "RepairOutput"])

    def test_untrusted_skill_heading_becomes_neutral_other(self):
        model = FakeModel([("OnePassOutput", {"match_plan": plan({"p2": "lead"}),
                                            "writer": draft([item("p2", "projects", [
                                                ("整理用户反馈并分类", ["f3"])])],
                                                            skill_groups={"十年算法总监经验": ["Python"]})})])
        result = run(source(), ROLE, model)
        # 固定类别：不可信的分组名从不显示，技能按词表归入「开发」
        self.assertEqual(result["resume_data"]["skill_groups"], {"开发": ["Python"]})
        self.assertNotIn("十年算法总监经验", json.dumps(result["resume_data"], ensure_ascii=False))

    def test_whole_rewrite_clears_uncited_old_summary(self):
        current = {"self_evaluation": "旧母版个人总结：十年算法总监经验"}
        meta = {"summary": {"fact_ids": ["old"], "text_hash": "old"}}
        for text, refs in (("", []), ("主导团队增长", ["f2"])):
            with self.subTest(summary=text):
                model = FakeModel([("OnePassOutput", {"match_plan": plan({"p2": "lead"}),
                                                    "writer": draft([item("p2", "projects", [
                                                        ("整理用户反馈并分类", ["f3"])])],
                                                                    summary=text, summary_fact_ids=refs)})])
                result = run(source(), ROLE, model, current_data=current, resume_meta=meta)
                self.assertEqual(result["resume_data"].get("self_evaluation"), "")
                self.assertNotIn("summary", result["resume_meta"])

    def test_valid_summary_records_citations_and_hash(self):
        text = "整理用户反馈并分类"
        model = FakeModel([("OnePassOutput", {"match_plan": plan({"p2": "lead"}),
                                            "writer": draft([item("p2", "projects", [(text, ["f3"])])],
                                                            summary=text, summary_fact_ids=["f3"])})])
        result = run(source(), ROLE, model, current_data={"self_evaluation": "旧母版个人总结"})
        self.assertEqual(result["resume_data"]["summary"], text)
        self.assertFalse(result["resume_data"]["self_evaluation"])
        self.assertEqual(result["resume_meta"]["summary"], {
            "fact_ids": ["f3"], "text_hash": hashlib.sha256(text.encode()).hexdigest()})

    def test_one_pass_keeps_source_titles_and_only_active_evidence(self):
        model = FakeModel([
            ("OnePassOutput", {"match_plan": plan({"p1": "lead", "p2": "backup", "w1": "keep"}),
                               "writer": draft([
                                   item("p1", "projects", [("做了原型", ["f1"])],
                                        {"name": "模型虚构项目", "role": "主导"}),
                                   item("w1", "work_experience", [("核对重复记录", ["f4"])],
                                        {"name": "虚构公司", "role": "经理"}),
                                   item("made-up", "projects", [("新经历", ["f3"])])],
                                   skill_groups={"技术": ["Python", "Kubernetes"]})}),
        ])
        original = source()
        before = deepcopy(original)
        result = run(original, ROLE, model)
        data = result["resume_data"]
        self.assertEqual(original, before)
        self.assertEqual([entry["item_id"] for entry in data["projects"]], ["p1", "p2"])
        self.assertEqual(data["projects"][0]["name"], "原型项目")
        self.assertEqual(data["work_experience"][0]["company"], "实习单位")
        self.assertTrue(data["projects"][1]["hidden"])
        self.assertEqual(data["skill_groups"], {"开发": ["Python"]})
        self.assertEqual(data["projects"][0]["description"], "")
        self.assertEqual(result["resume_meta"]["bullets"]["p1"][0]["text_hash"],
                         hashlib.sha256("完成原型".encode()).hexdigest())
        sent = model.calls[0][1][-1].content
        self.assertNotIn("旧成果1000用户", sent)
        self.assertNotIn("不能进入模型的旧备注", sent)
        self.assertNotIn("旧页眉名", sent)
        self.assertNotIn("13900000000", sent)
        self.assertEqual(model.responses, [])

    def test_two_pass_repairs_only_bad_bullet_once(self):
        model = FakeModel([
            ("MatchPlan", plan({"p1": "lead", "w1": "keep"})),
            ("WriterDraft", draft([
                item("p1", "projects", [("上线后服务1000人", ["f1"])]),
                item("w1", "work_experience", [("核对重复记录", ["f4"])])])),
            ("RepairOutput", {"bullets": [{"id": "b0", "text": "做了原型", "fact_ids": ["f1"]}]}),
        ])
        result = run(source(), ROLE, model, mode="two_pass")
        self.assertEqual([call[0] for call in model.calls], ["MatchPlan", "WriterDraft", "RepairOutput", "RepairOutput"])
        self.assertEqual(result["resume_data"]["projects"][0]["polished_bullets"], ["完成原型"])
        self.assertEqual(result["resume_data"]["work_experience"][0]["bullets"], ["核对重复记录"])
        self.assertEqual(result["guard_fallbacks"], [])
        self.assertIn("match_plan", model.calls[1][1][-1].content)

    def test_cross_item_or_deleted_reference_falls_back_to_own_fact(self):
        model = FakeModel([
            ("OnePassOutput", {"match_plan": plan({"p1": "lead"}),
                               "writer": draft([item("p1", "projects", [("整理用户反馈并分类", ["f3"])])])}),
            ("RepairOutput", {"bullets": [{"id": "b0", "text": "旧成果1000用户", "fact_ids": ["f2"]}]}),
        ])
        result = run(source(), ROLE, model)
        self.assertEqual(result["resume_data"]["projects"][0]["polished_bullets"], ["完成原型"])
        self.assertEqual(result["resume_meta"]["bullets"]["p1"][0]["fact_ids"], ["f1"])
        self.assertEqual(len(result["guard_fallbacks"]), 1)
        self.assertEqual(result["guard_fallbacks"][0]["reason"], "invalid_refs")

    def test_bullet_edit_keeps_every_other_item_and_metadata_unchanged(self):
        current = {"basic_info": {"name": "已确认姓名"}, "projects": [
            {"item_id": "p1", "name": "已确认项目名", "description": "保留原文", "role": "已确认角色",
             "polished_bullets": ["第一条", "第二条"], "custom": {"nested": True}},
            {"item_id": "p2", "name": "数据项目", "polished_bullets": ["别改我"]}],
            "work_experience": [{"item_id": "w1", "company": "实习单位", "bullets": ["别改实习"]}]}
        meta = {"bullets": {"p1": [{"text_hash": "old1"}, {"text_hash": "old2"}],
                            "p2": [{"text_hash": "keep"}]}, "custom": "preserve"}
        model = FakeModel([("OnePassOutput", {"match_plan": plan({"p1": "lead", "p2": "backup"}),
                                                 "writer": draft([
                                                     item("p1", "projects", [("做了原型", ["f1"])]),
                                                     item("p2", "projects", [("整理用户反馈并分类", ["f3"])])])})])
        result = run(source(), ROLE, model, current_data=current, resume_meta=meta,
                     scope="bullet", targets=["/projects/0/polished_bullets/1"])
        data = result["resume_data"]
        self.assertEqual(data["projects"][0]["polished_bullets"], ["第一条", "完成原型"])
        self.assertEqual(data["projects"][0]["name"], current["projects"][0]["name"])
        self.assertEqual(data["projects"][0]["role"], current["projects"][0]["role"])
        self.assertEqual(data["projects"][1], current["projects"][1])
        self.assertEqual(data["work_experience"][0], current["work_experience"][0])
        self.assertEqual(result["resume_meta"]["bullets"]["p2"], meta["bullets"]["p2"])
        self.assertEqual(result["resume_meta"]["bullets"]["p1"][0], meta["bullets"]["p1"][0])
        self.assertEqual(current["projects"][0]["polished_bullets"], ["第一条", "第二条"])

    def test_secondary_compression_failure_cleans_active_fact_without_new_claims(self):
        model = FakeModel([("OnePassOutput", RuntimeError("offline"))])
        result = run(source(), ROLE, model, primary_call=False)
        content = json.dumps(result["resume_data"], ensure_ascii=False)
        self.assertIn("完成原型", content)
        self.assertNotIn("旧成果1000用户", content)
        self.assertEqual(result["guard_fallbacks"], [])

    def test_internship_order_sections_and_objective_are_deterministic(self):
        collected = source()
        collected["internship"] = [{"item_id": "i1", "company": "校园实习", "facts": [
            fact("fi", "参与整理调研问卷")]}]
        current = {"basic_info": {"name": "已确认姓名", "objective": ""},
                   "projects": [{"item_id": "p1", "name": "原型项目", "description": "原始材料A"},
                                {"item_id": "p2", "name": "数据项目", "description": "原始材料B"}],
                   "work_experience": [{"item_id": "w1", "company": "实习单位", "bullets": []},
                                       {"item_id": "i1", "company": "校园实习", "bullets": []}],
                   "education": [{"item_id": "e1", "school": "已确认学校"}]}
        custom_plan = plan({"p2": "lead", "i1": "keep", "p1": "brief", "w1": "keep"})
        custom_plan["section_order"] = ["projects", "education", "work_experience", "skills", "certificates"]
        model = FakeModel([("OnePassOutput", {"match_plan": custom_plan,
                                             "writer": draft([
                                                 item("p2", "projects", [("整理用户反馈并分类", ["f3"])]),
                                                 item("i1", "work_experience", [("参与整理调研问卷", ["fi"])])],
                                                 objective="有5年AI产品经验")})])
        result = run(collected, {**ROLE, "target_role": "AI产品经理"}, model, current_data=current)
        data = result["resume_data"]
        self.assertEqual(data["basic_info"]["objective"], "AI产品经理")
        self.assertEqual([entry["item_id"] for entry in data["projects"]], ["p2", "p1"])
        self.assertEqual([entry["item_id"] for entry in data["work_experience"]], ["i1", "w1"])
        self.assertEqual([entry["kind"] for entry in data["sections"][:3]],
                         ["projects", "education", "work_experience"])
        self.assertEqual(data["projects"][1]["description"], "原始材料A")
        self.assertEqual(data["education"], current["education"])
        self.assertIn({"section": "work_experience", "item_id": "i1"}, result["changed_items"])
        sent = model.calls[0][1][-1].content
        self.assertIn("参与整理调研问卷", sent)

    def test_header_field_fact_cannot_become_bullet(self):
        collected = source()
        collected["projects"][0]["facts"].append({**fact("frole", "产品负责人"), "field": "role"})
        model = FakeModel([
            ("OnePassOutput", {"match_plan": plan({"p1": "lead"}),
                               "writer": draft([item("p1", "projects", [("产品负责人", ["frole"])])])}),
            ("RepairOutput", {"bullets": [{"id": "b0", "text": "产品负责人", "fact_ids": ["frole"]}]}),
        ])
        result = run(collected, ROLE, model)
        self.assertEqual(result["resume_data"]["projects"][0]["polished_bullets"], ["完成原型"])
        self.assertEqual(result["guard_fallbacks"][0]["reason"], "invalid_refs")
        self.assertNotIn("产品负责人", result["resume_data"]["projects"][0]["polished_bullets"])


if __name__ == "__main__":
    unittest.main()
