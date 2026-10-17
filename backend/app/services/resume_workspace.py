"""Read-only view of one conversation's facts, guidance and current resume.

UI choices are complete answers sent only after the user selects one. Building
this projection never selects an answer or turns an option into candidate facts.
This projection is shared by SSE, refresh and history so panels cannot drift.
"""

from __future__ import annotations

import copy
import hashlib
import re
from urllib.parse import urlsplit

from langchain_core.messages import AIMessage, HumanMessage

from app.services.canonical_resume import resume_revision
from app.services.resume_review import review_resume
from app.services.session_store import resume_data_has_content


def bounded_web_sources(sources, *, content_limit=1800) -> list[dict]:
    """Project only bounded display/provenance fields, never provider internals.

    Retrieval still performs its own SSRF checks. This boundary keeps stored
    source metadata safe to render as links and treats dates as supplied data,
    without guessing publication dates from retrieval timestamps.
    """
    result = []
    if not isinstance(sources, list):
        return result
    for source in sources[:5]:
        if not isinstance(source, dict) or not isinstance(source.get("kind"), str) or source["kind"] not in {"job_page", "search_result", "public_page"}:
            continue
        url = source.get("url")
        if not isinstance(url, str) or not url or len(url) > 2048 or any(ord(char) < 32 or ord(char) == 127 for char in url):
            continue
        try:
            parts = urlsplit(url)
            if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                continue
        except ValueError:
            continue

        def text(field, limit):
            value = source.get(field)
            return value.replace("\x00", "").strip()[:limit] if isinstance(value, str) else ""

        item = {"title": text("title", 240), "url": url, "kind": source["kind"],
                "fetched_at": text("fetched_at", 80), "content": text("content", max(0, content_limit))}
        if text("published_at", 80):
            item["published_at"] = text("published_at", 80)
        # This flag describes retrieval's input limit, not this view's excerpt.
        # Older sources omit it; never infer full-page coverage from absence.
        if source["kind"] in {"job_page", "public_page"} and isinstance(source.get("content_truncated"), bool):
            item["content_truncated"] = source["content_truncated"]
        if isinstance(source.get("read_scope"), str) and source["read_scope"] in {"public_page_text", "github_repository_metadata", "github_profile_and_public_repositories"}:
            item["read_scope"] = source["read_scope"]
        if type(source.get("request_count")) is int and 1 <= source["request_count"] <= 4:
            item["request_count"] = source["request_count"]
        if source["kind"] == "job_page" and isinstance(source.get("job_card"), dict):
            card = source["job_card"]
            item["job_card"] = {key: card[key] for key in (
                "company", "job_title", "location", "salary", "requirements", "responsibilities",
                "skills", "bonuses", "url", "source", "provider", "fetched_at", "raw_text") if key in card}
        result.append(item)
    return result


def _strings(values) -> list[str]:
    if isinstance(values, str):
        values = values.splitlines()
    return [value.strip() for value in (values or []) if isinstance(value, str) and value.strip()]


def _latest_turn(values: dict) -> tuple[str, str, str]:
    request, reply, material = "", "", ""
    for message in reversed(values.get("messages") or []):
        if isinstance(message, AIMessage) and not reply:
            if not message.tool_calls and isinstance(message.content, str):
                reply = message.content
        elif isinstance(message, AIMessage) and not message.tool_calls and isinstance(message.content, str):
            reply = message.content + "\n\n" + reply
        if isinstance(message, HumanMessage):
            request = message.content if isinstance(message.content, str) else ""
            material = message.additional_kwargs.get("career_material_type", "")
            if message.id in (values.get("non_candidate_message_ids") or []):
                material = "jd" if values.get("jd_text") == request else "reference"
            break
    return request, reply, material


def _guidance(question: str, why: str, options: list[tuple[str, str]], title="接下来，补充这一点") -> dict:
    return {
        "title": title, "question": question, "why": why,
        "options": [{"label": label, "value": value} for label, value in options],
        "allow_free_text": True,
    }



