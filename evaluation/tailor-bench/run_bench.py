#!/usr/bin/env python3
"""Run the unchanged resume graph on synthetic cases; dry run by default.

Every distinct node-boundary resume and committed resume is retained and judged.
Only committed versions count as user-visible. Never imports app storage until
disposable encrypted database paths have been installed in the environment.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import copy
from contextvars import ContextVar
from datetime import datetime
import hashlib
import json
import logging
import os
import re
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from simulate_user import answer_question, select_answer  # noqa: E402
from private_case import (  # noqa: E402
    assert_private_model_policy, evaluate_edit, evaluate_real01, followup_limit,
    is_private, load_cases, measure_rendered_resume, safe_output,
)


def timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def digest(data) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def source_manifest() -> dict:
    files = sorted(path for path in (ROOT / "backend").rglob("*") if path.is_file()
                   and path.suffix in {".py", ".md"} and "__pycache__" not in path.parts)
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    return {"git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "git_branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
            "backend_files_sha256": hashes, "backend_tree_sha256": digest(hashes)}


def isolate(folder: Path) -> None:
    os.environ.update({
        "DATABASE_URL": f"sqlite:///{folder / 'application.sqlite3'}",
        "CHECKPOINT_DB_PATH": str(folder / "checkpoints.sqlite3"),
        "APP_ENV": "local", "REQUIRE_ACCOUNT": "false", "ENABLE_RAG": "false",
        "ALLOW_INSECURE_LOCAL_STORAGE": "false", "AUTH_COOKIE_SECURE": "false",
        "DATA_ENCRYPTION_KEYS": json.dumps({"bench": base64.b64encode(os.urandom(32)).decode()}),
        "DATA_ENCRYPTION_ACTIVE_KEY": "bench", "ACCOUNT_SECRET": base64.b64encode(os.urandom(32)).decode(),
        "SMTP_HOST": "", "SMTP_FROM": "", "SMTP_USERNAME": "", "SMTP_PASSWORD": "",
        "EMAIL_PROVIDER": "smtp", "RESEND_API_KEY": "", "RESEND_FROM": "", "JEV_API_KEY": "",
        "TAVILY_API_KEY": "", "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false",
        "LANGCHAIN_API_KEY": "", "LANGSMITH_API_KEY": "",
    })


class VersionRecorder:
    """Maintain two timelines: all state changes and acknowledged SQL commits."""
    def __init__(self):
        self.versions: list[dict] = []
        self.commits: list[dict] = []
        self.previous_internal = digest({})
        self.previous_committed = digest({})
        self.seen_checkpoints: set[str] = set()

    def record(self, resume: dict, *, turn: int, stage: str, kind: str,
               observed: list[str], checkpoint_id: str | None = None,
               disclosed_fact_indices: list[int] | None = None) -> dict | None:
        current_hash = digest(resume)
        if kind == "committed":
            # A stage change is a generation event even if wording is identical.
            self.commits.append({"turn": turn, "stage": stage, "hash": current_hash,
                                 "has_experience": bool(resume.get("projects") or resume.get("work_experience"))})
        previous = self.previous_committed if kind == "committed" else self.previous_internal
        if current_hash == previous:
            return None
        if kind == "committed":
            self.previous_committed = current_hash
            # The exact internal candidate became visible at this turn's commit.
            for version in reversed(self.versions):
                if version["turn"] == turn and version["hash"] == current_hash:
                    version["user_visible"] = True
                    version["committed_stage"] = stage
                    return version
        else:
            self.previous_internal = current_hash
        version = {"version_id": f"v{len(self.versions) + 1:03d}", "turn": turn,
                   "kind": kind, "stage": stage, "hash": current_hash,
                   "user_visible": kind == "committed", "checkpoint_id": checkpoint_id,
                   "observed_facts": list(observed),
                   "disclosed_fact_indices": list(disclosed_fact_indices or []),
                   "resume_data": copy.deepcopy(resume)}
        self.versions.append(version)
        return version


def has_experience_body(resume: dict) -> bool:
    from judge import candidate_units
    return any(re.match(r"^(projects|work_experience|internship)\[\d+\]\.bullets\[", unit["path"])
               for unit in candidate_units(resume))


def first_draft_version(versions: list[dict]) -> dict | None:
    return next((v for v in versions if v["user_visible"] and has_experience_body(v["resume_data"])), None)


def usage_total(records: list[dict]) -> dict:
    counts = [record for record in records if record.get("usage")]
    keys = ("input_tokens", "output_tokens", "total_tokens")
    price_file = HERE / "pricing.json"
    pricing = json.loads(price_file.read_text()) if price_file.exists() else {}
    low = high = 0.0
    priced = 0
    for record in counts:
        rate = pricing.get("models", {}).get(record.get("model"))
        if not rate:
            continue
        priced += 1
        usage = record["usage"]
        low += (usage.get("input_tokens", 0) * rate["input_min"] + usage.get("output_tokens", 0) * rate["output_min"]) / 1_000_000
        high += (usage.get("input_tokens", 0) * rate["input_max"] + usage.get("output_tokens", 0) * rate["output_max"]) / 1_000_000
    return {**{key: sum(record["usage"].get(key, 0) or 0 for record in counts) for key in keys},
            "logical_model_calls": len(records), "calls_with_usage": len(counts),
            "calls_without_usage": len(records) - len(counts),
            "cost": None, "cost_status": "reported_tokens_range_only" if priced else "not_calculated",
            "reported_token_cost_usd": {"lower_bound": round(low, 6), "upper_bound": round(high, 6),
                                        "priced_calls": priced, "unpriced_calls": len(records) - priced,
                                        "source": pricing.get("source")} if priced else None,
            "sdk_http_attempts": None}


def transcript_text(case: dict, turns: list[dict]) -> str:
    label = "私有真实材料固定回放" if is_private(case) else "合成资料基线"
    lines = [f"# {case['id']} — {label}", "", f"Truth 审定状态：{case.get('truth_review_status', 'unknown')}；本次输出仍待 Claude 差异复核。", ""]
    for turn in turns:
        lines.extend([f"## 第 {turn['turn']} 轮 · {turn['phase']}", "", "### 用户", "", turn["user"],
                      "", "### Agent", "", turn.get("assistant") or "（没有公开回复）", "",
                      f"状态：{turn['status']}；stage={turn.get('stage', '')}；"
                      f"耗时 {turn['elapsed_seconds']} 秒；新增版本 {', '.join(turn.get('new_versions', [])) or '无'}", ""])
    return "\n".join(lines)


def review_call_ledger(meta: dict, scores: dict) -> list[dict]:
    """Recover metering after a crash between the score and meta writes."""
    result = []
    seen = set()
    rows = list(meta.get("judge_calls", []))
    for record in scores.get("versions", []) + scores.get("edits", []):
        rows.extend(record.get("review_calls", []))
        for old_calls in record.get("previous_review_calls", []):
            rows.extend(old_calls)
    for row in rows:
        identity = row.get("run_id")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        result.append(row)
    return result


async def rescore_case(case, judge_llm, counter_type, counter_context, args, output):
    """Retry only incomplete reviews from frozen artifacts, without another chat."""
    from judge import judge_version, judge_edit
    folder = output / case["id"]
    versions = json.loads((folder / "versions.json").read_text())
    edits = json.loads((folder / "edit-inputs.json").read_text())
    scores = json.loads((folder / "scores.json").read_text())
    meta = json.loads((folder / "meta.json").read_text())
    calls = []
    for kind, inputs, records in (("version", versions, scores["versions"]), ("edit", edits, scores["edits"])):
        for data, record in zip(inputs, records, strict=True):
            if record["score"]["status"] == "no_draft":
                continue
            if record["score"]["status"] == "completed" and not (kind == "version" and args.rejudge_versions):
                continue
            record.setdefault("previous_attempts", []).append(record["score"])
            if record.get("review_calls"):
                record.setdefault("previous_review_calls", []).append(record["review_calls"])
            counter = counter_type()
            token = counter_context.set(counter)
            try:
                async with asyncio.timeout(args.judge_timeout + 5):
                    if kind == "version":
                        score = await judge_version(case, data["resume_data"], judge_llm, observed_facts=data["observed_facts"],
                                                    disclosed_fact_indices=data.get("disclosed_fact_indices"))
                    else:
                        score = await judge_edit(case, data["before"], data["after"], data["instruction"], judge_llm,
                                                 observed_facts=data["observed_facts"])
            except Exception as exc:
                score = {"status": "error", "error_type": type(exc).__name__}
            finally:
                counter_context.reset(token)
            score["judge_code_sha256"] = hashlib.sha256((HERE / "judge.py").read_bytes()).hexdigest()
            record["score"] = score
            record["review_calls"] = counter.calls
            calls.extend(counter.calls)
            write_json(folder / "scores.json", scores)
            print(json.dumps({"case": case["id"], "rescore": data.get("version_id", data["turn"]),
                              "status": score["status"], "validation_error": score.get("validation_error")}), flush=True)
    meta["judge_calls"] = review_call_ledger(meta, scores)
    meta["judge_usage"] = usage_total(meta["judge_calls"])
    results = [r["score"] for r in scores["versions"] + scores["edits"]]
    complete = all(s["status"] in {"completed", "no_draft"} for s in results)
    meta["evaluation_status"] = "completed" if complete else "incomplete"
    if meta.get("graph_status", "completed") == "completed":
        meta["status"] = "completed" if complete else "evaluation_incomplete"
    write_json(folder / "meta.json", meta)
    return meta


async def run_case(case, llm, judge_llm, counter_type, counter_context, args, output, selector_llm=None):
    from app.agents.resume_graph import get_graph, stream_agent
    from app.services.conversation_store import create_conversation
    from app.services.session_store import load_resume_session, session_lock
    from judge import deterministic_score, judge_version, judge_edit

    if is_private(case):
        safe_output([case], output, "")
        if judge_llm is not None:
            raise ValueError("Private replay has no authorized independent semantic judge")
    folder = output / case["id"]
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "case.json", case)
    sid = create_conversation("private-benchmark" if is_private(case) else "synthetic-benchmark")["session_id"]
    graph = get_graph(llm)
    config = {"configurable": {"thread_id": sid}}
    recorder = VersionRecorder()
    turns: list[dict] = []
    observed: list[str] = []
    disclosed: set[int] = set()
    committed: dict = {}
    committed_context: dict = {}
    edit_inputs = []
    model_calls = []
    review_calls = []
    simulator_calls = []
    failed = False

    async def turn(text: str, phase: str, *, task="auto", simulation=None):
        nonlocal committed, committed_context, failed
        number = len(turns) + 1
        if phase != "jd":
            # Pass only material already shown to the graph, never future truth.
            observed.append(text)
            disclosed.update(index for index, fact in enumerate(case["truth_facts"]) if fact in text)
        record = {"turn": number, "phase": phase, "user": text, "task": task,
                  "simulation": simulation, "disclosed_fact_indices": sorted(disclosed),
                  "started_at": timestamp(), "status": "running"}
        counter = counter_type()
        token = counter_context.set(counter)
        started = time.monotonic()
        chunks = []
        before_ids = {v["version_id"] for v in recorder.versions}
        try:
            async with asyncio.timeout(args.turn_timeout):
                async with session_lock(sid):
                    async for chunk in stream_agent([{"role": "user", "content": text}], sid, llm, task=task):
                        chunks.append(chunk)
            record["status"] = "completed"
        except Exception as exc:
            record.update(status="error", error_type=type(exc).__name__)
            failed = True
        finally:
            counter_context.reset(token)
        record.update(assistant="".join(chunks), elapsed_seconds=round(time.monotonic() - started, 3),
                      model_calls=counter.calls, usage=usage_total(counter.calls))
        model_calls.extend(counter.calls)
        # Read actual durable checkpoints, including changes before a failed turn.
        try:
            history = [snap async for snap in graph.aget_state_history(config)]
            history.sort(key=lambda snap: (snap.metadata or {}).get("step", -1))
            for snap in history:
                checkpoint_id = snap.config["configurable"].get("checkpoint_id")
                if checkpoint_id in recorder.seen_checkpoints:
                    continue
                recorder.seen_checkpoints.add(checkpoint_id)
                if isinstance(snap.values.get("resume_data"), dict):
                    recorder.record(snap.values["resume_data"], turn=number,
                                    stage=snap.values.get("stage", ""), kind="internal",
                                    observed=observed, checkpoint_id=checkpoint_id,
                                    disclosed_fact_indices=sorted(disclosed))
            stored = load_resume_session(sid)
            committed = (stored or {}).get("resume_data") or {}
            stage = (stored or {}).get("stage", "")
            recorder.record(committed, turn=number, stage=stage, kind="committed", observed=observed,
                            disclosed_fact_indices=sorted(disclosed))
            record["stage"] = stage
            if is_private(case):
                current = history[-1].values if history else {}
                committed_context = {key: copy.deepcopy(current[key]) for key in
                                     ("session_constraints", "field_conflicts") if key in current}
                record["acceptance_context"] = copy.deepcopy(committed_context)
                for version in recorder.versions:
                    if version["turn"] == number:
                        version["acceptance_context"] = copy.deepcopy(committed_context)
        except Exception as exc:
            record.update(status="error", state_error_type=type(exc).__name__)
            failed = True
        record["new_versions"] = [v["version_id"] for v in recorder.versions if v["version_id"] not in before_ids]
        turns.append(record)
        write_json(folder / "turns.json", turns)
        write_json(folder / "versions.json", recorder.versions)
        (folder / "transcript.md").write_text(transcript_text(case, turns), encoding="utf-8")
        print(json.dumps({"case": case["id"], "turn": number, "phase": phase,
                          "status": record["status"], "versions": len(recorder.versions)}, ensure_ascii=False), flush=True)
        return record

    if case["jd_text"].strip():
        await turn(case["jd_text"], "jd", task="decode_jd")
    for index, opening in enumerate(case["opening_turns"]):
        if failed:
            break
        disclosed.update(case.get("opening_fact_indices", [[] for _ in case["opening_turns"]])[index])
        await turn(opening, "opening")
    for _ in range(followup_limit(case, args.max_followups)):
        if failed or not turns:
            break
        counter = counter_type()
        token = counter_context.set(counter)
        try:
            async with asyncio.timeout(args.selector_timeout + 5):
                answer = await select_answer(case, turns[-1]["assistant"], disclosed, selector_llm)
        except TimeoutError:
            answer = answer_question(case, turns[-1]["assistant"], disclosed)
            if answer:
                answer.update(selector_status="fallback", selector_error_type="TimeoutError")
        finally:
            counter_context.reset(token)
        simulator_calls.extend(counter.calls)
        if answer is not None:
            answer["model_calls"] = counter.calls
            answer["usage"] = usage_total(counter.calls)
        if answer is None:
            break
        disclosed.update(answer["fact_indices"])
        await turn(answer["text"], "followup", simulation=answer)
    for instruction in case["edit_instructions"]:
        if failed:
            break
        before = copy.deepcopy(committed)
        before_context = copy.deepcopy(committed_context)
        result = await turn(instruction, "edit")
        edit_inputs.append({"turn": result["turn"], "instruction": instruction, "before": before,
                            "after": copy.deepcopy(committed), "observed_facts": list(observed),
                            "turn_status": result["status"],
                            **({"before_context": before_context, "after_context": copy.deepcopy(committed_context)}
                               if is_private(case) else {})})
    write_json(folder / "resume.json", committed)

    scores = {"versions": [], "edits": [], "pairwise": {"status": "not_applicable_baseline_has_no_comparator"},
              "human_review": {"status": "pending_claude", "confirmed_new_facts": None}}
    # Scores are durable after each version, so interrupted reviews can resume.
    for version in recorder.versions:
        counter = counter_type()
        token = counter_context.set(counter)
        try:
            async with asyncio.timeout(args.judge_timeout + 5):
                score = await judge_version(case, version["resume_data"], judge_llm,
                                            observed_facts=version["observed_facts"],
                                            disclosed_fact_indices=version["disclosed_fact_indices"])
        except Exception as exc:
            score = {"status": "error", "error_type": type(exc).__name__,
                     "deterministic": deterministic_score(case, version["resume_data"], version["observed_facts"])}
        finally:
            counter_context.reset(token)
        score["judge_code_sha256"] = hashlib.sha256((HERE / "judge.py").read_bytes()).hexdigest()
        review_calls.extend(counter.calls)
        scores["versions"].append({"version_id": version["version_id"], "turn": version["turn"],
                                   "user_visible": version["user_visible"], "score": score, "review_calls": counter.calls})
        write_json(folder / "scores.json", scores)
        print(json.dumps({"case": case["id"], "judged_version": version["version_id"], "status": score["status"]}), flush=True)
    for edit in edit_inputs:
        counter = counter_type()
        token = counter_context.set(counter)
        try:
            async with asyncio.timeout(args.judge_timeout + 5):
                score = await judge_edit(case, edit["before"], edit["after"], edit["instruction"], judge_llm,
                                         observed_facts=edit["observed_facts"])
        except Exception as exc:
            score = {"status": "error", "error_type": type(exc).__name__}
        finally:
            counter_context.reset(token)
        score["judge_code_sha256"] = hashlib.sha256((HERE / "judge.py").read_bytes()).hexdigest()
        review_calls.extend(counter.calls)
        scores["edits"].append({"turn": edit["turn"], "instruction": edit["instruction"],
                                "turn_status": edit["turn_status"], "score": score, "review_calls": counter.calls})
        write_json(folder / "scores.json", scores)
    write_json(folder / "edit-inputs.json", edit_inputs)
    if is_private(case):
        # Golden reference is deliberately absent from every graph/model input.
        # Per-version rendered evidence stays beside the private frozen inputs.
        template_id = case.get("acceptance", {}).get("template_id", "t001-jianyue")
        rendered_cache = {}
        def render(data):
            key = digest(data)
            if key not in rendered_cache:
                rendered_cache[key] = measure_rendered_resume(data, template_id, page_limit=1,
                                                              pdf_path=folder / "rendered" / f"{key}.pdf")
            return rendered_cache[key]
        private_versions = [{"version_id": version["version_id"], "turn": version["turn"],
                             "user_visible": version["user_visible"],
                             "acceptance": evaluate_real01(version["resume_data"], rendered=render(version["resume_data"]),
                                                           context=version.get("acceptance_context"))}
                            for version in recorder.versions]
        private_edits = [{"turn": edit["turn"], **evaluate_edit(
            edit["before"], edit["after"], before_rendered=render(edit["before"]), rendered=render(edit["after"]),
            before_context=edit.get("before_context"), context=edit.get("after_context"), turn_status=edit["turn_status"])}
            for edit in edit_inputs]
        write_json(folder / "private-acceptance.json", {
            "case_id": case["id"], "status": "deterministic_only_pending_semantic_review",
            "golden_reference": case.get("golden_reference"),
            "versions": private_versions, "edits": private_edits,
            "final": evaluate_real01(committed, rendered=render(committed), context=committed_context)})
    draft_commits = [c for c in recorder.commits if c["stage"] in {"EVALUATING", "DRAFTED", "EXPORT"} and c["has_experience"]]
    first_draft = first_draft_version(recorder.versions)
    first_version = first_draft["version_id"] if first_draft else None
    score_results = [v["score"] for v in scores["versions"]] + [e["score"] for e in scores["edits"]]
    evaluation_complete = all(s["status"] in {"completed", "no_draft"} for s in score_results)
    meta = {"case_id": case["id"], "status": "graph_error" if failed else "completed",
            "graph_status": "error" if failed else "completed",
            "evaluation_status": "completed" if evaluation_complete else "incomplete",
            "truth_review_status": case.get("truth_review_status", "draft_pending_claude"),
            "turn_count": len(turns), "followup_count": sum(t["phase"] == "followup" for t in turns),
            "version_count": len(recorder.versions), "visible_version_count": sum(v["user_visible"] for v in recorder.versions),
            "first_draft_turn": first_draft["turn"] if first_draft else None,
            "first_draft_version": first_version, "commits": recorder.commits,
            "stage_first_draft_turn": draft_commits[0]["turn"] if draft_commits else None,
            "stage_first_draft_version": next((v["version_id"] for v in recorder.versions if draft_commits and v["hash"] == draft_commits[0]["hash"]), None),
            "final_has_body": has_experience_body(committed),
            "content_outcome": "has_experience_body" if has_experience_body(committed) else "empty_experience_body",
            "final_version": next((v["version_id"] for v in reversed(recorder.versions) if v["user_visible"]), None),
            "mean_turn_latency_seconds": round(statistics.mean(t["elapsed_seconds"] for t in turns), 3) if turns else None,
            "graph_usage": usage_total(model_calls), "judge_usage": usage_total(review_calls),
            "model_calls": model_calls, "judge_calls": review_calls,
            "simulator_calls": simulator_calls, "simulator_usage": usage_total(simulator_calls),
            "simulator_fallbacks": sum((t.get("simulation") or {}).get("selector_status") == "fallback" for t in turns),
            "guard_fallbacks": None, "guard_fallbacks_status": "not_instrumented_in_old_chain",
            "safety_gate": "pending_claude_review", "session_id": sid}
    if not failed and not evaluation_complete:
        meta["status"] = "evaluation_incomplete"
    write_json(folder / "meta.json", meta)
    write_json(folder / "scores.json", scores)
    return meta


async def run_live(cases, args, output, manifest):
    # All imports below happen only after isolate(). No live user stores opened.
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.tracers.context import register_configure_hook
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from app.config import get_settings
    from app.database import init_db, engine
    from app.agents.resume_graph import configure_checkpointer
    from app.services.conversation_store import checkpoint_owner
    from app.services.data_crypto import get_crypto
    from app.services.secure_checkpoint import SecureCheckpointSaver

    class Counter(BaseCallbackHandler):
        def __init__(self):
            self.calls = []
            self.runs = {}
        def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
            params = kwargs.get("invocation_params") or {}
            record = {"model": params.get("model_name") or params.get("model"), "status": "started",
                      "run_id": str(run_id), "started_at": timestamp()}
            self.runs[str(run_id)] = record
            self.calls.append(record)
        def on_llm_end(self, response, *, run_id, **kwargs):
            record = self.runs.get(str(run_id))
            if record is None:
                return
            record["status"] = "completed"
            usage = (response.llm_output or {}).get("token_usage") or {}
            if usage:
                record["usage"] = {"input_tokens": usage.get("prompt_tokens", 0),
                                   "output_tokens": usage.get("completion_tokens", 0),
                                   "total_tokens": usage.get("total_tokens", 0)}
            else:
                for group in response.generations:
                    for generation in group:
                        value = getattr(getattr(generation, "message", None), "usage_metadata", None)
                        if value:
                            record["usage"] = {key: value.get(key, 0) for key in ("input_tokens", "output_tokens", "total_tokens")}
                            return
        def on_llm_error(self, error, *, run_id, **kwargs):
            record = self.runs.get(str(run_id))
            if record is not None:
                record.update(status="error", error_type=type(error).__name__)

    context = ContextVar("tailor_bench_counter", default=None)
    register_configure_hook(context, inheritable=True)
    settings = get_settings()
    if not settings.LLM_API_KEY:
        raise RuntimeError("LLM credential is not configured")
    assert_private_model_policy(cases, args, settings)
    if not args.graph_only and args.judge_model in {settings.LLM_MODEL, settings.LLM_STRUCTURED_MODEL}:
        raise ValueError("Judge model must differ from both graph models")
    # Exactly mirrors the existing chat entry point. Do not tune the baseline.
    llm = ChatOpenAI(model=settings.LLM_MODEL, api_key=settings.LLM_API_KEY,
                     base_url=settings.LLM_BASE_URL, temperature=0.7, streaming=True)
    judge_llm = None if args.graph_only else ChatOpenAI(model=args.judge_model, api_key=settings.LLM_API_KEY,
                           base_url=settings.LLM_BASE_URL, temperature=0, timeout=args.judge_timeout,
                           max_retries=0, max_tokens=12000,
                           extra_body={"thinking": {"type": "enabled"}}, reasoning_effort="high")
    selector_llm = ChatOpenAI(model=settings.LLM_STRUCTURED_MODEL or settings.LLM_MODEL,
                              api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL,
                              temperature=0, streaming=False, timeout=args.selector_timeout,
                              max_retries=0, max_tokens=1024,
                              extra_body={"thinking": {"type": "disabled"}})
    if args.graph_only:
        judge_llm = None
    if args.rescore:
        manifest.setdefault("review_configs", []).append({"model": args.judge_model, "temperature": 0,
                                                          "reasoning_effort": "high", "concurrency": args.concurrency,
                                                          "timeout_seconds": args.judge_timeout,
                                                          "rejudge_versions": args.rejudge_versions})
    else:
        manifest.update(writer_model=settings.LLM_MODEL, structured_model=settings.LLM_STRUCTURED_MODEL,
                    judge_model=None if args.graph_only else args.judge_model, judge_temperature=0, judge_reasoning_effort="high",
                    graph_temperature=0.7, concurrency=args.concurrency,
                    max_followups=args.max_followups, turn_timeout_seconds=args.turn_timeout,
                    judge_timeout_seconds=args.judge_timeout,
                    simulator={"policy": "model_indices_deterministic_text_v2",
                               "model": settings.LLM_STRUCTURED_MODEL or settings.LLM_MODEL,
                               "temperature": 0, "max_tokens": 1024, "max_facts": 2,
                               "timeout_seconds": args.selector_timeout, "fallback": "keyword_then_negative_truth"},
                    logical_calls_not_http_retries=True,
                    isolation={"temporary_encrypted_application_db": True, "temporary_encrypted_checkpoints": True,
                               "real_user_database_accessed": False, "emails_sent": False, "rag_enabled": False,
                               "background_archivist_started": False, "web_tools_enabled": False})
    write_json(output / "manifest.json", manifest)
    init_db()
    semaphore = asyncio.Semaphore(args.concurrency)
    async def bounded(case):
        async with semaphore:
            try:
                if args.rescore:
                    return await rescore_case(case, judge_llm, Counter, context, args, output)
                return await run_case(case, llm, judge_llm, Counter, context, args, output, selector_llm)
            except Exception as exc:
                meta_path = output / case["id"] / "meta.json"
                result = json.loads(meta_path.read_text()) if args.rescore and meta_path.exists() else {"case_id": case["id"]}
                result.update(status="harness_error", error_type=type(exc).__name__)
                write_json(output / case["id"] / "meta.json", result)
                return result
    try:
        async with AsyncSqliteSaver.from_conn_string(settings.CHECKPOINT_DB_PATH) as saver:
            await saver.setup()
            configure_checkpointer(SecureCheckpointSaver(saver, get_crypto(), checkpoint_owner))
            results = await asyncio.gather(*(bounded(case) for case in cases))
            return results
    finally:
        configure_checkpointer(None)
        engine.dispose()


def summarize(output: Path, results: list[dict], manifest: dict) -> None:
    write_json(output / "summary.json", {"cases": results, "human_review_status": "pending_claude", "phase": "PR0"})
    from report import build_report
    build_report(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--include-private", action="store_true", help="Explicitly include gitignored cases-private fixtures")
    parser.add_argument("--cases-dir", type=Path, help="Explicit case directory; custom directories are classified private")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--concurrency", type=int, choices=range(1, 4), default=2)
    parser.add_argument("--max-followups", type=int, choices=range(5), default=4)
    parser.add_argument("--turn-timeout", type=float, default=150)
    parser.add_argument("--judge-timeout", type=float, default=120)
    parser.add_argument("--selector-timeout", type=float, default=60)
    parser.add_argument("--judge-model", default="deepseek-v4-pro")
    parser.add_argument("--graph-only", action="store_true", help="Capture chats first, leave semantic reviews explicitly incomplete")
    parser.add_argument("--rejudge-versions", action="store_true",
                        help="With --rescore, rejudge completed nonempty versions and retain every prior attempt")
    parser.add_argument("--rescore", type=Path, help="Review incomplete scores in frozen run artifacts, never rerun chats")
    args = parser.parse_args()
    if args.rejudge_versions and not args.rescore:
        parser.error("--rejudge-versions requires --rescore; never repeats graph conversations")
    if args.rescore and args.graph_only:
        parser.error("--rescore cannot be combined with --graph-only")
    if args.rescore and (args.cases_dir or args.include_private):
        parser.error("--rescore reads frozen cases; do not combine it with case-directory selection")
    cases = load_cases(cases_dir=args.cases_dir, include_private=args.include_private, rescore=args.rescore)
    if len({case['id'] for case in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    if args.case:
        if set(args.case) - {case['id'] for case in cases}:
            raise ValueError("Unknown case ID")
        cases = [case for case in cases if case["id"] in args.case]
    if not cases:
        raise ValueError("No cases found")
    private = any(is_private(case) for case in cases)
    output = safe_output(cases, args.rescore or args.output,
                         datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S") + "-baseline")
    if private and args.live and not args.graph_only:
        parser.error("Private cases currently require --graph-only; semantic review stays explicitly pending")
    if not args.live:
        print(json.dumps({"mode": "dry_run", "case_count": len(cases), "cases": [case['id'] for case in cases],
                          "max_followups": args.max_followups,
                          "fixed_two_turn_cases": [case['id'] for case in cases if is_private(case)],
                          "private": private, "output": str(output), "model_called": False}, ensure_ascii=False))
        return 0
    if not args.rescore and output.exists() and any(output.iterdir()):
        raise ValueError("Refusing to overwrite an existing run")
    if private:
        os.umask(0o077)
    output.mkdir(parents=True, exist_ok=True)
    manifest = (json.loads((output / "manifest.json").read_text()) if args.rescore else
                {**source_manifest(), "started_at": timestamp(), "case_hashes": {case['id']: digest(case) for case in cases},
                 "phase": "PR0", "scope": "private_fixed_replay" if private else "synthetic_old_stream_agent_baseline",
                 "private": private,
                 "private_case_ids": [case['id'] for case in cases if is_private(case)]})
    if args.rescore:
        manifest.pop("status", None)
        manifest.setdefault("rescore_attempts", []).append({"started_at": timestamp(), "cases": [c["id"] for c in cases],
                                                        "rejudge_versions": args.rejudge_versions})
    manifest.setdefault("harness_runs", []).append({"started_at": timestamp(), "phase": "rescore" if args.rescore else "graph",
                                                     "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                               for p in HERE.glob("*.py")}})
    write_json(output / "manifest.json", manifest)
    logging.basicConfig(level=logging.CRITICAL)
    results = []
    with tempfile.TemporaryDirectory(prefix="huhua-tailor-bench-") as directory:
        isolate(Path(directory))
        sys.path.insert(0, str(ROOT / "backend"))
        try:
            results = asyncio.run(run_live(cases, args, output, manifest))
        except Exception as exc:
            manifest.update(status="setup_error", error_type=type(exc).__name__)
    after = source_manifest()
    if args.rescore:
        # A targeted retry must not drop the other cases from the run report.
        results = [json.loads(path.read_text()) for path in sorted(output.glob("*/meta.json"))]
    manifest.update(finished_at=timestamp(), backend_unchanged=after["backend_tree_sha256"] == manifest["backend_tree_sha256"],
                    status=manifest.get("status", "completed" if len(results) == len(manifest["case_hashes"]) and all(r['status'] == 'completed' for r in results) else "partial"))
    write_json(output / "manifest.json", manifest)
    summarize(output, results, manifest)
    print(json.dumps({"status": manifest["status"], "output": str(output)}, ensure_ascii=False), flush=True)
    return 0 if manifest["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
