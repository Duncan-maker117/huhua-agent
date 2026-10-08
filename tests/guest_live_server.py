"""Disposable guest UI fixture: real auth/storage/export, synthetic model, no mail.

Run: .venv/bin/python tests/guest_live_server.py --port 8897
"""
import argparse
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from product_live_server import run


def setup(main):
    from app.agents.resume_graph import _init_state, get_graph
    from app.api import chat
    from app.services.session_store import save_resume_session
    from langchain_core.messages import AIMessage, HumanMessage

    async def synthetic_stream(messages, session_id, llm, **kwargs):
        data = json.loads((Path(__file__).resolve().parents[1] / "data/sample_resume.json").read_text())
        data = copy.deepcopy(data)
        data["basic_info"]["name"] = "游客体验测试"
        data["basic_info"]["email"] = "guest@huhua-fixture.invalid"
        graph = get_graph(llm)
        current = await graph.aget_state({"configurable": {"thread_id": session_id}})
        existing = (current.values or {}).get("messages", [])
        user = HumanMessage(content=messages[-1]["content"], id=f"guest-ui-human-{len(existing)}")
        reply = "已整理你的经历。右侧可以预览简历和切换模板；登录后能导出并长期保留本次对话。"
        await graph.aupdate_state({"configurable": {"thread_id": session_id}},
            {**_init_state(), "stage": "EVALUATING", "resume_data": data,
             "messages": [*existing, user, AIMessage(content=reply, id=f"guest-ui-ai-{len(existing)}")]}, as_node="building")
        save_resume_session(session_id, data, stage="EVALUATING", archive_event={
            "source_id": user.id, "event_type": "human_message", "payload": {"human_text": user.content}})
        for token in [reply[:12], reply[12:]]:
            yield token
            await asyncio.sleep(0.05)

    chat._get_llm = lambda: SimpleNamespace(model_name="guest-ui-fixture")
    chat.stream_agent = synthetic_stream


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8897)
    run(parser.parse_args().port, setup_fixture=setup)
