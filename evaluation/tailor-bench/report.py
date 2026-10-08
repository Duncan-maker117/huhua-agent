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
            for item in (case.get("requirements") or case.get("must_cover", []))]


def _positive_requirements(case: dict) -> list[dict]:
    if case.get("requirements"):
        return [row for row in case["requirements"] if row.get("expected_status") != "gap"]
    return [{"id": str(row).split(" ", 1)[0], "text": str(row), "evidence_fact_indices": []}
            for row in case.get("must_cover", [])]


def _coverage_summary(case: dict, raw: dict, mode: str, *, completed: bool,
                      no_draft: bool, disclosed: list[int] | None) -> dict:
    """Preserve both denominators, including N/A and missing evaluations."""
    positive = _positive_requirements(case)
    planned_total = len(positive) or 2
    group = raw.get(f"coverage_of_{mode}") or {}
    indices = set(disclosed or [])
    has_fact_plan = bool(positive) and all(row.get("evidence_fact_indices") for row in positive)
    applicable = positive
    if mode == "disclosed" and has_fact_plan and disclosed is not None:
        applicable = [row for row in positive if indices.intersection(row["evidence_fact_indices"])]
    total = len(applicable) if has_fact_plan and (mode == "truth" or disclosed is not None) else planned_total
    if type(group.get("total")) is int and 0 <= group["total"] <= planned_total:
        total = group["total"]
    fact_total = None
    if has_fact_plan and (mode == "truth" or disclosed is not None):
        fact_total = sum(len(row["evidence_fact_indices"]) if mode == "truth"
                         else len(indices.intersection(row["evidence_fact_indices"])) for row in applicable)
    if type(group.get("fact_total")) is int:
        fact_total = group["fact_total"]
    result = {"total": total, "covered": 0, "known_uncovered": 0, "unknown": total,
              "not_applicable": planned_total - total, "status": "unknown", "ratio": None,
              "fact_total": fact_total, "fact_covered": 0, "fact_unknown": fact_total,
              "fact_ratio": None, "applicability_unknown": mode == "disclosed" and not group and disclosed is None}
    if no_draft:
        result.update(known_uncovered=total, unknown=0, status="no_draft", ratio=_ratio(0, total),
                      fact_unknown=0 if fact_total is not None else None, fact_ratio=_ratio(0, fact_total or 0))
    elif completed:
        covered = group.get("covered")
        if not group:  # Frozen v1 artifacts retain the previous single-coverage contract.
            covered = sum(row.get("evidence_supported") is True for row in raw.get("requirements", [])
                          if row.get("expected_status") != "gap")
        if type(covered) is int and 0 <= covered <= total:
            result.update(covered=covered, known_uncovered=total - covered, unknown=0,
                          status="model_scored_pending_claude", ratio=_ratio(covered, total))
        fact_covered = group.get("fact_covered")
        if type(fact_covered) is int and fact_total is not None and 0 <= fact_covered <= fact_total:
            result.update(fact_covered=fact_covered, fact_unknown=0, fact_ratio=_ratio(fact_covered, fact_total))
    if not total:
        result.update(status="not_applicable", unknown=0)
    return result


def _aggregate_coverage(cases: list[dict], key: str) -> dict:
    rows = [case[key] for case in cases]
    total, covered, unknown = (sum(row[key] for row in rows) for key in ("total", "covered", "unknown"))
    fact_rows = [row for row in rows if row.get("fact_total") is not None]
    facts_total = sum(row["fact_total"] for row in fact_rows)
    facts_covered = sum(row["fact_covered"] for row in fact_rows)
    return {"total": total, "covered": covered, "known_uncovered": sum(row["known_uncovered"] for row in rows),
            "unknown": unknown, "not_applicable": sum(row["not_applicable"] for row in rows),
            "observed_lower_bound": _ratio(covered, total), "possible_upper_bound": _ratio(covered + unknown, total),
            "status": "complete_model_scores_pending_claude" if not unknown and cases else "incomplete_observed_lower_bound",
            "human_confirmed_covered": None, "fact_total": facts_total if fact_rows else None,
            "fact_covered": facts_covered if fact_rows else None,
            "fact_unknown": sum(row["fact_unknown"] or 0 for row in fact_rows) if fact_rows else None,
            "fact_observed_lower_bound": _ratio(facts_covered, facts_total),
            "cases_without_fact_denominator": len(rows) - len(fact_rows)}


