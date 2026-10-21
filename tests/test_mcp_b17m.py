"""第十七批 m：离线协议、真实隔离渲染和栏目诊断回归。"""

from copy import deepcopy
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_mcp_protocol as legacy
from test_mcp_v2 import draft
from app.mcp.writing_guide import STANDARD_SECTIONS, writing_guide
from app.services import mcp_preview
from app.services.intake import basics_values, intake_guidance
from app.services.mcp_service import CONTACT_PLACEHOLDERS, layout_contacts, template_preview, templates_list
from app.services.resume_pdf import measure_resume_pdf_layout
from app.mcp.server import MCPResume


class MCPBatch17ProtocolTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = legacy.MCPProtocolTests.asyncSetUp
    cleanup = legacy.MCPProtocolTests.cleanup
    client = legacy.MCPProtocolTests.client
    call = legacy.MCPProtocolTests.call
    add = legacy.MCPProtocolTests.add

    async def test_instructions_and_tool_descriptions_define_workflows(self):
        instructions = self.server.instructions
        self.assertLessEqual(len(instructions.splitlines()), 20)
        for name in ('huhua_profile_get', 'huhua_writing_guide', 'huhua_resume_check_facts',
                     'huhua_resume_measure', 'huhua_resume_preview', 'huhua_resume_save', 'huhua_resume_export',
                     'fit_to_one_page', 'huhua_facts_propose', 'import_memory_to_profile', 'log_project_to_profile'):
            self.assertIn(name, instructions)
        for text in ('untrusted_text', '网页确认', '词法初筛不等于事实已验证', '不调用写作模型',
                     '验证/计划阶段', '不为迎合 JD 自创栏目名', 'gallery_url', '手机/邮箱不得进入任何 LLM 提示'):
            self.assertIn(text, instructions)
        async with self.client() as client:
            tools = {row.name: row for row in (await client.list_tools()).tools}
        for name in ('huhua_resume_measure', 'huhua_resume_preview'):
            self.assertIn('测量和预览请留空联系方式，导出时服务端从档案填入', tools[name].description)
        self.assertIn('PNG 只用于 agent 自查排版', tools['huhua_templates_list'].description)
        for role in ('general', 'ai-pm', 'backend'):
            guide = writing_guide(role)['section_policy']
            self.assertEqual(guide['standard_titles'], STANDARD_SECTIONS)
            self.assertIn('验证/计划阶段', ' '.join(guide['rules']))

    async def test_gallery_urls_use_configured_origin(self):
        self.service.origin = lambda: 'https://configured.example.test/'
        async with self.client() as client:
            result = await self.call(client, 'huhua_templates_list')
        self.assertEqual(result['gallery_url'], 'https://configured.example.test/resume')
        for row in result['templates']:
            self.assertEqual(row['gallery_url'], result['gallery_url'] + '?template=' + row['id'])
            self.assertNotIn('testserver', row['gallery_url'])

    def count_conversations(self):
        from app.models.models import Conversation
        with self.factory() as db:
            return db.query(Conversation).count()

    async def test_save_and_export_return_edit_url(self):
        template = 't001-jianyue'
        args = {'resume': draft(), 'template_id': template}
        async with self.client() as client:
            saved = await self.call(client, 'huhua_resume_save', args)
            expected = 'http://testserver/resume?session=' + saved['conversation_id'] + '&template=' + template + '&from=mcp'
            self.assertEqual(saved['edit_url'], expected)
            self.assertIn('/chat?session=', saved['conversation_url'])
            before = self.count_conversations()
            same = await self.call(client, 'huhua_resume_export', {
                'conversation_id': saved['conversation_id'], 'template_id': template})
            self.assertEqual(same['edit_url'], expected)
            self.assertEqual(same['conversation_id'], saved['conversation_id'])
            self.assertEqual(self.count_conversations(), before)
            fresh = await self.call(client, 'huhua_resume_export', args)
            self.assertEqual(self.count_conversations(), before + 1)
            self.assertNotEqual(fresh['conversation_id'], saved['conversation_id'])
            self.assertEqual(fresh['edit_url'], 'http://testserver/resume?session=' + fresh['conversation_id'] + '&template=' + template + '&from=mcp')
            self.assertNotIn('edit_url_unavailable', fresh)
            self.assertTrue((await self.web.get(fresh['download_url'])).content.startswith(b'%PDF-'))
            got = await self.call(client, 'huhua_resume_get', {'conversation_id': fresh['conversation_id']})
            self.assertEqual(got['untrusted_text']['resume']['projects'][0]['name'], '虚构项目')

    async def test_export_without_write_scope_or_checkpointer_still_succeeds(self):
        args = {'resume': draft(), 'template_id': 't001-jianyue'}
        limited = self.tokens.create('a', '只导出', ['resume:export'])
        before = self.count_conversations()
        async with self.client(limited) as client:
            result = await self.call(client, 'huhua_resume_export', args)
        self.assertNotIn('edit_url', result)
        self.assertIn('resume:write', result['edit_url_unavailable'])
        self.assertTrue(result['download_url'])
        self.service.checkpointer = lambda: None
        async with self.client() as client:
            result = await self.call(client, 'huhua_resume_export', args)
        self.assertNotIn('edit_url', result)
        self.assertIn('edit_url_unavailable', result)
        self.assertTrue(result['download_url'])
        self.assertEqual(self.count_conversations(), before)

    def renamed(self, name):
        data = draft()
        data['projects'][0]['name'] = name
        return data

    async def test_update_existing_draft_keeps_one_conversation(self):
        template = 't001-jianyue'
        async with self.client() as client:
            first = await self.call(client, 'huhua_resume_save', {'resume': draft(), 'template_id': template})
            cid, revision = first['conversation_id'], first['revision']
            count = self.count_conversations()
            got = await self.call(client, 'huhua_resume_get', {'conversation_id': cid})
            self.assertEqual(got['revision'], revision)
            second = await self.call(client, 'huhua_resume_save', {
                'resume': self.renamed('第二版项目'), 'template_id': template,
                'conversation_id': cid, 'base_revision': revision})
            self.assertEqual(second['conversation_id'], cid)
            self.assertNotEqual(second['revision'], revision)
            self.assertNotEqual(second['version_id'], first['version_id'])
            self.assertEqual(self.count_conversations(), count)
            got = await self.call(client, 'huhua_resume_get', {'conversation_id': cid})
            self.assertEqual(got['untrusted_text']['resume']['projects'][0]['name'], '第二版项目')
            self.assertEqual(got['revision'], second['revision'])
            exported = await self.call(client, 'huhua_resume_export', {
                'resume': self.renamed('第三版项目'), 'template_id': template,
                'conversation_id': cid, 'base_revision': second['revision']})
            self.assertEqual((exported['conversation_id'], self.count_conversations()), (cid, count))
            self.assertNotEqual(exported['revision'], second['revision'])
            self.assertTrue((await self.web.get(exported['download_url'])).content.startswith(b'%PDF-'))
            got = await self.call(client, 'huhua_resume_get', {'conversation_id': cid})
            self.assertEqual(got['untrusted_text']['resume']['projects'][0]['name'], '第三版项目')
            # conversation_id only still exports the stored version without writing.
            only = await self.call(client, 'huhua_resume_export', {'conversation_id': cid, 'template_id': template})
            self.assertEqual(only['revision'], exported['revision'])
            # Without conversation_id a new draft is created, as before.
            other = await self.call(client, 'huhua_resume_save', {'resume': draft(), 'template_id': template})
            self.assertNotEqual(other['conversation_id'], cid)
            self.assertEqual(self.count_conversations(), count + 1)

    async def test_stale_base_revision_is_refused_without_writing_or_download(self):
        template = 't001-jianyue'
        async with self.client() as client:
            first = await self.call(client, 'huhua_resume_save', {'resume': draft(), 'template_id': template})
            cid = first['conversation_id']
            current = (await self.web.get('/api/resume/current', params={'session_id': cid})).json()
            edited = current['data']
            edited['projects'][0]['name'] = '用户手改'
            put = await self.web.put('/api/resume/current', json={
                'session_id': cid, 'expected_revision': current['revision'], 'resume_data': edited})
            self.assertEqual(put.status_code, 200, put.text)
            issued = len(self.downloads.entries)
            for tool, extra in (('huhua_resume_save', {}), ('huhua_resume_export', {'format': 'pdf'})):
                result = await self.call(client, tool, {
                    'resume': self.renamed('助手旧稿'), 'template_id': template, 'conversation_id': cid,
                    'base_revision': first['revision'], **extra}, error=True)
                self.assertEqual(result.structured_content['error'], 'draft_changed_reload', tool)
                self.assertIn('huhua_resume_get', result.structured_content['next_step'])
            self.assertEqual(len(self.downloads.entries), issued)
            got = await self.call(client, 'huhua_resume_get', {'conversation_id': cid})
            self.assertEqual(got['untrusted_text']['resume']['projects'][0]['name'], '用户手改')
            missing = await self.call(client, 'huhua_resume_save', {
                'resume': draft(), 'template_id': template, 'conversation_id': cid}, error=True)
            self.assertEqual(missing.structured_content['error'], 'base_revision_required')
            # Reading the latest revision lets the assistant continue.
            latest = got['untrusted_text']['resume']
            latest['projects'][0]['name'] = '基于最新'
            ok = await self.call(client, 'huhua_resume_save', {
                'resume': latest, 'template_id': template,
                'conversation_id': cid, 'base_revision': got['revision']})
            self.assertEqual(ok['conversation_id'], cid)

    async def test_update_rejects_foreign_and_non_mcp_sessions(self):
        from app.services.conversation_store import create_conversation
        from app.services.session_store import save_resume_session
        mine = create_conversation('account:a')['session_id']
        save_resume_session(mine, draft() | {'basic_info': {'name': 'x'}}, stage='EDITING', resume_meta={'source': 'writer'})
        theirs = create_conversation('account:b')['session_id']
        save_resume_session(theirs, draft(), stage='EDITING', resume_meta={'source': 'mcp'})
        before = self.count_conversations()
        async with self.client() as client:
            for tool in ('huhua_resume_save', 'huhua_resume_export'):
                args = {'resume': draft(), 'template_id': 't001-jianyue', 'base_revision': 'a' * 64}
                foreign = await self.call(client, tool, {**args, 'conversation_id': theirs}, error=True)
                self.assertIn('404', str(foreign))
                web = await self.call(client, tool, {**args, 'conversation_id': mine}, error=True)
                self.assertEqual(web.structured_content['error'], 'draft_not_mcp')
                missing = await self.call(client, tool, {**args, 'conversation_id': 'nope'}, error=True)
                self.assertIn('404', str(missing))
        self.assertEqual(self.count_conversations(), before)

    async def test_instructions_tell_assistant_to_share_edit_url(self):
        for text in ('edit_url', '点进去直接改', 'huhua_resume_get(conversation_id)', '不要拿旧稿覆盖'):
            self.assertIn(text, self.server.instructions)

    async def test_all_seven_preview_tools_and_resources_complete_without_extra_scopes(self):
        template_preview.cache_clear()
        for row in templates_list()['templates']:
            with self.subTest(template=row['id']):
                pat = self.tokens.create('a', '预览回归', [])
                async with self.client(pat) as client:
                    result = await client.call_tool('huhua_resume_preview', {'resume': draft(), 'template_id': row['id']})
                    self.assertFalse(result.is_error, result.content)
                    self.assertEqual(result.structured_content['pages'], 1)
                    self.assertTrue(any(part.type == 'image' for part in result.content))
                    resource = await client.read_resource(row['preview_uri'])
                    self.assertEqual(resource.contents[0].mime_type, 'image/png')
                    self.assertTrue(resource.contents[0].blob)

    async def test_empty_contacts_share_measure_and_preview_placeholders(self):
        self.add(category='basic', subject='基本信息', field='phone', value='13800001234')
        self.add(category='basic', subject='基本信息', field='email', value='hidden@example.test')
        pat = self.tokens.create('a', '无联系方式权限', [])
        data = draft()
        data['basic_info'].update(phone='', email='')
        before = deepcopy(data)
        from app.services.resume_capacity import measure_rendered_pages
        async with self.client(pat) as client:
            with patch('app.services.mcp_service.measure_rendered_pages', wraps=measure_rendered_pages) as measure:
                result = await self.call(client, 'huhua_resume_measure', {'resume': data, 'template_id': 't001-jianyue'})
                measured = measure.call_args.args[0]
            with patch('app.services.mcp_service.render_preview', wraps=mcp_preview.render_preview) as render:
                preview = await client.call_tool('huhua_resume_preview', {'resume': data, 'template_id': 't001-jianyue'})
                self.assertFalse(preview.is_error, preview.content)
                rendered = render.call_args.args[1]
        for name, value in CONTACT_PLACEHOLDERS.items():
            self.assertEqual(measured['basic_info'][name], value)
            self.assertEqual(rendered['basic_info'][name], value)
        self.assertEqual(result['pages'], preview.structured_content['pages'])
        self.assertEqual(data, before)
        for private in ('13800001234', 'hidden@example.test'):
            self.assertNotIn(private, json.dumps([measured, rendered, result, preview.structured_content]))

    async def test_timeout_has_bounded_fallback_and_safe_audit(self):
        async with self.client() as client:
            with patch('app.services.mcp_service.render_preview', side_effect=mcp_preview.PreviewTimeout('private-detail')):
                result = await self.call(client, 'huhua_resume_preview',
                                         {'resume': draft(), 'template_id': 't1002-jianyue'}, error=True)
                self.assertEqual(result.structured_content['error'], 'preview_timeout')
                self.assertIn('gallery_url', result.structured_content['next_step'])
                self.assertNotIn('private-detail', str(result))
                template_preview.cache_clear()
                with self.assertRaises(Exception) as error:
                    await client.read_resource('huhua://templates/t1002-jianyue/preview.png')
                self.assertIn('504', str(error.exception))
                self.assertNotIn('private-detail', str(error.exception))
            result = await client.call_tool('huhua_resume_preview', {'resume': draft(), 'template_id': 't1002-jianyue'})
            self.assertFalse(result.is_error)

    async def test_custom_sections_warn_on_save_export_without_rewriting(self):
        data = draft()
        data['sections'] = [{'id': 'p', 'kind': 'projects', 'title': '自定专题', 'content': ''},
                            {'id': 'c', 'kind': 'custom', 'title': '补充探索', 'content': '尚在验证想法。'}]
        before = deepcopy(data)
        async with self.client() as client:
            saved = await self.call(client, 'huhua_resume_save', {'resume': data})
            warnings = saved['section_diagnostics']
            self.assertEqual([row['code'] for row in warnings],
                             ['nonstandard_section_title', 'nonstandard_section_title', 'custom_section_review'])
            self.assertTrue(all(row['severity'] == 'advisory' for row in warnings))
            stored = await self.call(client, 'huhua_resume_get', {'conversation_id': saved['conversation_id']})
            self.assertEqual(stored['untrusted_text']['resume']['sections'], data['sections'])
            self.assertTrue(any('自定义栏目' in note for note in stored['untrusted_text']['resume']['verification_notes']))
            for format, target, content in [('pdf', 'render_resume_pdf', b'%PDF-test'),
                                            ('docx', 'resume_data_to_docx', b'PKtest')]:
                with patch('app.services.mcp_service.' + target, return_value=content) as render:
                    result = await self.call(client, 'huhua_resume_export',
                                             {'resume': data, 'template_id': 't001-jianyue', 'format': format})
                    rendered = render.call_args.args[-1]
                    self.assertEqual(rendered['sections'], data['sections'])
                    self.assertEqual(result['section_diagnostics'], warnings)
        self.assertEqual(data, before)


