"""P1 loop checks on frozen API records; no model or production tool imports."""
from importlib import import_module
import json
import math
from pathlib import Path
import re

checks = import_module("evaluation.persona-ux.checks")
FIXTURE_PATH = Path(__file__).with_name("loop-fixtures.json")
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CALL_SCOPE = "httpx_chat_completions_responses_attempts"


def delivered(turn):
    data = turn.get("resume_data") or {}
    return (turn.get("has_data") is True and turn.get("stage") in {"EVALUATING", "EXPORT"}
            and bool(turn.get("revision")) and checks.has_draft(data) and checks.has_experience_body(data))


def cards(turn):
    return [*(turn.get("guidance_history") or []), (turn.get("workspace") or {}).get("guidance") or {}]


def contact_request(turn):
    for card in cards(turn):
        if card.get("kind") == "intake_basics":
            missing = card.get("missing_fields")
            if missing is None or set(missing) & {"phone", "email"}:
                return True
        if card.get("kind") == "ask_user" and re.search(
                r"手机|电话|邮箱|联系方式|\b(?:phone|email)\b",
                re.sub(r"手机(?:拍摄|拍照|剪辑|录制)", "拍摄工具",
                       "\n".join(checks.strings({k: card.get(k) for k in ("question", "questions", "title")}))), re.I):
            return True
    for clause in re.split(r"[，,。！!；;\n]|但(?:是)?", turn.get("reply") or ""):
        clause = re.sub(r"手机(?:拍摄|拍照|剪辑|录制)", "拍摄工具", clause)
        if not re.search(r"手机|电话|邮箱|联系方式", clause):
            continue
        if re.search(r"(?:不|无需|不用|不必).{0,8}(?:需要|提供|补|填|发|给)|已(?:经)?(?:有|提供|记录|收到|记下)", clause):
            continue
        if re.search(r"[？?]|请|补充|提供|告诉|留(?:下|个)|填写|填入|发(?:我|来|一下)|给我|还缺|还差|缺少|需要", clause):
            return True
    return False


def observations(turns):
    first = next((i for i, t in enumerate(turns, 1) if delivered(t)), None)
    material = next((i for i, t in enumerate(turns, 1) if t.get("action") == "experience"), 1)
    return {"first_draft_turn": first,
            "turns_from_material": first - material + 1 if first and first >= material else None,
            "contact_request_turns": [i for i, t in enumerate(turns, 1) if contact_request(t)]}


def finite_nonnegative(value):
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def evaluate_loop(persona, turns):
    rows = []

    def add(key, label, ok, proof):
        rows.append({"id": f"{persona}.loop.{key}", "persona": persona, "label": label,
                     "status": "pass" if ok else "fail", "evidence": proof})

    first = turns[0] if turns else {}
    stats = observations(turns)
    add("no_initial_form", "首轮无基本信息/经历清单表单（含流中间卡片）", bool(turns) and not any(
        c.get("kind") in {"intake_basics", "intake_experiences"} for c in cards(first)),
        [checks.evidence(first, "guidance", cards(first))])
    add("first_draft_by_turn3", "从首条消息起至多3轮出现有正文的已保存初稿；确认轮计入", bool(
        stats["first_draft_turn"] and stats["first_draft_turn"] <= 3), [checks.evidence(first, "draft_timing", stats)])
    requests = stats["contact_request_turns"]
    add("contacts_once", "联系方式至多索要一次；同轮卡片与回复合计一次", bool(turns) and len(requests) <= 1,
        [checks.evidence(t, "reply", t.get("reply")) for t in turns if contact_request(t)] or
        [checks.evidence(first, "contact_request_turns", requests)])
    bad = []
    for turn in turns:
        counts = turn.get("model_calls")
        orchestration = turn.get('orchestrator') or {}
        expected = (turn.get('metrics_version') == 2 and turn.get('kind') != 'confirmation'
                    and not turn.get('answers') and not turn.get('intake'))
        orchestrator_ok = not expected or (
            type(orchestration.get('model_calls')) is int and orchestration['model_calls'] > 0
            and finite_nonnegative(orchestration.get('seconds'))
            and len(orchestration.get('turns') or []) == orchestration['model_calls'])
        if not (type(counts) is int and counts >= 0 and turn.get("metrics_agent_mode") == "loop"
                and turn.get("model_call_scope") == CALL_SCOPE
                and finite_nonnegative(turn.get("server_seconds"))
                and finite_nonnegative(turn.get("stream_seconds"))
                and finite_nonnegative(turn.get("elapsed_seconds")) and orchestrator_ok):
            bad.append(turn)
    add("metrics", "每轮有服务端模型HTTP尝试数与耗时；缺失不估为0", bool(turns) and not bad,
        [checks.evidence(t, "metrics", {k: t.get(k) for k in (
            "model_calls", "model_call_scope", "metrics_agent_mode", "server_seconds", "stream_seconds", "elapsed_seconds", "orchestrator")})
         for t in (bad or turns)])
    add("contacts_not_sent", "每轮出站隐私检查无拦截；原始联系方式不发模型", bool(turns) and all(
        type(t.get("privacy_blocks")) is int and t["privacy_blocks"] == 0 for t in turns),
        [checks.evidence(t, "privacy_blocks", t.get("privacy_blocks")) for t in turns])
    return rows


