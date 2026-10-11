"""Welcome metadata uses synthetic encrypted archives and an isolated database."""

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import test_profile_archive as fixtures
from app.agents.resume_graph import dialogue_node
from app.models.models import ResumeSession
from app.services import profile_bridge, profile_service


class P1ProfileWelcomeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ArchiveTests.asyncSetUp
    asyncTearDown = fixtures.ArchiveTests.asyncTearDown
    add = fixtures.ArchiveTests.add

    async def test_summary_is_account_scoped_counts_subjects_and_excludes_deleted_facts(self):
        self.add(category="basic", subject="本人", field="name", value="虚构小林")
        self.add(subject="项目甲", field="role", value="角色甲")
        self.add(subject="项目甲", field="description", value="私密说明甲")
        self.add(subject="项目乙", value="角色乙")
        self.add(account="b", subject="他人项目", value="他人说明")
        deleted = self.add(subject="已删除项目", value="已删除说明")
        with self.factory() as db:
            profile_service.delete_fact(db, "a", deleted["id"], deleted["revision"])
            db.commit()
            summary = profile_service.get_profile_summary(db, "a")
            empty = profile_service.get_profile_summary(db, "new-account")
        self.assertEqual(summary, {"has_facts": True, "name": "虚构小林", "experience_count": 2})
        self.assertEqual(empty, {"has_facts": False, "name": "", "experience_count": 0})
        self.assertNotIn("私密说明", str(summary))

    async def test_new_session_receives_welcome_summary_without_importing_experience_contents(self):
        self.add(category="basic", subject="本人", field="name", value="虚构小林")
        self.add(subject="项目甲", value="不应自动导入的分工")
        with self.factory() as db:
            db.add(ResumeSession(session_id="welcome-session", owner_key="account:a", resume_data={}, stage="JD_INPUT"))
            db.commit()
        graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values={})),
                                aupdate_state=AsyncMock())
        with patch.object(profile_bridge, "SessionLocal", self.factory), \
             patch.object(profile_bridge, "protect_data", side_effect=lambda owner, data, **kwargs: deepcopy(data)):
            await profile_bridge.prepare_graph_context("account:a", "welcome-session", graph)
        values = graph.aupdate_state.call_args.args[1]
        self.assertEqual(values["profile_summary"]["experience_count"], 1)
        self.assertFalse(values["collected_info"]["projects"])
        self.assertNotIn("不应自动导入的分工", str(values))
        reply = (await dialogue_node(values, None))["messages"][0].content
        self.assertIn("虚构小林，欢迎回来", reply)
        self.assertIn("档案里有 1 段经历", reply)


if __name__ == "__main__":
    unittest.main()
