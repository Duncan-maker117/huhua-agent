"""Public landing page, local redirects and synthetic frontend interactions."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import Settings  # noqa: E402

# Import without reading local credentials or starting application workers.
with patch('app.config.get_settings', return_value=Settings(
        _env_file=None, DATABASE_URL='sqlite:///:memory:', ENABLE_RAG=False,
        LLM_API_KEY='', REQUIRE_ACCOUNT=False, ALLOW_INSECURE_LOCAL_STORAGE=True)):
    from main import app  # noqa: E402


class ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.resources = []
        self.links = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'script', 'img', 'source', 'iframe'}:
            for name in ('src', 'srcset'):
                if name in attrs:
                    self.resources.extend(part.strip().split()[0] for part in attrs[name].split(','))
        if tag == 'link' and 'href' in attrs:
            self.resources.append(attrs['href'])
        if tag == 'a' and 'id' in attrs:
            self.links[attrs['id']] = attrs.get('href')


class HomePageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                       base_url='http://testserver', follow_redirects=False)
        self.addAsyncCleanup(self.client.aclose)

    async def test_root_serves_home(self):
        response = await self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, (ROOT / 'web/home.html').read_text())
        self.assertIn('把聊过的经历，</span><span>写成一页真实的简历。', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-cache')

    async def test_chat_serves_workbench(self):
        response = await self.client.get('/chat')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, (ROOT / 'web/index.html').read_text())
        self.assertIn('id="chat-pane"', response.text)

    async def test_connect_serves_token_page(self):
        response = await self.client.get('/connect')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, (ROOT / 'web/connect.html').read_text())
        self.assertIn('id="token-form"', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-cache')
        parser = ResourceParser()
        parser.feed(response.text)
        for resource in parser.resources:
            with self.subTest(resource=resource):
                parsed = urlsplit(resource)
                self.assertFalse(parsed.scheme or parsed.netloc)
                self.assertEqual(parsed.query, 'v=20261020-1')
                self.assertEqual((await self.client.get(resource)).status_code, 200)

    async def test_legacy_session_redirect_preserves_raw_query(self):
        for query in ('session=x', 'session=', 'session=a%2Fb&panel=profile&x=a+b&x=%26'):
            with self.subTest(query=query):
                response = await self.client.get('/?' + query)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers['location'], '/chat?' + query)

    async def test_redirect_cannot_leave_this_site(self):
        for path in ('//evil.com', '//evil.com/?session=x', '/%2F%2Fevil.com?session=x',
                     '/?session=//evil.com&next=https://evil.com', '/?session=%0d%0aLocation:%20//evil.com'):
            with self.subTest(path=path):
                response = await self.client.get('http://testserver' + path)
                target = urlsplit(response.headers.get('location', ''))
                self.assertIn(target.netloc, ('', 'testserver'))
                if response.is_redirect:
                    self.assertEqual(target.path, '/chat')

    async def test_home_resources_are_local_versioned_and_available(self):
        parser = ResourceParser()
        parser.feed((ROOT / 'web/home.html').read_text())
        self.assertGreater(len(parser.resources), 20)
        for resource in parser.resources:
            with self.subTest(resource=resource):
                parsed = urlsplit(resource)
                self.assertFalse(parsed.scheme or parsed.netloc)
                self.assertTrue(parsed.path.startswith('/static/'))
                self.assertEqual(parsed.query, 'v=20261020-1')
                self.assertTrue((ROOT / 'web' / parsed.path.removeprefix('/static/')).is_file())
        self.assertNotIn('tailwind', (ROOT / 'web/home.html').read_text())
        response = await self.client.get('/static/home.css?v=20261020-1')
        self.assertEqual(response.status_code, 200)

    async def test_mcp_three_steps_and_copyable_tasks(self):
        html = (await self.client.get('/')).text
        card = html.split('<article id="mcp"', 1)[1].split('</section>', 1)[0]
        steps = card.split('<ol class="mcp-steps"', 1)[1].split('</ol>', 1)[0]
        self.assertEqual(steps.count('<li>'), 3)
        for label in ('登录后生成令牌', '复制接入命令', '在助手里直接说任务'):
            self.assertIn(label, steps)
        self.assertIn('href="/connect"', steps)
        self.assertIn('id="mcp-command"', steps)
        self.assertIn('接入后可以这样用', card)
        for key, title in (('tailor', '按 JD 改简历'), ('project', '把项目记进档案'), ('check', '检查简历依据')):
            self.assertIn(f'<h5>{title}</h5>', card)
            self.assertIn(f'id="mcp-task-{key}"', card)
            self.assertIn(f'id="copy-task-{key}" type="button"', card)
            self.assertIn(f'id="copy-task-{key}-status" class="copy-status" role="status" aria-live="polite"', card)
        for note in ('只用已确认档案事实，逐条带出处，先测页数再导出。',
                     '我的档案 → 信息确认', '逐条对照档案事实，标出没有出处的句子。',
                     '/mcp__huhua__tailor_resume_for_jd', '/mcp__huhua__log_project_to_profile'):
            self.assertIn(note, card)

    async def test_home_three_entries_and_preview_tabs(self):
        text = (await self.client.get('/')).text
        parser = ResourceParser()
        parser.feed(text)
        self.assertEqual(parser.links['nav-mcp'], '/connect')
        self.assertEqual(parser.links['nav-account-mobile'], '/chat?panel=profile')
        self.assertEqual(parser.links['nav-account'], '/chat?panel=profile')
        self.assertEqual(parser.links['nav-workspace'], '/chat')
        self.assertIn('data-auth-open>登录</a>', text)
        self.assertIn('role="tablist"', text)
        self.assertEqual(text.count('role="tab"'), 2)
        self.assertEqual(text.count('role="tabpanel"'), 2)
        for name in ('chat', 'editor'):
            self.assertIn(f'aria-controls="preview-panel-{name}"', text)
            self.assertIn(f'aria-labelledby="preview-tab-{name}"', text)
        self.assertIn('aria-selected="true" aria-controls="preview-panel-chat"', text)
        self.assertIn('tabindex="0" hidden>', text)
        for extension in ('webp', 'png'):
            response = await self.client.get('/static/home/chat-1440.' + extension)
            self.assertEqual(response.status_code, 200)
        self.assertIn('聊几句经历，右侧实时长出一页简历。图中内容为虚构样例。', text)

    async def test_resume_returns_to_chat(self):
        parser = ResourceParser()
        html = (await self.client.get('/resume')).text
        parser.feed(html)
        self.assertEqual(parser.links['back-to-chat'], '/chat')
        self.assertIn('<a class="header-brand" href="/">胡话简历</a>', html)


class HomeDomTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_home_auth_and_connect_controllers(self):
        # 全量入口通过 unittest 收集此类，再执行新增的 DOM 回归。
        for name in ('home_auth.dom.js', 'connect.dom.js'):
            with self.subTest(controller=name):
                result = subprocess.run(['node', str(Path(__file__).with_name(name))],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_home_copy_navigation_and_menu(self):
        result = subprocess.run(['node', str(Path(__file__).with_name('home.dom.js'))],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_chat_entry_panels_and_login_continuation(self):
        result = subprocess.run(['node', str(Path(__file__).with_name('home_entry.dom.js'))],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
