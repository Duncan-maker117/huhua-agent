"""分阶段收集：表单是可选输入通道，阶段与深挖进度只由后端维护。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import uuid
from typing import Annotated, Literal

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.facts import FACT_LABELS
from app.services.resume_facts import new_fact, normalize_fact_store

STAGES = ("basics", "target", "experiences", "deepen", "ready")
MAX_FOLLOWUP_ROUNDS = 6  # 与旧流程离线回放共用的深挖轮数上限。
SECTIONS = ("projects", "work_experience", "internship", "campus", "open_source", "awards")
TYPES = {"项目": "projects", "实习": "internship", "校园": "campus", "竞赛": "awards", "其他": "projects"}
Month = Annotated[str, Field(pattern=r"^(?:\d{4}-(?:0[1-9]|1[0-2]))?$")]


class BasicsValues(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    name: str = Field(default="", max_length=120)
    school: str = Field(default="", max_length=160)
    major: str = Field(default="", max_length=160)
    degree: Literal["", "本科", "硕士", "博士", "大专", "其他"] = ""
    graduation: Month = ""
    location: str = Field(default="", max_length=120)
    availability: str = Field(default="", max_length=300)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=254)

    @model_validator(mode="after")
    def validate_basics(self):
        from app.services.profile_basics import clean_basic, EMAIL, PHONE
        for field in ("name", "location", "availability"):
            value = getattr(self, field)
            if value and clean_basic(field, value)[0] != field:
                raise ValueError("请将链接或联系方式填入对应字段")
        if self.phone and not PHONE.fullmatch(self.phone):
            raise ValueError("请检查手机号码")
        if self.email and not EMAIL.fullmatch(self.email):
            raise ValueError("请检查邮箱")
        return self


class BasicsIntake(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["basics"]
    values: BasicsValues = Field(default_factory=BasicsValues)
    skipped: bool = False


class ExperienceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    item_id: str = Field(default="", max_length=128)
    name: str = Field(min_length=1, max_length=160)
    type: Literal["项目", "实习", "校园", "竞赛", "其他"] = "项目"
    start: Month = ""
    end: str = Field(default="", pattern=r"^(?:\d{4}-(?:0[1-9]|1[0-2])|至今)?$")
    role: str = Field(default="", max_length=160)
    summary: str = Field(default="", max_length=2000)


class ExperiencesIntake(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["experiences"]
    items: list[ExperienceInput] = Field(default_factory=list, max_length=30)
    profile_item_ids: list[str] = Field(default_factory=list, max_length=30)
    skipped: bool = False

    @model_validator(mode="after")
    def require_items(self):
        if not self.skipped and not self.items and not self.profile_item_ids:
            raise ValueError("请至少填写一段经历，或选择跳过")
        return self


Intake = Annotated[BasicsIntake | ExperiencesIntake, Field(discriminator="kind")]


def experiences(state: dict) -> list[tuple[str, dict]]:
    return [(section, item) for section in SECTIONS
            for item in (state.get("collected_info") or {}).get(section) or []
            if isinstance(item, dict) and not item.get("hidden")]


def item_key(section: str, item: dict) -> str:
    # 老 checkpoint 没有 item_id 时，先用稳定名称；下一次收集统一迁移为真实 ID。
    return str(item.get("item_id") or f"{section}:{item.get(FACT_LABELS[section], '')}")


def field_value(item: dict, field: str) -> str:
    active = [fact for fact in item.get("facts") or []
              if fact.get("field") == field and fact.get("status", "active") == "active"]
    if not active and field == "role" and not item.get(field):
        active = [fact for fact in item.get("facts") or [] if fact.get("kind") == "role" and fact.get("status", "active") == "active"]
    return str(active[-1].get("text") if active else item.get(field) or "")


def month_value(value: str) -> str:
    if value == "至今":
        return value
    match = re.search(r"(\d{4})[年./-](\d{1,2})", value)
    return f"{match[1]}-{int(match[2]):02}" if match else ""


def role_value(item: dict) -> str:
    """只投影明确的身份/职位字段；kind=role 也可能是整句职责，不能直接预填。"""
    for field in ("role", "title"):
        active = [fact for fact in item.get("facts") or []
                  if fact.get("field") == field and fact.get("status", "active") == "active"]
        value = str(active[-1].get("text") if active else item.get(field) or "").strip()
        if (not value or len(value) > 40 or re.search(
                r"[，,。；;！？!?\n「」]|我|从.+到|完成|负责(?!人)|参与|担任|做过|帮|开发了|实现|"
                r"拍摄|排版|制作|编写|搭建|通过|用于|并|全流程|^在", value)):
            continue
        if re.search(r"(?:开发者|负责人|实习生|工程师|设计师|经理|助理|专员|顾问|总监|主管|"
                     r"部长|干事|委员|主席|成员|队长|组长|参赛者|志愿者|创始人|维护者|"
                     r"编辑|运营|策划|开发|产品设计|销售|客服|教师|会计|文员|研究员|"
                     r"developer|engineer|designer|manager|intern|owner|lead|PM|SRE|HR)$", value, re.I):
            return value
    return ""


def basics_values(collected: dict) -> dict:
    """表单白名单投影；联系方式只在出站模型边界脱敏。"""
    basic = collected.get("basic_info") or {}
    edu = next(iter(collected.get("education") or []), {})
    degree = field_value(edu, "degree")
    if degree and degree not in {"本科", "硕士", "博士", "大专", "其他"}:
        degree = next((label for pattern, label in (("博士", "博士"), ("硕士|研究生", "硕士"), ("本科|学士", "本科"), ("专科|大专", "大专"))
                       if re.search(pattern, degree)), "其他")
    return {"name": basic.get("name") or "", "location": basic.get("location") or "",
            "availability": basic.get("availability") or "", "phone": basic.get("phone") or "",
            "email": basic.get("email") or "", "school": field_value(edu, "school"),
            "major": field_value(edu, "major"), "degree": degree,
            "graduation": month_value(field_value(edu, "end_date"))}


def profile_basics_complete(values):
    return bool(values.get("name") and any(values.get(key) for key in ("school", "major", "degree")))


def profile_basics_notice(state):
    if (state.get("intake_progress") or {}).get("basics") != "from_profile":
        return ""
    values = basics_values(state.get("collected_info") or {})
    education = " ".join(filter(None, [values["school"], values["major"], values["degree"],
                                       values["graduation"] + " 毕业" if values["graduation"] else ""]))
    contacts = " ".join(label for field, label in (("phone", "手机"), ("email", "邮箱")) if values.get(field))
    return "已沿用档案：" + "｜".join(filter(None, [values["name"], values["location"], education,
                                                       contacts + "已带上" if contacts else ""])) + "；有变化直接说。"


def profile_dimensions(item):
    """已有档案证据覆盖的维度不再追问，不从描述数量猜细节齐全。"""
    from app.services.ask_user import question_dimension
    known = set()
    for fact in item.get("facts") or []:
        if not fact.get("profile_refs") or fact.get("status", "active") != "active":
            continue
        field = fact.get("field") or fact.get("profile_field", "")
        dimension = {"role": "my_work", "title": "my_work", "tool": "tech_stack", "status": "status",
                     "link": "links", "start_date": "dates", "end_date": "dates"}.get(field)
        if dimension:
            known.add(dimension)
        if fact.get("question_id"):
            known.add(question_dimension(fact["question_id"], fact.get("question_prompt", "")))
    return known


def _write_field(target: dict, field: str, value: str, message: HumanMessage):
    if not value:
        return  # 空白表示本轮不补充，不删除已有事实。
    for old in target.setdefault("facts", []):
        if old.get("field") == field and old.get("status", "active") == "active":
            if old.get("text") == value and old.get("turn_id") == message.id:
                target[field] = value
                return
            old["status"] = "superseded"
    fact = new_fact(value, kind="role" if field in {"role", "title"} else "context",
                    quote=value, turn_id=message.id or "", source_name="用户本人填写")
    labels = {"name": "名称", "company": "名称", "school": "学校", "major": "专业", "degree": "学历",
              "start_date": "开始时间", "end_date": "结束时间", "role": "角色", "title": "角色",
              "intake_type": "经历类型", "location": "城市", "availability": "可实习时间"}
    provenance = {"question_id": field, "question_prompt": labels.get(field, field),
                  "answer_value": value, "item_id": target.get("item_id", "")}
    fact.update(provenance)
    fact["sources"][0].update(provenance)
    target["facts"].append({**fact, "field": field})
    target[field] = value


def apply_submission(state: dict, submission: dict, message: HumanMessage) -> dict:
    collected = normalize_fact_store(state.get("collected_info") or {})
    progress = deepcopy(state.get("intake_progress") or {})
    kind = submission["kind"]
    progress[kind] = "skipped" if submission.get("skipped") else "confirmed"
    if submission.get("skipped"):
        return {"collected_info": collected, "intake_progress": progress}
    if kind == "basics":
        values = submission.get("values") or {}
        basic = collected.setdefault("basic_info", {})
        # 基本信息本身没有 facts 数组；其证据另存，避免混入 ResumeData 的字段。
        evidence = {"facts": collected.get("basic_info_facts") or []}
        for key in ("name", "location", "availability", "phone", "email"):
            if key not in {"phone", "email"}:
                _write_field(evidence, key, values.get(key, ""), message)
            if values.get(key):
                basic[key] = values[key]
        collected["basic_info_facts"] = evidence["facts"]
        if any(values.get(key) for key in ("school", "major", "degree", "graduation")):
            rows = collected.setdefault("education", [])
            target = next((row for row in rows if row.get("school") == values.get("school")), None)
            if target is None:
                target = rows[0] if len(rows) == 1 else {"item_id": str(uuid.uuid4()), "facts": []}
                if not rows or target not in rows:
                    rows.append(target)
            for source, field in (("school", "school"), ("major", "major"), ("degree", "degree"), ("graduation", "end_date")):
                _write_field(target, field, values.get(source, ""), message)
    else:
        for row in submission.get("items") or []:
            pairs = experiences({"collected_info": collected})
            found = next(((section, item) for section, item in pairs
                          if row.get("item_id") and item.get("item_id") == row["item_id"]), None)
            if found is None:
                found = next(((section, item) for section, item in pairs
                              if item.get(FACT_LABELS[section], "").strip().casefold() == row["name"].strip().casefold()), None)
            section = TYPES[row["type"]]
            if found:
                previous_section, target = found
                # 未改变类型时保留 work/open_source 等原栏目，不把预填的「其他」搬成项目。
                if row["type"] == experience_type(previous_section, target):
                    section = previous_section
                if section != previous_section:
                    collected[previous_section].remove(target)
                    collected.setdefault(section, []).append(target)
            else:
                target = {"item_id": str(uuid.uuid4()), "facts": []}
                collected.setdefault(section, []).append(target)
            target["intake_type"] = row["type"]
            for source, field in (("name", FACT_LABELS[section]), ("start", "start_date"),
                                  ("end", "end_date"), ("role", "title" if section in {"work_experience", "internship"} else "role")):
                _write_field(target, field, row.get(source, ""), message)
            # 简介也是用户确认的原话；事实与写稿分离，不能依赖模型恰好再次抽中。
            from app.services.answer_facts import append_answer
            _write_field(target, "intake_type", row["type"], message)
            if row.get("summary"):
                append_answer(target, row["summary"], message=message, question_id="summary",
                              prompt="一句话简介", kind="action")
                target["intake_summary"] = row["summary"]
                target["raw_notes"] = list(dict.fromkeys([*target.get("raw_notes", []), row["summary"]]))
    return {"collected_info": collected, "intake_progress": progress}


def experience_type(section: str, item: dict) -> str:
    return item.get("intake_type") or {"projects": "项目", "internship": "实习", "work_experience": "实习",
                                      "campus": "校园", "awards": "竞赛"}.get(section, "其他")


def target_known(state: dict) -> bool:
    jd = state.get("jd_info") or {}
    return bool(state.get("jd_text") or state.get("jd_keywords") or jd.get("job_title")
                or jd.get("role_direction") or jd.get("role_profile") or state.get("role_direction"))


def direct_requested(state: dict) -> bool:
    from app.agents.resume_graph import _explicit_generate_requested
    message = next((m for m in reversed(state.get("messages") or []) if isinstance(m, HumanMessage)), None)
    if not message or message.additional_kwargs.get("intake"):
        return False
    text = message.content.strip()
    # 「跳过这题」仍属于 ask_user；只有独立的全流程跳过才越过阶段。
    return _explicit_generate_requested(text) or bool(re.fullmatch(r"(?:(?:不用|不必)确认|(?:全部|都|先)?跳过)[。！!\s]*", text))


def _skeleton(section: str, item: dict) -> bool:
    from app.services.candidate_language import placeholder_name
    return bool(not placeholder_name(item.get(FACT_LABELS[section], ""))
                and ((field_value(item, "start_date") and field_value(item, "end_date"))
                     or field_value(item, "date") or field_value(item, "duration")))


def intake_update(state: dict) -> dict:
    progress = deepcopy(state.get("intake_progress") or {})
    rows = experiences(state)
    # 旧成稿/已确认方案继续原流程；仅有收集中实时预览不算成稿。
    legacy_ready = bool(state.get("pending_plan") or state.get("confirmed_plan") or state.get("resume_versions")
                        or state.get("stage") in {"EVALUATING", "EXPORT"}
                        or ("intake_stage" not in state and (state.get("stage") == "BUILDING"
                            or (state.get("resume_data") and not state.get("collected_info")))))
    if state.get("intake_stage") == "ready" or legacy_ready or direct_requested(state):
        return {"intake_stage": "ready", "intake_progress": progress}
    basic = basics_values(state.get("collected_info") or {})
    human_text = "\n".join(str(m.content) for m in state.get("messages") or [] if isinstance(m, HumanMessage))
    if state.get("intake_account") and profile_basics_complete(basics_values(state.get("intake_profile") or {})) and not progress.get("basics"):
        progress["basics"] = "from_profile"
    provided = any(basic.values()) and (not state.get("intake_profile")
                                       or any(value and value in human_text for value in basic.values()))
    if provided and progress.get("basics") in {None, "deferred"}:
        progress["basics"] = "provided"
    if not progress.get("basics") and (target_known(state) or rows):
        progress["basics"] = "deferred"
    if not progress.get("basics"):
        stage = "basics"
    elif not target_known(state) and not rows:
        stage = "target"
    elif not rows or (not progress.get("experiences") and not all(_skeleton(s, i) for s, i in rows)):
        stage = "experiences"
    else:
        stage = "deepen"
        deep = progress.setdefault("deepen", {})
        for section, item in rows:
            entry = deep.setdefault(item_key(section, item), {"asked_dimensions": [], "rounds": 0, "complete": False})
            from app.services.ask_user import subject_key
            closed = [row for row in state.get("closed_questions") or []
                      if subject_key(row.get("subject", ""), state) == subject_key(item.get("item_id") or item.get(FACT_LABELS[section]), state)]
            entry["closed_dimensions"] = list(dict.fromkeys(row.get("dimension") for row in closed if row.get("dimension")))
            if "intake_stage" not in state and closed and not entry["asked_dimensions"]:
                # 迁移第十四批 a 的关闭记录：已经答过的维度也是已完成的深挖轮次。
                entry["asked_dimensions"] = list(entry["closed_dimensions"])
                entry["rounds"] = len({row.get("turn_id") for row in closed})
            known = profile_dimensions(item)
            if {"my_work", "tech_stack", "status"} <= known:
                entry["complete"] = True
            asked = set(entry["asked_dimensions"])
            if asked and asked <= set(entry["closed_dimensions"]):
                without_fact = all(row.get("reason") in {"unknown", "skipped"} for row in closed if row.get("dimension") in asked)
                entry["complete"] = len(asked) >= 2 or without_fact
        done = all(deep[item_key(s, i)]["complete"] for s, i in rows)
        if done and any(_skeleton(s, i) and (deep[item_key(s, i)]["rounds"] or profile_dimensions(i)) for s, i in rows):
            if progress.get("basics") != "deferred":
                stage = "ready"
    previous = state.get("intake_stage")
    if previous in STAGES and STAGES.index(previous) > STAGES.index(stage):
        stage = previous  # 已走过的阶段不倒退，缺项可用同阶段表单或自由文本补齐。
    return {"intake_stage": stage, "intake_progress": progress}


def current_experience(state: dict) -> tuple[str, dict] | None:
    update = intake_update(state)
    if update["intake_stage"] != "deepen":
        return None
    deep = update["intake_progress"].get("deepen") or {}
    return next(((s, i) for s, i in experiences(state) if not deep.get(item_key(s, i), {}).get("complete")), None)


def intake_guidance(state: dict) -> dict | None:
    from app.config import get_settings
    if getattr(get_settings(), "AGENT_MODE", "off") == "loop":
        return None
    update = intake_update(state)
    stage, progress = update["intake_stage"], update["intake_progress"]
    if stage == "ready":
        return None
    kind = "basics" if stage == "basics" else "experiences" if stage == "experiences" else ""
    if stage == "deepen" and not current_experience({**state, **update}):
        if progress.get("basics") == "deferred":
            kind = "basics"
        elif not any(_skeleton(s, i) for s, i in experiences(state)):
            kind = "experiences"
    if not kind:
        return None
    if progress.get(kind) == "skipped":
        return None
    if kind == "basics":
        values = {**basics_values(state.get("intake_profile") or {}), **{
            k: v for k, v in basics_values(state.get("collected_info") or {}).items() if v}}
        # 全空时 missing_fields 包含全部字段；它表示待填项，不表示已有档案。
        card = {"kind": "intake_basics", "title": "补充基本信息" if any(values.values()) else "基本信息", "values": values,
                "missing_fields": [key for key, value in values.items() if not value]}
    else:
        from app.services.candidate_language import placeholder_name
        items = [{"item_id": item.get("item_id") or "", "name": "" if placeholder_name(item.get(FACT_LABELS[section], "")) else item.get(FACT_LABELS[section]) or "",
                  "type": experience_type(section, item), "start": month_value(field_value(item, "start_date")),
                  "end": month_value(field_value(item, "end_date") or field_value(item, "date")),
                  "role": role_value(item),
                  "summary": (item.get("intake_summary") or item.get("raw_description") or item.get("description")
                              or next((f.get("source_quote") or f.get("text") for f in item.get("facts") or []
                                       if not f.get("field") and f.get("kind") != "role" and f.get("status", "active") == "active"), ""))[:2000]}
                 for section, item in experiences(state)]
        from app.services.profile_tools import rank_items, relevance, role_query
        query = role_query(state)
        catalog = rank_items(state.get("profile_items") or [], query)[:30]
        selected = [item["id"] for item in catalog if query and relevance(item, query) > 0][:3]
        card = {"kind": "intake_experiences", "title": "从档案选经历" if catalog else "经历清单", "items": items,
                "profile_items": [{k: v for k, v in item.items() if k != "fact_ids"} for item in catalog],
                "selected_profile_ids": selected}
    card["turn_id"] = hashlib.sha256(json.dumps([card, progress.get(kind)], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return card


def deepen_dimensions(family: str) -> dict:
    """Shared role dimensions, independent of intake stage or draft presence."""
    from app.agents.career_prompt import playbook_followups
    from app.services.ask_user import question_dimension
    if family == "ai_pm":
        dimensions = {"problem": "问题定义", "my_work": "本人分工", "decision": "关键产品决策", "iteration": "badcase 与迭代",
                      "evaluation": "评测方式", "tech_stack": "技术栈", "status": "现状", "links": "链接",
                      "adoption": "使用人数（可选，个人项目不强制追问）"}
    else:
        dimensions = {}
        for index, question in enumerate(playbook_followups(family)):
            dimension = question_dimension(prompt=question)
            dimensions[dimension if re.fullmatch(r'[a-z][a-z0-9_-]*', dimension) else f'playbook_{index + 1}'] = question
        dimensions.setdefault("my_work", "本人分工")
    return dimensions


def deepen_context(state: dict) -> dict:
    from app.agents.career_prompt import ROLE_PLAYBOOKS, load_skill
    update = intake_update(state)
    current = current_experience(state)
    from app.services.followup_context import latest_followup
    asked_target = any(re.search(r"岗位|方向|想投", latest_followup(str(m.content)))
                       for m in state.get("messages") or [] if isinstance(m, AIMessage))
    from app.services.job_intel.integration import market_context
    context = {**update, "market_context": market_context(state), "instruction": "表单可跳过，任何自由文本照常抽取。岗位方向是可选信息，有经历就继续经历清单与深挖，不等待方向。"}
    if not target_known(state):
        context["instruction"] += (" 已在正文问过岗位方向，不再追问。" if asked_target else
                                   " 本轮可在正文顺带问一次目标岗位，不出方向问题卡，不阻塞经历收集。")
        if update['intake_stage'] == 'target' and not asked_target:
            context['instruction'] += ' target 阶段只在正文开放询问岗位方向，不出问题卡。'
    if not current:
        context["instruction"] += " 当前尚未到深挖，或深挖已经结束，不调用 ask_user；有表单时简短说明即可。"
        return context
    section, item = current
    family = str(((state.get("jd_info") or {}).get("role_profile") or {}).get("role_family") or "other").replace("-", "_")
    dimensions = deepen_dimensions(family)
    entry = update["intake_progress"].get("deepen", {}).get(item_key(section, item), {})
    closed = set(entry.get("closed_dimensions") or []) | profile_dimensions(item)
    context.update(subject=item.get(FACT_LABELS[section]) or "", item_id=item.get("item_id"),
                   dimensions=dimensions, remaining_dimensions=[d for d in dimensions if d not in closed],
                   current_progress=entry, playbook=load_skill("role-playbooks/" + ROLE_PLAYBOOKS.get(family, "general.md")))
    context["instruction"] = ("只深挖当前 subject 这一段；按下列岗位手册选总共 2–4 个有价值维度，通过 ask_user 提问，"
                              "subject 必须等于经历原名。单个纯开放问题可正文询问。已关闭维度不再问，不必问遍所有维度。"
                              "个人开发项目不必问用户数。回答或跳过本段所选问题后再换下一段。")
    return context


def record_questions(state: dict, replies: list) -> dict:
    update = intake_update(state)
    current = current_experience({**state, **update})
    if not current or intake_guidance({**state, **update}):
        return update
    from app.services.ask_user import question_dimension
    from app.services.followup_context import latest_followup
    section, item = current
    entry = update["intake_progress"]["deepen"][item_key(section, item)]
    allowed = deepen_context({**state, **update}).get("dimensions") or {}
    for message in replies:
        if not isinstance(message, AIMessage):
            continue
        card = message.additional_kwargs.get("ask_user") or {}
        questions = card.get("questions") or []
        if not questions and (question := latest_followup(message.content)):
            questions = [{"prompt": question}]
        dimensions = [question_dimension(q.get("id", ""), q["prompt"]) for q in questions]
        dimensions = [dimension for dimension in dimensions if dimension in allowed]
        if dimensions:
            entry["asked_dimensions"] = list(dict.fromkeys([*entry["asked_dimensions"], *dimensions]))
            entry["rounds"] += 1
    return update


def close_free_reply(state: dict, text: str, closed: list[dict], *, structured: bool = False) -> list[dict]:
    """记录自由回答的对话进度，不把关闭记录当成已确认的事实。"""
    if structured or not current_experience(state) or not text.strip() or direct_requested({**state, "messages": [HumanMessage(content=text)]}):
        return closed
    from app.agents.router import is_greeting, is_advice
    from app.agents.resume_graph import _has_jd_text, _looks_like_role_direction
    if is_greeting(text) or is_advice(text) or _has_jd_text(text) or _looks_like_role_direction(text) or re.search(r'另一个|另一段|还有.{0,5}(?:项目|经历)', text):
        return closed
    from app.services.ask_user import pending_card, question_dimension, subject_key
    from app.services.followup_context import latest_followup
    card = pending_card(state)
    if not card:
        message = next((m for m in reversed(state.get("messages") or []) if isinstance(m, AIMessage)), None)
        question = latest_followup(message.content) if message else ""
        if not question:
            return closed
        section, item = current_experience(state)
        card = {"subject": item.get(FACT_LABELS[section]), "questions": [{"id": question_dimension(prompt=question), "prompt": question}]}
    result = deepcopy(closed)
    # 单题回答或整组自由回复都结束本轮所问维度；内容仍须经过抽取与事实校验。
    reason = "unknown" if re.fullmatch(r"(?:都|全部)?(?:不知道|不清楚|没有|跳过)[。！!\s]*", text.strip()) else "answered"
    for q in card["questions"]:
        dimension = question_dimension(q.get("id", ""), q["prompt"])
        subject = subject_key(card.get("subject", ""), state)
        if not any(r.get("subject") == subject and r.get("dimension") == dimension for r in result):
            result.append({"subject": subject, "id": q.get("id", dimension), "dimension": dimension,
                           "prompt": q["prompt"], "reason": reason, "turn_id": card.get("turn_id", "")})
    return result
