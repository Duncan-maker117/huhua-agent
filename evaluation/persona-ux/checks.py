"""No model, renderer, database or application imports; check committed API data.

Input: a persona's ordered turn records (see run_persona.py). Missing evidence is
a failure, never a skipped/pass check. Every result has a stable ID and excerpts.
"""
from collections import Counter
from copy import deepcopy
import json
import re

PERSONAS = ("tech", "ops", "career", "service", "design")
EXPERIENCES = ("work_experience", "internship", "projects", "campus", "open_source", "awards")
TURN_ORDER = {
    "tech": ("initial", "recovery", "polish", "correction"),
    "ops": ("initial", "followup", "polish"),
    "career": ("initial", "recovery", "polish", "correction"),
    "service": ("initial", "polish"),
    "design": ("initial", "recovery", "paste", "polish"),
}


def month_key(value):
    match = re.fullmatch(r"\s*(\d{4})\s*[.年/-]\s*(\d{1,2})\s*月?\s*", str(value))
    return (int(match[1]), int(match[2])) if match else None


def strings(value):
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [text for row in value for text in strings(row)]
    if isinstance(value, dict):
        return [text for row in value.values() for text in strings(row)]
    return []


def visible_items(data, section):
    sections = data.get("sections")
    if sections is not None and section not in {row.get("kind") for row in sections}:
        return []
    return [row for row in data.get(section, []) if isinstance(row, dict) and not row.get("hidden")]


def item_text(row):
    """Template's project bullets take precedence over stale description text."""
    headers = [str(row.get(key) or "") for key in
               ("name", "company", "school", "major", "degree", "title", "role", "start_date", "end_date", "highlights")]
    body = row.get("polished_bullets") or row.get("bullets") or row.get("description") or []
    return "\n".join(text for text in headers + strings(body) if text)


def experience_text(data):
    return "\n".join(item_text(row) for section in EXPERIENCES for row in visible_items(data, section))


def skills_text(data):
    return "\n".join(strings(data.get("skill_groups") or data.get("skills") or []))


def resume_text(data):
    basic = data.get("basic_info") or {}
    return "\n".join([*strings({k: basic.get(k) for k in ("name", "objective")}),
                      *[item_text(row) for row in visible_items(data, "education")],
                      experience_text(data), skills_text(data),
                      *strings({k: data.get(k) for k in ("summary", "self_evaluation", "certificates")}),
                      *[str(row.get("content") or "") for row in data.get("sections") or [] if row.get("kind") == "custom"]])


def has_draft(data):
    return any(visible_items(data, section) for section in ("education", *EXPERIENCES))


def has_experience_body(data):
    return any(strings(row.get("polished_bullets") or row.get("bullets") or row.get("description"))
               for section in EXPERIENCES for row in visible_items(data, section))


def supplement_questions(reply):
    markers = list(re.finditer(r"需要你补充", reply))
    if not markers:
        return 0
    if len(markers) > 1:
        return len(markers)
    block = reply[markers[0].end():]
    block = re.split(r"\n\s*(?:#{1,4}\s|\*\*[^*\n]+\*\*|【[^】\n]+】)", block, maxsplit=1)[0]
    bullets = re.findall(r"(?m)^\s*(?:[-*·]|\d+[.、)])\s*\S", block)
    return max(1, len(bullets), len(re.findall(r"[？?]", block)))


def clean_fields(value):
    """Compare content, ignoring generated IDs and derivations, not wording."""
    if isinstance(value, dict):
        return {k: clean_fields(v) for k, v in value.items()
                if k not in {"item_id", "fact_ids", "revision", "sections"}}
    if isinstance(value, list):
        return [clean_fields(row) for row in value]
    return value


def protected(data, keys):
    return {key: clean_fields(data.get(key) or ({} if key == "basic_info" else [])) for key in keys}


def identity(data):
    return {"education": [{k: row.get(k, "") for k in ("school", "major", "degree")}
                          for row in data.get("education") or []],
            "name": (data.get("basic_info") or {}).get("name", ""),
            "objective": (data.get("basic_info") or {}).get("objective", "")}


