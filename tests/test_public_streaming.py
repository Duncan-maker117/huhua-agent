"""True public token streaming with an actual LangGraph and gated fake models."""

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.public_reply import (  # noqa: E402
    PUBLIC_REPLY_EVENT,
    PUBLIC_REPLY_INTERRUPTED,
    stream_public_reply,
)
from app.agents.career_tasks import run_resume_review  # noqa: E402
from app.agents.resume_graph import (  # noqa: E402
    _init_state,
    build_graph,
    stream_agent,
)


class GatedPublicModel:
    def __init__(self, *, failure=False, empty=False):
        self.release = asyncio.Event()
        self.closed = asyncio.Event()
        self.finished = False
        self.failure = failure
        self.empty = empty
        self.ainvoke = AsyncMock(return_value=AIMessage(content="PRIVATE_INTERNAL"))

    async def astream(self, _messages):
        try:
            yield AIMessageChunk(
                content=[{"type": "reasoning", "reasoning": "PRIVATE_REASONING"}],
                additional_kwargs={"reasoning_content": "PRIVATE_REASONING"},
            )
            if not self.empty:
                yield AIMessageChunk(content="第一段")
            await self.release.wait()
            if self.failure:
                raise RuntimeError("PRIVATE_PROVIDER_DIAGNOSTICS")
            if not self.empty:
                yield AIMessageChunk(content=[{"type": "text", "text": "第二段"}])
            self.finished = True
        finally:
            self.closed.set()


