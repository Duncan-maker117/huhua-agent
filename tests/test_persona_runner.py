"""HTTP wire/SSE against stdlib server handlers; never invokes a model.

Use socketpair for transport so the tests also work where listening TCP ports
are prohibited. urllib, cookie handling and HTTP serialization are unchanged.
"""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from copy import deepcopy
from http.server import BaseHTTPRequestHandler
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from urllib.error import HTTPError
from urllib.request import Request
import io
import json
from pathlib import Path
import tempfile
import threading
import socket
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from persona_support import checks, runner, FIXTURES, golden_turns, MATERIALS


@contextmanager
def stub_server(personas=("tech",), *, plans=True, done=True, stream_error=False, current_error=False, guest_cookie=True, bootstrap_error=False, with_recovery=False):
    state = {"sessions": {}, "requests": [], "uploads": [], "cookies": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, payload, content_type="application/json", cookie=None, status=200):
            if not isinstance(payload, bytes):
                payload = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            if cookie:
                self.send_header("Set-Cookie", f"huhua_guest={cookie}; Path=/; HttpOnly")
            self.end_headers()
            self.wfile.write(payload)

        def body(self):
            return self.rfile.read(int(self.headers.get("Content-Length", "0")))

        def cookie(self):
            parsed = SimpleCookie(self.headers.get("Cookie", ""))
            return parsed["huhua_guest"].value if "huhua_guest" in parsed else None

        def do_POST(self):
            raw = self.body()
            if self.path == "/api/chat/conversations":
                if bootstrap_error:
                    self.send({"detail": "Unavailable"}, status=503)
                    return
                index = len(state["sessions"])
                persona = personas[index]
                session_id, cookie = f"synthetic-session-{index}", f"synthetic-guest-{index}"
                state["sessions"][session_id] = {"persona": persona, "cookie": cookie, "index": 0, "pending": False, "current": {}}
                state["cookies"].append(cookie)
                self.send({"session_id": session_id}, cookie=cookie if guest_cookie else None)
            elif self.path == "/api/chat/upload":
                state["uploads"].append({"raw": raw, "type": self.headers.get("Content-Type"), "cookie": self.cookie()})
                text = (MATERIALS / "design-material.txt").read_text(encoding="utf-8")
                self.send({"filename": "design-material.txt", "text": text, "text_length": len(text), "source_type": "document"})
            elif self.path == "/api/chat/stream":
                payload = json.loads(raw)
                session = state["sessions"][payload["session_id"]]
                if self.cookie() != session["cookie"]:
                    self.send({"detail": "wrong guest"}, status=403)
                    return
                state["requests"].append({"payload": payload, "cookie": self.cookie()})
                persona = session["persona"]
                fixture_turns = golden_turns(persona, with_recovery)
                if session["pending"]:
                    turn = fixture_turns[0]
                    session.update(pending=False, index=1)
                else:
                    turn = fixture_turns[session["index"]]
                    if plans and session["index"] == 0:
                        session["pending"] = True
                        turn = deepcopy(turn)
                        turn["resume_data"] = {}
                        turn["workspace"] = {"guidance": {"kind": "structure_plan", "structure_plan": {"recommended": {"label": "合成推荐"}}, "options": [{"label": "按推荐写", "value": "按推荐写"}]}}
                    else:
                        session["index"] += 1
                session["current"] = {"has_data": bool(turn["resume_data"]), "data": turn["resume_data"], "workspace": turn["workspace"], "stage": "EVALUATING", "revision": "synthetic-revision"}
                reply = turn["reply"]
                events = [": keepalive\r\n\r\n"]
                events += ["data: " + json.dumps({"content": part}, ensure_ascii=False) + "\r\n\r\n" for part in (reply[:5], reply[5:])]
                events += ["data: " + json.dumps({"type": "meta", "session_id": payload["session_id"], "workspace": turn["workspace"]}, ensure_ascii=False) + "\r\n\r\n"]
                if stream_error:
                    events += ['data: {"error":"synthetic-provider-detail", "code":"E-SYNTHETIC"}\r\n\r\n']
                if done:
                    events += ["data: [DONE]\r\n\r\n"]
                self.send("".join(events).encode(), "text/event-stream")
            else:
                self.send({}, status=404)

        def do_GET(self):
            session_id = parse_qs(urlsplit(self.path).query)["session_id"][0]
            session = state["sessions"][session_id]
            if self.cookie() != session["cookie"]:
                self.send({}, status=403)
            elif current_error:
                self.send({}, status=503)
            else:
                self.send(session["current"])

    threads = []

    def connect(connection):
        client_socket, server_socket = socket.socketpair()
        client_socket.settimeout(5)
        connection.sock = client_socket

        def serve():
            with server_socket:
                Handler(server_socket, ("127.0.0.1", 8833), None)

        thread = threading.Thread(target=serve, daemon=True)
        threads.append(thread)
        thread.start()

    try:
        with patch.object(HTTPConnection, "connect", connect):
            yield "http://127.0.0.1:8833", state
    finally:
        for thread in threads:
            thread.join(timeout=5)
            if thread.is_alive():
                raise AssertionError("HTTP stub thread did not finish")


