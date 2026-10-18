#!/usr/bin/env python3
"""Replay synthetic fixtures through a running loopback service as fresh guests.

Uses only Python's standard library. Credentials remain in an in-memory cookie
jar, one per persona; neither response headers nor raw SSE metadata are saved.
No automatic retries: a retry can duplicate a paid turn or change its meaning.
"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
from http.cookiejar import CookieJar
from importlib import import_module
import ipaddress
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MATERIALS = ROOT / "evaluation" / "persona-ux-2026-10-15"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
checks = import_module("evaluation.persona-ux.checks")
aipm = import_module("evaluation.persona-ux.aipm")
aipm_real = import_module("evaluation.persona-ux.aipm_real")
returning = import_module("evaluation.persona-ux.returning")
loop_checks = import_module("evaluation.persona-ux.loop_checks")
metrics = import_module("evaluation.persona-ux.metrics")
CARD_PERSONAS = {"aipm": aipm, "aipm_real": aipm_real, "returning": returning}


def timestamp():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S-%f")


def local_base(value):
    parts = urlsplit(value)
    local = parts.hostname == "localhost"
    if not local:
        try:
            local = ipaddress.ip_address(parts.hostname or "").is_loopback
        except ValueError:
            pass
    if not local or parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.query or parts.fragment or parts.path not in {"", "/"}:
        raise ValueError("--base 必须是本地 loopback HTTP 服务的根地址")
    # Validate the port without including the supplied URL in error output.
    _ = parts.port
    return value.rstrip("/")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Redirect refused", headers, fp)


def read_sse(response, result=None):
    """Consume complete SSE frames, including CRLF, multiline data and comments."""
    result = result if result is not None else {"reply": "", "meta": {}, "done": False, "errors": []}
    lines = []

    def consume():
        if not lines:
            return
        payload = "\n".join(lines)
        lines.clear()
        if payload == "[DONE]":
            result["done"] = True
            return
        if result["done"]:
            return
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            result["errors"].append("Malformed SSE data")
            return
        if not isinstance(event, dict):
            result["errors"].append("SSE data is not an object")
        elif event.get("error"):
            # Keep an error code/type, not arbitrary server text that could
            # contain configured provider details or credentials.
            code = str(event.get("code") or "SSE_ERROR")
            result["errors"].append(code if code.replace("-", "").replace("_", "").isalnum() else "SSE_ERROR")
        elif event.get("type") == "meta":
            result["meta"].update(event)
            guidance = (event.get("workspace") or {}).get("guidance")
            if isinstance(guidance, dict) and guidance:
                result.setdefault("guidance_history", []).append({k: guidance[k] for k in
                    ("kind", "title", "question", "questions") if k in guidance})
        elif event.get("type") == "evaluation_metrics":
            if "metrics" in result:
                result["errors"].append("Duplicate evaluation metrics")
            result["metrics"] = {
                "model_calls": event.get("model_calls") if type(event.get("model_calls")) is int else None,
                "privacy_blocks": event.get("privacy_blocks") if type(event.get("privacy_blocks")) is int else None,
                "server_seconds": event.get("server_seconds") if loop_checks.finite_nonnegative(event.get("server_seconds")) else None,
                "metrics_agent_mode": event.get("agent_mode") if event.get("agent_mode") in {"off", "loop"} else None,
                "model_call_scope": loop_checks.CALL_SCOPE if event.get("model_call_scope") == loop_checks.CALL_SCOPE else None,
                "metrics_version": 2 if event.get("metrics_version") == 2 else None,
                "orchestrator": metrics.orchestrator(event.get("orchestrator")),
            }
        elif event.get("type") == "tool_status":
            name, status = event.get("tool"), event.get("status")
            if isinstance(name, str) and name.replace("_", "").isalnum() and status in {"running", "completed"}:
                result.setdefault("tool_status", []).append({"tool": name, "status": status})
        elif isinstance(event.get("content"), str):
            result["reply"] += event["content"]

    for raw in response:
        line = raw.decode("utf-8-sig").rstrip("\r\n")
        if not line:
            consume()
        elif line.startswith("data:"):
            lines.append(line[5:].removeprefix(" "))
    consume()
    if not result["done"]:
        result["errors"].append("SSE ended without [DONE]")
    return result


def safe_error(error):
    if isinstance(error, HTTPError):
        return f"HTTP {error.code}"
    if isinstance(error, (TimeoutError, URLError)):
        return "HTTP timeout/connection unavailable"
    return type(error).__name__


class GuestClient:
    def __init__(self, base, timeout=300):
        self.base = local_base(base)
        self.timeout = timeout
        self.cookies = CookieJar()
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(self.cookies))
        self.session_id = None

    def open(self, path, body=None, content_type="application/json"):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(self.base + path, data=payload,
                          headers={"Content-Type": content_type} if payload is not None else {})
        return self.opener.open(request, timeout=self.timeout)

    def json(self, path, body=None, content_type="application/json"):
        with self.open(path, body, content_type) as response:
            return json.load(response)

    def start(self):
        # Same creation API as conversation-history.js; no login or account APIs.
        body = self.json("/api/chat/conversations", {})
        self.session_id = body["session_id"]
        if not any(cookie.name == "huhua_guest" for cookie in self.cookies):
            raise ValueError("Guest cookie was not issued")

    def upload(self, path):
        boundary = "persona-" + uuid4().hex
        prefix = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                  f"filename=\"{path.name}\"\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n").encode()
        payload = prefix + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        result = self.json("/api/chat/upload", payload, f"multipart/form-data; boundary={boundary}")
        if not isinstance(result.get("text"), str) or not result["text"].strip():
            raise ValueError("Attachment extraction was empty")
        # Frontend send(): [文件: filename]\ntext\n\n---\n\nuser text.
        return f"[文件: {result['filename']}]\n{result['text']}"

    def turn(self, action, text, *, kind="fixture", trigger_action=None, answers=None, intake=None):
        started = time.monotonic()
        record = {"action": action, "trigger_action": trigger_action or action, "kind": kind,
                  "input": text, "reply": "", "resume_data": {}, "workspace": {},
                  "status": "ok", "error": "", "sse_done": False, "has_data": False}
        stream = {"reply": "", "meta": {}, "done": False, "errors": []}
        try:
            payload = {"messages": [{"role": "user", "content": text}], "session_id": self.session_id, "task": "auto"}
            payload.update({key: value for key, value in {"answers": answers, "intake": intake}.items() if value is not None})
            record.update({key: value for key, value in {"answers": answers, "intake": intake}.items() if value is not None})
            with self.open("/api/chat/stream", payload) as response:
                read_sse(response, stream)
            if stream["errors"]:
                record.update(status="error", error="; ".join(stream["errors"]))
        except Exception as error:
            record.update(status="error", error=safe_error(error))
        record.update(reply=stream["reply"], sse_done=stream["done"])
        record.update(stream.get("metrics") or dict.fromkeys(
            ("model_calls", "privacy_blocks", "server_seconds", "metrics_agent_mode", "model_call_scope")))
        record.setdefault('orchestrator', None)
        record["guidance_history"] = stream.get("guidance_history", [])
        record["tool_status"] = stream.get("tool_status", [])
        record["stream_seconds"] = round(time.monotonic() - started, 3)
        read_started = time.monotonic()
        # Read canonical data even after a failed/truncated stream, so a silent
        # save or a preserved previous version remains inspectable.
        try:
            current = self.json("/api/resume/current?" + urlencode({"session_id": self.session_id}))
            record.update(resume_data=current.get("data") or {}, workspace=(current.get("workspace") if "workspace" in current else stream["meta"].get("workspace")) or {},
                          has_data=bool(current.get("has_data")), stage=current.get("stage"), revision=current.get("revision"))
        except Exception as error:
            record.update(status="error", error="; ".join(filter(None, [record["error"], "current: " + safe_error(error)])))
            record["workspace"] = stream["meta"].get("workspace") or {}
        record["current_seconds"] = round(time.monotonic() - read_started, 3)
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return record


def confirmation_value(workspace):
    guidance = workspace.get("guidance") or {}
    if guidance.get("kind") != "structure_plan":
        return None
    for option in guidance.get("options") or []:
        if option.get("label") == "按推荐写" and isinstance(option.get("value"), str) and option["value"].strip():
            return option["value"]
    raise ValueError("Pending plan has no recommended confirmation option")


def fixture_actions(fixture, with_recovery=False):
    return [(name, text) for name, text in fixture.items() if name != "role" and (with_recovery or name != "recovery")]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_turn(directory, index, record):
    prefix = directory / f"{index:02d}-{record['action']}"
    write_json(prefix.with_suffix(".json"), record)
    prefix.with_suffix(".reply.txt").write_text(record["reply"], encoding="utf-8")


def run_replay(base, output, personas, *, with_recovery=False, timeout=300, materials=MATERIALS, returning_db=None, agent_mode=None):
    base = local_base(base)
    if not personas or len(set(personas)) != len(personas) or any(p not in (*checks.PERSONAS, *CARD_PERSONAS, *loop_checks.FIXTURES) for p in personas):
        raise ValueError("Personas must be a nonempty unique selection")
    if agent_mode not in {None, "off", "loop"}:
        raise ValueError("agent_mode must be off/loop")
    if "returning" in personas and not returning_db:
        raise ValueError("returning requires --returning-db for the isolated local service")
    if agent_mode is not None:
        config = GuestClient(base, timeout).json("/_evaluation/config")
        if (config.get("schema_version") != 1 or config.get("agent_mode") != agent_mode
                or config.get("model_call_scope") != loop_checks.CALL_SCOPE):
            raise ValueError("Replay server mode/metrics mismatch; start evaluation/persona-ux/serve.py")
    fixture_bytes = (materials / "fixtures.json").read_bytes()
    fixtures = {**json.loads(fixture_bytes), "aipm": aipm.FIXTURE, **loop_checks.FIXTURES}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    run = {"schema_version": 1, "run_id": output.name, "started_at": timestamp(), "base": base,
           "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(), "with_recovery": with_recovery,
           "agent_mode": agent_mode or "off", "agent_mode_verified": agent_mode is not None,
           "confirmation_contract": "workspace.guidance.options[label=按推荐写].value → /api/chat/stream, task=auto",
           "personas": {}}
    if any(p in loop_checks.FIXTURES for p in personas):
        run["loop_fixture_sha256"] = hashlib.sha256(loop_checks.FIXTURE_PATH.read_bytes()).hexdigest()
    if "aipm" in personas:
        run["aipm_synthetic_placeholder"] = True
        run["aipm_fixture_sha256"] = hashlib.sha256(Path(aipm.__file__).read_bytes()).hexdigest()
    if "aipm_real" in personas:
        run["aipm_real_source"] = "用户授权导出的真实对话；已确认无个人联系方式；经历名称与开始月份另经确认"
        run["aipm_real_fixture_sha256"] = hashlib.sha256(Path(aipm_real.__file__).read_bytes()).hexdigest()
    if "returning" in personas:
        run["returning_fixture_sha256"] = hashlib.sha256(Path(returning.__file__).read_bytes()).hexdigest()
    started = time.monotonic()
    write_json(output / "run.json", run)
    for persona in personas:
        directory = output / persona
        directory.mkdir()
        record = {"turns": [], "error": ""}
        run["personas"][persona] = record
        persona_started = time.monotonic()
        client = GuestClient(base, timeout)
        try:
            if persona == "returning":
                returning.start(client, returning_db)
            else:
                client.start()
            if persona in CARD_PERSONAS:
                options = {'agent_mode': agent_mode} if persona in {'aipm', 'aipm_real'} else {}
                for turn in CARD_PERSONAS[persona].replay(client, **options):
                    record["turns"].append(turn)
                    save_turn(directory, len(record["turns"]), turn)
            attachment = client.upload(materials / "design-material.txt") if persona == "design" else ""
            for action, text in ([] if persona in CARD_PERSONAS else fixture_actions(fixtures[persona], with_recovery)):
                extra = {}
                content = attachment + "\n\n---\n\n" + text if action == "initial" and attachment else text
                turn = client.turn(action, content, **extra)
                record["turns"].append(turn)
                save_turn(directory, len(record["turns"]), turn)
                if turn["status"] != "ok":
                    break
                value = confirmation_value(turn["workspace"])
                if value is not None:
                    confirmed = client.turn(action + "_confirm", value, kind="confirmation", trigger_action=action)
                    record["turns"].append(confirmed)
                    save_turn(directory, len(record["turns"]), confirmed)
                    if confirmed["status"] != "ok":
                        break
                    if confirmation_value(confirmed["workspace"]) is not None:
                        raise ValueError("Plan remained pending after one confirmation")
        except Exception as error:
            record["error"] = safe_error(error)
        finally:
            client.cookies.clear()
        record["elapsed_seconds"] = round(time.monotonic() - persona_started, 3)
        evaluator = loop_checks if persona in loop_checks.FIXTURES else CARD_PERSONAS.get(persona, checks)
        record["checks"] = evaluator.evaluate_persona(persona, record["turns"], with_recovery=with_recovery)
        if agent_mode == "loop":
            record["checks"] += loop_checks.evaluate_loop(persona, record["turns"])
        record["observations"] = loop_checks.observations(record["turns"], persona)
        if record["error"]:
            completion = next(c for c in record["checks"] if c["id"].endswith("common.rounds_complete"))
            completion["status"] = "fail"
            completion["evidence"].append(checks.evidence({}, "error", record["error"]))
        write_json(directory / "checks.json", record["checks"])
        write_json(output / "run.json", run)
    run["elapsed_seconds"] = round(time.monotonic() - started, 3)
    run["stream_requests"] = sum(len(p["turns"]) for p in run["personas"].values())
    run["status"] = "pass" if all(c["status"] == "pass" for p in run["personas"].values() for c in p["checks"]) else "fail"
    write_json(output / "run.json", run)
    return run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8833")
    parser.add_argument("--persona", default=",".join(checks.PERSONAS))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--with-recovery", action="store_true")
    parser.add_argument("--agent-mode", choices=("off", "loop"), help="核对评测服务的 AGENT_MODE；省略则兼容旧服务")
    parser.add_argument("--returning-db", type=Path, help="本地隔离回放服务已初始化的 SQLite 数据库；需使用相同加密配置")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args(argv)
    output = (args.output or HERE / "runs" / timestamp()).resolve()
    if not output.is_relative_to((HERE / "runs").resolve()) or output == (HERE / "runs").resolve():
        parser.error("--output 必须位于 evaluation/persona-ux/runs/<名称>，且目录尚不存在")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        run = run_replay(args.base, output, [p.strip() for p in args.persona.split(",")],
                         with_recovery=args.with_recovery, timeout=args.timeout, returning_db=args.returning_db, agent_mode=args.agent_mode)
    except (ValueError, OSError) as error:
        parser.error(safe_error(error))
    print(f"{run['status'].upper()} · {run['stream_requests']} 次聊天请求 · {output / 'run.json'}")
    return 0 if run["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
