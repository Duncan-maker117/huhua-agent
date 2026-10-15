"""Extract sparse, source-checked changes to the candidate fact master."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import logging
import os
import re
import uuid

from app.schemas.facts import FACT_FIELDS, FACT_LABELS, FACT_SECTIONS
from app.services.candidate_language import (
    PLACEHOLDER_NAMES, campus_evidence, coursework_evidence, literal_item_name, placeholder_name,
    non_fact, safe_item_name, safe_major, safe_objective, literal_employment, personal_header,
    constraint_only, wording_constraint,
)
from app.services.candidate_skills import canonical_skill_text, declared_skills, skill_declaration
from app.services.llm_compat import label_run, without_thinking
from app.services.resume_facts import new_fact, normalize_fact_store
from app.services.resume_field_hygiene import is_project_status

logger = logging.getLogger(__name__)

_CONTRACT = """从候选人本轮消息抽取简历事实，只输出 JSON patch：
{"items":[{"section":"projects|work_experience|internship|education|campus|open_source|awards","item_id":"已有ID或空","name":"经历名","facts":[{"kind":"role|action|method_tool|deliverable|result_metric|result_qualitative|scope_scale|status_limit|context|team","field":"结构字段可选","text":"规范化陈述","source_quote":"本轮连续原文"}],"links":[{"text":"PR或链接名","url":"用户提供的链接"}],"raw_notes":["本轮相关原话"]}],"basic_info":{"name":"姓名","phone":"电话占位原文","email":"邮箱占位原文","location":"城市","objective":"求职意向","links":[{"text":"GitHub或个人主页","url":"原文URL/域名/账号"}],"availability":"可实习时间原文"},"skills":[],"corrections":[{"item_id":"","fact_id":"","replacement":{"kind":"","text":"","source_quote":""}}],"removals":[{"item_id":"","fact_id":""}]}。
口语可转书面，但不能新增数字、动作、职责、成果或工具；否定、计划、Demo、未上线必须保留。归属已有经历须用已有 item_id。
followup_target 是当前追问针对的已有经历；用户短答未重复经历名时优先带该 item_id。用户转向其他/新经历时不得沿用，归属不明确不要猜。
更正旧事实用 corrections，删除事实用 removals；删除文稿的句子不等于删除事实。
JD、示例、助手建议、计划要做的事情不能变成已完成事实。metadata_context 和 previous_assistant 只帮助理解短答和冲突，不是正文事实；source_quote 只能来自 message。
教育的学校、专业、学历、起止时间分别标 field=school/major/degree/start_date/end_date；奖学金标 highlights，保留在 education，不重复放 awards。学校简称保持原词，不要自行扩写全称，不能压成「就读于某大学」一句。
学生组织、社团、学生会、志愿服务、班委、协会归 campus，不归 projects/open_source；name 用原文组织名，role 放职务。无法确定名称时留空，不影响保留事实。
求职意向只填不超过20字的明确岗位名；方向迷茫、兴趣、自评、计划和提问不填 objective，也不是经历动作。
开源贡献归 open_source，name 用仓库/项目名，简介（如星数）标 summary，PR号或链接标 pr，本人贡献和结果分别为正文事实；每个PR一条item，不能把「自己」当项目名。竞赛荣誉归 awards，名称、级别/名次、时间分别标 name/level/date。
原型、未上线、已上线等是状态，标 kind=status_limit，不得标为 role 或 field=role；荣誉 name 去掉首尾标点。
没有后台权限、不是负责人、选题由他人定、他人给文案、没有数据或不知道播放量都标 status_limit，约束措辞，不是成果。按子句最近的明确主体归属；「我还做过」无新主体时接续最近经历，海报不表示校园经历。
用户一次列出多个PR、多个奖项时必须逐条收录，不得只收第一条。数字及其单位（人/次/个/条）保留，不能把「20次」解释为「20次调用/请求」。
半句话中已经说清的团队规模、本人分工等分别抽取；未完成的尾巴不影响前面的事实，不猜缺失内容。
不要返回整份 collected_info，不要添加未知字段。"""


def split_incomplete_tail(message: str) -> tuple[str, str]:
    if not isinstance(message, str):
        return message, ""
    match = re.search(r"(?:分别是|分别为|包括|例如|比如)[：:，,。.!！?？\s]*$", message or "")
    if not match:
        return message, ""
    return message[:match.start()].rstrip("：:，,。；; \t\n"), match.group().strip("：:，,。.!！?？ \t\n")


def _candidate_evidence(message: str) -> str:
    """Exclude explicitly labelled external material while allowing mixed turns."""
    from app.services.candidate_material import split_mixed_material
    message, _ = split_mixed_material(message)
    external = False
    kept = []
    external_label = re.compile(r"^(?:岗位职责|任职要求|职位要求|招聘要求|示例简历|简历范文|参考简历|参考材料|JD)[：:]$", re.I)
    candidate_label = re.compile(r"^(?:我的经历|本人经历|我做过|我的项目|补充我的事实)[：:]$")
    split_labels = re.compile(r"((?:岗位职责|任职要求|职位要求|招聘要求|示例简历|简历范文|参考简历|参考材料|JD|我的经历|本人经历|我做过|我的项目|补充我的事实)[：:])", re.I)
    for line in message.splitlines():
        plain = line.strip(" #*\t")
        if re.match(r"^(岗位职责|任职要求|职位要求|招聘要求|示例简历|简历范文|参考简历|参考材料|JD)$", plain, re.I):
            external = True
            continue
        if re.match(r"^(我的经历|本人经历|我做过|我的项目|补充我的事实)$", plain):
            external = False
            continue
        for part in split_labels.split(line):
            if external_label.fullmatch(part):
                external = True
            elif candidate_label.fullmatch(part):
                external = False
            elif not external:
                kept.append(part)
    return "\n".join(kept)


def _content(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "content"):
        value = value.content
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I)
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {}


def _is_large_rewrite(text: str, quote: str) -> bool:
    def compact(value: str) -> str:
        return re.sub(r"\s|[，。；、,.!?！？：:]", "", value).casefold()
    a, b = compact(text), compact(quote)
    return not a or not b or a != b


def _skill_affirmed(message: str, name: str) -> bool:
    for match in re.finditer(re.escape(name), message, re.I):
        before = message[max(0, match.start() - 12):match.start()]
        if not re.search(r"(?:不会|不懂|不熟悉|没用过|没学过|未使用|不掌握|不具备|计划(?:学习|使用)?|准备(?:学习|使用)?|打算(?:学习|使用)?|将(?:学习|使用)?)\s*$", before):
            return True
    return False


def _quote_has_unquoted_limit(message: str, quote: str) -> bool:
    """A model cannot crop '没有/计划' off the front of a source quote."""
    positions = list(re.finditer(re.escape(quote), message, re.I))
    if not positions:
        return True
    for match in positions:
        clause_start = re.split(r"[，,。；;！？!?\n]", message[:match.start()])[-1]
        clause_end = re.split(r"[，,。；;！？!?\n]", message[match.end():])[0]
        if constraint_only(clause_start + quote + clause_end) and not constraint_only(quote):
            continue
        prefix = message[:match.start()]
        prefix = re.split(r"[，,。；;！？!?\n]|但是|不过|而是", prefix)[-1]
        if not re.search(r"(?:没有|尚未|并未|从未|未|没|不曾|不会|不|计划|准备|打算|将).{0,12}$", prefix):
            return False
    return True


# ── 抽取覆盖检查：动作/结果类子句不得被静默丢弃 ─────────────────────────────
_CLAUSE_SPLIT = re.compile(r"[，,。；;！!？?：:\n、]+")
_ACTION_VERB = re.compile(
    r"做|写|搭|开发|设计|实现|改成|改为|改|优化|发了|发布|发|推广|查|修|解决|提升|降低|增加|减少|完成|负责|带|用|调|"
    r"训练|部署|上线|测试|分析|整理|蒸馏|获得|拿到|拿了|star|推荐|挑|接入|重构|迁移|爬|抓|标注|评估|对接|拆|统计|获奖|参与|主导|协助|组织|运营")
_NARRATIVE = re.compile(r"我|本人|后来|一开始|起初|最初|之后|最后|最终|现在|还|已经|做过|做的|写的|搭的|[一二三四五六七八九十]+张|\d")
_INSTRUCTION = re.compile(
    r"帮我|给我|请|突出|按JD|按岗位|改改|改一下|写详细|写上|写进|也写|删掉|去掉|精简|压缩|调整|优化一下|换成|"
    r"能不能|可以吗|是否|要不要|吗|全称|出一版|生成|撤销|导出", re.I)
_PLAN_OR_NEGATED = re.compile(r"我(?:们)?(?:将|从未|并未|还?没有?|未|不曾|不)|计划|准备|打算|希望|想要|下个月|以后|将来|明天|还没")
_STATUS_CLAUSE = re.compile(r"开源|未上线|没上线|Demo|原型", re.I)
_RESULT_CLAUSE = re.compile(r"star|用户|提升|增长|降低|增加|减少|获奖|名|第一|\d", re.I)


def _fact_kind_for_clause(clause: str) -> str:
    """规则判定 kind，不调用模型。"""
    if _STATUS_CLAUSE.search(clause) or constraint_only(clause):
        return "status_limit"
    if re.search(r"[一二两三四五六七八九十\d]+(?:个)?人(?:的)?(?:团队|小组)", clause):
        return "team"
    if _RESULT_CLAUSE.search(clause) and re.search(r"\d", clause):
        return "result_metric"
    if re.search(r"提升|增长|降低|减少|获奖", clause):
        return "result_qualitative"
    if _ACTION_VERB.search(clause):
        return "action"
    return "context"


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} or ({text} if text else set())


def _clause_covered(clause: str, quotes: list[str], whole: str = "") -> bool:
    grams = _bigrams(clause)
    for quote in quotes:
        if not quote:
            continue
        if clause in quote or quote in clause:
            return True
        if grams and len(grams & _bigrams(quote)) / len(grams) >= 0.7:
            return True
    # 子句里的动作词全部落在某条已接受事实的原文片段内，也算覆盖（事实只引了子句的后半段）。
    start = whole.find(clause) if whole else -1
    verbs = [(start + m.start(), start + m.end()) for m in _ACTION_VERB.finditer(clause)] if start >= 0 else []
    spans = []
    for quote in quotes:
        at = whole.find(quote) if quote and whole else -1
        if at >= 0:
            spans.append((at, at + len(quote)))
    return bool(verbs) and all(any(a >= lo and b <= hi for lo, hi in spans) for a, b in verbs)


def uncovered_action_clauses(evidence: str, quotes: list[str]) -> list[str]:
    """候选人原话中含动作/结果类动词、却没有对应已接受事实的子句（保持原文）。"""
    from app.services.fact_guard import normalize_text
    complete, tail = split_incomplete_tail(evidence)
    normalized = [normalize_text(q) for q in quotes]
    whole = normalize_text(complete)
    rows = []
    clauses = _CLAUSE_SPLIT.split(complete)
    if tail:
        clauses = [part for clause in clauses for part in re.split(r"\s+(?=有一个|我|本人|还有一个)", clause)]
    for raw in clauses:
        clause = raw.strip()
        if non_fact(clause) or skill_declaration(clause) or len(clause) < 6 or _INSTRUCTION.search(clause) or _PLAN_OR_NEGATED.search(clause) or re.fullmatch(r"(?:我)?(?:还)?做过.{0,6}(?:东西|项目|事情?)", clause):
            continue
        team = tail and re.search(r"[一二两三四五六七八九十\d]+(?:个)?人(?:的)?(?:团队|小组)", clause)
        if not (team or (_ACTION_VERB.search(clause) and _NARRATIVE.search(clause))):
            continue
        if _clause_covered(normalize_text(clause), normalized, whole):
            continue
        if clause not in rows:
            rows.append(clause)
    return rows


def _reason_code(reason) -> str:
    if isinstance(reason, list):
        return ",".join(str(r) for r in reason[:3])
    return str(reason)


def _log_rejected(rejected: list[dict], turn_id: str) -> None:
    """只记错误码与 hash；benchmark（合成数据）设置 HUHUA_RECORD_REJECTED_TEXT=1 时记原文。"""
    record_text = os.environ.get("HUHUA_RECORD_REJECTED_TEXT") == "1"
    for row in rejected:
        digest = hashlib.sha256(str(row.get("text", "")).encode("utf-8")).hexdigest()[:10]
        extra = f" text={row.get('text')!r}" if record_text else ""
        logger.info("fact_rejected turn=%s code=%s hash=%s%s", turn_id or "-", _reason_code(row.get("reason")), digest, extra)


def fact_item_outline(collected: dict) -> list[dict]:
    return [{"section": section, "item_id": item.get("item_id"),
             "name": item.get("name") or item.get("company") or item.get("school") or "",
             "facts": [f for f in item.get("facts", []) if f.get("status") == "active"]}
            for section in FACT_SECTIONS for item in collected.get(section, [])
            if isinstance(item, dict) and item.get("item_id")]


def followup_item(collected: dict, *, evidence: str | None = None) -> dict | None:
    target = collected.get("followup_target") or {}
    outline = fact_item_outline(collected)
    matches = [item for item in outline
               if item["item_id"] == target.get("item_id")]
    if len(matches) != 1 or matches[0]["section"] != target.get("section"):
        return None
    item = {**matches[0], **({"question_kind": "name"} if target.get("question_kind") == "name" else {})}
    if evidence is not None and not _implicit_followup_allowed(evidence, outline, item):
        return None
    return item


def _name_answer(evidence: str, target: dict) -> str:
    """A naming follow-up accepts nouns or a refusal, never an experience paragraph."""
    text = evidence.strip(" 。！!\n")
    if re.fullmatch(r"(?:不方便(?:说|透露)|没有|不想说|暂不提供)", text):
        return "refused"
    if skill_declaration(text) or re.fullmatch(
            r"(?:(?:Photoshop|Illustrator|Word|Excel|PPT|可画|即梦|WorkBuddy)|[和及、/\s])+", canonical_skill_text(text), re.I):
        return ""
    if len(text) > 45 or non_fact(text) or re.search(
        r"[，,；;\n？?]|完成|海报|作业|课程|会用|会使用|使用|运用|做过|做了|采购和行政|几乎|独立", text):
        return ""
    label = literal_item_name(text, target["section"])
    if label:
        return label
    if re.search(r"^(?:我|本人)|没有|不方便|用了|用过|能力|大约|约\d|[零一二两三四五六七八九十\d]+(?:张|份|次|人)", text):
        return ""
    return text if len(text) <= 20 and safe_item_name(text) else ""


def _subject_hint(text: str) -> tuple[str, str]:
    """Explicit subjects outrank the extractor's section and follow-up ID."""
    if coursework_evidence(text):
        return "projects", "course"
    if re.search(r"周末|日常(?!用品|工作|行政|管理)|练手|自己玩|个人练习|自己练习", text):
        return "projects", "personal"
    if campus_evidence(text):
        return "campus", ""
    if re.search(r"(?:在|入职|就职于).{0,16}公司|公司里|咖啡店|店长", text) and not re.search(
        r"(?:没|未|不).{0,8}(?:做|设计|工作)", text):
        return "work_experience", ""
    if re.search(r"部长", text):
        return "campus", ""
    if re.search(r"采购|行政|考勤", text):
        return "work_experience", ""
    return "", ""


