import time
from typing import Any, Dict, Iterable

from heartbeat import get_all_heartbeats
from params import Params
from presence import build_presence_snapshot, resolve_presence_thresholds
from telemetry import data_lock as telemetry_lock
from telemetry import last_telemetry_time, telemetry_data_all_drones


def _normalize_hw_id(value: Any) -> str:
    return str(value).strip()


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

    thresholds = resolve_presence_thresholds(Params)

    snapshots: Dict[str, Dict[str, Any]] = {}
    for hw_id in sorted(all_hw_ids):
        heartbeat = heartbeats.get(hw_id) if isinstance(heartbeats.get(hw_id), dict) else None
        telemetry_row = telemetry_rows.get(hw_id) or {}
        snapshot = build_presence_snapshot(
            hw_id=hw_id,
            heartbeat=heartbeat,
            telemetry=telemetry_row,
            telemetry_success_time=telemetry_success_times.get(hw_id),
            now=now,
            thresholds=thresholds,
        )
        heartbeat_age_seconds = snapshot.get("heartbeat_age_sec")
        heartbeat_recent = bool(snapshot.get("heartbeat_recent"))
        telemetry_age_seconds = snapshot.get("telemetry_age_sec")
        telemetry_recent = bool(snapshot.get("telemetry_recent"))
        telemetry_available = bool(snapshot.get("telemetry_available"))
        online_recent = bool(snapshot.get("fresh"))

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
            "presence_state": snapshot.get("state", "unknown"),
            "last_seen_ms": snapshot.get("last_seen_ms"),
            "long_offline": bool(snapshot.get("long_offline")),
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
