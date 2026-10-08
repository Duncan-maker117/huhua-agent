"""Sparse fact extraction rejects only unsupported claims."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch
from app.services.resume_facts import active_facts_for_writer, new_fact


class FakeLLM:
    def __init__(self, value):
        self.value = value

    async def ainvoke(self, _messages):
        return SimpleNamespace(content=json.dumps(self.value, ensure_ascii=False))


class FactExtractorTest(unittest.IsolatedAsyncioTestCase):
    async def test_ui_empty_state_rewording_survives_fact_validation(self):
        message = '在资料页项目中，我还补了加载中、没结果和请求失败的界面，网站没上线。'
        llm = FakeLLM({'items': [{'section': 'projects', 'name': '资料页', 'facts': [
            {'kind': 'action', 'text': '补充加载、空结果和请求失败界面',
             'source_quote': '我还补了加载中、没结果和请求失败的界面'},
            {'kind': 'status_limit', 'text': '网站没上线', 'source_quote': '网站没上线'}]}]})
        checked = []

        async def semantic(pairs):
            checked.extend(pairs)
            return {row['id']: {'verdict': 'pass'} for row in pairs}

        patch = await extract_facts_patch(message, {}, llm, semantic_check=semantic)
        collected = apply_fact_patch({}, patch)
        self.assertEqual(patch['rejected'], [])
        self.assertEqual([fact['text'] for fact in collected['projects'][0]['facts']],
                         ['补充加载、空结果和请求失败界面', '网站没上线'])
        self.assertEqual(len(checked), 1)
        self.assertIn('没结果', checked[0]['source_quotes'][0])

    async def test_per_fact_rejection_keeps_supported_fact(self):
        message = "我在 PaperTool 做了原型，未上线。"
        llm = FakeLLM({"items": [{"section": "projects", "name": "PaperTool", "facts": [
            {"kind": "action", "text": "做了原型，未上线", "source_quote": "做了原型，未上线"},
            {"kind": "result_metric", "text": "服务了100万用户", "source_quote": "做了原型，未上线"},
            {"kind": "role", "text": "主导原型开发", "source_quote": "做了原型"},
        ]}]})
        patch = await extract_facts_patch(message, {}, llm, turn_id="turn-1")
        self.assertEqual(len(patch["items"][0]["facts"]), 1)
        self.assertEqual(len(patch["rejected"]), 2)
        collected = apply_fact_patch({}, patch)
        self.assertEqual(collected["projects"][0]["facts"][0]["source"], "chat")
        self.assertEqual(collected["projects"][0]["raw_notes"], ["做了原型，未上线"])

    async def test_correction_and_removal_hide_old_writer_evidence(self):
        old = new_fact("独立开发", quote="我独立开发")
        old["id"] = "f_old"
        other = new_fact("完成原型", quote="完成原型")
        other["id"] = "f_remove"
        collected = {"projects": [{"item_id": "p1", "name": "PaperTool", "facts": [old, other], "raw_notes": []}]}
        message = "更正：我只参与开发；原型那条删掉。"
        llm = FakeLLM({"corrections": [{"item_id": "p1", "fact_id": "f_old", "replacement":
                         {"kind": "role", "text": "参与开发", "source_quote": "参与开发"}}],
                       "removals": [{"item_id": "p1", "fact_id": "f_remove"}]})
        patch = await extract_facts_patch(message, collected, llm, turn_id="turn-2")
        updated = apply_fact_patch(collected, patch)
        self.assertEqual([f["status"] for f in updated["projects"][0]["facts"]], ["superseded", "deleted", "active"])
        self.assertEqual([f["text"] for f in active_facts_for_writer(updated)["projects"][0]["facts"]], ["参与开发"])

    async def test_semantic_hook_rejects_one_rewrite_and_metadata_is_not_evidence(self):
        message = "我核对了重复记录。"
        llm = FakeLLM({"items": [{"section": "projects", "name": "重复记录", "facts": [
            {"kind": "action", "text": "搭建重复记录清理流程", "source_quote": "核对了重复记录"}]}]})
        calls = []
        async def semantic(pairs):
            calls.extend(pairs)
            return {row["id"]: {"verdict": "fail"} for row in pairs}
        patch = await extract_facts_patch(message, {}, llm, metadata_context=["本人确认：已上线"], semantic_check=semantic)
        self.assertFalse(patch["items"])
        self.assertTrue(calls)
        self.assertEqual(patch["rejected"][0]["reason"], "semantic_verification_failed")

    async def test_short_rewording_uses_semantics_for_both_pass_and_fail(self):
        message = "在反馈项目中，我核对重复记录，效果变好了。"
        llm = FakeLLM({"items": [{"section": "projects", "name": "反馈项目", "facts": [
            {"kind": "action", "text": "清理重复记录", "source_quote": "核对重复记录"},
            {"kind": "result_qualitative", "text": "效果提升", "source_quote": "效果变好了"}]}]})
        seen = []
        async def semantic(pairs):
            seen.extend(pairs)
            return {row["id"]: {"verdict": "fail" if row["text"] == "清理重复记录" else "pass"} for row in pairs}
        patch = await extract_facts_patch(message, {}, llm, semantic_check=semantic)
        self.assertEqual({row["text"] for row in seen}, {"清理重复记录", "效果提升"})
        self.assertEqual([f["text"] for f in patch["items"][0]["facts"]], ["效果提升"])

    async def test_skill_name_must_appear_in_quoted_user_text(self):
        message = "我用过 Python 做接口。"
        llm = FakeLLM({"skills": [{"name": "Kubernetes", "source_quote": "用过 Python 做接口"},
                                  {"name": "Python", "source_quote": "用过 Python 做接口"}]})
        patch = await extract_facts_patch(message, {}, llm)
        self.assertEqual([skill["name"] for skill in patch["skills"]], ["Python"])

    async def test_cropped_negation_before_fact_quote_is_rejected(self):
        message = "我没有主导项目，只参与调研。"
        llm = FakeLLM({"items": [{"section": "projects", "name": "项目", "facts": [
            {"kind": "role", "text": "主导项目", "source_quote": "主导项目"},
            {"kind": "action", "text": "参与调研", "source_quote": "参与调研"}]}]})
        patch = await extract_facts_patch(message, {}, llm)
        self.assertEqual([fact["text"] for fact in patch["items"][0]["facts"]], ["参与调研"])
        self.assertEqual(patch["rejected"][0]["reason"], "source_quote_omits_limit")

    async def test_cropped_negation_cannot_create_skill_or_name(self):
        message = "我不会Python，我不是张三。"
        llm = FakeLLM({"skills": [{"name": "Python", "source_quote": "Python"}],
                       "basic_info": {"name": "张三"}})
        patch = await extract_facts_patch(message, {}, llm)
        self.assertEqual(patch["skills"], [])
        self.assertEqual(patch["basic_info"], {})

    async def test_external_jd_and_unknown_item_are_rejected(self):
        message = "岗位职责：主导增长项目，提升转化。"
        llm = FakeLLM({"items": [{"section": "projects", "item_id": "unknown", "name": "增长项目",
                              "facts": [{"kind": "role", "text": "主导增长项目", "source_quote": "主导增长项目"}]}]})
        patch = await extract_facts_patch(message, {}, llm)
        self.assertFalse(patch["items"])
        self.assertEqual(patch["rejected"][0]["reason"], "unknown_item_id")

    async def test_inline_jd_clause_cannot_become_candidate_fact(self):
        message = "我的经历：参与 PaperTool 原型。JD：主导增长项目，提升转化。"
        llm = FakeLLM({"items": [{"section": "projects", "name": "增长项目", "facts": [
            {"kind": "role", "text": "主导增长项目", "source_quote": "主导增长项目"}]}]})
        patch = await extract_facts_patch(message, {}, llm)
        self.assertFalse(patch["items"])
        self.assertTrue(patch["rejected"])

    async def test_candidate_evidence_resumes_after_inline_jd(self):
        message = "JD：主导增长项目。我的经历：参与 PaperTool 原型。"
        llm = FakeLLM({"items": [{"section": "projects", "name": "PaperTool", "facts": [
            {"kind": "action", "text": "参与 PaperTool 原型", "source_quote": "参与 PaperTool 原型"}]}]})
        patch = await extract_facts_patch(message, {}, llm)
        self.assertEqual(patch["items"][0]["facts"][0]["text"], "参与 PaperTool 原型")


if __name__ == "__main__":
    unittest.main()
