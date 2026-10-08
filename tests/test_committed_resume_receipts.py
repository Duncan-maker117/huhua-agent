"""Receipts reflect disposable SQL commits, never the pre-sanitization draft."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import test_product_security_flow as fixtures
from langchain_core.messages import AIMessage, HumanMessage
from app.agents.resume_graph import stream_agent, _writer_reply
from app.services.session_store import load_resume_session, save_resume_session
from app.services.resume_capacity import resume_data_hash, normalize_session_constraints
from app.services.resume_versions import text_hash
from app.services.resume_workspace import tailor_metadata


class CommittedResumeReceiptTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ProductSecurityFlow.asyncSetUp
    cleanup = fixtures.ProductSecurityFlow.cleanup
    login = fixtures.ProductSecurityFlow.login

    async def test_fact_cleaned_commit_rewrites_receipt_even_when_checkpoint_repair_fails(self):
        limits = normalize_session_constraints({})
        data = {'projects': [{'item_id': 'p1', 'name': '合成接口项目', 'polished_bullets': ['旧原型表述']} ]}
        facts = {'projects': [{'item_id': 'p1', 'name': '合成接口项目', 'facts': [
            {'id': 'old', 'text': '旧原型表述', 'source_quote': '旧原型表述', 'status': 'deleted'}]}]}
        page = {'status': 'rendered', 'pages': 2, 'within_page_limit': False,
                'template_id': limits['template_id'], 'page_limit': 1, 'data_hash': resume_data_hash(data)}
        meta = {'version_id': 'v1', 'writer_diagnostic': {'status': 'model_completed'}, 'page_check': page,
                'bullets': {'p1': [{'fact_ids': ['old'], 'text_hash': text_hash('旧原型表述')}]}}
        old_reply = _writer_reply({'resume_data': data, 'page_check': page, 'changed': True})
        for fail_repair in (False, True):
            with self.subTest(fail_repair=fail_repair):
                values = {'resume_data': copy.deepcopy(data), 'resume_meta': copy.deepcopy(meta),
                          'collected_info': copy.deepcopy(facts), 'session_constraints': limits,
                          'stage': 'EVALUATING', 'resume_versions': [],
                          'messages': [HumanMessage(content='修改简历', id='human'),
                                       AIMessage(content=old_reply, id='writer-receipt')]}
                async def events(*args, **kwargs):
                    yield 'updates', {'building': {'messages': [values['messages'][-1]]}}
                graph = SimpleNamespace(astream=events, aget_state=AsyncMock(return_value=SimpleNamespace(values=values)),
                                        aupdate_state=AsyncMock(side_effect=RuntimeError('synthetic checkpoint failure') if fail_repair else None))
                def measure(cleaned, effective):
                    self.assertEqual(cleaned['projects'][0]['polished_bullets'], [])
                    return {**page, 'pages': 1, 'within_page_limit': True, 'data_hash': resume_data_hash(cleaned)}
                captured = []
                def save(*args, **kwargs):
                    result = save_resume_session(*args, **kwargs)
                    captured.append(result)
                    return result
                sid = 'committed-receipt-' + str(fail_repair)
                with patch('app.agents.resume_graph.get_graph', return_value=graph), \
                     patch('app.services.session_store.save_resume_session', side_effect=save), \
                     patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measure):
                    chunks = [chunk async for chunk in stream_agent([{'content': '修改简历'}], sid, object())]
                reply = ''.join(chunks)
                self.assertIn('实际为 1 页', reply)
                self.assertNotIn('实际为 2 页', reply)
                self.assertNotIn('未保存', reply)
                self.assertIn('事实校验', reply)
                stored = load_resume_session(sid)
                self.assertEqual(stored['resume_data']['projects'][0]['polished_bullets'], [])
                self.assertEqual(captured[0]['resume_data'], stored['resume_data'])
                self.assertEqual(captured[0]['resume_meta']['page_check']['data_hash'], resume_data_hash(stored['resume_data']))
                self.assertIsNone(captured[0]['resume_meta']['page_check']['within_page_limit'])
                repair = graph.aupdate_state.call_args.args[1]
                self.assertEqual(repair['resume_data'], stored['resume_data'])
                self.assertEqual(repair['messages'][0].id, 'writer-receipt')
                self.assertEqual(repair['messages'][0].content, reply)

    async def test_workspace_marks_mismatched_pages_stale_without_rendering(self):
        data = {'projects': [{'item_id': 'p1', 'name': '合成项目', 'polished_bullets': ['实现接口']}]}
        constraints = normalize_session_constraints({})
        page = {'status': 'rendered', 'pages': 1, 'within_page_limit': True,
                'template_id': constraints['template_id'], 'page_limit': 1, 'data_hash': resume_data_hash(data)}
        with patch('app.services.resume_capacity.measure_rendered_pages', side_effect=AssertionError('GET must not render')):
            for change in ({'data_hash': 'old'}, {'template_id': 'wrong-template'}, {'page_limit': 2}):
                with self.subTest(change=change):
                    values = {'resume_meta': {'page_check': {**page, **change}}, 'session_constraints': constraints}
                    result = tailor_metadata(values, data)
                    self.assertEqual(result['page_check']['status'], 'stale')
                    self.assertIsNone(result['page_check']['pages'])
                    self.assertIsNone(result['resume_meta']['page_check']['within_page_limit'])
                    self.assertEqual(values['resume_meta']['page_check']['status'], 'rendered')
            valid = tailor_metadata({'resume_meta': {'page_check': page}, 'session_constraints': constraints}, data)
            self.assertEqual(valid['page_check'], page)


if __name__ == '__main__':
    unittest.main()
