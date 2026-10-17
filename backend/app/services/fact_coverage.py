"""Coverage requires a live citation plus entailment, including subsumed facts."""
import re
from collections import Counter

from app.schemas.facts import FACT_SECTIONS
from app.services.candidate_language import constraint_only, resume_bullet
from app.services.fact_guard import duplicate_key, lexical_fact_errors, normalize_text, strip_absence
from app.services.resume_facts import active_facts_for_writer
from app.services.resume_versions import text_hash


def numeric_actions_subsumed(text: str, covering: str) -> bool:
    """A deliberately narrow rule for reordered article-layout/draft counts.

    Bind each number to its action/object; shared numbers alone prove nothing.
    Unknown wording/limits must also survive in the more complete sentence.
    """
    def signature(value):
        value = normalize_text(value)
        claims = set()
        patterns = (
            ('排版', r'(?:完成)?(\d+)篇(?:公众号文章|公众号推文|推文|文章)排版'),
            ('排版', r'排版(?:过)?(?:公众号文章|公众号推文|推文|文章)?(\d+)篇(?:公众号文章|公众号推文|推文|文章)?'),
            ('撰写初稿', r'其中(\d+)篇(?:的)?初稿(?:是我写的|由本人撰写)'),
            ('撰写初稿', r'(?:撰写|编写)(?:推文|文章)?初稿(\d+)篇'),
            ('撰写初稿', r'(?:撰写|编写)(\d+)篇(?:推文|文章)?初稿'),
        )
        for action, pattern in patterns:
            def consume(match):
                claims.add((action, match[1]))
                return ''
            value = re.sub(pattern, consume, value)
        value = re.sub(r'参与公众号排版|[，,。；;、\s]', '', value)
        return claims, value
    if not extract_numeric_set(text) or extract_numeric_set(text) != extract_numeric_set(covering):
        return False
    claims, extra = signature(text)
    other, kept = signature(covering)
    return len(claims) >= 2 and claims == other and (not extra or extra in kept)


def extract_numeric_set(text):
    from app.services.fact_guard import extract_numbers
    return extract_numbers(text)


_LATENCY_CHANGE = re.compile(
    r'(?P<object>慢查询)?平均耗时(?:由|从)(?P<before>约?\d+(?:\.\d+)?(?:ms|毫秒))'
    r'(?:降到|降至|降低到|降低至)(?P<after>约?\d+(?:\.\d+)?(?:ms|毫秒))')


def latency_metric_covered(text: str, covering: str) -> bool:
    """Match a complete latency fact to its action, preserving ordered values.

    Only a bare metric clause is subsumed; other actions/qualifications must
    still be accounted for independently. Equal numbers on another object or
    in a plan/denial are not the same observed result.
    """
    wanted = _LATENCY_CHANGE.fullmatch(normalize_text(text).strip('。；;'))
    if not wanted:
        return False
    value = normalize_text(covering)
    for match in _LATENCY_CHANGE.finditer(value):
        context = value[:match.start()].rsplit('；', 1)[-1].rsplit(';', 1)[-1]
        if re.search(r'计划|准备|打算|未|没|不(?:曾|能|会)?', context):
            continue
        subject = match['object'] or ('慢查询' if '慢查询' in context else '')
        if wanted['object'] and wanted['object'] != subject:
            continue
        if all(wanted[key].replace('毫秒', 'ms') == match[key].replace('毫秒', 'ms')
               for key in ('before', 'after')):
            return True
    return False


def text_covered(text: str, bullets: list[str]) -> bool:
    from app.agents.fact_extractor import _clause_covered
    def normalized(value):
        value = duplicate_key(resume_bullet(value))
        value = re.sub(r'^负责(?!人)', '', value)
        value = value.replace('对答案做人工判定', '答案人工判定')
        value = value.replace('由基础版本的', '由').replace('从基础版本的', '从')
        value = re.sub(r"整理([^，,。；;]{1,18})并分类", r"分类整理\1", value)
        value = value.replace("公众号文章", "文章")
        value = re.sub(r"(?:完成)?(\d+)篇文章排版", r"排版\1篇文章", value)
        value = re.sub(r"其中(\d+)篇的?初稿(?:是我写的|由本人撰写)", r"撰写\1篇初稿", value)
        # Same object, baseline and outcome with only grammatical differences.
        # Keep the object and every number; shared quantities alone are not proof.
        value = re.sub(r'(?:由|从)(\d+)(?:个|道)?(?:提高到|提升至|提升到|提高至)(\d+)(?:个|道)?',
                       r'从\1提高到\2', value)
        return re.sub(r"[，,。；;]|(?<=[做用写查改])了", "", value)
    clauses = [normalized(part) for part in re.split(r"[，,。；;\n、]", text) if normalize_text(part)]
    quotes = [normalized(value) for value in bullets if value]
    if '基础版本' in text and not any('基础版本' in value for value in bullets):
        return False
    # _clause_covered's reverse-substring rule is useful during extraction but
    # cannot prove a whole responsibility survived a shorter written fragment.
    return bool(clauses) and all(any(
        (latency_metric_covered(clause, quote) if _LATENCY_CHANGE.fullmatch(clause) else
         ((clause in quote if len(extract_numeric_set(clause)) >= 2 else _clause_covered(clause, [quote]))
          and not (quote in clause and quote != clause) or _general_action_covered(clause, quote)))
        and not lexical_fact_errors(clause, quote)
        for quote in quotes) for clause in clauses)


