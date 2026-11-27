"""Retain bounded Smart Swarm observations for one verified ULog and aircraft."""

from __future__ import annotations

import asyncio
import math
import re
from collections import deque
from datetime import datetime, timezone

from mds_logging.api_schemas import CompanionEvidence, CompanionEvidenceEvent

_MAX_SESSIONS = 8
_MAX_PAGES = 16
_MAX_EVENTS = 128
_MAX_EVENT_BYTES = 128 * 1024
_SESSION = re.compile(r"s_(\d{8}_\d{6})(?:_\d+)?")
_COMPONENT = "smart_swarm.link"
_EVENT_LABELS = {
    "session_start": "Session started", "session_end": "Session ended", "link_summary": "Link sample",
    "mode_requested": "Mode requested", "mode_result": "Mode request result", "mode_observed": "Mode observed",
    "network_observation": "Aircraft Wi-Fi", "hold_decision": "Hold decision", "recovery": "Recovery", "coverage_gap": "Recording gap",
}
_METRICS = frozenset("""
    state transport last_accepted_at_ms position_age_ms heading_age_ms own_position_age_ms own_heading_age_ms
    accepted rejected duplicate fallback_attempts max_gap_ms last_rejection max_setpoint_send_ms max_setpoint_gap_ms setpoint_count hard_stale_ms
    action reason outcome error mode armed dropped event_sequence dropped_before trigger_age_ms threshold_ms
    validation leader_hw_id last_transport_error wifi_signal_percent wifi_interface wifi_observed_at_ms wifi_status mode_age_ms
""".split())


def unavailable(reason):
    return CompanionEvidence(status="unavailable", reason=reason)


def _flight_sessions(items, start, end):
    selected = []
    for item in items:
        if not isinstance(item, dict):
            continue
        session = item.get("session_id")
        match = _SESSION.fullmatch(session) if isinstance(session, str) and len(session) <= 64 else None
        if match:
            try:
                created = datetime.strptime(match[1], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc).timestamp()
                modified = float(item["modified"])
            except (ValueError, KeyError, TypeError, OverflowError):
                continue
            if created * 1000 <= end and modified * 1000 >= start:
                selected.append(session)
    return sorted(set(selected), reverse=True)


def _event(entry, session, hw_id, start, end):
    if not isinstance(entry, dict) or entry.get("component") != _COMPONENT:
        return None
    extra = entry.get("extra")
    if not isinstance(extra, dict) or extra.get("schema_version") != 1:
        return None
    if str(extra.get("hw_id")) != hw_id or entry.get("session_id") != session:
        return None
    # A companion subprocess may run outside the coordinator's global logging context.
    if entry.get("drone_id") is not None and str(entry["drone_id"]) != hw_id:
        return None
    kind, at = extra.get("event"), extra.get("observed_at_ms")
    if not isinstance(kind, str) or kind not in _EVENT_LABELS or type(at) is not int or not start <= at <= end:
        return None
    command_id = extra.get("session_id")
    if not isinstance(command_id, str) or not 0 < len(command_id) <= 128:
        return None
    metrics = {}
    for name in _METRICS:
        value = extra.get(name)
        if type(value) in (int, float, bool) and abs(value) <= 2 ** 53 and math.isfinite(value):
            metrics[name] = value
        elif isinstance(value, str) and 0 < len(value) <= 128:
            metrics[name] = value
    detail = {"mode_observed": "mode", "mode_requested": "action", "mode_result": "outcome",
              "hold_decision": "reason", "recovery": "outcome"}.get(kind)
    label = _EVENT_LABELS[kind]
    if detail and isinstance(metrics.get(detail), str):
        label += " · " + metrics[detail].replace("_", " ")[:64]
    source = "Companion Wi-Fi" if kind == "network_observation" else "Smart Swarm"
    category = "sample" if kind in {"network_observation", "link_summary"} else "event"
    return CompanionEvidenceEvent(utc_ms=at, source=source, kind=category, label=label,
                                  session_id=session, command_id=command_id, metrics=metrics)


