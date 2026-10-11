"""P2 encrypted archive, projection, and session identity regressions."""

import copy
import unittest

import test_profile_archive as archive_fixture
import test_resume_provenance as provenance_fixture
from test_p2_data_fidelity import HEADER, LISTS
from app.agents.profile_archivist import ArchiveBatch
from app.agents.resume_graph import _serialize_to_resume_data
from app.agents.turn_actions import choose_edit_plan
from app.services import profile_service as archive
from app.services.edit_plan import execute_edit_plan
from app.services.session_store import save_resume_session


class P2ArchiveTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = archive_fixture.ArchiveTests.asyncSetUp
    asyncTearDown = archive_fixture.ArchiveTests.asyncTearDown
    add = archive_fixture.ArchiveTests.add
    profile = archive_fixture.ArchiveTests.profile
    event = archive_fixture.ArchiveTests.event

    async def test_p2_all_rows_header_and_education_survive_encrypted_archive_roundtrip(self):
        self.event(HEADER + LISTS)
        async def fake_extractor(payload, context):
            return ArchiveBatch()
        outcome = await archive.process_pending_events(self.factory, fake_extractor)
        self.assertEqual(outcome["completed"], 1)
        for field, value in {"major": "计算机科学与技术", "degree": "本科", "start_date": "2023.09",
                             "end_date": "2027.06", "highlights": "校级三等奖学金"}.items():
            self.add(category="education", subject="示例甲大学", field=field, value=value)
        with self.factory() as db:
            context = archive.get_context(db, "a", include_contacts=True, limit=100,
                                          subject_ids=[fact["id"] for fact in self.profile()["facts"]])
            facts = archive.context_to_collected_info(context)
        data = _serialize_to_resume_data({"collected_info": facts})
        self.assertEqual({item["name"] for item in data["open_source"]}, {"StarBoat 项目", "CloudNote"})
        self.assertEqual(len(data["awards"]), 3)
        self.assertIn("等待审核", str(next(item for item in data["open_source"] if item["name"] == "CloudNote")["bullets"]))
        self.assertEqual(data["education"][0]["major"], "计算机科学与技术")
        self.assertIn("奖学金", data["education"][0]["highlights"])
        self.assertEqual(len(data["basic_info"]["links"]), 2)
        self.assertEqual(data["basic_info"]["availability"], "每周 6 天，6 个月起")

    async def test_p2_multiple_prs_in_same_repository_do_not_conflict_in_profile(self):
        self.event("开源贡献：\n- StarBoat PR #1：修复文件校验。\n- StarBoat PR #2：修复列表分页。")
        async def fake_extractor(payload, context):
            return ArchiveBatch()
        await archive.process_pending_events(self.factory, fake_extractor)
        self.assertEqual(self.profile()["conflicts"], [])
        with self.factory() as db:
            facts = archive.context_to_collected_info(archive.get_context(db, "a",
                subject_ids=[fact["id"] for fact in self.profile()["facts"]]))
        self.assertEqual({item["pr"] for item in facts["open_source"]}, {"PR #1", "PR #2"})

    async def test_p2_deleted_header_link_does_not_remove_unrelated_links(self):
        first = self.add(category="basic", subject="GitHub", field="link", value="https://github.com/fictional-example")
        self.add(category="basic", subject="个人主页", field="link", value="example.test")
        with self.factory() as db:
            data = _serialize_to_resume_data({"collected_info": archive.context_to_collected_info(
                archive.get_context(db, "a", include_contacts=True))})
            archive.delete_fact(db, "a", first["id"], first["revision"])
            guarded, _ = archive.sanitize_projection(db, "a", data)
            db.commit()
        self.assertNotIn("fictional-example", str(guarded))
        self.assertIn("example.test", str(guarded))


class P2StoredIdentityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = provenance_fixture.ResumeProvenanceTests.asyncSetUp
    cleanup = provenance_fixture.ResumeProvenanceTests.cleanup
    login = provenance_fixture.ResumeProvenanceTests.login
    fixture = provenance_fixture.ResumeProvenanceTests.fixture
    fact = provenance_fixture.ResumeProvenanceTests.fact
    current = provenance_fixture.ResumeProvenanceTests.current
    imported = provenance_fixture.ResumeProvenanceTests.imported
    linked = provenance_fixture.ResumeProvenanceTests.linked
    mapping = provenance_fixture.ResumeProvenanceTests.mapping

    async def test_p2_authorized_move_keeps_id_binding_and_old_version_delete_barrier(self):
        sid, fact, view = await self.imported(subject="StarBoat", field="description", value="参与整理需求")
        old = copy.deepcopy(view["data"])
        item = self.linked(old)
        item_id = item["item_id"]
        facts = {"projects": [copy.deepcopy(item)]}
        instruction = "StarBoat 这是开源贡献"
        moved = execute_edit_plan(old, {}, choose_edit_plan(instruction, old, []),
                                  collected_info=facts, instruction=instruction)
        save_resume_session(sid, moved["data"], stage="EVALUATING", collected_info=moved["collected_info"],
                            resume_meta={"operation_results": moved["operation_results"]},
                            resume_versions=[{"version_id": "old-synthetic", "resume_data": old}])
        current = await self.current(sid)
        self.assertEqual(current["data"]["open_source"][0]["item_id"], item_id)
        entry = self.mapping(sid)["items"][item_id]
        self.assertEqual(entry["collection"], "open_source")
        self.assertIn("projects", entry["previous_collections"])
        self.assertTrue(entry["fields"]["bullets"])
        response = await self.a.delete(f"/api/profile/facts/{fact['id']}?expected_revision={fact['revision']}")
        self.assertEqual(response.status_code, 200, response.text)
        current = await self.current(sid)
        self.assertEqual(current["data"]["open_source"][0]["bullets"], [])
        self.assertNotIn("参与整理需求", str(current.get("versions", [])))

    async def test_p2_profile_open_source_and_awards_can_be_imported_saved_and_reopened(self):
        sid, _ = await self.fixture()
        for category, field, value in (("open_source", "name", "StarBoat"), ("open_source", "pr", "PR #4"),
                                       ("open_source", "description", "修复文件校验"),
                                       ("awards", "name", "示例算法赛"), ("awards", "level", "省级三等奖")):
            fact = await self.fact(category=category, subject="StarBoat PR #4" if category == "open_source" else "示例算法赛",
                                   field=field, value=value)
            response = await self.a.post(f"/api/resume/session/{sid}/profile-facts", json={"fact_ids": [fact["id"]]})
            self.assertEqual(response.status_code, 200, response.text)
        current = await self.current(sid)
        self.assertEqual(current["data"]["open_source"][0]["name"], "StarBoat")
        self.assertEqual(current["data"]["open_source"][0]["pr"], "PR #4")
        self.assertEqual(current["data"]["awards"][0]["level"], "省级三等奖")
        self.assertEqual(current["data"]["open_source"][0]["bullets"], ["修复文件校验"])


if __name__ == "__main__":
    unittest.main()