class SSETests(unittest.TestCase):
    def test_crlf_comments_multiline_and_public_tokens(self):
        stream = io.BytesIO((': heartbeat\r\nevent: message\r\ndata: {"content":\r\ndata: "中文完整回复"}\r\n\r\n'
                             'data: {"type":"meta","workspace":{"focus":"resume"}}\n\n'
                             'data: [DONE]\n\n').encode())
        result = runner.read_sse(stream)
        self.assertEqual(result["reply"], "中文完整回复")
        self.assertEqual(result["meta"]["workspace"], {"focus": "resume"})
        self.assertTrue(result["done"])
        self.assertEqual(result["errors"], [])

    def test_missing_done_malformed_json_and_error_are_not_success(self):
        for payload, fragment in ((b'data: {"content":"partial"}\n\n', "without [DONE]"),
                                  (b'data: not-json\n\ndata: [DONE]\n\n', "Malformed"),
                                  (b'data: []\n\ndata: [DONE]\n\n', "not an object"),
                                  (b'data: {"error":"private-detail","code":"E-FAIL"}\n\ndata: [DONE]\n\n', "E-FAIL")):
            result = runner.read_sse(io.BytesIO(payload))
            self.assertTrue(any(fragment in error for error in result["errors"]))
            self.assertNotIn("private-detail", str(result["errors"]))

    def test_unterminated_final_frame_and_post_done_tokens(self):
        result = runner.read_sse(io.BytesIO(b'data: {"content":"before"}\n\ndata: [DONE]\n\ndata: {"content":"after"}'))
        self.assertEqual(result["reply"], "before")
        self.assertTrue(result["done"])