def _general_action_covered(general: str, specific: str) -> bool:
    """Only broad action/object claims can disappear into a more specific claim.

    Quantities, tools, purposes and extra actions in the general claim are not
    discarded. Those require a separate citation/semantic entailment check.
    """
    patterns = (
        (r"(?:协助)?(?:完成|制作)?公众号(?:文章)?排版", r"公众号|文章", r"排版"),
        (r"(?:撰写|编写)(?:推文|公众号文章)(?:初稿)?", r"(?:推文|文章|初稿)", r"撰写|编写|写的"),
        (r"拍摄(?:店里的?|店内的?)?短视频(?:素材)?", r"短视频", r"拍摄"),
        (r"(?:协助(?:店长)?(?:制作)?|完成|制作)(?:促销)?海报", r"海报", r"制作|排版|完成|设计"),
    )
    return any(re.fullmatch(base, general) and re.search(obj, specific) and re.search(verb, specific)
               and not re.search(r"(?:由|被)(?:店长|部长|同事|他人).{0,8}(?:" + verb + ")", specific)
               for base, obj, verb in patterns)


async def cite_entailed_facts(data: dict, meta: dict, collected: dict, llm, *, item_ids=()) -> None:
    """Reverse-check what each cited bullet actually conveys, never trust overcitation."""
    from app.services import fact_guard
    source = active_facts_for_writer(collected)
    allowed, pairs, pending = set(item_ids), [], {}
    for source_section in FACT_SECTIONS:
        section = "work_experience" if source_section == "internship" else source_section
        for original in source.get(source_section) or []:
            item_id = original["item_id"]
            if item_id not in allowed:
                continue
            item = next((row for row in data.get(section) or [] if row.get("item_id") == item_id), {})
            body = item.get("polished_bullets" if section == "projects" else "bullets") or []
            facts = {f["id"]: f for f in original.get("facts") or []}
            for value, record in zip(body, meta.get("bullets", {}).get(item_id, [])):
                if record.get("text_hash") != text_hash(value) or not record.get("fact_ids") or not set(record["fact_ids"]) <= facts.keys():
                    continue
                previous = set(record.get("coverage_fact_ids") or []) & facts.keys()
                record["coverage_fact_ids"] = []
                for fid, fact in facts.items():
                    text = resume_bullet(strip_absence(fact["text"]))
                    if fact.get("field") or not text or constraint_only(fact.get("source_quote") or fact["text"]):
                        continue
                    if fid in previous or text_covered(text, [value]):
                        record["coverage_fact_ids"].append(fid)
                    elif fid in record["fact_ids"] and not (extract_numeric_set(text) - extract_numeric_set(value)):
                        # 每条引用独立反向核验动作/对象/状态；字面重合不能证明或否定覆盖。
                        identifier = f"coverage{len(pairs)}"
                        pairs.append({"id": identifier, "text": text, "source_quotes": [value]})
                        pending[identifier] = (record, fid)
    decisions = await fact_guard.verify_semantics(pairs, llm, run_name="coverage_entailment") if pairs else {}
    for identifier, (record, fid) in pending.items():
        if decisions.get(identifier, {}).get("verdict") == "pass":
            record["coverage_fact_ids"].append(fid)


