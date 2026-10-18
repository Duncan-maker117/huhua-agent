"""P1c replay instrumentation/check regressions; no listening ports or models."""
import asyncio
from copy import deepcopy
from importlib import import_module
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from persona_support import runner, report

loop = import_module("evaluation.persona-ux.loop_checks")
server = import_module("evaluation.persona-ux.serve")


def metrics(mode="loop"):
    return dict(model_calls=2, privacy_blocks=0, server_seconds=1.5, stream_seconds=1.6,
                elapsed_seconds=1.7, metrics_agent_mode=mode, model_call_scope=loop.CALL_SCOPE)


def new_turns(persona):
    if persona == "cold":
        item = {"name": "校园读书社", "role": "志愿者", "start_date": "2026-03", "end_date": "2026-04",
                "bullets": ["用 Excel 登记核对28条借阅记录，整理2张汇总表交给社长。"]}
        section, phone, email = "campus", "13900002017", "cold.person@example.invalid"
    else:
        item = {"name": "预约系统课程测试", "role": "小组测试成员", "start_date": "2026-03", "end_date": "2026-05",
                "bullets": ["用 Python 编写16条测试用例，在本地环境执行，记录5个问题并提交问题清单。"]}
        section, phone, email = "projects", "13900002018", "upload.person@example.invalid"
    identity = ("程岚", "明溪学院", "信息管理") if persona == "cold" else ("叶清", "柳岸学院", "软件工程")
    data = {section: [item], "basic_info": {"name": identity[0], "phone": phone, "email": email},
            "education": [{"school": identity[1], "major": identity[2], "degree": "本科"}]}
    turns = []
    for number, (action, text) in enumerate(list(loop.FIXTURES[persona].items())[1:], 1):
        ready = persona == "upload" or number >= 3
        turns.append({"action": action, "kind": "fixture", "input": text, "reply": "已按原始材料处理。",
                      "status": "ok", "sse_done": True, "resume_data": deepcopy(data) if ready else {},
                      "workspace": {}, "has_data": ready, "revision": "r1" if ready else None,
                      "stage": "EVALUATING" if ready else "COLLECTING", **metrics()})
    if persona == "cold":
        turns[2]["reply"] = "请补充姓名、手机和邮箱。"
        turns[2]["resume_data"]["basic_info"] = {}
    return turns


def indexed(persona, turns):
    return {r["id"].removeprefix(persona + "."): r["status"] for r in
            loop.evaluate_persona(persona, turns) + loop.evaluate_loop(persona, turns)}


