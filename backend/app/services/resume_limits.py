"""Keep active experience limits visible when writing or trimming a document."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Mapping, Sequence

from app.services.fact_guard import (
    _experience_negation_text, _source_quote, contradicts_limit,
    normalize_text, strip_absence,
)
from app.services.resume_facts import active_facts_for_writer


_ASSERTED_LIMIT = re.compile(
    r"尚未|从未|并未|没有|不曾|未曾|不负责|不是|并非|不属于|"
    r"(?:未|没)(?:上线|发布|完成|部署|实现|验证|参与|测试|统计|做|测)|"
    r"计划|准备|打算|仅(?:负责|参与|完成)|只(?:负责|参与|完成)|"
    r"\b(?:planned|not|never|without)\b", re.I)
_PHASE_LIMITS = (
    re.compile(r"原型|\bprototype\b", re.I),
    re.compile(r"\bdemo\b", re.I),
    re.compile(r"模拟|\bmock\b", re.I),
)
_STATUS_LIMIT = re.compile(
    _ASSERTED_LIMIT.pattern + r"|原型|模拟|\b(?:demo|mock|prototype)\b", re.I)
_SENTENCE_BREAK = re.compile(r"[。；;！？!?\n]+")
_COMMA_BREAK = re.compile(r"[，]|,(?!\d)")
_CLAUSE_BREAK = re.compile(r"[。；;！？!?\n]+|[，]|,(?!\d)")
_CONDITION_HINT = re.compile(
    r"如果|若|除非|只有|前提|条件|取决于|等待|要等|须经|批准|审批|验收|"
    r"在[^，,；;。]*(?:时|情况下)")
_BARE_LIMIT = re.compile(r"^(?:尚未|从未|并未|没有|不曾|未曾|未|没|计划|准备|打算)")
_SUBJECT_END = re.compile(r"(?:模块|功能|接口|系统|项目|页面|版本|环境|方案|服务|数据|统计|测试|流程|评估|工作)$")
_CONTRIBUTION_LIMIT = re.compile(
    r'不是.{0,8}(?:负责人|组长)|不负责|仅负责|只负责|'
    r'(?:由|是).{0,12}(?:其他成员|他人|同学|同事|队友).{0,12}(?:实现|写|负责|完成)|'
    r'(?:主管|经理|店长).{0,8}(?:审批|批准)|(?:审批|批准).{0,8}(?:主管|经理|店长)')
_METRIC_SCOPE = re.compile(r'课堂|离线|本地|自拟|人工判定|模拟')
_PURE_DENIAL = re.compile(r'^(?:也)?(?:不是.{0,8}(?:负责人|组长)|没有管理团队|'
                          r'(?:没有|无)(?:真实用户|线上测试|生产部署|并发|模型训练))')
_TEST_DENIAL = re.compile(r'^(?:也)?(?:没(?:有)?|未)(?:做|进行|开展)?线上压测$')
_TEAM = re.compile(r'\d+\s*人(?:课程|小组|团队|组队)*(?:项目|作业)')


def _live_quote(fact):
    source = _source_quote(fact)
    return fact['text'] if source.startswith('原始材料：') and '\n本轮更正：' in source else source


def _restore_item_header(item, facts, role_field):
    from app.services.resume_field_hygiene import sourced_role
    role = sourced_role(facts, item.get(role_field, ''), item.get('name') or item.get('company', ''))
    clauses = [c.strip() for fact in facts for c in _CLAUSE_BREAK.split(_live_quote(fact)) if c.strip()]
    labels = [c for c in clauses if _TEAM.fullmatch(c)]
    if any(re.fullmatch(r'项目(?:尚未|未)上线', c) for c in clauses):
        labels.append('未上线')
    for label in reversed(list(dict.fromkeys(labels))):
        if label not in role and label not in str(item.get('name', '')):
            role = f'{label} · {role}'.strip(' ·')
    if role or role_field in item:
        item[role_field] = role
    return labels


def _limit_clauses(fact: dict) -> list[str]:
    """Extract intact source clauses, never a limitation invented by fact.text.

    The guard's legacy fallback applies only when the original quote is absent.
    Kind is not evidence: imported action prose can be tagged status_limit just
    because it mentions a prototype. Keep only the relevant original clauses.
    """
    if fact.get("field") and fact["field"] not in {"description", "highlights"}:
        return []
    source = _source_quote(fact).strip()
    if not source or not _STATUS_LIMIT.search(_experience_negation_text(source)):
        return []
    limits = []
    for sentence in _SENTENCE_BREAK.split(source):
        clauses = [part.strip() for part in _COMMA_BREAK.split(sentence) if part.strip()]
        if any(_STATUS_LIMIT.search(_experience_negation_text(clause)) for clause in clauses) and _CONDITION_HINT.search(sentence):
            # Do not detach a plan from prerequisites, including a condition
            # inside a clause or after the action. Approval/acceptance/waiting
            # hints are deliberately conservative: ambiguity retains the full
            # sentence instead of making a conditional action unconditional.
            limits.append(sentence.strip())
            continue
        for index, clause in enumerate(clauses):
            if not _STATUS_LIMIT.search(_experience_negation_text(clause)):
                continue
            # “支付模块，尚未上线” and “若审批通过，计划部署” must not
            # become a claim about the entire project or an unconditional plan.
            start = index
            if index:
                previous = clauses[index - 1]
                subject_fragment = (_BARE_LIMIT.search(clause) and len(previous) <= 40
                                    and _SUBJECT_END.search(previous))
                if subject_fragment:
                    start -= 1
            limits.append("，".join(clauses[start:index + 1]))
    return list(dict.fromkeys(limits))


def _phase_markers(text: str) -> set[int]:
    """Visible phase markers count only as affirmative, current statements."""
    phases = set()
    for clause in _CLAUSE_BREAK.split(text):
        for number, pattern in enumerate(_PHASE_LIMITS):
            for match in pattern.finditer(clause):
                prefix = clause[:match.start()]
                if _ASSERTED_LIMIT.search(prefix):
                    continue
                phases.add(number)
    return phases


def _limit_key(text: str) -> str:
    # Only a narrow grammatical equivalence, preserving the action and object.
    text = re.sub(r"尚未|并未|还未|没有", "未", normalize_text(text)).strip("。；;.,，")
    text = text.replace('对一个', '对').replace('加了', '加')
    text = re.sub(r'(?:没(?:有)?|未)(?:做|进行|开展)?线上压测', '未做线上压测', text)
    text = re.sub(r'(?:仅|只)(?:面向|给)(?:班级|班里|全班)(?:进行)?演示', '只给班里演示', text)
    text = re.sub(r'是(.{1,12}(?:同学|同事|成员|队友))写的', r'由\1编写', text)
    # Narrow ownership equivalence: retain the module and the exact actor.
    # “负责/参与/协助/计划实现” are deliberately not equivalent to completion.
    return re.sub(r'由(?:组内|团队内)?(另一位(?:同学|同事|成员|队友))(?:编写|实现|完成)',
                  r'由\1编写', text)


def _already_visible(clause: str, texts: Sequence[str]) -> bool:
    key = _limit_key(clause)
    if re.fullmatch(r'.+由另一位(?:同学|同事|成员|队友)编写', key):
        # Compare the whole ownership clause: a negation, plan or partial
        # contribution around the same words does not establish completion.
        return any(key == _limit_key(part) for text in texts for part in _CLAUSE_BREAK.split(text))
    if key and any(key in _limit_key(text) for text in texts):
        return True
    # Deployment and demo audience are separate units. Preserve the literal
    # "only" boundary, but do not append the already expressed location again.
    parts = [c.strip() for c in _CLAUSE_BREAK.split(clause) if c.strip()]
    if len(parts) > 1:
        return all(_already_visible(part, texts) for part in parts)
    # 正文已换说法写出同一动作（如「对一个慢查询加了联合索引」→「定位慢查询并添加联合索引」）
    # 时不再原句追加；否定、边界类限定不走这条近似判断。
    if not re.search(r"没|未|不|无|非|仅|只|由|指导", clause) and not _CONTRIBUTION_LIMIT.search(clause):
        wanted = set(re.sub(r"[\W\d_a-zA-Z]|[的了一个对把将在并和与及等]", "", key))
        if len(wanted) >= 6 and any(len(wanted - set(_limit_key(text))) <= 1 for text in texts):
            return True
    # A prototype stage need not repeat whole imported action paragraphs. This
    # shortcut never discharges a negation, future plan, or responsibility limit.
    if not _ASSERTED_LIMIT.search(clause) and not _CONDITION_HINT.search(clause):
        wanted = _phase_markers(clause)
        # Mock/demo can qualify individual data or interfaces; seeing the word
        # elsewhere is insufficient. Explicit subsystem prototype scope is also
        # retained, even if another part of the same item already says 原型.
        if wanted != {0} or re.search(r"模块|接口|页面|功能|环境|数据|服务", clause):
            return False
        visible = set().union(*(_phase_markers(text) for text in texts))
        return bool(wanted) and wanted <= visible
    return False


_PHASES = (
    ("课程原型", re.compile(r"课程原型")),
    ("原型", re.compile(r"原型|prototype", re.I)),
    ("Demo", re.compile(r"\bdemo\b", re.I)),
    ("模拟数据", re.compile(r"模拟数据|\bmock\b", re.I)),
    ("小组作业", re.compile(r"小组作业")),
)


def _phase_label(text: str) -> str:
    """Current stage word. A plan or a denial does not count as the stage."""
    text = re.sub(r'https?://[^\s，。；;<>]+', '', text or '', flags=re.I)
    for clause in re.split(r"[，,。；;\n]", text or ""):
        if re.search(r"计划|准备|打算|并非|不是", clause):
            continue
        for label, pattern in _PHASES:
            if pattern.search(clause):
                return label
    return ""


_STAGE_PHRASE = re.compile(
    r"[，,；;]?\s*(?:在|以|作为|基于)(?:这个|该|此)?(?:课程原型|原型|[Dd]emo|模拟数据|小组作业)(?:项目)?"
    r"(?:中|里|形式|下|阶段)?(?:的)?")


def strip_stage_phrases(text: str) -> str:
    """去掉与标题行重复的阶段短语（「…，在课程原型中实现行程推荐」→「…，实现行程推荐」）。"""
    cleaned = _STAGE_PHRASE.sub(lambda m: "，" if m.group(0)[:1] in "，,；;" else "", text or "")
    return re.sub(r"^[，,；;\s]+|[，,；;\s]+$", "", re.sub(r"[，,]{2,}", "，", cleaned))


def preserve_item_limits(data: dict, meta: dict, collected_info: dict, *,
                         item_ids: Sequence[str], bullet_indices: Mapping[str, set[int]] | None = None,
                         reason: str = "contradicted_status_limit", constraints: Mapping | None = None,
                         restore_required: bool = True) -> tuple[dict, dict, list[dict]]:
    """Keep ordinary limits as prohibitions; integrate required qualifications.

    A stage word is written once on the role line when neither the title nor a
    bullet already states it. A bullet that asserts the denied outcome is
    recorded. Explicitly requested limits and limits on quantities stay with
    their action bullet when the caller supplies the session constraints.
    """
    result, metadata = deepcopy(data), deepcopy(meta)
    source = active_facts_for_writer(collected_info)
    source_items = {item.get("item_id"): item for section in ("projects", "work_experience", "internship", "campus", "open_source", "awards")
                    for item in source.get(section, []) if isinstance(item, dict)}
    from app.services.resume_field_hygiene import role_body
    relocated_roles = {fact.get('id') for section in ('projects', 'work_experience', 'internship', 'campus', 'open_source', 'awards')
                       for original in collected_info.get(section, []) if isinstance(original, dict)
                       for fact in original.get('facts', [])
                       if fact.get('status', 'active') == 'active'
                       and (fact.get('field') in {'role', 'title'} or fact.get('kind') == 'role')
                       and role_body(fact.get('text', ''))}
    allowed = set(item_ids)
    fallbacks = []
    for section in ("projects", "work_experience", "campus", "open_source", "awards"):
        field = "polished_bullets" if section == "projects" else "bullets"
        for item in result.get(section, []):
            identifier = item.get("item_id")
            if identifier not in allowed or item.get("hidden"):
                continue
            facts = [fact for fact in source_items.get(identifier, {}).get("facts", [])
                     if fact.get("status", "active") == "active"]
            quotes = "\n".join(_live_quote(fact) for fact in facts)
            role_field = 'title' if section == 'work_experience' else 'summary' if section == 'open_source' else 'role'
            labels = _restore_item_header(item, facts, role_field)
            phase = _phase_label(quotes)
            explicit = bool((constraints or {}).get('preserve_explicit_limits'))
            def clean_body(text):
                from app.services.candidate_language import without_wording_constraints
                text = without_wording_constraints(text)
                # Team/stage belong in the header; pure denials constrain the
                # guard. Neither is a bullet's result or a skill declaration.
                def clean_parenthesis(match):
                    clause = match[1]
                    rest = text[:match.start()] + text[match.end():]
                    if _PURE_DENIAL.search(clause) or (_TEST_DENIAL.fullmatch(clause) and not explicit):
                        return ''
                    if _already_visible(clause, [rest]):
                        return ''
                    return '，' + clause if _TEST_DENIAL.fullmatch(clause) else match[0]
                text = re.sub(r'[（(]([^（）()]+)[）)]', clean_parenthesis, text)
                parts = [c.strip() for c in _CLAUSE_BREAK.split(text) if c.strip()]
                kept = [c for c in parts if not _PURE_DENIAL.search(c)
                        and not (_TEST_DENIAL.fullmatch(c) and not explicit)
                        and c != item.get(role_field)
                        and c not in labels and not _TEAM.fullmatch(c)
                        and c not in {'离线', '课堂', '本地', '自拟', '人工判定'}]
                from app.services.fact_coverage import text_covered
                unique = []
                for clause in kept:
                    if len(set(re.findall(r'\d+', clause))) >= 2 and text_covered(clause, unique):
                        continue
                    unique.append(clause)
                kept = unique
                if kept != parts:
                    text = '，'.join(kept)
                return strip_absence(text)
            old_bullets = item.get(field) or []
            surviving = [(index, clean_body(text)) for index, text in enumerate(old_bullets) if isinstance(text, str)]
            surviving = [(index, text) for index, text in surviving if text]
            bullets = [text for _, text in surviving]
            prior_records = metadata.get('bullets', {}).get(identifier)
            if prior_records is not None:
                from app.services.resume_versions import text_hash
                aligned = []
                for index, text in surviving:
                    record = deepcopy(prior_records[index]) if index < len(prior_records) else {}
                    if text != old_bullets[index]:
                        record.pop('coverage_fact_ids', None)
                        record['text_hash'] = text_hash(text)
                    aligned.append(record)
                metadata['bullets'][identifier] = aligned
            item[field] = bullets
            if isinstance(item.get("description"), str):
                item["description"] = "\n".join(
                    cleaned for line in item["description"].splitlines() if (cleaned := strip_absence(line)))
            visible = "\n".join([str(item.get("name") or ""), str(item.get("company") or ""),
                                 str(item.get(role_field) or ""), *bullets])
            strippable = any(isinstance(text, str) and strip_stage_phrases(text) != text for text in bullets)
            if phase and not _phase_label(" ".join(str(item.get(key) or "") for key in ("name", "company", role_field))) \
                    and (strippable or not _phase_label(visible)):
                role = str(item.get(role_field) or "").strip()
                item[role_field] = f"{role} · {phase}".strip(" ·")
            authorized = None if bullet_indices is None else {
                index for index in bullet_indices.get(identifier, set()) if isinstance(index, int)}
            header = " ".join(str(item.get(key) or "") for key in ("name", "company", role_field))
            if _phase_label(header):
                # 标题行已表达阶段，bullet 里的「在课程原型中…」「以原型形式…」重复短语去掉
                bullets = [strip_stage_phrases(text) if isinstance(text, str) and (
                    authorized is None or index in authorized) else text for index, text in enumerate(bullets)]
                bullets = [text for text in bullets if not isinstance(text, str) or text.strip()]
                item[field] = bullets
            for index, text in enumerate(bullets):
                if not isinstance(text, str):
                    continue
                if authorized is not None and index not in authorized:
                    continue
                if contradicts_limit(text, quotes):
                    fallbacks.append({"item_id": identifier, "bullet_index": index, "reason": reason,
                                      "fact_ids": [fact["id"] for fact in facts if fact.get("id")][:4]})
            if restore_required:
                _integrate_required_limits(item, field, metadata, facts, constraints or {}, authorized, relocated_roles)
    return result, metadata, fallbacks


def _integrate_required_limits(item, field, metadata, facts, constraints, authorized, relocated_roles=()):
    """Restore source-backed qualifications inside the relevant action bullet."""
    from app.services.resume_versions import text_hash
    from app.services.resume_field_hygiene import role_body
    explicit = constraints.get('preserve_explicit_limits', False)
    bullets = item.get(field) or []
    records = deepcopy(metadata.get('bullets', {}).get(item['item_id'], []))
    records.extend({} for _ in range(max(0, len(bullets) - len(records))))
    extra = re.compile(r'测试环境|导师.{0,6}指导|(?:同学|同事).{0,12}(?:写|负责)|'
                       r'(?:登录|模块).{0,12}(?:同学|同事)|只给.{0,10}演示|'
                       r'退款.{0,12}主管.{0,6}审批|复杂投诉.{0,12}主管')
    for fact in facts:
        source = _live_quote(fact)
        clauses = [c.strip() for c in _CLAUSE_BREAK.split(source) if c.strip()]
        # A demo's audience and deployment location form one scope. Dropping
        # “实验室服务器” while retaining “只给班里演示” loses that scope.
        for i in range(len(clauses) - 1, 0, -1):
            if re.search(r'只给.{0,10}演示', clauses[i]) and re.search(r'部署|服务器', clauses[i - 1]):
                clauses[i - 1:i + 1] = ['，'.join(clauses[i - 1:i + 1])]
        for clause in clauses:
            relocated = fact['id'] in relocated_roles and bool(role_body(clause))
            if (_PURE_DENIAL.search(clause) or _TEAM.fullmatch(clause)
                    or re.fullmatch(r'项目(?:尚未|未)上线', clause)
                    or (_TEST_DENIAL.fullmatch(clause) and not explicit)):
                continue
            contribution = bool(_CONTRIBUTION_LIMIT.search(clause))
            metric_scope = bool(_METRIC_SCOPE.search(clause))
            demo_scope = bool(re.search(r'只给.{0,10}演示', clause))
            if not (relocated or _STATUS_LIMIT.search(clause) or extra.search(clause) or contribution or metric_scope):
                continue
            # A limit on the same quantitative claim must survive even without
            # an explicit retention instruction. Other limits constrain wording.
            numeric = bool(re.search(r'\d+\s*(?:ms|条|场|次|人|名|道|个|%|％)', source, re.I))
            if not explicit and not numeric and not contribution and not metric_scope and not demo_scope and not relocated:
                continue
            candidates = [i for i in range(len(bullets)) if authorized is None or i in authorized]
            if contribution:
                # Ownership is prose, not an identity. Prefer a non-metric
                # action and retain the boundary once within the same budget.
                non_metrics = [i for i in candidates if not re.search(r'完成数|正确数|耗时', bullets[i])]
                if non_metrics:
                    for i in candidates:
                        if i not in non_metrics:
                            bullets[i] = re.sub(r'[（(]([^（）()]+)[）)]',
                                lambda m: '' if _limit_key(m[1]) == _limit_key(clause) else m[0], bullets[i])
                    candidates = non_metrics
            if metric_scope:
                candidates = [i for i in candidates if re.search(r'\d', bullets[i])
                              and re.search(r'完成数|正确|准确|提高|提升|耗时|降低|增长|转化', bullets[i])]
            if not candidates:
                continue
            if not metric_scope and _already_visible(clause, bullets):
                continue
            def relevance(index):
                text = bullets[index]
                grams = {source[i:i + 2] for i in range(len(source) - 1)}
                overlap = sum(part in text for part in grams if re.search(r'[\w\u4e00-\u9fff]', part))
                if re.search(r'压测|测试环境', clause) and re.search(r'测试|索引|耗时|ms', text, re.I):
                    overlap += 20
                return overlap + (10 if fact['id'] in records[index].get('fact_ids', []) else 0)
            target = max(candidates, key=relevance)
            targets = [target]
            if metric_scope:
                # A separately extracted item-wide scope (e.g. 未上线) qualifies
                # every metric, not whichever bullet happened to be first.
                scoped_numbers = set(re.findall(r'\d+', clause))
                targets = [i for i in candidates if not scoped_numbers or scoped_numbers & set(re.findall(r'\d+', bullets[i]))]
            for target in targets:
                addition = clause
                if demo_scope:
                    addition = '，'.join(c for c in _CLAUSE_BREAK.split(clause)
                                        if c.strip() and not _already_visible(c.strip(), bullets))
                    if _limit_key(addition) == '只给班里演示':
                        # Add the missing exclusivity to the existing audience
                        # phrase instead of repeating the demo in another clause.
                        bullets[target] = re.sub(r'(?<!仅)(?<!只)面向(?:班级|班里|全班)演示',
                                                 lambda m: '仅' + m[0], bullets[target])
                if metric_scope:
                    markers = list(dict.fromkeys(_METRIC_SCOPE.findall(clause)))
                    missing = [value for value in markers if value not in bullets[target]]
                    if '本地' in missing and any('本地' in value for value in bullets):
                        missing.remove('本地')
                    if not missing:
                        continue
                    for marker in missing:
                        text = bullets[target]
                        if marker == '自拟':
                            text = re.sub(r'(\d+\s*道\s*)(?=问题|题)', r'\1自拟', text)
                        elif marker == '模拟':
                            text = re.sub(r'(\d+\s*个\s*)(?=任务)', r'\1模拟', text)
                            if '同一组' in clause and '同一组' not in text:
                                text = re.sub(r'(\d+\s*个\s*模拟任务)', r'同一组\1', text, count=1)
                        elif marker == '人工判定':
                            text = text.replace('正确', '人工判定正确', 1)
                        elif marker == '课堂' and '离线测试' in text:
                            text = text.replace('离线测试', '课堂离线测试', 1)
                        else:
                            text = {'课堂': '课堂测试中，', '离线': '离线测试中，', '本地': '在本地测试中，'}[marker] + text
                        bullets[target] = text
                elif not _already_visible(addition, [bullets[target]]):
                    from app.services.fact_coverage import text_covered
                    if text_covered(addition, [bullets[target]]):
                        continue
                    bullets[target] = bullets[target].rstrip('。；;，, ') + '，' + addition.rstrip('。；;，, ')
                record = records[target]
                record['fact_ids'] = list(dict.fromkeys([*record.get('fact_ids', []), fact['id']]))
                record['text_hash'] = text_hash(bullets[target])
                record.pop('coverage_fact_ids', None)
                metadata.setdefault('bullets', {})[item['item_id']] = records
    for index, (text, record) in enumerate(zip(bullets, records)):
        if authorized is not None and index not in authorized:
            continue
        if record.get('text_hash') != text_hash(text):
            record.pop('coverage_fact_ids', None)
        record['text_hash'] = text_hash(text)
    if any(record.get('fact_ids') for record in records):
        metadata.setdefault('bullets', {})[item['item_id']] = records
