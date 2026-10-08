"""Opaque item identities preserve server fact bindings across manual edits."""

import copy
import io
import json
import unittest
import uuid
import zipfile
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select

import test_product_security_flow as fixtures
from app.agents.resume_graph import _serialize_to_resume_data
from app.models.profile import ProfileJobVersion
from app.schemas.editor import ResumeData
from app.services.canonical_resume import save_canonical_resume
from app.services.profile_bridge import prepare_graph_context
from app.services.profile_service import _open
from app.services.session_store import save_resume_session


class ResumeProvenanceTests(unittest.IsolatedAsyncioTestCase):
    cleanup = fixtures.ProductSecurityFlow.cleanup
    login = fixtures.ProductSecurityFlow.login
    fixture = fixtures.ProductSecurityFlow.fixture

    async def asyncSetUp(self):
        await fixtures.ProductSecurityFlow.asyncSetUp(self)
        p = patch("app.api.resume.SessionLocal", self.factory)
        p.start()
        self.patches.append(p)

    async def fact(self, *, subject="来源项目", field="role", value="项目负责人", category="project"):
        response = await self.a.post("/api/profile/facts", json={
            "category": category, "subject": subject, "field": field, "value": value,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return next(item for item in response.json()["facts"] if item["subject"] == subject and item["field"] == field)

    async def imported(self, *, field="role", value="项目负责人", subject="来源项目"):
        sid, _ = await self.fixture()
        fact = await self.fact(subject=subject, field=field, value=value)
        result = await self.a.post(f"/api/resume/session/{sid}/profile-facts", json={"fact_ids": [fact["id"]]})
        self.assertEqual(result.status_code, 200, result.text)
        return sid, fact, result.json()

    async def current(self, sid):
        response = await self.a.get(f"/api/resume/current?session_id={sid}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def save(self, sid, view, data, removed=(), client=None):
        return await (client or self.a).put("/api/resume/current", json={
            "session_id": sid, "expected_revision": view["revision"], "resume_data": data,
            "removed_item_ids": list(removed),
        })

    def linked(self, data):
        return next((item for item in data["projects"] if item.get("item_id") and item.get("name") != "课程工具"),
                    next(item for item in data["projects"] if item.get("item_id")))

    def mapping(self, sid):
        with self.factory() as db:
            row = db.scalar(select(ProfileJobVersion).where(ProfileJobVersion.session_id == sid))
            return copy.deepcopy(_open(row).get("projection_v1", {})) if row else {}

    async def test_import_rename_reorder_then_correction_blocks_original_field_and_copy(self):
        sid, fact, view = await self.imported()
        data = copy.deepcopy(view["data"])
        linked = self.linked(data)
        item_id = linked["item_id"]
        linked.update(name="完全不同的新名称", description="担任项目负责人")
        data["projects"].reverse()
        data["projects"].append({"name": "普通新项目", "description": "独立的手工内容"})
        saved = await self.save(sid, view, data)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.linked(saved.json()["data"])["item_id"], item_id)
        corrected = await self.a.patch(f"/api/profile/facts/{fact['id']}", json={"value": "参与开发", "expected_revision": fact["revision"]})
        self.assertEqual(corrected.status_code, 200, corrected.text)
        current = await self.current(sid)
        linked = self.linked(current["data"])
        self.assertEqual(linked["name"], "完全不同的新名称")
        self.assertEqual(linked["role"], "")
        self.assertEqual(linked["description"], "")
        self.assertEqual(current["data"]["projects"][-1]["description"], "独立的手工内容")

    async def test_renamed_rephrased_description_and_derived_bullets_remain_bound(self):
        sid, fact, view = await self.imported(field="description", value="参与整理需求")
        data = copy.deepcopy(view["data"])
        self.linked(data).update(name="重命名", description="参与梳理需求", polished_bullets=["参与梳理用户需求"])
        saved = await self.save(sid, view, data)
        self.assertEqual(saved.status_code, 200, saved.text)
        deleted = await self.a.delete(f"/api/profile/facts/{fact['id']}?expected_revision={fact['revision']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        linked = self.linked((await self.current(sid))["data"])
        self.assertEqual(linked["description"], "")
        self.assertEqual(linked["polished_bullets"], [])

    async def test_graph_rebuild_and_old_checkpoint_keep_id_and_delete_barrier(self):
        sid, fact, view = await self.imported()
        data = copy.deepcopy(view["data"])
        self.linked(data)["name"] = "图状态改名"
        saved = await self.save(sid, view, data)
        self.assertEqual(saved.status_code, 200, saved.text)
        await prepare_graph_context("account:" + self.account_a, sid, self.graph)
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": sid}})
        rebuilt = _serialize_to_resume_data(snapshot.values)
        self.assertEqual(self.linked(rebuilt)["item_id"], self.linked(data)["item_id"])
        save_resume_session(sid, rebuilt, stage="EVALUATING")
        stale_values = copy.deepcopy(snapshot.values)
        await self.a.delete(f"/api/profile/facts/{fact['id']}?expected_revision={fact['revision']}")
        await self.graph.aupdate_state({"configurable": {"thread_id": sid}}, stale_values, as_node="building")
        await prepare_graph_context("account:" + self.account_a, sid, self.graph)
        refreshed = await self.graph.aget_state({"configurable": {"thread_id": sid}})
        self.assertEqual(self.linked(refreshed.values["resume_data"])["role"], "")
        self.assertEqual(self.linked(refreshed.values["collected_info"])["role"], "")

    async def test_missing_duplicate_unknown_and_replaced_ids_are_rejected(self):
        sid, _, view = await self.imported()
        for change in ("missing", "unknown", "duplicate"):
            data = copy.deepcopy(view["data"])
            item = self.linked(data)
            if change == "missing":
                item.pop("item_id")
            elif change == "unknown":
                item["item_id"] = str(uuid.uuid4())
            else:
                data["projects"].append(copy.deepcopy(item))
            response = await self.save(sid, view, data)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((await self.current(sid))["data"], view["data"])

    async def test_cross_session_and_cross_account_item_ids_cannot_be_attached(self):
        sid, _, view = await self.imported()
        item = copy.deepcopy(self.linked(view["data"]))
        for client in (self.a, self.b):
            other_sid, data = await self.fixture(client=client)
            data["projects"].append(item)
            current = await client.get(f"/api/resume/current?session_id={other_sid}")
            response = await self.save(other_sid, current.json(), data, client=client)
            self.assertEqual(response.status_code, 409, response.text)

    async def test_explicit_deletion_preserves_tombstone_and_rejects_forged_removal(self):
        sid, _, view = await self.imported()
        item_id = self.linked(view["data"])["item_id"]
        for removed in ([str(uuid.uuid4())], [item_id], [item_id, item_id]):
            response = await self.save(sid, view, view["data"], removed)
            self.assertEqual(response.status_code, 409, response.text)
        data = copy.deepcopy(view["data"])
        data["projects"] = [item for item in data["projects"] if item.get("item_id") != item_id]
        self.assertEqual((await self.save(sid, view, data)).status_code, 409)
        preview = await self.a.post(f"/api/resume/render/t001-jianyue?interactive=true&session_id={sid}&removed_item_ids={item_id}", json=data)
        self.assertEqual(preview.status_code, 200, preview.text)
        deleted = await self.save(sid, view, data, [item_id])
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(self.mapping(sid)["items"][item_id]["removed"])
        self.assertEqual((await self.save(sid, deleted.json(), view["data"])).status_code, 409)

    async def test_manual_existing_value_is_not_bound_just_because_fact_was_selected(self):
        sid, data = await self.fixture()
        fact = await self.fact(subject="课程工具", value="别的职责")
        result = await self.a.post(f"/api/resume/session/{sid}/profile-facts", json={"fact_ids": [fact["id"]]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["data"]["projects"][0]["role"], data["projects"][0]["role"])
        item_id = result.json()["data"]["projects"][0]["item_id"]
        self.assertEqual(self.mapping(sid)["items"][item_id]["fields"], {})

    async def test_explicit_same_value_import_binds_existing_item(self):
        sid, data = await self.fixture()
        fact = await self.fact(subject="课程工具", value=data["projects"][0]["role"])
        result = await self.a.post(f"/api/resume/session/{sid}/profile-facts", json={"fact_ids": [fact["id"]]})
        self.assertEqual(result.status_code, 200, result.text)
        view = result.json()
        item = self.linked(view["data"])
        self.assertTrue(item["item_id"])
        item["name"] = "同值导入后的新名称"
        saved = await self.save(sid, view, view["data"])
        self.assertEqual(saved.status_code, 200, saved.text)
        await self.a.delete(f"/api/profile/facts/{fact['id']}?expected_revision={fact['revision']}")
        cleaned = self.linked((await self.current(sid))["data"])
        self.assertEqual(cleaned["role"], "")
        self.assertEqual(cleaned["description"], data["projects"][0]["description"])

    async def test_atomic_id_removal_and_exact_body_replacement_is_rejected(self):
        sid, _, view = await self.imported()
        data = copy.deepcopy(view["data"])
        item = self.linked(data)
        item_id = item.pop("item_id")
        item["name"] = "只是换一个项目显示名称"
        response = await self.save(sid, view, data, [item_id])
        self.assertEqual(response.status_code, 409, response.text)
        # Different newly authored content remains a normal delete-plus-add.
        item["role"] = ""
        item["description"] = "参与一项不同的课程调研"
        response = await self.save(sid, view, data, [item_id])
        self.assertEqual(response.status_code, 200, response.text)

    async def test_extraction_may_echo_existing_id_but_cannot_assign_one(self):
        from app.agents.fact_extractor import extract_facts_patch, apply_fact_patch
        from types import SimpleNamespace
        item_id = str(uuid.uuid4())
        current = {"projects": [{"item_id": item_id, "name": "来源项目", "role": "参与者"}]}
        parsed = {"items": [{"section": "projects", "item_id": item_id, "name": "来源项目", "facts": [
            {"kind": "action", "text": "整理需求", "source_quote": "整理需求"}]}]}
        class Model:
            async def ainvoke(self, _):
                return SimpleNamespace(content=json.dumps(parsed, ensure_ascii=False))
        patch = await extract_facts_patch("来源项目中整理需求", current, Model())
        merged = apply_fact_patch(current, patch)
        self.assertEqual(merged["projects"][0]["item_id"], item_id)
        self.assertIn("整理需求", [fact["text"] for fact in merged["projects"][0]["facts"]])
        parsed["items"][0]["item_id"] = str(uuid.uuid4())
        patch = await extract_facts_patch("来源项目中整理需求", current, Model())
        self.assertEqual(patch["items"], [])
        self.assertEqual(patch["rejected"][0]["reason"], "unknown_item_id")

    async def test_explicit_unauthenticated_local_compatibility_can_render_custom_body(self):
        self.a.cookies.clear()
        self.settings.REQUIRE_ACCOUNT = False
        data = {"basic_info": {"name": "本地兼容模式"}, "projects": [{"name": "自行填写"}]}
        response = await self.a.post("/api/resume/render/t001-jianyue?interactive=true", json=data)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("本地兼容模式", response.text)

    async def test_job_save_keeps_private_projection_metadata(self):
        sid, _, view = await self.imported()
        before = self.mapping(sid)
        result = await self.a.post("/api/profile/jobs", json={"session_id": sid, "name": "新岗位"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.mapping(sid), before)
        public = await self.a.get("/api/profile")
        self.assertNotIn("projection_v1", public.text)

    async def test_import_transaction_failure_rolls_back_bindings_and_checkpoint(self):
        sid, data = await self.fixture()
        fact = await self.fact()
        with patch("app.api.resume_changes.merge_job_version_import", side_effect=HTTPException(409, "并发冲突")):
            result = await self.a.post(f"/api/resume/session/{sid}/profile-facts", json={"fact_ids": [fact["id"]]})
        self.assertEqual(result.status_code, 409, result.text)
        self.assertFalse(self.mapping(sid))
        self.assertEqual((await self.current(sid))["data"], data)
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": sid}})
        self.assertEqual(snapshot.values["resume_data"], data)

    async def test_removal_transaction_failure_restores_active_map_and_data(self):
        sid, _, view = await self.imported()
        before = self.mapping(sid)
        item_id = self.linked(view["data"])["item_id"]
        data = copy.deepcopy(view["data"])
        data["projects"] = [item for item in data["projects"] if item.get("item_id") != item_id]

        def fail(*_):
            raise HTTPException(409, "保存回滚")

        with self.assertRaises(HTTPException):
            await save_canonical_resume(sid, view["revision"], data, self.graph, _serialize_to_resume_data,
                                        removed_item_ids=[item_id], after_save=fail)
        self.assertEqual(self.mapping(sid), before)
        self.assertEqual((await self.current(sid))["data"], view["data"])

    async def test_interactive_preview_keeps_unsaved_form_but_exports_committed_data(self):
        sid, _, view = await self.imported()
        data = copy.deepcopy(view["data"])
        self.linked(data)["name"] = "UNSAVED_PREVIEW_ONLY"
        preview = await self.a.post(f"/api/resume/render/t001-jianyue?interactive=true&session_id={sid}", json=data)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertIn("UNSAVED_PREVIEW_ONLY", preview.text)
        rendered = await self.a.post(f"/api/resume/render/t001-jianyue?session_id={sid}", json=data)
        self.assertEqual(rendered.status_code, 200, rendered.text)
        self.assertNotIn("UNSAVED_PREVIEW_ONLY", rendered.text)
        exported = await self.a.post(f"/api/resume/export/docx/t001-jianyue?session_id={sid}", json=data)
        self.assertEqual(exported.status_code, 200, exported.text if exported.status_code != 200 else "")
        with zipfile.ZipFile(io.BytesIO(exported.content)) as document:
            self.assertNotIn(b"UNSAVED_PREVIEW_ONLY", document.read("word/document.xml"))

    async def test_raw_body_and_stripped_id_cannot_bypass_render_or_export(self):
        sid, fact, view = await self.imported()
        data = copy.deepcopy(view["data"])
        self.linked(data)["name"] = "绕过尝试"
        self.linked(data).pop("item_id")
        await self.a.delete(f"/api/profile/facts/{fact['id']}?expected_revision={fact['revision']}")
        for endpoint in ("render", "export/docx"):
            response = await self.a.post(f"/api/resume/{endpoint}/t001-jianyue", json=data)
            self.assertEqual(response.status_code, 409, response.text)
        response = await self.a.post(f"/api/resume/render/t001-jianyue?interactive=true&session_id={sid}", json=data)
        self.assertEqual(response.status_code, 409, response.text)
        # An export with a session ignores arbitrary body data and reads the
        # canonical document, already protected by its server-held bindings.
        response = await self.a.post(f"/api/resume/export/docx/t001-jianyue?session_id={sid}", json=data)
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as document:
            self.assertNotIn("项目负责人", document.read("word/document.xml").decode())
        denied = await self.b.post(f"/api/resume/export/docx/t001-jianyue?session_id={sid}", json=data)
        self.assertEqual(denied.status_code, 404)

    async def test_sample_still_renders_and_exports_without_session(self):
        sample = await self.a.get("/api/resume/sample")
        self.assertEqual(sample.status_code, 200)
        for endpoint in ("render", "export/docx"):
            response = await self.a.post(f"/api/resume/{endpoint}/t001-jianyue", json=sample.json())
            self.assertEqual(response.status_code, 200)

    async def test_all_schema_projections_keep_id_without_exposing_it_in_resume_text(self):
        from app.services.resume_review import resume_to_text
        ids = [str(uuid.uuid4()) for _ in range(3)]
        data = {"education": [{"item_id": ids[0], "school": "学校"}],
                "work_experience": [{"item_id": ids[1], "company": "公司"}],
                "projects": [{"item_id": ids[2], "name": "项目"}]}
        normalized = ResumeData.model_validate(data).model_dump()
        rebuilt = _serialize_to_resume_data({"collected_info": normalized})
        for group, item_id in zip(("education", "work_experience", "projects"), ids):
            self.assertEqual(rebuilt[group][0]["item_id"], item_id)
            self.assertNotIn(item_id, resume_to_text(rebuilt))

    async def test_version_undo_preserves_sidecar_and_later_erasure(self):
        from app.services.resume_versions import prepare_version
        sid, fact, view = await self.imported(field="description", value="参与整理需求。")
        before = self.mapping(sid)
        changed = copy.deepcopy(view["data"])
        self.linked(changed)["description"] = "参与整理需求；"
        proposal = prepare_version(view["data"], {}, [], changed, {})
        applied = await save_canonical_resume(sid, view["revision"], changed, self.graph,
                    _serialize_to_resume_data, source="writer", resume_meta=proposal["resume_meta"],
                    resume_versions=proposal["resume_versions"])
        undone = await self.a.post(f"/api/resume/session/{sid}/versions/undo", json={"expected_revision": applied["revision"]})
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(self.mapping(sid), before)
        await self.a.delete(f"/api/profile/facts/{fact['id']}?expected_revision={fact['revision']}")
        self.assertEqual(self.linked((await self.current(sid))["data"])["description"], "")


if __name__ == "__main__":
    unittest.main()
