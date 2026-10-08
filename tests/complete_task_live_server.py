"""Disposable complete-input UI regression with a real graph and encrypted store.

The current writer runs its active-fact fallback with a non-model object. The
LLM client points to an unused loopback port; no provider credentials or external
model calls are possible. Chat routing, parsing, SSE, persistence and restore
are the production implementation. All input is synthetic.

Run: .venv/bin/python tests/complete_task_live_server.py --port 8901
"""

import argparse

from product_live_server import run


def setup(main):
    from langchain_openai import ChatOpenAI

    from app.agents import tailor_pipeline
    from app.agents.resume_writer import run_resume_writer
    from app.api import chat
    from test_candidate_material_chat import CHAT_MATERIAL

    audit = {"editor_calls": 0, "editor_input_counts": [], "writer_calls": 0,
             "external_model_allowed": False}

    async def bounded_writer(collected_info, role_profile, llm, **kwargs):
        # Retain the old audit keys for the frozen browser harness contract.
        audit["editor_calls"] += 1
        audit["writer_calls"] += 1
        audit["editor_input_counts"].append({
            key: len(collected_info.get(key) or [])
            for key in ("projects", "education", "skills", "certificates")
        })
        return await run_resume_writer(collected_info, role_profile, object(),
                                       **{**kwargs, "structured_llm": None})

    tailor_pipeline.run_resume_writer = bounded_writer
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
