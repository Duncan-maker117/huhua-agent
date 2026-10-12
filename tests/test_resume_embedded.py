"""Offline UI controllers and export routing; no live models or user stores."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.agents.resume_graph import export_node  # noqa: E402
from app.services.resume_workspace import build_workspace  # noqa: E402


class EmbeddedResumeTest(unittest.IsolatedAsyncioTestCase):
    def test_embedded_dom_controllers(self):
        result = subprocess.run(['node', str(ROOT / 'tests/resume_embedded.dom.js')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('embedded resume DOM checks passed', result.stdout)

    async def test_export_intent_projects_download_focus_without_mutating_draft(self):
        data = {'basic_info': {'name': '虚构测试'}, 'projects': [{'name': '虚构项目', 'description': '本地原型'}]}
        state = {'stage': 'EXPORT', 'resume_data': data, 'messages': [HumanMessage(content='导出当前版本')]}
        with patch('app.agents.resume_graph.evaluating_node', AsyncMock()) as evaluate:
            result = await export_node(state, object())
        evaluate.assert_not_awaited()
        reply = result['messages'][0].content
        self.assertIn('右侧「写简历」', reply)
        self.assertIn('「下载 PDF」或「下载 Word」', reply)
        self.assertNotIn('/resume', reply)
        self.assertNotIn('导出标签', reply)
        view = build_workspace({**state, 'messages': state['messages'] + result['messages']}, data)
        self.assertEqual(view['focus'], 'resume')
        self.assertTrue(view['focus_download'])
        self.assertNotIn('resume_data', result)

    def test_non_export_focus_does_not_request_download(self):
        view = build_workspace({'stage': 'COLLECTING'}, {})
        self.assertFalse(view['focus_download'])
