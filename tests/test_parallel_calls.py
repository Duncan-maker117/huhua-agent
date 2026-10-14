"""Parallelised model calls: they overlap, and the result equals the serial order.

A "serial reference" run swaps the speculative scope for one that starts each call
only where the consumer awaits it, which is exactly the original sequential flow.
Only local doubles with asyncio.sleep are used; no endpoint is contacted.
"""

import asyncio
import re
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app.agents import resume_graph as rg  # noqa: E402
from app.agents import resume_writer as rw  # noqa: E402
from app.agents.router import route_intents, start_route_call  # noqa: E402
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402
from app.services.speculative import SpeculativeScope  # noqa: E402

DELAY = 0.2


class _Lazy:
    """Runs its coroutine only when awaited: the original sequential order."""

    def __init__(self, coroutine):
        self.coroutine = coroutine
        self.started = False

    def __await__(self):
        self.started = True
        return self.coroutine.__await__()

    def done(self):
        return False

    def cancel(self):
        if not self.started:
            self.coroutine.close()


class LazyScope:
    def __init__(self):
        self.started = []

    def start(self, awaitable):
        self.started.append(_Lazy(awaitable))
        return self.started[-1]

    def adopt(self, task):
        return task

    async def aclose(self):
        for lazy in self.started:
            lazy.cancel()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        await self.aclose()


def serial(module):
    return mock.patch.object(module, "SpeculativeScope", LazyScope)


class SpeculativeScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_exit_cancels_unfinished_and_retrieves_errors(self):
        cancelled = asyncio.Event()

        async def slow():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def failing():
            raise RuntimeError("late failure")

        async with SpeculativeScope() as scope:
            scope.start(slow())
            failed = scope.start(failing())
            await asyncio.sleep(0.01)
            self.assertTrue(failed.done())
        self.assertTrue(cancelled.is_set())
        self.assertEqual(asyncio.all_tasks() - {asyncio.current_task()}, set())
        self.assertIsInstance(failed.exception(), RuntimeError)

    async def test_awaited_result_is_returned_and_error_propagates(self):
        async def value():
            await asyncio.sleep(0.01)
            return 7

        async def boom():
            raise ValueError("x")

        async with SpeculativeScope() as scope:
            self.assertEqual(await scope.start(value()), 7)
            with self.assertRaises(ValueError):
                await scope.start(boom())


def same(left, right):
    """Equality that ignores freshly generated uuid item ids."""
    pattern = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|f_[0-9a-f]{32}")
    return pattern.sub("ID", repr(left)) == pattern.sub("ID", repr(right))


def collecting_state(text="我做了一个反馈整理小程序，负责需求分析。"):
    return {"messages": [HumanMessage(content=text, id="m1")], "stage": "COLLECTING",
            "collected_info": rg._empty_collected_info(), "resume_data": {}}


class CollectingParallelTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []
        self.decision = TriageDecision(action=TriageAction.ASK_EXPERIENCE, reason="t")
        patches = [
            mock.patch.object(rg, "_make_non_streaming_llm", lambda llm, temperature=None: llm),
            mock.patch.object(rg, "run_triage", self.triage),
            mock.patch.object(rg, "_extract_info_from_message", self.extract),
            mock.patch.object(rg, "stream_public_reply", self.reply),
            mock.patch.object(rg, "_run_decoder_and_build_reply", self.decode),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.extract_error = None
        self.extract_cancelled = False

    async def triage(self, **kwargs):
        self.events.append(("triage_start", time.monotonic()))
        await asyncio.sleep(DELAY)
        return self.decision

    async def extract(self, message, current, llm):
        self.events.append(("extract_start", time.monotonic()))
        try:
            await asyncio.sleep(DELAY)
        except asyncio.CancelledError:
            self.extract_cancelled = True
            raise
        if self.extract_error:
            raise self.extract_error
        result = dict(current)
        result["extracted"] = message
        return result

    async def reply(self, llm, messages, **kwargs):
        return AIMessage(content="reply", id="r1")

    async def decode(self, text, llm):
        return {"job_title": "x", "role_profile": {}}, "decoded"

    async def run_node(self, state=None):
        return await rg._collecting_turn_node(state or collecting_state(), object())

    async def test_triage_and_extraction_overlap_with_serial_equal_result(self):
        started = time.monotonic()
        parallel = await self.run_node()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, DELAY * 1.7)
        starts = {name: at for name, at in self.events}
        self.assertLess(abs(starts["triage_start"] - starts["extract_start"]), 0.05)
        with serial(rg):
            reference = await self.run_node()
        self.assertTrue(same(parallel["collected_info"], reference["collected_info"]))
        self.assertIn("extracted", parallel["collected_info"])
        self.assertEqual(parallel["dig_attempts"], reference["dig_attempts"])
        self.assertEqual([m.content for m in parallel["messages"]][:1], ["reply"])

    async def test_decode_jd_discards_speculative_extraction(self):
        self.decision = TriageDecision(action=TriageAction.DECODE_JD, reason="jd")
        current = collecting_state('招聘产品实习生，负责需求分析与跨团队合作。')
        result = await self.run_node(current)
        self.assertTrue(self.extract_cancelled)
        self.assertNotIn("extracted", result["collected_info"])
        with serial(rg):
            reference = await self.run_node(current)
        self.assertTrue(same(result["collected_info"], reference["collected_info"]))
        self.assertEqual(result["jd_info"], reference["jd_info"])
        self.assertEqual(asyncio.all_tasks() - {asyncio.current_task()}, set())

    async def test_extraction_failure_propagates_like_serial_and_leaves_no_task(self):
        self.extract_error = RuntimeError("extract failed")
        with self.assertRaises(RuntimeError):
            await self.run_node()
        with serial(rg), self.assertRaises(RuntimeError):
            await self.run_node()
        self.assertEqual(asyncio.all_tasks() - {asyncio.current_task()}, set())

    async def test_triage_failure_cancels_speculative_extraction(self):
        async def broken(**kwargs):
            await asyncio.sleep(DELAY / 4)
            raise RuntimeError("triage failed")
        with mock.patch.object(rg, "run_triage", broken), self.assertRaises(RuntimeError):
            await self.run_node()
        self.assertTrue(self.extract_cancelled)
        self.assertEqual(asyncio.all_tasks() - {asyncio.current_task()}, set())

    async def test_rewrite_task_keeps_original_flow(self):
        state = {**collecting_state(), "requested_task": "rewrite_experience"}
        result = await self.run_node(state)
        self.assertEqual([name for name, _ in self.events], ["extract_start"])
        self.assertIn("extracted", result["collected_info"])


class FakeStructured:
    """Stateless structured double; records when each schema call starts and ends."""

    def __init__(self, responses, delays=None):
        self.responses = responses
        self.delays = delays or {}
        self.spans = []

    def with_structured_output(self, schema):
        owner = self

        class Bound:
            async def ainvoke(self, messages):
                name = schema.__name__
                begin = time.monotonic()
                await asyncio.sleep(owner.delays.get(name, DELAY))
                owner.spans.append((name, begin, time.monotonic()))
                response = owner.responses[name]
                if isinstance(response, Exception):
                    raise response
                return response
        return Bound()


ROUTE = {"intents": ["edit"], "edit": {"scope": "whole", "targets": [], "instruction": ""},
         "edit_plan": [{"op": "rewrite", "target": "whole", "args": {}}], "reason": "r"}
ROUTE_STATE = {"messages": [HumanMessage(content="把项目写详细点")], "resume_data": {
    "projects": [{"item_id": "p1", "name": "项目", "polished_bullets": ["做了原型"]}]},
    "collected_info": {}}