class LoopChecksTests(unittest.TestCase):
    def test_new_personas_good_canonical_data_and_no_vacuous_pass(self):
        for persona in loop.FIXTURES:
            results = indexed(persona, new_turns(persona))
            self.assertTrue(all(v == "pass" for v in results.values()), results)
            empty = indexed(persona, [])
            self.assertEqual(empty["common.rounds_complete"], "fail")
            self.assertEqual(empty["common.first_draft"], "fail")
            self.assertEqual(empty["facts.no_new_numbers"], "fail")
            self.assertEqual(empty["loop.metrics"], "fail")

    def test_three_rounds_counts_greeting_confirmation_and_contacts(self):
        turns = new_turns("cold")
        turns[2].update(has_data=False, stage="COLLECTING")
        result = indexed("cold", turns)
        self.assertEqual(result["loop.first_draft_by_turn3"], "fail")
        self.assertEqual(loop.observations(turns)["first_draft_turn"], 4)
        self.assertEqual(loop.observations(turns)["turns_from_material"], 2)
        turns.insert(2, {**deepcopy(turns[1]), "action": "confirm", "kind": "confirmation"})
        self.assertEqual(loop.observations(turns)["first_draft_turn"], 5)

    def test_preview_empty_hidden_or_uncommitted_is_not_delivered(self):
        for mutate in (
            lambda t: t.update(stage="COLLECTING"), lambda t: t.update(revision=None),
            lambda t: t.update(has_data=False), lambda t: t["resume_data"].update(projects=[]),
            lambda t: t["resume_data"]["projects"][0].update(hidden=True),
            lambda t: t["resume_data"].update(sections=[]),
            lambda t: t["resume_data"]["projects"][0].update(bullets=[]),
        ):
            turn = new_turns("upload")[0]
            mutate(turn)
            self.assertFalse(loop.delivered(turn), turn)

    def test_form_seen_midstream_cannot_be_hidden_by_current_readback(self):
        turns = new_turns("upload")
        turns[0]["guidance_history"] = [{"kind": "intake_experiences"}]
        self.assertEqual(indexed("upload", turns)["loop.no_initial_form"], "fail")

    def test_contacts_card_and_reply_same_turn_are_one_but_next_turn_repeats(self):
        turns = new_turns("cold")
        turns[2]["workspace"] = {"guidance": {"kind": "ask_user", "questions": [{"prompt": "手机和邮箱"}]}}
        self.assertEqual(loop.observations(turns)["contact_request_turns"], [3])
        turns[-1]["reply"] = "请再提供一下手机号。"
        self.assertEqual(indexed("cold", turns)["loop.contacts_once"], "fail")
        turns[0]["reply"] = "请补充联系方式。"
        self.assertEqual(indexed("cold", turns)["contacts_late"], "fail")

    def test_acknowledgment_or_negative_contact_mentions_are_not_requests(self):
        for text in ("联系方式已记录，无需补充。", "不用发送手机和邮箱。", "不需要提供联系方式。", "已收到邮箱。"):
            self.assertFalse(loop.contact_request({"reply": text}), text)
        for text in ("手机是多少？", "还缺手机、邮箱", "请补充联系方式", "邮箱发我一下"):
            self.assertTrue(loop.contact_request({"reply": text}), text)
        turns = new_turns("upload")
        turns[1]["reply"] = "请填写邮箱。"
        self.assertEqual(indexed("upload", turns)["contacts_not_repeated"], "fail")

    def test_missing_invalid_or_wrong_mode_metrics_are_fail_not_zero(self):
        for field, value in (("model_calls", None), ("model_calls", -1), ("model_calls", True),
                             ("server_seconds", float("nan")), ("elapsed_seconds", -1),
                             ("model_call_scope", "guessed_from_tools"), ("metrics_agent_mode", "off")):
            turns = new_turns("upload")
            turns[0][field] = value
            self.assertEqual(indexed("upload", turns)["loop.metrics"], "fail", (field, value))
        for value in (None, 1, False):
            turns[0]["privacy_blocks"] = value
            self.assertEqual(indexed("upload", turns)["loop.contacts_not_sent"], "fail")

    def test_fabrication_omission_and_hidden_facts_fail_existing_style_checks(self):
        turns = new_turns("upload")
        turns[0]["resume_data"]["projects"][0]["bullets"] += ["成功上线，完成生产压测，性能提升80%。"]
        result = indexed("upload", turns)
        self.assertEqual(result["facts.scope"], "fail")
        self.assertEqual(result["facts.no_new_numbers"], "fail")
        turns = new_turns("upload")
        turns[0]["resume_data"]["projects"][0]["polished_bullets"] = ["负责测试。"]
        self.assertEqual(indexed("upload", turns)["facts.retained"], "fail")
        turns = new_turns("upload")
        turns[0]["resume_data"]["projects"][0]["bullets"] += ["没有上线部署，未做生产压测。"]
        self.assertEqual(indexed("upload", turns)["facts.scope"], "pass")

    def test_new_identity_tools_experiences_and_role_upgrade_are_rejected(self):
        for field, mutate in (
            ("facts.identity", lambda data: data["education"][0].update(school="另一个学校")),
            ("facts.no_new_tools", lambda data: data.update(skills=["Python 基础", "Kubernetes"])),
            ("facts.no_extra_experience", lambda data: data.update(awards=[{"name": "竞赛奖项", "bullets": ["获奖"]}])),
            ("facts.scope", lambda data: data["projects"][0].update(role="项目负责人")),
            ("facts.no_new_numbers", lambda data: data["projects"][0]["bullets"].append("处理999条记录。")),
        ):
            turns = new_turns("upload")
            mutate(turns[-1]["resume_data"])
            self.assertEqual(indexed("upload", turns)[field], "fail", field)
        turns = new_turns("upload")
        turns[0]["resume_data"]["projects"][0].update(start_date="2026.03", end_date="2026/05")
        turns[0]["resume_data"]["projects"][0]["bullets"].append("不是项目负责人。")
        self.assertEqual(indexed("upload", turns)["facts.no_new_numbers"], "pass")
        self.assertEqual(indexed("upload", turns)["facts.scope"], "pass")

    def test_off_and_loop_reports_recompute_new_and_all_eight_old_personas(self):
        personas = (*runner.checks.PERSONAS, *runner.CARD_PERSONAS)
        run = {"schema_version": 1, "run_id": "old", "personas": {p: {"turns": []} for p in personas}}
        old = report.result_index(run)
        run.update(agent_mode="loop", agent_mode_verified=True)
        new = report.result_index(run)
        self.assertTrue(all(new[k]["status"] == row["status"] for k, row in old.items()))
        self.assertEqual(len(new) - len(old), 5 * 8)
        run["personas"].update({p: {"turns": new_turns(p), "checks": []} for p in loop.FIXTURES})
        run["personas"]["upload"]["turns"][0]["model_calls"] = None
        text = report.render_report([run])
        self.assertIn("returning.profile.draft", text)
        self.assertIn("upload.loop.metrics", text)
        self.assertIn("N/A", text)
        self.assertIn("首稿总轮次=3", text)


