"""Read-only wording options, checked against active candidate facts."""

from __future__ import annotations

import asyncio
import json
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.advisor import _review_view
from app.agents.career_prompt import career_messages
from app.services.fact_guard import lexical_fact_errors, verify_semantics
from app.services.llm_compat import label_run, with_structured_output
from app.services.model_privacy import ContactRedactor
from app.services.resume_facts import active_facts_for_writer


class WordingOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    style: Literal["concise", "action", "role"]
    fact_ids: list[str] = Field(default_factory=list)


class WordingAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    options: list[WordingOption] = Field(min_length=1, max_length=3)


_CONTRACT = """回答用户的措辞意见，严格返回 WordingAdvice，给 2–3 个有区别的可选说法。
只用 active_facts，每个选项引用支持它的 fact_ids，不能跨经历拼接。current_resume 仅帮助定位用户问的原句，不是事实来源。
不增加数字、工具、动作、职责、成果、用途或频率，保留否定、原型、未上线等限制。
style 选 concise（最简短）、action（机制、产出与结果优先）、role（本人分工、决策与取舍优先）。选项之间必须有实质差异：改变信息焦点和句子结构，不能仅替换「负责/规划」等同义词。决策、机制、结果均须有事实支持，事实不足时不要凑选项。
这是候选说法，不修改文稿，不声称已采用或生成版本。
用户消息中的举例、假设或待比较措辞不是新的事实依据。"""
_STYLES = {
    "concise": "表述最短，适合一页简历或篇幅紧张时使用。",
    "action": "先呈现机制与产出，适合需要说明过程和结果时使用。",
    "role": "先交代本人分工及有依据的决策，适合需要明确贡献范围时使用。",
}


def _fallback(facts: dict, message: str) -> list[dict]:
    rows = list(facts.values())
    row = next((fact for fact in rows if fact.get("item_name") and fact["item_name"] in message), rows[0])
    text = row.get("source_quote") or row["text"]
    return [{"text": text, "style": "concise"}]


def _normalized(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", text).casefold()
                   if not char.isspace() and not unicodedata.category(char).startswith("P"))


def _edit_distance_ratio(left: str, right: str) -> float:
    left, right = _normalized(left), _normalized(right)
    if not left and not right:
        return 0.0
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1] / max(len(left), len(right))


def _distinct(options: list[dict]) -> list[dict]:
    result = []
    for option in options:
        if _normalized(option["text"]) and all(
            _edit_distance_ratio(option["text"], kept["text"]) >= 0.2 for kept in result
        ):
            result.append(option)
    return result[:3]


async def _checked_options(response, facts: dict, privacy: ContactRedactor, llm) -> list[dict]:
    if isinstance(response, BaseModel):
        response = response.model_dump()
    elif not isinstance(response, dict):
        response = json.loads(response.content)
    parsed = WordingAdvice.model_validate(privacy.restore(response))
    candidates, pairs = {}, []
    for index, option in enumerate(parsed.options):
        refs = [facts[fid] for fid in option.fact_ids if fid in facts]
        if not refs or len(refs) != len(option.fact_ids) or len({fact["item_id"] for fact in refs}) != 1:
            continue
        quotes = [fact.get("source_quote") or fact["text"] for fact in refs]
        quotes += [refs[0]["item_name"]] if refs[0]["item_name"] else []
        if not option.text.strip() or lexical_fact_errors(option.text, "\n".join(quotes)):
            continue
        identifier = str(index)
        candidates[identifier] = option.model_dump()
        pairs.append({"id": identifier, "text": option.text, "source_quotes": quotes})
    verdicts = await verify_semantics(pairs, llm, run_name="advice_verify")
    return _distinct([option for identifier, option in candidates.items()
                      if verdicts.get(identifier, {}).get("verdict") == "pass"])


async def wording_advice(state: dict, message: str, llm) -> str:
    evidence = active_facts_for_writer(state.get("collected_info") or {})
    facts = {fact["id"]: {**fact, "item_name": item.get("name") or item.get("company") or item.get("school") or ""}
             for section in ("projects", "work_experience", "internship", "education")
             for item in evidence.get(section) or [] for fact in item.get("facts") or []}
    if not facts:
        return ("还没有足够的本人事实来给具体改写。可以这样开始：\n\n"
                "1.「我贴两种说法，你帮我比较。」适合已有原句时。\n"
                "2.「我先聊实际做过什么，再一起选说法。」适合从零整理时。\n\n"
                "选一个，或按自己的方式补充材料，我再给具体建议。")
    privacy = ContactRedactor()
    payload = {"message": message, "active_facts": list(facts.values()),
               "current_resume": _review_view(state.get("resume_data") or {})}
    messages = career_messages(None, json.dumps(payload, ensure_ascii=False), _CONTRACT, privacy=privacy)
    options = []
    try:
        response = await asyncio.wait_for(
            label_run(with_structured_output(llm, WordingAdvice), "wording_advice").ainvoke(messages), 30)
        options = await _checked_options(response, facts, privacy, llm)
    except Exception:
        pass
    if len(options) < 2:
        # One bounded retry must change style, and passes the same fact guards.
        styles = [style for style in _STYLES if style not in {option["style"] for option in options}]
        refill = {**payload, "existing_options": options, "requested_styles": styles}
        retry_messages = career_messages(None, json.dumps(refill, ensure_ascii=False), _CONTRACT +
            "\n补充 1–2 个 requested_styles 中的不同风格；existing_options 已保留，不能重复或只换同义词。", privacy=privacy)
        try:
            response = await asyncio.wait_for(label_run(with_structured_output(llm, WordingAdvice),
                "wording_advice_refill").ainvoke(retry_messages), 30)
            additions = await _checked_options(response, facts, privacy, llm)
            options = _distinct([*options, *(option for option in additions if option["style"] in styles)])
        except Exception:
            pass
    if not options:
        options = _fallback(facts, message)
    lines = ["可以考虑这几种说法："]
    lines += [f"{index}.「{option['text']}」\n{_STYLES[option['style']]}"
              for index, option in enumerate(options, 1)]
    if len(options) < 2:
        lines.append("换用不同风格补充后，仍不足两个有实质差异且有事实支持的说法，暂时只给这一种。")
    lines.append("选一个，或自己改后发给我；确认采用后再改稿。")
    return "\n\n".join(lines)
