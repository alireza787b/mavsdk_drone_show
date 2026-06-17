"""In-memory node boot/init status reported before coordinator readiness."""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

from mds_logging import get_logger

logger = get_logger("node_boot")

NODE_BOOT_STATUS_TTL_MS = 15 * 60 * 1000
NODE_BOOT_STATUS_MAX_ENTRIES = 1024
NODE_BOOT_ALLOWED_STATUSES = {"running", "success", "warning", "error"}
NODE_BOOT_ALLOWED_RUNTIME_MODES = {"real", "sitl"}

node_boot_statuses: dict[str, dict[str, Any]] = {}
node_boot_status_lock = Lock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return " ".join(text.split())


def _bounded_text(value: Any, default: str = "", *, max_length: int) -> str:
    return _clean_text(value, default)[:max_length]


def _prune_node_boot_statuses(now_ms: int) -> None:
    stale_before = now_ms - NODE_BOOT_STATUS_TTL_MS
    stale_keys = [
        key for key, value in node_boot_statuses.items()
        if int(value.get("timestamp") or 0) < stale_before
    ]
    for key in stale_keys:
        node_boot_statuses.pop(key, None)

    overflow = len(node_boot_statuses) - NODE_BOOT_STATUS_MAX_ENTRIES
    if overflow <= 0:
        return
    oldest_keys = sorted(
        node_boot_statuses,
        key=lambda key: int(node_boot_statuses[key].get("timestamp") or 0),
    )[:overflow]
    for key in oldest_keys:
        node_boot_statuses.pop(key, None)


def handle_node_boot_status_post(
    *,
    hw_id: str,
    pos_id: int | None = None,
    ip: str | None = None,
    runtime_mode: str | None = None,
    phase: str,
    status: str = "running",
    message: str | None = None,
    source: str = "git-sync",
    timestamp: int | None = None,
    allowed_hw_ids: set[str] | None = None,
    identity_trust: str | None = None,
    source_ip_matched: bool | None = None,
) -> dict[str, Any]:
    """Store one boot report without marking the node commandable."""

    normalized_hw_id = _bounded_text(hw_id, max_length=32)
    if not normalized_hw_id:
        raise ValueError("Missing hw_id")
    if allowed_hw_ids is not None and normalized_hw_id not in allowed_hw_ids:
        raise ValueError(f"Node boot status rejected for unconfigured hw_id={normalized_hw_id}")

    normalized_phase = _bounded_text(phase, "unknown", max_length=64).lower().replace(" ", "_") or "unknown"
    normalized_status = _bounded_text(status, "running", max_length=16).lower().replace(" ", "_") or "running"
    if normalized_status not in NODE_BOOT_ALLOWED_STATUSES:
        raise ValueError("Node boot status must be one of: running, success, warning, error")
    normalized_runtime_mode = _bounded_text(runtime_mode, max_length=16).lower() or None
    if normalized_runtime_mode and normalized_runtime_mode not in NODE_BOOT_ALLOWED_RUNTIME_MODES:
        raise ValueError("runtime_mode must be either real or sitl")

    # Use server receipt time for operator evidence; client time is not trusted.
    timestamp_ms = _now_ms()
    payload = {
        "hw_id": normalized_hw_id,
        "pos_id": pos_id,
        "ip": _bounded_text(ip, max_length=128) or None,
        "runtime_mode": normalized_runtime_mode,
        "phase": normalized_phase,
        "status": normalized_status,
        "message": _bounded_text(message, max_length=240),
        "source": _bounded_text(source, "git-sync", max_length=64) or "git-sync",
        "timestamp": timestamp_ms,
        "identity_trust": _bounded_text(identity_trust, "config_bound", max_length=32) or "config_bound",
        "source_ip_matched": bool(source_ip_matched),
    }

    with node_boot_status_lock:
        _prune_node_boot_statuses(timestamp_ms)
        existing = node_boot_statuses.get(normalized_hw_id, {})
        payload["first_seen"] = existing.get("first_seen") or timestamp_ms
        node_boot_statuses[normalized_hw_id] = payload

    logger.info(
        "Node boot status: hw_id=%s phase=%s status=%s source=%s",
        normalized_hw_id,
        normalized_phase,
        normalized_status,
        payload["source"],
    )
    return {"accepted": True, "node": dict(payload)}


def get_all_node_boot_statuses() -> dict[str, dict[str, Any]]:
    """Return a copy of the latest boot/init status by hardware ID."""

    now_ms = _now_ms()
    with node_boot_status_lock:
        _prune_node_boot_statuses(now_ms)
        return {key: dict(value) for key, value in node_boot_statuses.items()}
