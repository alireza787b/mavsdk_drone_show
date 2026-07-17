"""Canonical GCS fleet-presence classification.

This module keeps liveness semantics in one place so dashboard cards, Fleet Ops,
preflight, and command routing do not drift into different definitions of
"online" or "offline".
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PresenceThresholds:
    live_sec: float
    recent_loss_sec: float
    stale_sec: float
    long_offline_sec: float


def _safe_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed) or parsed < 0:
        return default
    return parsed


def resolve_presence_thresholds(params: Any | None = None) -> PresenceThresholds:
    """Resolve configurable fleet-presence thresholds.

    `live_sec` intentionally stays derived from heartbeat/telemetry cadence so a
    slow but expected polling interval does not create false offline transitions.
    Operator-facing grace windows are then layered above it.
    """

    telemetry_timeout = _safe_float(getattr(params, "TELEMETRY_POLLING_TIMEOUT", 10.0), 10.0)
    heartbeat_interval = _safe_float(getattr(params, "heartbeat_interval", 10.0), 10.0)
    live_sec = max(telemetry_timeout, heartbeat_interval * 2)

    recent_loss_sec = _safe_float(
        os.environ.get("MDS_PRESENCE_RECENT_LOSS_SEC"),
        _safe_float(getattr(params, "PRESENCE_RECENT_LOSS_SEC", 30.0), 30.0),
    )
    stale_sec = _safe_float(
        os.environ.get("MDS_PRESENCE_STALE_SEC"),
        _safe_float(getattr(params, "PRESENCE_STALE_SEC", 60.0), 60.0),
    )
    long_offline_sec = _safe_float(
        os.environ.get("MDS_PRESENCE_LONG_OFFLINE_SEC"),
        _safe_float(getattr(params, "PRESENCE_LONG_OFFLINE_SEC", 300.0), 300.0),
    )

    recent_loss_sec = max(live_sec, recent_loss_sec)
    stale_sec = max(recent_loss_sec, stale_sec)
    long_offline_sec = max(stale_sec, long_offline_sec)

    return PresenceThresholds(
        live_sec=live_sec,
        recent_loss_sec=recent_loss_sec,
        stale_sec=stale_sec,
        long_offline_sec=long_offline_sec,
    )


def _normalize_timestamp_ms(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    if numeric < 1_000_000_000_000:
        numeric *= 1000.0
    return int(numeric)


def _age_sec(timestamp_ms: int | None, now_ms: int) -> float | None:
    if not timestamp_ms:
        return None
    return max(0.0, (now_ms - timestamp_ms) / 1000.0)


def _pick_newest_source(
    heartbeat_timestamp_ms: int | None,
    telemetry_timestamp_ms: int | None,
) -> tuple[int | None, str]:
    if heartbeat_timestamp_ms and telemetry_timestamp_ms:
        if telemetry_timestamp_ms >= heartbeat_timestamp_ms:
            return telemetry_timestamp_ms, "telemetry"
        return heartbeat_timestamp_ms, "heartbeat"
    if telemetry_timestamp_ms:
        return telemetry_timestamp_ms, "telemetry"
    if heartbeat_timestamp_ms:
        return heartbeat_timestamp_ms, "heartbeat"
    return None, "none"


def build_presence_snapshot(
    *,
    hw_id: Any,
    heartbeat: Mapping[str, Any] | None = None,
    telemetry: Mapping[str, Any] | None = None,
    telemetry_success_time: Any = None,
    configured: bool = False,
    preflight_blocked: bool = False,
    now: float | None = None,
    thresholds: PresenceThresholds | None = None,
) -> dict[str, Any]:
    """Return the canonical operator presence snapshot for a node."""

    now_ms = int((now if now is not None else time.time()) * 1000)
    thresholds = thresholds or resolve_presence_thresholds()

    heartbeat_timestamp_ms = _normalize_timestamp_ms((heartbeat or {}).get("timestamp"))
    telemetry_timestamp_ms = _normalize_timestamp_ms(telemetry_success_time)
    telemetry_available = bool((telemetry or {}).get("telemetry_available"))
    if not telemetry_timestamp_ms and telemetry_available:
        telemetry_timestamp_ms = _normalize_timestamp_ms((telemetry or {}).get("update_time") or (telemetry or {}).get("timestamp"))

    last_seen_ms, source = _pick_newest_source(heartbeat_timestamp_ms, telemetry_timestamp_ms)
    age_sec = _age_sec(last_seen_ms, now_ms)
    heartbeat_age_sec = _age_sec(heartbeat_timestamp_ms, now_ms)
    telemetry_age_sec = _age_sec(telemetry_timestamp_ms, now_ms)

    heartbeat_recent = heartbeat_age_sec is not None and heartbeat_age_sec <= thresholds.live_sec
    telemetry_recent = bool(
        telemetry_available
        and telemetry_age_sec is not None
        and telemetry_age_sec <= thresholds.live_sec
    )
    fresh = heartbeat_recent or telemetry_recent

    if last_seen_ms is None:
        state = "never_seen"
        label = "Never seen"
        detail = "No accepted heartbeat or telemetry has been observed by this GCS runtime."
    elif fresh and preflight_blocked:
        state = "blocked"
        label = "Live blocked"
        detail = f"Live link via {source}, but readiness/preflight is blocked."
    elif fresh:
        state = "live"
        label = "Live"
        detail = f"Fresh link via {source}; newest sample {age_sec:.1f}s old."
    elif age_sec is not None and age_sec <= thresholds.recent_loss_sec:
        state = "recently_lost"
        label = "Recent loss"
        detail = f"Link dropped {age_sec:.1f}s ago; monitor for recovery."
    elif age_sec is not None and age_sec <= thresholds.stale_sec:
        state = "stale"
        label = "Stale"
        detail = f"Link stale for {age_sec:.1f}s."
    else:
        state = "offline"
        label = "Offline"
        detail = f"Last seen {age_sec:.1f}s ago." if age_sec is not None else "No recent link evidence."

    long_offline = bool(age_sec is not None and age_sec > thresholds.long_offline_sec)

    return {
        "hw_id": str(hw_id),
        "state": state,
        "label": label,
        "fresh": fresh,
        "configured": bool(configured),
        "source": source,
        "detail": detail,
        "last_seen_ms": last_seen_ms,
        "age_sec": age_sec,
        "long_offline": long_offline,
        "heartbeat_recent": heartbeat_recent,
        "heartbeat_age_sec": heartbeat_age_sec,
        "telemetry_recent": telemetry_recent,
        "telemetry_age_sec": telemetry_age_sec,
        "telemetry_available": telemetry_available,
        "thresholds": {
            "live_sec": thresholds.live_sec,
            "recent_loss_sec": thresholds.recent_loss_sec,
            "stale_sec": thresholds.stale_sec,
            "long_offline_sec": thresholds.long_offline_sec,
        },
    }