def numeric_signature(data, excluded):
    text = re.sub(excluded, "", resume_text(data), flags=re.I)
    return Counter(re.findall(r"\d+(?:\.\d+)?", text))


def evidence(turn, field, value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return {"action": turn.get("action", "missing"), "field": field,
            "excerpt": text[:400] if text else "[空/缺失]"}


def excerpt(text, pattern):
    match = re.search(pattern, text, re.I)
    return text[max(0, match.start() - 40):match.end() + 120] if match else text[:280]


def affirmative_claim(text, pattern):
    """Narrow lexical check: do not mistake '没有使用CRM' for CRM experience."""
    for clause in re.split(r"[，,。；;\n]", text):
        for match in re.finditer(pattern, clause, re.I):
            prefix = clause[max(0, match.start() - 18):match.start()]
            if not re.search(r"没有|未|不能|不要|不曾|尚无|不(?:会|写|应|能|增加|编造|负责)|无", prefix):
                return True
    return False


def evaluate_persona(persona, turns, *, with_recovery=False):
    if persona not in PERSONAS:
        raise ValueError(f"Unknown persona: {persona}")
    turns = deepcopy(turns)
    results = []

    def add(id_, label, ok, proof):
        results.append({"id": f"{persona}.{id_}", "persona": persona, "label": label,
                        "status": "pass" if ok else "fail", "evidence": proof})

    def matching(action):
        return [t for t in turns if t.get("trigger_action", t.get("action")) == action]

    def last(action):
        rows = matching(action)
        return rows[-1] if rows else {"action": action, "resume_data": {}, "reply": ""}

    def since(action):
        start = next((i for i, t in enumerate(turns) if t.get("action") == action), len(turns))
        return turns[start:]

    def check_rows(id_, label, rows, predicate, field="resume_data", view=None):
        view = view or (lambda t: t.get(field) or {})
        judged = [(t, bool(predicate(t))) for t in rows]
        failed = [t for t, ok in judged if not ok]
        add(id_, label, bool(rows) and not failed,
            [evidence(t, field, view(t)) for t in (failed or rows)[-4:]] or
            [evidence({}, field, "没有该轮证据")])

    initial, polish, correction = last("initial"), last("polish"), last("correction")
    # A plan card is not a delivered draft. Judge each fixture at its own
    # confirmation boundary, never borrowing a later recovery/paste/polish.
    document_turns = [last(t['action']) for t in turns if t.get('kind', 'fixture') == 'fixture']
    polish_index = next((i for i, t in enumerate(turns) if t.get("action") == "polish"), -1)
    before = turns[polish_index - 1] if polish_index > 0 else {"resume_data": {}}
    data = lambda t: t.get("resume_data") or {}
    body = lambda t: experience_text(data(t))
    public = lambda t: str(t.get("reply") or "")
    all_drafts = [t for t in turns if has_draft(data(t))]

    expected = [a for a in TURN_ORDER[persona] if with_recovery or a != "recovery"]
    actual = [t.get("action") for t in turns if t.get("kind", "fixture") == "fixture"]
    bad = [t for t in turns if t.get("status", "ok") != "ok" or not public(t).strip() or t.get("sse_done") is False]
    add("common.rounds_complete", "轮次按顺序完成；SSE 无错误且公开回复非空", actual == expected and not bad,
        [evidence({}, "actions", {"expected": expected, "actual": actual})] +
        [evidence(t, "error", t.get("error") or "SSE/回复不完整") for t in bad])
    check_rows("common.one_question", "每次成稿回复至多一处「需要你补充」", all_drafts,
               lambda t: supplement_questions(public(t)) <= 1, "reply", public)
    direct = [t for t in turns if t.get("kind", "fixture") == "fixture" and
              re.search(r"先直接生成|请直接|直接生成|直接补齐|不要再追问|不要继续问|不再追问", t.get("input", ""))]
    check_rows("common.direct_first_draft", "要求直接生成/停止追问的当轮，确认方案前已有正文", direct,
               lambda t: has_draft(data(t)) and has_experience_body(data(t)), "resume_data", lambda t: resume_text(data(t)))
    # Personas without a literal direct-generation instruction are still covered
    # by the first-draft gate below, rather than failing a nonexistent instruction.
    if not direct:
        results[-1]["status"] = "pass" if turns else "fail"
        results[-1]["evidence"] = [evidence({}, "input", "本人物没有指定直接生成/停止追问措辞")]
    check_rows("common.public_language", "公开回复无英文 internship/project 或「当前排版为 0 档」", turns,
               lambda t: not re.search(r"\b(?:internship|project)\b|当前排版为\s*0\s*档", public(t), re.I),
               "reply", lambda t: excerpt(public(t), r"\b(?:internship|project)\b|当前排版为\s*0\s*档"))
    add("common.first_draft", "initial 后（含其方案确认）有经历成稿，不借 recovery/paste 补救",
        has_draft(data(initial)) and has_experience_body(data(initial)),
        [evidence(initial, "resume_data", resume_text(data(initial)))])

    def text_check(id_, label, rows, pattern, *, absent=False, view=body):
        check_rows(id_, label, rows, lambda t: bool(re.search(pattern, view(t), re.I)) != absent,
                   "reply" if view is public else "resume_data", lambda t: excerpt(view(t), pattern))

    def scope_check(keys):
        add("polish_scope", "润色只改指定经历，其他栏目/个人字段保持原值",
            bool(data(before)) and bool(data(polish)) and protected(data(before), keys) == protected(data(polish), keys),
            [evidence(t, "protected_fields", protected(data(t), keys)) for t in (before, polish)])

    def identity_check(id_="polish_identity"):
        old, new = identity(data(before)), identity(data(polish))
        add(id_, "润色前后学校/专业/学历、姓名、objective 完全相同",
            bool(old["education"]) and bool(old["name"]) and bool(old["objective"]) and old == new,
            [evidence(t, "identity", identity(data(t))) for t in (before, polish)])

    if persona == "tech":
        check_rows("initial_internship", "首版工作/实习栏含云舟科技及接口职责", [initial],
                   lambda t: any("云舟科技" in item_text(row) and re.search(r"接口|参数校验", item_text(row))
                                 for sec in ("work_experience", "internship") for row in visible_items(data(t), sec)), view=lambda t: body(t))
        check_rows("initial_project", "首版项目栏含校园二手交易系统及接口职责", [initial],
                   lambda t: any("校园二手交易系统" in item_text(row) and "接口" in item_text(row)
                                 for row in visible_items(data(t), "projects")), view=lambda t: body(t))
        check_rows("single_project", "课程项目全程只有一个条目，分工不独立成项", turns,
                   lambda t: len(data(t).get("projects") or []) == 1 and "校园二手交易系统" in item_text(data(t)["projects"][0]))
        check_rows("skills", "技能有 Java、Git、了解 Redis，无 Kubernetes", turns,
                   lambda t: all(re.search(rf"(?<![a-z0-9]){word}(?![a-z0-9])", skills_text(data(t)), re.I) for word in ("Java", "Git", "Redis"))
                   and bool(re.search(r"了解[^\n；;]*Redis|Redis[^\n；;]*了解", skills_text(data(t)), re.I))
                   and "kubernetes" not in skills_text(data(t)).casefold(), view=lambda t: skills_text(data(t)))
        for id_, label, pattern in (
            ("mentor", "正文保留导师指导限定", r"导师.{0,8}指导|指导.{0,8}导师"),
            ("test_environment", "正文保留测试环境限定", r"测试环境"),
            ("no_online_load", "正文保留未做线上压测限定", r"(?:没|未|无|没有).{0,8}线上.{0,3}压测"),
            ("team_scope", "正文保留同学负责登录、实验室演示/无真实用户分工", r"(?:登录[^\n。；]*同学|同学[^\n。；]*登录)[\s\S]*(?:实验室|无真实用户|没有真实用户)"),
        ):
            text_check(id_, label, turns, pattern)
        identity_check()
        scope_check(("basic_info", "education", "projects", "campus", "skills", "skill_groups", "summary"))
        text_check("correction_190", "更正后正文有190ms且无170ms", [correction], r"(?<!\d)190\s*ms\b")
        if re.search(r"(?<!\d)170\s*ms\b", body(correction), re.I):
            results[-1]["status"] = "fail"
            results[-1]["evidence"] = [evidence(correction, "resume_data", excerpt(body(correction), r"170\s*ms"))]
        exclusion = r"(?<!\d)(?:170|190)\s*ms\b"
        add("correction_other_numbers", "更正前后其他数字完全相同，420ms、12条仍在",
            bool(data(polish)) and bool(re.search(r"420\s*ms", body(correction), re.I))
            and bool(re.search(r"12\s*条", body(correction)))
            and numeric_signature(data(polish), exclusion) == numeric_signature(data(correction), exclusion),
            [evidence(t, "other_numbers", dict(numeric_signature(data(t), exclusion))) for t in (polish, correction)])
    elif persona == "ops":
        rows = since("followup")
        def posters_owned(t):
            items = [(section, row) for section in EXPERIENCES for row in visible_items(data(t), section)]
            cafe = [row for _section, row in items if "小巷咖啡" in item_text(row)]
            return len(cafe) == 1 and bool(re.search(r"4\s*张[^\n。；]*海报|海报[^\n。；]*4\s*张", item_text(cafe[0]))) and all(
                "海报" not in item_text(row) for _section, row in items if row is not cafe[0])
        check_rows("posters_ownership", "4张促销海报和店长海报职责只在小巷咖啡条目", rows, posters_owned,
                   view=lambda t: body(t))
        check_rows("no_placeholder_campus", "无待补/未命名校园占位条目", rows,
                   lambda t: all(str(row.get("name") or "").strip() and
                                 not re.search(r"待补|未命名|对话中描述", str(row.get("name")))
                                 for row in data(t).get("campus") or []), view=lambda t: data(t).get("campus"))
        text_check("no_raw_duplicates", "无「写过推文」「拍过店里的短视频」重复原话", rows,
                   r"写过推文|拍过店里的短视频", absent=True)
        def association_date(t):
            assoc = [row for sec in EXPERIENCES for row in visible_items(data(t), sec) if "读书协会" in item_text(row)]
            return len(assoc) == 1 and month_key(assoc[0].get("start_date", "")) == (2024, 9) and month_key(assoc[0].get("end_date", "")) == (2025, 6)
        check_rows("association_dates", "协会条目日期为2024.09—2025.06", rows, association_date, view=lambda t: body(t))
        # Inspect question-bearing clauses and the actual guidance/question API,
        # not mentions such as '没有阅读量，因此不写阅读量'.
        def readership_questions(t):
            clauses = re.split(r"[。！!；;\n]", public(t))
            guidance = (t.get("workspace") or {}).get("guidance") or {}
            clauses += strings(guidance.get("question")) + strings(((t.get("workspace") or {}).get("tailor") or {}).get("questions"))
            return [s for s in clauses if re.search(r"阅读量", s) and re.search(r"[？?]|(?:请|能否|可以|是否|补充|寻找|有没有|多少|找一下)", s)]
        check_rows("no_readership_followup", "说明没有数据后，不再追问阅读量", rows,
                   lambda t: not readership_questions(t), "reply", lambda t: readership_questions(t) or public(t))
        check_rows("numeric_outputs", "8篇排版、3篇初稿、6条素材、2条发布保留", rows,
                   lambda t: all(re.search(pattern, body(t)) for pattern in (r"8\s*篇", r"3\s*篇", r"6\s*条", r"2\s*条")),
                   view=lambda t: body(t))
        check_rows("no_invented_operations", "不声称增长成果/独立账号运营", rows,
                   lambda t: not affirmative_claim(body(t), r"(?:增长|提升|增加).{0,12}\d+\s*%|独立(?:负责|运营|策划)|粉丝.{0,12}(?:达到|增长|增加)"),
                   view=lambda t: body(t))
        scope_check(("basic_info", "education", "projects", "campus", "skills", "skill_groups"))
    elif persona == "career":
        check_rows("initial_named_work", "首版工作栏为启明商贸行政职责", [initial],
                   lambda t: any("启明商贸" in item_text(row) and re.search(r"报销|通讯录|培训", item_text(row))
                                 for row in visible_items(data(t), "work_experience")), view=lambda t: body(t))
        text_check("no_instruction_body", "经历正文无杂项标题、姓名叙述或生成指令", turns,
                   r"对话中描述的经历|周宁|这是虚构测试|请先做|请直接|说明哪些能力|不要把行政工作", absent=True,
                   view=lambda t: body(t) + "\n" + str(data(t).get("summary") or ""))
        text_check("correction_four", "培训更正后正文有4场且无6场", [correction], r"(?:4|四)\s*场")
        if re.search(r"(?:6|六)\s*场", body(correction)):
            results[-1]["status"] = "fail"
        exclusion = r"(?<!\d)(?:4|6|四|六)\s*场"
        add("correction_other_numbers", "培训更正不改变120人、30份及其他数字",
            bool(data(polish)) and bool(re.search(r"120\s*人", body(correction))) and bool(re.search(r"30\s*份", body(correction)))
            and numeric_signature(data(polish), exclusion) == numeric_signature(data(correction), exclusion),
            [evidence(t, "other_numbers", dict(numeric_signature(data(t), exclusion))) for t in (polish, correction)])
        def retained(t):
            # Only explicit omissions in this version's review metadata/notes
            # count as backup. The raw experiences panel alone cannot prove it.
            ws = t.get("workspace") or {}
            coverage = (((ws.get("tailor") or {}).get("resume_meta") or {}).get("fact_coverage") or {}).get("facts") or []
            backup = "\n".join(str(row.get("text") or "") for row in coverage
                               if row.get("status") == "omitted" and row.get("reason"))
            backup += "\n" + "\n".join(note for note in strings(data(t).get("verification_notes")) if re.search(r"备用|不展示|未写|省略", note))
            return all(re.search(pattern, body(t)) or re.search(pattern, backup)
                       for pattern in (r"通讯录", r"培训", r"报销", r"(?:接待|访客|客户问题)"))
        check_rows("retained_duties", "每版保留通讯录、培训、报销、接待，或在核对中明确列备用", all_drafts, retained,
                   view=lambda t: {"body": body(t), "review": (t.get("workspace") or {}).get("tailor", {}), "notes": data(t).get("verification_notes")})
        check_rows("no_invented_customer_outcomes", "不编造客户续费/客户培训/CRM使用/销售业绩", turns,
                   lambda t: not affirmative_claim(body(t), r"(?:促成|提升|负责|完成|实现|开展).{0,12}(?:客户续费|客户培训|续费率|销售业绩)|(?:使用|运用|熟练).{0,5}CRM"),
                   view=lambda t: body(t))
        reply = public(initial) + "\n" + public(polish)
        add("transition_evidence_gaps", "转岗解释区分已有迁移能力与缺少的岗位证据",
            bool(re.search(r"沟通|记录|协调|文档|迁移", reply)) and
            bool(re.search(r"(?:缺|补充|尚无|暂无|没有|待)[^。\n]{0,50}(?:客户成功|CRM|续费|客户培训|产品)|(?:客户成功|CRM|续费|客户培训|产品)[^。\n]{0,40}(?:缺|补充|尚无|暂无|没有|待)", reply, re.I)),
            [evidence(initial, "reply", reply)])
        scope_check(("basic_info", "education", "projects", "campus", "skills", "skill_groups"))
    elif persona == "service":
        check_rows("single_education", "每次交付稿（含本轮方案确认）教育只有一条", document_turns, lambda t: len(data(t).get("education") or []) == 1,
                   view=lambda t: data(t).get("education"))
        check_rows("school_clean", "学校为新城职业学院，无「在」前缀", document_turns,
                   lambda t: bool(data(t).get("education")) and all(row.get("school") == "新城职业学院" for row in data(t)["education"]),
                   view=lambda t: data(t).get("education"))
        identity_check()
        add("polish_education", "润色后完整教育字段不变",
            bool(data(before).get("education")) and clean_fields(data(before).get("education")) == clean_fields(data(polish).get("education")),
            [evidence(t, "education", data(t).get("education")) for t in (before, polish)])
        text_check("no_instruction_major", "教育字段没有「写得更」", [polish], r"写得更", absent=True,
                   view=lambda t: "\n".join(strings(data(t).get("education"))))
        text_check("approval_limit", "正文保留退款由主管审批", document_turns, r"退款[^。；\n]{0,25}主管[^。；\n]{0,10}审批|主管[^。；\n]{0,10}审批[^。；\n]{0,10}退款")
        text_check("complaint_limit", "正文保留复杂投诉转交主管", document_turns, r"复杂投诉[^。；\n]{0,20}(?:转交|转给|上报)[^。；\n]{0,10}主管")
        text_check("volume_800", "正文保留每月800次咨询", document_turns, r"800\s*次[^。；\n]{0,8}咨询")
        scope_check(("basic_info", "education", "projects", "campus", "skills", "skill_groups"))
    else:
        check_rows("initial_project", "附件首版项目栏含借物App课程项目及12页面/18组件", [initial],
                   lambda t: any(all(re.search(pattern, item_text(row), re.I) for pattern in
                                     (r"借物\s*App", r"12[^。；\n]{0,15}(?:页|界面)", r"18[^。；\n]{0,15}组件"))
                                 for row in visible_items(data(t), "projects")), view=lambda t: body(t))
        check_rows("initial_education_major", "附件首版含江湾艺术学院/视觉传达设计/本科", [initial],
                   lambda t: any(row.get("school") == "江湾艺术学院" and row.get("major") == "视觉传达设计" and row.get("degree") == "本科" for row in visible_items(data(t), "education")),
                   view=lambda t: data(t).get("education"))
        check_rows("initial_volunteer_posters", "附件首版志愿者协会独立于课程项目，保留6张海报", [initial],
                   lambda t: any("青年志愿者协会" in item_text(row) and re.search(r"6\s*张[^。；\n]*海报", item_text(row)) for row in visible_items(data(t), "campus")),
                   view=lambda t: data(t).get("campus"))
        ws = initial.get("workspace") or {}
        candidate = body(initial) + "\n" + "\n".join(strings((ws.get("experiences") or {}).get("items")))
        jd = "\n".join(strings(ws.get("jd") or {}))
        add("attachment_not_jd", "借物App/12页/18组件进入本人经历，附件不成为JD",
            bool(re.search(r"借物\s*App", candidate, re.I)) and not re.search(r"借物\s*App|许禾|xuhe@", jd, re.I),
            [evidence(initial, "candidate", candidate), evidence(initial, "workspace.jd", jd)])
        text_check("no_negative_skills", "技能不含没有前端/不会等否定项", turns,
                   r"没有|不会|未(?:做|学|掌握)|无.{0,4}(?:经验|能力)", absent=True, view=lambda t: skills_text(data(t)))
        check_rows("single_course_project", "借物课程项目一个条目，分工不拆成项目", document_turns,
                   lambda t: len(data(t).get("projects") or []) == 1 and bool(re.search(r"借物\s*App", item_text(data(t)["projects"][0]), re.I)))
        text_check("concept_limit", "保留课程概念/未上线限定，不声称增长或转化验证", document_turns,
                   r"课程|概念|未上线|没有上线")
        check_rows("no_invented_design_results", "无上线/增长/转化验证成果", turns,
                   lambda t: not affirmative_claim(body(t), r"(?:已|成功|正式).{0,3}上线|(?:用户增长|转化率).{0,10}(?:提升|提高|\d+%)|验证.{0,5}转化"),
                   view=lambda t: body(t))
        scope_check(("basic_info", "education", "work_experience", "campus", "skills", "skill_groups"))
    return results


def evaluate_run(run):
    return [check for persona, record in run.get("personas", {}).items()
            for check in evaluate_persona(persona, record.get("turns") or [], with_recovery=run.get("with_recovery", False))]