def _clause_subject(quote: str, evidence: str) -> tuple[str, str, str]:
    section, kind = _subject_hint(quote)
    context = quote
    if not section and quote and quote in evidence:
        # Adjacent continuation clauses may cross a full stop, but never a new
        # explicit subject. Do not let a deliverable (海报) become a subject.
        prefix = evidence[:evidence.find(quote)]
        if not re.match(r"(?:我|本人|其中|也|还|没有|不知道|选题|文案)", quote):
            prefix = re.split(r"[。！？!?\n]", prefix)[-1]
        else:
            prefix = prefix[-300:]
        poster_context = ""
        for part in reversed(re.split(r"[，,。；;：:！？!?\n]", prefix)):
            if not poster_context and "海报" in part:
                poster_context = part
            section, kind = _subject_hint(part)
            if section:
                context = part + "，" + quote
                break
        if not section and poster_context:
            section, context = "campus", poster_context + "，" + quote
    if not section and "海报" in quote:
        section = "campus"
    return section, kind, context


def _subject_owner(quote: str, evidence: str, items: list[dict], target=None) -> dict | None:
    if nearest := _nearest_named_owner(quote, evidence, items):
        return nearest
    section, kind, context = _clause_subject(quote, evidence)
    if not section:
        return None
    sentence = next((part for part in re.split(r"[。！？!?\n]", evidence) if quote in part), context)
    if re.search(r"另外|另一个|新的?(?:项目|工作|经历)|其他(?:的)?(?:项目|工作|经历)", sentence):
        return None
    # A poster for an explicitly established company/design project can belong
    # there. An unrelated purchasing/admin follow-up supplies no such evidence.
    if section == "campus" and not campus_evidence(context) and target:
        prior = " ".join(f["text"] for f in target.get("facts", []))
        if target["section"] != "campus" and re.search(r"海报|产品图|设计", prior) and not re.search(r"没有|没做|未做", prior):
            section = target["section"]
    name = literal_item_name(context, section)
    if section == "campus" and re.fullmatch(r"(?:协会|社团|学生会)?(?:的)?(?:宣传部)?", name):
        name = ""
    if kind == "course" and not name:
        sentence = next((part for part in re.split(r"[。！？!?\n]", evidence) if quote in part), context)
        name = literal_item_name(sentence, section)
    candidates = [item for item in items if item["section"] == section or (
        section == "work_experience" and item["section"] == "internship")]
    if kind and not name:
        candidates = [item for item in candidates if _subject_hint(
            " ".join([item["name"], *[f.get("source_quote", "") for f in item.get("facts", [])]]))[1] == kind]
    if name:
        named = [item for item in candidates if name in item["name"] or item["name"] in name]
        unnamed = [item for item in candidates if placeholder_name(item["name"])]
        candidates = named or (unnamed if len(unnamed) == 1 else [])
    if len({item["item_id"] for item in candidates}) == 1:
        return {**candidates[0], "name": name} if name and placeholder_name(candidates[0]["name"]) else candidates[0]
    label = name or ("课程作业（待补名称）" if kind == "course" else
                     "个人练习（待补名称）" if kind == "personal" else PLACEHOLDER_NAMES[section])
    return {"section": section, "item_id": str(uuid.uuid4()), "name": label, "facts": [], "raw_notes": []}