def _next_step_options() -> list[tuple[str, str]]:
    return [("先生成草稿", "请按已有真实资料生成简历草稿，缺失信息保留待核对提示。"),
            ("继续补充", "我想继续补充真实经历，暂时不生成新草稿。")]


def _question_kind(question: str) -> str:
    # Names and quoted phrases do not themselves make a question about a
    # milestone (for example, an experience called “上线助手”).
    text = re.sub(r"[「『][^」』]*[」』]", "", question)
    if len(re.findall(r"[？?]", text)) > 1 or re.search(r"同时|另外|以及|分别|并且", text):
        return "free_text"
    if re.search(r"为什么|为何|原因|具体.{0,5}(?:步骤|流程|贡献|负责)|负责.{0,6}(?:哪|什么)|哪.{0,5}(?:部分|一步|环节)|算法|原理|难点", text):
        return "free_text"
    implementation = bool(re.search(r"怎么(?:实现|开发)|如何(?:实现|开发)|(?:哪个|哪些|什么).{0,5}实现方式", text))
    ownership = bool(re.search(r"独立.{0,12}(?:还是|或).{0,8}团队|团队.{0,12}(?:还是|或).{0,8}独立|是否.{0,8}独立|独立.{0,8}吗|一个人.{0,8}(?:完成|做)", text))
    milestones = [kind for kind, pattern in (
        ("online", r"上线"), ("usage", r"(?:实际|真实用户|用户|其他人).{0,8}使用|有人.{0,5}(?:用|使用)"),
        ("validation", r"验证"), ("working", r"跑通"),
    ) if re.search(pattern, text)]
    if not (milestones or implementation or ownership) and re.search(r"(?:生成|整理|写).{0,8}(?:草稿|简历)", text) and re.search(r"补充|继续|是否|要不要|还是|想|可以|先|[？?]", text):
        if not re.search(r"(?:生成|整理|写).{0,8}(?:之前|前)|先.{0,20}补充.{0,20}再", text):
            return "next_action"
    if len(milestones) + int(implementation) + int(ownership) > 1:
        return "free_text"
    if implementation:
        return "implementation"
    if ownership:
        return "ownership"
    if milestones and re.search(r"是否|有没有|有无|吗|了没", text):
        return milestones[0]
    return "free_text"


def _question_options(question: str, name: str) -> list[tuple[str, str]]:
    """Only supply choices that answer this question without adding claims."""
    subject = f"在「{name}」里，" if name else ""
    status_subject = f"「{name}」刚问到的这部分" if name else "刚才问到的这部分"
    kind = _question_kind(question)
    if kind == "next_action":
        return _next_step_options()
    if kind == "implementation":
        return [("AI 编程工具辅助", subject + "我使用 AI 编程工具辅助实现。"),
                ("自己编写代码", subject + "我自己编写了代码。"),
                ("现成工具组合", subject + "我用现成工具组合完成。")]
    if kind == "ownership":
        return [("独立完成", subject + "我是独立完成的。"),
                ("团队中负责一部分", subject + "我只负责团队中的一部分工作。"),
                ("暂不确定分工", subject + "我暂时还不能准确说明个人分工，请先保留待核对提示。")]
    if kind == "online":
        return [("已上线", status_subject + "已经上线。"), ("尚未上线", status_subject + "尚未上线。"),
                ("上线状态不确定", status_subject + "是否上线，我暂时不确定。")]
    if kind == "usage":
        return [("已有实际使用", status_subject + "已有实际使用。"), ("尚无实际使用", status_subject + "目前还没有实际使用。"),
                ("使用情况不确定", status_subject + "的实际使用情况，我暂时不确定。")]
    if kind in {"validation", "working"}:
        action = "跑通" if kind == "working" else "验证"
        return [(f"已经{action}", status_subject + f"已经{action}。"), (f"尚未{action}", status_subject + f"尚未{action}。"),
                ("暂时不确定", status_subject + f"是否{action}，我暂时不确定。")]
    return []


def _active_fact_rows(item: dict) -> list[dict]:
    return [fact for fact in item.get("facts") or []
            if isinstance(fact, dict) and fact.get("status", "active") == "active" and str(fact.get("text") or "").strip()]


