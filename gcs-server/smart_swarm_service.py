"""Saved-cluster launch and truthful runtime presentation for Smart Swarm.

Uses the existing command journal/dispatch and callback capabilities.  It does
not own flight control, leader election, or an independent safety policy.
"""
from __future__ import annotations

import time
from fastapi import HTTPException
from src.smart_swarm_contract import (
    SmartSwarmSession, dependency_closed_targets, normalize_topology,
    resolve_clusters, topology_revision,
)


def build_preview(deps):
    assignments = normalize_topology(deps.load_swarm() or [])
    with deps.telemetry_lock:
        telemetry = {str(k): dict(v) for k, v in deps.telemetry_data_all_drones.items()}
    now_ms = int(time.time() * 1000)
    clusters = resolve_clusters(assignments)
    for cluster in clusters:
        unavailable = []
        for member in cluster["members"]:
            state = telemetry.get(member["hw_id"], {})
            timestamp = state.get("telemetry_timestamp_ms") or state.get("update_time") or 0
            try:
                timestamp = float(timestamp)
                if timestamp < 10_000_000_000:
                    timestamp *= 1000
            except (TypeError, ValueError):
                timestamp = 0
            available = state.get("telemetry_available") is not False and 0 <= now_ms - timestamp <= 5000
            member["available"] = available
            member["armed"] = state.get("is_armed")
            if not available:
                unavailable.append(member["hw_id"])
        cluster["unavailable_hw_ids"] = unavailable
        cluster["available_hw_ids"] = dependency_closed_targets(cluster["members"], unavailable)
        cluster["partial_exclusion_hw_ids"] = sorted(
            set(m["hw_id"] for m in cluster["members"]) - set(cluster["available_hw_ids"]),
            key=int,
        )
    return {"revision": topology_revision(assignments), "clusters": clusters}


async def start_cluster(deps, request):
    from command_submission import submit_tracked_command, build_replay_receipt
    from schemas import SubmitCommandRequest

    # A lost HTTP response must recover the same command even if the operator
    # edited the layout or a node reconnected since the original acceptance.
    existing = await deps.get_command_tracker().lookup_command_by_idempotency_key(request.idempotency_key)
    if existing:
        snapshot = existing.get("params", {}).get("smart_swarm") or {}
        clusters = resolve_clusters(snapshot.get("assignments", []))
        requested_cluster = request.cluster_id
        if requested_cluster is None and len(clusters) == 1:
            requested_cluster = clusters[0]["cluster_id"]
        original_cluster = next((c for c in clusters if c["cluster_id"] == requested_cluster), None)
        expected = (dependency_closed_targets(original_cluster["members"], request.excluded_hw_ids)
                    if original_cluster else [])
        if (existing.get("mission_type") != 2 or snapshot.get("revision") != request.revision
            or set(snapshot.get("excluded_hw_ids", [])) != set(request.excluded_hw_ids)
            or set(existing.get("target_drones", [])) != set(expected)):
            raise HTTPException(409, "Idempotency key already belongs to a different command")
        return build_replay_receipt(existing)

    preview = build_preview(deps)
    if request.revision != preview["revision"]:
        raise HTTPException(409, "Swarm layout changed; review the updated formation")
    clusters = preview["clusters"]
    cluster = next((c for c in clusters if c["cluster_id"] == request.cluster_id), None)
    if cluster is None and request.cluster_id is None and len(clusters) == 1:
        cluster = clusters[0]
    if cluster is None:
        raise HTTPException(409, "Choose the saved swarm cluster to start")
    all_ids = [m["hw_id"] for m in cluster["members"]]
    excluded = set(request.excluded_hw_ids)
    allowed_exclusions = set(all_ids) - set(cluster["available_hw_ids"])
    if excluded and excluded != allowed_exclusions:
        raise HTTPException(409, "Availability changed; review the partial-start confirmation")
    targets = dependency_closed_targets(cluster["members"], list(excluded))
    if not targets:
        raise HTTPException(409, "No available leader and follow chain to start")
    # A stale GCS cache is advisory. With no explicit exclusions, send the
    # complete reviewed cluster and let each node check fresh flight evidence.
    assignments = normalize_topology([member for c in preview["clusters"] for member in c["members"]])
    session = SmartSwarmSession(
        revision=preview["revision"], assignments=assignments,
        expected_hw_ids=targets, excluded_hw_ids=sorted(excluded),
    )
    return await submit_tracked_command(deps, SubmitCommandRequest(
        mission_type=2, trigger_time=0, target_drone_ids=targets,
        idempotency_key=request.idempotency_key, smart_swarm=session,
        operator_label="Start Smart Swarm" if not excluded else "Start partial Smart Swarm",
    ))


def runtime_summary(params, targets, *, now_ms=None, terminal=False):
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    snapshot = params.get("smart_swarm")
    if not snapshot:
        return None
    reports = params.get("_swarm_runtime", {})
    live_phases = {"active", "acquiring", "settling", "tracking_degraded", "holding"}
    active = [i for i in targets if reports.get(i, {}).get("phase") in live_phases
              and now_ms - reports[i]["received_at_ms"] <= 15000]
    takeover = [i for i in targets if reports.get(i, {}).get("phase") == "takeover"]
    leader_session_active = any(
        str(reports.get(i, {}).get("role", "")).lower() == "leader"
        and reports.get(i, {}).get("phase") in live_phases
        and now_ms - reports[i]["received_at_ms"] <= 15000
        for i in targets
    )
    if terminal:
        confirmed_stop = all(reports.get(i, {}).get("phase") in {"takeover", "stopped", "failed"} for i in targets)
        state = ("pilot_takeover" if takeover else "stopped") if confirmed_stop else "unconfirmed"
    elif len(active) == len(targets):
        state = "partial" if snapshot.get("excluded_hw_ids") else "active"
    elif leader_session_active and not takeover:
        # A leader-side jog/show changes vehicle control ownership, not the
        # cluster role session.  Keep the operator state truthful without
        # turning that expected transition into an alarm.
        state = "leader_motion"
    elif takeover:
        state = "pilot_takeover"
    elif active or any(r.get("phase") in {"active", "holding", "stopped", "failed"} for r in reports.values()):
        state = "degraded"
    else:
        state = "starting"
    return {"state": state, "active_hw_ids": active, "targets": targets,
            "leader_session_active": leader_session_active,
            "excluded_hw_ids": snapshot.get("excluded_hw_ids", []), "nodes": reports}
