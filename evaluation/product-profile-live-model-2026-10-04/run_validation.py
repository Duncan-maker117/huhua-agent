"""At most two live structured calls using synthetic data and a temporary DB."""
# ruff: noqa: E402 -- repository-local app imports require the backend path above.

import asyncio
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import UTC, datetime
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from langchain_openai import ChatOpenAI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents import profile_archivist
from app.config import get_settings
from app.database import Base
from app.services.data_crypto import DataCrypto
from app.services import profile_service as archive
from app.services.profile_bridge import ClaimedHistoryImport  # noqa: F401

OUT = Path(__file__).parent


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


async def main():
    logging.basicConfig(level=logging.WARNING)
    settings = get_settings()
    summary = {"date": datetime.now(UTC).isoformat(), "scope": "synthetic_only", "max_model_calls": 2,
               "actual_model_calls": 0, "completed_model_calls": 0, "sdk_retries": 0, "cases": [], "real_user_database_accessed": False}
    if not settings.LLM_API_KEY:
        summary.update(status="not_validated", limitation="model_key_not_configured")
        write_json("verification.json", summary)
        print(json.dumps({"status": summary["status"], "limitation": summary["limitation"]}))
        return
    # The existing configured structured model is used without config changes.
    llm = ChatOpenAI(model=settings.LLM_STRUCTURED_MODEL or settings.LLM_MODEL,
                     api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL,
                     temperature=0, timeout=40, max_retries=0)
    extractor = profile_archivist.make_archivist(llm)
    crypto = DataCrypto({"synthetic-test": os.urandom(32)}, "synthetic-test")
    index_key = os.urandom(32)
    def index(value, scope):
        return hmac.new(index_key, (scope + value).encode(), hashlib.sha256).hexdigest()
    cases = [
        {"id": "limited_role_and_not_launched", "account": "synthetic-one", "project": "纸舟测试项目一",
         "text": "我在「纸舟测试项目一」中只负责后端接口开发。我做出了本地 Demo，尚未上线。", "seed": False},
        {"id": "explicit_correction_and_earlier_demo", "account": "synthetic-two", "project": "纸舟测试项目二",
         "text": "更正：在「纸舟测试项目二」中，之前说我是项目负责人不准确，我实际是后端参与者。这个项目在 2026-08-01 只有本地 Demo；2026-10-01 已经上线。", "seed": True},
    ]
    with tempfile.TemporaryDirectory(prefix="huhua-profile-live-synthetic-") as tmp:
        dbpath = Path(tmp) / "synthetic.sqlite3"
        engine = create_engine(f"sqlite:///{dbpath}")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with patch.object(archive, "get_crypto", return_value=crypto), patch.object(archive, "blind_index", side_effect=index):
            for case in cases:
                if case["seed"]:
                    with factory() as db:
                        archive.add_fact(db, case["account"], category="project", subject=case["project"], field="role", value="项目负责人")
                        archive.add_fact(db, case["account"], category="project", subject=case["project"], field="status", value="已经上线",
                                         effective_at=datetime(2026, 10, 1))
                        db.commit()
                with factory() as db:
                    archive.enqueue_archive_event(db, case["account"], case["id"], "synthetic-chat-" + case["account"],
                                                  {"human_text": case["text"], "source_kind": "self"})
                    before = archive.get_profile(db, case["account"])
                    db.commit()
                recorded = {"case": case["id"], "input": case["text"], "before": before}
                outbound = []
                errors = []
                real_redactor = profile_archivist.redact_model_messages

                def capture_messages(messages, privacy=None):
                    safe = real_redactor(messages, privacy)
                    outbound.extend(safe)
                    return safe

                async def run_once(payload, context):
                    if summary["actual_model_calls"] >= 2:
                        raise RuntimeError("model_call_limit_reached")
                    summary["actual_model_calls"] += 1
                    recorded["extraction_context"] = context
                    try:
                        result = await extractor(payload, context)
                    except Exception as error:
                        # Exception bodies/configuration can include provider internals.
                        errors.append(type(error).__name__)
                        raise
                    recorded["model_output"] = result.model_dump(mode="json")
                    summary["completed_model_calls"] += 1
                    recorded["grounding"] = [
                        {"category": item.category, "field": item.field, "value": item.value,
                         "accepted_literal_evidence": profile_archivist.validate_grounding(item, payload, context)}
                        for item in result.proposals
                    ]
                    return result

                start = time.monotonic()
                with patch.object(profile_archivist, "redact_model_messages", side_effect=capture_messages):
                    outcome = await archive.process_pending_events(factory, run_once, limit=1, timeout_seconds=45)
                with factory() as db:
                    after = archive.get_profile(db, case["account"])
                    db.commit()
                active = after["facts"]
                values = [fact["value"] for fact in active]
                checks = {
                    "worker_completed": outcome["completed"] == 1,
                    "literal_evidence_accepted": bool(recorded.get("grounding")) and all(r["accepted_literal_evidence"] for r in recorded.get("grounding", [])),
                    "user_provided_not_independently_verified": all(f["source_type"] == "user_provided" for f in active),
                    "database_has_no_synthetic_plaintext": case["project"].encode() not in dbpath.read_bytes(),
                }
                if not case["seed"]:
                    checks.update(limited_contribution_retained=any("只负责后端" in value for value in values),
                                  not_launched_retained=any("尚未上线" in value for value in values))
                else:
                    checks.update(corrected_role_active=any(f["field"] == "role" and f["value"] == "后端参与者" for f in active),
                                  old_role_not_active=all(f["value"] != "项目负责人" for f in active),
                                  later_launch_not_overwritten=any(f["field"] == "status" and f["value"] == "已经上线" for f in active))
                recorded.update(outbound_messages=outbound, after=after, worker_outcome=outcome,
                                error_types=errors, checks=checks, passed=all(checks.values()),
                                elapsed_seconds=round(time.monotonic() - start, 2))
                write_json(case["id"] + ".json", recorded)
                summary["cases"].append({"id": case["id"], "passed": recorded["passed"], "checks": checks,
                                         "error_types": errors, "elapsed_seconds": recorded["elapsed_seconds"]})
                if errors:
                    # No retries or alternate provider/model after a failure.
                    summary["limitation"] = "live_model_call_failed_no_retry"
                    break
        engine.dispose()
    summary["status"] = ("not_validated" if any(case["error_types"] for case in summary["cases"])
                         else "passed" if len(summary["cases"]) == 2 and all(case["passed"] for case in summary["cases"])
                         else "not_passed")
    summary["limitation"] = summary.get("limitation") or "Two synthetic examples only; not a general model quality guarantee."
    write_json("verification.json", summary)
    print(json.dumps({"status": summary["status"], "actual_model_calls": summary["actual_model_calls"],
                      "case_results": [{"id": c["id"], "passed": c["passed"], "error_types": c["error_types"]} for c in summary["cases"]]}))


if __name__ == "__main__":
    asyncio.run(main())