def _nearest_named_owner(quote: str, evidence: str, items: list[dict]) -> dict | None:
    """Resolve adjacent named experiences before falling back to section hints."""
    if not quote or quote not in evidence:
        return None
    new_subject = r"另外|另一个|新的?(?:项目|工作|经历)|其他(?:的)?(?:项目|工作|经历)"
    if re.search(new_subject, quote):
        return None
    section = _subject_hint(quote)[0]
    prefix = evidence[:evidence.find(quote)].rsplit("\n", 1)[-1]
    if not re.match(r"(?:我|本人|其中|也|还|没有|不知道|选题|文案)", quote):
        prefix = re.split(r"[。！？!?\n]", prefix)[-1]
    for part in [quote, *reversed(re.split(r"[，,。；;！？!?\n]", prefix[-300:]))]:
        named = {item["item_id"]: item for item in items
                 if item["section"] in {"work_experience", "internship", "campus"}
                 and item.get("name") and not placeholder_name(item["name"]) and item["name"] in part}
        if len(named) == 1:
            item = next(iter(named.values()))
            return item if not section or section == item["section"] or (
                section == "work_experience" and item["section"] == "internship") else None
        if len(named) > 1 or (part != quote and (_subject_hint(part)[0] or re.search(new_subject, part))):
            break  # A new or ambiguous explicit subject stops carry-over.
    return None


