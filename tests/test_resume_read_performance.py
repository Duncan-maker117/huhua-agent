"""Committed reads and layout scheduling on disposable stores; no model calls."""
import asyncio
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import test_product_security_flow as fixtures
from app.agents.resume_graph import stream_agent
from app.services.session_store import session_lock, load_resume_session


class ResumeReadPerformanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ProductSecurityFlow.asyncSetUp(self)
        patcher = patch('app.api.resume.SessionLocal', self.factory)
        patcher.start()
        self.patches.append(patcher)

    cleanup = fixtures.ProductSecurityFlow.cleanup
    login = fixtures.ProductSecurityFlow.login
    fixture = fixtures.ProductSecurityFlow.fixture

    async def test_reads_return_committed_data_while_chat_owns_lock(self):
        sid, data = await self.fixture(marker='已提交的虚构姓名')
        proposed = {**data, 'basic_info': {'name': '未提交的虚构姓名'}}
        with patch('app.api.resume.render_resume_pdf', return_value=b'%PDF-synthetic') as pdf, \
             patch('app.api.resume.resume_data_to_docx', return_value=b'PK-synthetic') as docx:
            async with session_lock(sid):
                for path in ('render', 'export/docx', 'export/pdf'):
                    response = await asyncio.wait_for(self.a.post(
                        f'/api/resume/{path}/t001-jianyue?session_id={sid}', json=proposed), 1)
                    self.assertEqual(response.status_code, 200, path)
                    if path == 'render':
                        self.assertIn('已提交的虚构姓名', response.text)
                        self.assertNotIn('未提交的虚构姓名', response.text)
                current = await asyncio.wait_for(self.a.get(f'/api/resume/current?session_id={sid}'), 1)
                self.assertEqual(current.json()['data']['basic_info']['name'], '已提交的虚构姓名')
                interactive = await asyncio.wait_for(self.a.post(
                    f'/api/resume/render/t001-jianyue?session_id={sid}&interactive=true', json=proposed), 1)
                self.assertEqual(interactive.status_code, 200, interactive.text)
                self.assertIn('未提交的虚构姓名', interactive.text)
            self.assertEqual(pdf.call_args.args[1]['basic_info']['name'], '已提交的虚构姓名')
            self.assertEqual(docx.call_args.args[0]['basic_info']['name'], '已提交的虚构姓名')

    async def test_stream_save_and_editor_save_measure_off_event_loop(self):
        sid, data = await self.fixture(marker='虚构线程测试')
        loop_thread = threading.current_thread()
        measured = []

        def measure(*args, **kwargs):
            self.assertIsNot(threading.current_thread(), loop_thread)
            self.assertIsNot(threading.current_thread(), threading.main_thread())
            measured.append(threading.get_ident())
            return {'status': 'render_error', 'pages': None}

        values = {'resume_data': data, 'stage': 'EVALUATING', 'collected_info': data}

        async def events(*args, **kwargs):
            if False:
                yield

        graph = SimpleNamespace(astream=events, aget_state=AsyncMock(return_value=SimpleNamespace(values=values)),
                                aupdate_state=AsyncMock())
        with patch('app.agents.resume_graph.get_graph', return_value=graph), \
             patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measure):
            _ = [chunk async for chunk in stream_agent([{'content': '保存虚构资料'}], sid, object())]
        self.assertTrue(measured)
        self.assertEqual(load_resume_session(sid)['resume_data']['basic_info']['name'], '虚构线程测试')
        measured.clear()
        current = (await self.a.get(f'/api/resume/current?session_id={sid}')).json()
        data['basic_info']['name'] = '虚构编辑修改'
        with patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measure):
            response = await self.a.put('/api/resume/current', json={
                'session_id': sid, 'expected_revision': current['revision'], 'resume_data': data})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(measured)

    async def test_cancelled_stream_keeps_lock_until_save_thread_finishes(self):
        entered, release = threading.Event(), threading.Event()
        values = {'resume_data': {'basic_info': {'name': '虚构取消测试'}}, 'stage': 'EVALUATING'}

        async def events(*args, **kwargs):
            if False:
                yield

        graph = SimpleNamespace(astream=events, aget_state=AsyncMock(return_value=SimpleNamespace(values=values)))

        def save(**kwargs):
            entered.set()
            release.wait(2)

        async def stream():
            async with session_lock('synthetic-cancel'):
                _ = [chunk async for chunk in stream_agent([{'content': '保存'}], 'synthetic-cancel', object())]

        with patch('app.agents.resume_graph.get_graph', return_value=graph), \
             patch('app.services.session_store.save_resume_session', side_effect=save):
            task = asyncio.create_task(stream())
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                task.cancel()
                await asyncio.sleep(.01)
                self.assertFalse(task.done(), 'cancel must not release the write lock while saving')
                async def next_writer():
                    async with session_lock('synthetic-cancel'):
                        return True
                with self.assertRaises(TimeoutError):
                    await asyncio.wait_for(next_writer(), .02)
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task

