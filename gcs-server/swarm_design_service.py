"""Formation configuration receipts; never a flight-control or election policy."""
from __future__ import annotations

import time
from contextlib import nullcontext

from fastapi import HTTPException

from src.smart_swarm_contract import normalize_topology, topology_revision


async def formation_status(deps, assignments=None):
    """Describe observed node configuration separately from the canonical GCS file."""
    assignments = normalize_topology(deps.load_swarm() if assignments is None else assignments)
    revision = topology_revision(assignments)
    now = int(time.time() * 1000)
    with getattr(deps, "telemetry_lock", nullcontext()):
        telemetry = {str(k): dict(v) for k, v in getattr(deps, "telemetry_data_all_drones", {}).items()}
    tracker_factory = getattr(deps, "get_command_tracker", None)
    commands = await tracker_factory().get_active_commands() if callable(tracker_factory) else []
    reports = {}
    targets = set()
    initial_revisions = {}
    for command in commands:
        runtime = command.get("swarm_runtime") or {}
        if not runtime:
            continue
        targets.update(str(i) for i in command.get("target_drones", runtime.get("targets", [])))
        initial = (command.get("params", {}).get("smart_swarm") or {}).get("revision")
        for hw_id, report in runtime.get("nodes", {}).items():
            if report.get("received_at_ms", 0) > reports.get(str(hw_id), {}).get("received_at_ms", 0):
                reports[str(hw_id)] = report
                initial_revisions[str(hw_id)] = initial
    nodes = []
    for assignment in assignments:
        hw_id = assignment["hw_id"]
        state = telemetry.get(hw_id, {})
        timestamp = state.get("telemetry_timestamp_ms") or state.get("update_time") or 0
        try:
            timestamp = float(timestamp)
            if timestamp < 10_000_000_000:
                timestamp *= 1000
        except (TypeError, ValueError):
            timestamp = 0
        reachable = state.get("telemetry_available") is not False and 0 <= now - timestamp <= 5000
        report = reports.get(hw_id, {})
        fresh_report = 0 <= now - report.get("received_at_ms", 0) <= 5000
        phase = report.get("phase")
        if not reachable:
            status = "not_reachable"
        elif hw_id not in targets or (fresh_report and phase in {"takeover", "stopped", "failed"}):
            status = "inactive"
        elif (fresh_report and report.get("applied_revision") == revision
              and str(report.get("follow")) == assignment["follow"]):
            status = "applied"
        else:
            status = "pending"
        nodes.append({"hw_id": hw_id, "status": status,
                      "received_revision": report.get("revision"),
                      "applied_revision": report.get("applied_revision"),
                      "active": hw_id in targets, "phase": phase,
                      # Older clients cannot prove effective installation. Do
                      # not invent proof, but the confirmed startup snapshot is
                      # not an unresolved *later* Apply transaction either.
                      "update_pending": status == "pending" and initial_revisions.get(hw_id) != revision})
    return {"revision": revision, "nodes": nodes,
            "unavailable_hw_ids": [n["hw_id"] for n in nodes if n["status"] == "not_reachable"]}


def changed_formation_ids(before, after):
    old = {m["hw_id"]: m for m in normalize_topology(before)}
    new = {m["hw_id"]: m for m in normalize_topology(after)}
    changed = {hw for hw in old.keys() | new.keys() if old.get(hw) != new.get(hw)}
    # A changed parent also affects descendants, including old dependencies.
    while True:
        expanded = changed | {m["hw_id"] for m in [*old.values(), *new.values()] if m["follow"] in changed}
        if expanded == changed:
            return changed
        changed = expanded


async def validate_apply_observation(deps, before, after, acknowledged_unavailable):
    """Confirm known reachability gaps; do not promise network-atomic delivery."""
    changed = changed_formation_ids(before, after)
    if not changed:
        return
    status = await formation_status(deps, before)
    after_status = await formation_status(deps, after)
    unavailable = sorted(changed & (set(status["unavailable_hw_ids"]) | set(after_status["unavailable_hw_ids"])), key=int)
    if set(unavailable) - set(acknowledged_unavailable):
        raise HTTPException(409, {"code": "unavailable_confirmation_required",
                                  "message": "Some aircraft are not reachable. Apply for when they reconnect?",
                                  "unavailable_hw_ids": unavailable})
    pending = [n["hw_id"] for n in status["nodes"] if n["active"] and n["update_pending"]]
    if pending:
        raise HTTPException(409, {"code": "formation_apply_pending",
                                  "message": "The previous formation is not yet confirmed. Retry after readback or stop the swarm.",
                                  "pending_hw_ids": pending})
