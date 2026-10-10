"""Evidence-linked follow-up questions after a resume draft is written."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from app.services.resume_facts import active_facts_for_writer


MAX_QUESTIONS = 3
NO_ANSWER = re.compile(r"^(?:不知道|不清楚|没有|暂无|暂时没有|没数字|没有数字|记不清|跳过|先不答|不知道\s*/\s*没有)[。！!\s]*$")
GENERATE_REQUEST = re.compile(
    r"出一版|写一版|生成吧|直接写吧|先出稿|先给我出|按现有材料生成|(?:生成|整理|写|输出).{0,12}(?:简历|草稿)"
)


def _latest_user_text(state: dict) -> str:
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", "") == "human" and isinstance(getattr(message, "content", None), str):
            return message.content
    return ""


def first_draft_ready(state: dict) -> bool:
    """Generate as soon as the minimum role and one two-fact experience exist."""
    text = _latest_user_text(state)
    if state.get("requested_task") == "generate" or (
        GENERATE_REQUEST.search(text) and not re.search(r"不要|先别|暂不|不想|还不", text)
    ):
        return True
    jd = state.get("jd_info") or {}
    has_role = bool(state.get("jd_text") or jd.get("job_title") or jd.get("role_direction")
                    or state.get("role_direction"))
    evidence = active_facts_for_writer(state.get("collected_info") or {})
    has_experience = any(len(item.get("facts") or []) >= 2 for section in
                         ("projects", "work_experience", "internship") for item in evidence.get(section) or [])
    return bool(has_role and has_experience)


def _item_has_role(collected: dict, item_id: str) -> bool:
    evidence = active_facts_for_writer(collected or {})
    for section in ("projects", "work_experience", "internship"):
        for item in evidence.get(section) or []:
            if item.get("item_id") == item_id and any(
                fact.get("kind") == "role" for fact in item.get("facts") or []
            ):
                return True
    return False


def _known_targets(data: dict) -> dict[str, tuple[str, int, dict]]:
    return {item["item_id"]: (section, index, item)
            for section in ("projects", "work_experience")
            for index, item in enumerate(data.get(section) or [])
            if isinstance(item, dict) and item.get("item_id") and item.get("hidden") is not True}


def _question_id(question: str, item_id: str, req_id: str) -> str:
    key = f"{item_id}|{req_id}|{re.sub(r'\s+', '', question).casefold()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _asked_ids(rows: list) -> set[str]:
    return {row if isinstance(row, str) else str(row.get("question_id") or row.get("id") or "")
            for row in rows if isinstance(row, (str, dict))}


def _question_location(item_id: str, req_id: str, target: tuple[str, int, dict],
                       match_plan: dict, resume_meta: dict) -> tuple[str, str]:
    section, index, item = target
    field = "polished_bullets" if section == "projects" else "bullets"
    bullets = item.get(field) or []
    requirement = next((row for row in match_plan.get("requirements") or []
                        if row.get("req_id") == req_id), {})
    req_facts = set(requirement.get("fact_ids") or [])
    bullet_meta = (resume_meta.get("bullets") or {}).get(item_id) or []
    position = next((number for number, row in enumerate(bullet_meta)
                     if req_facts and req_facts.intersection(row.get("fact_ids") or [])
                     and number < len(bullets)), 0)
    name = item.get("name") or item.get("company") or "这段经历"
    if bullets:
        return f"/{section}/{index}/{field}/{position}", f"{name} 第 {position + 1} 条"
    return f"/{section}/{index}", name


def _pre_draft_question(state: dict) -> dict:
    jd = state.get("jd_info") or {}
    has_role = bool(state.get("jd_text") or jd.get("job_title") or jd.get("role_direction")
                    or state.get("role_direction"))
    if not has_role:
        q = "你想投什么岗位？有 JD 可以直接贴，没有也可以说方向。"
        options = [("粘贴 JD", "我想先贴目标岗位 JD。"),
                   ("说岗位方向", "我想投产品实习方向。"),
                   ("先写通用版", "先按现有材料生成通用简历。")]
        kind = "role_direction"
    else:
        q = "说说你做过的一件最相关的事：你本人做了什么，产出了什么？"
        options = [("项目", "我想先讲一个项目及我做的部分。"),
                   ("实习", "我想先讲一段实习及我做的部分。"),
                   ("校园经历", "我想先讲一段校园经历及我做的部分。")]
        kind = "experience"
    return {"question_id": kind, "q": q, "why": "补齐首稿所需的最少信息。",
            "improves": {"item_id": "", "req_id": ""}, "location_path": "",
            "location_label": "首稿", "options": [{"label": label, "value": value} for label, value in options],
            "value": 5}


def education_question(state: dict) -> tuple[str, list]:
    """One school-abbreviation question per conversation, owned by the interviewer."""
    from app.agents.turn_actions import education_confirmation, parse_education_fields

    note = education_confirmation(parse_education_fields(_latest_user_text(state)))
    asked = deepcopy(state.get("asked_questions") or [])
    if not note:
        return "", asked
    question_id = "education_full_name"
    if question_id in _asked_ids(asked):
        return "", asked
    asked.append({"question_id": question_id, "status": "asked", "q": note})
    return note, asked


def _question_candidates(state: dict, plan: dict, profile: dict, data: dict, already: set[str]) -> list[dict]:
    """All displayable follow-up questions for known visible items, minus `already`."""
    known = _known_targets(data)
    valid_reqs = {row.get("id") for row in profile.get("requirements") or [] if isinstance(row, dict)}
    valid_reqs.update(row.get("req_id") for row in plan.get("requirements") or [] if isinstance(row, dict))
    candidates = []
    for candidate in plan.get("questions") or []:
        if not isinstance(candidate, dict):
            continue
        q = str(candidate.get("q") or "").strip()
        if re.search(r"和「[^」]{1,40}」(?:直接)?相关的部分", q):
            continue  # 把岗位信号名套进模板的问句不用，改由手册问句/模型原生问句承担
        improvement = candidate.get("improves") or {}
        item_id, req_id = improvement.get("item_id") or "", improvement.get("req_id") or ""
        if not q or item_id not in known or (req_id and req_id not in valid_reqs):
            continue
        identifier = _question_id(q, item_id, req_id)
        if identifier in already:
            continue
        if re.search(r"职责|分工|独立完成|团队协作|一个人", q) and _item_has_role(
            state.get("collected_info") or {}, item_id
        ):
            continue
        path, label = _question_location(item_id, req_id, known[item_id], plan,
                                         state.get("resume_meta") or {})
        options = [{"label": str(option)[:60], "value": str(option)}
                   for option in candidate.get("options") or [] if isinstance(option, str) and option.strip()][:3]
        options.append({"label": "不知道 / 没有", "value": "不知道 / 没有"})
        try:
            value = max(1, min(5, int(candidate.get("value") or 1)))
        except (TypeError, ValueError):
            value = 1
        candidates.append({"question_id": identifier, "q": q, "why": str(candidate.get("why") or ""),
                           "improves": {"item_id": item_id, "req_id": req_id},
                           "location_path": path, "location_label": label,
                           "options": options, "value": value})
    return candidates


def _playbook_candidates(state: dict, plan: dict, profile: dict, data: dict, already: set[str],
                         taken: set[str], needed: int) -> list[dict]:
    """规划器没给够问题时，用岗位手册「高价值追问」补齐：只问该条目事实里还没出现对应线索的，先每条目一个。"""
    from app.agents.career_prompt import _FOLLOWUP_CUES, playbook_followups
    known = _known_targets(data)
    questions = playbook_followups(profile.get("role_family") or "other")
    if not known or not questions or needed <= 0:
        return []
    evidence = active_facts_for_writer(state.get("collected_info") or {})
    facts_by_item = {item.get("item_id"): " ".join(str(f.get("text") or "") for f in item.get("facts") or [])
                     for section in ("projects", "work_experience", "internship")
                     for item in evidence.get(section) or [] if isinstance(item, dict)}
    lead = [row.get("item_id") for row in plan.get("experience_plan") or [] if row.get("treatment") == "lead"]
    order = [i for i in lead if i in known] + [i for i in known if i not in lead]
    per_item: list[list[dict]] = []
    for item_id in order:
        text = facts_by_item.get(item_id, "")
        name = known[item_id][2].get("name") or known[item_id][2].get("company") or "这段经历"
        rows = []
        for question in questions:
            cue = next((cues for keys, cues in _FOLLOWUP_CUES if re.search(keys, question)), "")
            if cue and re.search(cue, text):
                continue
            if re.search(r"职责|分工|独立完成|团队协作|一个人|自己做|自己写", question) and _item_has_role(
                    state.get("collected_info") or {}, item_id):
                continue
            q = f"{name}：{question}"
            identifier = _question_id(q, item_id, "")
            if identifier in already or identifier in taken:
                continue
            path, label = _question_location(item_id, "", known[item_id], plan, state.get("resume_meta") or {})
            rows.append({"question_id": identifier, "q": q, "why": "岗位手册里这一类经历最常被追问的信号",
                         "improves": {"item_id": item_id, "req_id": ""}, "location_path": path,
                         "location_label": label, "value": 3,
                         "options": [{"label": "不知道 / 没有", "value": "不知道 / 没有"}]})
        per_item.append(rows)
    output = []
    for depth in range(len(questions)):  # 轮流从每个条目取，避免只问第一个条目
        for rows in per_item:
            if depth < len(rows) and len(output) < needed:
                output.append(rows[depth])
    return output


def compose_interviewer_reply(state: dict, *, match_plan: dict | None = None,
                              role_profile: dict | None = None,
                              version_number: int | None = None) -> dict:
    """Compose a bounded reply and guidance without editing facts or the draft."""
    plan = match_plan if match_plan is not None else state.get("match_plan") or {}
    profile = role_profile if role_profile is not None else (state.get("jd_info") or {}).get("role_profile") or {}
    data = state.get("resume_data") or {}
    asked = deepcopy(state.get("asked_questions") or [])
    has_draft = bool(data.get("projects") or data.get("work_experience") or data.get("education"))
    ready = first_draft_ready(state)
    if not has_draft:
        if ready:
            return {"text": "已有材料足以先生成一版草稿；缺少的细节会在首稿后再问。",
                    "questions": [], "guidance": {"title": "先出首稿", "question": "按现有材料生成草稿？",
                                             "why": "先写后问，未提供的事实不会代填。",
                                             "options": [{"label": "生成草稿", "value": "按现有材料生成简历草稿。"}],
                                             "allow_free_text": True},
                    "asked_questions": asked, "ready_for_first_draft": True,
                    "pre_draft_rounds": len([row for row in asked if isinstance(row, dict)
                                             and row.get("question_id") in {"role_direction", "experience"}]),
                    "next_action": "write"}
        question = _pre_draft_question(state)
        previously_asked = question["question_id"] in _asked_ids(asked)
        if previously_asked:
            return {"text": "首稿还缺目标方向或一段足够具体的经历。可以补充真实信息，也可以明确说“先按现有材料生成”。",
                    "questions": [],
                    "guidance": {"title": "首稿还差一步", "question": "补充事实，还是先按现有材料生成？",
                                 "why": "缺失内容不会由系统代填。",
                                 "options": [{"label": "补充经历", "value": "我想补充一段真实经历。"},
                                             {"label": "先生成", "value": "先按现有材料生成简历。"}],
                                 "allow_free_text": True},
                    "asked_questions": asked, "ready_for_first_draft": False,
                    "pre_draft_rounds": len([row for row in asked if isinstance(row, dict)
                                             and row.get("question_id") in {"role_direction", "experience"}]),
                    "next_action": "await_user_or_generate"}
        asked.append({"question_id": question["question_id"], "status": "asked"})
        guidance = {"title": "先补齐首稿", "question": question["q"], "why": question["why"],
                    "options": question["options"], "allow_free_text": True}
        return {"text": question["q"], "questions": [question], "guidance": guidance,
                "asked_questions": asked, "ready_for_first_draft": False,
                "pre_draft_rounds": len([row for row in asked if isinstance(row, dict)
                                         and row.get("question_id") in {"role_direction", "experience"}]),
                "next_action": "ask"}
    known = _known_targets(data)
    already = _asked_ids(asked)
    candidates = _question_candidates(state, plan, profile, data, already)
    if len(candidates) < MAX_QUESTIONS:
        candidates += _playbook_candidates(state, plan, profile, data, already,
                                           {row["question_id"] for row in candidates},
                                           MAX_QUESTIONS - len(candidates))
    selected = sorted(candidates, key=lambda row: -row["value"])[:MAX_QUESTIONS]
    role = ((state.get("jd_info") or {}).get("job_title")
            or (state.get("jd_info") or {}).get("role_direction")
            or data.get("basic_info", {}).get("objective") or "目标岗位")
    version = version_number if version_number is not None else (len(state.get("resume_versions") or []) + 1)
    lead = f"已按「{role}」更新第 {version} 版简历，右侧可以查看。"
    treatments = plan.get("experience_plan") or []
    lead_items = [row.get("item_id") for row in treatments if row.get("treatment") == "lead"]
    backup_items = [row.get("item_id") for row in treatments if row.get("treatment") == "backup"]
    reasons = []
    evidence = active_facts_for_writer(state.get("collected_info") or {})
    item_facts = {item.get("item_id"): {fact.get("id") for fact in item.get("facts") or []}
                  for section in ("projects", "work_experience", "internship")
                  for item in evidence.get(section) or []}
    req_text = {row.get("id"): row.get("text") for row in profile.get("requirements") or []
                if isinstance(row, dict)}
    if lead_items:
        for item_id in lead_items:
            if item_id not in known:
                continue
            name = known[item_id][2].get("name") or known[item_id][2].get("company")
            requirement = next((row for row in plan.get("requirements") or []
                                if row.get("status") in {"direct", "transferable"}
                                and item_facts.get(item_id, set()).intersection(row.get("fact_ids") or [])
                                and req_text.get(row.get("req_id"))), None)
            cited = {fid for bullet in (state.get("resume_meta") or {}).get("bullets", {}).get(item_id) or []
                     if isinstance(bullet, dict) for fid in bullet.get("fact_ids") or []}
            written = [fact for item in evidence.get("projects", []) + evidence.get("work_experience", [])
                       + evidence.get("internship", []) if item.get("item_id") == item_id
                       for fact in item.get("facts") or []
                       if fact.get("id") in cited and fact.get("id") in (requirement or {}).get("fact_ids", [])]
            # 思路句只引用正文实际出现的事实，不把整条 JD 要求当作已被证明。
            if name and requirement and written:
                quoted = "」「".join(str(f.get("text") or "")[:24] for f in written[:2])
                reasons.append(f"突出了 {name}：正文写到「{quoted}」，对应岗位要求「{req_text[requirement['req_id']]}」。")
            if len(reasons) >= 2:
                break
    if backup_items:
        reasons.append(f"将 {len(backup_items)} 段相关性较低的经历留作备用，仍可恢复。")
    if not reasons:
        reasons.append("按已确认事实整理了当前文稿，未补入缺少证据的成果或数字。")
    transferable = [row for row in plan.get("requirements") or [] if row.get("status") == "transferable"]
    prior_plan = (state.get("resume_meta") or {}).get("match_plan") or {}
    def _signature(value):
        return [(row.get("item_id"), row.get("treatment")) for row in (value or {}).get("experience_plan") or []]
    explain = len(state.get("resume_versions") or []) <= 1 or _signature(prior_plan) != _signature(plan)
    parts = [lead]
    if explain:
        parts.append("\n**这版的思路**：" + " ".join(reasons[:3]))
        in_draft = {fid for rows in (state.get("resume_meta") or {}).get("bullets", {}).values()
                    for bullet in rows if isinstance(bullet, dict) for fid in bullet.get("fact_ids") or []}
        for row in [r for r in transferable if not in_draft or in_draft.intersection(r.get("fact_ids") or [])][:2]:
            req = req_text.get(row.get("req_id")) or row.get("text") or ""
            name = next((known[item_id][2].get("name") or known[item_id][2].get("company")
                         for item_id, ids in item_facts.items()
                         if item_id in known and ids.intersection(row.get("fact_ids") or [])), "")
            if req and name:
                parts.append(f"\n**可迁移表述**：「{req}」由{name}的已有经历迁移表达。")
    if selected:
        parts.append("\n**想让它更强，回答任意一个就行**：")
        parts.extend(f"{index}. {row['q']}（会改进：{row['location_label']}）"
                     for index, row in enumerate(selected, 1))
    guidance = ({"title": "补充一处就行", "question": selected[0]["q"],
                 "why": f"会改进：{selected[0]['location_label']}。" + selected[0]["why"],
                 "options": selected[0]["options"], "allow_free_text": True}
                if selected else {"title": "草稿已就绪", "question": "接下来想局部修改还是核对当前稿？",
                                  "why": "可以直接说要改的经历或句子。",
                                  "options": [{"label": "核对", "value": "请核对当前简历。"},
                                              {"label": "局部修改", "value": "我想修改当前简历。"}],
                                  "allow_free_text": True})
    asked.extend({"question_id": row["question_id"], "status": "asked"} for row in selected)
    note, asked = education_question({**state, "asked_questions": asked})
    if note:
        parts.append(note)
    return {"text": "\n".join(parts), "questions": selected, "guidance": guidance,
            "asked_questions": asked, "ready_for_first_draft": ready, "next_action": "done"}


def record_interview_answer(asked_questions: list, question_id: str, answer: str) -> dict:
    """Close a question without treating its answer as an established fact."""
    rows = deepcopy(asked_questions or [])
    normalized = (answer or "").strip()
    if not normalized:
        return {"asked_questions": rows, "status": "unanswered", "candidate_turn": "", "facts_added": False}
    status = "closed_without_fact" if NO_ANSWER.fullmatch(normalized) else "answered_pending_extraction"
    existing = next((row for row in rows if isinstance(row, dict)
                     and row.get("question_id") == question_id), None)
    entry = {"question_id": question_id, "status": status}
    if existing is None:
        rows.append(entry)
    else:
        existing.update(entry)
    return {"asked_questions": rows, "status": status,
            "candidate_turn": normalized if status == "answered_pending_extraction" else "",
            "facts_added": False}


def open_questions(state: dict) -> list[dict]:
    """Questions already put to the user and still unanswered; a closed one never reappears."""
    plan = state.get("match_plan") or {}
    status = {row.get("question_id"): row.get("status") for row in state.get("asked_questions") or []
              if isinstance(row, dict)}
    if not status:
        return []
    profile = (state.get("jd_info") or {}).get("role_profile") or {}
    data = state.get("resume_data") or {}
    try:
        rows = _question_candidates(state, plan, profile, data, set())
    except Exception:
        return []
    return [row for row in rows if status.get(row["question_id"]) == "asked"][:MAX_QUESTIONS]