class MCPBatch17LocalTests(unittest.TestCase):
    def test_timeout_kills_child_and_releases_slot(self):
        real_run, real_popen = subprocess.run, subprocess.Popen
        children = []
        def track(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child
        def stalled(*args, **kwargs):
            return real_run([sys.executable, '-c', 'import time; time.sleep(60)'],
                            capture_output=True, timeout=0.1)
        with patch.object(mcp_preview.subprocess, 'Popen', side_effect=track), \
                patch.object(mcp_preview.subprocess, 'run', side_effect=stalled):
            with self.assertRaisesRegex(TimeoutError, 'preview_timeout'):
                mcp_preview.render_preview('t1002-jianyue', draft())
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        with self.assertRaises(ProcessLookupError):
            os.kill(children[0].pid, 0)
        png, pages = mcp_preview.render_preview('t1002-jianyue', draft())
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertEqual(pages, 1)

    def test_preview_concurrency_is_bounded_and_stderr_stays_private(self):
        from fastapi import HTTPException
        for _ in range(2):
            self.assertTrue(mcp_preview._slots.acquire(blocking=False))
        try:
            with patch.object(mcp_preview.subprocess, 'run') as run:
                with self.assertRaises(HTTPException) as error:
                    mcp_preview.render_preview('t1002-jianyue', draft())
                self.assertEqual(error.exception.status_code, 503)
                run.assert_not_called()
        finally:
            for _ in range(2):
                mcp_preview._slots.release()
        with patch.object(mcp_preview.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, b'', b'private-data')):
            with self.assertRaisesRegex(RuntimeError, '^preview_unavailable$'):
                mcp_preview.render_preview('t1002-jianyue', draft())

    def test_placeholders_reserve_at_least_typical_contact_layout_for_every_template(self):
        data = MCPResume.model_validate(draft()).model_dump()
        data['basic_info'].update(phone='+86 13800001234', email='candidate.portfolio@example.test', location='深圳')
        before = deepcopy(data)
        for row in templates_list()['templates']:
            with self.subTest(template=row['id']):
                actual = measure_resume_pdf_layout(row['id'], data, 1)
                placeholder = measure_resume_pdf_layout(row['id'], layout_contacts(data), 1)
                self.assertGreaterEqual(placeholder['pages'], actual['pages'])
                self.assertGreaterEqual(placeholder['last_page_content_height_px'], actual['last_page_content_height_px'])
        self.assertEqual(data, before)

    def test_missing_fields_describes_all_empty_fields_for_guest_and_empty_profile(self):
        for state in ({}, {'intake_account': True, 'intake_profile': {}}):
            guidance = intake_guidance(state)
            self.assertEqual(guidance['title'], '基本信息')
            self.assertEqual(set(guidance['missing_fields']), set(basics_values({})))
            self.assertFalse(any(guidance['values'].values()))

    def test_standard_and_legacy_section_diagnostics_are_non_mutating(self):
        from app.mcp.diagnostics import section_diagnostics
        self.assertEqual(section_diagnostics({'sections': [
            {'id': str(index), 'kind': 'projects', 'title': title} for index, title in enumerate(STANDARD_SECTIONS)]}), [])
        data = {'experience_section_title': '自定栏目', 'projects': [{'name': '保留'}]}
        before = deepcopy(data)
        self.assertEqual(section_diagnostics(data)[0]['path'], '/experience_section_title')
        self.assertEqual(data, before)
        self.assertEqual(section_diagnostics({}), [])

    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_editor_prompts_login_for_unreadable_linked_session(self):
        script = os.path.join(os.path.dirname(__file__), 'resume_login_needed.dom.js')
        result = subprocess.run(['node', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
