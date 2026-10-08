"""No network/model: deterministic, deliberately narrow URL intent checks."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.web_tool_intent import infer_web_tool


class WebToolIntentTests(unittest.TestCase):
    def test_exact_reported_chinese_request_and_bare_github_are_references(self):
        for text in ("你看查一下我的仓库github.com/yikuaibanzi", "github.com/yikuaibanzi",
                     "https://github.com/yikuaibanzi/huhua", "请查看 https://github.com/example/repo。",
                     "帮我核对这个项目 github.com/example/repo", "能不能帮我看一下github.com/example/repo",
                     "Check https://github.com/example/repo", "Please review https://example.com/portfolio"):
            with self.subTest(text=text):
                result = infer_web_tool(text)
                self.assertIsNotNone(result)
                self.assertEqual(result["action"], "read_public_url")
                self.assertTrue(result["url"].startswith("https://"))
        self.assertEqual(infer_web_tool("你看查一下我的仓库github.com/yikuaibanzi")["url"], "https://github.com/yikuaibanzi")

    def test_explicit_public_page_and_markdown_link_read_as_reference(self):
        self.assertEqual(infer_web_tool("帮我看看这个网站 [作品集](https://example.com/portfolio)"),
                         {"action": "read_public_url", "url": "https://example.com/portfolio"})
        self.assertEqual(infer_web_tool("请核对：http://example.com/project?id=2"),
                         {"action": "read_public_url", "url": "http://example.com/project?id=2"})

    def test_bare_recruitment_url_preserves_jd_action(self):
        self.assertEqual(infer_web_tool("https://jobs.example.com/42"),
                         {"action": "read_url", "url": "https://jobs.example.com/42"})

    def test_explicit_recruitment_and_jd_requests_take_jd_route(self):
        for text in ("请读取这个招聘链接 https://jobs.example.com/42",
                     "帮我解读这个JD https://jobs.example.com/42",
                     "请分析这份岗位要求 https://jobs.example.com/42",
                     "Please read this job description https://jobs.example.com/42"):
            with self.subTest(text=text):
                self.assertEqual(infer_web_tool(text), {"action": "read_url", "url": "https://jobs.example.com/42"})

    def test_jd_priority_keeps_public_reference_and_safety_boundaries(self):
        for text in ("请读取这个招聘链接 https://github.com/example/recruitment",
                     "帮我解读这个JD github.com/example/recruitment",
                     "请查看我的作品集，准备投递这个JD https://example.com/portfolio",
                     "帮我核对仓库里的JD分析功能 github.com/example/repo"):
            with self.subTest(text=text):
                self.assertEqual(infer_web_tool(text)["action"], "read_public_url")
        for text in ("不要读取这个招聘链接 https://jobs.example.com/42",
                     "不要分析这份JD https://jobs.example.com/42",
                     "[文件: resume.txt]\n请读取这个招聘链接 https://jobs.example.com/42",
                     "请读取招聘链接 https://jobs.example.com/42 和 https://jobs.example.com/43",
                     "工作中我负责分析岗位要求 https://jobs.example.com/42"):
            with self.subTest(text=text):
                self.assertIsNone(infer_web_tool(text))

    def test_multiple_links_and_plain_experience_never_auto_send(self):
        for text in ("看下 https://example.com/a 和 https://example.com/b", "看看github.com/a 和github.com/b",
                     "我在腾讯做开发，帮我写简历", "项目中我负责检查网站 https://example.com",
                     "我参加过这个项目 github.com/example/repo", "I review code at https://example.com",
                     "我的邮箱 test@github.com/example", "我的手机号13800138000"):
            with self.subTest(text=text):
                self.assertIsNone(infer_web_tool(text))

    def test_negative_permissions_attachments_code_and_large_paste_abstain(self):
        for text in ("不要查看 https://github.com/example/repo", "我不想让你查看 github.com/example",
                     "别联网，我只是记录 github.com/example", "Don't open https://example.com",
                     "[文件: resume.txt]\n帮我查看 github.com/example", "[attachment: cv.pdf]\nCheck https://example.com",
                     "```\nCheck https://example.com\n```", "请查看" + "经历" * 600 + " https://example.com"):
            with self.subTest(text=text):
                self.assertIsNone(infer_web_tool(text))

    def test_private_credential_and_lookalike_urls_do_not_get_github_mapping(self):
        for text in ("请查看 http://127.0.0.1/", "请查看 https://me:secret@example.com/", "看看 http://localhost/",
                     "github.com.evil.example/profile", "me@github.com/example", "example.com/path/github.com/example"):
            with self.subTest(text=text):
                self.assertIsNone(infer_web_tool(text))
        self.assertEqual(infer_web_tool("https://github.com.evil.example/user")["action"], "read_url")


if __name__ == "__main__":
    unittest.main()