def _implicit_followup_allowed(evidence: str, outline: list[dict], target: dict) -> bool:
    from app.services.fact_guard import normalize_text
    if target.get("question_kind") == "name":
        return bool(_name_answer(evidence, target))
    if non_fact(evidence) or skill_declaration(evidence):
        return False
    section, kind = _subject_hint(evidence)
    if section and (section != target["section"] or (kind and _subject_hint(
            " ".join(f["text"] for f in target.get("facts", [])))[1] != kind)):
        return False
    if re.search(r"另外|(?:新(?:的)?(?:一(?:个|项|段))?|另(?:一(?:个|项|段|次)|的)?|别的|其他(?:的)?)\s*(?:项目|活动|经历|工作|实习|公司)", evidence):
        return False
    # An explicit newly named subject also stops an implicit carry-over.
    subjects = re.findall(r'[“「\"\']([^”」\"\']+)[”」\"\']\s*(?:项目|活动)|(?:项目|活动|小程序|应用|工具).{0,8}(?:叫|名为)\s*[“「\"\']?([^，。；;\s”」\"\']+)', evidence)
    names = [name for pair in subjects for name in pair if name]
    names += re.findall(r'(?:我在|我(?:开发|参与|做)(?:了|过)?)\s*([^，,。；;\s「“\"\']{1,30}?)\s*(?:项目|活动)', evidence)
    if any(normalize_text(name) not in normalize_text(target["name"])
           and normalize_text(target["name"]) not in normalize_text(name) for name in names):
        return False
    mentioned = [item for item in outline if item["name"] and normalize_text(item["name"]) in normalize_text(evidence)]
    if mentioned:
        return all(item["item_id"] == target["item_id"] for item in mentioned)
    if section:
        return True
    # A short numeric/ownership answer can omit its subject. Longer content
    # needs a shared topic; merely containing a generic action verb is not enough.
    if re.fullmatch(r"(?:是|我|本人|我们|基本|大约|约|共|一共|有|由|了|的|都|自己|独立|一起|完成|负责|制作|[零一二两三四五六七八九十百\d余多]+|人|张|个|家|次|[，,。\s])+", evidence):
        return True
    context = " ".join([target["name"], *[f["text"] for f in target.get("facts", [])], *target.get("raw_notes", [])])
    generic = r"我|本人|目前|这个|那个|主要|后来|完成|负责|参与|使用|工作|做了|做过|一个|项目|经历"
    left, right = (re.sub(generic, "", normalize_text(value)) for value in (evidence, context))
    return bool(_bigrams(left) & _bigrams(right))


