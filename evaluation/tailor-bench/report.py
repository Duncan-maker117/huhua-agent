"""Build a fail-closed PR0 report from frozen run artifacts, without model calls.

The report never turns an AI judgment into a human safety confirmation. Missing
cases, edits and reviews stay in the denominators and are reported explicitly.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import statistics
from typing import Any


QUALITY_DIMENSIONS = (
    "jd_relevance", "personal_contribution", "results_impact",
    "professional_expression", "selection_length",
)
_spec = importlib.util.spec_from_file_location("_tailor_report_judge", Path(__file__).with_name("judge.py"))
_judge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_judge)


def _read(path: Path, default: Any, problems: list[str]) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, type(default)):
            raise ValueError("wrong artifact type")
        return value
    except (OSError, ValueError):
        problems.append(path.name)
        return default


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _requirements(case: dict) -> list[str]:
    return [f"{item.get('id', '')} {item.get('text', '')}" if isinstance(item, dict) else str(item)
            for item in case.get("must_cover", [])]


def _quality(score: dict) -> dict | None:
    value = score.get("quality")
    if (score.get("status") == "completed" and isinstance(value, dict)
            and set(value) == set(QUALITY_DIMENSIONS)
            and all(type(value[key]) is int and 1 <= value[key] <= 5 for key in QUALITY_DIMENSIONS)):
        return value
    return None


def _has_experience_body(resume: dict) -> bool:
    """Use renderer-visible bullets/description, not merely a project name."""
    return any(re.match(r"^(?:projects|work_experience|internship)\[\d+\]\.bullets\[", unit["path"])
               for unit in _judge.candidate_units(resume))


def _version_status(score: dict, version: dict, requirements: list[str]) -> str:
    status = score.get("status", "missing")
    has_content = bool(_judge.candidate_units(version.get("resume_data")))
    if status == "no_draft":
        return "invalid_no_draft" if has_content else status
    if status != "completed":
        return status
    coverage = score.get("coverage") or {}
    rows = coverage.get("requirements")
    factuality = score.get("factuality") or {}
    audits = factuality.get("audits")
    deterministic = score.get("deterministic") or {}
    if (_quality(score) is None or not isinstance(rows, list)
            or len(rows) != len(requirements)
            or Counter(row.get("requirement") for row in rows if isinstance(row, dict)) != Counter(requirements)
            or not all(isinstance(row, dict) and type(row.get("evidence_supported")) is bool for row in rows)
            or deterministic.get("status") != "completed" or not isinstance(deterministic.get("flags"), list)
            or factuality.get("status") != "pending_human_review"
            or not isinstance(audits, list)
            or len(audits) != len(_judge.candidate_units(version.get("resume_data")))):
        return "invalid_completed_score"
    return status


def _sum_usage(values: list[dict | None]) -> dict:
    present = [value for value in values if isinstance(value, dict) and value]
    result = {"cases_with_usage": len(present), "cases_missing_usage": len(values) - len(present),
              "actual_cost_usd": None, "sdk_http_attempts": None}
    for field in ("input_tokens", "output_tokens", "total_tokens", "logical_model_calls",
                  "calls_with_usage", "calls_without_usage"):
        known = [value[field] for value in present if type(value.get(field)) in (int, float)]
        result[field] = sum(known) if known else None
        result[f"{field}_complete"] = len(known) == len(values) and bool(values)
    ranges = [value["reported_token_cost_usd"] for value in present
              if isinstance(value.get("reported_token_cost_usd"), dict)]
    valid_ranges = [value for value in ranges
                    if type(value.get("lower_bound")) in (int, float)
                    and type(value.get("upper_bound")) in (int, float)]
    result["reported_token_cost_usd"] = ({
        "lower_bound": round(sum(value["lower_bound"] for value in valid_ranges), 6),
        "upper_bound": round(sum(value["upper_bound"] for value in valid_ranges), 6),
        "priced_calls": sum(value.get("priced_calls", 0) for value in valid_ranges),
        "unpriced_calls": sum(value.get("unpriced_calls", 0) for value in valid_ranges),
        "cases_with_range": len(valid_ranges),
        "cases_without_range": len(values) - len(valid_ranges),
        "sources": list(dict.fromkeys(str(value["source"]) for value in valid_ranges if value.get("source"))),
        "status": "reported_token_estimate_not_invoice",
    } if valid_ranges else None)
    return result


def _edit_rows(case: dict, scores: dict, turns: list[dict], expected: int) -> list[dict]:
    instructions = case.get("edit_instructions", [])
    score_rows = scores.get("edits", [])
    edit_turns = [turn for turn in turns if turn.get("phase") == "edit"]
    result = []
    for index in range(expected):
        instruction = instructions[index] if index < len(instructions) else None
        matches = [row for row in score_rows if instruction is not None and row.get("instruction") == instruction]
        record = matches[0] if len(matches) == 1 else (score_rows[index] if index < len(score_rows) else {})
        turn = next((row for row in edit_turns if row.get("turn") == record.get("turn")),
                    edit_turns[index] if index < len(edit_turns) else {})
        score = record.get("score") or {}
        status = score.get("status", "missing")
        turn_status = record.get("turn_status") or turn.get("status")
        # A failed graph turn cannot earn edit credit even if a draft was saved.
        if turn_status == "error" or status == "error":
            category = "error"
        elif not record and not turn:
            category = "not_run"
        elif status in {"not_run", "missing"}:
            category = "not_run" if not turn else "unscored"
        elif status == "no_draft":
            category = "no_draft"
        elif status == "completed" and score.get("substantive_diff") is False:
            category = "no_diff"
        elif (status == "completed" and score.get("substantive_diff") is True
              and score.get("followed") is True and score.get("executed") is True
              and turn_status == "completed"):
            category = "executed"
        elif status == "completed" and score.get("followed") is False:
            category = "not_followed"
        else:
            category = "uncertain"
        result.append({"edit_index": index + 1, "instruction": instruction,
                       "turn": record.get("turn", turn.get("turn")), "turn_status": turn_status,
                       "score_status": status, "category": category,
                       "substantive_diff": score.get("substantive_diff"),
                       "followed": score.get("followed"), "executed": category == "executed",
                       "reason": score.get("reason"), "error_type": score.get("error_type")})
    return result


def _case_report(folder: Path, queue: list[dict]) -> dict:
    problems: list[str] = []
    case = _read(folder / "case.json", {}, problems)
    meta = _read(folder / "meta.json", {}, problems)
    scores = _read(folder / "scores.json", {}, problems)
    versions = _read(folder / "versions.json", [], problems)
    turns = _read(folder / "turns.json", [], problems)
    cid = folder.name
    requirements = _requirements(case)
    # Manifest-reserved PR0 cases must not disappear while a run is incomplete.
    requirement_count = len(requirements) if requirements else 2
    expected_edits = len(case.get("edit_instructions", [])) or 2
    links = {name: f"{cid}/{name}" for name in ("case.json", "meta.json", "scores.json", "versions.json", "turns.json", "transcript.md", "resume.json")}
    truth_status = meta.get("truth_review_status") or case.get("truth_review_status") or "draft_pending_claude"
    queue.append({"kind": "truth_review", "case_id": cid, "review_status": "pending_claude",
                  "truth_review_status": truth_status, "source": links["case.json"]})
    indexed_scores = {row.get("version_id"): row.get("score") or {} for row in scores.get("versions", [])}
    version_rows = []
    for version in versions:
        vid = version.get("version_id")
        score = indexed_scores.get(vid, {})
        status = _version_status(score, version, requirements)
        visible = version.get("user_visible") is True
        deterministic = score.get("deterministic") or {}
        lexical = deterministic.get("flags") or []
        factuality = score.get("factuality") or {}
        # Unvalidated provider output is deliberately excluded from evidence.
        semantic = factuality.get("suspicions", []) if status == "completed" else []
        audits = factuality.get("audits", []) if status == "completed" else []
        entry = {"version_id": vid, "turn": version.get("turn"), "stage": version.get("stage"),
                 "user_visible": visible, "score_status": status,
                 "has_displayed_content": bool(_judge.candidate_units(version.get("resume_data"))),
                 "has_experience_body": _has_experience_body(version.get("resume_data") or {}),
                 "lexical_status": deterministic.get("status", "missing"),
                 "lexical_flags": len(lexical),
                 "semantic_status": "completed_pending_claude" if status == "completed" else factuality.get("status", "missing"),
                 "semantic_suspicions": len(semantic),
                 "semantic_verdicts": dict(Counter(row.get("verdict", "unknown") for row in audits)),
                 "quality": _quality(score) if status == "completed" else None,
                 "coverage": score.get("coverage") if status == "completed" else None,
                 "error_type": score.get("error_type"), "validation_error": score.get("validation_error")}
        version_rows.append(entry)
        location = {"case_id": cid, "version_id": vid, "turn": version.get("turn"),
                    "user_visible": visible, "review_status": "pending_claude",
                    "source": links["scores.json"], "resume_source": links["versions.json"]}
        if entry["has_displayed_content"]:
            queue.append({**location, "kind": "version_review", "score_status": status,
                          "reason": "逐版事实仍需人工复核，模型通过不等于人工确认。"})
        for flag in lexical:
            queue.append({**location, "kind": "lexical", "finding": flag})
        for suspicion in semantic:
            queue.append({**location, "kind": "semantic", "finding": suspicion})
        if status not in {"completed", "no_draft"}:
            queue.append({**location, "kind": "evaluation_incomplete", "score_status": status,
                          "error_type": score.get("error_type"), "validation_error": score.get("validation_error")})

    by_id = {row["version_id"]: row for row in version_rows}
    first_id = meta.get("first_draft_version")
    # Do not filter COLLECTING: an unchanged draft can first be acknowledged later.
    first = by_id.get(first_id)
    first_visible = next((row for row in version_rows if row["user_visible"] and row["has_experience_body"]), None)
    final_id = meta.get("final_version")
    if not final_id:
        final_id = next((row["version_id"] for row in reversed(version_rows) if row["user_visible"]), None)
    final = by_id.get(final_id)
    has_visible_content = bool(final and final["user_visible"] and final["has_displayed_content"])
    graph_status = meta.get("graph_status")
    if any(turn.get("status") == "error" for turn in turns) or meta.get("status") in {"graph_error", "harness_error"}:
        graph_status = "error"
    elif graph_status is None:
        graph_status = "unknown"
    run_attempted = bool(meta or turns or versions)
    coverage = {"total": requirement_count, "covered": 0, "known_uncovered": 0, "unknown": requirement_count,
                "status": "unknown", "ratio": None}
    if not has_visible_content and run_attempted and graph_status in {"completed", "error"}:
        coverage.update(known_uncovered=requirement_count, unknown=0, status="no_draft", ratio=0.0)
    elif has_visible_content and final["score_status"] == "completed" and requirements:
        covered = sum(row.get("evidence_supported") is True for row in final["coverage"]["requirements"])
        coverage.update(covered=covered, known_uncovered=requirement_count - covered, unknown=0,
                        status="model_scored_pending_claude", ratio=_ratio(covered, requirement_count))
    edits = _edit_rows(case, scores, turns, expected_edits)
    edit_counts = Counter(row["category"] for row in edits)
    evaluation_complete = (not any(name in problems for name in ("case.json", "scores.json", "versions.json"))
                           and all(row["score_status"] in {"completed", "no_draft"} for row in version_rows)
                           and all(row["score_status"] in {"completed", "no_draft"} for row in edits)
                           and len(indexed_scores) == len(version_rows))
    if meta.get("evaluation_status") == "incomplete":
        evaluation_complete = False
    failures = []
    if graph_status != "completed":
        failures.append("graph_failed" if graph_status == "error" else "graph_incomplete")
    if not evaluation_complete:
        failures.append("evaluation_incomplete")
    if not has_visible_content:
        failures.append("no_visible_draft" if run_attempted else "case_not_run")
    elif first_visible is None:
        failures.append("no_visible_experience_body")
    if meta.get("first_draft_turn") is None:
        failures.append("no_completed_first_draft")
    elif meta["first_draft_turn"] > 2:
        failures.append("first_draft_over_2_turns")
    if edit_counts["executed"] < expected_edits:
        failures.append("edit_not_executed")
    if coverage["ratio"] is not None and coverage["ratio"] < 0.8:
        failures.append("coverage_below_80_percent")
    elif coverage["unknown"]:
        failures.append("coverage_unknown")
    if first_id and first is None:
        failures.append("first_draft_score_reference_missing")
    if meta.get("final_version") and final is None:
        failures.append("final_score_reference_missing")
    return {"case_id": cid, "role_family": case.get("role_family"), "truth_review_status": truth_status,
            "graph_status": graph_status, "evaluation_status": "completed" if evaluation_complete else "incomplete",
            "artifact_problems": problems, "denominator_source": "case" if requirements else "pr0_expected_two_per_missing_case",
            "first_draft_turn": meta.get("first_draft_turn"), "first_draft_version": first_id,
            "formal_first_quality": first.get("quality") if first else None,
            "formal_first_score_status": first["score_status"] if first else "no_draft" if meta else "unknown",
            "first_visible_experience_version": first_visible["version_id"] if first_visible else None,
            "first_visible_experience_turn": first_visible["turn"] if first_visible else None,
            "first_quality": first_visible.get("quality") if first_visible else None,
            "first_score_status": first_visible["score_status"] if first_visible else "no_visible_experience" if meta else "unknown",
            "final_version": final_id, "final_quality": final.get("quality") if final else None,
            "final_score_status": final["score_status"] if final else "no_draft" if run_attempted else "unknown",
            "has_visible_content": has_visible_content, "final_coverage": coverage,
            "expected_edits": expected_edits, "edits": edits, "edit_counts": dict(edit_counts),
            "versions": version_rows, "version_count": len(version_rows),
            "visible_version_count": sum(row["user_visible"] for row in version_rows),
            "internal_only_version_count": sum(not row["user_visible"] for row in version_rows),
            "turn_count": len(turns), "turn_latencies_seconds": [turn["elapsed_seconds"] for turn in turns if type(turn.get("elapsed_seconds")) in (int, float)],
            "graph_usage": meta.get("graph_usage"), "judge_usage": meta.get("judge_usage"),
            "guard_fallbacks": meta.get("guard_fallbacks"),
            "guard_fallbacks_status": meta.get("guard_fallbacks_status", "not_observed"),
            "failures": failures, "links": links}


def _quality_summary(cases: list[dict], key: str) -> dict:
    values = [case[key] for case in cases if case[key] is not None]
    return {"scored_cases": len(values), "missing_cases": len(cases) - len(values),
            "means": {dimension: round(statistics.mean(value[dimension] for value in values), 3) if values else None
                      for dimension in QUALITY_DIMENSIONS}}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _percent(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1%}"


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _quality_text(value: dict | None, status: str) -> str:
    return "/".join(str(value[key]) for key in QUALITY_DIMENSIONS) if value else f"— ({status})"


def _usage_text(value: dict) -> str:
    tokens = value.get("total_tokens")
    suffix = "" if value.get("total_tokens_complete") else "（已记录部分）"
    return "unknown" if tokens is None else f"{tokens:,}{suffix}"


def _render(aggregate: dict) -> str:
    run, totals = aggregate["run"], aggregate["totals"]
    coverage, edits, facts = totals["coverage"], totals["edits"], totals["facts"]
    lines = ["# Tailor PR0 · 旧链路逐版本基线", "",
             f"运行：{_cell(run.get('started_at', 'unknown'))}；源码快照 `{_cell(run.get('git_commit', 'unknown'))}`。",
             f"写作模型 `{_cell(run.get('writer_model', 'unknown'))}`；评审模型 `{_cell(run.get('judge_model', 'unknown'))}`。", "",
             f"本报告状态：**{aggregate['status']}**。{totals['cases']} 个合成用例，"
             f"{totals['versions']} 个变化版本（可见 {totals['visible_versions']}，仅内部 {totals['internal_only_versions']}）。",
             "所有 truth 与事实疑点均待 Claude 审定。确认新增事实为 **null（未知）**，事实安全门槛尚未通过；模型无疑点也不等于复核确认。", "",
             "## 总体指标", "", "| 指标 | 结果 | 解释 |", "|---|---|---|",
             f"| 最终稿要求覆盖 | {coverage['covered']}/{coverage['total']} = {_percent(coverage['observed_lower_bound'])} | 已验证评审结果的 observed lower bound；已知未覆盖 {coverage['known_uncovered']}，未知 {coverage['unknown']}。不是人工确认覆盖率。 |",
             f"| 编辑执行 | {edits['executed']}/{edits['expected']} = {_percent(edits['observed_lower_bound'])} | 使用全部计划编辑作为分母；无 diff {edits['no_diff']}，错误 {edits['error']}，未运行 {edits['not_run']}，未评分 {edits['unscored']}，无稿 {edits['no_draft']}，未遵循 {edits['not_followed']}，不确定 {edits['uncertain']}。 |",
             f"| 首稿 ≤ 2 个用户轮（进入成稿 stage） | {totals['first_draft']['within_two_turns']}/{totals['cases']} | 有正式首稿 {totals['first_draft']['drafted_cases']}；反映旧状态机，仅凭它不能断言用户此前看不到正文。JD 消息计入用户轮数。 |",
             f"| 首次可见经历正文 ≤ 2 轮 | {totals['first_visible_experience']['within_two_turns']}/{totals['cases']} | 有可见经历正文 {totals['first_visible_experience']['drafted_cases']}；要求经历 bullet/description 有实文，只有名称不计。 |",
             f"| 逐版本评分 | {totals['version_score_statuses']} | 任一缺失/错误/未运行仍为评估不完整；no_draft 不代表质量或安全通过。 |",
             f"| 词法疑点 | {facts['lexical_flags']} | 可见 {facts['visible_lexical_flags']}，仅内部 {facts['internal_lexical_flags']}；独立于语义疑点计数，可能重叠。 |",
             f"| 语义疑点 | {facts['semantic_suspicions']} | 可见 {facts['visible_semantic_suspicions']}，仅内部 {facts['internal_semantic_suspicions']}；{facts['semantic_completed_versions']} 个版本完成模型语义评分，仍待人工。 |",
             f"| 平均轮延迟 | {totals['latency']['mean_seconds'] if totals['latency']['mean_seconds'] is not None else 'unknown'} 秒 | 基于 {totals['latency']['observed_turns']} 个实际记录轮，非按用例平均值二次平均。 |",
             f"| Graph / Judge tokens | {_usage_text(totals['usage']['graph'])} / {_usage_text(totals['usage']['judge'])} | 仅报告 SDK 已记录 token；HTTP 重试次数未知。 |",
             "| Pairwise 新版胜率 | N/A | 旧链路基线没有新版对手，不计算胜率。 |",
             "| Guard 回退 / 误杀 | 未观测 | 旧链路无新语义 guard，不能伪记为零。 |", "",
             "无最终可见正文的已运行用例覆盖记 0；有正文但评分缺失的要求记 unknown。即使 first_draft_turn 尚为空，已可见的 COLLECTING 版本也保留逐版评分和终稿覆盖，另列未完成首稿。",
             "覆盖和编辑比例在评分未齐时只是已观测下界，不得用于宣称通过门槛。", "",
             "## 每例首稿与终稿", "",
             "五维顺序：JD 相关性 / 个人贡献 / 结果产出 / 专业表达 / 取舍篇幅，各 1–5 分。首稿质量取首次可见经历正文版本；进入成稿 stage 的 first_draft_version 及其质量另存 aggregate.json，指向 COLLECTING 时也不丢失。", "",
             "| 用例 | Graph / 评估 | 首次可见正文五维 | 终稿五维 | 最终覆盖 | 编辑执行 | 首次正文轮 / 正式成稿轮 | 版本：可见/仅内部 |",
             "|---|---|---|---|---|---|---|---|"]
    for case in aggregate["cases"]:
        cov = case["final_coverage"]
        cov_text = f"{cov['covered']}/{cov['total']}" if not cov["unknown"] else f"unknown ({cov['unknown']}/{cov['total']})"
        lines.append(f"| [{case['case_id']}]({case['links']['transcript.md']}) | {case['graph_status']} / {case['evaluation_status']} | "
                     f"{_quality_text(case['first_quality'], case['first_score_status'])} | {_quality_text(case['final_quality'], case['final_score_status'])} | "
                     f"{cov_text} | {case['edit_counts'].get('executed', 0)}/{case['expected_edits']} | {case['first_visible_experience_turn'] or '无正文'} / {case['first_draft_turn'] or '未成稿'} | "
                     f"{case['visible_version_count']}/{case['internal_only_version_count']} |")
    lines.extend(["", "五维均分仅针对成功评分用例，不给未评分/无稿填零，也不删除它们在覆盖与编辑指标中的分母。", "",
                  "| 质量位置 | 有效用例 / 全部 | 五维均分 |", "|---|---|---|"])
    for position in ("first", "final"):
        value = totals["quality"][position]
        means = "/".join(str(value["means"][key]) if value["means"][key] is not None else "unknown" for key in QUALITY_DIMENSIONS)
        lines.append(f"| {position} | {value['scored_cases']}/{totals['cases']} | {means} |")
    lines.extend(["", "## 逐版本评分清单", "",
                  "| 用例 / 版本 | 轮 / stage | 可见性 | 评分 | 词法状态 / 疑点 | 语义状态 / 疑点 |", "|---|---|---|---|---|---|"])
    for case in aggregate["cases"]:
        if not case["versions"]:
            lines.append(f"| {case['case_id']} / — | — | — | 没有版本 | 未观测 | 未观测 |")
        for row in case["versions"]:
            label = f"{case['case_id']} / {row['version_id']}"
            lines.append(f"| [{label}]({case['links']['scores.json']}) | {row['turn']} / {_cell(row['stage'])} | "
                         f"{'用户可见' if row['user_visible'] else '仅内部'} | {row['score_status']} | "
                         f"{row['lexical_status']} / {row['lexical_flags']} | {row['semantic_status']} / {row['semantic_suspicions']} |")
    lines.extend(["", "## 失败与未知项", ""])
    for case in aggregate["cases"]:
        if case["failures"]:
            lines.append(f"- [{case['case_id']}]({case['links']['meta.json']}): {', '.join(case['failures'])}。"
                         f"编辑分类 {case['edit_counts']}。")
    if not aggregate["failures"]:
        lines.append("没有记录到产品/执行指标失败；事实安全和 truth 审定仍待 Claude，不宣称全部验收通过。")
    lines.extend(["", "## 用量与费用", "", "费用区间只覆盖记录到 token 且有费率的调用，不是账单；缺少价格或使用量不填零。", ""])
    for kind in ("graph", "judge"):
        usage = totals["usage"][kind]
        cost = usage["reported_token_cost_usd"]
        if cost:
            lines.append(f"- {kind}: 已记录 token 估算 USD {cost['lower_bound']:.6f}–{cost['upper_bound']:.6f}；"
                         f"有价格调用 {cost['priced_calls']}，区间记录内未定价调用 {cost['unpriced_calls']}，"
                         f"无费用区间用例 {cost['cases_without_range']}。费率来源保存在 [aggregate.json](aggregate.json)。")
        else:
            lines.append(f"- {kind}: 费用 unknown；有用量记录 {usage['cases_with_usage']} 个用例，缺失 {usage['cases_missing_usage']} 个。")
    if aggregate.get("limitations"):
        lines.extend(["", "## 本次运行的已知限制", ""])
        lines.extend("- " + note for note in aggregate["limitations"])
    lines.extend(["", "## Claude 复核入口", "",
                  f"- [review-queue.json](review-queue.json)：{aggregate['review_queue_count']} 项待审任务，包含 truth、每版人工复核、词法和语义疑点及评估未完成项。",
                  "- [aggregate.json](aggregate.json)：完整分母、unknown、编辑分类、逐版状态和使用量汇总。",
                  "- [manifest.json](manifest.json)：源码、模型与隔离配置。先审 truth，再阅读每例 transcript / versions / scores。",
                  "- AI 标注没有转成确认新增事实；不允许把 reviewed/passed 的模型状态充当 Claude 人工确认。PR1 未开始。", ""])
    return "\n".join(lines)


def build_report(output: Path) -> dict:
    """Write detailed-summary.md, review-queue.json and aggregate.json; return aggregate."""
    output = Path(output)
    problems: list[str] = []
    manifest = _read(output / "manifest.json", {}, problems)
    reserved = set((manifest.get("case_hashes") or {}).keys())
    found = {path.parent.name for path in output.glob("*/case.json")}
    case_ids = sorted(reserved | found)
    queue: list[dict] = []
    cases = [_case_report(output / cid, queue) for cid in case_ids]
    versions = [row for case in cases for row in case["versions"]]
    edit_counts = Counter(row["category"] for case in cases for row in case["edits"])
    covered = sum(case["final_coverage"]["covered"] for case in cases)
    known_uncovered = sum(case["final_coverage"]["known_uncovered"] for case in cases)
    unknown = sum(case["final_coverage"]["unknown"] for case in cases)
    requirements_total = sum(case["final_coverage"]["total"] for case in cases)
    edits_total = sum(case["expected_edits"] for case in cases)
    drafted = [case["first_draft_turn"] for case in cases if type(case["first_draft_turn"]) is int]
    visible_drafted = [case["first_visible_experience_turn"] for case in cases if type(case["first_visible_experience_turn"]) is int]
    latencies = [value for case in cases for value in case["turn_latencies_seconds"]]
    total_facts = {
        "confirmed_new_facts": None, "safe": None, "status": "pending_claude_review",
        "lexical_flags": sum(row["lexical_flags"] for row in versions),
        "lexical_statuses": dict(Counter(row["lexical_status"] for row in versions)),
        "semantic_suspicions": sum(row["semantic_suspicions"] for row in versions),
        "semantic_completed_versions": sum(row["score_status"] == "completed" for row in versions),
        "semantic_unscored_content_versions": sum(row["has_displayed_content"] and row["score_status"] != "completed" for row in versions),
        "semantic_statuses": dict(Counter(row["semantic_status"] for row in versions)),
        "semantic_verdicts": dict(sum((Counter(row["semantic_verdicts"]) for row in versions), Counter())),
    }
    for visibility, visible in (("visible", True), ("internal", False)):
        total_facts[f"{visibility}_lexical_flags"] = sum(row["lexical_flags"] for row in versions if row["user_visible"] == visible)
        total_facts[f"{visibility}_semantic_suspicions"] = sum(row["semantic_suspicions"] for row in versions if row["user_visible"] == visible)
    complete = bool(cases) and not problems and all(case["graph_status"] == "completed" and case["evaluation_status"] == "completed" for case in cases)
    aggregate = {
        "report_version": 1, "status": "evaluated_pending_claude" if complete else "incomplete",
        "run": {key: manifest.get(key) for key in ("started_at", "finished_at", "git_commit", "git_branch", "writer_model", "structured_model", "judge_model", "status", "backend_unchanged")},
        "manifest_problems": problems, "truth_review_status": "pending_claude",
        "limitations": manifest.get("limitations", []),
        "pairwise": {"status": "not_applicable_baseline_has_no_comparator", "win_rate": None},
        "totals": {
            "cases": len(cases), "versions": len(versions),
            "visible_versions": sum(row["user_visible"] for row in versions),
            "internal_only_versions": sum(not row["user_visible"] for row in versions),
            "version_score_statuses": dict(Counter(row["score_status"] for row in versions)),
            "graph_statuses": dict(Counter(case["graph_status"] for case in cases)),
            "evaluation_statuses": dict(Counter(case["evaluation_status"] for case in cases)),
            "facts": total_facts,
            "coverage": {"total": requirements_total, "covered": covered, "known_uncovered": known_uncovered,
                         "unknown": unknown, "observed_lower_bound": _ratio(covered, requirements_total),
                         "possible_upper_bound": _ratio(covered + unknown, requirements_total),
                         "status": "complete_model_scores_pending_claude" if not unknown and cases else "incomplete_observed_lower_bound",
                         "human_confirmed_covered": None},
            "edits": {"expected": edits_total, **{key: edit_counts[key] for key in ("executed", "no_diff", "error", "not_run", "unscored", "no_draft", "not_followed", "uncertain")},
                      "observed_lower_bound": _ratio(edit_counts["executed"], edits_total)},
            "quality": {"dimensions": list(QUALITY_DIMENSIONS), "first": _quality_summary(cases, "first_quality"), "final": _quality_summary(cases, "final_quality")},
            "first_draft": {"drafted_cases": len(drafted), "missing_cases": len(cases) - len(drafted),
                            "within_two_turns": sum(value <= 2 for value in drafted),
                            "mean_turns_drafted_cases_only": round(statistics.mean(drafted), 3) if drafted else None},
            "first_visible_experience": {"drafted_cases": len(visible_drafted), "missing_cases": len(cases) - len(visible_drafted),
                                         "within_two_turns": sum(value <= 2 for value in visible_drafted),
                                         "mean_turns_drafted_cases_only": round(statistics.mean(visible_drafted), 3) if visible_drafted else None},
            "latency": {"observed_turns": len(latencies), "mean_seconds": round(statistics.mean(latencies), 3) if latencies else None},
            "usage": {kind: _sum_usage([case.get(f"{kind}_usage") for case in cases]) for kind in ("graph", "judge")},
            "guard": {"fallbacks": None, "false_positive_rate": None, "status": "not_observed_in_old_chain"},
        },
        "failures": [{"case_id": case["case_id"], "reasons": case["failures"], "source": case["links"]["meta.json"]} for case in cases if case["failures"]],
        "cases": cases, "review_queue_count": len(queue),
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "aggregate.json", aggregate)
    _write_json(output / "review-queue.json", {"status": "pending_claude", "confirmed_new_facts": None, "items": queue})
    rendered = _render(aggregate)
    (output / "detailed-summary.md").write_text(rendered, encoding="utf-8")
    (output / "summary.md").write_text(rendered, encoding="utf-8")
    return aggregate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build_report(args.output)
    print(json.dumps({"status": result["status"], "cases": result["totals"]["cases"], "review_queue_count": result["review_queue_count"]}))
