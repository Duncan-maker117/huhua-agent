"""Disposable real-app UI harness. Never import this module in production.

Uses fresh temporary databases and random process-only keys. Authentication,
ownership, encryption, profile, resume and export endpoints are the real app.
Only outbound SMTP transport is replaced by a memory mailbox for .invalid users.
Run: .venv/bin/python tests/product_live_server.py --port 8894
"""

import argparse
import base64
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path


def run(port=8894, *, setup_fixture=None):
    with tempfile.TemporaryDirectory(prefix="huhua-real-ui-") as directory:
        root = Path(directory)
        os.environ.update({
            "APP_ENV": "local", "REQUIRE_ACCOUNT": "true", "AUTH_COOKIE_SECURE": "false",
            "ALLOW_INSECURE_LOCAL_STORAGE": "false", "LLM_API_KEY": "", "JEV_API_KEY": "", "TAVILY_API_KEY": "",
            "ENABLE_RAG": "false", "SMTP_HOST": "", "SMTP_FROM": "", "SMTP_USERNAME": "", "SMTP_PASSWORD": "",
            "EMAIL_PROVIDER": "smtp", "RESEND_API_KEY": "", "RESEND_FROM": "",
            "DATABASE_URL": f"sqlite:///{root / 'app.sqlite3'}",
            "CHECKPOINT_DB_PATH": str(root / "checkpoints.sqlite3"),
            "DATA_ENCRYPTION_ACTIVE_KEY": "fixture-v1",
            "DATA_ENCRYPTION_KEYS": json.dumps({"fixture-v1": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}),
            "ACCOUNT_SECRET": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            "APP_ORIGIN": f"http://127.0.0.1:{port}",
            "ARCHIVE_POLL_SECONDS": "60",
        })
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        from app.config import get_settings
        get_settings.cache_clear()
        import main
        from fastapi import HTTPException, Query

        class Mailbox:
            codes = {}

            def available(self):
                return True

            def send(self, email, code):
                if not email.endswith("@huhua-fixture.invalid"):
                    raise HTTPException(422, "This test harness accepts fictional fixture addresses only")
                self.codes[email] = code

        mailbox = Mailbox()
        make_service = main.get_account_service

        def with_mailbox():
            service = make_service()
            service.transport = mailbox
            return service

        main.get_account_service = with_mailbox
        if setup_fixture is not None:
            setup_fixture(main)

        @main.app.get("/__test__/otp")
        async def fixture_otp(email: str = Query(...)):
            if email not in mailbox.codes:
                raise HTTPException(404, "No fixture message")
            return {"code": mailbox.codes[email]}

        @main.app.get("/__test__/storage-audit")
        async def fixture_storage_audit():
            markers = ["HUHUA_LIVE_NORA", "HUHUA_LIVE_EDIT", "本地合并虚构验收", "nora@huhua-fixture.invalid"]
            files = [p for p in root.iterdir() if p.is_file()]
            findings = {p.name: [m for m in markers if m.encode() in p.read_bytes()] for p in files}
            return {"encrypted": True, "require_account": True, "model_key_configured": False,
                    "mail_delivery": "memory-only-fixture", "markers": markers, "files": findings,
                    "plaintext_marker_found": any(findings.values())}

        print(f"Fixture-only encrypted app at http://127.0.0.1:{port}; fresh temporary database; no outbound SMTP/model", flush=True)
        import uvicorn
        uvicorn.run(main.app, host="127.0.0.1", port=port, access_log=False, log_level="warning")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8894)
    run(parser.parse_args().port)