async def extract_facts_patch(message: str, collected: dict, llm, *, turn_id: str = "",
                              metadata_context=None, semantic_check=None,
                              previous_assistant: str = "") -> dict:
    """Reject individual unsupported facts while retaining the rest of a patch."""
    from app.services.fact_guard import lexical_fact_errors, normalize_text, verify_semantics

    complete, tail = split_incomplete_tail(message)
    empty = {"items": [], "basic_info": {}, "skills": [], "corrections": [], "removals": [], "rejected": [], "uncovered": [],
             "incomplete": [tail] if tail else []}
    if not isinstance(message, str) or not message.strip() or llm is None:
        return empty
    visible = normalize_fact_store(collected)
    outline = fact_item_outline(visible)
    evidence = _candidate_evidence(complete)
    prior_target = followup_item(visible)
    if prior_target and placeholder_name(prior_target["name"]) and re.search(
            r"名称|名字|公司.{0,5}(?:叫|名)|组织.{0,5}(?:叫|名)", previous_assistant):
        prior_target["question_kind"] = "name"
    naming_answer = _name_answer(evidence, prior_target) if prior_target and prior_target.get("question_kind") == "name" else ""
    target = prior_target if prior_target and _implicit_followup_allowed(evidence, outline, prior_target) else None
    payload = {"message": complete, "existing": [
        {**item, "facts": [{"id": f["id"], "text": f["text"]} for f in item["facts"]]} for item in outline],
               "metadata_context": metadata_context or [],
               "previous_assistant": (previous_assistant or "")[:500]}
    if target:
        payload["followup_target"] = {key: target[key] for key in ("item_id", "section", "name")}
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from app.services.model_privacy import ContactRedactor, redact_model_messages
        privacy = ContactRedactor()
        messages = redact_model_messages([SystemMessage(content=_CONTRACT),
                                          HumanMessage(content=json.dumps(payload, ensure_ascii=False))], privacy)
        from app.config import get_settings
        model = llm if getattr(get_settings(), "LLM_EXTRACTOR_THINKING", True) else without_thinking(llm)
        response = await label_run(model, "fact_extractor").ainvoke(messages)
        candidate = privacy.restore(_content(response))
    except Exception:
        return empty
    if not isinstance(candidate, dict):
        return empty
    result = copy.deepcopy(empty)
    evidence = _candidate_evidence(complete)
    known = {(item.get("item_id"), fact.get("id")) for section in FACT_SECTIONS
             for item in visible.get(section, []) if isinstance(item, dict)
             for fact in item.get("facts", []) if fact.get("status") == "active"}
    known_items = {item.get("item_id") for section in FACT_SECTIONS
                   for item in visible.get(section, []) if isinstance(item, dict)}
    semantic_pairs = []
    pending = []
    ambiguous_owner = False

    def validated(raw):
        if not isinstance(raw, dict):
            return None
        text, quote = str(raw.get("text", "")).strip(), str(raw.get("source_quote", "")).strip()
        if not text or not quote or normalize_text(quote) not in normalize_text(evidence):
            result["rejected"].append({"text": text, "reason": "source_quote_not_in_candidate_message"})
            return None
        if (non_fact(text) or non_fact(quote)) and not constraint_only(quote):
            result.setdefault("metadata_context", []).append(quote)
            return None
        if skill_declaration(quote):
            return None
        if naming_answer == "refused":
            return None
        context_clauses = [part for part in re.split(r"[，,。；;\n]", evidence) if quote in part]
        if context_clauses and all(non_fact(part) for part in context_clauses) and not constraint_only(quote):
            result.setdefault("metadata_context", []).extend(context_clauses)
            return None
        if _quote_has_unquoted_limit(evidence, quote):
            result["rejected"].append({"text": text, "reason": "source_quote_omits_limit"})
            return None
        if (errors := lexical_fact_errors(text, quote)):
            result["rejected"].append({"text": text, "reason": errors})
            return None
        fact = new_fact(text, kind="status_limit" if constraint_only(quote) else raw.get("kind", "context"), quote=quote,
                        source="chat", turn_id=turn_id)
        if _is_large_rewrite(text, quote):
            semantic_pairs.append({"id": fact["id"], "text": text, "source_quotes": [quote]})
            pending.append(fact)
        return fact

    raw_items = []
    subject_items = copy.deepcopy(outline)
    for raw_index, raw_item in enumerate(candidate.get("items", []) if isinstance(candidate.get("items"), list) else []):
        if not isinstance(raw_item, dict):
            continue
        if raw_item.get("item_id") and raw_item["item_id"] not in known_items:
            result["rejected"].append({"text": str(raw_item.get("name", "")), "reason": "unknown_item_id"})
            continue
        raw_item = {**raw_item, "_raw_index": raw_index}
        raw_facts = raw_item.get("facts")
        raw_facts = [fact for fact in raw_facts if isinstance(fact, dict)] if isinstance(raw_facts, list) else []
        if not raw_facts:
            if prior_target and prior_target.get("question_kind") == "name" and not naming_answer:
                result.setdefault("raw_notes", []).extend(note for note in raw_item.get("raw_notes") or []
                    if isinstance(note, str) and note in evidence)
            else:
                raw_items.append(raw_item)
        for fact in raw_facts:
            quote = str(fact.get("source_quote") or "")
            parts = [part.strip() for part in re.split(r"[，,。；;\n]", quote) if part.strip()]
            scopes = {_subject_hint(part) for part in parts} - {("", "")}
            split = len(parts) > 1 and (len(scopes) > 1 or any(non_fact(p) or skill_declaration(p) or wording_constraint(p)
                                       or (raw_item.get('section') != 'education' and personal_header(p)) for p in parts))
            fragments = [{"text": part, "source_quote": part, "kind": fact.get("kind", "action")}
                         for part in parts] if split else [fact]
            for fragment in fragments:
                quote = str(fragment.get("source_quote") or "")
                if raw_item.get('section') != 'education' and personal_header(quote):
                    result.setdefault('metadata_context', []).append(quote)
                    continue
                if (non_fact(quote) or non_fact(str(fragment.get("text") or ""))) and not constraint_only(quote):
                    if quote and quote in evidence:
                        result.setdefault("metadata_context", []).append(quote)
                    continue
                if skill_declaration(quote):
                    continue
                # Ordinary work/project matching retains the existing ambiguity
                # checks. Override model ownership only for explicit other subjects.
                scope_section = _clause_subject(quote, evidence)[0]
                owner = _nearest_named_owner(quote, evidence, subject_items) or (_subject_owner(quote, evidence, subject_items, target)
                         if quote and quote in evidence and (re.search(r"咖啡店|店长", evidence) or scope_section != "work_experience"
                             or raw_item.get("section") not in {"work_experience", "internship"}
                             or (prior_target and (prior_target.get("question_kind") == "name" or target is None))) else None)
                notes = [quote] if any(isinstance(note, str) and quote in note for note in raw_item.get("raw_notes") or []) else []
                if owner:
                    if not any(row["item_id"] == owner["item_id"] for row in subject_items):
                        subject_items.append(owner)
                        # Keep this new identity available to validation, without
                        # pretending it was an existing model-supplied ID.
                        known_items.add(owner["item_id"])
                    owner.setdefault("facts", []).append({"text": quote, "source_quote": quote})
                    raw_items.append({**raw_item, "section": owner["section"], "item_id": owner["item_id"],
                                      "name": owner["name"], "facts": [fragment], "raw_notes": notes, "_scoped": True})
                elif prior_target and prior_target.get("question_kind") == "name" and not naming_answer:
                    # The model's stale work ID/name is not evidence of ownership.
                    result.setdefault("raw_notes", []).append(quote)
                elif prior_target and raw_item.get("item_id") == prior_target["item_id"] and not _implicit_followup_allowed(
                        quote, outline, prior_target):
                    result.setdefault("raw_notes", []).append(quote)
                else:
                    raw_items.append({**raw_item, "facts": [fragment],
                                      "raw_notes": notes if split else raw_item.get("raw_notes", [])})
    grouped = {}
    for item in raw_items:
        identity = (item["_raw_index"], item.get("item_id"))
        if identity in grouped:
            grouped[identity].setdefault("facts", []).extend(item.get("facts") or [])
            grouped[identity].setdefault("raw_notes", []).extend(item.get("raw_notes") or [])
        else:
            grouped[identity] = item
    raw_items = list(grouped.values())
    for raw_item in raw_items:
        if not isinstance(raw_item, dict) or raw_item.get("section") not in FACT_SECTIONS:
            continue
        item_id = raw_item.get("item_id")
        owner = None
        if item_id and item_id not in known_items:
            result["rejected"].append({"text": str(raw_item.get("name", "")), "reason": "unknown_item_id"})
            continue
        if (prior_target and item_id == prior_target["item_id"] and target is None
                and normalize_text(prior_target["name"]) not in normalize_text(evidence)
                and not raw_item.get("_scoped")):
            result["rejected"].append({"text": str(raw_item.get("name", "")), "reason": "conflicting_followup_target"})
            continue
        if not item_id:
            name = normalize_text(raw_item.get("name", ""))
            matches = [item for item in outline if name and item["name"] and (
                name in normalize_text(item["name"]) or normalize_text(item["name"]) in name)]
            if len(matches) > 1:
                ambiguous_owner = True
                result["rejected"].append({"text": str(raw_item.get("name", "")), "reason": "item_name_not_in_candidate_message"})
                continue
            if matches and (name in normalize_text(evidence) or _implicit_followup_allowed(evidence, outline, matches[0])):
                owner = matches[0]
            elif target and (naming_answer or not name or name not in normalize_text(evidence)):
                owner = target
            if owner:
                item_id = owner["item_id"]
        else:
            owner = next((row for row in subject_items if row["item_id"] == item_id), None)
        section = owner["section"] if owner else raw_item["section"]
        raw_facts = raw_item.get("facts") if isinstance(raw_item.get("facts"), list) else []
        item_evidence = "\n".join(str(f.get("source_quote") or "") for f in raw_facts
                                  if isinstance(f, dict) and f.get("source_quote")
                                  and str(f["source_quote"]) in evidence)
        if not item_id and section in {"projects", "open_source", "campus"} and campus_evidence(item_evidence):
            section = "campus"
        employment = literal_employment(item_evidence)
        if not item_id and employment[0]:
            section = 'internship' if '实习' in employment[1] else 'work_experience'
        from app.services.resume_field_hygiene import trim_name_punctuation
        label = trim_name_punctuation(raw_item.get("name") or "")
        if section == 'education':
            from app.services.education_fields import clean_education_value
            label = clean_education_value('school', label)
        literal = literal_item_name(item_evidence or evidence, section)
        if owner:
            label = literal if literal and placeholder_name(owner["name"]) else owner["name"]
        elif not item_id:
            label = literal or (label if safe_item_name(label) and normalize_text(label) in normalize_text(evidence)
                                else PLACEHOLDER_NAMES[section])
        facts = []
        for raw in raw_facts:
            if fact := validated(raw):
                if re.fullmatch(r"(?:咖啡店|公司)(?:名|名字|名称)?(?:叫|是|名为).+", fact["source_quote"]):
                    if named := literal_item_name(fact["source_quote"], section):
                        fact["field"], fact["text"] = FACT_LABELS[section], named
                if raw.get("field") in FACT_FIELDS[section] and not constraint_only(fact["source_quote"]):
                    fact["field"] = raw["field"]
                if section == "education":
                    from app.services.education_fields import clean_education_value
                    fact["text"] = clean_education_value(fact.get("field"), fact["text"])
                if fact.get("field") == "major":
                    from app.agents.turn_actions import parse_education_fields
                    if not safe_major(fact['text']) or parse_education_fields(evidence).get('major') != fact['text']:
                        continue
                if fact.get("field") == FACT_LABELS[section] and section != "awards" and not safe_item_name(fact["text"]):
                    continue
                if section == "campus" and (role := re.search(r"担任(?:了)?([^，,。；;\n]{1,16}(?:部长|干事|委员|主席|负责人))", fact["source_quote"])):
                    role_fact = new_fact(role[1], kind="role", quote=role[1], turn_id=turn_id)
                    role_fact["field"] = "role"
                    facts.append(role_fact)
                if (fact.get("field") == "role" or fact["kind"] == "role") and is_project_status(fact["text"]):
                    fact["kind"] = "status_limit"
                    fact.pop("field", None)
                facts.append(fact)
        if section in {'work_experience', 'internship'} and employment[0] == label and not any(f.get('field') == 'title' for f in facts):
            role = new_fact(employment[1], kind='role', quote=employment[1], turn_id=turn_id)
            role['field'] = 'title'
            facts.append(role)
        raw_notes = raw_item.get("raw_notes") if isinstance(raw_item.get("raw_notes"), list) else []
        notes = [note for note in raw_notes
                 if isinstance(note, str) and note.strip() and normalize_text(note) in normalize_text(evidence)]
        if section != 'education':
            notes = [note for note in notes if not any(non_fact(part.strip()) or personal_header(part)
                     for part in re.split(r'[，,。；;\n]', note) if part.strip())]
        if not facts and not notes:
            continue
        result["items"].append({"section": section, "item_id": item_id or str(uuid.uuid4()),
                                "name": label, "facts": facts,
                                "raw_notes": list(dict.fromkeys(notes))})
        links = raw_item.get("links") or []
        accepted = [link for link in links if isinstance(link, dict)
                    and isinstance(link.get("url"), str) and link["url"] in evidence
                    and isinstance(link.get("text"), str) and link["text"] in evidence]
        if accepted:
            result["items"][-1]["links"] = accepted
    for raw in candidate.get("corrections", []) if isinstance(candidate.get("corrections"), list) else []:
        if not isinstance(raw, dict) or (raw.get("item_id"), raw.get("fact_id")) not in known:
            if isinstance(raw, dict):
                result["rejected"].append({"text": str(raw.get("fact_id", "")), "reason": "unknown_correction_target"})
            continue
        replacement = validated(raw.get("replacement"))
        if replacement:
            old = next(fact for section in FACT_SECTIONS for item in visible.get(section, [])
                       if item.get("item_id") == raw["item_id"] for fact in item.get("facts", [])
                       if fact.get("id") == raw["fact_id"])
            if old.get("field"):
                replacement["field"] = old["field"]
                if old['field'] == 'major':
                    from app.agents.turn_actions import parse_education_fields
                    if parse_education_fields(message).get('major') != replacement['text']:
                        continue
            result["corrections"].append({"item_id": raw["item_id"], "fact_id": raw["fact_id"], "replacement": replacement})
    for raw in candidate.get("removals", []) if isinstance(candidate.get("removals"), list) else []:
        if isinstance(raw, dict) and (raw.get("item_id"), raw.get("fact_id")) in known:
            result["removals"].append({"item_id": raw["item_id"], "fact_id": raw["fact_id"]})
        elif isinstance(raw, dict):
            result["rejected"].append({"text": str(raw.get("fact_id", "")), "reason": "unknown_removal_target"})
    basic = candidate.get("basic_info")
    if isinstance(basic, dict):
        for key, value in basic.items():
            if key in {"name", "phone", "email", "location", "city", "github", "objective", "availability"} and isinstance(value, str) and value.strip() and normalize_text(value) in normalize_text(evidence) and not _quote_has_unquoted_limit(evidence, value):
                if key == "objective" and not safe_objective(value):
                    result.setdefault("metadata_context", []).append(value.strip())
                    continue
                result["basic_info"]["location" if key == "city" else key] = value.strip()
            elif key == "links" and isinstance(value, list):
                result["basic_info"][key] = [link for link in value if isinstance(link, dict)
                    and isinstance(link.get("url"), str) and link["url"] in evidence
                    and isinstance(link.get("text"), str) and link["text"].lower() in evidence.lower()]
    skills = candidate.get("skills")
    from app.services.candidate_skills import sourced_skill_name, skill_identity
    from app.services.fact_guard import _skill_affirmed as affirmed_skill
    if isinstance(skills, list):
        for value in skills:
            name = value if isinstance(value, str) else value.get("name") if isinstance(value, dict) else ""
            quote = value.get("source_quote", name) if isinstance(value, dict) else name
            normalized_name = canonical_skill_text(name)
            normalized_quote = canonical_skill_text(quote)
            if name and quote and normalize_text(quote) in normalize_text(evidence) and normalize_text(normalized_name) in normalize_text(normalized_quote) and affirmed_skill(canonical_skill_text(evidence), normalized_name) and not lexical_fact_errors(normalized_name, normalized_quote):
                name = sourced_skill_name(normalized_name, evidence)
                result["skills"].append({"name": name, "source_quote": quote, "source": "chat", "turn_id": turn_id})
    for skill in declared_skills(evidence):
        skill['name'] = sourced_skill_name(skill['name'], evidence)
        if not any(skill_identity(row["name"]) == skill_identity(skill["name"]) for row in result["skills"]):
            result["skills"].append({**skill, "source": "chat", "turn_id": turn_id})
    if semantic_pairs:
        try:
            checker = semantic_check or (lambda pairs: verify_semantics(pairs, llm, run_name="extract_verify"))
            verdicts = checker(semantic_pairs)
            if inspect.isawaitable(verdicts):
                verdicts = await verdicts
        except Exception:
            verdicts = {}
        failed = {fact["id"] for fact in pending
                  if not isinstance(verdicts, dict) or verdicts.get(fact["id"], {}).get("verdict") != "pass"}
        result["rejected"].extend({"text": fact["text"], "reason": "semantic_verification_failed"}
                                  for fact in pending if fact["id"] in failed)
        for item in result["items"]:
            item["facts"] = [fact for fact in item["facts"] if fact["id"] not in failed]
        result["items"] = [item for item in result["items"] if item["facts"] or item["raw_notes"]]
        result["corrections"] = [entry for entry in result["corrections"] if entry["replacement"]["id"] not in failed]
    if tail and not result["items"] and not re.search(r"新项目|另一个项目|另外一个项目", evidence):
        owners = [item for item in outline if item["section"] in {"projects", "work_experience", "internship"}
                  and item["name"] and (item["name"] in evidence or (
                      item["name"] in previous_assistant and re.search(r"团队|分工|负责|几人|人数", previous_assistant)))]
        if len(owners) == 1:
            owner = owners[0]
            result["items"].append({"section": owner["section"], "item_id": owner["item_id"],
                                    "name": owner["name"], "facts": [], "raw_notes": [evidence]})
    from app.services.candidate_sections import parse_header_fields, parse_labelled_items
    header = parse_header_fields(evidence)
    for key, value in header.items():
        if key == "links":
            existing = result["basic_info"].setdefault("links", [])
            existing.extend(link for link in value if link not in existing)
        elif not _quote_has_unquoted_limit(evidence, value):
            result["basic_info"].setdefault(key, value)
    claimed_rows = set()
    for section, rows in parse_labelled_items(evidence, turn_id=turn_id).items():
        for row in rows:
            quote = row["raw_notes"][0]
            # An explicitly labelled row supplies the section and repository title,
            # even when a model incorrectly called it a project named 「自己」.
            owner = next((item for item in result["items"] if id(item) not in claimed_rows and any(
                fact.get("field") in {None, "pr"} and fact.get("source_quote")
                and normalize_text(fact["source_quote"]) in normalize_text(quote)
                for fact in item["facts"])), None)
            if owner is None:
                owner = {"section": section, "item_id": row["item_id"], "name": row["name"],
                         "facts": [], "raw_notes": []}
                result["items"].append(owner)
            claimed_rows.add(id(owner))
            owner.update(section=section, name=row["name"])
            known_quotes = {fact["source_quote"] for fact in owner["facts"]}
            owner["facts"].extend(fact for fact in row["facts"] if fact["source_quote"] not in known_quotes
                                  or fact.get("field"))
            owner["raw_notes"].extend(note for note in row["raw_notes"] if note not in owner["raw_notes"])
            if row.get("links"):
                owner["links"] = row["links"]
    coverage_evidence = evidence + (" " + tail if tail else "")
    # The model may omit a literal major/degree span. Recover structured fields
    # here so generation, history recovery and normal collection share the fix.
    from app.agents.turn_actions import parse_education_fields
    education_evidence = '\n'.join(line for line in evidence.splitlines()
                                   if not re.search(r'学校.{0,8}(?:改|写|填|换)|写全称|学校全称', line))
    fields = parse_education_fields(education_evidence)
    if fields.get("school"):
        school = fields["school"]
        owner = next((row for row in result["items"] if row["section"] == "education" and (
            row["name"] == school or any(f.get("field") == "school" and f["text"] == school for f in row["facts"]))), None)
        if owner is None:
            prior = next((row for row in visible.get("education", []) if row.get("school") == school), None)
            owner = {"section": "education", "item_id": prior["item_id"] if prior else str(uuid.uuid4()),
                     "name": school, "facts": [], "raw_notes": []}
            result["items"].append(owner)
        for field, value in fields.items():
            if not any(f.get("field") == field for f in owner["facts"]):
                fact = new_fact(value, kind="context", quote=value, turn_id=turn_id)
                fact["field"] = field
                owner["facts"].append(fact)
    _cover_dropped_clauses(result, coverage_evidence, turn_id, lexical_fact_errors, normalize_text,
                           followup_target=None if ambiguous_owner else target, outline=outline)
    # A literal answer to the one naming question updates the existing identity,
    # even when the model returns no facts or invents a new item without an ID.
    if target and naming_answer and naming_answer != "refused":
        label = naming_answer
        if label:
            entries = [item for item in result["items"] if item["item_id"] == target["item_id"] or item["name"] == label]
            entry = entries[0] if entries else {"section": target["section"], "item_id": target["item_id"], "facts": [], "raw_notes": []}
            if not entries:
                result["items"].append(entry)
            entry.update(section=target["section"], item_id=target["item_id"], name=label)
            fact = new_fact(label, kind="context", quote=label, turn_id=turn_id)
            fact["field"] = FACT_LABELS[target["section"]]
            entry["facts"].append(fact)
    # Deterministic subject recovery and model rows may describe the same
    # explicitly named course/school. Reuse that identity before applying facts.
    identities = {}
    for item in result['items']:
        name = item['name']
        if item['section'] == 'projects' and placeholder_name(name):
            named = {literal_item_name(sentence, 'projects') for sentence in re.split(r'[。\n]', evidence)
                     if coursework_evidence(sentence) and any(f['source_quote'] in sentence for f in item['facts'])}
            named.discard('')
            if len(named) == 1:
                item['name'] = name = named.pop()
        if item['section'] not in {'projects', 'education'} or placeholder_name(name):
            continue
        key = (item['section'], normalize_text(name))
        prior = next((row for row in outline if row['section'] == item['section'] and normalize_text(row['name']) == key[1]), None)
        item['item_id'] = identities.setdefault(key, prior['item_id'] if prior else item['item_id'])
    merged = {}
    for item in result["items"]:
        if item["item_id"] in merged:
            row = merged[item["item_id"]]
            row["facts"].extend(f for f in item["facts"] if not any(
                (f["text"], f.get("field")) == (old["text"], old.get("field")) for old in row["facts"]))
            row["raw_notes"].extend(note for note in item["raw_notes"] if note not in row["raw_notes"])
            if item.get("links"):
                row.setdefault("links", []).extend(link for link in item["links"] if link not in row["links"])
        else:
            merged[item["item_id"]] = item
    result["items"] = list(merged.values())
    from app.services.experience_dates import recover_experience_dates
    recover_experience_dates(result, evidence, outline, turn_id)
    for item in result["items"]:
        course_quote = next((f["source_quote"] for f in item["facts"] if coursework_evidence(f["source_quote"])
                             and not re.search(r"(?:不是|并非|不属于|没|未).{0,8}(?:作业|课程)", f["source_quote"])), "")
        if item["section"] == "projects" and course_quote and not any(f["kind"] == "status_limit" for f in item["facts"]):
            item["facts"].append(new_fact("课程作业", kind="status_limit", quote=course_quote, turn_id=turn_id))
        item["raw_notes"].extend(fact["source_quote"] for fact in item["facts"]
                                 if fact["source_quote"] not in item["raw_notes"])
    result["items"] = [item for item in result["items"] if item["facts"] or item["raw_notes"]]
    _log_rejected(result["rejected"], turn_id)
    return result


