"""Actual PDF bytes, pagination, embedded photos, and account boundaries."""

import base64
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pdfplumber
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.resume_pdf import _photo_resource, render_resume_pdf
from app.services.renderer import list_templates
import test_product_security_flow as product_fixture


class ResumePdfRenderTest(unittest.TestCase):
    def test_all_templates_return_a4_pdf_with_chinese_text_and_uploaded_photo(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "data/sample_resume.json").read_text())
        photo = io.BytesIO()
        Image.new("RGB", (95, 120), (100, 160, 180)).save(photo, "PNG")
        data["basic_info"]["photo"] = "data:image/png;base64," + base64.b64encode(photo.getvalue()).decode()
        data["basic_info"]["name"] = "虚构测试"
        for template in list_templates():
            with self.subTest(template=template["id"]):
                result = render_resume_pdf(template["id"], data)
                self.assertTrue(result.startswith(b"%PDF-"))
                with pdfplumber.open(io.BytesIO(result)) as document:
                    text = "".join(page.extract_text() or "" for page in document.pages)
                    self.assertIn("虚构测试", "".join(text.split()))
                    self.assertIn("自我评价", text)
                    self.assertEqual(sum(len(page.images) for page in document.pages), 1)
                    for page in document.pages:
                        self.assertAlmostEqual(page.width, 595.28, delta=0.1)
                        self.assertAlmostEqual(page.height, 841.89, delta=0.1)

    def test_long_resume_keeps_last_project_on_later_page(self):
        data = {"basic_info": {"name": "分页验收"}, "projects": [
            {"name": f"项目{i:02}", "polished_bullets": ["负责整理本次课程的反馈并编写核对记录。" * 4]}
            for i in range(16)
        ]}
        result = render_resume_pdf("t004-jianyue", data)
        with pdfplumber.open(io.BytesIO(result)) as document:
            self.assertGreater(len(document.pages), 1)
            text = "".join(page.extract_text() or "" for page in document.pages)
            for i in range(16):
                self.assertIn(f"项目{i:02}", text)
            for page in document.pages:
                self.assertTrue(all(char["bottom"] <= page.height - 20 for char in page.chars))

    def test_resource_fetching_rejects_network_files_and_svg(self):
        for url in ("https://example.test/photo.png", "http://127.0.0.1/secret", "file:///etc/passwd",
                    "data:image/svg+xml;base64,PHN2Zy8+", "data:text/plain;base64,c2VjcmV0"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    _photo_resource(url)
                with patch("app.services.resume_pdf.render_resume", return_value=f'<html><head></head><body><img src="{url}"></body></html>'):
                    with self.assertRaises(Exception) as result:
                        render_resume_pdf("t001-jianyue", {})
                    self.assertIn("not an uploaded image", str(result.exception))

    def test_unknown_template_is_not_a_general_html_or_file_renderer(self):
        with self.assertRaises(ValueError):
            render_resume_pdf("../../private", {})

    def test_malformed_photo_is_rejected_before_renderer_can_log_its_data_url(self):
        with self.assertRaisesRegex(ValueError, "Invalid PDF photo"):
            _photo_resource("data:image/png;base64,bm90LWFuLWltYWdl")


class ResumePdfAccountTest(unittest.IsolatedAsyncioTestCase):
    # Reuse the real encrypted app fixture without inheriting its test cases.
    asyncSetUp = product_fixture.ProductSecurityFlow.asyncSetUp
    cleanup = product_fixture.ProductSecurityFlow.cleanup
    login = product_fixture.ProductSecurityFlow.login
    fixture = product_fixture.ProductSecurityFlow.fixture

    async def test_pdf_and_word_export_use_saved_authorized_content(self):
        sid, data = await self.fixture(marker="SAVED_PDF_CONTENT")
        data["basic_info"]["name"] = "UNSAVED_BODY_IGNORED"
        url = f"/api/resume/export/pdf/t002-jianyue?session_id={sid}"
        response = await self.a.post(url, json=data)
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertIn("filename*=UTF-8''", response.headers["content-disposition"])
        with pdfplumber.open(io.BytesIO(response.content)) as document:
            text = "".join((page.extract_text() or "") for page in document.pages)
            self.assertIn("SAVED_PDF_CONTENT", "".join(text.split()))
            self.assertNotIn("UNSAVED_BODY", text)
        for format in ("pdf", "docx"):
            denied = await self.b.post(f"/api/resume/export/{format}/t002-jianyue?session_id={sid}", json=data)
            self.assertEqual(denied.status_code, 404)
            self.assertNotIn("SAVED_PDF_CONTENT", denied.text)

    async def test_unauthenticated_export_rejected(self):
        self.a.cookies.clear()
        response = await self.a.post("/api/resume/export/pdf/t001-jianyue", json={})
        self.assertEqual(response.status_code, 401)

    async def test_pdf_failure_is_recoverable_and_does_not_expose_document(self):
        sid, data = await self.fixture()
        with patch("app.api.resume.render_resume_pdf", side_effect=RuntimeError("PRIVATE_DOCUMENT_DETAILS")):
            response = await self.a.post(f"/api/resume/export/pdf/t001-jianyue?session_id={sid}", json=data)
        self.assertEqual(response.status_code, 503)
        self.assertIn("PDF 生成失败", response.json()["detail"]["message"])
        self.assertNotIn("PRIVATE_DOCUMENT_DETAILS", response.text)
        word = await self.a.post(f"/api/resume/export/docx/t001-jianyue?session_id={sid}", json=data)
        self.assertEqual(word.status_code, 200)
        self.assertTrue(word.content.startswith(b"PK\x03\x04"))

    async def test_arbitrary_stateless_document_cannot_bypass_session_binding(self):
        response = await self.a.post("/api/resume/export/pdf/t001-jianyue", json={"basic_info": {"name": "not a public sample"}})
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
