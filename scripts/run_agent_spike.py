"""Compare prescribed offline loops or explicitly requested real model decisions."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.orchestrator_spike import (  # noqa: E402
    FakeTools, OpenAIStreamModel, ScriptedModel, SYSTEM_PROMPT, TOOL_SCHEMAS, run_loop,
)
from app.services.model_privacy import ContactRedactor  # noqa: E402

DEFAULT_CASES = ROOT / "evaluation" / "agent-loop-spike" / "cases.json"


def assess(case: dict, result: dict) -> dict:
    expected = case["expectation"]
    sequence = result["requested_tool_sequence"]
    violations = []
    if sequence not in expected["accepted_sequences"]:
        violations.append("unexpected_tool_sequence")
    forbidden = set(sequence) & set(expected["forbidden_tools"])
    violations.extend(f"forbidden_tool:{name}" for name in sorted(forbidden))
    if result["status"] != "completed":
        violations.append(result["status"])
    if any(row["result"].get("status") == "error" for row in result["tools"]):
        violations.append("tool_error")
    for text in expected.get("forbidden_reply_fragments", []):
        if text in result["final_reply"]:
            violations.append("forbidden_reply_fragment")
    return {"matches_expectation": not violations, "violations": violations,
            "semantic_review": "pending", "review_points": expected["review_points"]}


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _tokens(usage: dict) -> str:
    return "/".join("N/A" if usage.get(key) is None else str(usage[key])
                    for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens"))


def write_report(directory: Path, report: dict) -> None:
    # Redact the serialized text too; reports must not persist contacts or raw CoT.
    safe = json.loads(ContactRedactor().redact(json.dumps(report, ensure_ascii=False)))
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "report.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = safe["metadata"]
    lines = [f"# Agent loop spike — {meta['mode']} / {meta['model_source']}", "",
             "stub 的工具决策、回复与 token 是脚本桩；耗时是本机桩开销，不能评价模型质量、速度或成本。"
             if meta["model_source"] == "stub" else
             "真实模型 + 模拟工具。自动结果只验证序列、状态与禁用项；产品语义仍需逐例人工复核。",
             "", f"完成且序列符合：{safe['summary']['matched']}/{safe['summary']['total']}；"
             f"工具预算 4；模型调用最多 5（含最终回复）。", "",
             "token 列为 prompt/completion/reasoning；reasoning 是 completion 的子集，不再次相加；"
             "N/A 表示供应商未报告，不能当作 0。", "",
             "| 场景 | 请求工具序列 | 符合期望 | 工具步 / 模型调用 | 总秒数 | token P/C/R | 回复摘要 |",
             "|---|---|---|---|---|---|---|"]
    for row in safe["cases"]:
        lines.append("| " + " | ".join(map(_cell, [
            row["id"], " → ".join(row["requested_tool_sequence"]) or "无",
            "是" if row["matches_expectation"] else "否：" + ", ".join(row["violations"]),
            f"{row['steps']} / {row['model_calls']}", f"{row['seconds']:.4f}",
            _tokens(row["usage"]), row["final_reply"][:180],
        ])) + " |")
    for row in safe["cases"]:
        lines.extend(["", f"## {row['id']} — {row['title']}", "",
                      f"状态：{row['status']}；语义复核：待人工。", "",
                      "| 模型调用 | 耗时（秒） | token P/C/R |", "|---|---|---|"])
        for turn in row["turns"]:
            lines.append(f"| {turn['turn']} | {turn['seconds']:.4f} | {_tokens(turn['usage'])} |")
        lines.extend(["", "| 工具步 | 工具 | 耗时（秒） | 结果状态 |", "|---|---|---|---|"])
        for tool in row["tools"]:
            lines.append(f"| {tool['step']} | {_cell(tool['name'])} | {tool['seconds']:.4f} | {_cell(tool['result'].get('status'))} |")
        lines.extend(["", "人工核对：" + "；".join(row["review_points"]), "",
                      "最终回复：" + row["final_reply"]])
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def real_config() -> dict:
    # Called only behind --real. Stub neither opens .env nor constructs an SDK client.
    from dotenv import dotenv_values
    values = dotenv_values(ROOT / "backend" / ".env")
    for key in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "LLM_CHAT_TEMPERATURE", "LLM_TEMPERATURE", "LLM_MAX_TOKENS"):
        if key in os.environ:
            values[key] = os.environ[key]
    if not values.get("LLM_API_KEY") or not values.get("LLM_MODEL") or not values.get("LLM_BASE_URL"):
        raise ValueError("--real requires LLM_API_KEY, LLM_MODEL and LLM_BASE_URL")
    if not (values["LLM_MODEL"].lower().startswith(("deepseek", "vanchin/deepseek"))
            or urlsplit(values["LLM_BASE_URL"]).hostname == "api.deepseek.com"):
        raise ValueError("this spike requires a DeepSeek model/endpoint")
    return {"api_key": values["LLM_API_KEY"], "base_url": values["LLM_BASE_URL"], "model": values["LLM_MODEL"],
            "temperature": float(values.get("LLM_CHAT_TEMPERATURE") or values.get("LLM_TEMPERATURE") or 0.7),
            "max_tokens": int(values["LLM_MAX_TOKENS"]) if values.get("LLM_MAX_TOKENS") else None}


async def evaluate(args) -> int:
    payload = args.cases.read_bytes()
    cases = json.loads(payload)["cases"]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("cases must have unique IDs and be nonempty")
    directory = args.output_root / (args.name or datetime.now().strftime(f"%Y%m%d-%H%M%S-%f-{args.mode}-{'real' if args.real else 'stub'}"))
    if directory.exists():
        raise ValueError("run directory exists; choose a new --name")
    client, real_model = None, None
    metadata = {"mode": args.mode, "model_source": "real" if args.real else "stub", "tools": "fake",
                "created_at": datetime.now().astimezone().isoformat(),
                "cases_sha256": hashlib.sha256(payload).hexdigest(),
                "prompt_schema_sha256": hashlib.sha256((SYSTEM_PROMPT + json.dumps(TOOL_SCHEMAS, ensure_ascii=False)).encode()).hexdigest(),
                "versions": {name: version(name) for name in ("openai", "langchain-openai")},
                "token_source": "provider" if args.real else "scripted_fixture", "max_tool_steps": 4}
    if args.real:
        from openai import AsyncOpenAI
        config = real_config()
        client = AsyncOpenAI(api_key=config["api_key"], base_url=config["base_url"], max_retries=0, timeout=args.timeout)
        real_model = OpenAIStreamModel(client, model=config["model"], temperature=config["temperature"], max_tokens=config["max_tokens"])
        metadata.update({"model": config["model"], "endpoint_host": urlsplit(config["base_url"]).hostname,
                         "temperature_off": config["temperature"], "max_tokens": config["max_tokens"]})
    rows = []
    try:
        for case in cases:
            model = real_model if args.real else ScriptedModel(case["stub_script"])
            tools = FakeTools(case["user_message"], state=case.get("state"), results=case.get("tool_results"))
            result = await run_loop(model, tools, user_message=case["user_message"],
                                    history_summary=case["history_summary"], mode=args.mode, timeout=args.timeout)
            row = {"id": case["id"], "title": case["title"], **result, **assess(case, result)}
            rows.append(row)
            print(f"{case['id']}: {'PASS' if row['matches_expectation'] else 'FAIL'} "
                  f"tools={','.join(row['requested_tool_sequence']) or '-'} steps={row['steps']} "
                  f"calls={row['model_calls']} seconds={row['seconds']:.4f} tokens={_tokens(row['usage'])}")
            for turn in row["turns"]:
                print(f"  model {turn['turn']}: {turn['seconds']:.4f}s tokens={_tokens(turn['usage'])}")
            for tool in row["tools"]:
                print(f"  tool {tool['step']} {tool['name']}: {tool['seconds']:.4f}s {tool['result'].get('status')}")
            print("  reply: " + row["final_reply"][:180].replace("\n", " "))
    finally:
        if client is not None:
            await client.close()
    report = {"metadata": metadata, "cases": rows,
              "summary": {"total": len(rows), "matched": sum(row["matches_expectation"] for row in rows),
                          "semantic_quality": "not_measured_by_stub" if args.stub else "pending_human_review"}}
    write_report(directory, report)
    print(f"Report: {directory / 'report.md'}")
    return 0 if report["summary"]["matched"] == len(rows) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("off", "thinking"), required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--real", action="store_true")
    source.add_argument("--stub", action="store_true")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_CASES.parent / "runs")
    parser.add_argument("--name")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.name and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.name):
        parser.error("--name must be a plain run name")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        return asyncio.run(evaluate(args))
    except Exception as exc:
        # No traceback/provider error text or configuration values in artifacts/logs.
        print(f"Spike failed before report completion: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