def _cover_dropped_clauses(result: dict, evidence: str, turn_id: str, lexical_fact_errors, normalize_text,
                           *, followup_target: dict | None = None, outline: list[dict] | None = None) -> None:
    """未被任何已接受事实覆盖的动作/结果子句：用子句原文作保守事实重试，仍不行则记入 uncovered。"""
    quotes = [fact["source_quote"] for item in result["items"] for fact in item["facts"]]
    quotes += [entry["replacement"]["source_quote"] for entry in result["corrections"]]
    # Literal skill declarations already have a destination. Do not report
    # them as lost experience actions; concrete deliveries still need an owner.
    quotes += [skill["source_quote"] for skill in result["skills"]
               if re.match(r"^(?:我)?(?:会(?:使用|用)?|熟悉|掌握|了解|用过|使用过|做过(?:日常摄影|产品拍摄))", skill["source_quote"])
               and not re.search(r"\d|完成|制作了|设计了|负责|交付|上线", skill["source_quote"])]
    objective = (result.get("basic_info") or {}).get("objective")
    if objective:
        quotes += [part for part in _CLAUSE_SPLIT.split(evidence) if objective in part and re.search(r"想投|求职|应聘|找.{0,5}工作", part)]
    clauses = uncovered_action_clauses(evidence, quotes)
    # Course headers and short delivery fragments have an explicit subject even
    # when they lack the first-person/action pattern used by the generic fallback.
    for clause in re.split(r"[，,。；;\n]", evidence):
        clause = clause.strip()
        if constraint_only(clause) and not _clause_covered(normalize_text(clause), [normalize_text(q) for q in quotes]):
            clauses.append(clause)
        elif (clause and not non_fact(clause) and not skill_declaration(clause)
                and not _PLAN_OR_NEGATED.search(clause) and not _INSTRUCTION.search(clause)
                and _clause_subject(clause, evidence)[0] in {"projects", "campus"}
                and (coursework_evidence(clause) or re.search(r"完成|拍摄|排版|海报|使用|做了", clause))
                and not _clause_covered(normalize_text(clause), [normalize_text(q) for q in quotes])
                and clause not in clauses):
            clauses.append(clause)
    for clause in clauses:
        section = _clause_subject(clause, evidence)[0]
        owner = (_subject_owner(clause, evidence, [*result["items"], *(outline or [])], followup_target)
                 if section in {"projects", "campus"} or (section == "work_experience" and re.search(r"咖啡店|店长|公司里", evidence)) else None)
        if owner is not None:
            # Existing outlines are read-only; a patch must contain new facts only.
            owner = next((item for item in result["items"] if item["item_id"] == owner["item_id"]),
                         {**owner, "facts": [], "raw_notes": []})
        else:
            owner = _owner_item(result["items"], clause, evidence, normalize_text, followup_target=followup_target)
        errors = lexical_fact_errors(clause, clause) if owner is not None else ["no_owner_item"]
        if owner is None or errors or _quote_has_unquoted_limit(evidence, clause):
            if constraint_only(clause):
                continue  # A missing owner is not a missing resume bullet.
            result["rejected"].append({"text": clause, "reason": "coverage_fallback_failed:" + _reason_code(errors or "limit")})
            result["uncovered"].append(clause)
            continue
        if not any(item is owner for item in result["items"]):
            result["items"].append(owner)
        owner["facts"].append(new_fact(_third_person(clause), kind=_fact_kind_for_clause(clause), quote=clause,
                                       source="chat", turn_id=turn_id))
        logger.info("fact_coverage_fallback turn=%s hash=%s", turn_id or "-",
                    hashlib.sha256(clause.encode("utf-8")).hexdigest()[:10])


