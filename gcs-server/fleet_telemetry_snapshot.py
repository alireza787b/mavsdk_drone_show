"""Copy-on-read heartbeat metadata, independent of FC telemetry pull backoff."""
from contextlib import nullcontext
from copy import deepcopy
import time

from src.px4_preflight_telemetry import REPORT_KEYS
from px4_preflight_relay import monotonic_ms

from presence import build_presence_snapshot, resolve_presence_thresholds


def fleet_telemetry_snapshot(deps):
    lock = getattr(deps, 'telemetry_lock', None)
    if lock is None:
        lock = getattr(deps, 'telemetry_lock', None) or getattr(deps, 'data_lock', None)
    with lock if lock is not None else nullcontext():
        rows = {key: dict(value or {}) for key, value in deps.telemetry_data_all_drones.items()}
    # Never nest the heartbeat lock inside the telemetry lock.
    getter = getattr(deps, 'get_all_heartbeats', None)
    heartbeats = getter() if callable(getter) else {}
    now_ms = time.time_ns() // 1_000_000
    now_mono = monotonic_ms()
    for key, row in rows.items():
        cache = row.pop('_px4_preflight_cache', {})
        for report_key in REPORT_KEYS:
            item = cache.get(report_key)
            if not item and report_key not in row:
                continue
            remaining = item[0] - now_mono if item else 0
            row[report_key] = {**item[1], 'expires_at_gcs_ms': now_ms + remaining,
                               'expires_at_gcs_monotonic_ms': item[0]} if remaining > 0 else None
        hw_id = str(row.get('hw_id', key))
        heartbeat = heartbeats.get(hw_id)
        if not heartbeat:
            continue
        # An explicit canonical receipt, even invalid, must not fall back to a
        # newer node clock. No HTTP/read time becomes an aircraft timestamp.
        receipt = heartbeat.get('received_at_gcs_ms', heartbeat.get('timestamp'))
        row['heartbeat_last_seen'] = receipt
        row['heartbeat_network_info'] = deepcopy(heartbeat.get('network_info') or {})
        if isinstance(row.get('presence'), dict):
            safe_heartbeat = dict(heartbeat)
            snapshot = build_presence_snapshot(hw_id=hw_id, heartbeat=safe_heartbeat, telemetry=row,
                configured=row['presence'].get('configured', False),
                preflight_blocked=row.get('readiness_status') == 'blocked',
                thresholds=resolve_presence_thresholds(getattr(deps, 'Params', None)))
            if 'received_at_gcs_ms' in heartbeat and snapshot['heartbeat_received_at_gcs_ms'] is None:
                # Preserve the node clock as diagnostics, never as receipt authority.
                sent_at_node_ms = snapshot['heartbeat_sent_at_node_ms']
                safe_heartbeat.update(timestamp=None, sent_at_node_ms=None)
                snapshot = build_presence_snapshot(hw_id=hw_id, heartbeat=safe_heartbeat, telemetry=row,
                    configured=row['presence'].get('configured', False),
                    preflight_blocked=row.get('readiness_status') == 'blocked',
                    thresholds=resolve_presence_thresholds(getattr(deps, 'Params', None)))
                snapshot['heartbeat_sent_at_node_ms'] = sent_at_node_ms
            row['presence'] = snapshot
    return rows
