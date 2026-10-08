"""Bounded, reproducible comparison on synthetic cases; no app/database writes.

Default only validates fixtures. --live explicitly invokes the configured model,
at most 16 requests, no retries, two in flight, 40 seconds / 1400 tokens per call.
Results do not prove job outcomes or statistically significant superiority.
"""

import argparse
import asyncio
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from app.agents.career_prompt import PROMPT_VERSION, career_system  # noqa: E402
from app.agents.career_tasks import REVIEW_CONTRACT  # noqa: E402
from app.agents.prompts import JD_DECODER_CONTRACT  # noqa: E402

FIXTURES = ROOT / "evaluation" / "career-v1" / "cases.json"
GENERIC = "你是一位通用 AI 助手。根据用户提供的信息完成任务，准确、清晰，不编造信息。"
CONTRACTS = {
    "decode_jd": JD_DECODER_CONTRACT,
    "rewrite_experience": "完成用户的经历包装要求：有足够材料时给一条可复制的简历建议，有缺项时提出最关键的追问。",
    "review_resume": REVIEW_CONTRACT,
}


async def compare(cases, output: Path, variant: str):
    from app.config import get_settings
    from app.services.llm_compat import _is_deepseek

    settings = get_settings()
    if not settings.LLM_API_KEY:
        raise SystemExit("模型未配置；未执行真实对照。")
    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=0,
        streaming=False,
        max_tokens=1400,
        max_retries=0,
        timeout=35,
    )
    if _is_deepseek(llm):
        llm = llm.model_copy(update={"extra_body": {"thinking": {"type": "disabled"}}})
    semaphore = asyncio.Semaphore(2)
    rng = random.Random(20261002)
    key = {}
    records = []
    for case in cases:
        names = ["generic", "career"] if variant == "both" else ["career"]
        rng.shuffle(names)
        key[case["id"]] = dict(zip(("A", "B"), names))
        records.append({**case, "outputs": {}})
    metadata = {
        "date": datetime.now(timezone.utc).isoformat(),
        "model": settings.LLM_MODEL,
        "prompt_version": PROMPT_VERSION,
        "temperature": 0,
        "max_tokens": 1400,
        "max_requests": len(cases) * (2 if variant == "both" else 1),
        "variant": variant,
        "scope": f"{len(cases)} 个虚构风险案例，每个版本一次；未测用户投递结果或完整网站流程。",
    }
    output.mkdir(parents=True, exist_ok=True)

    def save():
        (output / "blind-outputs.json").write_text(
            json.dumps(
                {"metadata": metadata, "cases": records}, ensure_ascii=False, indent=2
            )
        )
        (output / "comparison-key.json").write_text(json.dumps(key, indent=2))

    async def run(index, label, variant):
        case = cases[index]
        contract = CONTRACTS[case["task"]]
        system = (
            career_system(case["task"], contract)
            if variant == "career"
            else GENERIC + "\n\n" + contract
        )
        async with semaphore:
            start = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    llm.ainvoke(
                        [
                            SystemMessage(content=system),
                            HumanMessage(content=case["input"]),
                        ]
                    ),
                    timeout=40,
                )
                if (
                    not isinstance(response.content, str)
                    or not response.content.strip()
                ):
                    raise ValueError("Empty output")
                item = {
                    "text": response.content,
                    "seconds": round(time.monotonic() - start, 2),
                    "usage": response.usage_metadata or {},
                    "finish_reason": response.response_metadata.get("finish_reason"),
                    "prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
                }
            except Exception as exc:
                item = {
                    "error_type": type(exc).__name__,
                    "seconds": round(time.monotonic() - start, 2),
                }
            records[index]["outputs"][label] = item
            save()
            print(
                case["id"], label, "error" if "error_type" in item else "ok", flush=True
            )

    save()
    await asyncio.gather(
        *(
            run(i, label, variant)
            for i, case in enumerate(cases)
            for label, variant in key[case["id"]].items()
        )
    )
    print("对照记录已保存；需独立语义评审，不能只按结构宣布效果。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--cases", help="只复测指定案例 ID，逗号分隔")
    parser.add_argument("--variant", choices=("both", "career"), default="both")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evaluation" / "career-v1" / "results"
    )
    args = parser.parse_args()
    cases = json.loads(FIXTURES.read_text())
    assert len(cases) == 8 and len({c["id"] for c in cases}) == 8
    assert all(c["task"] in CONTRACTS and c["input"] and c["criteria"] for c in cases)
    if args.cases:
        selected = set(args.cases.split(","))
        assert selected <= {c["id"] for c in cases}
        cases = [c for c in cases if c["id"] in selected]
    if not args.live:
        print(f"{len(cases)} 个虚构案例有效；未调用模型。")
        return
    asyncio.run(compare(cases, args.output, args.variant))


if __name__ == "__main__":
    main()
