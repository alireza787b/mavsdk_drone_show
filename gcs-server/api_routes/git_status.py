"""Git status and repo sync routes for the GCS FastAPI app."""

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from auth_runtime import authorize_websocket
from git_status import commits_match
from presence import build_presence_snapshot, resolve_presence_thresholds
from schemas import (
    DroneConnectivityRuntimeStatus,
    DroneEnvRuntimeStatus,
    DroneGitStatus,
    DroneGitSyncRuntimeStatus,
    DroneMavlinkRuntimeStatus,
    GitStatus,
    GitStatusResponse,
    GitStatusStreamMessage,
    SyncReposRequest,
    SyncReposResponse,
)
from src.managed_runtime_status import resolve_dashboard_access

FLEET_OPS_MUTATION_TOKEN_ENV = "MDS_FLEET_OPS_MUTATION_TOKEN"
GIT_SYNC_SCHEMA = "mds.fleet_git_sync.v1"
GIT_SYNC_DRY_RUN_TTL_SECONDS = 300
_git_sync_jobs: dict[str, dict[str, Any]] = {}


class FleetGitSyncDryRunRequest(BaseModel):
    pos_ids: list[int] | None = None
    include_offline: bool = False


class FleetActionConfirmation(BaseModel):
    operator: str | None = None
    acknowledged_risks: bool = False
    confirmation_token: str | None = None


