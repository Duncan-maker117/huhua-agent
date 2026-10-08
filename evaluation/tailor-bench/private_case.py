"""Private replay policy and deterministic §10 acceptance checks.

Golden prose never enters graph/simulator inputs. These checks are evidence about
visible structure, not semantic factuality judgments or a human safety approval.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import unicodedata
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
PRIVATE_RUNS = HERE / "runs-private"
PROJECTS = ("mtagent", "CodeWiz", "Forge Skill", "Huhua Agent")
DUPLICATE_THRESHOLD = 0.6


def is_private(case: dict) -> bool:
    return case.get("private") is True or case.get("data_classification") == "private" or case.get("id") == "real-01"


def validate_benchmark_case(case: dict) -> None:
    from simulate_user import validate_case
    if not is_private(case):
        validate_case(case)
        return
    if case.get("private") is not True or case.get("replay_policy") != "fixed_two_turns":
        raise ValueError("Private cases require explicit classification and fixed_two_turns replay")
    if case.get("jd_text") or len(case.get("opening_turns", [])) != 1 or len(case.get("edit_instructions", [])) != 1:
        raise ValueError("Private replay requires exactly one opening and one edit, without JD or simulator turns")
    # Retain all public truth/index validation without changing its two-edit API.
    validate_case({**case, "edit_instructions": case["edit_instructions"] * 2})
    for text, expected in zip(case["opening_turns"] + case["edit_instructions"], case.get("replay_sha256", []), strict=True):
        if hashlib.sha256(text.encode()).hexdigest() != expected:
            raise ValueError("Private replay text does not match its frozen SHA-256")
    if case.get("id") == "real-01" and len(case["edit_instructions"][0]) != 237:
        raise ValueError("real-01 requires the original 237-character second turn")
    if case.get("simulator_topics"):
        raise ValueError("Private replay must not have simulator topics")


def load_cases(*, cases_dir: Path | None = None, include_private: bool = False,
               rescore: Path | None = None) -> list[dict]:
    if rescore:
        paths = sorted(rescore.glob("*/case.json"))
    else:
        directory = (cases_dir or HERE / "cases").resolve()
        paths = sorted(directory.glob("*.json"))
        if include_private and directory != (HERE / "cases-private").resolve():
            paths.extend(sorted((HERE / "cases-private").glob("*.json")))
    cases = []
    for path in paths:
        case = json.loads(path.read_text(encoding="utf-8"))
        # Custom input directories are private by default. Never trust a copied
        # personal fixture's filename or a removed `private` marker.
        if not rescore and path.parent.resolve() != (HERE / "cases").resolve():
            case["private"] = True
            case["data_classification"] = "private"
        validate_benchmark_case(case)
        cases.append(case)
    return cases


def safe_output(cases: list[dict], requested: Path | None, run_name: str) -> Path:
    private = any(is_private(case) for case in cases)
    root = PRIVATE_RUNS if private else HERE / "runs"
    output = (requested or root / run_name).resolve()
    if private and not output.is_relative_to(PRIVATE_RUNS.resolve()):
        raise ValueError("Private cases must write only under evaluation/tailor-bench/runs-private (gitignored)")
    return output


def assert_private_model_policy(cases, args, settings) -> None:
    if not any(is_private(case) for case in cases):
        return
    from urllib.parse import urlparse
    endpoint = urlparse(settings.LLM_BASE_URL)
    if (settings.LLM_MODEL != "deepseek-flash"
            or (settings.LLM_STRUCTURED_MODEL or settings.LLM_MODEL) != "deepseek-flash"
            or endpoint.scheme != "https" or endpoint.hostname != "api.deepseek.com"
            or endpoint.username or endpoint.password):
        raise ValueError("Private materials are authorized only for official DeepSeek deepseek-flash")
    if not args.graph_only:
        raise ValueError("Private replay currently requires --graph-only; independent semantic review is pending")


def followup_limit(case: dict, configured: int) -> int:
    return 0 if is_private(case) else configured


def normalize(text: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]", "", unicodedata.normalize("NFKC", text).casefold())


def ngram_overlap(left: str, right: str, n: int = 3) -> float:
    """Containment overlap, intersection / shorter set; normalized char trigrams."""
    left, right = normalize(left), normalize(right)
    if min(len(left), len(right)) < n:
        return float(bool(left) and left == right)
    a = {left[i:i + n] for i in range(len(left) - n + 1)}
    b = {right[i:i + n] for i in range(len(right) - n + 1)}
    return len(a & b) / min(len(a), len(b))


def visible_projects(resume: dict) -> list[dict]:
    sections = resume.get("sections")
    if isinstance(sections, list) and not any(s.get("kind") == "projects" for s in sections if isinstance(s, dict)):
        return []
    result = []
    for index, item in enumerate(resume.get("projects") or []):
        if not isinstance(item, dict) or item.get("hidden") is True:
            continue
        raw = item.get("bullets") or item.get("polished_bullets") or [item.get("description", "")]
        bullets = [line.strip() for value in raw
                   for line in (value.get("text", "") if isinstance(value, dict) else str(value or "")).splitlines()
                   if line.strip()]
        result.append({**item, "index": index, "visible_bullets": bullets})
    return result


def length_metrics(resume: dict, chars_per_line: int = 30) -> dict:
    """Reusable length/duplication metrics. Estimates never count as PDF proof."""
    if chars_per_line <= 0:
        raise ValueError("chars_per_line must be positive")
    rows = [{"project_index": item["index"], "bullet_index": index, "text": text,
             "characters": len(text), "estimated_lines": math.ceil(len(text) / chars_per_line),
             "actual_lines": None}
            for item in visible_projects(resume) for index, text in enumerate(item["visible_bullets"])]
    duplicates = []
    for i, left in enumerate(rows):
        for j, right in enumerate(rows[:i]):
            if min(len(normalize(left["text"])), len(normalize(right["text"]))) < 8:
                continue
            overlap = ngram_overlap(left["text"], right["text"])
            if overlap >= DUPLICATE_THRESHOLD:
                duplicates.append({"left": j, "right": i, "overlap": round(overlap, 4),
                                   "cross_project": left["project_index"] != right["project_index"]})
    return {"bullet_count": len(rows), "bullets": rows, "chars_per_line": chars_per_line,
            "line_estimate_status": "heuristic_not_rendered", "actual_line_status": "not_rendered",
            "over_60_character_bullets": sum(row["characters"] > 60 for row in rows),
            "duplicate_threshold": DUPLICATE_THRESHOLD, "duplicate_pairs": duplicates,
            "duplicate_status": "lexical_candidates_pending_semantic_review"}


def measure_rendered_resume(resume: dict, template_id: str, page_limit: int = 1,
                            pdf_path: Path | None = None, existing_pdf: Path | None = None) -> dict:
    """Use production export's actual PDF; absent native tools fail closed.

    pdftotext line matching is optional. Ambiguous/missing matches stay unknown;
    `estimated_lines` in length_metrics is never substituted for actual lines.
    """
    result = {"status": "not_rendered", "template_id": template_id, "page_limit": page_limit,
              "pages": None, "within_page_limit": None, "bullet_lines": []}
    try:
        if existing_pdf is not None:
            pdf = existing_pdf.read_bytes()
        else:
            from app.services.resume_pdf import render_resume_pdf
            pdf = render_resume_pdf(template_id, resume)
        info = subprocess.run(["pdfinfo", "-"], input=pdf, capture_output=True, check=True, timeout=30)
        match = re.search(rb"^Pages:\s+(\d+)\s*$", info.stdout, re.M)
        if not match or int(match[1]) <= 0:
            raise ValueError("PDF page count unavailable")
        pages = int(match[1])
        result.update(status="rendered", pages=pages, within_page_limit=pages <= page_limit,
                      pdf_sha256=hashlib.sha256(pdf).hexdigest(),
                      renderer="frozen_production_pdf+pdfinfo" if existing_pdf else "production_render_resume_pdf/weasyprint+pdfinfo",
                      source_pdf=str(existing_pdf) if existing_pdf else None)
        if pdf_path:
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(pdf)
    except Exception as exc:
        result.update(status="render_error", error_type=type(exc).__name__)
        return result
    try:
        extracted = subprocess.run(["pdftotext", "-bbox-layout", "-", "-"], input=pdf,
                                   capture_output=True, check=True, timeout=30)
        tree = ET.fromstring(extracted.stdout)
        lines = [normalize("".join(node.itertext())) for node in tree.iter() if node.tag.rsplit("}", 1)[-1] == "line"]
        for row in length_metrics(resume)["bullets"]:
            target = normalize(row["text"])
            matches = []
            for start in range(len(lines)):
                for size in range(1, min(16, len(lines) - start) + 1):
                    candidate = "".join(lines[start:start + size])
                    if candidate == target:
                        matches.append(size)
                    if len(candidate) > len(target):
                        break
            result["bullet_lines"].append({"project_index": row["project_index"], "bullet_index": row["bullet_index"],
                                           "actual_lines": matches[0] if len(matches) == 1 else None,
                                           "status": "matched_pdf_text" if len(matches) == 1 else "unresolved_pdf_text"})
        result["actual_line_status"] = "completed" if all(row["actual_lines"] is not None for row in result["bullet_lines"]) else "partial"
    except Exception as exc:
        result.update(actual_line_status="unavailable", line_error_type=type(exc).__name__)
    return result


def _op(op: str, target: str, passed: bool | None, evidence=None) -> dict:
    return {"op": op, "target": target, "status": "unknown" if passed is None else "pass" if passed else "fail",
            "evidence": evidence}


def _goal(identifier: str, label: str, ops: list[dict]) -> dict:
    statuses = {row["status"] for row in ops}
    return {"id": identifier, "label": label, "ops": ops,
            "status": "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"}


def evaluate_real01(resume: dict, *, rendered: dict | None = None, context: dict | None = None) -> dict:
    """Eight observable goals, split into 14 implementation-level operations."""
    from judge import candidate_units
    projects = visible_projects(resume)
    by_name = {name: [item for item in projects if normalize(name) in normalize(item.get("name", ""))] for name in PROJECTS}
    units = candidate_units(resume)
    displayed = "\n".join(row["text"] for row in units)
    basic = resume.get("basic_info") or {}
    metrics = length_metrics(resume)
    repeated_roles, repeated_times = [], []
    for item in projects:
        for index, bullet in enumerate(item["visible_bullets"]):
            clean = normalize(bullet)
            role = normalize(item.get("role", ""))
            # Metadata-like lines are distinct from an action that mentions the
            # role's nouns. A simple role substring in a long action is not enough.
            if (role and role in clean and len(clean) <= len(role) + 20) or re.search(r"^(?:个人项目|字节跳动.*训练营|美团黑客松).{0,20}(?:负责|产品方案|原型实现)", bullet):
                repeated_roles.append([item["index"], index])
            if re.search(r"(?:20\d{2}[./年-]?\d{0,2}).{0,6}(?:至今|20\d{2}[./年-]?\d{0,2})", bullet):
                repeated_times.append([item["index"], index])
    skill_values = [row["text"] for row in units if row["path"].startswith("skills")]
    skill_tokens = [normalize(token.rsplit("：", 1)[-1].rsplit(":", 1)[-1]) for text in skill_values for token in re.split(r"[、,，;；/|\n]|\s+[与和]\s+", text)
                    if len(normalize(token)) >= 2]
    repeated_skills = [token for token, count in Counter(skill_tokens).items() if count > 1]
    repeated_skill_rows = any(ngram_overlap(a, b) >= DUPLICATE_THRESHOLD for i, a in enumerate(skill_values) for b in skill_values[:i])
    codewiz = by_name["CodeWiz"]
    link_text = "\n".join(text for item in codewiz for text in item["visible_bullets"])
    constraints = (context or {}).get("session_constraints") or resume.get("session_constraints") or {}
    page = rendered or {"status": "not_rendered", "pages": None}
    goals = [
        _goal("location", "删除深圳伪项目，并保留为所在地", [
            _op("delete_item", "深圳", bool(projects) and not any("深圳" in item.get("name", "") for item in projects)),
            _op("set_field", "basic_info.location", "深圳" in basic.get("location", ""))]),
        _goal("project_caps", "四个真实项目各最多两条", [
            _op("cap_bullets(2)", name, len(by_name[name]) == 1 and 1 <= len(by_name[name][0]["visible_bullets"]) <= 2,
                [len(item["visible_bullets"]) for item in by_name[name]]) for name in PROJECTS]),
        _goal("metadata_dedup", "正文不重复职责和时间行", [
            _op("clean_format", "repeated_roles", bool(projects) and not repeated_roles, repeated_roles),
            _op("clean_format", "repeated_times", bool(projects) and not repeated_times, repeated_times)]),
        _goal("self_evaluation", "删除整段自我评价", [
            _op("remove_section", "self_evaluation", bool(projects) and not any(row["path"] == "self_evaluation" for row in units))]),
        _goal("skills_dedup", "技能去重", [
            _op("clean_format", "skills", bool(skill_values) and not repeated_skills and not repeated_skill_rows, repeated_skills)]),
        _goal("readable_links", "CodeWiz PR 链接可读", [
            _op("clean_format", "CodeWiz.links", bool(codewiz) and not re.search(r"\[[^\]]+\]\([^)]+\)", link_text)
                and bool(re.search(r"PR\s*#?\s*6", link_text, re.I)) and bool(re.search(r"(?:PR\s*)?#?\s*8", link_text, re.I)))]),
        _goal("objective", "求职意向使用指定方向", [
            _op("set_field", "basic_info.objective", normalize(basic.get("objective", resume.get("objective", ""))) == normalize("AI 产品经理实习（Agent 应用方向）"))]),
        _goal("one_page", "保存一页约束且真实渲染不超页", [
            _op("set_constraint", "page_limit", constraints.get("page_limit") == 1 if "page_limit" in constraints else None),
            _op("compress", "rendered_pages", page.get("pages", 0) <= 1 if page.get("status") == "rendered" and page.get("pages") else None,
                {"status": page.get("status"), "pages": page.get("pages")})]),
    ]
    # Golden is a reference, not a required verbatim answer. These lexical checks
    # intentionally flag review candidates instead of asserting semantic safety.
    conflict_text = json.dumps({"notes": resume.get("verification_notes", []), "conflicts": (context or {}).get("field_conflicts", resume.get("field_conflicts", []))}, ensure_ascii=False)
    mt = by_name["mtagent"]
    mt_body = "\n".join(str(item.get(key, "")) for item in mt for key in ("role", "start_date", "end_date")) + "\n" + "\n".join(b for item in mt for b in item["visible_bullets"])
    hh = by_name["Huhua Agent"]
    hh_text = " ".join(str(item.get(key, "")) for item in hh for key in ("start_date", "end_date", "description"))
    observed_order = [next((name for name in PROJECTS if normalize(name) in normalize(item.get("name", ""))), item.get("name", "")) for item in projects]
    reference = {
        "reference_only": True, "golden_bullets": 7, "golden_project_order": list(PROJECTS),
        "observed_project_order": observed_order, "order_matches_reference": observed_order == list(PROJECTS),
        "four_real_projects_only": len(projects) == 4 and all(len(rows) == 1 for rows in by_name.values()),
        "bullet_budget_matches_reference": metrics["bullet_count"] <= 7 and all(by_name.values()),
        "huhua_original_date_retained": bool(re.search(r"2025[.年/-]0?9", hh_text)),
        "mtagent_conflict_in_review": "mtagent" in conflict_text.casefold() and bool(re.search(r"2026|时间|日期|职责|角色", conflict_text)),
        "mtagent_both_dates_in_body": bool(re.search(r"2026\s*[-–—]\s*至今", mt_body)) and bool(re.search(r"2026[./年]0?5", mt_body)),
        "prototype_limit_visible": bool(re.search(r"原型|prototype", displayed, re.I)),
        "editor_notes_leaked": bool(re.search(r"编辑记录|不进入\s*(?:PDF|Word)", displayed, re.I)),
        "ten_seconds_claim_requires_review": bool(re.search(r"10\s*秒", displayed)) and not bool(re.search(r"目标.{0,40}10\s*秒|10\s*秒.{0,40}目标", displayed)),
        "semantic_limitations_status": "pending_review",
        "mandatory_review": ["10 秒为目标，非实测；Stub/估算非真实旅行效果", "原型/真实模型及用户效果未验证，不能扩为上线成效", "74 Stars 为历史材料值；PR #6/#8 不累加工量、不改为全手写", "Huhua 2025.09 原值保留；mtagent 角色/日期不得两版并印"],
    }
    ops = [op for goal in goals for op in goal["ops"]]
    return {"status": "deterministic_only_pending_semantic_review", "goals": goals,
            "goal_counts": dict(Counter(goal["status"] for goal in goals)), "goal_total": len(goals),
            "op_counts": dict(Counter(op["status"] for op in ops)), "op_total": len(ops),
            "length": metrics, "render": page, "golden_comparison": reference}


def evaluate_edit(before: dict, after: dict, *, before_rendered=None, rendered=None,
                  before_context=None, context=None, turn_status="completed") -> dict:
    left = evaluate_real01(before, rendered=before_rendered, context=before_context)
    right = evaluate_real01(after, rendered=rendered, context=context)
    rows = []
    for prior_goal, goal in zip(left["goals"], right["goals"], strict=True):
        for prior, op in zip(prior_goal["ops"], goal["ops"], strict=True):
            category = ("error" if turn_status != "completed" else
                        "already_satisfied" if prior["status"] == op["status"] == "pass" else
                        "executed" if prior["status"] == "fail" and op["status"] == "pass" else
                        "unknown" if "unknown" in (prior["status"], op["status"]) else "not_executed")
            rows.append({"goal": goal["id"], "op": op["op"], "target": op["target"],
                         "before": prior["status"], "after": op["status"], "category": category})
    counts = Counter(row["category"] for row in rows)
    goals = []
    for goal in right["goals"]:
        operations = [row for row in rows if row["goal"] == goal["id"]]
        achieved = all(row["category"] in {"executed", "already_satisfied"} for row in operations)
        goals.append({"id": goal["id"], "status": goal["status"], "executed": achieved and any(row["category"] == "executed" for row in operations)})
    return {"status": "deterministic_only_pending_semantic_review", "ops": rows, "goals": goals,
            "op_total": len(rows), "op_executed": counts["executed"], "op_counts": dict(counts),
            "op_execution_rate": counts["executed"] / len(rows), "goal_total": len(goals),
            "goal_executed": sum(row["executed"] for row in goals), "after": right}


def import_saved_run(source: Path, output: Path) -> dict:
    """Create a NEW private baseline from frozen UI evidence, with no model call.

    Original input, output, PDF and golden files remain byte-for-byte untouched.
    The saved PDF proves only the matching first draft. A changed second draft
    cannot silently borrow its page count.
    """
    case = json.loads((HERE / "cases-private" / "real-01.json").read_text())
    validate_benchmark_case(case)
    output = safe_output([case], output, "")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Refusing to overwrite an existing run")
    first = json.loads((source / "turn-1-resume.json").read_text())["data"]
    second = json.loads((source / "turn-2-resume.json").read_text())["data"]
    first_conversation = json.loads((source / "turn-1-conversation.json").read_text())
    conversation = json.loads((source / "turn-2-conversation.json").read_text())
    messages = conversation["messages"]
    user_turns = [row["content"] for row in messages if row["role"] == "user"]
    if (user_turns != case["opening_turns"] + case["edit_instructions"]
            or first_conversation["messages"] != messages[:len(first_conversation["messages"])]
            or [row["content"] for row in first_conversation["messages"] if row["role"] == "user"] != case["opening_turns"]):
        raise ValueError("Saved conversation does not match frozen real-01 replay")
    golden = Path(case["golden_reference"]["path"])
    if not golden.is_absolute():
        golden = HERE.parents[1] / golden
    if hashlib.sha256(golden.read_bytes()).hexdigest() != case["golden_reference"]["sha256"]:
        raise ValueError("Golden reference changed; review and refresh the private fixture explicitly")
    import os
    os.umask(0o077)
    folder = output / case["id"]
    folder.mkdir(parents=True)
    def save(name, data):
        (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    def sha(data):
        return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    template = case["acceptance"]["template_id"]
    unchanged = sha(first) == sha(second)
    first_pdf = source / "generated-resume.pdf"
    second_pdf = source / "after-edit-resume.pdf"
    if unchanged and hashlib.sha256(first_pdf.read_bytes()).digest() != hashlib.sha256(second_pdf.read_bytes()).digest():
        raise ValueError("Identical saved drafts have different PDFs; cannot attribute rendered pages")
    first_render = measure_rendered_resume(first, template, existing_pdf=first_pdf)
    second_render = (measure_rendered_resume(second, template, existing_pdf=second_pdf) if unchanged else
                     {"status": "not_rendered", "pages": None,
                      "reason": "Changed second draft cannot be tied to the saved PDF without a content proof"})
    versions = [{"version_id": "v001", "turn": 1, "kind": "committed", "stage": "EVALUATING",
                 "hash": sha(first), "user_visible": True, "resume_data": first,
                 "observed_facts": case["opening_turns"], "disclosed_fact_indices": [0, 1]}]
    if not unchanged:
        versions.append({**versions[0], "version_id": "v002", "turn": 2, "hash": sha(second), "resume_data": second,
                         "observed_facts": case["opening_turns"] + case["edit_instructions"]})
    assistants = [row["content"] for row in messages if row["role"] == "assistant"]
    turns = [{"turn": index + 1, "phase": "opening" if index == 0 else "edit", "user": text,
              "assistant": assistants[index] if index < len(assistants) else "", "status": "completed",
              "stage": "EVALUATING", "elapsed_seconds": None,
              "new_versions": ["v001"] if index == 0 else [] if unchanged else ["v002"],
              "evidence_mode": "imported_frozen_ui_artifacts_no_new_model_calls"}
             for index, text in enumerate(user_turns)]
    edit_input = {"turn": 2, "instruction": user_turns[1], "before": first, "after": second,
                  "observed_facts": user_turns, "turn_status": "completed"}
    acceptance = {"case_id": case["id"], "status": "deterministic_only_pending_semantic_review",
                  "golden_reference": case["golden_reference"],
                  "versions": [{"version_id": row["version_id"], "turn": row["turn"], "user_visible": True,
                                "acceptance": evaluate_real01(row["resume_data"], rendered=first_render if row["turn"] == 1 else second_render)} for row in versions],
                  "edits": [{"turn": 2, **evaluate_edit(first, second, before_rendered=first_render, rendered=second_render)}],
                  "final": evaluate_real01(second, rendered=second_render)}
    meta = {"case_id": "real-01", "graph_status": "completed", "status": "evaluation_incomplete",
            "evaluation_status": "incomplete", "turn_count": 2, "followup_count": 0,
            "version_count": len(versions), "visible_version_count": len(versions),
            "first_draft_turn": 1 if any(item["visible_bullets"] for item in visible_projects(first)) else None,
            "first_draft_version": "v001", "final_version": versions[-1]["version_id"],
            "truth_review_status": case["truth_review_status"], "import_mode": "saved_real_ui_run",
            "new_model_calls": 0, "historical_model_usage": "not_imported", "source_artifacts": str(source.resolve())}
    scores = {"versions": [{"version_id": row["version_id"], "turn": row["turn"], "user_visible": True,
                            "score": {"status": "not_run", "reason": "Private semantic review not authorized; deterministic checks are separate"}}
                           for row in versions],
              "edits": [{"turn": 2, "instruction": user_turns[1], "turn_status": "completed",
                         "score": {"status": "not_run", "substantive_diff": not unchanged}}]}
    for name, data in (("case.json", case), ("turns.json", turns), ("versions.json", versions),
                       ("resume.json", second), ("edit-inputs.json", [edit_input]), ("scores.json", scores),
                       ("meta.json", meta), ("private-acceptance.json", acceptance)):
        save(name, data)
    transcript = ["# real-01 · 原始 UI 对话证据导入（没有重新调用模型）", ""]
    for row in turns:
        transcript.extend([f"## 第 {row['turn']} 轮", "", "### 用户", row["user"], "", "### Agent", row["assistant"], ""])
    (folder / "transcript.md").write_text("\n".join(transcript))
    source_hashes = {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in source.rglob("*") if path.is_file()}
    manifest = {"private": True, "scope": "saved_real_ui_artifact_import", "status": "partial",
                "case_hashes": {"real-01": sha(case)}, "private_case_ids": ["real-01"],
                "writer_model": "deepseek-flash (historical UI run)", "judge_model": None,
                "git_commit": "a742100 (historical business source; not current checkout)",
                "source_artifacts": str(source.resolve()), "source_files_sha256": source_hashes,
                "golden_sha256": case["golden_reference"]["sha256"], "new_model_calls": 0,
                "limitations": ["导入已保存的两轮 UI 实测，没有用当前业务重跑旧链路；当前代码不代表该历史运行。",
                                "仅页数/结构/长度与复合指令执行做确定性检查，语义事实评分仍未运行。",
                                "缺少 session_constraints 历史状态时，该底层操作记 unknown；目标执行与本来满足分开。",
                                "PDF 行数以可唯一定位的实际 PDF 文本为证；缺失/歧义不换算为通过。"]}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    from report import build_report
    return build_report(output)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Import the original private UI test into a new benchmark run; no external calls")
    parser.add_argument("--from-real-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = import_saved_run(args.from_real_run.resolve(), args.output)
    print(json.dumps({"status": report["status"], "output": str(args.output), "new_model_calls": 0}))
