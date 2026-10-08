"""Bounded synthetic live rewrite check. Default only lists cases, no providers.

Use --live --max-cases 1 for at most one generation plus one support check.
All application storage is temporary and encrypted with disposable keys. This
does not test archival, real email, production deployment or user effectiveness.
"""

import argparse
import asyncio
import base64
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evaluation/project-review-2026-10-05/rewrite-cases.json"


async def evaluate(cases, summary):
    # Imported only after main has replaced every application store and mail
    # setting. The configured model is retained, never printed or reconfigured.
    from fastapi import HTTPException
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_openai import ChatOpenAI
    from app.config import get_settings
    from app.database import init_db, engine, SessionLocal
    from app.models.models import ResumeSession
    from app.services.canonical_resume import resume_revision
    from app.services.resume_suggestions import generate_suggestion

    settings = get_settings()
    if not settings.LLM_API_KEY:
        summary.update(status="not_validated", limitation="model_not_configured")
        return

    class Counter(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, **kwargs):
            summary["model_call_attempts"] += 1

        def on_llm_error(self, error, **kwargs):
            summary["provider_error_types"].append(type(error).__name__)

    llm = ChatOpenAI(model=settings.LLM_STRUCTURED_MODEL or settings.LLM_MODEL,
                     api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL,
                     temperature=0, timeout=25, max_retries=0, callbacks=[Counter()])
    init_db()
    try:
        for case in cases:
            data = {"basic_info": {"name": "虚构验收人"},
                    "projects": [{"name": "虚构案例", "description": case["source"]}]}
            session_id = "synthetic-rewrite-" + case["id"]
            with SessionLocal() as db:
                db.add(ResumeSession(session_id=session_id, owner_key="synthetic-review",
                                     resume_data=data, resume_draft="", stage="EVALUATING"))
                db.commit()
            started = time.monotonic()
            record = {"id": case["id"], "input": case, "status": "pending"}
            try:
                result = await generate_suggestion("synthetic-review", session_id, case["source"],
                                                  resume_revision(data), case["instruction"], llm)
                text = result["suggested_text"]
                with SessionLocal() as db:
                    unchanged = db.get(ResumeSession, session_id).resume_data == data
                record.update(status="model_returned", result=result, automated_checks={
                    "canonical_unchanged": unchanged,
                    "no_new_numbers": not (set(re.findall(r"\d+", text)) - set(re.findall(r"\d+", case["source"]))),
                    "preserved_case_markers": all(term.casefold() in text.casefold() for term in case["must_preserve"]),
                    "no_forbidden_case_claims": not any(term.casefold() in text.casefold() for term in case["must_not_add"]),
                })
            except HTTPException as exc:
                record.update(status="not_validated", http_status=exc.status_code)
            except Exception as exc:
                record.update(status="not_validated", error_type=type(exc).__name__)
            record["elapsed_seconds"] = round(time.monotonic() - started, 2)
            summary["cases"].append(record)
            print(json.dumps({"case": case["id"], "status": record["status"]}), flush=True)
            if record["status"] == "not_validated":
                summary["limitation"] = "stopped_after_unavailable_call_no_retry"
                break
        summary["status"] = "awaiting_semantic_review" if all(c["status"] == "model_returned" for c in summary["cases"]) else "not_validated"
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-cases", type=int, choices=range(1, 7), default=1)
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation/project-review-2026-10-05/live-rewrite.json")
    args = parser.parse_args()
    cases = json.loads(CASES.read_text(encoding="utf-8"))[:args.max_cases]
    if not args.live:
        print(json.dumps({"mode": "dry_run", "cases": [c["id"] for c in cases],
                          "max_model_calls": len(cases) * 2, "model_called": False}, ensure_ascii=False))
        return
    logging.basicConfig(level=logging.CRITICAL)
    summary = {"checked_at": datetime.now(timezone.utc).isoformat(), "scope": "synthetic_rewrite_service_only",
               "real_user_database_accessed": False, "smtp_sent": False, "sdk_retries": 0,
               "max_model_calls": len(cases) * 2, "model_call_attempts": 0, "provider_error_types": [],
               "human_semantic_review_required": True, "cases": []}
    with tempfile.TemporaryDirectory(prefix="huhua-rewrite-eval-") as directory:
        folder = Path(directory)
        os.environ.update({
            "DATABASE_URL": f"sqlite:///{folder / 'application.sqlite3'}",
            "CHECKPOINT_DB_PATH": str(folder / "checkpoints.sqlite3"),
            "APP_ENV": "local", "REQUIRE_ACCOUNT": "false", "ENABLE_RAG": "false",
            "ALLOW_INSECURE_LOCAL_STORAGE": "false", "AUTH_COOKIE_SECURE": "false",
            "DATA_ENCRYPTION_KEYS": json.dumps({"eval": base64.b64encode(os.urandom(32)).decode()}),
            "DATA_ENCRYPTION_ACTIVE_KEY": "eval", "ACCOUNT_SECRET": base64.b64encode(os.urandom(32)).decode(),
            "SMTP_HOST": "", "SMTP_FROM": "", "SMTP_USERNAME": "", "SMTP_PASSWORD": "",
            "EMAIL_PROVIDER": "smtp", "RESEND_API_KEY": "", "RESEND_FROM": "", "JEV_API_KEY": "",
        })
        sys.path.insert(0, str(ROOT / "backend"))
        try:
            asyncio.run(evaluate(cases, summary))
        except Exception as exc:
            summary.update(status="not_validated", setup_error_type=type(exc).__name__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "model_call_attempts": summary["model_call_attempts"]}))


if __name__ == "__main__":
    main()
