"""Offline public-web boundaries plus a real local TLS/HTTPX transport check."""
import asyncio
from contextlib import asynccontextmanager, nullcontext
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import socket
import ssl
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services import web_research as web


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        for index in range(0, len(self.body), 1024):
            yield self.body[index:index + 1024]


def response(body=b"", status=200, headers=None):
    return httpx.Response(status, headers=headers or {"content-type": "text/html"}, stream=BytesStream(body))


def public_dns(address="93.184.215.14"):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))]


def github_repo(owner="example", name="project", **extra):
    return {"name": name, "full_name": f"{owner}/{name}", "owner": {"login": owner}, "private": False,
            "description": "公开项目简介", "stargazers_count": 123, "forks_count": 7,
            "fork": False, "language": "Python", "updated_at": "2026-10-01T12:00:00Z", **extra}


class WebResearchTests(unittest.IsolatedAsyncioTestCase):
    async def _read_fixture(self, html, content_type="text/html"):
        @asynccontextmanager
        async def fetch(*_):
            yield response(html.encode(), headers={"content-type": content_type})
        with patch.object(web, "_resolve_public", AsyncMock(return_value="93.184.215.14")), patch.object(web, "_public_response", fetch):
            return await web.read_job_url("https://example.com/jobs/fixture")

    def test_reject_nonpublic_ambiguous_and_credential_urls(self):
        invalid = [
            "file:///etc/passwd", "https://user:pass@example.com/job", "http://localhost/",
            "http://foo.local/", "http://127.0.0.1/", "http://169.254.169.254/",
            "http://10.1.2.3/", "http://172.16.1.1/", "https://[::1]/", "http://[::ffff:8.8.8.8]/",
            "https://[64:ff9b::a00:1]/", "http://[2002:0808:0808::1]/", "http://224.0.0.1/",
            "http://192.0.0.9/", "https://example.com:8443/", "https://example.com:0/",
            "http://example.com\\@127.0.0.1/", "https://example.com/\nfoo", "https://foo/",
            "https://%31%32%37.0.0.1/", "https://[fe80::1%25eth0]/", "https://example..com/",
        ]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(web.WebResearchError):
                web._normalize_url(url)

    def test_canonical_url_removes_fragment_preserves_public_path(self):
        url, host, port = web._normalize_url("https://EXAMPLE.COM.:443/jobs?id=abc#detail")
        self.assertEqual((url, host, port), ("https://example.com/jobs?id=abc", "example.com", 443))
        self.assertTrue(web._public_ip("2606:4700:4700::1111"))
        self.assertFalse(web._public_ip("ff02::1"))

    async def test_mixed_dns_answers_and_numeric_local_name_are_rejected(self):
        loop = asyncio.get_running_loop()
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=public_dns() + public_dns("127.0.0.1"))):
            with self.assertRaises(web.WebResearchError):
                await web._resolve_public("example.com", 443)
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=public_dns("127.0.0.1"))):
            with self.assertRaises(web.WebResearchError):
                await web._resolve_public("2130706433", 80)

    async def test_dns_error_is_safe_and_total_timeout_covers_resolution(self):
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(side_effect=socket.gaierror("secret-host"))):
            with self.assertRaises(web.WebResearchError) as caught:
                await web.read_job_url("https://example.com/")
            self.assertNotIn("secret-host", caught.exception.message)
        async def stall(*_):
            await asyncio.sleep(1)
        with patch.object(web, "_resolve_public", stall), patch.object(web, "TOTAL_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(web.WebResearchError) as caught:
                await web.read_job_url("https://example.com/")
            self.assertEqual(caught.exception.status_code, 504)

    async def test_redirect_revalidates_destination_before_request(self):
        visited = []
        @asynccontextmanager
        async def fetch(url, address):
            visited.append((url, address))
            yield response(status=302, headers={"location": "http://169.254.169.254/latest"})
        with patch.object(web, "_resolve_public", AsyncMock(return_value="93.184.215.14")), patch.object(web, "_public_response", fetch):
            with self.assertRaises(web.WebResearchError):
                await web.read_job_url("https://example.com/jobs")
        self.assertEqual(len(visited), 1)

    async def test_redirect_resolves_each_hop_and_stops_after_three(self):
        visited = []
        @asynccontextmanager
        async def fetch(url, address):
            visited.append(url)
            yield response(status=302, headers={"location": "/next"})
        resolve = AsyncMock(return_value="93.184.215.14")
        with patch.object(web, "_resolve_public", resolve), patch.object(web, "_public_response", fetch):
            with self.assertRaises(web.WebResearchError):
                await web.read_job_url("https://example.com/jobs")
        self.assertEqual((len(visited), resolve.await_count), (4, 4))

    async def test_relative_redirect_has_final_source_and_structured_job(self):
        job = {"@context": "https://schema.org", "@type": "JobPosting", "title": "后端工程师",
               "datePosted": "2026-10-01", "hiringOrganization": {"name": "示例公司"},
               "description": "<p>岗位职责：负责服务端接口与自动化测试。</p>" * 12}
        html = '<title>职位页</title><nav>杂乱导航</nav><script type="application/ld+json">' + json.dumps({"@graph": [job]}) + '</script><body>登录菜单</body>'
        @asynccontextmanager
        async def fetch(url, address):
            if url.endswith("/first"):
                yield response(status=302, headers={"location": "/jobs/2#details"})
            else:
                yield response(html.encode())
        with patch.object(web, "_resolve_public", AsyncMock(return_value="93.184.215.14")), patch.object(web, "_public_response", fetch):
            result = await web.read_job_url("https://example.com/first")
        self.assertEqual(result["url"], "https://example.com/jobs/2")
        self.assertEqual(result["title"], "后端工程师")
        self.assertEqual(result["published_at"], "2026-10-01")
        self.assertEqual(result["kind"], "job_page")
        self.assertIs(result["content_truncated"], False)
        self.assertIn("公司：示例公司", result["content"])
        self.assertNotIn("杂乱导航", result["content"])
        self.assertIsNotNone(datetime.fromisoformat(result["fetched_at"]).tzinfo)

    async def test_plain_main_and_body_report_actual_cleaned_truncation(self):
        for kind in ("plain", "main", "body"):
            for length in (web.READ_CONTENT_LIMIT, web.READ_CONTENT_LIMIT + 1):
                with self.subTest(kind=kind, length=length):
                    text = "岗" * length
                    # Trimmed whitespace/markup must not create a false positive.
                    source = text + "\n  " if kind == "plain" else f"<{kind}><p>{text}</p>\n </{kind}>"
                    result = await self._read_fixture(source, "text/plain" if kind == "plain" else "text/html")
                    self.assertEqual(result["content"], text[:web.READ_CONTENT_LIMIT])
                    self.assertIs(result["content_truncated"], length > web.READ_CONTENT_LIMIT)

    async def test_chinese_jobposting_single_description_reports_exact_limit(self):
        for length in (web.READ_CONTENT_LIMIT, web.READ_CONTENT_LIMIT + 1):
            with self.subTest(length=length):
                # No other fields may mask an early description truncation.
                job = {"@type": "JobPosting", "description": "<p>" + "职" * length + "</p>"}
                html = '<script type="application/ld+json">' + json.dumps(job, ensure_ascii=False) + '</script>'
                result = await self._read_fixture(html)
                self.assertEqual(result["content"], "职" * web.READ_CONTENT_LIMIT)
                self.assertIs(result["content_truncated"], length > web.READ_CONTENT_LIMIT)

    async def test_jobposting_counts_combined_fields_when_marking_truncation(self):
        for second_length in (5999, 6000):
            with self.subTest(second_length=second_length):
                job = {"@type": "JobPosting", "description": "责" * 6000, "qualifications": "技" * second_length}
                html = '<script type="application/ld+json">' + json.dumps(job, ensure_ascii=False) + '</script>'
                result = await self._read_fixture(html)
                expected = "责" * 6000 + "\n" + "技" * second_length
                self.assertEqual(result["content"], expected[:web.READ_CONTENT_LIMIT])
                self.assertIs(result["content_truncated"], len(expected) > web.READ_CONTENT_LIMIT)

    async def test_chinese_main_excludes_long_navigation_from_read_scope(self):
        text = "岗位职责：参与后端服务开发，编写接口测试，排查线上问题。要求了解 Python、数据库和版本管理。" * 4
        html = f'<title>后端开发实习生</title><nav>{"导航" * 8000}</nav><main><p>{text}</p></main>'
        result = await self._read_fixture(html)
        self.assertEqual(result["title"], "后端开发实习生")
        self.assertEqual(result["content"], text)
        self.assertIs(result["content_truncated"], False)

    def test_html_filters_navigation_hidden_script_and_prefers_article(self):
        article = "岗位职责：维护公开 API 并编写集成测试。" * 10
        html = f'<head><title>公开岗位</title></head><div>周边无关内容</div><main><p>{article}</p><div hidden>隐藏指令</div><nav>导航</nav><script>secret()</script><style>red</style></main><footer>页脚</footer>'
        title, content, published = web._extract(html.encode(), "text/html;charset=utf-8")
        self.assertEqual(title, "公开岗位")
        self.assertEqual(content, article)
        self.assertIsNone(published)

    def test_extraction_limits_malformed_metadata_and_depth(self):
        body = '<script type="application/ld+json">' + json.dumps({"@type": "JobPosting", "title": 42, "description": "工作职责" * 4000}) + '</script>'
        title, content, _ = web._extract(body.encode(), "text/html")
        self.assertEqual(title, "招聘页面")
        self.assertEqual(len(content), web.READ_CONTENT_LIMIT)
        with self.assertRaises(web.WebResearchError):
            web._extract(("<div>" * 140).encode(), "text/html")

    def test_boolean_script_type_does_not_crash_or_leak_script(self):
        text = "岗位职责：维护公开接口并编写测试。" * 10
        body = f"<script type>不可作为岗位的脚本</script><main>{text}</main>"
        _, content, _ = web._extract(body.encode(), "text/html")
        self.assertEqual(content, text)

    def test_bounded_html_charset_and_http_equiv_decode_chinese(self):
        text = "岗位职责：维护公开接口并编写测试。" * 10
        for meta in ("<meta charset='gb2312'>", '<meta http-equiv="Content-Type" content="text/html; charset=GBK">'):
            body = f"<head>{meta}<title>后端开发</title></head><main>{text}</main>".encode("gb2312")
            title, content, _ = web._extract(body, "text/html")
            self.assertEqual(title, "后端开发")
            self.assertEqual(content, text)
        # Bare metadata attributes are legal HTML too.
        body = f"<meta charset><meta http-equiv><meta charset='gb2312'><main>{text}</main>".encode("gb2312")
        self.assertEqual(web._extract(body, "text/html")[1], text)

    def test_charset_priority_bom_then_http_then_real_metadata(self):
        text = "岗位职责：维护公开接口并编写测试。" * 10
        body = f"<meta charset='gb2312'><main>{text}</main>".encode("utf-8")
        self.assertEqual(web._extract(body, "text/html;charset=utf-8")[1], text)
        self.assertEqual(web._extract(b"\xef\xbb\xbf" + body, "text/html;charset=gb2312")[1], text)
        misleading = f'<script>"<meta charset=gb2312>"</script><!-- <meta charset=gb2312> --><main>{text}</main>'
        self.assertEqual(web._extract(misleading.encode(), "text/html")[1], text)

    def test_undeclared_or_late_charset_garbling_is_rejected(self):
        text = "岗位职责：维护公开接口并编写测试。" * 20
        for body in (f"<main>{text}</main>".encode("gb2312"),
                     (" " * 8192 + f"<meta charset=gb2312><main>{text}</main>").encode("gb2312"),
                     ("<script>" + "x" * 100_000 + f"</script><main>{text}</main>").encode("gb2312")):
            with self.assertRaises(web.WebResearchError) as caught:
                web._extract(body, "text/html")
            self.assertIn("编码", caught.exception.message)

    async def test_login_or_empty_dynamic_page_has_manual_fallback(self):
        for text in ("<html><div id='app'></div><script>load()</script></html>", "<main>请先登录查看岗位" * 10 + "</main>"):
            @asynccontextmanager
            async def fetch(*_):
                yield response(text.encode())
            with patch.object(web, "_resolve_public", AsyncMock(return_value="93.184.215.14")), patch.object(web, "_public_response", fetch):
                with self.assertRaises(web.WebResearchError) as caught:
                    await web.read_job_url("https://example.com/")
                self.assertIn("上传", caught.exception.message)

    async def test_content_type_and_status_do_not_pass_binary_or_login(self):
        for status, headers in ((200, {"content-type": "application/pdf"}), (403, {}), (404, {})):
            @asynccontextmanager
            async def fetch(*_):
                yield response(b"private body", status=status, headers=headers)
            with patch.object(web, "_resolve_public", AsyncMock(return_value="93.184.215.14")), patch.object(web, "_public_response", fetch):
                with self.assertRaises(web.WebResearchError) as caught:
                    await web.read_job_url("https://example.com/")
                self.assertNotIn("private body", caught.exception.message)

    async def test_raw_and_decompressed_limits_and_truncated_encoding(self):
        cases = [
            response(b"x" * (web.MAX_BODY_BYTES + 1)),
            response(gzip.compress(b"x" * (web.MAX_BODY_BYTES + 1)), headers={"content-encoding": "gzip"}),
            response(gzip.compress(b"hello")[:-4], headers={"content-encoding": "gzip"}),
            response(b"invalid", headers={"content-encoding": "gzip"}),
            response(b"small", headers={"content-length": str(web.MAX_BODY_BYTES + 1)}),
            response(b"small", headers={"content-encoding": "br"}),
        ]
        for item in cases:
            with self.subTest(headers=item.headers), self.assertRaises(web.WebResearchError):
                await web._bounded_body(item)
        normal = "岗位职责".encode() * 20
        self.assertEqual(await web._bounded_body(response(gzip.compress(normal), headers={"content-encoding": "gzip"})), normal)

    def test_search_query_excludes_contacts_links_and_resume_blocks(self):
        for company, role in [("a@example.com", "开发"), ("公司", "138 0013 8000"), ("公司", "https://private.test"),
                              ("公司", "我做过项目\n其他经历"), ("公司", "www.example.com"), ("", ""), ("a" * 81, "开发")]:
            with self.subTest(company=company, role=role), self.assertRaises(web.WebResearchError):
                web._search_query(company, role)
        self.assertEqual(web._search_query("示例公司", "后端开发"), "示例公司 后端开发 岗位职责")

    def test_search_allows_normal_technology_names(self):
        for role in (".NET 后端", "C/C++ 开发", "Node.js 全栈", "CI/CD 工程师"):
            self.assertEqual(web._search_query("示例公司", role), f"示例公司 {role} 岗位职责")

    async def test_missing_key_disables_provider(self):
        provider = AsyncMock()
        with patch.object(web, "get_settings", return_value=SimpleNamespace(TAVILY_API_KEY="")), patch.object(web, "_search_response", provider):
            with self.assertRaises(web.WebResearchError) as caught:
                await web.search_job_context("示例公司", "后端开发")
            self.assertEqual(caught.exception.status_code, 503)
            provider.assert_not_called()

    async def test_search_filters_unsafe_duplicates_caps_and_marks_only_real_date(self):
        rows = [{"title": "内部", "url": "http://127.0.0.1/", "content": "bad"}]
        rows += [{"title": "<b>岗位</b>", "url": f"https://example.com/{i}", "content": "岗位描述" * 600,
                  "published_date": "2026-10-01" if i == 0 else "unknown"} for i in range(6)]
        rows.insert(2, rows[1])
        with patch.object(web, "get_settings", return_value=SimpleNamespace(TAVILY_API_KEY="test-key")), patch.object(web, "_search_response", AsyncMock(return_value={"results": rows})) as provider, patch.object(web, "_resolve_public", AsyncMock(return_value="93.184.215.14")):
            results = await web.search_job_context("示例公司", "后端开发")
        self.assertEqual(len(results), 4)
        self.assertEqual(len({r["url"] for r in results}), 4)
        self.assertEqual(provider.call_args.args, ("示例公司 后端开发 岗位职责", "test-key"))
        self.assertEqual(results[0]["published_at"], "2026-10-01")
        self.assertNotIn("published_at", results[1])
        self.assertEqual(results[0]["title"], "岗位")
        self.assertEqual(len(results[0]["content"]), 1800)
        self.assertTrue(all(item["kind"] == "search_result" for item in results))
        self.assertTrue(all("content_truncated" not in item for item in results))

    async def test_provider_payload_is_minimal_and_errors_never_echo_body(self):
        seen = []
        class FakeTransport:
            def __init__(self, **kwargs):
                self.options = kwargs
            async def __aenter__(self):
                self_case.assertFalse(self.options["trust_env"])
                return self
            async def __aexit__(self, *_):
                pass
            async def handle_async_request(self, request):
                seen.append(request)
                return response(b'{"results": []}')
        self_case = self
        with patch.object(web.httpx, "AsyncHTTPTransport", FakeTransport):
            self.assertEqual(await web._search_response("公司 开发 岗位职责", "test-key"), {"results": []})
        request = seen[0]
        self.assertEqual(str(request.url), "https://api.tavily.com/search")
        payload = json.loads(request.content)
        self.assertEqual(payload["max_results"], 4)
        self.assertFalse(payload["include_raw_content"])
        self.assertFalse(payload["include_answer"])
        self.assertEqual(request.headers["authorization"], "Bearer test-key")
        for status in (301, 401, 403, 429, 432, 433, 500):
            async def fail(_self, request):
                return response(b'key-or-query-should-not-leak', status=status)
            with patch.object(web.httpx, "AsyncHTTPTransport", FakeTransport), patch.object(FakeTransport, "handle_async_request", fail):
                with self.assertRaises(web.WebResearchError) as caught:
                    await web._search_response("公司 开发 岗位职责", "test-key")
                self.assertNotIn("key-or-query", caught.exception.message)
                self.assertNotIn("test-key", caught.exception.message)

    async def test_search_provider_timeout_and_invalid_json_are_safe(self):
        with patch.object(web, "get_settings", return_value=SimpleNamespace(TAVILY_API_KEY="test-key")), patch.object(web, "_search_response", AsyncMock(side_effect=httpx.ReadTimeout("private-query"))):
            with self.assertRaises(web.WebResearchError) as caught:
                await web.search_job_context("公司", "开发")
            self.assertEqual(caught.exception.status_code, 504)
            self.assertNotIn("private-query", caught.exception.message)
        for body in (b"not-json-private-response", b"[]", b'{"results": null}'):
            class InvalidTransport:
                def __init__(self, **kwargs):
                    pass
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *_):
                    pass
                async def handle_async_request(self, request):
                    return response(body)
            with patch.object(web.httpx, "AsyncHTTPTransport", InvalidTransport):
                with self.assertRaises(web.WebResearchError) as caught:
                    await web._search_response("公司 开发 岗位职责", "test-key")
                self.assertEqual(caught.exception.status_code, 502)
                self.assertNotIn("private-response", caught.exception.message)

    async def test_search_result_dns_must_also_be_public(self):
        rows = [{"title": "岗位", "url": "https://private.example/jobs", "content": "岗位职责"}]
        with patch.object(web, "get_settings", return_value=SimpleNamespace(TAVILY_API_KEY="test-key")), patch.object(web, "_search_response", AsyncMock(return_value={"results": rows})), patch.object(web, "_resolve_public", AsyncMock(side_effect=web.WebResearchError("内部地址"))):
            self.assertEqual(await web.search_job_context("公司", "开发"), [])

    async def test_public_page_needs_no_job_text_and_ignores_embedded_jobposting(self):
        text = "这是一个公开作品主页。这里介绍界面设计、开源演示和项目链接，所有材料均供参考。"
        job = {"@type": "JobPosting", "description": "无关招聘职责" * 30}
        html = f'<title>公开作品</title><script type="application/ld+json">{json.dumps(job)}</script><main>{text}</main>'
        @asynccontextmanager
        async def fetch(*_):
            yield response(html.encode())
        with patch.object(web, "_resolve_public", AsyncMock(return_value="93.184.215.14")), patch.object(web, "_public_response", fetch):
            result = await web.read_public_url("https://example.com/portfolio")
        self.assertEqual(result["kind"], "public_page")
        self.assertEqual(result["content"], text)
        self.assertEqual(result["read_scope"], "public_page_text")
        self.assertEqual(result["request_count"], 1)
        self.assertFalse(result["content_truncated"])

    async def test_public_reader_still_rejects_private_and_credential_urls_before_io(self):
        resolver = AsyncMock()
        with patch.object(web, "_resolve_public", resolver):
            for url in ("http://127.0.0.1/", "https://user:password@github.com/example/project", "http://169.254.169.254/"):
                with self.subTest(url=url), self.assertRaises(web.WebResearchError):
                    await web.read_public_url(url)
        resolver.assert_not_called()

    async def test_github_profile_maps_to_two_bounded_official_api_requests(self):
        visited = []
        @asynccontextmanager
        async def fetch(url, address, **kwargs):
            visited.append((url, address, kwargs))
            data = {"login": "example", "name": "公开名称", "bio": "记录公开项目", "public_repos": 17}
            if "/repos?" in url:
                data = [github_repo(name=f"repo{i}") for i in range(9)]
            yield response(json.dumps(data).encode(), headers={"content-type": "application/json"})
        resolve = AsyncMock(return_value="140.82.112.6")
        with patch.object(web, "_resolve_public", resolve), patch.object(web, "_public_response", fetch):
            result = await web.read_public_url("github.com/example")
        self.assertEqual([item[0] for item in visited], [
            "https://api.github.com/users/example",
            "https://api.github.com/users/example/repos?type=owner&sort=updated&direction=desc&per_page=5&page=1"])
        self.assertTrue(all(item[1] == "140.82.112.6" and item[2]["accept"] == "application/vnd.github+json" for item in visited))
        self.assertEqual(resolve.await_args_list[0].args, ("api.github.com", 443))
        self.assertEqual(result["url"], "https://github.com/example")
        self.assertEqual(result["read_scope"], "github_profile_and_public_repositories")
        self.assertEqual(result["request_count"], 2)
        self.assertEqual(result["kind"], "public_page")
        self.assertIn("最多 5 个", result["content"])
        self.assertIn("未读取后续分页", result["content"])
        self.assertIn("example/repo4", result["content"])
        self.assertNotIn("example/repo5", result["content"])
        self.assertIn("不证明当前使用者拥有该账号", result["content"])

    async def test_github_repository_counts_are_observed_metadata_not_candidate_facts(self):
        fetch = AsyncMock(return_value=github_repo(stargazers_count=321))
        with patch.object(web, "_github_json", fetch):
            result = await web.read_public_url("https://github.com/example/project")
        fetch.assert_awaited_once_with("/repos/example/project")
        self.assertEqual(result["read_scope"], "github_repository_metadata")
        self.assertEqual(result["request_count"], 1)
        self.assertIn("Stars：321；Forks：7", result["content"])
        self.assertIn(result["fetched_at"], result["content"])
        self.assertIn("不是 Stars 统计时间", result["content"])
        self.assertIn("不是代码、README 或提交历史的完整审查", result["content"])
        self.assertNotIn("published_at", result)

    async def test_github_private_mismatched_and_guessed_repository_ownership_is_rejected(self):
        for data in (github_repo(private=True), github_repo(owner="another"), github_repo(name="same-name-guess"),
                     github_repo(full_name="unrelated/project"), github_repo(private=None)):
            with self.subTest(data=data), patch.object(web, "_github_json", AsyncMock(return_value=data)):
                with self.assertRaises(web.WebResearchError):
                    await web.read_public_url("https://github.com/example/project")
        values = [{"login": "example", "public_repos": 2}, [github_repo(owner="other"), github_repo(private=True), github_repo(name="real")]]
        with patch.object(web, "_github_json", AsyncMock(side_effect=values)):
            result = await web.read_public_url("https://github.com/example")
        self.assertIn("example/real", result["content"])
        self.assertNotIn("other/project", result["content"])
        self.assertNotIn("example/project", result["content"])
        self.assertIn("本次展示 1 个", result["content"])

    async def test_github_deep_link_tabs_and_lookalike_hosts_use_actual_page_only(self):
        page = AsyncMock(return_value={"kind": "public_page"})
        github = AsyncMock()
        with patch.object(web, "_read_web_url", page), patch.object(web, "_read_github_metadata", github):
            for url in ("https://github.com/example/repo/blob/main/app.py", "https://github.com/example?tab=stars",
                        "https://github.com.evil.example/example/repo", "https://github.com/login",
                        "https://github.com/example/repo?tab=readme-ov-file"):
                await web.read_public_url(url)
                page.assert_awaited_with(url, public_reference=True)
        github.assert_not_called()

    async def test_github_api_denials_redirects_and_invalid_payloads_are_safe(self):
        for status, body in ((301, b"redirect-token"), (404, b"secret"), (403, b"rate-secret"), (429, b"rate"), (200, b"not-json")):
            seen = []
            @asynccontextmanager
            async def fetch(url, address, **kwargs):
                seen.append(url)
                yield response(body, status=status, headers={"location": "http://127.0.0.1/private"})
            with self.subTest(status=status), patch.object(web, "_resolve_public", AsyncMock(return_value="140.82.112.6")), patch.object(web, "_public_response", fetch):
                with self.assertRaises(web.WebResearchError) as caught:
                    await web.read_public_url("https://github.com/example/project")
                self.assertNotIn("secret", caught.exception.message)
                self.assertNotIn("redirect-token", caught.exception.message)
            self.assertEqual(seen, ["https://api.github.com/repos/example/project"])

    async def test_github_read_deadline_bounds_two_requests_and_validates_api_dns(self):
        with patch.object(web, "_resolve_public", AsyncMock(side_effect=web.WebResearchError("非公开地址"))):
            with self.assertRaises(web.WebResearchError):
                await web.read_public_url("https://github.com/example/project")
        async def stall(*_):
            await asyncio.sleep(1)
        with patch.object(web, "_github_json", stall), patch.object(web, "TOTAL_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(web.WebResearchError) as caught:
                await web.read_public_url("https://github.com/example")
            self.assertEqual(caught.exception.status_code, 504)

    async def test_real_tls_transport_pins_socket_but_keeps_host_sni_and_verifies_certificate(self):
        # Only the socket target is local. The production URL validator remains
        # strict; this transport-only fixture supplies a local CA explicitly.
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "jobs.example.test")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
                .not_valid_after(now + timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("jobs.example.test")]), critical=False)
                .sign(key, hashes.SHA256()))
        requests, names = [], []
        payload = gzip.compress(("岗位职责：编写接口和测试。" * 20).encode())
        async def serve(reader, writer):
            requests.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Encoding: gzip\r\nContent-Length: " + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        original_transport = httpx.AsyncHTTPTransport
        with tempfile.TemporaryDirectory() as tmp:
            cert_path, key_path = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_ctx.load_cert_chain(cert_path, key_path)
            server_ctx.set_servername_callback(lambda _sock, name, _ctx: names.append(name))
            client_ctx = ssl.create_default_context(cafile=str(cert_path))
            def transport(**kwargs):
                self.assertFalse(kwargs["trust_env"])
                return original_transport(verify=client_ctx, **kwargs)
            loop = asyncio.get_running_loop()
            connections = []
            try:
                server = await asyncio.start_server(serve, "127.0.0.1", 0, ssl=server_ctx)
                port = server.sockets[0].getsockname()[1]
                dial_patch = nullcontext()
            except PermissionError:
                # Managed sandboxes forbid listen/bind. Replace only TCP dialing
                # with a connected socket pair; HTTPX, TLS, SNI and certificate
                # validation still run unchanged over real encrypted sockets.
                import anyio
                from httpcore._backends.anyio import AnyIOBackend, AnyIOStream
                server, port = None, 8443
                async def dial(_backend, host, port, **kwargs):
                    self.assertEqual((host, port), ("127.0.0.1", 8443))
                    client_socket, server_socket = socket.socketpair()
                    client_socket.setblocking(False)
                    server_socket.setblocking(False)
                    reader = asyncio.StreamReader()
                    task = asyncio.create_task(loop.connect_accepted_socket(
                        lambda: asyncio.StreamReaderProtocol(reader, client_connected_cb=serve),
                        server_socket, ssl=server_ctx))
                    connections.append(task)
                    return AnyIOStream(await anyio.abc.SocketStream.from_socket(client_socket))
                dial_patch = patch.object(AnyIOBackend, "connect_tcp", dial)
            previous_handler = loop.get_exception_handler()
            def expected_tls_reset(loop, context):
                if (context.get("message") == "Error on transport creation for incoming connection"
                        and isinstance(context.get("exception"), ConnectionResetError)):
                    return  # Expected when the client rejects the wrong certificate.
                if previous_handler:
                    previous_handler(loop, context)
                else:
                    loop.default_exception_handler(context)
            loop.set_exception_handler(expected_tls_reset)
            try:
                with dial_patch, self.assertNoLogs("httpx", level="INFO"), patch.object(web.httpx, "AsyncHTTPTransport", transport), patch.dict("os.environ", {"HTTPS_PROXY": "http://127.0.0.1:1"}):
                    async with web._public_response(f"https://jobs.example.test:{port}/role?x=1", "127.0.0.1") as actual:
                        body = await web._bounded_body(actual)
                    self.assertIn("岗位职责", body.decode())
                    self.assertEqual(names, ["jobs.example.test"])
                    self.assertIn(f"Host: jobs.example.test:{port}".encode(), requests[0])
                    self.assertTrue(requests[0].startswith(b"GET /role?x=1 HTTP/1.1"))
                    with self.assertRaises(httpx.ConnectError):
                        async with web._public_response(f"https://wrong.example.test:{port}/role", "127.0.0.1"):
                            self.fail("Wrong hostname certificate must never be accepted")
            finally:
                if server is not None:
                    server.close()
                    await server.wait_closed()
                for result in await asyncio.gather(*connections, return_exceptions=True):
                    if isinstance(result, BaseException):
                        self.assertIsInstance(result, ConnectionResetError)
                await asyncio.sleep(0)
                loop.set_exception_handler(previous_handler)


if __name__ == "__main__":
    unittest.main()
