#!/usr/bin/env python3
"""Re-evaluate and tabulate one or more frozen runs, without model calls."""
import argparse
from importlib import import_module
import json
from pathlib import Path
from statistics import mean, median
import sys

HERE = Path(__file__).resolve().parent
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / 'backend'))
checks = import_module("evaluation.persona-ux.checks")
loop_checks = import_module("evaluation.persona-ux.loop_checks")
metrics = import_module("evaluation.persona-ux.metrics")


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


def measured(values):
    known = [v for v in values if metrics.number(v) is not None]
    return (f'{mean(known):.3f} / {max(known):.3f} ({len(known)}/{len(values)})'
            if known else f'N/A (0/{len(values)})')


def token_cell(usage):
    return ' / '.join('N/A' if usage.get(key) is None else str(usage[key]) for key in metrics.TOKEN_FIELDS)


def comparison_tables(runs, indexes):
    lines = ['', '## 两模式与人物对比', '',
             '通过率按当前检查器重评，未改写旧产物；两模式总断言数不同，另列共同断言。',
             '耗时/调用为平均 / 最大（已记录轮数/总轮数）；总秒含 SSE 与 canonical 回读，编排秒包含工具执行。',
             '编排 token 仅含编排 SDK，不含工具内部模型；P/C/R/H = prompt/completion/reasoning/cache-hit。缺失保留 N/A，不能当作 0。',
             '旧版 HTTP 计数若全为 0，不能据此认定没有模型调用或隐私检查已覆盖；需新回放核对。', '',
             '| 人物 | Run / 模式 | 通过/总数（率） | 共同断言 | 未过项 | 每轮总秒 均/最大 | 编排秒 均/最大 | 编排调用 均/最大 | 编排 token P/C/R/H | 单次 prompt 中位/最大 |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    personas = list(dict.fromkeys(p for run in runs for p in run['personas']))
    for persona in ['合计', *personas]:
        selected = [{key: row for key, row in index.items() if persona == '合计' or key.startswith(persona + '.')}
                    for index in indexes]
        shared = set.intersection(*(set(rows) for rows in selected))
        for run, rows in zip(runs, selected):
            label = cell(run.get('run_id', 'run') + ' / ' + run.get('agent_mode', 'off') +
                         ('' if run.get('agent_mode_verified') else '（未核对）'))
            if not rows:
                lines.append(f'| {persona} | {label} | MISSING | N/A | MISSING | N/A | N/A | N/A | N/A | N/A |')
                continue
            turns = [turn for name, record in run['personas'].items() if persona == '合计' or name == persona
                     for turn in record.get('turns', [])]
            orch = [metrics.orchestrator(t.get('orchestrator')) for t in turns]
            known = [o for o in orch if o is not None]
            usage = {key: metrics.complete_sum([o['usage'][key] for o in known]) for key in metrics.TOKEN_FIELDS}
            prompts = [c['usage']['prompt_tokens'] for o in known for c in o['turns']]
            prompt_values = [p for p in prompts if p is not None]
            prompt_stats = (f'{median(prompt_values):g} / {max(prompt_values):g} ({len(prompt_values)}/{len(prompts)})'
                            if prompt_values else 'N/A')
            passed = sum(row['status'] == 'pass' for row in rows.values())
            common = f"{sum(rows[key]['status'] == 'pass' for key in shared)}/{len(shared)}" if shared else 'N/A'
            failed = '、'.join(key.removeprefix(persona + '.') for key, row in rows.items() if row['status'] != 'pass') or '—'
            if persona == '合计':
                failed = f'{len(rows) - passed} 项（下表分人物）'
            lines.append(f'| {persona} | {label} | {passed}/{len(rows)} ({passed / len(rows):.1%}) | {common} | {cell(failed)} | ' +
                         ' | '.join([measured([t.get('elapsed_seconds') for t in turns]),
                                     measured([o.get('seconds') if o else None for o in orch]),
                                     measured([o.get('model_calls') if o else None for o in orch]),
                                     token_cell(usage), prompt_stats]) + ' |')
    return lines


def comparison_warnings(runs):
    lines = []
    if any(len({run.get(key) for run in runs}) > 1 for key in (
            'fixture_sha256', 'loop_fixture_sha256', 'aipm_fixture_sha256', 'aipm_real_fixture_sha256', 'returning_fixture_sha256')) or len({run.get('with_recovery', False) for run in runs}) > 1:
        lines += ['', '注意：fixtures 哈希或 recovery 设置不同，对比不是同脚本修复前后验收。']
    if len({tuple(sorted(run['personas'])) for run in runs}) > 1:
        lines += ['', '注意：人物选择不同；MISSING 表示未覆盖，不计为通过。']
    return lines


def render_comparison(runs):
    if len(runs) != 2:
        raise ValueError('Exactly two runs are required')
    return '\n'.join(['# 人物回放对比', *comparison_warnings(runs),
                      *comparison_tables(runs, [result_index(run) for run in runs])]) + '\n'


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
    lines += comparison_warnings(runs)
    lines += comparison_tables(runs, indexes)
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
            lines += ["| Run | 人物/轮次 | 模型HTTP调用 | 服务端秒 | SSE秒 | 总秒 | 编排调用 | 编排秒 | 编排 token P/C/R/H |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
            for number, turn in enumerate(record.get('turns') or [], 1):
                values = [turn.get(key) for key in ('model_calls', 'server_seconds', 'stream_seconds', 'elapsed_seconds')]
                orch = metrics.orchestrator(turn.get('orchestrator')) or {}
                values += [orch.get('model_calls'), orch.get('seconds')]
                lines.append(f"| {cell(label)} | {persona}/{number}:{cell(turn.get('action'))} | " + ' | '.join('N/A' if v is None else str(v) for v in values) + f" | {token_cell(orch.get('usage', {}))} |")
            calls = [(i, j, c) for i, t in enumerate(record.get('turns') or [], 1)
                     for j, c in enumerate((metrics.orchestrator(t.get('orchestrator')) or {}).get('turns', []), 1)]
            if calls:
                lines += ['', '| 轮次/编排请求 | 思考模式 | 请求秒 | token P/C/R/H |', '| --- | --- | ---: | --- |']
                for i, j, call in calls:
                    lines.append(f"| {i}/{j} | {call['mode'] or 'N/A'} | {call['seconds'] if call['seconds'] is not None else 'N/A'} | {token_cell(call['usage'])} |")
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