class LoopRunnerTests(unittest.TestCase):
    def test_mode_mismatch_fails_before_guest_creation_or_output(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner.GuestClient, "json", return_value={
                "schema_version": 1, "agent_mode": "off", "model_call_scope": loop.CALL_SCOPE}) as call:
            output = Path(directory) / "run"
            with self.assertRaises(ValueError):
                runner.run_replay("http://127.0.0.1:8847", output, ["cold"], agent_mode="loop")
            call.assert_called_once_with("/_evaluation/config")
            self.assertFalse(output.exists())

    def test_sse_metrics_projection_tool_progress_and_card_snapshot(self):
        events = [{"type": "evaluation_metrics", "agent_mode": "loop", **metrics(), "secret": "DO_NOT_SAVE"},
                  {"type": "tool_status", "tool": "record_facts", "status": "completed", "arguments": "DO_NOT_SAVE"},
                  {"type": "meta", "workspace": {"guidance": {"kind": "intake_basics"}}},
                  {"content": "公开回复"}]
        raw = ''.join("data: " + json.dumps(e) + "\n\n" for e in events) + 'data: [DONE]\n\n'
        result = runner.read_sse(io.BytesIO(raw.encode()))
        self.assertEqual(result["metrics"]["model_calls"], 2)
        self.assertNotIn("DO_NOT_SAVE", str(result))
        self.assertEqual(result["guidance_history"], [{"kind": "intake_basics"}])
        self.assertEqual(result["reply"], "公开回复")

    def test_new_personas_wire_uses_free_text_without_tool_args_or_mode_override(self):
        sent = []

        class Client:
            def __init__(self, *_):
                self.cookies = SimpleNamespace(clear=lambda: None)
                self.rows = []

            def json(self, path):
                self.assert_path = path
                return {"schema_version": 1, "agent_mode": "loop", "model_call_scope": loop.CALL_SCOPE}

            def start(self):
                pass

            def turn(self, action, text, **kwargs):
                if not self.rows:
                    self.rows = new_turns("cold" if text == loop.FIXTURES["cold"]["initial"] else "upload")
                sent.append((action, text, kwargs))
                return self.rows.pop(0)

        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "GuestClient", Client):
            run = runner.run_replay("http://127.0.0.1:8847", Path(directory) / "run", ["cold", "upload"], agent_mode="loop")
            self.assertEqual(run["status"], "pass")
            self.assertEqual(run["stream_requests"], 7)
            self.assertTrue(run["agent_mode_verified"])
            self.assertTrue(all(not extra for _, _, extra in sent))
            self.assertEqual(sent[0][1], "你好")
            self.assertEqual(run["personas"]["cold"]["observations"]["first_draft_turn"], 3)

    def test_mode_setting_requires_actual_production_support(self):
        self.assertEqual(server.configured_mode(SimpleNamespace(), "off"), "off")
        with self.assertRaises(ValueError):
            server.configured_mode(SimpleNamespace(), "loop")
        self.assertEqual(server.configured_mode(SimpleNamespace(AGENT_MODE="loop"), "loop"), "loop")