class RouterPrefetchTest(unittest.IsolatedAsyncioTestCase):
    async def test_prefetched_equals_direct_call(self):
        model = FakeStructured({"RouteSchema": ROUTE})
        direct = await route_intents("把项目写详细点", ROUTE_STATE, model)
        task = start_route_call("把项目写详细点", ROUTE_STATE, model)
        prefetched = await route_intents("把项目写详细点", ROUTE_STATE, model, prefetched=task)
        self.assertEqual(direct, prefetched)
        self.assertEqual(len(model.spans), 2)

    async def test_prefetched_failure_falls_back_like_direct_failure(self):
        model = FakeStructured({"RouteSchema": RuntimeError("down")})
        direct = await route_intents("把项目写详细点", ROUTE_STATE, model)
        task = start_route_call("把项目写详细点", ROUTE_STATE, model)
        prefetched = await route_intents("把项目写详细点", ROUTE_STATE, model, prefetched=task)
        self.assertEqual(direct, prefetched)
        self.assertEqual(direct["fallback_reason"], "router_unavailable")


class EditRoundParallelTest(unittest.IsolatedAsyncioTestCase):
    """Extraction (new fact in an edit) overlaps the router; plan and writer stay ordered."""

    def setUp(self):
        self.spans = {}
        self.router = FakeStructured({"RouteSchema": ROUTE}, {"RouteSchema": DELAY})
        text = "把项目写详细点，另外我还做过一个抖音推广，负责投放。"
        self.state = {
            "messages": [HumanMessage(content=text, id="m2")], "stage": "EVALUATING",
            "resume_data": {"projects": [{"item_id": "p1", "name": "项目", "polished_bullets": ["做了原型"]}]},
            "collected_info": rg._empty_collected_info(),
        }
        for patch in (
            mock.patch.object(rg, "_router_model", lambda llm: self.router),
            mock.patch.object(rg, "_extract_info_from_message", self.extract),
            mock.patch.object(rg, "_write_resume_update", self.write),
            mock.patch.object(rg, "_generation_contains_facts", lambda *args, **kwargs: True),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.written_with = None

    async def extract(self, message, current, llm):
        begin = time.monotonic()
        await asyncio.sleep(DELAY)
        self.spans["extract"] = (begin, time.monotonic())
        result = dict(current)
        result["marker"] = "extracted"
        return result

    async def write(self, state, llm, *, scope="whole", targets=()):
        self.spans["write"] = (time.monotonic(), None)
        self.written_with = (state["collected_info"].get("marker"), scope)
        data = state["resume_data"] or {"projects": []}
        return {"resume_data": data, "resume_meta": {}, "collected_info": state["collected_info"]}

    async def run_node(self):
        self.router.spans.clear()
        return await rg._evaluating_turn_node(self.state, object())

    async def test_router_overlaps_extraction_and_writer_waits_for_both(self):
        started = time.monotonic()
        parallel = await self.run_node()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, DELAY * 1.7)
        route_begin = self.router.spans[0][1]
        extract_begin, extract_end = self.spans["extract"]
        self.assertLess(abs(route_begin - extract_begin), 0.05)
        self.assertGreaterEqual(self.spans["write"][0], extract_end)
        self.assertGreaterEqual(self.spans["write"][0], self.router.spans[0][2])
        self.assertEqual(self.written_with, ("extracted", "whole"))
        with serial(rg):
            reference = await self.run_node()
        self.assertEqual(self.written_with, ("extracted", "whole"))
        self.assertEqual(parallel["messages"][0].content, reference["messages"][0].content)
        self.assertTrue(same(parallel["collected_info"], reference["collected_info"]))
        self.assertEqual(parallel["resume_data"], reference["resume_data"])
        self.assertEqual(asyncio.all_tasks() - {asyncio.current_task()}, set())

    async def test_router_failure_uses_same_fallback_as_serial(self):
        self.router.responses["RouteSchema"] = RuntimeError("router down")
        parallel = await self.run_node()
        with serial(rg):
            reference = await self.run_node()
        self.assertEqual(parallel["messages"][0].content, reference["messages"][0].content)
        self.assertTrue(same(parallel["collected_info"], reference["collected_info"]))

    async def test_extraction_error_cancels_router_without_leftovers(self):
        async def broken(message, current, llm):
            raise RuntimeError("extract exploded")
        with mock.patch.object(rg, "_extract_info_from_message", broken), self.assertRaises(RuntimeError):
            await self.run_node()
        self.assertEqual(asyncio.all_tasks() - {asyncio.current_task()}, set())