def _role_is_described(item: dict) -> bool:
    """Do not re-ask a display-field gap when the candidate text already says it.

    This does not populate role, select an answer or mutate the canonical data.
    """
    if any(fact.get("kind") == "role" for fact in _active_fact_rows(item)):
        return True
    text = "\n".join(_strings(item.get("description")) + _strings(item.get("polished_bullets")) + _strings(item.get("bullets"))
                     + [fact.get("text", "") for fact in _active_fact_rows(item)])
    pattern = r"(?:我|本人)(?:主要|独立|具体)?(?:负责|完成|承担)|(?:我|本人)(?:是|作为|担任)(?:独立开发者|独立作者)|(?:^|[\n，。；：:])\s*(?:独立开发者|独立作者|独立完成|独立开发)"
    for match in re.finditer(pattern, text):
        prefix = text[max(0, match.start() - 10):match.start()]
        if not re.search(r"不是|并非|不由|并不|尚未|没有|未曾|别人|他人", prefix):
            return True
    return False


def _wants_draft(request: str) -> bool:
    if re.search(r"(?:不要|先别|暂不|不想|还不).{0,8}(?:生成|整理|写)", request):
        return False
    return bool(re.search(r"(?:生成|整理|写|输出).{0,12}(?:简历|草稿)|(?:没|没有|暂无).{0,6}(?:其他|更多)?补充|(?:资料|信息|经历)(?:就|只有)这些", request))


