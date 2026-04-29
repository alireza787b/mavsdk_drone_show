#!/usr/bin/env python3
"""CLI recovery/admin helper for optional MDS auth."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for candidate in [REPO_ROOT, REPO_ROOT / "src"]:
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from src.security.auth import AuthService, AuthSettings  # noqa: E402


def _load_gcs_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_gcs_env(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else [
        "# MDS GCS Configuration",
        "# Updated by mds_auth_admin.py",
    ]
    seen: set[str] = set()
    rendered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in updates:
                rendered.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        rendered.append(line)
    for key, value in updates.items():
        if key not in seen:
            rendered.append(f"{key}={value}")
    path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")


def _settings() -> AuthSettings:
    env_path = Path(os.environ.get("MDS_GCS_SYSTEM_CONFIG", "/etc/mds/gcs.env"))
    for key, value in _load_gcs_env(env_path).items():
        os.environ.setdefault(key, value)
    return AuthSettings.from_env()


def _service() -> AuthService:
    return AuthService(_settings())


def _read_password(args) -> str:
    if args.password_file:
        return Path(args.password_file).read_text(encoding="utf-8").strip()
    if args.password_stdin:
        return sys.stdin.read().strip()
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    return first


def cmd_status(args) -> int:
    service = _service()
    payload = {
        "dashboard_auth_enabled": service.settings.dashboard_auth_enabled,
        "api_auth_enabled": service.settings.api_auth_enabled,
        "setup_required": service.setup_required(),
        "users_file": str(service.settings.users_file),
        "tokens_file": str(service.settings.tokens_file),
        "users": service.store.list_users(),
        "tokens": service.store.list_tokens(),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_enable_disable(args) -> int:
    env_path = Path(os.environ.get("MDS_GCS_SYSTEM_CONFIG", "/etc/mds/gcs.env"))
    updates: dict[str, str] = {}
    if args.target in {"dashboard", "both"}:
        updates["MDS_AUTH_ENABLED"] = "true" if args.enable else "false"
    if args.target in {"api", "both"}:
        updates["MDS_API_AUTH_ENABLED"] = "true" if args.enable else "false"
    _write_gcs_env(env_path, updates)
    print(json.dumps({"updated": updates, "env_file": str(env_path)}, indent=2, sort_keys=True))
    return 0


def cmd_add_user(args) -> int:
    service = _service()
    password = _read_password(args)
    user = service.store.upsert_user(
        args.username,
        password=password,
        role=args.role,
        disabled=False,
        force_password_change=args.force_password_change,
    )
    print(json.dumps({"user": user, "message": "User saved"}, indent=2, sort_keys=True))
    return 0


def cmd_set_password(args) -> int:
    service = _service()
    password = _read_password(args)
    user = service.store.set_password(args.username, password, force_password_change=args.force_password_change)
    print(json.dumps({"user": user, "message": "Password updated"}, indent=2, sort_keys=True))
    return 0


def cmd_create_token(args) -> int:
    service = _service()
    ttl_seconds = args.ttl_hours * 3600 if args.ttl_hours else None
    token = service.store.create_token(
        args.name,
        scopes=args.scope,
        ttl_seconds=ttl_seconds,
        created_by=args.created_by,
        notes=args.notes,
    )
    print(json.dumps({"token": token, "message": "Copy token now; plaintext is shown only once."}, indent=2, sort_keys=True))
    return 0


def cmd_revoke_token(args) -> int:
    service = _service()
    token = service.store.revoke_token(args.token_id)
    print(json.dumps({"token": token, "message": "Token revoked"}, indent=2, sort_keys=True))
    return 0


def cmd_rotate_session_secret(args) -> int:
    service = _service()
    secret_path = service.settings.session_secret_file
    backup_path = secret_path.with_suffix(f"{secret_path.suffix}.bak")
    if secret_path.exists():
        backup_path.write_text(secret_path.read_text(encoding="utf-8"), encoding="utf-8")
    secret_path.write_text("", encoding="utf-8")
    service = AuthService(_settings())
    service.create_session({"username": "rotation-check", "role": "admin"})
    print(json.dumps({"message": "Session secret rotated; existing browser sessions are invalid.", "backup": str(backup_path)}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MDS auth admin/recovery helper")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)

    for name, enable in [("enable-dashboard", True), ("disable-dashboard", False), ("enable-api", True), ("disable-api", False)]:
        command = sub.add_parser(name)
        command.set_defaults(func=cmd_enable_disable, enable=enable, target="dashboard" if "dashboard" in name else "api")

    add_user = sub.add_parser("add-user")
    add_user.add_argument("username")
    add_user.add_argument("--role", default="admin", choices=["admin", "operator", "viewer"])
    add_user.add_argument("--password-file")
    add_user.add_argument("--password-stdin", action="store_true")
    add_user.add_argument("--force-password-change", action="store_true")
    add_user.set_defaults(func=cmd_add_user)

    set_password = sub.add_parser("set-password")
    set_password.add_argument("username")
    set_password.add_argument("--password-file")
    set_password.add_argument("--password-stdin", action="store_true")
    set_password.add_argument("--force-password-change", action="store_true")
    set_password.set_defaults(func=cmd_set_password)

    create_token = sub.add_parser("create-token")
    create_token.add_argument("--name", required=True)
    create_token.add_argument("--scope", action="append", default=[])
    create_token.add_argument("--ttl-hours", type=int)
    create_token.add_argument("--created-by", default="cli")
    create_token.add_argument("--notes", default="")
    create_token.set_defaults(func=cmd_create_token)

    revoke_token = sub.add_parser("revoke-token")
    revoke_token.add_argument("token_id")
    revoke_token.set_defaults(func=cmd_revoke_token)

    rotate = sub.add_parser("rotate-session-secret")
    rotate.set_defaults(func=cmd_rotate_session_secret)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