def ensure_fact_coverage(data: dict, meta: dict, collected: dict, *, repair_ids=(), withheld=None, caps=None,
                         repairs=None) -> dict:
    """Restore uncovered body facts, or record an explicit per-fact omission.

    Repairs must already have passed the writer/guard. An explicit count/backup
    choice still wins. This audit never manufactures a raw-text fallback.
    """
    repair_ids, withheld, caps = set(repair_ids), withheld or {}, caps or {}
    prior_omissions = {row["fact_id"]: row["reason"] for row in (meta.get("fact_coverage") or {}).get("facts", [])
                       if row.get("status") == "omitted" and row.get("reason")}
    source = active_facts_for_writer(collected)
    id_counts = Counter(fact["id"] for section in FACT_SECTIONS for item in source.get(section) or []
                        for fact in item.get("facts") or [])
    rows, restored = [], 0
    visible_sections = {row["kind"] for row in data["sections"]} if data.get("sections") is not None else None
    for source_section in FACT_SECTIONS:
        section = "work_experience" if source_section == "internship" else source_section
        for original in source.get(source_section) or []:
            item_id = original["item_id"]
            item = next((row for row in data.get(section) or [] if row.get("item_id") == item_id), None)
            field = "polished_bullets" if section == "projects" else "bullets"
            hidden = item is None or item.get("hidden") or (visible_sections is not None and section not in visible_sections)
            facts = original.get("facts") or []
            # The writer orders repairs by selected JD evidence. Fill the
            # bounded slots in that order, not arbitrary extraction order.
            priority = {fid: index for index, fid in enumerate(repairs or {})}
            ordered = sorted(facts, key=lambda fact: priority.get(fact['id'], len(priority))) if item_id in repair_ids else facts
            for fact in ordered:
                if constraint_only(fact.get("source_quote") or fact["text"]):
                    continue
                text = resume_bullet(strip_absence(fact["text"]), name=original.get("name") or original.get("company") or "",
                                     role=(item or {}).get("role") or (item or {}).get("title") or "")
                fact_field = fact.get("field")
                body = list((item or {}).get(field) or [])
                displayed_body = body or [str((item or {}).get("description") or "")]
                headers = [str((item or {}).get(key) or "") for key in
                           ("name", "company", "school", "role", "title", "start_date", "end_date", "major", "degree", "summary", "pr", "level", "date", "highlights")]
                if section == "education" or fact_field:
                    covered = not hidden and text_covered(text or fact["text"], headers + displayed_body)
                else:
                    records = meta.get("bullets", {}).get(item_id, [])
                    own_ids = {row["id"] for row in facts}
                    referenced_body = [value for value, record in zip(body, records)
                                       if record.get("text_hash") == text_hash(value) and record.get("fact_ids")
                                       and set(record["fact_ids"]) <= own_ids]
                    cited_body = [value for value, record in zip(body, records)
                                  if record.get("text_hash") == text_hash(value)
                                  and fact["id"] in record.get("fact_ids", [])]
                    entailed = any(record.get("text_hash") == text_hash(value)
                                   and fact["id"] in record.get("coverage_fact_ids", [])
                                   for value, record in zip(body, records))
                    # Legacy drafts have no citations. A precise literal match
                    # remains usable; new drafts carry validated coverage IDs.
                    covered = not hidden and (entailed or text_covered(text, referenced_body or cited_body
                                                                      or (displayed_body if not records else [])))
                reason = ""
                # resume_bullet removes header echoes. Test the original
                # source-backed identity before treating an empty body as omitted.
                if not hidden and text_covered(fact['text'], headers):
                    covered = True
                if not covered:
                    if hidden:
                        reason = withheld.get(item_id) or "经历或栏目设为备用，不在本版展示"
                    elif not text:
                        reason = "自评、提问或未发生事项，仅保留在事实记录"
                    elif id_counts[fact["id"]] > 1:
                        reason = "事实标识冲突，待核对后展示"
                    elif text_covered(text, headers):
                        covered = True
                    elif item_id in withheld:
                        reason = withheld[item_id]
                    elif item_id in caps and len(body) >= caps[item_id]:
                        reason = "本版条数上限，未覆盖的职责保留为备用"
                    elif (not fact_field and section != "education" and item_id in repair_ids
                          and fact["id"] in (repairs or {})):
                        # A compound fact can cover several existing fragments.
                        # Keep the complete literal rewrite once, with all IDs.
                        replacement = (repairs or {}).get(fact["id"], {})
                        text = replacement.get("text", text)
                        records = meta.setdefault("bullets", {}).setdefault(item_id, [])
                        records.extend({} for _ in range(max(0, len(body) - len(records))))
                        subsumed = [i for i, value in enumerate(body) if text_covered(value, [text])]
                        refs = list(dict.fromkeys([fact["id"], *(fid for i in subsumed for fid in records[i].get("fact_ids", []))]))
                        body = [value for i, value in enumerate(body) if i not in subsumed]
                        records = [record for i, record in enumerate(records) if i not in subsumed]
                        body.append(text)
                        records.append({**replacement, "fact_ids": refs, "req_ids": [], "flags": [], "needs_metric": False,
                                        "metric_question": "", "text_hash": text_hash(text)})
                        item[field], meta["bullets"][item_id] = body, records
                        covered, restored = True, restored + 1
                    else:
                        reason = prior_omissions.get(fact["id"]) or "本次编辑范围或篇幅取舍，保留为备用事实"
                rows.append({"fact_id": fact["id"], "item_id": item_id,
                             "text": fact["text"],
                             "status": "covered" if covered else "omitted", **({"reason": reason} if reason else {})})
    covered = sum(row["status"] == "covered" for row in rows)
    report = {"total": len(rows), "covered": covered, "coverage_rate": covered / len(rows) if rows else 1.0,
              "restored": restored, "facts": rows}
    meta["fact_coverage"] = report
    return report


def coverage_notice(report: dict) -> str:
    omitted = [row for row in report.get("facts", []) if row["status"] == "omitted" and not constraint_only(row.get("text", ""))]
    return f"另有 {len(omitted)} 条信息作为备用未放进这一版（可在右侧『核对』查看）。" if omitted else ""