def build_workspace(values: dict, canonical: dict | None = None) -> dict:
    """Return display data without changing facts or calling a model."""
    canonical = canonical or {}
    facts = values.get("collected_info") or {}
    # An explicit canonical object can represent a deliberate deletion. Never
    # populate its panels from an older collected_info object in that case.
    source = canonical if canonical else facts
    fact_items = []
    for key, kind in (("projects", "项目"), ("work_experience", "工作"), ("internship", "实习"), ("campus", "校园经历"), ("open_source", "开源贡献"), ("awards", "竞赛荣誉")):
        for item in facts.get(key) or []:
            if isinstance(item, dict) and _active_fact_rows(item):
                fact_items.append((key, kind, item))
    items = []
    if fact_items:
        hidden_ids = {
            item.get("item_id"): bool(item.get("hidden"))
            for key, _kind in (("projects", ""), ("work_experience", ""), ("internship", ""), ("campus", ""), ("open_source", ""), ("awards", ""))
            for item in (canonical or {}).get(key) or [] if isinstance(item, dict) and item.get("item_id")
        }
        for _key, kind, item in fact_items:
            name = item.get("name") or item.get("company") or "未命名经历"
            role_facts = [fact.get("text", "") for fact in _active_fact_rows(item) if fact.get("kind") == "role"]
            role = item.get("role") or item.get("title") or (role_facts[0] if role_facts else "")
            bullets = [fact.get("text", "") for fact in _active_fact_rows(item)
                       if fact.get("kind") != "role" and not fact.get("field")]
            if not bullets:
                bullets = [fact.get("text", "") for fact in _active_fact_rows(item) if not fact.get("field")]
            missing = []
            if _key not in {"open_source", "awards"} and not role and not _role_is_described(item):
                missing.append("你的职责与分工")
            if not bullets:
                missing.append("具体动作与交付物")
            if _key not in {"open_source", "awards"} and not (item.get("start_date") or item.get("end_date")):
                missing.append("经历时间")
            items.append({
                "name": str(name), "kind": kind, "role": str(role),
                "item_id": item.get("item_id"),
                "hidden": hidden_ids.get(item.get("item_id"), bool(item.get("hidden"))),
                "period": " — ".join(str(item.get(k)) for k in ("start_date", "end_date") if item.get(k)),
                "bullets": bullets, "missing": missing,
            })
    for key, kind in (() if fact_items else (("projects", "项目"), ("work_experience", "工作"), ("internship", "实习"), ("campus", "校园经历"), ("open_source", "开源贡献"), ("awards", "竞赛荣誉"))):
        for item in source.get(key) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("company") or "未命名经历"
            role = item.get("role") or item.get("title") or ""
            bullets = _strings(item.get("polished_bullets") or item.get("bullets") or item.get("description"))
            missing = []
            if key not in {"open_source", "awards"} and not role and not _role_is_described(item):
                missing.append("你的职责与分工")
            if not bullets:
                missing.append("具体动作与交付物")
            if key not in {"open_source", "awards"} and not (item.get("start_date") or item.get("end_date")):
                missing.append("经历时间")
            items.append({
                "name": str(name), "kind": kind, "role": str(role),
                "item_id": item.get("item_id"), "hidden": bool(item.get("hidden")),
                "period": " — ".join(str(item.get(k)) for k in ("start_date", "end_date") if item.get(k)),
                "bullets": bullets, "missing": missing,
            })

    from app.services.job_intel.background import expire_info
    jd = expire_info(values.get("jd_info"))
    if items and isinstance(jd.get("summary"), str):
        kept = [part for part in re.split(r"(?<=[。！])|\n", jd["summary"])
                if part.strip() and not re.search(r"只给了|没有给我个人|没有个人材料|只有\s*JD|只给了岗位", part)]
        jd["summary"] = "".join(kept).strip()
    basic = copy.deepcopy(source.get("basic_info") or {})
    has_data = resume_data_has_content(canonical)
    request, reply, material = _latest_turn(values)
    stage = values.get("stage") or "JD_INPUT"
    focus = "resume" if has_data else ("experiences" if jd or values.get("jd_skipped") else "jd")
    if material == "jd" or (request and request == values.get("jd_text")):
        focus = "jd"
    elif material == "review":
        focus = "review"
    elif stage == "EXPORT":
        focus = "resume"
    elif stage == "COLLECTING" and items:
        focus = "experiences"

    suggestions = []
    # 正文问句不再投影成卡；只有模型工具结果负责补充问题。
    from app.services.ask_user import pending_card, is_closed
    for item in items:
        item["missing"] = [field for field in item["missing"]
                           if not is_closed(values, item.get("item_id") or item["name"], prompt=field)]
    guidance = None
    if _wants_draft(request) and (items or has_data):
        if stage == "EVALUATING" and has_data:
            guidance = _guidance("先核对当前草稿，还是导出？", "草稿已在右侧，可以核对或局部修改。",
                                 [("核对当前草稿", "请核对简历。"), ("导出当前版本", "导出当前版本"),
                                  ("继续补充", "我想继续补充或更正当前草稿。")], "草稿已就绪")
        else:
            guidance = _guidance("先生成当前草稿，还是继续补充？", "只使用已有真实材料。", _next_step_options(), "选择下一步")
    if guidance:
        guidance.update(kind="next_action", turn_id=hashlib.sha256(
            f"{len(values.get('messages') or [])}:{request}:{reply}".encode()).hexdigest()[:16])
    from app.services.intake import intake_guidance, intake_update
    intake_state = {**values, 'resume_data': canonical}
    # 旧会话的成稿可能只在 canonical 中；工具校验与表单必须看到同一份状态。
    guidance = pending_card(intake_state) or guidance
    guidance = intake_guidance(intake_state) or guidance
    if values.get('pending_plan'):
        from app.services.structure_plan import plan_guidance, ALIASES
        retained = {section for message in values.get('messages') or [] if isinstance(message, HumanMessage)
                    for clause in re.split(r'[。；;\n]', str(message.content))
                    if re.search(r'保留.{0,15}栏目|栏目.{0,15}保留', clause) and not re.search(r'不保留|不要保留', clause)
                    for alias, section in ALIASES.items() if alias in clause}
        guidance = {**plan_guidance(values['pending_plan'], facts, (values.get('jd_info') or {}).get('role_profile'), retained_sections=retained),
                    'turn_id': hashlib.sha256(str(values['pending_plan']).encode()).hexdigest()[:16]}

    advice = re.search(r"(?:\*\*|#{1,3}\s*|【)我的建议(?:\*\*|】)?\s*[:：]?\s*([\s\S]*?)(?=(?:\*\*|#{1,3}\s*|【)需要你补充|$)", reply)
    if advice and advice.group(1).strip():
        suggestions.insert(0, {"title": "这一轮的建议", "detail": advice.group(1).strip()[:1600]})

    if jd:
        highlights = _strings((jd.get("resume_strategy") or {}).get("must_highlight"))
        if highlights:
            suggestions.append({"title": "岗位建议优先呈现", "detail": "、".join(highlights[:3]) + "。只用你实际做过的经历支撑；JD 要求不会自动写成你的技能。"})

    groups = source.get("skill_groups") or {}
    skills = [skill for values in groups.values() for skill in _strings(values)] if groups else _strings(source.get("skills"))
    if fact_items and facts.get("skills"):
        fact_skills = []
        for skill in facts.get("skills") or []:
            if isinstance(skill, dict):
                if skill.get("status", "active") == "active" and skill.get("name"):
                    fact_skills.append(str(skill["name"]))
            elif isinstance(skill, str) and skill.strip():
                fact_skills.append(skill.strip())
        if fact_skills:
            skills = fact_skills
    education_rows = copy.deepcopy((facts.get("education") if fact_items and facts.get("education") else source.get("education")) or [])
    notes = _strings(source.get("verification_notes"))
    if "verification_notes" in facts:
        current_notes = _strings(facts.get("verification_notes"))
        notes = [note for note in notes if not note.startswith("这句没有记下来：") or note in current_notes]
    return {
        "tailor": tailor_metadata(values, canonical),
        "web_sources": bounded_web_sources(values.get("web_sources")),
        "jd": {"info": jd, "keywords": _strings(values.get("jd_keywords")), "raw_text": values.get("jd_text") or ""},
        "experiences": {"items": items, "basic_info": basic, "skills": skills,
                        "education": education_rows,
                        "certificates": _strings(source.get("certificates")),
                        "verification_notes": notes},
        "resume": {"has_data": has_data, "version": resume_revision(canonical)},
        "review": {"items": review_resume(canonical, jd) if has_data else [], "reply": reply if material == "review" else ""},
        "guidance": guidance, "intake_stage": intake_update(intake_state)["intake_stage"], "suggestions": suggestions, "focus": focus,
        "focus_download": stage == "EXPORT" and focus == "resume",
    }


