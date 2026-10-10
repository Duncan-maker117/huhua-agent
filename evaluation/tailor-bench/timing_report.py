#!/usr/bin/env python3
"""Per-turn model-call timing table for a tailor-bench run directory.

Usage: timing_report.py RUN_DIR [--case CASE_ID]

RUN_DIR is either a run folder holding one sub-folder per case, or a single case
folder with turns.json. Calls whose time spans overlap are marked with the same
letter in the "par" column (they ran in parallel). Runs recorded before call
labels existed show "?" and, lacking durations, cannot be checked for overlap.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys


def parse(value):
    return datetime.fromisoformat(value) if value else None


def call_span(call):
    start = parse(call.get("started_at"))
    end = parse(call.get("ended_at"))
    if end is None and start is not None and call.get("duration_ms") is not None:
        end = start + timedelta(milliseconds=call["duration_ms"])
    return start, end


def overlap_groups(spans):
    """Letters for calls that overlap in time with at least one other call."""
    known = [(i, s, e) for i, (s, e) in enumerate(spans) if s is not None and e is not None]
    parent = {i: i for i, _, _ in known}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, (i, s1, e1) in enumerate(known):
        for j, s2, e2 in known[a + 1:]:
            if s1 < e2 and s2 < e1:
                parent[find(i)] = find(j)
    members = {}
    for i, _, _ in known:
        members.setdefault(find(i), []).append(i)
    letters = {}
    for n, group in enumerate(g for g in members.values() if len(g) > 1):
        for i in group:
            letters[i] = chr(ord("A") + n % 26)
    return letters


def fmt(value, width, spec=""):
    return f"{value:{spec}}".rjust(width) if value is not None else "-".rjust(width)


def turn_table(turn):
    calls = turn.get("model_calls") or []
    origin = parse(turn.get("started_at"))
    spans = [call_span(c) for c in calls]
    letters = overlap_groups(spans)
    lines = [f"turn {turn.get('turn')} [{turn.get('phase')}] total {turn.get('elapsed_seconds')}s, "
             f"{len(calls)} calls, status {turn.get('status')}"]
    header = f"  {'#':>2} {'label':<24} {'start+s':>8} {'dur s':>7} {'in tok':>7} {'out tok':>7} {'think':>6} {'par':>3}  status"
    lines.append(header)
    for index, call in enumerate(calls):
        start, end = spans[index]
        offset = (start - origin).total_seconds() if start and origin else None
        duration = call.get("duration_ms")
        duration = duration / 1000 if duration is not None else (
            (end - start).total_seconds() if start and end else None)
        usage = call.get("usage") or {}
        lines.append(f"  {index + 1:>2} {str(call.get('label', '?')):<24} {fmt(offset, 8, '.2f')} "
                     f"{fmt(duration, 7, '.2f')} {fmt(usage.get('input_tokens'), 7)} "
                     f"{fmt(usage.get('output_tokens'), 7)} {fmt(call.get('reasoning_tokens'), 6)} "
                     f"{letters.get(index, ''):>3}  {call.get('status', '')}")
    if letters:
        pairs = sorted({letter for letter in letters.values()})
        lines.append("  parallel groups: " + ", ".join(
            f"{letter}=" + "+".join(str(calls[i].get("label", "?")) for i, l in letters.items() if l == letter)
            for letter in pairs))
    done = sorted((s, e) for s, e in spans if s is not None and e is not None)
    if origin and done:
        busy = sum((e - s).total_seconds() for s, e in done)
        union, (cur_s, cur_e) = 0.0, done[0]
        for s, e in done[1:]:
            if s > cur_e:
                union += (cur_e - cur_s).total_seconds()
                cur_s, cur_e = s, e
            else:
                cur_e = max(cur_e, e)
        union += (cur_e - cur_s).total_seconds()
        lines.append(f"  summed call time {busy:.2f}s, time with a call in flight {union:.2f}s "
                     f"(saved by overlap {busy - union:.2f}s)")
    return lines


def case_folders(path: Path, only: str | None):
    if (path / "turns.json").is_file():
        return [path]
    folders = sorted(p for p in path.iterdir() if (p / "turns.json").is_file())
    return [p for p in folders if only is None or p.name == only]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--case")
    args = parser.parse_args(argv)
    folders = case_folders(args.run_dir, args.case)
    if not folders:
        print(f"no turns.json under {args.run_dir}", file=sys.stderr)
        return 1
    for folder in folders:
        turns = json.loads((folder / "turns.json").read_text())
        print(f"== {folder.name}")
        for turn in turns:
            print("\n".join(turn_table(turn)))
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
