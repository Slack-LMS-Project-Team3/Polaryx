#!/usr/bin/env python3
"""Generate local JWT fixtures for Polaryx performance tests."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ALGORITHM = "HS256"
DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "fixtures" / "users.example.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "fixtures" / "users.local.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--secret", default=os.getenv("SECRET_KEY"))
    parser.add_argument("--expires-minutes", type=int, default=24 * 60)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def load_fixture(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fixture_file:
        data = json.load(fixture_file)

    users = data.get("users")
    if not isinstance(users, list) or not users:
        raise SystemExit(f"{path} must contain a non-empty users array")

    for index, user in enumerate(users, start=1):
        if not user.get("user_id") or not user.get("email"):
            raise SystemExit(f"user #{index} must contain user_id and email")

    return data


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def encode_hs256(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": ALGORITHM, "typ": "JWT"}
    signing_input = ".".join(
        [
            _base64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _base64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_base64url(signature)}"


def add_tokens(data: dict[str, Any], secret: str, expires_minutes: int) -> dict[str, Any]:
    expires_at = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    output = json.loads(json.dumps(data))

    for user in output["users"]:
        payload = {
            "user_id": user["user_id"],
            "email": user["email"],
            "exp": int(expires_at.timestamp()),
        }
        user["access_token"] = encode_hs256(payload, secret)

    output["token_expires_at"] = expires_at.isoformat()
    return output


def main() -> None:
    args = parse_args()
    if not args.secret:
        raise SystemExit("SECRET_KEY is required. Pass --secret or export SECRET_KEY from BE/.env.")

    if args.output.exists() and not args.force:
        raise SystemExit(f"{args.output} already exists. Pass --force to overwrite it.")

    data = load_fixture(args.input)
    output = add_tokens(data, args.secret, args.expires_minutes)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output_file:
        json.dump(output, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