def _open_questions(values: dict, canonical: dict, plan: dict, meta: dict) -> list:
    """旧 interviewer 仅作为模型候选，界面不再另出一组问题。"""
    return []


def tailor_metadata(values: dict, canonical: dict) -> dict:
    """UI contract uses sanitized committed snapshots, never an ahead checkpoint diff."""
    from app.services.resume_versions import document_diff, valid_bullet_metadata
    meta = valid_bullet_metadata(canonical, values.get('resume_meta') or {})
    page = meta.get('page_check') or {}
    if page:
        from app.services.resume_capacity import normalize_session_constraints, resume_data_hash
        try:
            constraints = normalize_session_constraints(values.get('session_constraints'))
            stale = (page.get('data_hash') != resume_data_hash(canonical)
                     or page.get('template_id') != constraints['template_id']
                     or page.get('page_limit') != constraints['page_limit'])
        except (TypeError, ValueError):
            stale = True
        if stale:
            # GET never renders PDFs. Do not present a stale count/fit verdict
            # as a measurement of the current sanitized document.
            meta['page_check'] = {**page, 'status': 'stale', 'pages': None,
                                  'within_page_limit': None,
                                  'reason': 'document_or_page_constraints_changed'}
    history = values.get('resume_versions') or []
    plan = meta.get('match_plan') or values.get('match_plan') or {}
    previous = history[-1].get('resume_data') or {} if history else {}
    diff = document_diff(previous, canonical) if meta.get('version_id') else []
    return {'version_id': meta.get('version_id'), 'diff': diff,
            'change_summary': copy.deepcopy(meta.get('change_summary') or []),
            'match_plan': copy.deepcopy(plan), 'questions': _open_questions(values, canonical, plan, meta),
            'resume_meta': meta, 'session_constraints': copy.deepcopy(values.get('session_constraints') or {}),
            'page_check': copy.deepcopy(meta.get('page_check') or {}),
            'can_undo': bool(history)}
