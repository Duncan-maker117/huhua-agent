"""用户点名要写的内容：事实库回补与回执核对（P0-A 4 / P0-B）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.agents.turn_actions import render_operation_report
from app.services.named_content import named_content_rows, named_terms, recover_named_facts, term_present
from app.services.resume_facts import new_fact

MESSAGE = "按JD再改改，mtagent突出一下agent设计和我解决幻觉那块，forge写详细点，抖音推广也写上。学校写全称哈尔滨商业大学，计算机科学与技术专业"
LABELS = ["mtagent", "forge skill"]


def collected(with_poi=True, with_douyin=True):
    mt = [new_fact("旅游路线规划的 agent", kind="deliverable", quote="旅游路线规划的agent")]
    if with_poi:
        mt.append(new_fact("一开始模型老推荐不存在的店", kind="context", quote="一开始模型老推荐不存在的店"))
    forge = [new_fact("GitHub 有 70 多个 star", kind="result_metric", quote="github有70多个star")]
    return {"projects": [
        {"item_id": "p1", "name": "mtagent", "facts": mt, "raw_notes": [
            "一个是美团黑客松做的mtagent，一开始模型老推荐不存在的店，后来我改成先用高德查poi再让模型从里面挑。"]},
        {"item_id": "p2", "name": "forge skill", "facts": forge, "raw_notes": [
            "还有一个forge skill，开源的，github有70多个star，我还发了抖音推广。"]}]}


def resume(mt_bullets, forge_bullets):
    return {"projects": [{"item_id": "p1", "name": "mtagent", "polished_bullets": mt_bullets},
                         {"item_id": "p2", "name": "forge skill", "polished_bullets": forge_bullets}]}


class NamedTermsTest(unittest.TestCase):
    def test_terms_from_emphasis_and_add_clauses(self):
        rows = named_terms(MESSAGE, LABELS)
        self.assertEqual([r["term"] for r in rows], ["agent设计", "幻觉", "抖音推广"])
        self.assertEqual(rows[0]["label"], "mtagent")
        self.assertEqual(rows[2]["label"], "")

    def test_generic_and_field_requests_are_not_terms(self):
        self.assertEqual(named_terms("突出一下亮点，学校写全称，专业也写上，改成一页", LABELS), [])

    def test_hallucination_matches_its_colloquial_fact(self):
        self.assertTrue(term_present("幻觉", "初期模型推荐不存在的店铺"))
        self.assertFalse(term_present("幻觉", "使用 FastAPI 开发"))


class RecoveryTest(unittest.TestCase):
    def test_named_term_missing_from_facts_is_recovered_from_raw_notes(self):
        before = collected()
        after, recovered = recover_named_facts(MESSAGE, before, [], LABELS)
        self.assertEqual(recovered, ["抖音推广"])
        forge = after["projects"][1]
        self.assertIn("我还发了抖音推广", [f["text"] for f in forge["facts"]])
        self.assertEqual(len(before["projects"][1]["facts"]), 1)  # 入参不被修改

    def test_recovered_from_history_when_notes_lack_it(self):
        base = collected()
        base["projects"][1]["raw_notes"] = []
        history = ["还有一个forge skill，开源的，我还发了抖音推广。"]
        after, recovered = recover_named_facts(MESSAGE, base, history, LABELS)
        self.assertEqual(recovered, ["抖音推广"])
        self.assertIn("我还发了抖音推广", [f["text"] for f in after["projects"][1]["facts"]])

    def test_never_said_stays_unrecovered(self):
        base = collected()
        base["projects"][1]["raw_notes"] = []
        after, recovered = recover_named_facts(MESSAGE, base, ["我做过mtagent"], LABELS)
        self.assertEqual(recovered, [])
        self.assertEqual(after, base)


class ReceiptTest(unittest.TestCase):
    def rows(self):
        return [{"op": "refocus", "target": "p1", "status": "done", "reason": "", "changed": True, "affected_item_ids": ["p1"]},
                {"op": "rewrite", "target": "p2", "status": "done", "reason": "", "changed": True, "affected_item_ids": ["p2"]}]

    def test_check_mark_requires_named_content_in_target_item(self):
        before = resume(["旧一"], ["旧二"])
        after = resume(["基于 FastAPI 的多 Agent 路线规划"], ["开源 skill，GitHub 70+ star"])
        facts, _ = recover_named_facts(MESSAGE, collected(), [], LABELS)  # 抖音推广已回补进事实库，但稿里没有
        lines = render_operation_report(
            named_content_rows(MESSAGE, self.rows(), before, after, facts), before, after)
        text = "\n".join(lines)
        self.assertNotIn("✅ 调整重点 mtagent", text)
        self.assertNotIn("✅ 改写 forge skill", text)
        self.assertIn("⚠ mtagent", text)
        self.assertIn("「幻觉」", text)
        self.assertIn("⚠ forge skill", text)
        self.assertIn("「抖音推广」在事实库里有，但这版没有写进去", text)

    def test_check_mark_kept_when_named_content_is_in_draft(self):
        before = resume(["旧一"], ["旧二"])
        after = resume(["多 Agent 架构设计与分工", "先用高德查 POI 再让模型挑选，避免推荐不存在的店"],
                       ["开源 skill，GitHub 70+ star", "在抖音做推广"])
        # 抖音推广 字面差一个字：「抖音」同义组命中前提是整词；这里用整词
        after["projects"][1]["polished_bullets"][1] = "发布抖音推广内容"
        lines = render_operation_report(
            named_content_rows(MESSAGE, self.rows(), before, after, collected()), before, after)
        self.assertEqual([l[:1] for l in lines], ["✅", "✅"])

    def test_not_in_fact_store_asks_user(self):
        base = collected(with_poi=False)
        base["projects"][1]["raw_notes"] = []
        base["projects"][0]["raw_notes"] = []
        base["projects"][1]["facts"] = base["projects"][1]["facts"][:1]
        before = resume(["旧一"], ["旧二"])
        after = resume(["多 Agent 路线规划"], ["开源 skill"])
        lines = render_operation_report(named_content_rows(MESSAGE, self.rows(), before, after, base), before, after)
        text = "\n".join(lines)
        self.assertIn("我没有记录到「幻觉」，能再说一下吗", text)
        self.assertIn("我没有记录到「抖音推广」，能再说一下吗", text)


class UnrecordedNoticeTest(unittest.IsolatedAsyncioTestCase):
    async def test_unrecoverable_clause_is_told_to_the_user_and_noted(self):
        import json
        from types import SimpleNamespace
        from app.agents.resume_graph import _extract_info_from_message, unrecorded_notice
        llm = SimpleNamespace(ainvoke=lambda _m: None)

        async def empty(_m):
            return SimpleNamespace(content=json.dumps({}))
        llm.ainvoke = empty
        message = "我还发了抖音推广"
        result = await _extract_info_from_message(message, {}, llm)
        self.assertIn("这句没有记下来：我还发了抖音推广", result["verification_notes"])
        self.assertIn("这句我没记下来：「我还发了抖音推广」，能换个说法吗？", unrecorded_notice(result, message))
        self.assertEqual(unrecorded_notice(result, "下一轮别的话"), "")  # 只在产生它的那一轮提示


if __name__ == "__main__":
    unittest.main()