def writer_fixtures():
    from test_resume_writer import ROLE, draft, item, plan, source
    return source(), ROLE, draft, item, plan


class WriterSummaryParallelTest(unittest.IsolatedAsyncioTestCase):
    def build(self, summary_refs=("f3",), summary_text="整理并分类用户反馈"):
        src, role, draft, item, plan = writer_fixtures()
        semantic = {"decisions": [{"id": "b0", "subject_ok": True, "actions_supported": True,
                                   "objects_supported": True, "results_supported": True,
                                   "limits_kept": True, "unsupported_spans": [], "verdict": "pass"},
                                  {"id": "summary", "subject_ok": True, "actions_supported": True,
                                   "objects_supported": True, "results_supported": True,
                                   "limits_kept": True, "unsupported_spans": [], "verdict": "pass"}]}
        model = FakeStructured({
            "OnePassOutput": {"match_plan": plan({"p2": "lead"}), "writer": draft(
                [item("p2", "projects", [("分类整理用户反馈", ["f3"])])],
                summary=summary_text, summary_fact_ids=list(summary_refs))},
            "SemanticBatch": semantic,
        # Only guard latency is under test; source-echo polish has its own suite.
        }, {"OnePassOutput": 0.0, "SemanticBatch": DELAY, "RepairOutput": 0.0})
        return src, role, model

    async def test_summary_guard_overlaps_bullet_guard_with_identical_result(self):
        src, role, model = self.build()
        started = time.monotonic()
        parallel = await rw.run_resume_writer(src, role, model)
        elapsed = time.monotonic() - started
        guards = [span for span in model.spans if span[0] == "SemanticBatch"]
        self.assertEqual(len(guards), 2)
        self.assertLess(elapsed, DELAY * 1.6)
        self.assertLess(guards[0][1], guards[1][2])
        self.assertLess(guards[1][1], guards[0][2])
        src, role, model = self.build()
        with serial(rw):
            reference = await rw.run_resume_writer(src, role, model)
        guards = [span for span in model.spans if span[0] == "SemanticBatch"]
        self.assertGreaterEqual(guards[1][1], guards[0][2])
        self.assertEqual(parallel, reference)
        self.assertEqual(parallel["resume_data"]["summary"], "整理并分类用户反馈")

    async def test_summary_failure_closed_like_serial(self):
        src, role, model = self.build()
        model.responses["SemanticBatch"] = RuntimeError("guard down")
        parallel = await rw.run_resume_writer(src, role, model)
        src, role, model = self.build()
        model.responses["SemanticBatch"] = RuntimeError("guard down")
        with serial(rw):
            reference = await rw.run_resume_writer(src, role, model)
        self.assertEqual(parallel, reference)
        self.assertEqual(parallel["resume_data"]["self_evaluation"], "")

    async def test_no_summary_means_no_extra_call(self):
        src, role, model = self.build(summary_refs=(), summary_text="")
        await rw.run_resume_writer(src, role, model)
        self.assertEqual(sum(span[0] == "SemanticBatch" for span in model.spans), 1)

    async def test_bullet_stage_error_cancels_summary_guard(self):
        src, role, model = self.build()
        calls = []

        async def broken(*args, **kwargs):
            calls.append(1)
            await asyncio.sleep(0.01)
            raise RuntimeError("guard stage exploded")
        with mock.patch.object(rw, "_guard_and_repair", broken), self.assertRaises(RuntimeError):
            await rw.run_resume_writer(src, role, model)
        self.assertEqual(asyncio.all_tasks() - {asyncio.current_task()}, set())


if __name__ == "__main__":
    unittest.main()