def evaluate_persona(persona, turns, **_):
    fixture = FIXTURES[persona]
    rows = []

    def add(key, label, ok, proof):
        rows.append({"id": f"{persona}.{key}", "persona": persona, "label": label,
                     "status": "pass" if ok else "fail", "evidence": proof})

    expected = [key for key in fixture if key != "role"]
    actual = [t.get("action") for t in turns if t.get("kind", "fixture") == "fixture"]
    add("common.rounds_complete", "固定输入按序完成；SSE和公开回复完整", actual == expected and all(
        t.get("status") == "ok" and t.get("sse_done") is True and (t.get("reply") or "").strip() for t in turns),
        [checks.evidence({}, "actions", {"expected": expected, "actual": actual})])
    drafts = [t for t in turns if checks.has_experience_body(t.get("resume_data") or {})]
    final = turns[-1] if turns else {}
    add("common.first_draft", "最后一轮有已保存的经历正文", delivered(final),
        [checks.evidence(final, "resume_data", checks.resume_text(final.get("resume_data") or {}))])
    if persona == "cold":
        patterns = (r"读书社", r"Excel", r"28\s*条", r"2\s*张", r"登记|核对", r"汇总表")
        forbidden = r"(?:独立|全面)(?:负责|组织|策划)|负责人|主导|牵头|(?:增长|提升|增加).{0,12}\d+\s*%"
        limit = r"志愿者|协助|登记|核对"
        identity = ("程岚", "明溪学院", "信息管理", "本科")
        item_name = "读书社"
        material_turn = next((i for i, t in enumerate(turns, 1) if t.get("action") == "experience"), None)
        contact_turn = next((i for i, t in enumerate(turns, 1) if t.get("action") == "contacts"), None)
        requests = observations(turns)["contact_request_turns"]
        add("contacts_late", "只在提供具体经历之后、补联系方式之前索要一次", bool(
            material_turn and contact_turn and len(requests) == 1 and material_turn <= requests[0] < contact_turn),
            [checks.evidence({}, "contact_request_turns", requests)])
        add("facts.not_before_material", "具体经历提供前不生成经历正文", bool(material_turn) and not any(
            checks.has_experience_body(t.get("resume_data") or {}) for t in turns[:material_turn - 1]),
            [checks.evidence({}, "material_turn", material_turn)])
    else:
        patterns = (r"预约系统", r"Python", r"16\s*条", r"5\s*个", r"测试用例", r"问题清单")
        forbidden = r"(?:独立|全面)负责|负责人|主导|牵头|(?:已|成功|正式).{0,3}上线|生产压测|(?:增长|提升).{0,12}\d+\s*%"
        limit = r"本地|课程"
        identity = ("叶清", "柳岸学院", "软件工程", "本科")
        item_name = "预约系统"
        add("contacts_not_repeated", "旧简历已含联系方式，不重复索要", bool(turns) and not any(map(contact_request, turns)),
            [checks.evidence(t, "contact_request", contact_request(t)) for t in turns])
    for key, label, predicate in (
        ("facts.retained", "每版可见正文保留来源中的任务与数量", lambda text: all(re.search(p, text, re.I) for p in patterns)),
        ("facts.scope", "保留参与范围/场景，未升级职责或编造上线与增长", lambda text: bool(re.search(limit, text)) and not checks.affirmative_claim(re.sub("不是|并非", "未", text), forbidden)),
    ):
        failed = [t for t in drafts if not predicate(checks.experience_text(t["resume_data"]))]
        add(key, label, bool(drafts) and not failed, [checks.evidence(t, "resume_data", checks.experience_text(t["resume_data"])) for t in failed or drafts])
    source = "\n".join(fixture.values())
    extra_items = [t for t in drafts if any(item_name not in checks.item_text(row)
        for section in checks.EXPERIENCES for row in checks.visible_items(t["resume_data"], section))]
    add("facts.no_extra_experience", "不添加来源外经历/奖项", bool(drafts) and not extra_items,
        [checks.evidence(t, "resume_data", checks.experience_text(t["resume_data"])) for t in extra_items or drafts])
    school_rows = checks.visible_items(final.get("resume_data") or {}, "education")
    add("facts.identity", "最终成稿姓名与学校/专业/学历来自原始输入", bool(
        (final.get("resume_data") or {}).get("basic_info", {}).get("name") == identity[0]
        and len(school_rows) == 1 and tuple(school_rows[0].get(k) for k in ("school", "major", "degree")) == identity[1:]),
        [checks.evidence(final, "identity", checks.identity(final.get("resume_data") or {}))])
    known_tools = {word.casefold() for word in re.findall(r"[A-Za-z]+", source)}
    extra_skills = [(t, sorted({word.casefold() for word in re.findall(r"[A-Za-z]+", checks.skills_text(t["resume_data"]))} - known_tools)) for t in drafts]
    add("facts.no_new_tools", "技能栏没有来源外英文工具名", bool(drafts) and all(not words for _, words in extra_skills),
        [checks.evidence(t, "unsupported_tools", words) for t, words in extra_skills])
    allowed = {str(float(n)) for n in re.findall(r"\d+(?:\.\d+)?", source)}
    def numbers(text):
        text = re.sub(r"(\d{4})[./-](\d{1,2})(?!\d)", r"\1年\2月", text)
        return {str(float(n)) for n in re.findall(r"\d+(?:\.\d+)?", text)}
    invented = [(t, sorted(numbers(checks.resume_text(t["resume_data"])) - allowed)) for t in drafts]
    add("facts.no_new_numbers", "可见简历无来源外数字（词法检查）", bool(drafts) and all(not nums for _, nums in invented),
        [checks.evidence(t, "unsupported_numbers", nums) for t, nums in invented])
    # Contacts are checked only in canonical basic_info, never used as evidence text.
    basic = (final.get("resume_data") or {}).get("basic_info") or {}
    phone = re.search(r"1\d{10}", source)[0]
    email = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", source)[0]
    add("contacts_projected", "补充的手机/邮箱出现在成稿头部", basic.get("phone") == phone and basic.get("email") == email,
        [checks.evidence(final, "basic_info", {"phone_matches": basic.get("phone") == phone, "email_matches": basic.get("email") == email})])
    return rows