class FleetGitSyncApplyRequest(BaseModel):
    dry_run_id: str
    confirmation: FleetActionConfirmation


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _build_git_status_response(deps: Any) -> GitStatusResponse:
    drones_config = deps.load_config()
    drone_map = {str(drone["hw_id"]): drone for drone in drones_config}

    try:
        gcs_status = deps.get_gcs_git_report()
    except Exception:
        gcs_status = None

    gcs_branch = (gcs_status or {}).get("branch")
    gcs_commit = (gcs_status or {}).get("commit")
    transformed_git_status = {}
    actionable_online_hw_ids = _resolve_actionable_online_hw_ids(deps)

    with deps.data_lock_git_status:
        for hw_id, raw_data in deps.git_status_data_all_drones.items():
            if not raw_data:
                continue

            drone_info = drone_map.get(str(hw_id), {})
            raw_status = raw_data.get("status", "unknown")
            commits_behind = raw_data.get("commits_behind", 0)
            commits_ahead = raw_data.get("commits_ahead", 0)

            if raw_status == "clean" and commits_behind == 0 and commits_ahead == 0:
                mapped_status = GitStatus.SYNCED
            elif commits_behind > 0 and commits_ahead > 0:
                mapped_status = GitStatus.DIVERGED
            elif commits_behind > 0:
                mapped_status = GitStatus.BEHIND
            elif commits_ahead > 0:
                mapped_status = GitStatus.AHEAD
            elif raw_status == "dirty":
                mapped_status = GitStatus.DIRTY
            elif raw_status == "clean":
                mapped_status = GitStatus.SYNCED
            else:
                try:
                    mapped_status = GitStatus(raw_status)
                except ValueError:
                    mapped_status = GitStatus.UNKNOWN

            commit_hash = raw_data.get("commit", "unknown")
            same_branch_as_gcs = raw_data.get("branch") == gcs_branch if gcs_branch else mapped_status == GitStatus.SYNCED
            same_commit_as_gcs = commits_match(commit_hash, gcs_commit) if gcs_commit else mapped_status == GitStatus.SYNCED
            in_sync_with_gcs = (
                same_branch_as_gcs
                and same_commit_as_gcs
                and raw_status != "dirty"
                and not raw_data.get("uncommitted_changes")
            )

            drone_ip = drone_info.get("ip", "unknown")
            raw_mavlink_runtime = raw_data.get("mavlink_runtime") if isinstance(raw_data.get("mavlink_runtime"), dict) else None
            raw_connectivity_runtime = raw_data.get("connectivity_runtime") if isinstance(raw_data.get("connectivity_runtime"), dict) else None
            raw_git_sync_runtime = raw_data.get("git_sync_runtime") if isinstance(raw_data.get("git_sync_runtime"), dict) else None
            raw_env_runtime = raw_data.get("env_runtime") if isinstance(raw_data.get("env_runtime"), dict) else None

            mavlink_runtime = None
            if raw_mavlink_runtime:
                dashboard_enabled = bool(raw_mavlink_runtime.get("dashboard_enabled", False))
                access = (
                    {"dashboard_access_mode": "disabled", "dashboard_url": None}
                    if not dashboard_enabled
                    else resolve_dashboard_access(drone_ip, raw_mavlink_runtime.get("dashboard_listen"))
                )
                mavlink_runtime = DroneMavlinkRuntimeStatus(
                    tool=raw_mavlink_runtime.get("tool", "mavlink-anywhere"),
                    status_source=raw_mavlink_runtime.get("status_source", "unknown"),
                    mode=raw_mavlink_runtime.get("mode"),
                    management_mode=raw_mavlink_runtime.get("management_mode", "unknown"),
                    service_state=raw_mavlink_runtime.get("service_state"),
                    ref=raw_mavlink_runtime.get("ref", "unknown"),
                    installed_ref=raw_mavlink_runtime.get("installed_ref"),
                    repo_web_url=raw_mavlink_runtime.get("repo_web_url"),
                    install_dir_present=bool(raw_mavlink_runtime.get("install_dir_present", False)),
                    runtime_present=bool(raw_mavlink_runtime.get("runtime_present", False)),
                    runtime_head=raw_mavlink_runtime.get("runtime_head"),
                    router_service_status=raw_mavlink_runtime.get("router_service_status", "unknown"),
                    dashboard_enabled=dashboard_enabled,
                    dashboard_listen=raw_mavlink_runtime.get("dashboard_listen", ""),
                    dashboard_service_status=raw_mavlink_runtime.get("dashboard_service_status", "unknown"),
                    dashboard_access_mode=str(access.get("dashboard_access_mode") or "unknown"),
                    dashboard_url=access.get("dashboard_url"),
                    desired_config_hash=raw_mavlink_runtime.get("desired_config_hash"),
                    applied_config_hash=raw_mavlink_runtime.get("applied_config_hash"),
                    config_hash_match=raw_mavlink_runtime.get("config_hash_match"),
                    profile_source=raw_mavlink_runtime.get("profile_source"),
                    desired_hash=raw_mavlink_runtime.get("desired_hash"),
                    applied_hash=raw_mavlink_runtime.get("applied_hash"),
                    local_hash=raw_mavlink_runtime.get("local_hash"),
                    drift_state=raw_mavlink_runtime.get("drift_state"),
                    profile_summary=raw_mavlink_runtime.get("profile_summary") or {},
                    last_apply_result=raw_mavlink_runtime.get("last_apply_result"),
                )

            connectivity_runtime = None
            if raw_connectivity_runtime:
                access = resolve_dashboard_access(drone_ip, raw_connectivity_runtime.get("dashboard_listen"))
                connectivity_runtime = DroneConnectivityRuntimeStatus(
                    tool=raw_connectivity_runtime.get("tool", "smart-wifi-manager"),
                    status_source=raw_connectivity_runtime.get("status_source", "unknown"),
                    backend=raw_connectivity_runtime.get("backend", "unknown"),
                    service_state=raw_connectivity_runtime.get("service_state"),
                    ref=raw_connectivity_runtime.get("ref", "unknown"),
                    installed_ref=raw_connectivity_runtime.get("installed_ref"),
                    repo_web_url=raw_connectivity_runtime.get("repo_web_url"),
                    install_dir_present=bool(raw_connectivity_runtime.get("install_dir_present", False)),
                    mode=raw_connectivity_runtime.get("mode", "unknown"),
                    import_mode=raw_connectivity_runtime.get("import_mode", "unknown"),
                    profile_present=bool(raw_connectivity_runtime.get("profile_present", False)),
                    profile_hash=raw_connectivity_runtime.get("profile_hash"),
                    dashboard_listen=raw_connectivity_runtime.get("dashboard_listen", ""),
                    service_status=raw_connectivity_runtime.get("service_status", "unknown"),
                    dashboard_access_mode=str(access.get("dashboard_access_mode") or "unknown"),
                    dashboard_url=access.get("dashboard_url"),
                    desired_config_hash=raw_connectivity_runtime.get("desired_config_hash"),
                    applied_config_hash=raw_connectivity_runtime.get("applied_config_hash"),
                    config_hash_match=raw_connectivity_runtime.get("config_hash_match"),
                    profile_source=raw_connectivity_runtime.get("profile_source"),
                    desired_hash=raw_connectivity_runtime.get("desired_hash"),
                    applied_hash=raw_connectivity_runtime.get("applied_hash"),
                    local_hash=raw_connectivity_runtime.get("local_hash"),
                    drift_state=raw_connectivity_runtime.get("drift_state"),
                    profile_summary=raw_connectivity_runtime.get("profile_summary") or {},
                    last_apply_result=raw_connectivity_runtime.get("last_apply_result"),
                )

            git_sync_runtime = None
            if raw_git_sync_runtime:
                git_sync_runtime = DroneGitSyncRuntimeStatus(
                    status=raw_git_sync_runtime.get("status", "unknown"),
                    summary=raw_git_sync_runtime.get("summary", ""),
                    last_run_at_ms=raw_git_sync_runtime.get("last_run_at_ms"),
                    updated_units=raw_git_sync_runtime.get("updated_units", []),
                    service_reload_status=raw_git_sync_runtime.get("service_reload_status", "unknown"),
                    service_reload_message=raw_git_sync_runtime.get("service_reload_message", ""),
                    deferred_unit_actions=raw_git_sync_runtime.get("deferred_unit_actions", []),
                    coordinator_restart_scheduled=bool(raw_git_sync_runtime.get("coordinator_restart_scheduled", False)),
                    connectivity_reconcile_status=raw_git_sync_runtime.get("connectivity_reconcile_status", "unknown"),
                    mavlink_runtime_reconcile_status=raw_git_sync_runtime.get("mavlink_runtime_reconcile_status", "unknown"),
                    mavsdk_runtime_status=raw_git_sync_runtime.get("mavsdk_runtime_status", "unknown"),
                    requirements_update_status=raw_git_sync_runtime.get("requirements_update_status", "unknown"),
                    recovery_action=raw_git_sync_runtime.get("recovery_action", "none"),
                    recovery_backup_path=raw_git_sync_runtime.get("recovery_backup_path"),
                    disk_available_status=raw_git_sync_runtime.get("disk_available_status", "unknown"),
                    disk_free_kb=raw_git_sync_runtime.get("disk_free_kb"),
                )

            env_runtime = None
            if raw_env_runtime:
                raw_env_hw_id = raw_env_runtime.get("hw_id")
                env_hw_id = _safe_int(raw_env_hw_id, 0) or None
                env_runtime = DroneEnvRuntimeStatus(
                    status_source=raw_env_runtime.get("status_source", "unknown"),
                    registry_version=_safe_int(raw_env_runtime.get("registry_version"), 0),
                    registry_hash=raw_env_runtime.get("registry_hash", ""),
                    local_env_path=raw_env_runtime.get("local_env_path", ""),
                    local_env_present=bool(raw_env_runtime.get("local_env_present", False)),
                    node_identity_path=raw_env_runtime.get("node_identity_path", ""),
                    node_identity_present=bool(raw_env_runtime.get("node_identity_present", False)),
                    runtime_mode=raw_env_runtime.get("runtime_mode", "unknown"),
                    runtime_mode_source=raw_env_runtime.get("runtime_mode_source", "unknown"),
                    hw_id=env_hw_id,
                    hw_id_source=raw_env_runtime.get("hw_id_source", "unknown"),
                    configured_key_count=_safe_int(raw_env_runtime.get("configured_key_count"), 0),
                    configured_node_key_count=_safe_int(raw_env_runtime.get("configured_node_key_count"), 0),
                    registered_node_key_count=_safe_int(raw_env_runtime.get("registered_node_key_count"), 0),
                    unknown_keys=_safe_string_list(raw_env_runtime.get("unknown_keys")),
                    deprecated_keys=_safe_string_list(raw_env_runtime.get("deprecated_keys")),
                    warnings=_safe_string_list(raw_env_runtime.get("warnings")),
                )

            transformed_git_status[str(hw_id)] = DroneGitStatus(
                pos_id=int(drone_info.get("pos_id", hw_id)),
                hw_id=str(hw_id),
                ip=drone_ip,
                branch=raw_data.get("branch", "unknown"),
                commit=commit_hash,
                commit_message=raw_data.get("commit_message"),
                commit_date=raw_data.get("commit_date"),
                author_name=raw_data.get("author_name"),
                author_email=raw_data.get("author_email"),
                status=mapped_status,
                in_sync_with_gcs=in_sync_with_gcs,
                commits_ahead=raw_data.get("commits_ahead", 0),
                commits_behind=raw_data.get("commits_behind", 0),
                uncommitted_changes=raw_data.get("uncommitted_changes", []),
                repo_access_mode=raw_data.get("repo_access_mode", "custom_or_unknown"),
                git_auth_health_status=raw_data.get("git_auth_health_status", "unknown"),
                git_auth_health_summary=raw_data.get("git_auth_health_summary"),
                git_auth_health_issues=raw_data.get("git_auth_health_issues", []),
                mavlink_runtime=mavlink_runtime,
                connectivity_runtime=connectivity_runtime,
                git_sync_runtime=git_sync_runtime,
                env_runtime=env_runtime,
                last_check=int(time.time() * 1000),
                last_sync=None,
            )

    actionable_statuses = [
        status
        for hw_id, status in transformed_git_status.items()
        if actionable_online_hw_ids is None or hw_id in actionable_online_hw_ids
    ]
    synced_count = len([status for status in actionable_statuses if status.in_sync_with_gcs])

    return GitStatusResponse(
        git_status=transformed_git_status,
        total_drones=len(transformed_git_status),
        synced_count=synced_count,
        needs_sync_count=len(actionable_statuses) - synced_count,
        gcs_status=gcs_status,
        sync_in_progress=deps._sync_state["active"],
        timestamp=int(time.time() * 1000),
    )


