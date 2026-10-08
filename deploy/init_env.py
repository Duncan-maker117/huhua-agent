"""Create a NEW installation's runtime env once; never rotate existing keys."""

import argparse
import base64
import json
import os
from pathlib import Path
import secrets


def initialize(destination):
    template = Path(__file__).with_name("app.env.example").read_text(encoding="utf-8")
    keyring = json.dumps({"v1": base64.b64encode(secrets.token_bytes(32)).decode()}, separators=(",", ":"))
    content = template.replace("__GENERATED_KEYRING__", keyring).replace(
        "__GENERATED_ACCOUNT_SECRET__", base64.b64encode(secrets.token_bytes(32)).decode(),
    )
    # O_EXCL also refuses a pre-existing symlink; no key material reaches stdout.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("app.env"))
    args = parser.parse_args()
    try:
        initialize(args.output)
    except FileExistsError:
        raise SystemExit("Refused: environment file already exists. Keep its original data/account keys.")
    print(f"Created {args.output} with mode 0600. Configure model/email settings; keep keys backed up separately.")
