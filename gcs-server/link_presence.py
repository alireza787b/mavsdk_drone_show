import time
from typing import Any, Dict, Iterable

from heartbeat import get_all_heartbeats
from params import Params
from telemetry import data_lock as telemetry_lock
from telemetry import last_telemetry_time, telemetry_data_all_drones


def _normalize_hw_id(value: Any) -> str:
    return str(value).strip()


def _safe_age_seconds_from_ms(timestamp_ms: Any, now: float) -> float | None:
    if not timestamp_ms:
        return None

    try:
        return now - (float(timestamp_ms) / 1000.0)
    except (TypeError, ValueError):
        return None


def _safe_age_seconds_from_seconds(timestamp_seconds: Any, now: float) -> float | None:
    if not timestamp_seconds:
        return None

    try:
        return now - float(timestamp_seconds)
    except (TypeError, ValueError):
        return None


def get_recent_link_presence(
    hw_ids: Iterable[Any] | None = None,
    *,
    now: float | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Build a recent-link snapshot from both heartbeat and telemetry state.

    Heartbeats are still useful for broad fleet liveness, but command dispatch and
    active-fleet selection should not treat a drone as offline if direct telemetry
    polling is still succeeding. This helper provides one canonical recent-link
    view for those backend decisions.
    """
    if now is None:
        now = time.time()

    try:
        heartbeats = get_all_heartbeats() or {}
    except Exception:
        heartbeats = {}

    with telemetry_lock:
        telemetry_rows = {
            _normalize_hw_id(hw_id): dict(row or {})
            for hw_id, row in telemetry_data_all_drones.items()
        }
        telemetry_success_times = {
            _normalize_hw_id(hw_id): last_success
            for hw_id, last_success in last_telemetry_time.items()
        }

    requested_ids = {
        _normalize_hw_id(hw_id)
        for hw_id in (hw_ids or [])
        if _normalize_hw_id(hw_id)
    }
    all_hw_ids = requested_ids | set(heartbeats.keys()) | set(telemetry_rows.keys())

    heartbeat_grace_seconds = max(Params.TELEMETRY_POLLING_TIMEOUT, Params.heartbeat_interval * 2)
    telemetry_grace_seconds = max(
        Params.TELEMETRY_POLLING_TIMEOUT,
        Params.HTTP_REQUEST_TIMEOUT * 3,
        Params.telem_poll_interval * 3,
    )

    snapshots: Dict[str, Dict[str, Any]] = {}
    for hw_id in sorted(all_hw_ids):
        heartbeat = heartbeats.get(hw_id) if isinstance(heartbeats.get(hw_id), dict) else None
        heartbeat_age_seconds = _safe_age_seconds_from_ms(
            heartbeat.get("timestamp") if heartbeat else None,
            now,
        )
        heartbeat_recent = (
            heartbeat_age_seconds is not None and heartbeat_age_seconds <= heartbeat_grace_seconds
        )

        telemetry_row = telemetry_rows.get(hw_id) or {}
        telemetry_available = bool(telemetry_row.get("telemetry_available"))
        telemetry_age_seconds = _safe_age_seconds_from_seconds(
            telemetry_success_times.get(hw_id),
            now,
        )
        telemetry_recent = (
            telemetry_available
            and telemetry_age_seconds is not None
            and telemetry_age_seconds <= telemetry_grace_seconds
        )

        online_recent = heartbeat_recent or telemetry_recent

        if online_recent:
            if heartbeat_recent and telemetry_recent:
                reason = "Recent heartbeat and telemetry"
                source = "heartbeat+telemetry"
            elif telemetry_recent:
                reason = "Recent telemetry"
                source = "telemetry"
            else:
                reason = "Recent heartbeat"
                source = "heartbeat"
        elif heartbeat_age_seconds is not None:
            reason = f"Heartbeat stale ({heartbeat_age_seconds:.1f}s old)"
            source = "stale-heartbeat"
        elif telemetry_age_seconds is not None and telemetry_available:
            reason = f"Telemetry stale ({telemetry_age_seconds:.1f}s old)"
            source = "stale-telemetry"
        elif telemetry_age_seconds is not None:
            reason = "Telemetry unavailable"
            source = "telemetry-unavailable"
        else:
            reason = "No recent heartbeat or telemetry"
            source = "none"

        snapshots[hw_id] = {
            "hw_id": hw_id,
            "online_recent": online_recent,
            "reason": reason,
            "source": source,
            "heartbeat_recent": heartbeat_recent,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "telemetry_recent": telemetry_recent,
            "telemetry_age_seconds": telemetry_age_seconds,
            "telemetry_available": telemetry_available,
        }

    return snapshots
