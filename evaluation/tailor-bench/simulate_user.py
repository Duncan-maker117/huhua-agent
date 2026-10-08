"""A reproducible user who can disclose only authored truth strings.

There is deliberately no generative model here. Topic matches select indices;
the actual answer is copied verbatim. Control replies contain no resume facts.
"""
from __future__ import annotations

import re


def answer_question(case: dict, assistant: str, disclosed: set[int]) -> dict | None:
    lines = [line.strip() for line in assistant.splitlines() if line.strip()]
    questions = [line for line in lines if re.search(r"[?？]|请(?:补充|提供|介绍|告诉)|想了解|可以说说", line)]
    if not questions:
        return None
    query = "\n".join(questions)
    # Answer explicit generation offers without quietly forcing a draft on
    # otherwise stalled collection. This branch is logged in the transcript.
    if (re.search(r"(?:是否|要不要|需要我|要我|可以|现在).{0,16}(?:生成|成稿|整理.*简历)", query)
            and not re.search(r"(?:不能|无法|不可|尚未|还没|没法|不够|不适合).{0,8}(?:生成|成稿|整理.*简历)|不(?:生成|成稿)", query)):
        return {"text": "请按已经提供的真实资料生成简历，缺失信息不要补写。",
                "fact_indices": [], "reason": "explicit_generation_offer"}
    chosen: list[int] = []
    matches = []
    for order, topic in enumerate(case.get("simulator_topics", [])):
        score = sum(keyword.casefold() in query.casefold() for keyword in topic["keywords"])
        if score:
            matches.append((-score, order, topic))
    for _, _, topic in sorted(matches, key=lambda match: match[:2]):
        for index in topic["fact_indices"]:
            if index not in disclosed and index not in chosen:
                chosen.append(index)
                if len(chosen) == 2:
                    break
        if len(chosen) == 2:
            break
    if not chosen:
        return {"text": "这方面我没有更多可以确认的信息，请只使用我已经提供的内容。",
                "fact_indices": [], "reason": "no_undisclosed_matching_truth"}
    return {"text": "\n".join(case["truth_facts"][index] for index in chosen),
            "fact_indices": chosen, "reason": "verbatim_topic_match"}


def validate_case(case: dict) -> None:
    required = {"id", "role_family", "jd_text", "opening_turns", "truth_facts",
                "forbidden", "must_cover", "edit_instructions"}
    if required - case.keys():
        raise ValueError("Missing case fields")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", case["id"]):
        raise ValueError("Unsafe case ID")
    for field in ("opening_turns", "truth_facts", "must_cover", "edit_instructions"):
        if not isinstance(case[field], list) or not case[field] or not all(
                isinstance(value, str) and value.strip() for value in case[field]):
            raise ValueError(f"Invalid {field}")
    if len(case["edit_instructions"]) != 2:
        raise ValueError("PR0 cases require two edit instructions")
    for topic in case.get("simulator_topics", []):
        if not topic.get("keywords") or not topic.get("fact_indices"):
            raise ValueError("Empty simulator topic")
        if any(type(index) is not int or not 0 <= index < len(case["truth_facts"])
               for index in topic["fact_indices"]):
            raise ValueError("Invalid simulator fact index")
    for requirement in case.get("requirements", []):
        if any(type(index) is not int or not 0 <= index < len(case["truth_facts"])
               for index in requirement.get("evidence_fact_indices", [])):
            raise ValueError("Invalid requirement fact index")
    opening_indices = case.get("opening_fact_indices", [[] for _ in case["opening_turns"]])
    if len(opening_indices) != len(case["opening_turns"]) or any(
            type(index) is not int or not 0 <= index < len(case["truth_facts"])
            for indices in opening_indices for index in indices):
        raise ValueError("Invalid opening fact indices")
