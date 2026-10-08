"""Guest-to-account behavior on isolated encrypted stores, without real mail/LLM."""
import asyncio
import copy
import io
import unittest
import zipfile
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage

import test_product_security_flow as harness
from app.agents.resume_graph import _init_state
from app.models.models import Conversation
from app.models.profile import ProfileArchiveEvent, ProfileSource
from app.services.canonical_resume import resume_revision
from app.services.conversation_store import checkpoint_owner
from app.services.profile_bridge import import_claimed_history
from app.services.session_store import save_resume_session, session_lock


class GuestExperienceFlow(unittest.IsolatedAsyncioTestCase):
    # Reuse the encrypted DB/mailbox harness without inheriting/repeating its tests.
    asyncSetUp = harness.ProductSecurityFlow.asyncSetUp
    cleanup = harness.ProductSecurityFlow.cleanup
    login = harness.ProductSecurityFlow.login
    fixture = harness.ProductSecurityFlow.fixture

    async def guest(self):
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver", headers={"Origin": "http://testserver"})
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_guest_can_preview_samples_but_export_history_and_memory_require_login(self):
        visitor = await self.guest()
        me = (await visitor.get("/api/account/me")).json()
        self.assertTrue(me["guest_allowed"])
        self.assertFalse(me["authenticated"])
        self.assertEqual((await visitor.get("/api/resume/templates")).status_code, 200)
        sample = (await visitor.get("/api/resume/sample")).json()
        preview = await visitor.post("/api/resume/render/t001-jianyue", json=sample)
        self.assertEqual(preview.status_code, 200, preview.text)
        for path in ("/api/resume/render/t001-jianyue?export=true", "/api/resume/export/docx/t001-jianyue"):
            denied = await visitor.post(path, json=sample)
            self.assertEqual(denied.status_code, 401, denied.text)
        for path in ("/api/chat/conversations", "/api/profile", "/api/chat/export/docx?session_id=missing"):
            self.assertEqual((await visitor.get(path)).status_code, 401)

    async def test_guest_stream_then_login_claim_preserves_content_and_enables_export(self):
        visitor = await self.guest()
        data = {"basic_info": {"name": "GUEST_FLOW_MARKER"}, "projects": [{"name":"虚构工具","description":"参与需求整理。"}]}
        async def synthetic_stream(messages, session_id, llm):
            user = HumanMessage(content=messages[-1]["content"], id="guest-human-" + session_id)
            await self.graph.aupdate_state({"configurable":{"thread_id":session_id}},
                {**_init_state(),"stage":"EVALUATING","resume_data":data,
                 "messages":[user,AIMessage(content="已整理当前简历。",id="guest-ai-"+session_id)]},as_node="building")
            save_resume_session(session_id,data,stage="EVALUATING",archive_event={"source_id":user.id,"event_type":"human_message","payload":{"human_text":user.content}})
            yield "已整理当前简历。"
        with patch("app.api.chat._get_llm",return_value=object()), patch("app.api.chat.stream_agent",side_effect=synthetic_stream):
            streamed = await visitor.post("/api/chat/stream",json={"messages":[{"role":"user","content":"我叫GUEST_FLOW_MARKER，参与虚构工具的需求整理。"}]})
        self.assertEqual(streamed.status_code,200,streamed.text)
        self.assertNotIn('"error"',streamed.text)
        with self.factory() as db:
            guest_rows = db.query(Conversation).filter(Conversation.owner_hash.startswith("guest:")).all()
            self.assertEqual(len(guest_rows),1)
            sid = guest_rows[0].session_id
            self.assertEqual(db.query(ProfileArchiveEvent).count(),0)
            self.assertEqual(db.query(ProfileSource).count(),0)
        original_binding=checkpoint_owner(sid)
        current=await visitor.get("/api/resume/current",params={"session_id":sid})
        self.assertEqual(current.json()["data"]["basic_info"]["name"],"GUEST_FLOW_MARKER")
        self.assertEqual((await visitor.get(f"/api/chat/conversations/{sid}")).status_code,200)
        self.assertEqual((await visitor.get("/api/chat/conversations")).status_code,401)
        self.assertEqual((await visitor.post("/api/resume/export/docx/t001-jianyue",params={"session_id":sid},json=data)).status_code,401)
        account_id=await self.login(visitor,"guest-upgrade@example.test")
        claimed=await visitor.post("/api/account/claim-guest",json={"session_id":sid})
        self.assertEqual(claimed.status_code,200,claimed.text)
        self.assertEqual(claimed.json()["session_id"],sid)
        self.assertEqual(checkpoint_owner(sid),original_binding)
        history=(await visitor.get("/api/chat/conversations")).json()["conversations"]
        self.assertIn(sid,[row["session_id"] for row in history])
        continued=(await visitor.get(f"/api/chat/conversations/{sid}")).json()
        self.assertEqual(continued["resume_data"]["basic_info"]["name"],"GUEST_FLOW_MARKER")
        self.assertEqual(len(continued["messages"]),2)
        exported=await visitor.post("/api/resume/export/docx/t001-jianyue",params={"session_id":sid},json=data)
        self.assertEqual(exported.status_code,200,exported.text[:100] if exported.status_code!=200 else "")
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            self.assertIn("GUEST_FLOW_MARKER",archive.read("word/document.xml").decode())
        await import_claimed_history(self.saver)
        with self.factory() as db:
            events=db.query(ProfileArchiveEvent).filter_by(account_id=account_id).all()
            self.assertEqual(len(events),1)
        self.assertEqual((await self.b.get(f"/api/chat/conversations/{sid}")).status_code,404)

    async def test_guest_cannot_read_another_browser_or_claim_with_id_alone(self):
        visitor=await self.guest()
        intruder=await self.guest()
        sid,data=await self.fixture(visitor,marker="PRIVATE_GUEST_CANARY")
        for path in (f"/api/chat/conversations/{sid}",f"/api/resume/current?session_id={sid}"):
            response=await intruder.get(path)
            self.assertEqual(response.status_code,404,response.text)
            self.assertNotIn("PRIVATE_GUEST_CANARY",response.text)
        edited=copy.deepcopy(data)
        edited["basic_info"]["name"]="ATTACK"
        r=await intruder.put("/api/resume/current",json={"session_id":sid,"expected_revision":resume_revision(data),"resume_data":edited})
        self.assertEqual(r.status_code,404,r.text)
        r=await self.a.post("/api/account/claim-guest",json={"session_id":sid})
        self.assertEqual(r.status_code,404,r.text)
        r=await visitor.put("/api/resume/current",json={"session_id":sid,"expected_revision":resume_revision(data),"resume_data":edited,"archive_facts":True})
        self.assertEqual(r.status_code,401,r.text)
        r=await visitor.post("/api/resume/render/t001-jianyue",json=data)
        self.assertEqual(r.status_code,409,r.text)

    async def test_owner_is_rechecked_when_guest_write_waited_behind_login_claim(self):
        visitor=await self.guest()
        sid,data=await self.fixture(visitor,marker="CLAIM_RACE_MARKER")
        account_client=await self.guest()
        account_client.cookies.update(visitor.cookies)
        await self.login(account_client,"race-owner@example.test")
        pending=None
        async with session_lock(sid):
            pending=asyncio.create_task(visitor.delete(f"/api/chat/session/{sid}"))
            await asyncio.sleep(.05)
            # Simulate claim's transactional owner transfer while owning the same lock.
            with self.factory() as db:
                row=db.get(Conversation,sid)
                title=row.title
                row.owner_hash="account:"+(await account_client.get("/api/account/me")).json()["account"]["id"]
                row.title=title
                db.commit()
        rejected=await pending
        self.assertEqual(rejected.status_code,404,rejected.text)
        self.assertEqual((await account_client.get(f"/api/chat/conversations/{sid}")).status_code,200)

    async def test_production_middleware_allows_guest_preview_but_keeps_same_origin(self):
        import main
        self.settings.APP_ENV="production"
        # Exercise middleware with the fixture's test origin using HTTPS clients.
        self.settings.APP_ORIGIN="https://testserver"
        self.settings.AUTH_COOKIE_SECURE=True
        from fastapi import FastAPI
        production=FastAPI()
        production.state.account_service=self.service
        production.state.checkpointer=self.saver
        production.include_router(harness.account.router,prefix="/api")
        production.include_router(harness.conversations.router,prefix="/api/chat")
        production.include_router(harness.resume.router,prefix="/api/resume")
        production.middleware("http")(main.security_headers)
        visitor=httpx.AsyncClient(transport=httpx.ASGITransport(app=production),base_url="https://testserver",headers={"Origin":"https://testserver"})
        self.addAsyncCleanup(visitor.aclose)
        with patch("main.get_settings",return_value=self.settings):
            sample=(await visitor.get("/api/resume/sample")).json()
            self.assertEqual((await visitor.post("/api/resume/render/t001-jianyue",json=sample)).status_code,200)
            created=await visitor.post("/api/chat/conversations")
            self.assertEqual(created.status_code,200,created.text)
            cookie=created.headers.get("set-cookie","")
            self.assertIn("Secure",cookie)
            self.assertIn("HttpOnly",cookie)
            self.assertNotIn("Max-Age",cookie)
            self.assertEqual((await visitor.get("/api/chat/conversations")).status_code,401)
            cross=await visitor.post("/api/chat/conversations",headers={"Origin":"https://evil.example"})
            self.assertEqual(cross.status_code,403)
