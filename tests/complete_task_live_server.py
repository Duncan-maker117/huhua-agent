"""Disposable complete-input UI regression with a real graph and encrypted store.

Only the optional polishing result is replaced with an unchanged copy. The LLM
client points to an unused loopback port; no provider credentials or external
model calls are possible. Chat routing, parsing, SSE, persistence and restore
are the production implementation. All input is synthetic.

Run: .venv/bin/python tests/complete_task_live_server.py --port 8901
"""

import argparse
import copy

from product_live_server import run


def setup(main):
    from langchain_openai import ChatOpenAI

    from app.agents import editor_chain
    from app.api import chat
    from test_candidate_material_chat import CHAT_MATERIAL

    audit = {"editor_calls": 0, "editor_input_counts": [], "external_model_allowed": False}

    async def unchanged_editor(resume_data, llm):
        audit["editor_calls"] += 1
        audit["editor_input_counts"].append({
            key: len(resume_data.get(key) or [])
            for key in ("projects", "education", "skills", "certificates")
        })
        return copy.deepcopy(resume_data)

    editor_chain.run_editor = unchanged_editor
    chat._get_llm = lambda: ChatOpenAI(
        model="complete-task-local-fixture",
        api_key="unused-local-fixture-value",
        base_url="http://127.0.0.1:9/v1",
        temperature=0,
        timeout=0.2,
        max_retries=0,
    )

    @main.app.get("/__test__/complete-task-input")
    async def fixture_input():
        return {"synthetic": True, "text": CHAT_MATERIAL}

    @main.app.get("/__test__/complete-task-audit")
    async def fixture_audit():
        return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8901)
    run(parser.parse_args().port, setup_fixture=setup)