def _resolve_actionable_online_hw_ids(deps: Any) -> set[str] | None:
    """Return online heartbeat ids for sync warnings, or None when unavailable.

    Git status records can outlive an offline drone. Keeping those records is
    useful for Fleet Ops diagnostics, but the global sync warning should only
    count drones that are currently actionable.
    """
    try:
        heartbeats = deps.get_all_heartbeats() or {}
    except Exception:
        return None

    if not isinstance(heartbeats, dict):
        return None
    if not heartbeats:
        return set()

    now = time.time()
    thresholds = resolve_presence_thresholds(deps.Params)
    online_hw_ids: set[str] = set()

    for hw_id, heartbeat in heartbeats.items():
        if not isinstance(heartbeat, dict):
            continue
        snapshot = build_presence_snapshot(
            hw_id=hw_id,
            heartbeat=heartbeat,
            now=now,
            thresholds=thresholds,
        )
        if snapshot.get("fresh"):
            online_hw_ids.add(str(hw_id))

    return online_hw_ids


def _require_mutation_authority(request: Request) -> None:
    expected = os.environ.get(FLEET_OPS_MUTATION_TOKEN_ENV, "").strip()
    if not expected:
        return
    supplied = request.headers.get("x-fleet-ops-token", "").strip()
    auth_header = request.headers.get("authorization", "").strip()
    if not supplied and auth_header.lower().startswith("bearer "):
        supplied = auth_header[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="invalid Fleet Ops mutation token")


