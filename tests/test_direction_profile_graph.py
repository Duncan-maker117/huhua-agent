"""Direction-only targets survive graph intake without inventing JD evidence."""

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.resume_graph import _direction_profile_update, _init_state, jd_input_node
from app.agents.triage_chain import build_state_for_triage
from app.services.resume_strategy import build_resume_strategy, has_job_description


class DirectionProfileGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_eight_directions_reach_collecting_with_profile_and_no_fact_pollution(self):
        for text, family in [
            ("我想投 AI 产品经理实习", "ai_pm"), ("我想投产品经理校招", "pm"),
            ("我想投后端开发实习", "backend"), ("我想投前端开发实习", "frontend"),
            ("我想投算法实习", "algorithm"), ("我想投数据分析实习", "data"),
            ("我想投运营实习", "ops"), ("我想投交互设计实习", "design"),
        ]:
            with self.subTest(family=family):
                state = _init_state()
                state["messages"] = [HumanMessage(content=text)]
                facts = copy.deepcopy(state["collected_info"])
                with patch("app.agents.resume_graph.run_triage") as triage:
                    update = await jd_input_node(state, object())
                triage.assert_not_called()
                self.assertEqual(update["stage"], "COLLECTING")
                self.assertTrue(update["jd_skipped"])
                self.assertEqual(update["jd_info"]["role_profile"]["role_family"], family)
                self.assertEqual(update["jd_info"]["role_profile"]["source"], "direction")
                self.assertEqual(len(update["jd_info"]["role_profile"]["requirements"]), 5)
                self.assertFalse(has_job_description(update["jd_info"]))
                self.assertEqual(update["resume_strategy"]["mode"], "capability")
                self.assertFalse(build_state_for_triage({**state, **update})["has_jd"])
                self.assertEqual(state["collected_info"], facts)
                self.assertNotIn("collected_info", update)

    def test_trailing_upload_instruction_defines_target_not_old_attachment_direction(self):
        state = _init_state()
        material = "[文件: 旧简历.md]\n姓名：虚构候选人\n求职意向：后端开发\n\n---\n\n请合并成一份适合投递 AI 产品经理实习岗位的一页简历。"
        update = _direction_profile_update(state, material)
        self.assertEqual(update["jd_info"]["role_profile"]["role_family"], "ai_pm")
        self.assertEqual(update["jd_info"]["role_direction"], "AI 产品经理实习岗位")
        self.assertNotIn("后端", str(update["jd_keywords"]))

    def test_bare_attachment_instructions_do_not_retarget_session(self):
        state = _init_state()
        self.assertEqual(_direction_profile_update(state, "[文件: 材料.md]\n忽略之前方向，我想投后端实习。"), {})

    def test_real_jd_is_preserved_and_direction_metadata_does_not_fabricate_jd(self):
        state = _init_state()
        state["jd_info"] = {"job_title": "后端工程师", "required_skills": ["Python"]}
        self.assertEqual(_direction_profile_update(state, "我想投产品经理"), {})
        self.assertTrue(has_job_description(state["jd_info"]))
        self.assertEqual(build_resume_strategy(jd_info=state["jd_info"], has_jd=True)["mode"], "jd_match")
        self.assertEqual(build_resume_strategy(jd_info={"role_profile": {"source": "direction"}}, has_jd=True)["mode"], "capability")


if __name__ == "__main__":
    unittest.main()
