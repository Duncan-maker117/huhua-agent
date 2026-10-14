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
checks = import_module("evaluation.persona-ux.checks")


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

    def turn(self, action, text, *, kind="fixture", trigger_action=None):
        started = time.monotonic()
        record = {"action": action, "trigger_action": trigger_action or action, "kind": kind,
                  "input": text, "reply": "", "resume_data": {}, "workspace": {},
                  "status": "ok", "error": "", "sse_done": False, "has_data": False}
        stream = {"reply": "", "meta": {}, "done": False, "errors": []}
        try:
            payload = {"messages": [{"role": "user", "content": text}], "session_id": self.session_id, "task": "auto"}
            with self.open("/api/chat/stream", payload) as response:
                read_sse(response, stream)
            if stream["errors"]:
                record.update(status="error", error="; ".join(stream["errors"]))
        except Exception as error:
            record.update(status="error", error=safe_error(error))
        record.update(reply=stream["reply"], sse_done=stream["done"])
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


def run_replay(base, output, personas, *, with_recovery=False, timeout=300, materials=MATERIALS):
    base = local_base(base)
    if not personas or len(set(personas)) != len(personas) or any(p not in checks.PERSONAS for p in personas):
        raise ValueError("Personas must be a nonempty unique selection")
    fixture_bytes = (materials / "fixtures.json").read_bytes()
    fixtures = json.loads(fixture_bytes)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    run = {"schema_version": 1, "run_id": output.name, "started_at": timestamp(), "base": base,
           "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(), "with_recovery": with_recovery,
           "confirmation_contract": "workspace.guidance.options[label=按推荐写].value → /api/chat/stream, task=auto",
           "personas": {}}
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
            client.start()
            attachment = client.upload(materials / "design-material.txt") if persona == "design" else ""
            for action, text in fixture_actions(fixtures[persona], with_recovery):
                content = attachment + "\n\n---\n\n" + text if action == "initial" and attachment else text
                turn = client.turn(action, content)
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
        record["checks"] = checks.evaluate_persona(persona, record["turns"], with_recovery=with_recovery)
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
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args(argv)
    output = (args.output or HERE / "runs" / timestamp()).resolve()
    if not output.is_relative_to((HERE / "runs").resolve()) or output == (HERE / "runs").resolve():
        parser.error("--output 必须位于 evaluation/persona-ux/runs/<名称>，且目录尚不存在")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        run = run_replay(args.base, output, [p.strip() for p in args.persona.split(",")],
                         with_recovery=args.with_recovery, timeout=args.timeout)
    except (ValueError, OSError) as error:
        parser.error(safe_error(error))
    print(f"{run['status'].upper()} · {run['stream_requests']} 次聊天请求 · {output / 'run.json'}")
    return 0 if run["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