def _evenly_spaced(rows, limit):
    if limit <= 0:
        return []
    if len(rows) <= limit:
        return rows
    if limit == 1:
        return rows[-1:]
    return [rows[i * (len(rows) - 1) // (limit - 1)] for i in range(limit)]


def _retained_rows(rows):
    # Preserve flight decisions before periodic samples. Page/request limits already
    # bound the working set; the smaller persisted projection has its own budget.
    rows.sort(key=lambda row: row.utc_ms)
    decisions = [row for row in rows if row.kind == "event"]
    samples = [row for row in rows if row.kind == "sample"]
    limit = _MAX_EVENTS
    while limit:
        selected = _evenly_spaced(decisions, limit)
        selected = selected + _evenly_spaced(samples, limit - len(selected))
        size = sum(len(row.model_dump_json().encode()) + 1 for row in selected)
        if size <= _MAX_EVENT_BYTES:
            return sorted(selected, key=lambda row: row.utc_ms)
        limit = min(limit - 1, limit * _MAX_EVENT_BYTES // size)
    return []


async def collect_companion_evidence(hw_id, timeline):
    from log_proxy import DroneProxyResponseError, fetch_drone_session_content, fetch_drone_sessions, resolve_drone_ip

    start, end = (timeline or {}).get("start_utc_ms"), (timeline or {}).get("end_utc_ms")
    if start is None or end is None:
        return unavailable("The flight log has no verified UTC interval.")
    rows, reason = [], None
    command_bounds, sequences = {}, {}
    # JSONL ts is write time. Read some margin and match each row's observation time locally.
    query = {name: datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()
             for name, ms in (("since", start - 10_000), ("until", end + 10_000))}
    try:
        async with asyncio.timeout(12):
            ip = resolve_drone_ip(int(hw_id))
            if not ip:
                return unavailable("The aircraft address is unavailable.")
            inventory = await fetch_drone_sessions(ip)
            if not isinstance(inventory, dict) or not isinstance(inventory.get("sessions"), list):
                return unavailable("Companion sessions could not be read.")
            sessions = _flight_sessions(inventory["sessions"], start - 10_000, end + 10_000)
            if len(sessions) > _MAX_SESSIONS:
                reason = "The capture reached its session limit."
            # One page per source per pass, so an active coordinator log cannot starve a follower log.
            pending = deque((session, None, ip) for session in sessions[:_MAX_SESSIONS])
            for _ in range(_MAX_PAGES):
                if not pending:
                    break
                session, cursor, cursor_host = pending.popleft()
                ip = resolve_drone_ip(int(hw_id))
                if not ip:
                    reason = "The aircraft address became unavailable during capture."
                    break
                if cursor and ip != cursor_host:
                    # A node-issued cursor is pinned to an endpoint and file snapshot.
                    reason = "The aircraft address changed during a paged session read."
                    continue
                try:
                    page = await fetch_drone_session_content(ip, session, component=_COMPONENT,
                                                            limit=64, cursor=cursor, **query)
                except DroneProxyResponseError:
                    page = None
                if not page or page.get("session_id") != session or page.get("schema_version") != "1.1":
                    reason = "A companion session was unavailable or uses an older log format."
                    continue
                coverage = page.get("coverage")
                if not isinstance(coverage, dict):
                    coverage = {}
                if any(coverage.get(field) for field in ("malformed_records", "oversized_records", "incomplete_records")):
                    reason = "The companion session contains unreadable records."
                for entry in page["lines"]:
                    row = _event(entry, session, hw_id, start, end)
                    if row is None:
                        continue
                    rows.append(row)
                    kind = entry["extra"]["event"]
                    command_bounds.setdefault(row.command_id, set()).add(kind)
                    sequence = row.metrics.get("event_sequence")
                    key = (session, row.command_id)
                    if type(sequence) is int:
                        if key in sequences and sequence != sequences[key] + 1:
                            reason = "The companion reported a recording gap."
                        sequences[key] = sequence
                    if kind == "coverage_gap" or row.metrics.get("dropped_before"):
                        reason = "The companion reported a recording gap."
                if page.get("has_more"):
                    following = page.get("next_cursor")
                    if isinstance(following, str) and 0 < len(following) <= 4096 and following != cursor:
                        pending.append((session, following, ip))
                    else:
                        reason = "The companion could not provide the next page."
            if pending:
                reason = "The capture reached its page limit."
    except TimeoutError:
        reason = "Companion capture timed out."
    if not rows:
        return unavailable(reason or "No matching Smart Swarm observations were recorded for this flight.")
    if any(not {"session_start", "session_end"} <= events for events in command_bounds.values()):
        reason = reason or "Only part of a Smart Swarm session was captured within this flight."
    selected = _retained_rows(rows)
    if len(selected) < len(rows):
        reason = reason or "The saved timeline was sampled to fit the retention limit."
    return CompanionEvidence(status="partial" if reason else "available", reason=reason, events=selected)
