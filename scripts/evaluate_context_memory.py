"""Reproducible synthetic input-size/fidelity probe; no model or database calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys

from langchain_core.messages import AIMessage, HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.agents.context_memory import estimate_input_tokens  # noqa: E402
from app.agents.orchestrator import _input_messages, _sources, SYSTEM_PROMPT  # noqa: E402
from app.services.model_privacy import CONTACT_PRIVACY_NOTICE, ContactRedactor  # noqa: E402


def measure():
    items, messages, expected = [], [], []
    for index in range(4):
        subject = f"合成项目{index}"
        statements = [f"{subject}只做了本地原型，没有上线。", f"{subject}登录由同学完成，我没有写登录模块。",
                      f"{subject}整理了12条离线测试记录，没有做线上压测。"]
        expected.extend(statements)
        source_id = f"source-{index}"
        messages.append(HumanMessage(content="\n".join(statements), id=source_id))
        facts = [{"id": f"f-{index}-{j}", "text": text, "source_quote": text,
                  "kind": "status_limit", "status": "active", "turn_id": source_id}
                 for j, text in enumerate(statements)]
        items.append({"item_id": f"p-{index}", "name": subject, "facts": facts})
        messages.append(AIMessage(content="可以根据这些真实材料整理经历。" * 150))
    for index in range(36):
        messages.extend([HumanMessage(content=f"第{index}轮：保持这些事实边界。", id=f"discussion-{index}"),
                         AIMessage(content="我会根据已有材料分析措辞，保留实际分工、测试口径和未完成状态。" * 100)])
    messages.append(HumanMessage(content="请总结四个项目，不能把没做过的事情写成做过。", id="current"))
    state = {"messages": messages, "collected_info": {"projects": items}}
    original = deepcopy(state)
    compacted = _input_messages(state, _sources(state), ContactRedactor())
    full = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + CONTACT_PRIVACY_NOTICE},
            *[{"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content} for m in messages]]
    memory = json.loads(compacted[1]["content"])["untrusted_data"]["candidate_memory"]
    evidence_text = json.dumps(memory, ensure_ascii=False)
    retained = sum(text in evidence_text for text in expected)
    before, after = estimate_input_tokens(full), estimate_input_tokens(compacted)
    assert retained == len(expected) and state == original
    return {"fixture": "synthetic-4-projects-41-user-turns", "provider_calls": 0,
            "measurement": "conservative UTF-8 input estimate; not actual provider token usage",
            "baseline": "full transcript with the same system prompt; not previous bounded projection",
            "full_transcript_estimate": before, "compacted_estimate": after,
            "reduction_vs_full_transcript_percent": round(100 * (1 - after / before), 2),
            "required_statements": len(expected), "retained_statements": retained,
            "source_state_unchanged": state == original}


if __name__ == "__main__":
    print(json.dumps(measure(), ensure_ascii=False, indent=2))
