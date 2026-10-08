"""A page result belongs to the exact document that was rendered."""

import importlib.util
from pathlib import Path
from unittest import TestCase, mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("resume_capacity_commit_fix", ROOT / "backend/app/services/resume_capacity.py")
assert SPEC and SPEC.loader
capacity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capacity)


class CommittedPageCheckTest(TestCase):
    def test_changed_by_sanitizer_rerenders_but_cannot_claim_compression_success(self):
        before = {"projects": [{"item_id": "p1", "polished_bullets": ["A", "B"]}]}
        committed = {"projects": [{"item_id": "p1", "polished_bullets": ["A"]}]}
        previous = {"page_check": {"status": "rendered", "pages": 2, "within_page_limit": False,
                                   "page_limit": 1, "template_id": "t001-jianyue",
                                   "data_hash": capacity.resume_data_hash(before)}}
        rendered = {"status": "rendered", "pages": 1, "within_page_limit": True,
                    "page_limit": 1, "template_id": "t001-jianyue",
                    "data_hash": capacity.resume_data_hash(committed)}
        with mock.patch.object(capacity, "measure_rendered_pages", return_value=rendered) as measure:
            result = capacity.revalidate_committed_page_check(
                committed, previous, {"page_limit": 1, "template_id": "t001-jianyue"},
                content_changed=True, pre_sanitization_hash=capacity.resume_data_hash(before))
        measure.assert_called_once_with(committed, {"page_limit": 1, "template_id": "t001-jianyue"})
        page = result["page_check"]
        self.assertEqual(page["pages"], 1)
        self.assertIsNone(page["within_page_limit"])
        self.assertEqual(page["content_integrity"], "changed_by_fact_sanitizer")
        self.assertEqual(page["pre_sanitization_data_hash"], capacity.resume_data_hash(before))
        self.assertEqual(page["data_hash"], capacity.resume_data_hash(committed))
        self.assertEqual(previous["page_check"]["pages"], 2)

    def test_hash_matching_committed_document_does_not_need_another_render(self):
        data = {"projects": [{"item_id": "p1", "polished_bullets": ["A"]}]}
        meta = {"page_check": {"status": "rendered", "pages": 1,
                               "page_limit": 1, "template_id": "t001-jianyue",
                               "data_hash": capacity.resume_data_hash(data)}}
        with mock.patch.object(capacity, "measure_rendered_pages") as measure:
            result = capacity.revalidate_committed_page_check(data, meta,
                                                              {"page_limit": 1, "template_id": "t001-jianyue"})
        measure.assert_not_called()
        self.assertEqual(result, meta)

    def test_render_failure_never_inherits_old_page_count(self):
        data = {"projects": []}
        meta = {"page_check": {"status": "rendered", "pages": 2, "page_limit": 1,
                               "template_id": "t001-jianyue", "within_page_limit": False}}
        with mock.patch.object(capacity, "measure_rendered_pages", return_value={
            "status": "render_error", "pages": None, "within_page_limit": None,
            "data_hash": capacity.resume_data_hash(data)}) as measure:
            result = capacity.revalidate_committed_page_check(data, meta, {})
        measure.assert_called_once()
        self.assertEqual(result["page_check"]["status"], "render_error")
        self.assertIsNone(result["page_check"]["pages"])
