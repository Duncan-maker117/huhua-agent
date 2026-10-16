"""The current writer reads active evidence without changing the fact master."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.resume_writer import run_resume_writer  # noqa: E402
from app.services.resume_facts import active_facts_for_writer  # noqa: E402
from app.services.resume_review import resume_to_text  # noqa: E402


def fact(identifier, text, *, status="active", kind="action"):
    return {"id": identifier, "text": text, "source_quote": text,
            "kind": kind, "status": status, "source": "chat"}


def source():
    return {"projects": [{"item_id": "p1", "name": "纸页工具",
                          "description": "过时文稿：上线服务百万用户",
                          "raw_notes": ["内部编辑备注：准备上线"],
                          "facts": [fact("f1", "实现页面拆分，向一位同学演示，收集到2条反馈；尚未上线。",
                                         kind="status_limit"),
                                    fact("f2", "服务百万用户", status="deleted")]},
                         {"item_id": "p2", "name": "访谈整理器",
                          "facts": [fact("f3", "整理访谈笔记。")]}],
            "skills": [{"name": "Python", "status": "active"},
                       {"name": "Kubernetes", "status": "deleted"}]}


class EditorSourceCoverageTest(unittest.IsolatedAsyncioTestCase):
    async def test_secondary_failure_writes_active_source_without_printing_its_limit(self):
        collected = source()
        before = copy.deepcopy(collected)
        result = await run_resume_writer(collected, {}, object(), primary_call=False)
        self.assertEqual(collected, before)
        data = result["resume_data"]
        draft = resume_to_text(data)
        for statement in ("实现页面拆分", "收集到2条反馈"):
            self.assertIn(statement, draft)
        self.assertIn("尚未上线", draft)  # 与演示反馈成果同源的限定随成果保留
        for unsupported in ("百万用户", "准备上线", "Kubernetes"):
            self.assertNotIn(unsupported, draft)
        self.assertEqual(result["resume_meta"]["bullets"]["p1"][0]["fact_ids"], ["f1"])

    async def test_tailoring_cannot_erase_unselected_source_facts(self):
        collected = source()
        result = await run_resume_writer(collected, {}, object(), primary_call=False)
        self.assertEqual([row["id"] for row in collected["projects"][0]["facts"]], ["f1", "f2"])
        self.assertEqual([row["id"] for row in active_facts_for_writer(collected)["projects"][0]["facts"]], ["f1"])
        self.assertIn("整理访谈笔记", resume_to_text(result["resume_data"]))

    async def test_deleted_only_item_is_not_displayed(self):
        collected = source()
        collected["projects"][0]["facts"][0]["status"] = "deleted"
        result = await run_resume_writer(collected, {}, object(), primary_call=False)
        self.assertNotIn("纸页工具", resume_to_text(result["resume_data"]))
        self.assertIn("访谈整理器", resume_to_text(result["resume_data"]))


if __name__ == "__main__":
    unittest.main()