def _job_confirmation_token(job: dict[str, Any]) -> str:
    seed = json.dumps(
        {
            "job_id": job.get("job_id"),
            "kind": job.get("kind"),
            "target_branch": job.get("target_branch"),
            "target_commit": job.get("target_commit"),
            "targets": job.get("targets", []),
            "created_at": job.get("created_at"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _confirmation_token_matches(job: dict[str, Any], supplied: str | None) -> bool:
    expected = str(job.get("confirmation_token") or "")
    return bool(expected and supplied and hmac.compare_digest(str(supplied).strip(), expected))


def _safe_heartbeats(deps: Any) -> dict[str, dict[str, Any]]:
    try:
        heartbeats = deps.get_all_heartbeats() or {}
    except Exception:
        return {}
    if not isinstance(heartbeats, dict):
        return {}
    return {str(key): value for key, value in heartbeats.items() if isinstance(value, dict)}


def _presence_for_hw_id(deps: Any, hw_id: str, heartbeats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    heartbeat = heartbeats.get(str(hw_id), {})
    timestamp_ms = heartbeat.get("timestamp") or heartbeat.get("last_heartbeat")
    if not timestamp_ms:
        return {"state": "unknown", "fresh": False, "last_seen_ms": None}
    try:
        last_seen_ms = int(float(timestamp_ms))
    except (TypeError, ValueError):
        return {"state": "unknown", "fresh": False, "last_seen_ms": None}
    timeout = float(getattr(deps.Params, "TELEMETRY_POLLING_TIMEOUT", 5) or 5)
    age_seconds = max(0.0, time.time() - (last_seen_ms / 1000.0))
    fresh = age_seconds < timeout
    return {
        "state": "online" if fresh else "offline",
        "fresh": fresh,
        "last_seen_ms": last_seen_ms,
        "age_seconds": round(age_seconds, 1),
    }


def _git_row_status(raw_data: dict[str, Any], gcs_status: dict[str, Any] | None) -> tuple[str, bool]:
    raw_status = raw_data.get("status", "unknown")
    commits_behind = _safe_int(raw_data.get("commits_behind"), 0)
    commits_ahead = _safe_int(raw_data.get("commits_ahead"), 0)
    if raw_status == "dirty" or raw_data.get("uncommitted_changes"):
        status = "dirty"
    elif commits_behind > 0 and commits_ahead > 0:
        status = "diverged"
    elif commits_behind > 0:
        status = "behind"
    elif commits_ahead > 0:
        status = "ahead"
    elif raw_status == "clean":
        status = "synced"
    else:
        status = str(raw_status or "unknown")

    gcs_branch = (gcs_status or {}).get("branch")
    gcs_commit = (gcs_status or {}).get("commit")
    same_branch = raw_data.get("branch") == gcs_branch if gcs_branch else status == "synced"
    same_commit = commits_match(raw_data.get("commit", ""), gcs_commit) if gcs_commit else status == "synced"
    return status, bool(same_branch and same_commit and status == "synced")


def _build_fleet_git_sync_table(deps: Any) -> dict[str, Any]:
    drones_config = deps.load_config()
    try:
        gcs_status = deps.get_gcs_git_report()
    except Exception:
        gcs_status = None
    heartbeats = _safe_heartbeats(deps)
    rows = []
    with deps.data_lock_git_status:
        git_snapshot = dict(deps.git_status_data_all_drones)
    for drone in drones_config:
        hw_id = str(drone.get("hw_id"))
        raw_data = git_snapshot.get(hw_id, {}) or {}
        status, in_sync = _git_row_status(raw_data, gcs_status)
        presence = _presence_for_hw_id(deps, hw_id, heartbeats)
        rows.append(
            {
                "hw_id": hw_id,
                "pos_id": int(drone.get("pos_id", drone.get("hw_id", 0)) or 0),
                "ip": drone.get("ip"),
                "presence": presence,
                "status": status,
                "in_sync_with_gcs": in_sync,
                "branch": raw_data.get("branch", "unknown"),
                "commit": raw_data.get("commit", "unknown"),
                "target_branch": (gcs_status or {}).get("branch"),
                "target_commit": (gcs_status or {}).get("commit"),
                "git_auth_health_status": raw_data.get("git_auth_health_status", "unknown"),
                "git_sync_runtime": raw_data.get("git_sync_runtime") if isinstance(raw_data.get("git_sync_runtime"), dict) else None,
            }
        )
    return {
        "schema": GIT_SYNC_SCHEMA,
        "rows": rows,
        "needs_sync_count": len([row for row in rows if row["presence"]["fresh"] and not row["in_sync_with_gcs"]]),
        "timestamp": int(time.time() * 1000),
        "gcs_status": gcs_status,
    }


def _selected_git_sync_targets(deps: Any, pos_ids: list[int] | None) -> list[dict[str, Any]]:
    drones_config = deps.load_config()
    if pos_ids:
        requested = {int(pos_id) for pos_id in pos_ids}
        return [drone for drone in drones_config if int(drone.get("pos_id", 0) or 0) in requested]
    target_drones, _skipped = deps._select_sync_target_drones(drones_config, None)
    return target_drones


def _build_git_sync_dry_run(deps: Any, request_payload: FleetGitSyncDryRunRequest) -> dict[str, Any]:
    try:
        gcs_status = deps.get_gcs_git_report()
    except Exception:
        gcs_status = {}
    branch = (gcs_status or {}).get("branch") or getattr(deps.Params, "GIT_BRANCH", "main")
    expected_commit = (gcs_status or {}).get("commit", "")
    heartbeats = _safe_heartbeats(deps)
    targets = _selected_git_sync_targets(deps, request_payload.pos_ids)
    results: dict[str, Any] = {}
    accepted_targets: list[dict[str, Any]] = []
    for drone in targets:
        hw_id = str(drone.get("hw_id"))
        presence = _presence_for_hw_id(deps, hw_id, heartbeats)
        warnings = []
        if not presence["fresh"]:
            if not request_payload.include_offline:
                results[hw_id] = {"ok": False, "error": "node is not online; rerun with include_offline only for deliberate recovery", "presence": presence}
                continue
            warnings.append("node is offline or stale; apply will target last-known node metadata")
        accepted_targets.append(drone)
        results[hw_id] = {
            "ok": True,
            "pos_id": int(drone.get("pos_id", drone.get("hw_id", 0)) or 0),
            "ip": drone.get("ip"),
            "presence": presence,
            "warnings": warnings,
            "planned_command": "UPDATE_CODE",
            "target_branch": branch,
            "target_commit": expected_commit,
        }
    job = {
        "schema": GIT_SYNC_SCHEMA,
        "job_id": f"git-sync-{uuid.uuid4().hex[:12]}",
        "kind": "git-sync-dry-run",
        "target_branch": branch,
        "target_commit": expected_commit,
        "targets": [
            {
                "hw_id": str(drone.get("hw_id")),
                "pos_id": int(drone.get("pos_id", drone.get("hw_id", 0)) or 0),
                "ip": drone.get("ip"),
            }
            for drone in accepted_targets
        ],
        "results": results,
        "created_at": int(time.time() * 1000),
        "applied": False,
    }
    job["confirmation_token"] = _job_confirmation_token(job)
    _git_sync_jobs[job["job_id"]] = job
    return job


def _validate_git_sync_job(job: dict[str, Any], confirmation: FleetActionConfirmation) -> None:
    if job.get("applied"):
        raise HTTPException(status_code=409, detail="dry-run job was already applied")
    created_at = _safe_int(job.get("created_at"), 0)
    if created_at <= 0 or time.time() - (created_at / 1000.0) > GIT_SYNC_DRY_RUN_TTL_SECONDS:
        raise HTTPException(status_code=409, detail="dry-run job expired")
    if not confirmation.acknowledged_risks:
        raise HTTPException(status_code=400, detail="acknowledged_risks is required")
    if not _confirmation_token_matches(job, confirmation.confirmation_token):
        raise HTTPException(status_code=400, detail="dry-run confirmation token is required")


def create_git_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/git/status", response_model=GitStatusResponse, tags=["Git"])
    async def get_git_status():
        """Get git status from all drones."""
        return _build_git_status_response(deps)

    @router.get("/api/v1/fleet/git-sync", tags=["Git"])
    async def get_fleet_git_sync_table():
        """Return Fleet Ops git-sync table state without mutating drones."""
        return _build_fleet_git_sync_table(deps)

    @router.post("/api/v1/fleet/git-sync/dry-run", tags=["Git"])
    async def dry_run_fleet_git_sync(sync_request: FleetGitSyncDryRunRequest, http_request: Request):
        """Plan a node git sync. No drone command is dispatched."""
        _require_mutation_authority(http_request)
        return _build_git_sync_dry_run(deps, sync_request)

    @router.post("/api/v1/fleet/git-sync/apply", response_model=SyncReposResponse, tags=["Git"])
    async def apply_fleet_git_sync(sync_request: FleetGitSyncApplyRequest, http_request: Request):
        """Apply a previously accepted Fleet Ops git-sync dry-run."""
        _require_mutation_authority(http_request)
        job = _git_sync_jobs.get(sync_request.dry_run_id)
        if not job:
            raise HTTPException(status_code=404, detail="dry-run job not found")
        _validate_git_sync_job(job, sync_request.confirmation)

        async with deps._sync_lock:
            if deps._sync_state["active"]:
                return SyncReposResponse(
                    success=False,
                    message="A sync operation is already in progress",
                    synced_drones=[],
                    failed_drones=[],
                    total_attempted=0,
                    target_branch=None,
                    target_commit=None,
                )
            deps._sync_state["active"] = True
            deps._sync_state["started_at"] = time.time()
            deps._sync_state["results"] = None

        try:
            heartbeats = _safe_heartbeats(deps)
            all_targets = [dict(target) for target in job.get("targets", [])]
            live_targets = []
            stale_targets = []
            for target in all_targets:
                presence = _presence_for_hw_id(deps, str(target.get("hw_id")), heartbeats)
                if presence["fresh"]:
                    live_targets.append(target)
                else:
                    stale_targets.append(target)
            if stale_targets:
                raise HTTPException(status_code=409, detail="one or more dry-run targets are no longer online; rerun dry-run")
            if not live_targets:
                return SyncReposResponse(
                    success=False,
                    message="No eligible dry-run targets remain online",
                    synced_drones=[],
                    failed_drones=[],
                    total_attempted=0,
                    target_branch=job.get("target_branch"),
                    target_commit=job.get("target_commit"),
                )

            command_data = {
                "mission_type": 103,
                "trigger_time": 0,
                "update_branch": job.get("target_branch"),
            }
            target_hw_ids = [str(target["hw_id"]) for target in live_targets]
            results = deps.send_commands_to_selected(deps.load_config(), command_data, target_hw_ids)
            accepted_hw_ids = []
            failed_hw_ids = []
            per_drone_results = results.get("results", {}) if isinstance(results, dict) else {}
            for hw_id, drone_result in per_drone_results.items():
                category = drone_result.get("category", "error") if isinstance(drone_result, dict) else "error"
                if category == "accepted":
                    accepted_hw_ids.append(str(hw_id))
                else:
                    failed_hw_ids.append(str(hw_id))

            accepted_targets = [target for target in live_targets if str(target["hw_id"]) in set(accepted_hw_ids)]
            verified_synced, verification_failed = await deps._verify_sync_targets(
                accepted_targets,
                expected_branch=str(job.get("target_branch") or ""),
                expected_commit=str(job.get("target_commit") or ""),
            )
            hw_to_pos = {str(target["hw_id"]): int(target.get("pos_id", 0) or 0) for target in live_targets}
            immediate_failed = {
                hw_to_pos.get(str(hw_id), 0)
                for hw_id in failed_hw_ids
                if hw_to_pos.get(str(hw_id), 0)
            }
            failed = sorted(immediate_failed.union(set(verification_failed)))
            synced = verified_synced
            job["applied"] = True
            job["applied_at"] = int(time.time() * 1000)
            deps._sync_state["results"] = {"synced": synced, "failed": failed}
            total_attempted = len(live_targets)
            success = total_attempted > 0 and len(synced) == total_attempted
            message = (
                f"Sync verified: {len(synced)} of {total_attempted} drones now match GCS"
                if success
                else f"Sync partially verified: {len(synced)} of {total_attempted} drones updated; {len(failed)} failed or timed out"
            )
            return SyncReposResponse(
                success=success,
                message=message,
                synced_drones=synced,
                failed_drones=failed,
                total_attempted=total_attempted,
                target_branch=job.get("target_branch"),
                target_commit=job.get("target_commit"),
            )
        except HTTPException:
            raise
        except Exception as exc:
            deps.log_system_error(f"Fleet git sync apply failed: {exc}", "git")
            return SyncReposResponse(
                success=False,
                message=f"Sync operation failed: {exc}",
                synced_drones=[],
                failed_drones=[],
                total_attempted=0,
                target_branch=job.get("target_branch"),
                target_commit=job.get("target_commit"),
            )
        finally:
            deps._sync_state["active"] = False

    @router.post("/api/v1/git/sync-operations", response_model=SyncReposResponse, tags=["Git"])
    async def sync_repos(sync_request: SyncReposRequest):
        """Deprecated direct sync endpoint. Use Fleet Ops dry-run/apply."""
        return SyncReposResponse(
            success=False,
            message="Direct sync is disabled. Use Fleet Ops Git Sync dry-run and explicit apply.",
            synced_drones=[],
            failed_drones=[],
            total_attempted=0,
            target_branch=None,
            target_commit=None,
        )

    @router.websocket("/ws/git-status")
    async def websocket_git_status(websocket: WebSocket):
        """Stream the same git-status payload shape exposed by GET /api/v1/git/status."""
        if await authorize_websocket(websocket) is None:
            return
        await websocket.accept()
        deps.log_system_event("Git status WebSocket client connected", "INFO", "websocket")

        try:
            while True:
                try:
                    data = _build_git_status_response(deps).model_dump()
                except Exception:
                    data = {
                        "git_status": {},
                        "total_drones": 0,
                        "synced_count": 0,
                        "needs_sync_count": 0,
                        "gcs_status": None,
                        "sync_in_progress": False,
                    }

                message = GitStatusStreamMessage(
                    type="git_status",
                    timestamp=int(time.time() * 1000),
                    data=data,
                    sync_in_progress=data.get("sync_in_progress", False),
                )
                await websocket.send_json(message.model_dump())
                await asyncio.sleep(5.0)
        except WebSocketDisconnect:
            deps.log_system_event("Git status WebSocket client disconnected", "INFO", "websocket")
        except Exception as exc:
            deps.log_system_error(f"Git status WebSocket error: {exc}", "websocket")

    return router
