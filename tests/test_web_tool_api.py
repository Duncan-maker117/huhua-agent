"""Tool integration on real encrypted ownership/storage; no network or live LLM."""
import copy
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

import test_product_security_flow as harness
from app.api import chat
from app.schemas.chat import ChatRequest
from app.services.profile_bridge import import_claimed_history
from app.services.profile_service import _open
from app.models.profile import ProfileSource


SOURCE = {"title": "公开测试岗位", "url": "https://careers.example.org/jobs/123",
          "fetched_at": "2026-10-06T10:00:00+00:00", "kind": "job_page",
          "content": "招聘方要求：熟悉 Kubernetes，负责系统可用性。这不是候选人的技能。"}


class WebToolAPI(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = harness.ProductSecurityFlow.asyncSetUp
    cleanup = harness.ProductSecurityFlow.cleanup
    login = harness.ProductSecurityFlow.login
    fixture = harness.ProductSecurityFlow.fixture

    def payload(self, sid, tool=None):
        return {"session_id": sid, "messages": [{"role": "user", "content": "请分析公开岗位"}],
                "web_tool": tool or {"action": "read_url", "url": SOURCE["url"]}}

    async def test_capabilities_are_public_booleans_without_keys(self):
        self.settings.TAVILY_API_KEY = ""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver") as visitor:
            response = await visitor.get("/api/chat/tools")
            self.assertEqual(response.json(), {"read_url": True, "read_public_url": True, "search": False})
            self.settings.TAVILY_API_KEY = "fake-fixture-key-never-sent"
            response = await visitor.get("/api/chat/tools")
            self.assertEqual(response.json(), {"read_url": True, "read_public_url": True, "search": True})
            self.assertNotIn("fake-fixture", response.text)

    async def test_invalid_tool_shape_is_rejected_before_any_provider(self):
        sid, _ = await self.fixture()
        for tool in ({"action": "exec", "command": "foo"},
                     {"action": "search", "company": "", "role": ""},
                     {"action": "search", "company": "x" * 81},
                     {"action": "read_url", "url": SOURCE["url"], "sources": [SOURCE]}):
            with self.subTest(tool=tool), patch.object(chat, "_execute_web_tool") as execute:
                r = await self.a.post("/api/chat/stream", json=self.payload(sid, tool))
                self.assertEqual(r.status_code, 422)
                execute.assert_not_called()

    def test_read_url_model_input_discloses_retrieval_scope(self):
        tool = ChatRequest(**self.payload("scope-test")).web_tool
        for flag in (True, False, None):
            source = {**SOURCE, **({"content_truncated": flag} if flag is not None else {})}
            messages, task = chat._web_turn([{"role": "user", "content": "read"}], tool, [source])
            self.assertEqual(task, "decode_jd")
            text = messages[-1]["content"]
            self.assertIn("材料范围：", text)
            self.assertIn("前 12,000", text) if flag is True else self.assertIn("不代表已读取整个网站", text)
            self.assertIn(SOURCE["content"], text)

    async def test_missing_search_key_preserves_session_and_does_not_spend_turn(self):
        sid, data = await self.fixture()
        self.settings.TAVILY_API_KEY = ""
        with patch.object(chat, "_execute_web_tool") as execute, patch.object(chat, "reserve_turn") as reserve:
            r = await self.a.post("/api/chat/stream", json=self.payload(sid, {"action":"search","company":"测试公司","role":"开发"}))
            self.assertEqual(r.status_code, 503, r.text)
            execute.assert_not_called()
            reserve.assert_not_called()
        current = await self.a.get("/api/resume/current", params={"session_id": sid})
        self.assertEqual(current.json()["data"], data)

    async def test_other_account_cannot_trigger_tools_on_session(self):
        sid, _ = await self.fixture()
        with patch.object(chat, "_execute_web_tool") as execute, patch.object(chat, "_get_llm"):
            r = await self.b.post("/api/chat/stream", json=self.payload(sid))
        self.assertEqual(r.status_code, 404)
        execute.assert_not_called()

    async def test_explicit_public_profile_request_uses_tool_and_reference_route(self):
        sid, data = await self.fixture()
        captured = {}
        async def tokens(messages, _sid, _llm, **kwargs):
            captured.update(messages=messages, **kwargs)
            yield "已取得仓库公开指标 [1]。"
        source = {**SOURCE, "kind": "public_page", "url": "https://github.com/example-user"}
        execute = AsyncMock(return_value=[source])
        with (patch.object(chat, "_get_llm", return_value=object()),
              patch.object(chat, "_execute_web_tool", execute),
              patch.object(chat, "stream_agent", side_effect=tokens),
              patch.object(chat, "reserve_turn") as reserve):
            response = await self.a.post("/api/chat/stream", json={"session_id": sid,
                "messages": [{"role": "user", "content": "你看查一下我的仓库github.com/example-user"}]})
        self.assertIn('"tool": "read_public_url"', response.text)
        self.assertEqual(execute.await_args.args[0].url, source["url"])
        self.assertEqual(captured["task"], "research_job")
        self.assertEqual(captured["web_sources"], [source])
        reserve.assert_called_once()
        current = await self.a.get("/api/resume/current", params={"session_id": sid})
        self.assertEqual(current.json()["data"], data)

    async def test_inferred_tools_still_require_session_ownership(self):
        sid, _ = await self.fixture()
        with patch.object(chat, "_execute_web_tool") as execute, patch.object(chat, "reserve_turn") as reserve:
            response = await self.b.post("/api/chat/stream", json={"session_id": sid,
                "messages": [{"role": "user", "content": "查看 https://github.com/example-user"}]})
        self.assertEqual(response.status_code, 404)
        execute.assert_not_called()
        reserve.assert_not_called()

    async def test_attachments_or_explicit_edit_do_not_trigger_implicit_fetch(self):
        sid, _ = await self.fixture()
        async def tokens(*args, **kwargs):
            yield "原有简历流程"
        cases = [
            {"content": "[文件: resume.md]\n我的主页 github.com/example-user\n请查看我的资料", "task": "auto"},
            {"content": "查看 https://github.com/example-user", "task": "rewrite_experience"},
        ]
        for case in cases:
            with (patch.object(chat, "_get_llm", return_value=object()),
                  patch.object(chat, "_execute_web_tool") as execute,
                  patch.object(chat, "stream_agent", side_effect=tokens)):
                response = await self.a.post("/api/chat/stream", json={"session_id": sid,
                    "messages": [{"role": "user", "content": case["content"]}], "task": case["task"]})
            self.assertIn("原有简历流程", response.text)
            execute.assert_not_called()

    async def test_tool_error_has_fallback_and_does_not_call_model_or_modify_resume(self):
        sid, data = await self.fixture()
        with (patch.object(chat, "_get_llm", return_value=object()),
              patch.object(chat, "_execute_web_tool", AsyncMock(side_effect=HTTPException(422,"页面需登录，请粘贴 JD 正文或上传岗位截图"))),
              patch.object(chat, "stream_agent") as stream):
            r = await self.a.post("/api/chat/stream", json=self.payload(sid))
        self.assertIn('"type": "tool_status"', r.text)
        self.assertIn("页面需登录", r.text)
        self.assertIn("data: [DONE]", r.text)
        stream.assert_not_called()
        current = await self.a.get("/api/resume/current", params={"session_id": sid})
        self.assertEqual(current.json()["data"], data)

    async def test_search_sends_only_explicit_terms_and_uses_reference_route(self):
        sid, _ = await self.fixture()
        self.settings.TAVILY_API_KEY = "fake-fixture-key-never-sent"
        captured = {}

        async def tokens(messages, _sid, _llm, **kwargs):
            captured.update(messages=messages, **kwargs)
            yield "公开资料参考建议"

        source = {**SOURCE, "kind": "search_result"}
        execute = AsyncMock(return_value=[source])
        with (patch.object(chat, "_get_llm", return_value=object()),
              patch.object(chat, "_execute_web_tool", execute),
              patch.object(chat, "prepare_graph_context", AsyncMock()) as prepare,
              patch.object(chat, "stream_agent", side_effect=tokens)):
            payload = self.payload(sid, {"action":"search","company":"公开示例公司","role":"后端实习"})
            payload["messages"][-1]["content"] = "PRIVATE_DRAFT 邮箱 student@example.test"
            payload["task"] = "rewrite_experience"
            r = await self.a.post("/api/chat/stream", json=payload)
        self.assertIn('"type": "sources"', r.text)
        self.assertEqual(execute.await_args.args[0].company, "公开示例公司")
        self.assertEqual(captured["task"], "research_job")
        self.assertEqual(captured["web_sources"], [source])
        self.assertNotIn("PRIVATE_DRAFT", str(captured["messages"]))
        self.assertEqual(prepare.await_args.kwargs["context"]["facts"], [])

    async def test_guest_url_evidence_survives_claim_without_becoming_personal_fact(self):
        visitor = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver", headers={"Origin":"http://testserver"})
        self.addAsyncCleanup(visitor.aclose)
        sid, data = await self.fixture(visitor, marker="GUEST_SOURCE_BOUNDARY")
        from app.agents import resume_graph
        jd_info = {"job_title":"后端实习", "required_skills":["Kubernetes"]}
        with (patch.object(chat, "_get_llm", return_value=object()),
              patch.object(chat, "_execute_web_tool", AsyncMock(return_value=[copy.deepcopy(SOURCE)])),
              patch.object(resume_graph, "get_graph", return_value=self.graph),
              patch.object(resume_graph, "_run_decoder_and_build_reply", AsyncMock(return_value=(jd_info,"已读取岗位。")))):
            r = await visitor.post("/api/chat/stream", json=self.payload(sid))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn('"error"', r.text)
        snapshot = (await self.graph.aget_state({"configurable":{"thread_id":sid}})).values
        self.assertEqual(snapshot["web_sources"][0]["url"], SOURCE["url"])
        self.assertNotIn("Kubernetes", str(snapshot.get("collected_info")))
        self.assertEqual(snapshot["resume_data"], data)
        imported = snapshot["messages"][-2]
        self.assertEqual(imported.additional_kwargs["career_material_type"], "jd")
        account = await self.login(visitor, "research-claim@example.test")
        r = await visitor.post("/api/account/claim-guest", json={"session_id":sid})
        self.assertEqual(r.status_code, 200, r.text)
        await import_claimed_history(self.saver)
        with self.factory() as db:
            rows = db.query(ProfileSource).filter_by(account_id=account).all()
            web_rows = [row for row in rows if "Kubernetes" in str(_open(row))]
            self.assertTrue(web_rows)
            self.assertTrue(all(_open(row).get("source_kind") == "jd" for row in web_rows))
        async with self.inner.conn.execute("SELECT checkpoint FROM checkpoints") as cursor:
            records = await cursor.fetchall()
        self.assertNotIn("Kubernetes", str(records))
        history = await visitor.get(f"/api/chat/conversations/{sid}")
        self.assertEqual(history.json()["workspace"]["web_sources"][0]["url"], SOURCE["url"])


if __name__ == "__main__":
    unittest.main()
