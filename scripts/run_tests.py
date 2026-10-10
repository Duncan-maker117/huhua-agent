"""Run the offline suite without touching configured user stores or providers."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="huhua-offline-tests-") as directory:
        path = Path(directory)
        environment = {
            **os.environ,
            "DATABASE_URL": f"sqlite:///{path / 'application.sqlite3'}",
            "CHECKPOINT_DB_PATH": str(path / "checkpoints.sqlite3"),
            "LLM_API_KEY": "", "TAVILY_API_KEY": "", "ENABLE_RAG": "false",
            "SMTP_HOST": "", "SMTP_PASSWORD": "", "SMTP_FROM": "",
            "EMAIL_PROVIDER": "smtp", "RESEND_API_KEY": "", "RESEND_FROM": "",
            "APP_ENV": "local", "REQUIRE_ACCOUNT": "false",
            "ALLOW_INSECURE_LOCAL_STORAGE": "true", "ACCOUNT_SECRET": "",
            "DATA_ENCRYPTION_KEYS": "{}", "DATA_ENCRYPTION_ACTIVE_KEY": "",
        }
        # Encryption/account integration fixtures inject their own random keys
        # and require authentication. This compatibility mode is only for the
        # pre-existing isolated unit fixtures, never the application runtime.
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests",
             "-p", "test_*.py", *sys.argv[1:]], cwd=root, env=environment,
        )
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
