"""Read-only professional review of current or supplied resume materials."""

import json
import logging

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from app.agents.career_prompt import career_messages
from app.agents.public_reply import stream_public_reply
from app.config import get_settings
from app.services.resume_review import review_resume

logger = logging.getLogger(__name__)
REVIEW_CONTRACT = """检查用户这次提供的简历；若本轮只是说检查，则检查当前简历数据。
当前数据为空且本轮没有简历时，请用户贴简历，不凑问题。岗位信息和个人材料分别核对。
输出最多 5 项主要问题，每项含「位置/原句」「问题与依据」「具体修改或一个关键追问」。
注明本次可核对和未核对的范围。当前是检查任务，不生成新的简历正文、可复制 bullet 或填空范例。
修改动作说明应保留、删除、核对或补问哪些原句；缺本人动作时只追问，不能在范例里先固定新的录入/汇总等动作再留数字空格。需要成稿时可在本人补齐事实后交给包装经历任务。
检查不能修改输入资料、候选人事实或草稿，不声称建议已被采用。"""


async def run_resume_review(
    state: dict, user_material: str, llm, *, return_message: bool = False
) -> str | AIMessage:
    data = state.get("resume_data") or {}
    facts = state.get("collected_info") or {}
    payload = {
        "review_request_or_resume_material": user_material,
        "current_resume_data": data,
        "candidate_facts": facts,
        "recruiter_jd_text": state.get("jd_text") or "",
        "recruiter_jd_info": state.get("jd_info") or {},
        "deterministic_checks_on_current_resume": review_resume(
            data, state.get("jd_info")
        )
        if data
        else [],
    }
    try:
        # Keep review's original deterministic temperature, while using the
        # public model endpoint and a streaming copy rather than the internal
        # structured-output client. Do not mutate the shared chat model.
        review_llm = (
            llm.model_copy(update={"temperature": 0, "streaming": True})
            if isinstance(llm, ChatOpenAI)
            else llm
        )
        response = await stream_public_reply(
            review_llm,
            career_messages(
                "review_resume",
                json.dumps(payload, ensure_ascii=False),
                REVIEW_CONTRACT,
            ),
            ask_state=state,
            timeout=get_settings().LLM_REVIEW_TIMEOUT_SECONDS,
            suffix=(
                "\n\n本次为文字与内容检查；导出文件排版、实际招聘系统解析尚未验证。修改建议尚未写入简历。"
            ),
        )
        return response if return_message else response.content
    except Exception as exc:
        logger.warning("Career review unavailable: %s", type(exc).__name__)
        if data:
            reply = "专业内容检查暂时不可用，先列出基础核对项：\n" + "\n".join(
                review_resume(data, state.get("jd_info"))
            )
        else:
            reply = "专业内容检查暂时不可用，请稍后重试；已有材料未被修改。"
        return AIMessage(content=reply) if return_message else reply
