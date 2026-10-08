"""Disposable encrypted UI app with synthetic web/model responses, no providers.

Run: .venv/bin/python tests/research_live_server.py --port 8898
Use https://careers.example.org/backend for success, /long for truncated text,
or /unavailable for a fallback.
"""
import argparse
import asyncio
from langchain_core.messages import AIMessageChunk

from product_live_server import run


def setup(main, *, search_enabled=True):
    from app.agents import resume_graph
    from app.api import chat
    from app.services import web_research

    class FixtureLLM:
        model_name = "web-research-ui-fixture"

        async def astream(self, messages):
            reply = "公开资料提到 Python 接口开发和测试要求 [1]。目前本次对话还没有你的项目细节，不能据此认定你掌握了这些能力。\n\n**我的建议**\n先选一个你真实参与的项目，说清具体做了什么；岗位要求作为对照，不直接写进个人经历。"
            for piece in [reply[:22], reply[22:70], reply[70:]]:
                yield AIMessageChunk(content=piece)
                await asyncio.sleep(.1)

    async def read_url(url):
        await asyncio.sleep(.2)
        if url.endswith("/unavailable"):
            raise web_research.WebResearchError("该网页需要登录，请粘贴 JD 正文或上传岗位截图。", 422)
        if url not in {"https://careers.example.org/backend", "https://careers.example.org/long"}:
            raise web_research.WebResearchError("本地验收仅接受预设的虚构公开链接。", 422)
        return {"title":"示例科技 · Python 后端实习（虚构验收）", "url":url,
                "fetched_at":"2026-10-06T08:00:00+00:00", "published_at":"2026-10-01",
                "kind":"job_page", "content_truncated":url.endswith("/long"),
                "content":("岗位职责：参与 Python API 开发，编写接口测试，整理技术文档。要求了解 HTTP 和数据库；个人或课程项目均可说明贡献。此页面仅用于本地功能验收。" * (180 if url.endswith("/long") else 1))[:12000]}

    async def search(company, role):
        await asyncio.sleep(.2)
        return [{"title":f"{company} · {role}（虚构公开资料）", "url":"https://careers.example.org/backend",
                 "fetched_at":"2026-10-06T08:05:00+00:00", "kind":"search_result",
                 "content":"公开页面摘要提到 Python、接口开发和测试；不能代表候选人已掌握这些技能，也不能推断实际工作待遇。"}]

    async def read_public(url):
        await asyncio.sleep(.2)
        if url != "https://github.com/example-user":
            raise web_research.WebResearchError("本地验收只允许虚构的 example-user 主页。", 422)
        return {"title":"GitHub 公开主页：example-user（虚构验收）", "url":url,
                "fetched_at":"2026-10-06T08:00:00+00:00", "kind":"public_page",
                "read_scope":"github_profile_and_public_repositories", "request_count":2, "content_truncated":False,
                "content":"仅获取公开元数据。example-user/mirror-tool：12 Stars、2 Forks。未读取代码，不证明候选人贡献。"}

    async def decode(text, llm):
        return ({"job_title":"Python 后端实习", "company":"示例科技", "required_skills":["Python","HTTP","数据库"],
                 "responsibilities":["API 开发","接口测试","整理技术文档"]},
                "已读取招聘链接，岗位材料和来源已放在右侧 JD 页。这个岗位重点看接口开发与测试；接下来可以说说你实际参与过的项目。")

    main.get_settings().TAVILY_API_KEY = "fixture-only-never-sent" if search_enabled else ""
    chat._get_llm = lambda: FixtureLLM()
    web_research.read_job_url = read_url
    web_research.read_public_url = read_public
    web_research.search_job_context = search
    resume_graph._run_decoder_and_build_reply = decode


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8898)
    parser.add_argument("--search-disabled", action="store_true")
    args = parser.parse_args()
    run(args.port, setup_fixture=lambda main: setup(main, search_enabled=not args.search_disabled))
