#!/usr/bin/env python3
"""Re-evaluate and tabulate one or more frozen runs, without model calls."""
import argparse
from importlib import import_module
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / 'backend'))
checks = import_module("evaluation.persona-ux.checks")
loop_checks = import_module("evaluation.persona-ux.loop_checks")


def load_run(path):
    path = Path(path)
    if path.is_dir():
        path = path / "run.json"
    run = json.loads(path.read_text(encoding="utf-8"))
    if run.get("schema_version") != 1 or not isinstance(run.get("personas"), dict):
        raise ValueError("Not a persona replay schema_version=1 run")
    return run


def cell(value):
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def result_index(run):
    result = {}
    for persona, record in run['personas'].items():
        evaluator = loop_checks if persona in loop_checks.FIXTURES else (
            import_module(f'evaluation.persona-ux.{persona}') if persona in {'aipm', 'aipm_real', 'returning'} else checks)
        turns = record.get('turns') or []
        rows = evaluator.evaluate_persona(persona, turns, with_recovery=run.get('with_recovery', False))
        if run.get('agent_mode') == 'loop':
            rows += loop_checks.evaluate_loop(persona, turns)
        for row in rows:
            result[row['id']] = {**row, 'label': row.get('label', row.get('title', row['id']))}
    for persona, record in run["personas"].items():
        if record.get("error"):
            row = result[f"{persona}.common.rounds_complete"]
            row["status"] = "fail"
            row["evidence"].append(checks.evidence({}, "error", record["error"]))
    return result


def render_report(runs):
    if not runs:
        raise ValueError("At least one run is required")
    indexes = [result_index(run) for run in runs]
    labels = [run.get("run_id", f"run-{i + 1}") for i, run in enumerate(runs)]
    title = "人物 API 回放验收" if any(set(run['personas']) - set(checks.PERSONAS) for run in runs) else "五人物 API 回放验收"
    lines = ["# " + title, "", "仅对已保存的 API 数据做确定性断言；PASS 不代表语言质量或真实用户效果。", "",
             "| Run | Agent模式 | 人物 | 聊天请求 | 耗时（秒） | PASS / FAIL |", "| --- | --- | --- | ---: | ---: | --- |"]
    for run, label, index in zip(runs, labels, indexes):
        passed = sum(row["status"] == "pass" for row in index.values())
        mode = run.get('agent_mode', 'off') + ('' if run.get('agent_mode_verified') else '（未核对）')
        lines.append(f"| {cell(label)} | {cell(mode)} | {cell(', '.join(run['personas']))} | {run.get('stream_requests', '未记录')} | {run.get('elapsed_seconds', '未记录')} | {passed} / {len(index) - passed} |")
    if any(len({run.get(key) for run in runs}) > 1 for key in (
            "fixture_sha256", "loop_fixture_sha256", "aipm_fixture_sha256", "aipm_real_fixture_sha256", "returning_fixture_sha256")) or len({run.get("with_recovery", False) for run in runs}) > 1:
        lines += ["", "注意：fixtures 哈希或 recovery 设置不同，对比不是同脚本修复前后验收。"]
    if len({tuple(sorted(run["personas"])) for run in runs}) > 1:
        lines += ["", "注意：人物选择不同；MISSING 表示未覆盖，不计为通过。"]
    ids = list(dict.fromkeys(id_ for index in indexes for id_ in index))
    lines += ["", "| 断言 | 完成条件 | " + " | ".join(cell(label) for label in labels) + " | 首次→末次 | 证据（末次；缺失时取最近一次） |",
              "| --- | --- | " + " | ".join("---" for _ in runs) + " | --- | --- |"]
    for id_ in ids:
        available = [index[id_] for index in indexes if id_ in index]
        row = available[-1]
        statuses = [index.get(id_, {}).get("status", "missing") for index in indexes]
        first, last = statuses[0], statuses[-1]
        change = "不变" if first == last else "改善" if (first, last) == ("fail", "pass") else "退化" if (first, last) == ("pass", "fail") else "新增" if first == "missing" else "缺失"
        proof = "；".join(f"{e.get('action')}/{e.get('field')}: {e.get('excerpt')}" for e in row.get("evidence", [])[:2])
        lines.append(f"| {cell(id_)} | {cell(row['label'])} | " + " | ".join(s.upper() for s in statuses) + f" | {change} | {cell(proof)} |")
    lines += ["", "## 逐轮调用与耗时", "", "模型调用数是服务端观测到的模型 HTTP 尝试数，含编排、工具内部调用与重试；不含轮次外后台归档。N/A 表示缺证据，不能当作0。"]
    for run, label in zip(runs, labels):
        for persona, record in run['personas'].items():
            stats = loop_checks.observations(record.get('turns') or [])
            lines += [f"\n{cell(label)}/{persona}：首稿总轮次={stats['first_draft_turn'] or 'N/A'}；从具体材料起={stats['turns_from_material'] or 'N/A'}；联系方式索要轮次={stats['contact_request_turns']}。\n"]
            lines += ["| Run | 人物/轮次 | 模型调用 | 服务端秒 | SSE秒 | 总秒 |", "| --- | --- | ---: | ---: | ---: | ---: |"]
            for number, turn in enumerate(record.get('turns') or [], 1):
                values = [turn.get(key) for key in ('model_calls', 'server_seconds', 'stream_seconds', 'elapsed_seconds')]
                lines.append(f"| {cell(label)} | {persona}/{number}:{cell(turn.get('action'))} | " + ' | '.join('N/A' if v is None else str(v) for v in values) + ' |')
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path, help="run directories or run.json files, oldest first")
    parser.add_argument("--output", type=Path, help="Markdown path under evaluation/persona-ux/")
    args = parser.parse_args(argv)
    if args.output and not args.output.resolve().is_relative_to(HERE.resolve()):
        parser.error("--output 必须位于 evaluation/persona-ux/ 下")
    try:
        report = render_report([load_run(path) for path in args.runs])
    except (OSError, ValueError) as error:
        parser.error(type(error).__name__)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