class RunnerTests(unittest.TestCase):
    def test_full_guest_http_upload_and_confirmation_replay_without_recovery(self):
        with tempfile.TemporaryDirectory() as directory, stub_server(checks.PERSONAS) as (base, state):
            output = Path(directory) / "run"
            run = runner.run_replay(base, output, checks.PERSONAS)
            self.assertEqual(run["stream_requests"], 19)  # 14 fixed turns + 5 plan confirmations.
            self.assertEqual(run["status"], "fail")  # Empty pre-confirmation direct-generation turn is a real failure.
            self.assertEqual(len(state["sessions"]), 5)
            self.assertEqual(len(set(state["cookies"])), 5)
            self.assertEqual(len(state["uploads"]), 1)
            self.assertIn(b'name="file"', state["uploads"][0]["raw"])
            self.assertIn("借物".encode(), state["uploads"][0]["raw"])
            for persona, record in run["personas"].items():
                actions = [t["action"] for t in record["turns"]]
                self.assertNotIn("recovery", actions)
                self.assertEqual(actions[0:2], ["initial", "initial_confirm"])
                self.assertEqual(record["turns"][1]["input"], "按推荐写")
                self.assertEqual(record["turns"][1]["kind"], "confirmation")
                for turn in record["turns"]:
                    self.assertEqual(turn["status"], "ok")
                    self.assertTrue(turn["sse_done"])
                    self.assertGreaterEqual(turn["elapsed_seconds"], 0)
                self.assertTrue(all((output / persona / f"{i:02d}-{t['action']}.json").exists() for i, t in enumerate(record["turns"], 1)))
            design = run["personas"]["design"]["turns"][0]["input"]
            self.assertTrue(design.startswith("[文件: design-material.txt]\n"))
            self.assertTrue(design.endswith("\n\n---\n\n" + FIXTURES["design"]["initial"]))
            for request in state["requests"]:
                self.assertEqual(request["payload"]["task"], "auto")
                self.assertEqual(len(request["payload"]["messages"]), 1)
                session = state["sessions"][request["payload"]["session_id"]]
                self.assertEqual(request["cookie"], session["cookie"])
            saved = "\n".join(path.read_text() for path in output.rglob("*") if path.is_file())
            for cookie in state["cookies"]:
                self.assertNotIn(cookie, saved)
            self.assertNotIn("Set-Cookie", saved)
            self.assertNotIn("synthetic-session-", saved)
            self.assertEqual(json.loads((output / "run.json").read_text()), run)

    def test_no_plan_path_passes_and_does_not_send_guessed_confirmation(self):
        with tempfile.TemporaryDirectory() as directory, stub_server(checks.PERSONAS, plans=False) as (base, state):
            run = runner.run_replay(base, Path(directory) / "run", checks.PERSONAS)
            self.assertEqual(run["status"], "pass", [c for p in run["personas"].values() for c in p["checks"] if c["status"] == "fail"])
            self.assertEqual(run["stream_requests"], 14)
            self.assertEqual(len(state["requests"]), 14)

    def test_full_recovery_path_follows_seventeen_fixture_turns(self):
        with tempfile.TemporaryDirectory() as directory, stub_server(checks.PERSONAS, plans=False, with_recovery=True) as (base, _):
            run = runner.run_replay(base, Path(directory) / "run", checks.PERSONAS, with_recovery=True)
            self.assertEqual(run["stream_requests"], 17)
            self.assertEqual(run["status"], "pass")
            for persona in ("tech", "career", "design"):
                self.assertEqual(run["personas"][persona]["turns"][1]["action"], "recovery")

    def test_http_failures_are_saved_and_other_personas_continue(self):
        with tempfile.TemporaryDirectory() as directory, stub_server(("tech", "service"), plans=False, current_error=True) as (base, _):
            run = runner.run_replay(base, Path(directory) / "run", ("tech", "service"))
            for record in run["personas"].values():
                self.assertEqual(len(record["turns"]), 1)
                self.assertEqual(record["turns"][0]["status"], "error")
                self.assertIn("HTTP 503", record["turns"][0]["error"])
                self.assertTrue(record["turns"][0]["reply"])

    def test_bootstrap_failure_or_missing_guest_cookie_fails_without_turns(self):
        for kwargs in ({"guest_cookie": False}, {"bootstrap_error": True}):
            with tempfile.TemporaryDirectory() as directory, stub_server(**kwargs) as (base, _):
                run = runner.run_replay(base, Path(directory) / "run", ("tech",))
                self.assertEqual(run["status"], "fail")
                self.assertTrue(run["personas"]["tech"]["error"])
                self.assertEqual(run["personas"]["tech"]["turns"], [])

    def test_sse_errors_and_truncation_preserve_reply_and_current(self):
        for kwargs in ({"done": False}, {"stream_error": True}):
            with tempfile.TemporaryDirectory() as directory, stub_server(plans=False, **kwargs) as (base, _):
                run = runner.run_replay(base, Path(directory) / "run", ("tech",))
                turn = run["personas"]["tech"]["turns"][0]
                self.assertEqual(turn["status"], "error")
                self.assertTrue(turn["reply"])
                self.assertEqual(turn["resume_data"], golden_turns("tech")[0]["resume_data"])

    def test_confirmation_uses_card_value_and_rejects_missing_option(self):
        self.assertIsNone(runner.confirmation_value({}))
        card = {"guidance": {"kind": "structure_plan", "options": [{"label": "按推荐写", "value": "returned-option-value"}]}}
        self.assertEqual(runner.confirmation_value(card), "returned-option-value")
        card["guidance"]["options"] = []
        with self.assertRaises(ValueError):
            runner.confirmation_value(card)

    def test_fixture_order_and_recovery_switch(self):
        self.assertEqual([a for a, _ in runner.fixture_actions(FIXTURES["design"])], ["initial", "paste", "polish"])
        self.assertEqual([a for a, _ in runner.fixture_actions(FIXTURES["design"], True)], ["initial", "recovery", "paste", "polish"])
        self.assertEqual(sum(len(runner.fixture_actions(FIXTURES[p])) for p in checks.PERSONAS), 14)
        self.assertEqual(sum(len(runner.fixture_actions(FIXTURES[p], True)) for p in checks.PERSONAS), 17)

    def test_remote_or_credential_urls_and_redirects_rejected(self):
        for value in ("https://example.invalid", "http://127.0.0.1:8833/private", "http://user:pass@localhost", "http://localhost?token=x", "ftp://localhost", "http://localhost:bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.local_base(value)
        self.assertEqual(runner.local_base("http://[::1]:8833/"), "http://[::1]:8833")
        with self.assertRaises(HTTPError):
            runner.NoRedirect().redirect_request(Request("http://localhost:8833"), None, 302, "redirect", {}, "http://example.invalid")

    def test_output_not_overwritten_and_invalid_personas_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            output.mkdir()
            with self.assertRaises(FileExistsError):
                runner.run_replay("http://localhost:8833", output, ("tech",))
            for personas in ((), ("tech", "tech"), ("unknown",)):
                with self.assertRaises(ValueError):
                    runner.run_replay("http://localhost:8833", output, personas)

    def test_cli_pass_fail_and_path_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            here = Path(directory)
            passed = {"status": "pass", "stream_requests": 14}
            with patch.object(runner, "HERE", here), patch.object(runner, "run_replay", return_value=passed) as call, redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(["--output", str(here / "runs" / "one"), "--persona", "ops,tech", "--with-recovery"]), 0)
                self.assertEqual(call.call_args.args[2], ["ops", "tech"])
                self.assertTrue(call.call_args.kwargs["with_recovery"])
                passed["status"] = "fail"
                self.assertEqual(runner.main([]), 1)
            with patch.object(runner, "HERE", here), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.main(["--output", str(here / "outside")])
