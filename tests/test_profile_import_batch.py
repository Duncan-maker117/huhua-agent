"""Fictional 99-row imports and partial batch results against real HTTP/SQLite."""

import json
import unittest
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import select

import test_profile_archive as fixtures
from app.models.profile import ProfileFact, ProfileInbox, ProfileSource
from app.services import profile_memory as memory, profile_service as archive
from app.services.data_crypto import DataDecryptionError


def candidate(index, **changes):
    return {"category": "project", "subject": f"虚构项目{index}", "field": "description",
            "value": f"仅完成本地合成任务{index}，未上线", "evidence": f"合成记录{index}：本人明确提供", **changes}


class ImportBatchTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ArchiveTests.asyncSetUp
    asyncTearDown = fixtures.ArchiveTests.asyncTearDown
    add = fixtures.ArchiveTests.add
    profile = fixtures.ArchiveTests.profile

    async def import_rows(self, rows):
        response = await self.client.post("/api/profile/import-memory", headers={"x-test-account": "a"},
                                          json={"text": json.dumps(rows, ensure_ascii=False)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def inbox(self):
        with self.factory() as db:
            result = archive.list_inbox_items(db, "a")["items"]
            db.commit()
            return result

    def proposals(self, rows, account="a"):
        with self.factory() as db:
            for start in range(0, len(rows), 50):
                archive.propose_to_inbox(db, account, "synthetic-mcp-token", rows[start:start + 50])
            db.commit()

    async def batch(self, entries, action="accept", account="a"):
        return await self.client.post("/api/profile/confirmations/batch", headers={"x-test-account": account},
            json={"action": action, "items": [{"kind": row.get("kind", "inbox"), "id": row["id"],
                                              "expected_revision": row["expected_revision"]} for row in entries]})

    async def undo(self, batch_id, account="a"):
        return await self.client.post(f"/api/profile/import-memory/{batch_id}/undo", json={}, headers={"x-test-account": account})

    async def test_99_rows_direct_uncertain_conflicts_duplicates_and_batch_undo(self):
        conflicts, duplicates = [], []
        for index in range(10):
            self.add(category="education", subject=f"虚构学校{index}", field="major", value="原有专业")
            conflicts.append(candidate(index, category="education", subject=f"虚构学校{index}", field="major", value="另一专业"))
        for index in range(14):
            self.add(subject=f"已存项目{index}", field="role", value="Local QA")
            duplicates.append(candidate(index, subject=f"已存项目{index}", field="role", value="  local  qa  "))
        baseline = {row["id"]: row for row in self.profile()["facts"]}
        normal = [candidate(index) for index in range(60)]
        uncertain = [candidate(100 + index, evidence="uncertain: 日期待核实") for index in range(12)]
        uncertain += [candidate(200, value=""), candidate(201, value=None), candidate(202, value="[待补充]")]
        rows = normal + uncertain + conflicts + duplicates
        self.assertEqual(len(rows), 99)
        result = await self.import_rows(rows)
        self.assertEqual({key: result[key] for key in ("added_count", "uncertain_count", "conflict_count", "duplicate_count", "pending_count")},
                         dict(added_count=60, uncertain_count=15, conflict_count=10, duplicate_count=14, pending_count=25))
        profile = self.profile()
        self.assertEqual((len(profile["facts"]), len(profile["conflicts"]), len(self.inbox())), (84, 10, 15))
        new = [row for row in profile["facts"] if row["id"] not in baseline]
        for row in new:
            self.assertEqual(row["sources"][0]["kind"], "memory_import")
            self.assertEqual(row["sources"][0]["import_batch_id"], result["batch_id"])
            self.assertEqual(row["sources"][0]["evidence"], next(item["evidence"] for item in normal if item["subject"] == row["subject"]))
        for row in profile["facts"]:
            if row["id"] in baseline:
                self.assertEqual(row, baseline[row["id"]], "Duplicates must not even change prior provenance")
        self.assertNotIn(normal[0]["value"].encode(), self.path.read_bytes())
        undone = await self.undo(result["batch_id"])
        self.assertEqual(undone.json(), {"deleted_count": 60, "changed_count": 0, "cancelled_count": 25})
        self.assertEqual({row["id"]: row for row in self.profile()["facts"]}, baseline)
        self.assertEqual(self.inbox(), [])
        self.assertEqual(self.profile()["conflicts"], [])
        self.assertEqual((await self.undo(result["batch_id"])).json()["deleted_count"], 0)

    async def test_phone_normalization_conflict_and_explicit_uncertainty(self):
        self.add(category="basic", field="phone", value="18800001111")
        result = await self.import_rows([
            candidate(1, category="basic", subject="我", field="phone", value="188-0000-1111"),
            candidate(2, category="basic", field="phone", value="18800002222"),
            candidate(3, evidence="【不确定】可能记错了"), candidate(4, evidence="UNCERTAIN_date：待核对"),
            candidate(5, value="<请填写内容>"), candidate(6, value="仅本地验证，计划上线"),
        ])
        self.assertEqual([result[key] for key in ("added_count", "conflict_count", "uncertain_count", "duplicate_count")], [1, 1, 3, 1])
        self.assertEqual(next(row for row in self.profile()["facts"] if row["field"] == "phone")["value"], "18800001111")

    async def test_skills_do_not_auto_upgrade_and_repeated_read_keeps_conflict(self):
        self.add(category="skill", subject="技能", field="skill", value="了解 Python")
        result = await self.import_rows([candidate(1, category="skill", subject="技能", field="skill", value="熟练 Python / JavaScript")])
        self.assertEqual((result["added_count"], result["conflict_count"]), (1, 1))
        for _ in range(2):
            profile = self.profile()
            self.assertEqual(len(profile["conflicts"]), 1)
            self.assertEqual(next(row for row in profile["facts"] if row["value"] == "Python")["proficiency"], "了解")
        response = await self.batch([{**profile["conflicts"][0], "kind": "conflict"}])
        self.assertEqual(response.json()["accepted_count"], 1)
        self.assertEqual(next(row for row in self.profile()["facts"] if row["value"] == "Python")["proficiency"], "熟练")
        self.assertEqual((await self.undo(result["batch_id"])).json()["deleted_count"], 1)
        self.assertEqual([row["value"] for row in self.profile()["facts"]], ["Python"])

    async def test_undo_keeps_later_edits_other_batches_and_previous_conflict_target(self):
        before = self.add(field="role", value="原有角色")
        first = await self.import_rows([candidate(1), candidate(2, evidence="uncertain"), candidate(3, subject="测试项目", field="role", value="新角色")])
        second = await self.import_rows([candidate(4)])
        imported = next(row for row in self.profile()["facts"] if row["subject"] == "虚构项目1")
        with self.factory() as db:
            archive.edit_fact(db, "a", imported["id"], value="用户后来更正", expected_revision=imported["revision"])
            db.commit()
        response = await self.batch(self.inbox() + [{**row, "kind": "conflict"} for row in self.profile()["conflicts"]])
        self.assertEqual(response.json()["accepted_count"], 2)
        result = (await self.undo(first["batch_id"])).json()
        self.assertEqual((result["deleted_count"], result["changed_count"]), (1, 1))
        profile = self.profile()
        self.assertEqual(next(row for row in profile["facts"] if row["id"] == before["id"])["value"], "新角色")
        self.assertTrue(any(row["value"] == "用户后来更正" for row in profile["facts"]))
        self.assertTrue(any(row["subject"] == "虚构项目4" for row in profile["facts"]))
        self.assertEqual([row["id"] for row in profile["memory_imports"]], [second["batch_id"]])
        self.assertEqual((await self.undo(second["batch_id"], account="b")).status_code, 404)

    async def test_batch_99_mcp_all_success_and_replay_is_not_a_second_write(self):
        self.proposals([candidate(index) for index in range(99)])
        entries = self.inbox()
        response = await self.batch(entries)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()["accepted_count"], response.json()["failed_count"], response.json()["pending_count"]), (99, 0, 0))
        self.assertEqual(len(self.profile()["facts"]), 99)
        self.assertEqual((await self.batch(entries)).json()["failed_count"], 99)
        self.assertEqual(len(self.profile()["facts"]), 99)

    async def test_partial_stale_revisions_and_accurate_pending_count(self):
        self.proposals([candidate(index) for index in range(5)])
        entries = self.inbox()
        for item in entries[:2]:
            self.add(subject=item["subject"], field="description", value="另一处新添的本人信息")
        response = (await self.batch(entries)).json()
        self.assertEqual((response["accepted_count"], response["failed_count"], response["pending_count"]), (3, 2, 2))
        self.assertEqual({row["id"] for row in response["results"] if row.get("code") == "revision_conflict"}, {row["id"] for row in entries[:2]})
        self.assertEqual(len(self.profile()["facts"]), 5)
        self.assertEqual((await self.batch(self.inbox(), action="reject")).json()["pending_count"], 0)

    async def test_same_slot_batch_checks_initial_snapshot_not_its_own_writes(self):
        self.proposals([candidate(index, subject="同一虚构项目") for index in range(4)])
        result = (await self.batch(self.inbox())).json()
        self.assertEqual((result["accepted_count"], result["failed_count"]), (4, 0))

    async def test_partial_invalid_expired_and_foreign_items_do_not_rollback_success(self):
        await self.import_rows([candidate(1, value=""), candidate(2, evidence="uncertain")])
        self.proposals([candidate(3)])
        self.proposals([candidate(4)], account="b")
        entries = self.inbox()
        expired = next(row for row in entries if row["subject"] == "虚构项目3")
        with self.factory() as db:
            db.get(ProfileInbox, expired["id"]).expires_at = archive._now() - timedelta(seconds=1)
            foreign = archive.list_inbox_items(db, "b")["items"][0]
            db.commit()
        result = (await self.batch(entries + [foreign])).json()
        self.assertEqual((result["accepted_count"], result["failed_count"], result["pending_count"]), (1, 3, 1))
        self.assertEqual(len(self.profile()["facts"]), 1)
        self.assertEqual(self.profile("b")["facts"], [])
        self.assertEqual((await self.batch(self.inbox(), action="reject")).json()["rejected_count"], 1)

    async def test_partial_stale_conflict_does_not_lose_valid_inbox_item(self):
        old = self.add(field="role", value="原角色")
        await self.import_rows([candidate(1, subject="测试项目", field="role", value="新角色")])
        conflict = {**self.profile()["conflicts"][0], "kind": "conflict"}
        with self.factory() as db:
            archive.edit_fact(db, "a", old["id"], value="其他窗口更正", expected_revision=old["revision"])
            db.commit()
        self.proposals([candidate(3)])
        result = (await self.batch([conflict] + self.inbox())).json()
        self.assertEqual((result["accepted_count"], result["failed_count"]), (1, 1))
        self.assertEqual(result["results"][0]["code"], "revision_conflict")
        self.assertEqual(next(row for row in self.profile()["facts"] if row["id"] == old["id"])["value"], "其他窗口更正")

    async def test_auth_origin_and_missing_revision_rejected(self):
        self.proposals([candidate(1)])
        item = self.inbox()[0]
        body = {"action": "accept", "items": [{"kind": "inbox", "id": item["id"], "expected_revision": item["expected_revision"]}]}
        self.assertEqual((await self.client.post("/api/profile/confirmations/batch", json=body)).status_code, 401)
        self.assertEqual((await self.client.post("/api/profile/confirmations/batch", json=body,
            headers={"x-test-account": "a", "origin": "https://evil.test"})).status_code, 403)
        del body["items"][0]["expected_revision"]
        self.assertEqual((await self.client.post("/api/profile/confirmations/batch", json=body, headers={"x-test-account": "a"})).status_code, 422)
        self.assertEqual((await self.batch([item, item])).status_code, 422)
        self.assertEqual(self.profile()["facts"], [])

    async def test_import_failure_rolls_back_direct_writes_and_batch_provenance(self):
        original = memory.apply_candidate
        def fail_second(db, account_id, item, batch, **kwargs):
            if item["subject"] == "虚构项目2":
                raise DataDecryptionError("synthetic failure")
            return original(db, account_id, item, batch, **kwargs)
        with patch.object(memory, "apply_candidate", side_effect=fail_second):
            result = await self.client.post("/api/profile/import-memory", headers={"x-test-account": "a"},
                json={"text": json.dumps([candidate(1), candidate(2)])})
        self.assertEqual(result.status_code, 503)
        with self.factory() as db:
            for model in (ProfileFact, ProfileSource, ProfileInbox):
                self.assertEqual(list(db.scalars(select(model))), [])

    async def test_import_sources_are_not_reenqueued_by_archive_compensation(self):
        await self.import_rows([candidate(1), candidate(2, evidence="uncertain")])
        with self.factory() as db:
            self.assertEqual(archive.compensate_archive_events(db, "a"), 0)
            db.commit()
        self.assertEqual(len(self.profile()["facts"]), 1)
        self.assertEqual(len(self.inbox()), 1)
