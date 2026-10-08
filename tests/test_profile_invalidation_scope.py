"""Synthetic encrypted fixtures for fact-scoped correction/deletion barriers."""

import copy
import hashlib
import hmac
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models.profile import ProfileInvalidation, ProfileSource
from app.services import profile_bridge, profile_service as archive
from app.services.data_crypto import DataCrypto
from app.services.resume_review import resume_to_text


class ScopedInvalidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="huhua-scoped-invalidation-")
        self.engine = create_engine(f"sqlite:///{Path(self.directory.name) / 'isolated.sqlite3'}")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        crypto = DataCrypto({"test": b"s" * 32}, "test")
        patches = [patch.object(archive, "get_crypto", return_value=crypto),
                   patch.object(archive, "blind_index", side_effect=lambda value, scope: hmac.new(
                       b"invalidation-test-key", (scope + value).encode(), hashlib.sha256).hexdigest()),
                   patch.object(profile_bridge, "SessionLocal", self.factory)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self):
        self.engine.dispose()
        self.directory.cleanup()

    def add(self, *, account="a", category="education", subject="测试大学", field="end_date", value="2025"):
        with self.factory() as db:
            result = archive.add_fact(db, account, category=category, subject=subject, field=field, value=value)
            db.commit()
            return next(item for item in result["facts"] if item["subject"] == subject and item["field"] == field)

    def invalidate(self, fact, *, replacement="2026", delete=False, account="a"):
        with self.factory() as db:
            if delete:
                archive.delete_fact(db, account, fact["id"], fact["revision"])
            else:
                archive.edit_fact(db, account, fact["id"], value=replacement, expected_revision=fact["revision"])
            db.commit()

    def clean(self, data, account="a"):
        with self.factory() as db:
            return archive.sanitize_projection(db, account, data)

    def resume(self):
        return {"education": [{"school": "测试大学", "start_date": "2025", "end_date": "2025"},
                              {"school": "另一学校", "end_date": "2025"}],
                "projects": [{"name": "2025 校园信息工具", "description": "2025 年完成本地搜索功能", "end_date": "2025"}]}

    def test_year_correction_preserves_other_fields_subjects_and_categories(self):
        fact = self.add()
        self.invalidate(fact)
        source = self.resume()
        before = copy.deepcopy(source)
        clean, changed = self.clean(source)
        self.assertTrue(changed)
        self.assertEqual(clean["education"][0]["end_date"], "")
        self.assertEqual(clean["education"][0]["start_date"], "2025")
        self.assertEqual(clean["education"][1], source["education"][1])
        self.assertEqual(clean["projects"], source["projects"])
        self.assertEqual(source, before, "guard must not mutate caller data")

    def test_legacy_invalidation_without_category_uses_retained_tombstone(self):
        fact = self.add()
        self.invalidate(fact, delete=True)
        with self.factory() as db:
            row = db.scalar(select(ProfileInvalidation))
            payload = archive._open(row)
            payload.pop("category")
            row.payload = archive._seal(row, payload)
            db.commit()
        clean, _ = self.clean(self.resume())
        self.assertEqual(clean["education"][0]["end_date"], "")
        self.assertEqual(clean["projects"], self.resume()["projects"])

    def test_same_active_value_in_another_fact_does_not_exempt_deleted_fact(self):
        fact = self.add(category="project", subject="旧项目", field="role", value="参与开发")
        self.add(category="project", subject="新项目", field="role", value="参与开发")
        self.invalidate(fact, delete=True)
        clean, _ = self.clean({"projects": [{"name": "旧项目", "role": "参与开发"},
                                             {"name": "新项目", "role": "参与开发"}]})
        self.assertEqual(clean["projects"][0]["role"], "")
        self.assertEqual(clean["projects"][1]["role"], "参与开发")
        self.assertEqual(self.clean("参与开发")[0], "")

    def test_short_skill_uses_token_boundaries(self):
        fact = self.add(category="skill", subject="编程技能", field="skill", value="Go")
        self.invalidate(fact, delete=True)
        clean, _ = self.clean({"skills": ["Go", "Google Apps Script", "Golang"],
                               "self_evaluation": "使用 Google Docs。掌握 Go。保留 Python。"})
        self.assertEqual(clean["skills"], ["", "Google Apps Script", "Golang"])
        self.assertEqual(clean["self_evaluation"], "使用 Google Docs。保留 Python。")

    def test_known_fact_reference_is_independent_of_display_name(self):
        fact = self.add(category="project", subject="旧项目", field="role", value="项目负责人")
        self.invalidate(fact, replacement="参与开发")
        clean, _ = self.clean({"fact_id": fact["id"], "revision": 1, "category": "project",
                               "subject": "更名后的项目", "field": "role", "value": "项目负责人"})
        self.assertEqual(clean["value"], "")

    def test_manual_wording_survives_but_old_claim_in_same_slot_is_blocked(self):
        fact = self.add(category="project", subject="课程项目", field="role", value="负责人")
        self.invalidate(fact, replacement="不是负责人")
        clean, _ = self.clean({"projects": [{"name": "课程项目", "role": "不是负责人",
                                             "description": "完成接口测试", "polished_bullets": ["担任负责人"]}]})
        self.assertEqual(clean["projects"][0]["role"], "不是负责人")
        self.assertEqual(clean["projects"][0]["description"], "完成接口测试")
        self.assertEqual(clean["projects"][0]["polished_bullets"], [""])

    def test_unknown_legacy_body_quarantines_claim_not_whole_document(self):
        fact = self.add(category="project", subject="课程项目", field="role", value="秘密职责")
        self.invalidate(fact, delete=True)
        clean, changed = self.clean({"resume_draft": "保留说明。曾从事秘密职责。\n其他合法内容。"})
        self.assertTrue(changed)
        self.assertEqual(clean["resume_draft"], "保留说明。\n其他合法内容。")
        self.assertEqual(self.clean("课程项目\n担任秘密职责")[0], "课程项目\n")

    def test_legacy_rendered_body_scopes_year_to_education_heading(self):
        fact = self.add()
        self.invalidate(fact)
        text = resume_to_text(self.resume())
        clean, _ = self.clean(text)
        self.assertNotIn("2025 — 2025", clean)
        self.assertIn("2025 校园信息工具", clean)
        self.assertIn("2025 年完成本地搜索功能", clean)
        self.assertIn("另一学校\n2025", clean)
        self.assertEqual(self.clean("2025 年完成本地搜索功能"), ("2025 年完成本地搜索功能", False))
        self.assertEqual(self.clean("2025 年毕业")[0], "")
        self.assertEqual(self.clean("2021 — 2025")[0], "")

    def test_checkpoint_excludes_disabled_original_source_and_scopes_other_state(self):
        fact = self.add()
        with self.factory() as db:
            source = db.get(ProfileSource, fact["source_ids"][0])
            message_id = archive._open(source)["original_source_id"]
        self.invalidate(fact)
        state = {"resume_data": self.resume(), "collected_info": self.resume(),
                 "messages": [HumanMessage(id=message_id, content="2025 年毕业，同时参与校园信息工具"),
                              HumanMessage(id="other-message", content="2025 年完成本地搜索功能")]}
        clean = profile_bridge.protect_state("account:a", state)
        self.assertEqual([message.id for message in clean["messages"]], ["other-message"])
        for key in ("resume_data", "collected_info"):
            self.assertEqual(clean[key]["education"][0]["end_date"], "")
            self.assertEqual(clean[key]["projects"], self.resume()["projects"])

    def test_full_deleted_contacts_cannot_hide_in_unrelated_sections(self):
        for field, value in (("email", "private@example.invalid"), ("phone", "13800001234")):
            fact = self.add(category="basic", subject="本人", field=field, value=value)
            self.invalidate(fact, delete=True)
            clean, _ = self.clean({"basic_info": {field: value},
                                   "projects": [{"name": "无关项目", "description": "联系 " + value}],
                                   "sections": [{"id": "custom", "kind": "custom", "title": "说明", "content": value}]})
            self.assertNotIn(value, str(clean))

    def test_deleted_phone_country_code_and_formatting_cannot_bypass_guard(self):
        fact = self.add(category="basic", subject="本人", field="phone", value="13800001234")
        self.invalidate(fact, delete=True)
        for variant in ("+8613800001234", "0086 138 0000 1234", "+86 (138) 0000-1234", "138（0000）1234"):
            with self.subTest(variant=variant):
                source = {"basic_info": {"phone": variant},
                          "projects": [{"name": "独立项目", "description": "联系 " + variant}],
                          "sections": [{"id": "contact", "kind": "custom", "title": "联系", "content": variant}]}
                clean, changed = self.clean(source)
                self.assertTrue(changed)
                self.assertEqual(clean["basic_info"]["phone"], "")
                self.assertEqual(clean["projects"][0]["description"], "")
                self.assertEqual(clean["sections"][0]["content"], "")
                self.assertEqual(self.clean(source, "b"), (source, False))
        preserved = {"projects": [{"name": "订单查询", "description": "订单 991380000123499；标识 id13800001234；联系 13900001234"}]}
        self.assertEqual(self.clean(preserved), (preserved, False))

    def test_phone_invalidation_normalizes_stored_country_code_too(self):
        fact = self.add(category="basic", subject="本人", field="phone", value="+86 (138) 0000-1234")
        self.invalidate(fact, delete=True)
        clean, changed = self.clean({"basic_info": {"phone": "13800001234"}})
        self.assertTrue(changed)
        self.assertEqual(clean["basic_info"]["phone"], "")

    def test_subject_mention_cannot_invalidate_neighboring_school_or_project(self):
        fact = self.add()
        self.invalidate(fact)
        source = "另一学校 2025 年毕业。测试大学 2025 年毕业。\n2025 年完成本地搜索功能。"
        clean, _ = self.clean(source)
        self.assertEqual(clean, "另一学校 2025 年毕业。\n2025 年完成本地搜索功能。")
        source = "## 项目经历\n校园项目 · 参与者\n- 2025 年到测试大学做访谈。"
        self.assertEqual(self.clean(source), (source, False))

    def test_source_linked_record_does_not_survive_as_rephrased_content(self):
        fact = self.add()
        self.invalidate(fact, delete=True)
        clean, _ = self.clean([{"source_ids": fact["source_ids"], "description": "重新措辞的旧信息"},
                               {"source_id": "another-source", "description": "独立信息"}])
        self.assertEqual(clean, [{"source_id": "another-source", "description": "独立信息"}])

    def test_account_isolation_and_repeat_guard_idempotence(self):
        fact = self.add()
        self.invalidate(fact, delete=True)
        original = self.resume()
        self.assertEqual(self.clean(original, "b"), (original, False))
        first, _ = self.clean(original)
        self.assertEqual(self.clean(first), (first, False))


if __name__ == "__main__":
    unittest.main()
