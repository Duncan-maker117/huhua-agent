"""对话接线：只向 jd_info 合并参考资料，不触碰 collected_info/facts。"""

from __future__ import annotations

import copy
from functools import wraps
import json

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from . import sample_jobs
from . import background


class SearchCompany(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=80,
        description="需要了解背景的目标公司名称，不含个人信息",
    )


COMPANY_CONTRACT = (
    "需要目标公司背景时可调用 search_company，每轮最多一次，只传公司名。"
    "查询结果仅供岗位参考，不能写入候选人的技能、事实或经历；查不到如实说明。"
    "公司信息的简短说明由工具附上来源链接，不得猜测缺失字段。"
)


async def enrich_direction(state, llm, *, graph=None, session=None):
    from app.services.resume_strategy import has_job_description

    info = background.expire_info(state.get("jd_info"))
    direction = info.get("role_direction")
    if not direction or state.get("jd_text") or has_job_description(info):
        return {}
    profile = info.get("role_profile") or {}
    if (
        profile.get("source") == "market_sample"
        and profile.get("direction") == direction
    ):
        return {}
    try:
        cached = background.cached_sample(direction)
    except Exception:
        cached = None
    if cached and cached.get("status") == "ok":
        info["sample_attempted_direction"] = direction
        info = background.completed_info(info, cached)
    else:
        # Failed/pending attempts never bill again; a newly available cache may still recover them.
        if info.get("sample_attempted_direction") == direction:
            return {"jd_info": info} if info != state.get("jd_info") else {}
        info["sample_attempted_direction"] = direction
        from .service import session_id
        session = session or session_id()
        if session == "standalone":
            # A standalone node has no session/checkpoint to update in the background.
            info["role_profile"] = {**profile, "status": "failed", "message": background.FAILED}
        else:
            graph = graph or background.current_graph.get()
            if graph is None:
                from app.agents.resume_graph import get_graph
                graph = get_graph(llm)
            info["role_profile"] = background.schedule(graph, session, direction, llm, profile, sample_jobs)
    return {"jd_info": info}


def market_context(state):
    profile = (state.get("jd_info") or {}).get("role_profile") or {}
    if profile.get("source") != "market_sample" or profile.get("status") in {"pending", "failed"}:
        return ""
    labels = [
        item["text"]
        for field in ("responsibilities", "skills", "bonuses", "requirements")
        for item in profile.get(field, [])
        if isinstance(item, dict)
        and item.get("text")
        and isinstance(item.get("count"), int)
    ]
    return (
        f"市场上的岗位通常看重：{'、'.join(labels[:10])}（来源：{profile.get('sample_count', 0)} 条真实岗位）。"
        + (f"仅基于 {profile.get('sample_count', 0)} 条岗位，样本较少。" if profile.get("low_sample") else "")
        + profile.get("weighting_note", "")
        + "这只是抽样，不代表全部市场或用户已具备的技能；仅用于确定追问方向，不得变成简历事实。\n"
        + json.dumps({"market_sources": profile.get("sources", [])}, ensure_ascii=False)
    )


async def company_tool(args, state):
    from app.services.chat_turns import current_turn

    turn = current_turn.get()
    if turn and getattr(turn, "intel_company_used", False):
        return {"status": "limited", "message": "本轮已查询过公司背景。"}
    if turn:
        turn.intel_company_used = True
    try:
        parsed = (
            SearchCompany.model_validate_json(args)
            if isinstance(args, str)
            else SearchCompany.model_validate(args)
        )
    except ValueError:
        return {"status": "rejected", "message": "公司名称无效，暂未查询。"}
    # llm 由公开回复入口显式传入，不向搜索服务发送对话或简历。
    return parsed


def company_reply(result):
    if result.get("status") != "ok":
        return result.get("message", "暂未查到可核对的公司资料。")
    company = result["company"]
    lines = [f"{company['name']}："]
    for field, label in (
        ("industry", "行业"),
        ("description", "简介"),
        ("official_site", "官网"),
    ):
        value = company.get(field)
        lines.append(
            f"{label}：{value['text']}（[{value.get('source_type', '')}来源]({value['url']})）"
            if value
            else f"{label}：暂未查到。"
        )
    return "\n".join(lines)


def intel_result(function):
    """将公开回复携带的公司卡及本轮岗位卡纳入图的显式更新。"""

    @wraps(function)
    async def wrapped(state, *args, **kwargs):
        result = await function(state, *args, **kwargs)
        info = copy.deepcopy(result.get("jd_info", state.get("jd_info")) or {})
        changed = False
        if result.get("jd_text"):
            for source in state.get("web_sources") or []:
                card = source.get("job_card")
                if (
                    card
                    and source.get("kind") == "job_page"
                    and card.get("url") in result["jd_text"]
                    and source.get("content")
                    and source["content"] in result["jd_text"]
                ):
                    info.update(
                        source="job_url",
                        url=card["url"],
                        fetched_at=card["fetched_at"],
                        job_card=card,
                    )
                    changed = True
                    from langchain_core.messages import AIMessage

                    # 节点回复已经告知「读岗位」时不再补一句同义回执。
                    if not any(
                        m.additional_kwargs.get("intel_read_receipt")
                        or "「读岗位」" in str(getattr(m, "content", ""))
                        for m in result.get("messages") or []
                    ):
                        result = {
                            **result,
                            "messages": [
                                AIMessage(
                                    content=f"已读到岗位：{card.get('job_title') or '招聘岗位'}。岗位要求与原链接已放到右侧「读岗位」。",
                                    additional_kwargs={"intel_read_receipt": True},
                                ),
                                *(result.get("messages") or []),
                            ],
                        }
                    break
        for message in result.get("messages") or []:
            company = message.additional_kwargs.get("intel_company")
            if company:
                info["company"] = company
                changed = True
        if changed:
            result = {**result, "jd_info": info}
            if result.get("jd_text"):
                from app.services.intake import intake_update

                result.update(intake_update({**state, **result}))
        return result

    return wrapped


async def save_notice(graph, session, user_text, notice):
    from uuid import uuid4
    from langchain_core.messages import AIMessage
    from app.agents.resume_graph import _init_state

    config = {"configurable": {"thread_id": session}}
    snapshot = await graph.aget_state(config)
    existing = (snapshot.values if snapshot else {}) or {}
    # 失败回复也持久化，用户可继续贴正文；原有 JD 和事实不变。
    update = {} if existing else _init_state()
    update.update(
        messages=[
            HumanMessage(
                content=user_text,
                id=str(uuid4()),
                additional_kwargs={"career_material_type": "reference"},
            ),
            AIMessage(content=notice, id=str(uuid4())),
        ],
        requested_task="auto",
    )
    await graph.aupdate_state(config, update, as_node="dialogue")