def _product_observations(case: dict, version: dict | None, checks: list[dict], disclosed: list[int] | None) -> dict:
    data = (version or {}).get("resume_data") or {}
    units = _judge.candidate_units(data)
    bodies = [unit["text"] for unit in units
              if re.match(r"^(?:projects|work_experience|internship)\[\d+\]\.bullets\[", unit["path"])]
    def normalize(value):
        return re.sub(r"[\s，,。.;；:：!?！？、\"“”'‘’]+", "", value)
    body_keys = [normalize(text) for text in bodies if len(normalize(text)) >= 6]
    sentences = [normalize(sentence) for text in bodies for sentence in re.split(r"[。！？;；\n]+", text)
                 if len(normalize(sentence)) >= 6]
    sources = [normalize(text) for text in (version or {}).get("observed_facts", [])]
    disclosed_education = [row for row in case.get("disclosed_education", [])
                           if row["fact_index"] in set(disclosed or [])]
    return {"has_experience_body": bool(bodies), "body_unit_count": len(bodies),
            "self_evaluation_assertions": [unit["text"] for unit in _judge.assertion_units(data)
                                           if unit["path"] == "self_evaluation"],
            "title_errors": [row for row in checks if row.get("kind") == "project_title_mismatch"],
            "duplicate_projects": [row for row in checks if row.get("kind") == "duplicate_project"],
            "education_checks": [row for row in checks if row.get("kind") in {"education_missing", "education_field_missing"}],
            "education_disclosed": bool(disclosed_education),
            "education_present": any(unit["path"].startswith("education[") for unit in units),
            "first_person_body_units": sum("我" in text for text in bodies),
            "verbatim_body_units": sum(any(text in source for source in sources) for text in body_keys),
            "duplicate_body_units": sum(count - 1 for count in Counter(body_keys).values() if count > 1),
            "duplicate_sentences": sum(count - 1 for count in Counter(sentences).values() if count > 1)}


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
            or not all(isinstance(row, dict) and (row.get("expected_status") == "gap"
                                                 or type(row.get("evidence_supported")) is bool) for row in rows)
            or deterministic.get("status") != "completed" or not isinstance(deterministic.get("flags"), list)
            or factuality.get("status") != "pending_human_review"
            or not isinstance(audits, list)
            or len(audits) != len(_judge.candidate_units(version.get("resume_data")))):
        return "invalid_completed_score"
    if any(row.get("expected_status") for row in rows) or "coverage_of_truth" in coverage or "coverage_of_disclosed" in coverage:
        for mode in ("truth", "disclosed"):
            group = coverage.get(f"coverage_of_{mode}")
            if (not isinstance(group, dict)
                    or not all(type(group.get(key)) is int for key in ("covered", "total", "fact_covered", "fact_total"))
                    or not 0 <= group["covered"] <= group["total"]
                    or not 0 <= group["fact_covered"] <= group["fact_total"]):
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
    expected_edits = len(case.get("edit_instructions", [])) or 2
    links = {name: f"{cid}/{name}" for name in ("case.json", "meta.json", "scores.json", "versions.json", "turns.json", "transcript.md", "resume.json")}
    truth_status = meta.get("truth_review_status") or case.get("truth_review_status") or "draft_pending_claude"
    if truth_status != "approved_by_claude":
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
        unverifiable = factuality.get("unverifiable_units", []) if status == "completed" else []
        quality_checks = score.get("quality_checks", [])
        entry = {"version_id": vid, "turn": version.get("turn"), "stage": version.get("stage"),
                 "user_visible": visible, "score_status": status,
                 "has_displayed_content": bool(_judge.candidate_units(version.get("resume_data"))),
                 "has_experience_body": _has_experience_body(version.get("resume_data") or {}),
                 "lexical_status": deterministic.get("status", "missing"),
                 "lexical_flags": len(lexical),
                 "semantic_status": "completed_pending_claude" if status == "completed" else factuality.get("status", "missing"),
                 "semantic_suspicions": len(semantic),
                 "unverifiable_units": len(unverifiable), "quality_checks": quality_checks,
                 "semantic_verdicts": dict(Counter(row.get("verdict", "unknown") for row in audits)),
                 "quality": _quality(score) if status == "completed" else None,
                 "coverage": score.get("coverage"),
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
        for item in unverifiable:
            queue.append({**location, "kind": "unverifiable_unit", "finding": item})
        for item in quality_checks:
            queue.append({**location, "kind": "quality_check", "finding": item})
        if status not in {"completed", "no_draft"}:
            queue.append({**location, "kind": "evaluation_incomplete", "score_status": status,
                          "error_type": score.get("error_type"), "validation_error": score.get("validation_error")})

    by_id = {row["version_id"]: row for row in version_rows}
    first_id = meta.get("stage_first_draft_version", meta.get("first_draft_version"))
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
    final_raw = next((row for row in versions if row.get("version_id") == final_id), None)
    disclosed = final_raw.get("disclosed_fact_indices") if final_raw else None
    raw_coverage = (final or {}).get("coverage") or {}
    no_draft = not has_visible_content and run_attempted and graph_status in {"completed", "error"}
    coverage_args = {"completed": bool(final and final["score_status"] == "completed"),
                     "no_draft": no_draft, "disclosed": disclosed}
    coverage = _coverage_summary(case, raw_coverage, "truth", **coverage_args)
    disclosed_coverage = _coverage_summary(case, raw_coverage, "disclosed", **coverage_args)
    observations = _product_observations(case, final_raw, (final or {}).get("quality_checks", []), disclosed)
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
    if first_visible is None:
        failures.append("no_first_draft")
    elif first_visible["turn"] > 2:
        failures.append("first_draft_over_2_turns")
    if edit_counts["executed"] < expected_edits:
        failures.append("edit_not_executed")
    if coverage["ratio"] is not None and coverage["ratio"] < 0.8:
        failures.append("coverage_below_80_percent")
    elif coverage["unknown"]:
        failures.append("coverage_unknown")
    if meta.get("final_version") and final is None:
        failures.append("final_score_reference_missing")
    return {"case_id": cid, "role_family": case.get("role_family"), "truth_review_status": truth_status,
            "graph_status": graph_status, "evaluation_status": "completed" if evaluation_complete else "incomplete",
            "artifact_problems": problems, "denominator_source": "case" if requirements else "pr0_expected_two_per_missing_case",
            "first_draft_turn": first_visible["turn"] if first_visible else None,
            "first_draft_version": first_visible["version_id"] if first_visible else None,
            "diagnostic_stage_first_draft_turn": meta.get("stage_first_draft_turn", meta.get("first_draft_turn")),
            "diagnostic_stage_first_draft_version": first_id,
            "formal_first_quality": first.get("quality") if first else None,
            "formal_first_score_status": first["score_status"] if first else "no_draft" if meta else "unknown",
            "first_visible_experience_version": first_visible["version_id"] if first_visible else None,
            "first_visible_experience_turn": first_visible["turn"] if first_visible else None,
            "first_quality": first_visible.get("quality") if first_visible else None,
            "first_score_status": first_visible["score_status"] if first_visible else "no_visible_experience" if meta else "unknown",
            "final_version": final_id, "final_quality": final.get("quality") if final else None,
            "final_score_status": final["score_status"] if final else "no_draft" if run_attempted else "unknown",
            "has_visible_content": has_visible_content, "final_coverage": coverage,
            "final_coverage_of_truth": coverage, "final_coverage_of_disclosed": disclosed_coverage,
            "product_observations": observations,
            "gap_requirements": [row for row in case.get("requirements", []) if row.get("expected_status") == "gap"],
            "expected_edits": expected_edits, "edits": edits, "edit_counts": dict(edit_counts),
            "versions": version_rows, "version_count": len(version_rows),
            "visible_version_count": sum(row["user_visible"] for row in version_rows),
            "internal_only_version_count": sum(not row["user_visible"] for row in version_rows),
            "turn_count": len(turns), "turn_latencies_seconds": [turn["elapsed_seconds"] for turn in turns if type(turn.get("elapsed_seconds")) in (int, float)],
            "graph_usage": meta.get("graph_usage"), "judge_usage": meta.get("judge_usage"),
            "simulator_usage": meta.get("simulator_usage"), "simulator_fallbacks": meta.get("simulator_fallbacks"),
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
    truth, disclosed = totals["coverage_of_truth"], totals["coverage_of_disclosed"]
    edits, facts, product = totals["edits"], totals["facts"], totals["product_findings"]
    truth_label = "合成 truth 已获 Claude 审定" if aggregate["truth_review_status"] == "approved_by_claude" else "合成 truth 仍待 Claude 审定"
    lines = ["# Tailor PR0 · 旧链路逐版本基线", "",
             f"运行：{_cell(run.get('started_at', 'unknown'))}；源码快照 `{_cell(run.get('git_commit', 'unknown'))}`。",
             f"写作模型 `{_cell(run.get('writer_model', 'unknown'))}`；评审模型 `{_cell(run.get('judge_model', 'unknown'))}`。", "",
             f"本报告状态：**{aggregate['status']}**。{totals['cases']} 个合成用例，{totals['versions']} 个变化版本（可见 {totals['visible_versions']}，仅内部 {totals['internal_only_versions']}）。",
             f"{truth_label}；**本轮输出的确认新增经历事实仍为 null（未知）**，需 Claude 差异复核。模型评分不替代复核确认。", "",
             "## 历史复核归属", "",
             "[Claude 对 v1 的复核](../../claude-review-response.txt)确认：`20261008-baseline` 的新增经历事实为 0，另有 1 例未经支持的求职意向扩写。"
             "这个 0 只属于 v1；没有转移到本轮，也没有覆盖或重写 v1 的原始运行文件。", "",
             "## 总体指标", "", "| 指标 | 结果 | 解释 |", "|---|---|---|"]
    for label, value in (("coverage_of_disclosed", disclosed), ("coverage_of_truth", truth)):
        lines.append(f"| {label} · 要求覆盖 | {value['covered']}/{value['total']} = {_percent(value['observed_lower_bound'])} | 已评分观察下界；已知未覆盖 {value['known_uncovered']}，未知 {value['unknown']}，N/A {value['not_applicable']}。 |")
        lines.append(f"| {label} · 证据事实覆盖 | {value['fact_covered'] if value['fact_covered'] is not None else 'unknown'}/{value['fact_total'] if value['fact_total'] is not None else 'unknown'} = {_percent(value['fact_observed_lower_bound'])} | 按该要求的证据事实计，不把出现任意一条证据称为覆盖全部事实；未知 {value['fact_unknown']}。 |")
    lines.extend([
        f"| 编辑执行 | {edits['executed']}/{edits['expected']} = {_percent(edits['observed_lower_bound'])} | 无 diff {edits['no_diff']}；错误 {edits['error']}；未运行 {edits['not_run']}；未评分 {edits['unscored']}；无稿 {edits['no_draft']}；未遵循 {edits['not_followed']}；不确定 {edits['uncertain']}。 |",
        f"| 首稿 ≤ 2 个用户轮 | {totals['first_draft']['within_two_turns']}/{totals['cases']} | 首个用户可见且至少一段经历有 bullet/description 正文的版本；有首稿 {totals['first_draft']['drafted_cases']}。JD 消息计入用户轮。 |",
        f"| 逐版本评分 | {totals['version_score_statuses']} | 任一缺失/错误/未运行仍为评估不完整，no_draft 不代表质量或安全通过。 |",
        f"| 词法 / 语义事实疑点 | {facts['lexical_flags']} / {facts['semantic_suspicions']} | 分开计数，可能重叠；所有疑点待复核。 |",
        f"| unverifiable_unit | {facts['unverifiable_units']} | uncertain 单独统计，不计新增事实疑点。标题、技能等质量检查也单列。 |",
        f"| 平均轮延迟 | {totals['latency']['mean_seconds'] if totals['latency']['mean_seconds'] is not None else 'unknown'} 秒 | 基于 {totals['latency']['observed_turns']} 个实际记录轮。 |",
        f"| Graph / Judge / 模拟器 tokens | {_usage_text(totals['usage']['graph'])} / {_usage_text(totals['usage']['judge'])} / {_usage_text(totals['usage']['simulator'])} | 三类分开统计，合计费用包含模拟器；HTTP 重试次数未知。 |",
        "| Pairwise 新版胜率 | N/A | 旧链路基线没有新版对手。 |",
        "| Guard 回退 / 误杀 | 未观测 | 旧链路没有新语义 guard，不能记为零。 |", "",
        f"正向要求分母共 {truth['total']} 条；{totals['gap_requirements']} 条 gap 要求不进正向覆盖分母。disclosed 只计截至该版已有证据的要求；全部证据未披露的要求记 N/A。truth 衡量追问加写作。",
        "没有任何可见断言正文的已运行用例覆盖记 0；有断言正文但评分缺失记 unknown。覆盖不限经历栏，不能替代首稿指标：已披露行动句即使被放入自评栏仍可形成事实覆盖，但不满足经历栏首稿定义；只有标题或技能词不能充当覆盖证据。比例在评分不齐时仅为已观测下界，不用于宣称验收通过。", "",
        "## 首稿口径与五维质量", "",
        "首稿轮数与质量统一取首个用户可见、且至少一段经历的 bullet 或 description 非空的版本。只有项目名称不计首稿。"
        "stage 口径已废弃，仅保留在 aggregate.json 的 diagnostic_stage_first_draft_* 中作诊断；COLLECTING 的可见正文按同一规则评分。",
        "五维顺序：JD 相关性 / 个人贡献 / 结果产出 / 专业表达 / 取舍篇幅（1–5 分）。原话粘贴即使满足可见首稿条件，也不等于写作质量合格。", "",
        "| 用例 | Graph / 评估 | 首稿五维 | 终稿五维 | 最终覆盖 disclosed / truth | 编辑执行 | 首稿轮 | 可见/仅内部版本 |",
        "|---|---|---|---|---|---|---|---|"])
    def coverage_cell(value):
        if not value["total"]:
            return "N/A"
        return f"{value['covered']}/{value['total']}" if not value["unknown"] else f"unknown ({value['unknown']}/{value['total']})"
    for case in aggregate["cases"]:
        lines.append(f"| [{case['case_id']}]({case['links']['transcript.md']}) | {case['graph_status']} / {case['evaluation_status']} | "
                     f"{_quality_text(case['first_quality'], case['first_score_status'])} | {_quality_text(case['final_quality'], case['final_score_status'])} | "
                     f"{coverage_cell(case['final_coverage_of_disclosed'])} / {coverage_cell(case['final_coverage_of_truth'])} | "
                     f"{case['edit_counts'].get('executed', 0)}/{case['expected_edits']} | {case['first_draft_turn'] or '无稿'} | {case['visible_version_count']}/{case['internal_only_version_count']} |")
    lines.extend(["", "质量均分仅针对成功评分的用例，不给缺失质量分填零；无稿/未评分不从覆盖和编辑分母消失。", "",
                  "| 位置 | 有效用例 / 全部 | 五维均分 |", "|---|---|---|"])
    for position in ("first", "final"):
        value = totals["quality"][position]
        means = "/".join(str(value["means"][key]) if value["means"][key] is not None else "unknown" for key in QUALITY_DIMENSIONS)
        lines.append(f"| {position} | {value['scored_cases']}/{totals['cases']} | {means} |")
    lines.extend(["", "## 产品发现（本轮实际结果）", "",
                  f"**E1 编辑执行。** 本轮 {edits['executed']}/{edits['expected']} 条指令被评分为实质执行。无 diff {edits['no_diff']}、无稿 {edits['no_draft']}、未遵循 {edits['not_followed']}；未知或未完成不按成功计算。", "",
                  f"**E2 标题与重复项目。** {product['drafted_cases']} 个有稿例中，当前终稿已记录标题错误 {len(product['title_error_cases'])} 例（{', '.join(product['title_error_cases']) or '无已记录项'}），"
                  f"重复项目 {len(product['duplicate_project_cases'])} 例（{', '.join(product['duplicate_project_cases']) or '无已记录项'}）。来源为确定性质量检查；这些是质量缺陷，不自动当作新增经历事实。", "",
                  f"**E3 无稿与整份导入。** 本轮无可见经历正文 {len(product['no_draft_cases'])}/{totals['cases']} 例：{', '.join(product['no_draft_cases']) or '无'}。"])
    for case in aggregate["cases"]:
        if (case["first_draft_turn"] is None and case["product_observations"]["self_evaluation_assertions"]
                and case["final_coverage_of_truth"]["covered"]):
            lines.append(f"{case['case_id']} 的已披露行动事实被放入 self_evaluation（自评栏），经历栏仍没有正文；"
                         f"终稿已有事实覆盖 {case['final_coverage_of_truth']['covered']}/{case['final_coverage_of_truth']['total']}，"
                         "但首稿仍为无稿。这是内容放错栏目，不是仅靠标题或技能词获得覆盖。")
    imported = next((case for case in aggregate["cases"] if case["case_id"] == "import-01"), None)
    if imported:
        if imported["first_draft_turn"] is None:
            lines.append("整份本人旧简历导入例 import-01 本轮仍未出现经历正文，不能视为‘完整资料直接成稿’已验证。")
        else:
            lines.append(f"整份本人旧简历导入例 import-01 本轮在第 {imported['first_draft_turn']} 轮出现经历正文；v1 无正文是历史结果，不套用到本轮。")
        lines.append("[只读导入诊断](../../import-intake-diagnosis-v2.json)显示：原开场未被现有解析器识别；保持事实不变、仅规范教育/项目标签后可解析出 2 个项目和 1 条教育。"
                     "此前完整资料测试采用受支持标签且包含显式生成指令，不能推广成‘任意完整材料都直接成稿’。这定位了格式分支差异，未证明先发 JD 是唯一原因；业务修复留待 PR4。")
    lines.extend(["", f"**E4 教育信息。** 有稿例中 {len(product['drafts_without_education'])}/{product['drafted_cases']} 的最终可见简历没有教育栏。"
                  f"已披露教育 {len(product['disclosed_education_cases'])} 例；其中确定性检查记录缺栏/缺字段 {len(product['disclosed_education_missing_cases'])} 例（{', '.join(product['disclosed_education_missing_cases']) or '无已记录项'}）。"
                  "没有询问到的隐藏教育不会被当作已披露漏写；导入例开场教育按已披露检查。", "",
                  f"**E5 正文表达。** 有稿例中至少一条正文出现第一人称‘我’ {len(product['first_person_cases'])} 例，"
                  f"整条正文规范化后可在已披露用户文本中找到 {len(product['verbatim_body_cases'])} 例，重复正文单元 {len(product['duplicate_body_cases'])} 例、重复句 {len(product['duplicate_sentence_cases'])} 例。"
                  "这是可复查的表达观察，不是自动质量分，也不说明其他文字一定经过了合格改写。", "",
                  "## 逐版本评分清单", "",
                  "| 用例 / 版本 | 轮 / stage | 可见性 | 评分 | 词法 / 语义疑点 | 不可判定单元 | 质量检查 |",
                  "|---|---|---|---|---|---|---|"])
    for case in aggregate["cases"]:
        if not case["versions"]:
            lines.append(f"| {case['case_id']} / — | — | — | 没有版本 | 未观测 | 未观测 | 未观测 |")
        for row in case["versions"]:
            lines.append(f"| [{case['case_id']} / {row['version_id']}]({case['links']['scores.json']}) | {row['turn']} / {_cell(row['stage'])} | "
                         f"{'用户可见' if row['user_visible'] else '仅内部'} | {row['score_status']} | {row['lexical_flags']} / {row['semantic_suspicions']} | "
                         f"{row['unverifiable_units']} | {len(row['quality_checks'])} |")
    lines.extend(["", "## 失败与未知项", ""])
    for case in aggregate["cases"]:
        if case["failures"]:
            lines.append(f"- [{case['case_id']}]({case['links']['meta.json']}): {', '.join(case['failures'])}。编辑分类 {case['edit_counts']}。")
    if not aggregate["failures"]:
        lines.append("没有记录到产品/执行指标失败；本轮事实安全仍待 Claude 复核，不宣称全部验收通过。")
    lines.extend(["", "## 用量与费用", "", "费用区间只覆盖记录到 token 且有费率的调用，不是账单；缺价/缺量不填零。all_models 包含 Graph、Judge 与模拟器。", ""])
    for kind in ("graph", "judge", "simulator", "all_models"):
        usage = totals["usage"][kind]
        cost = usage["reported_token_cost_usd"]
        if cost:
            lines.append(f"- {kind}: 已记录 token 估算 USD {cost['lower_bound']:.6f}–{cost['upper_bound']:.6f}；有价格调用 {cost['priced_calls']}，"
                         f"区间内未定价调用 {cost['unpriced_calls']}，无费用区间记录 {cost['cases_without_range']}。来源见 [aggregate.json](aggregate.json)。")
        else:
            lines.append(f"- {kind}: 费用 unknown；有用量记录 {usage['cases_with_usage']}，缺失记录 {usage['cases_missing_usage']}。")
    if aggregate.get("limitations"):
        lines.extend(["", "## 本次运行的已知限制", ""])
        lines.extend("- " + note for note in aggregate["limitations"])
    lines.extend(["", "## Claude 复核入口", "",
                  f"- [review-queue.json](review-queue.json)：{aggregate['review_queue_count']} 项待审任务；事实疑点、不可判定单元、质量检查分别标注。",
                  "- [aggregate.json](aggregate.json)：双覆盖分母、unknown、编辑分类、逐版状态、stage 诊断和使用量。",
                  "- [manifest.json](manifest.json)：源码、模型与隔离配置；逐例 transcript / versions / scores 都是相对链接。",
                  "- v1 复核结论只归属 v1，本轮待差异复核。PR1 进度另见项目 mmr，不属于本次旧链路基线。", ""])
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
    truth_coverage = _aggregate_coverage(cases, "final_coverage_of_truth")
    disclosed_coverage = _aggregate_coverage(cases, "final_coverage_of_disclosed")
    edits_total = sum(case["expected_edits"] for case in cases)
    drafted = [case["first_draft_turn"] for case in cases if type(case["first_draft_turn"]) is int]
    visible_drafted = [case["first_visible_experience_turn"] for case in cases if type(case["first_visible_experience_turn"]) is int]
    latencies = [value for case in cases for value in case["turn_latencies_seconds"]]
    total_facts = {
        "confirmed_new_facts": None, "safe": None, "status": "pending_claude_review",
        "lexical_flags": sum(row["lexical_flags"] for row in versions),
        "lexical_statuses": dict(Counter(row["lexical_status"] for row in versions)),
        "semantic_suspicions": sum(row["semantic_suspicions"] for row in versions),
        "unverifiable_units": sum(row["unverifiable_units"] for row in versions),
        "quality_check_counts": dict(Counter(item.get("kind", "unknown") for row in versions for item in row["quality_checks"])),
        "semantic_completed_versions": sum(row["score_status"] == "completed" for row in versions),
        "semantic_unscored_content_versions": sum(row["has_displayed_content"] and row["score_status"] != "completed" for row in versions),
        "semantic_statuses": dict(Counter(row["semantic_status"] for row in versions)),
        "semantic_verdicts": dict(sum((Counter(row["semantic_verdicts"]) for row in versions), Counter())),
    }
    for visibility, visible in (("visible", True), ("internal", False)):
        total_facts[f"{visibility}_lexical_flags"] = sum(row["lexical_flags"] for row in versions if row["user_visible"] == visible)
        total_facts[f"{visibility}_semantic_suspicions"] = sum(row["semantic_suspicions"] for row in versions if row["user_visible"] == visible)
    complete = bool(cases) and not problems and all(case["graph_status"] == "completed" and case["evaluation_status"] == "completed" for case in cases)
    drafted_cases = [case for case in cases if case["first_draft_turn"] is not None]
    product = {
        "drafted_cases": len(drafted_cases),
        "no_draft_cases": [case["case_id"] for case in cases if case["first_draft_turn"] is None],
        "title_error_cases": [case["case_id"] for case in drafted_cases if case["product_observations"]["title_errors"]],
        "duplicate_project_cases": [case["case_id"] for case in drafted_cases if case["product_observations"]["duplicate_projects"]],
        "drafts_without_education": [case["case_id"] for case in drafted_cases if not case["product_observations"]["education_present"]],
        "disclosed_education_cases": [case["case_id"] for case in cases if case["product_observations"]["education_disclosed"]],
        "disclosed_education_missing_cases": [case["case_id"] for case in cases if case["product_observations"]["education_checks"]],
        "first_person_cases": [case["case_id"] for case in drafted_cases if case["product_observations"]["first_person_body_units"]],
        "verbatim_body_cases": [case["case_id"] for case in drafted_cases if case["product_observations"]["verbatim_body_units"]],
        "duplicate_body_cases": [case["case_id"] for case in drafted_cases if case["product_observations"]["duplicate_body_units"]],
        "duplicate_sentence_cases": [case["case_id"] for case in drafted_cases if case["product_observations"]["duplicate_sentences"]],
    }
    usage = {kind: _sum_usage([case.get(f"{kind}_usage") for case in cases]) for kind in ("graph", "judge", "simulator")}
    usage["all_models"] = _sum_usage([case.get(f"{kind}_usage") for case in cases for kind in ("graph", "judge", "simulator")])
    aggregate = {
        "report_version": 2, "status": "evaluated_pending_claude" if complete else "incomplete",
        "run": {key: manifest.get(key) for key in ("started_at", "finished_at", "git_commit", "git_branch", "writer_model", "structured_model", "judge_model", "status", "backend_unchanged")},
        "manifest_problems": problems, "truth_review_status": "approved_by_claude" if cases and all(case["truth_review_status"] == "approved_by_claude" for case in cases) else "pending_claude",
        "historical_review": {"run_id": "20261008-baseline", "reviewer": "Claude", "source": "../../claude-review-response.txt",
                              "confirmed_new_experience_facts": 0, "unsupported_objective_expansion_cases": 1,
                              "scope": "v1 only; does not confirm the current run"},
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
            "coverage": truth_coverage, "coverage_of_truth": truth_coverage, "coverage_of_disclosed": disclosed_coverage,
            "gap_requirements": sum(len(case["gap_requirements"]) for case in cases),
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
            "usage": usage, "product_findings": product,
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
