"""Actor-bound opaque handles for GCS-proxied raw ULog jobs."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import HTTPException, Request

from src.security.auth import build_auth_service


_HANDLE_SCOPE = "ulog-job-v1"
_CAPABILITY_SCOPE = "ulog-job-capability-v1"
_HANDLE_MAX_AGE_SECONDS = 24 * 60 * 60
_ALLOWED_RAW_ULOG_ROLES = frozenset({"operator", "admin"})


@dataclass(frozen=True)
class UlogJobCapability:
    nonce: str
    access_token: str


@dataclass(frozen=True)
class ResolvedUlogJobHandle:
    node_job_id: str
    access_token: str


def _derive_access_token(*, nonce: str, drone_id: int, owner_fingerprint: str) -> str:
    return build_auth_service().derive_scoped_secret(
        _CAPABILITY_SCOPE,
        {
            "nonce": str(nonce),
            "drone_id": int(drone_id),
            "owner": str(owner_fingerprint),
        },
    )


def create_ulog_job_capability(
    *,
    drone_id: int,
    owner_fingerprint: str,
) -> UlogJobCapability:
    nonce = secrets.token_urlsafe(24)
    return UlogJobCapability(
        nonce=nonce,
        access_token=_derive_access_token(
            nonce=nonce,
            drone_id=drone_id,
            owner_fingerprint=owner_fingerprint,
        ),
    )


def require_raw_ulog_actor(request: Request) -> str:
    """Require an operator identity and return its non-reversible fingerprint."""

    context = getattr(request.state, "mds_auth_context", None)
    if not isinstance(context, Mapping):
        context = {}
    role = str(context.get("role") or "viewer").strip().lower()
    if role not in _ALLOWED_RAW_ULOG_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Operator or admin role required for raw ULog download jobs.",
        )
    token = context.get("token")
    token_id = token.get("id") if isinstance(token, Mapping) else None
    identity = {
        "kind": str(context.get("kind") or "unknown"),
        "username": str(context.get("username") or ""),
        "session_id": str(context.get("sid") or ""),
        "token_id": str(token_id or ""),
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def issue_ulog_job_handle(
    *,
    drone_id: int,
    node_job_id: str,
    owner_fingerprint: str,
    expires_at_ms: int | None,
    capability_nonce: str,
) -> str:
    payload = {
        "version": 1,
        "drone_id": int(drone_id),
        "node_job_id": str(node_job_id),
        "owner": str(owner_fingerprint),
        "capability_nonce": str(capability_nonce),
        "expires_at_ms": int(expires_at_ms) if expires_at_ms is not None else None,
    }
    return build_auth_service().sign_scoped_payload(_HANDLE_SCOPE, payload)


def resolve_ulog_job_handle(
    handle: str,
    *,
    drone_id: int,
    owner_fingerprint: str,
) -> ResolvedUlogJobHandle:
    payload = build_auth_service().verify_scoped_payload(
        _HANDLE_SCOPE,
        str(handle),
        max_age_seconds=_HANDLE_MAX_AGE_SECONDS,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="ULog download job not found.")
    expires_at_ms = payload.get("expires_at_ms")
    if expires_at_ms is not None:
        try:
            expired = int(expires_at_ms) <= int(time.time() * 1000)
        except (TypeError, ValueError):
            expired = True
        if expired:
            raise HTTPException(status_code=410, detail="ULog download job has expired.")
    if (
        payload.get("version") != 1
        or int(payload.get("drone_id") or -1) != int(drone_id)
        or str(payload.get("owner") or "") != str(owner_fingerprint)
    ):
        raise HTTPException(status_code=404, detail="ULog download job not found.")
    node_job_id = str(payload.get("node_job_id") or "").strip()
    capability_nonce = str(payload.get("capability_nonce") or "").strip()
    if not node_job_id or not capability_nonce:
        raise HTTPException(status_code=404, detail="ULog download job not found.")
    return ResolvedUlogJobHandle(
        node_job_id=node_job_id,
        access_token=_derive_access_token(
            nonce=capability_nonce,
            drone_id=drone_id,
            owner_fingerprint=owner_fingerprint,
        ),
    )


def protect_ulog_job_payload(
    payload: Mapping[str, Any],
    *,
    handle: str,
) -> dict[str, Any]:
    protected = dict(payload)
    raw_job = protected.get("job")
    if not isinstance(raw_job, Mapping):
        raise HTTPException(status_code=502, detail="Drone returned an invalid ULog job.")
    protected["job"] = {**dict(raw_job), "job_id": handle}
    return protected