def _third_person(clause: str) -> str:
    """去掉句首的「我(还/也)」口语主语，其余原文不动（不新增信息）；去完为空则保持原句。"""
    cleaned = re.sub(r"^(.{0,3}?)我(?:还|也|又|就)?", r"\1", clause, count=1).strip()
    return cleaned if len(cleaned) >= 4 else clause


def _owner_item(items: list[dict], clause: str, evidence: str, normalize_text,
                *, followup_target: dict | None = None):
    """同句已有事实优先；否则只接续确定的追问目标，新经历不沿用。"""
    if nearest := _nearest_named_owner(clause, evidence, items):
        return nearest
    wanted = normalize_text(clause)
    sentence = next((part for part in re.split(r"(?<=[。！？!?\n])", evidence) if clause in part), "")
    sentence_norm = normalize_text(sentence)
    candidates = [item for item in items if item["section"] in {"projects", "work_experience", "internship", "campus", "open_source", "awards"}]
    candidates = [item for item in candidates if _implicit_followup_allowed(clause, candidates, item)
                  or (split_incomplete_tail(evidence)[1] and _implicit_followup_allowed(sentence, candidates, item))]
    noted = [item for item in candidates if any(wanted in normalize_text(note) for note in item.get("raw_notes", []))]
    if noted:
        return noted[0] if len({item["item_id"] for item in noted}) == 1 else None
    start = sentence.find(clause)
    best, best_end, ambiguous = None, -1, False
    for item in candidates:
        for fact in item["facts"]:
            pos = sentence.find(fact["source_quote"]) if sentence else -1
            if 0 <= pos <= start and pos > best_end and normalize_text(fact["source_quote"]) in sentence_norm:
                best, best_end = item, pos
                ambiguous = False
            elif best is not None and pos == best_end and item["item_id"] != best["item_id"]:
                ambiguous = True
    if ambiguous:
        return None
    if best is None and split_incomplete_tail(evidence)[1]:
        same_sentence = [item for item in candidates if any(
            normalize_text(fact["source_quote"]) in sentence_norm for fact in item["facts"])]
        if len(same_sentence) == 1:
            return same_sentence[0]
    if best is not None:
        return best
    if followup_target and _implicit_followup_allowed(evidence, candidates, followup_target):
        return next((item for item in items if item["item_id"] == followup_target["item_id"]),
                    {**{key: followup_target[key] for key in ("section", "item_id", "name")},
                     "facts": [], "raw_notes": []})
    return None