class MeterTests(unittest.IsolatedAsyncioTestCase):
    async def test_nested_sync_async_retries_count_and_concurrent_turns_stay_isolated(self):
        async def run(count):
            ledger = {"model_calls": 0, "privacy_blocks": 0}
            token = server.COUNTS.set(ledger)
            try:
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(400))) as client:
                    async def nested():
                        for _ in range(count):
                            await client.post("https://model.invalid/v1/chat/completions", json={"messages": []})
                            await asyncio.sleep(0)
                        await client.get("https://model.invalid/other")
                    await asyncio.create_task(nested())
                with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
                    client.post("https://model.invalid/v1/responses", json={"input": "safe"})
                return ledger
            finally:
                server.COUNTS.reset(token)

        with server.model_meter():
            one, two = await asyncio.gather(run(1), run(3))
        self.assertEqual(one["model_calls"], 2)
        self.assertEqual(two["model_calls"], 4)
        self.assertIsNone(server.COUNTS.get())

    async def test_contacts_blocked_before_any_provider_send_including_reasoning(self):
        ledger = {"model_calls": 0, "privacy_blocks": 0}
        token = server.COUNTS.set(ledger)
        sent = []
        try:
            with server.model_meter():
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: sent.append(r))) as client:
                    for body in ({"messages": [{"content": "13900002017"}]},
                                 {"messages": [{"reasoning_content": "a@example.invalid"}]},
                                 {"input": [{"function": {"arguments": '{"email":"a@example.invalid"}'}}]}):
                        with self.assertRaisesRegex(ValueError, "^contacts_in_model_request$"):
                            await client.post("https://model.invalid/v1/chat/completions", json=body)
            self.assertEqual(sent, [])
            self.assertEqual(ledger, {"model_calls": 0, "privacy_blocks": 3})
        finally:
            server.COUNTS.reset(token)

    async def test_asgi_adds_metrics_before_split_done_without_raw_metadata(self):
        async def app(scope, receive, send):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
                await client.post("https://model.invalid/chat/completions", json={"messages": []})
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
            for body in (b'data: {"content":"ok"}\r\n\r\ndata: [DO', b'NE]\r\n\r\n'):
                await send({"type": "http.response.body", "body": body, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        outgoing = []

        async def send(message):
            outgoing.append(message)

        with server.model_meter():
            await server.ReplayApp(app, "loop")({"type": "http", "path": "/api/chat/stream", "method": "POST"}, None, send)
        raw = b''.join(m.get("body", b"") for m in outgoing)
        result = runner.read_sse(io.BytesIO(raw))
        self.assertTrue(result["done"])
        self.assertEqual(result["reply"], "ok")
        self.assertEqual(result["metrics"]["model_calls"], 1)
        self.assertEqual(result["metrics"]["metrics_agent_mode"], "loop")
        self.assertLess(raw.index(b'evaluation_metrics'), raw.index(b'[DONE]'))

    async def test_no_done_is_still_failure_and_config_never_calls_app(self):
        async def app(scope, receive, send):
            raise AssertionError("config must not call application")

        outgoing = []

        async def send(message):
            outgoing.append(message)

        await server.ReplayApp(app, "off")({"type": "http", "path": "/_evaluation/config"}, None, send)
        self.assertEqual(json.loads(outgoing[-1]["body"])["agent_mode"], "off")
        self.assertIsNone(runner.read_sse(io.BytesIO(b'data: {"content":"partial"}\n\n')).get("metrics"))

    async def test_truncated_sse_records_cost_without_fabricating_done(self):
        async def app(scope, receive, send):
            server.COUNTS.get()["model_calls"] = 3
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
            await send({"type": "http.response.body", "body": b'data: {"content":"partial"}\n\n', "more_body": False})

        outgoing = []

        async def send(message):
            outgoing.append(message)

        await server.ReplayApp(app, "loop")({"type": "http", "path": "/api/chat/stream", "method": "POST"}, None, send)
        result = runner.read_sse(io.BytesIO(b''.join(m.get("body", b"") for m in outgoing)))
        self.assertFalse(result["done"])
        self.assertEqual(result["metrics"]["model_calls"], 3)
        self.assertIn("SSE ended without [DONE]", result["errors"])


class SpikeExpectationsTests(unittest.TestCase):
    def test_only_post_draft_questions_are_accepted_for_updated_cases(self):
        from scripts.run_agent_spike import assess, DEFAULT_CASES
        cases = {c["id"]: c for c in json.loads(DEFAULT_CASES.read_text())["cases"]}
        for key, prefix in (("04", ["read_profile", "use_profile_items"]), ("08", ["record_facts"])):
            result = dict(status="completed", tools=[], final_reply="模拟", requested_tool_sequence=prefix + ["write_draft", "ask_user"])
            self.assertTrue(assess(cases[key], result)["matches_expectation"])
            result["requested_tool_sequence"] = prefix + ["ask_user", "write_draft"]
            self.assertFalse(assess(cases[key], result)["matches_expectation"])
        self.assertEqual(len(cases), 13)