class PublicStreamingTest(unittest.IsolatedAsyncioTestCase):
    async def test_review_first_delta_arrives_before_completion_and_saves_full_reply(
        self,
    ):
        model = GatedPublicModel()
        graph = build_graph(model)
        with (
            patch("app.agents.resume_graph.get_graph", return_value=graph),
            patch("app.services.session_store.save_resume_session") as save,
        ):
            stream = stream_agent(
                [{"content": "检查简历：我只做过 Mock 演示。"}],
                "gated-review",
                model,
                task="review_resume",
            )
            first = await asyncio.wait_for(anext(stream), timeout=1)
            self.assertEqual(first, "第一段")
            self.assertFalse(model.finished)
            save.assert_not_called()
            model.release.set()
            chunks = [first] + [chunk async for chunk in stream]
            state = await graph.aget_state(
                {"configurable": {"thread_id": "gated-review"}}
            )
        reply = next(
            m for m in reversed(state.values["messages"]) if isinstance(m, AIMessage)
        )
        self.assertEqual("".join(chunks), reply.content)
        self.assertEqual("".join(chunks).count("第一段"), 1)
        self.assertIn("修改建议尚未写入简历", chunks[-1])
        self.assertNotIn("PRIVATE", "".join(chunks))
        self.assertTrue(model.closed.is_set())
        model.ainvoke.assert_not_called()
        self.assertEqual(state.values["requested_task"], "auto")
        self.assertEqual(state.values.get("collected_info", {}), {})
        save.assert_called_once()

    async def test_wrap_streams_prose_and_keeps_internal_extraction_private(self):
        model = GatedPublicModel()
        graph = build_graph(model)
        source = "我在测试项目参与调研，整理访谈笔记。"
        with (
            patch("app.agents.resume_graph.get_graph", return_value=graph),
            patch(
                "app.agents.resume_graph._make_non_streaming_llm", return_value=object()
            ),
            patch(
                "app.agents.resume_graph._extract_info_from_message",
                AsyncMock(return_value=_init_state()["collected_info"]),
            ),
            patch("app.services.session_store.save_resume_session") as save,
        ):
            stream = stream_agent(
                [{"content": source}], "gated-wrap", model, task="rewrite_experience"
            )
            first = await asyncio.wait_for(anext(stream), timeout=1)
            self.assertEqual(first, "第一段")
            self.assertFalse(model.finished)
            model.release.set()
            chunks = [first] + [chunk async for chunk in stream]
            state = await graph.aget_state(
                {"configurable": {"thread_id": "gated-wrap"}}
            )
        self.assertEqual(chunks, ["第一段", "第二段"])
        self.assertEqual(state.values["messages"][-1].content, "第一段第二段")
        self.assertEqual(
            state.values["collected_info"]["projects"][0]["description"], source
        )
        self.assertNotIn("第一段", str(state.values["collected_info"]))
        save.assert_called_once()

    async def test_custom_protocol_filters_internal_events_and_deduplicates_reply(self):
        def delta(node, reply_id, text):
            return {
                "type": PUBLIC_REPLY_EVENT,
                "node": node,
                "reply_id": reply_id,
                "content": text,
            }

        class Graph:
            async def astream(self, _input, *, config, stream_mode):
                assert stream_mode == ["custom", "updates"]
                yield "custom", delta("triage", "private", "PRIVATE_TRIAGE")
                yield "messages", (AIMessageChunk(content="PRIVATE_MODEL"), {})
                yield "custom", {"type": "internal", "content": "PRIVATE_JSON"}
                yield "custom", delta("collecting", "r1", "第一段")
                yield "custom", delta("collecting", "r1", "第二段")
                yield (
                    "updates",
                    {
                        "collecting": {
                            "messages": [AIMessage(content="第一段第二段", id="r1")]
                        },
                        "decoder": {"messages": [AIMessage(content="PRIVATE_DECODER")]},
                    },
                )
                yield "custom", delta("collecting", "r1", "STALE_DUPLICATE")
                yield (
                    "updates",
                    {
                        "evaluating": {
                            "messages": [AIMessage(content="安全检查结果", id="r2")]
                        }
                    },
                )

            async def aget_state(self, _config):
                return SimpleNamespace(
                    values={"resume_data": {"projects": [{"name": "A"}]}}
                )

        with (
            patch("app.agents.resume_graph.get_graph", return_value=Graph()),
            patch("app.services.session_store.save_resume_session"),
        ):
            chunks = [
                chunk
                async for chunk in stream_agent(
                    [{"content": "你好"}], "protocol", object()
                )
            ]
        self.assertEqual(chunks, ["第一段", "第二段", "安全检查结果"])

    async def test_partial_model_failure_marks_and_checkpoints_interrupted_reply(self):
        model = GatedPublicModel(failure=True)
        graph = build_graph(model)
        with (
            patch("app.agents.resume_graph.get_graph", return_value=graph),
            patch("app.services.session_store.save_resume_session") as save,
        ):
            stream = stream_agent(
                [{"content": "检查简历"}], "failed-review", model, task="review_resume"
            )
            first = await asyncio.wait_for(anext(stream), timeout=1)
            model.release.set()
            chunks = [first] + [chunk async for chunk in stream]
            state = await graph.aget_state(
                {"configurable": {"thread_id": "failed-review"}}
            )
        self.assertEqual(chunks, ["第一段", PUBLIC_REPLY_INTERRUPTED])
        self.assertNotIn("PRIVATE", "".join(chunks))
        reply = state.values["messages"][-1]
        self.assertEqual(reply.content, "".join(chunks))
        self.assertTrue(reply.additional_kwargs["public_reply_interrupted"])
        self.assertTrue(model.closed.is_set())
        save.assert_called_once()

    async def test_client_close_cancels_upstream_without_saving_incomplete_reply(self):
        model = GatedPublicModel()
        graph = build_graph(model)
        with (
            patch("app.agents.resume_graph.get_graph", return_value=graph),
            patch("app.services.session_store.save_resume_session") as save,
        ):
            stream = stream_agent(
                [{"content": "检查简历"}], "cancel-review", model, task="review_resume"
            )
            self.assertEqual(await asyncio.wait_for(anext(stream), timeout=1), "第一段")
            await stream.aclose()
            await asyncio.wait_for(model.closed.wait(), timeout=1)
            save.assert_not_called()
        self.assertFalse(model.finished)

    async def test_timeout_after_first_chunk_has_interruption_notice(self):
        model = GatedPublicModel()
        response = await stream_public_reply(
            model, [HumanMessage(content="检查")], timeout=0.01
        )
        self.assertEqual(response.content, "第一段" + PUBLIC_REPLY_INTERRUPTED)
        self.assertTrue(response.additional_kwargs["public_reply_interrupted"])
        self.assertTrue(model.closed.is_set())

    async def test_review_budget_falls_back_if_no_public_text_arrives(self):
        model = GatedPublicModel(empty=True)
        state = {"resume_data": {"basic_info": {"name": "徐同学"}}}
        with patch(
            "app.agents.career_tasks.get_settings",
            return_value=SimpleNamespace(LLM_REVIEW_TIMEOUT_SECONDS=0.01),
        ):
            response = await asyncio.wait_for(
                run_resume_review(state, "检查简历", model, return_message=True),
                timeout=1,
            )
        self.assertIn("专业内容检查暂时不可用", response.content)
        self.assertIn("补全至少一种联系方式", response.content)
        self.assertNotIn("PRIVATE", response.content)
        self.assertTrue(model.closed.is_set())
        model.ainvoke.assert_not_called()

    async def test_review_budget_retains_partial_public_text(self):
        model = GatedPublicModel()
        with patch(
            "app.agents.career_tasks.get_settings",
            return_value=SimpleNamespace(LLM_REVIEW_TIMEOUT_SECONDS=0.01),
        ):
            response = await asyncio.wait_for(
                run_resume_review({}, "检查简历", model, return_message=True),
                timeout=1,
            )
        self.assertEqual(response.content, "第一段" + PUBLIC_REPLY_INTERRUPTED)
        self.assertTrue(response.additional_kwargs["public_reply_interrupted"])
        self.assertNotIn("专业内容检查暂时不可用", response.content)
        self.assertTrue(model.closed.is_set())

    async def test_validated_draft_waits_for_writer_and_remains_one_canonical_reply(
        self,
    ):
        model = GatedPublicModel()
        graph = build_graph(model)
        editor_started = asyncio.Event()
        editor_release = asyncio.Event()
        draft = {"projects": [{"name": "A", "description": "整理访谈笔记"}]}

        async def build(_state, _model):
            editor_started.set()
            await editor_release.wait()
            return {"resume_data": draft, "resume_meta": {}, "resume_versions": [], "changed": True,
                    "change_summary": [], "page_check": {"status": "render_error"}, "resume_strategy": {}}

        config = {"configurable": {"thread_id": "safe-draft"}}
        await graph.aupdate_state(config, {**_init_state(), "stage": "BUILDING"})
        with (
            patch("app.agents.resume_graph.get_graph", return_value=graph),
            patch(
                "app.agents.resume_graph._write_resume_update",
                side_effect=build,
            ),
            patch("app.services.session_store.save_resume_session") as save,
        ):
            stream = stream_agent([{"content": "生成简历"}], "safe-draft", model)
            pending = asyncio.create_task(anext(stream))
            await asyncio.wait_for(editor_started.wait(), timeout=1)
            self.assertFalse(pending.done())
            editor_release.set()
            first = await asyncio.wait_for(pending, timeout=1)
            rest = [chunk async for chunk in stream]
            state = await graph.aget_state(config)
        self.assertIn("更新右侧待核对草稿", first)
        self.assertNotIn("整理访谈笔记", first)
        self.assertEqual(rest, [])
        self.assertEqual(state.values["resume_data"], draft)
        self.assertIn("整理访谈笔记", state.values["resume_draft"])
        self.assertNotEqual(state.values["resume_draft"], first)
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