def apply_fact_patch(collected: dict, patch: dict) -> dict:
    """Apply validated sparse patch; previous facts remain available for audit."""
    result = normalize_fact_store(collected)
    if patch.get("raw_notes"):
        notes = result.setdefault("raw_notes", [])
        notes.extend(note for note in patch["raw_notes"] if note and note not in notes)
    if patch.get("metadata_context"):
        context = result.setdefault("metadata_context", [])
        context.extend(value for value in patch["metadata_context"] if value not in context)
    basic = result.setdefault("basic_info", {})
    for key, value in (patch.get("basic_info") or {}).items():
        # A sparse extraction's empty field is absence, not a deletion command.
        if key == "links" and isinstance(value, list):
            links = basic.setdefault("links", [])
            links.extend(copy.deepcopy(link) for link in value if link not in links)
        elif isinstance(value, str) and value.strip():
            basic[key] = value.strip()
    skills = result.setdefault("skills", [])
    from app.services.candidate_skills import skill_identity
    for skill in patch.get("skills") or []:
        if isinstance(skill, dict) and skill.get("name"):
            old = next((old for old in skills if isinstance(old, dict)
                        and skill_identity(old.get('name', '')) == skill_identity(skill['name'])), None)
            if old is None:
                skills.append(copy.deepcopy(skill))
            elif re.search(r'了解|熟悉|基础|会一点|会点', skill['name']):
                old.update(copy.deepcopy(skill))
    by_id = {item.get("item_id"): item for section in FACT_SECTIONS
             for item in result.get(section, []) if isinstance(item, dict)}
    for entry in patch.get("items") or []:
        section, item_id = entry.get("section"), entry.get("item_id")
        if section not in FACT_SECTIONS or not item_id:
            continue
        item = by_id.get(item_id)
        if item is None:
            label = FACT_LABELS[section]
            item = {"item_id": item_id, label: entry.get("name", ""), "facts": [], "raw_notes": []}
            result.setdefault(section, []).append(item)
            by_id[item_id] = item
        elif placeholder_name(item.get(FACT_LABELS[section], "")) and not placeholder_name(entry.get("name", "")) and entry.get("name"):
            item[FACT_LABELS[section]] = entry["name"]
        if entry.get("links"):
            item.setdefault("links", []).extend(link for link in entry["links"] if link not in item["links"])
        existing = {fact.get("id") for fact in item.setdefault("facts", [])}
        item["facts"].extend(copy.deepcopy(fact) for fact in entry.get("facts", []) if fact.get("id") not in existing)
        notes = item.setdefault("raw_notes", [])
        notes.extend(note for note in entry.get("raw_notes", []) if note not in notes)
    for entry in patch.get("corrections") or []:
        item = by_id.get(entry.get("item_id"))
        if item is None:
            continue
        old = next((fact for fact in item["facts"] if fact.get("id") == entry.get("fact_id") and fact.get("status") == "active"), None)
        if old and isinstance(entry.get("replacement"), dict):
            old["status"] = "superseded"
            replacement = copy.deepcopy(entry["replacement"])
            replacement["replaces"] = old["id"]
            item["facts"].append(replacement)
            quote = replacement.get("source_quote")
            if quote and quote not in item.setdefault("raw_notes", []):
                item["raw_notes"].append(quote)
    for entry in patch.get("removals") or []:
        item = by_id.get(entry.get("item_id"))
        if item:
            for fact in item["facts"]:
                if fact.get("id") == entry.get("fact_id"):
                    fact["status"] = "deleted"
    return normalize_fact_store(result)
