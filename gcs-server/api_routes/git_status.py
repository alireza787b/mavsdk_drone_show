"""Git status and repo sync routes for the GCS FastAPI app."""

import secrets
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket
from fastapi.responses import JSONResponse

from auth_runtime import authorize_websocket
from observation_stream import LatestObservationPublisher, serve_observations
from api_routes.fleet_git_sync import FleetGitSyncDryRunRequest, create_fleet_git_sync_router
from fleet_git_operations import now_ms
from git_status import commits_match, tracking_count
from presence import build_presence_snapshot, resolve_presence_thresholds
from overview_display_policy import resolve_overview_display_policy
from schemas import (
    DroneConnectivityRuntimeStatus,
    DroneEnvRuntimeStatus,
    DroneGitStatus,
    DroneGitSyncRuntimeStatus,
    DroneMavlinkRuntimeStatus,
    GitStatus,
    GitStatusResponse,
    GitStatusSnapshotResponse,
)
from src.managed_runtime_status import resolve_dashboard_access

GIT_SYNC_SCHEMA = "mds.fleet_git_sync.v1"


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
    transformed_git_status = {}
    branch_only_count = 0
    reviewable_hw_ids = _resolve_reviewable_hw_ids(deps)

    with deps.data_lock_git_status:
        reports = {str(key): value for key, value in deps.git_status_data_all_drones.items()}
    for hw_id in (reviewable_hw_ids or set()) & drone_map.keys():
        reports.setdefault(hw_id, {})

    for hw_id, raw_data in reports.items():
        drone_info = drone_map.get(hw_id, {})
        raw_data = raw_data or {}
        mapped_status, in_sync_with_gcs = _git_row_status(raw_data, gcs_status, deps.Params)
        commit_hash = raw_data.get("commit") or "unknown"
        reviewable = reviewable_hw_ids is None or hw_id in reviewable_hw_ids
        if (reviewable and in_sync_with_gcs and gcs_branch
                and raw_data.get("branch") not in (None, "", "unknown", gcs_branch)):
            branch_only_count += 1

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
                phase=raw_git_sync_runtime.get("phase", "unknown"),
                phase_message=raw_git_sync_runtime.get("phase_message", ""),
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
            reviewable=reviewable,
            maintenance_drift=_maintenance_drift(mavlink_runtime, connectivity_runtime, git_sync_runtime),
            commits_ahead=max(0, _safe_int(raw_data.get("commits_ahead"))),
            commits_behind=max(0, _safe_int(raw_data.get("commits_behind"))),
            uncommitted_changes=raw_data.get("uncommitted_changes", []),
            repo_access_mode=raw_data.get("repo_access_mode", "custom_or_unknown"),
            git_auth_health_status=raw_data.get("git_auth_health_status", "unknown"),
            git_auth_health_summary=raw_data.get("git_auth_health_summary"),
            git_auth_health_issues=raw_data.get("git_auth_health_issues", []),
            mavlink_runtime=mavlink_runtime,
            connectivity_runtime=connectivity_runtime,
            git_sync_runtime=git_sync_runtime,
            env_runtime=env_runtime,
            last_check=raw_data.get("last_check", 0),
            last_sync=None,
        )

    reviewable_statuses = [
        status
        for hw_id, status in transformed_git_status.items()
        if reviewable_hw_ids is None or hw_id in reviewable_hw_ids
    ]
    synced_count = len([status for status in reviewable_statuses if status.in_sync_with_gcs])
    unknown_count = sum(status.status == GitStatus.UNKNOWN for status in reviewable_statuses)

    return GitStatusResponse(
        git_status=transformed_git_status,
        total_drones=len(transformed_git_status),
        synced_count=synced_count,
        needs_sync_count=len(reviewable_statuses) - synced_count - unknown_count,
        unknown_count=unknown_count,
        branch_only_count=branch_only_count,
        maintenance_count=sum(row.maintenance_drift for row in reviewable_statuses),
        attention_count=sum(not row.in_sync_with_gcs or row.maintenance_drift for row in reviewable_statuses),
        gcs_status=gcs_status,
        sync_in_progress=deps._sync_state["active"],
        timestamp=int(time.time() * 1000),
    )


def _resolve_reviewable_hw_ids(deps: Any) -> set[str] | None:
    """Retain source attention through Overview's brief-loss display window.

    This does not grant update eligibility: mutation routes retain their fresh
    native/heartbeat checks. Missing presence evidence must not clear a notice.
    """
    provider = getattr(deps, 'get_all_heartbeats', None)
    if provider is None:
        return None  # Compatibility with adapters without heartbeat discovery.
    try:
        heartbeats = provider()
    except Exception as exc:
        raise HTTPException(status_code=503, detail='Aircraft presence unavailable') from exc

    if not isinstance(heartbeats, dict):
        raise HTTPException(status_code=503, detail='Aircraft presence unavailable')
    if not heartbeats:
        return set()

    now = time.time()
    thresholds = resolve_presence_thresholds(deps.Params)
    review_window = resolve_overview_display_policy(deps.Params)['available_sec']
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
        age = snapshot.get('heartbeat_age_sec')
        if age is not None and age < review_window:
            online_hw_ids.add(str(hw_id))

    return online_hw_ids


def _safe_heartbeats(deps: Any) -> dict[str, dict[str, Any]]:
    try:
        heartbeats = deps.get_all_heartbeats()
    except Exception as exc:
        raise HTTPException(503, "Aircraft presence unavailable") from exc
    if not isinstance(heartbeats, dict):
        raise HTTPException(503, "Aircraft presence unavailable")
    return {str(key): value for key, value in heartbeats.items() if isinstance(value, dict)}


def _presence_for_hw_id(deps: Any, hw_id: str, heartbeats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    heartbeat = heartbeats.get(str(hw_id), {})
    if str(heartbeat.get("hw_id", hw_id)) != hw_id:
        return {"state": "unknown", "fresh": False, "last_seen_ms": None}
    if not heartbeat.get("timestamp") and heartbeat.get("last_heartbeat"):
        heartbeat = {**heartbeat, "timestamp": heartbeat["last_heartbeat"]}
    # Timestamp-only records can be in seconds or milliseconds. Prefer the time the GCS received the heartbeat.
    snapshot = build_presence_snapshot(hw_id=hw_id, heartbeat=heartbeat, thresholds=resolve_presence_thresholds(deps.Params))
    received = snapshot.get("last_seen_ms")
    if not received:
        return {"state": "unknown", "fresh": False, "last_seen_ms": None}
    age = (now_ms() - received) / 1000.0
    timeout = float(getattr(deps.Params, "TELEMETRY_POLLING_TIMEOUT", 5) or 5)
    fresh = 0 <= age < timeout
    return {"state": "online" if fresh else "offline", "fresh": fresh,
            "last_seen_ms": received, "age_seconds": round(age, 1)}


def _git_row_status(raw_data: dict[str, Any], gcs_status: dict[str, Any] | None, params: Any) -> tuple[GitStatus, bool]:
    """Compare reported revisions independently of the two checkout branch names."""
    # An online heartbeat cannot refresh an older repository observation.
    last_check = _safe_int(raw_data.get("last_check"))
    max_age = 2 * getattr(params, "git_poll_interval", 10) + getattr(params, "GCS_GIT_STATUS_REQUEST_TIMEOUT_SEC", 5)
    if last_check and time.time() - last_check / 1000 > max_age:
        return GitStatus.UNKNOWN, False
    raw_status = raw_data.get("status")
    ahead = tracking_count(raw_data, "commits_ahead")
    behind = tracking_count(raw_data, "commits_behind")
    commit = raw_data.get("commit")
    target = (gcs_status or {}).get("commit")
    if (not commit or not target or "unknown" in (commit, target)
            or min(ahead, behind) < 0 or raw_status in (None, "unknown")):
        return GitStatus.UNKNOWN, False
    if raw_status == "dirty" or raw_data.get("uncommitted_changes"):
        return GitStatus.DIRTY, False
    if ahead and behind:
        return GitStatus.DIVERGED, False
    if ahead:
        return GitStatus.AHEAD, False
    if behind:
        return GitStatus.BEHIND, False
    if raw_status in ("clean", "synced"):
        return GitStatus.SYNCED, commits_match(commit, target)
    try:
        return GitStatus(raw_status), False
    except ValueError:
        return GitStatus.UNKNOWN, False


def _maintenance_drift(mavlink, connectivity, sync) -> bool:
    """Only raise a maintenance notice from an explicit mismatch or failure."""
    if mavlink and mavlink.management_mode not in ("none", "disabled", "manual") and mavlink.config_hash_match is False:
        return True
    if connectivity and connectivity.backend != "none" and connectivity.config_hash_match is False:
        return True
    if not sync:
        return False
    outcomes = (sync.status, sync.service_reload_status, sync.mavsdk_runtime_status,
                sync.mavlink_runtime_reconcile_status, sync.connectivity_reconcile_status)
    return (any(value in {"warning", "failed", "error", "unhealthy", "degraded"} for value in outcomes)
            or any("manual_unit_update_required" in action for action in sync.deferred_unit_actions))


def _build_fleet_git_sync_table(deps: Any) -> dict[str, Any]:
    drones_config = deps.load_config()
    try:
        gcs_status = deps.get_gcs_git_report()
    except Exception:
        gcs_status = None
    heartbeats = _safe_heartbeats(deps)
    rows = []
    with deps.data_lock_git_status:
        git_snapshot = {str(key): value for key, value in deps.git_status_data_all_drones.items()}
    for drone in drones_config:
        hw_id = str(drone.get("hw_id"))
        raw_data = git_snapshot.get(hw_id, {}) or {}
        status, in_sync = _git_row_status(raw_data, gcs_status, deps.Params)
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
        "needs_sync_count": sum(row["presence"]["fresh"] and row["status"] != GitStatus.UNKNOWN and not row["in_sync_with_gcs"] for row in rows),
        "unknown_count": sum(row["presence"]["fresh"] and row["status"] == GitStatus.UNKNOWN for row in rows),
        "timestamp": int(time.time() * 1000),
        "gcs_status": gcs_status,
    }


def _configured_git_targets(deps: Any) -> dict[str, dict]:
    rows = deps.load_config()
    indexed = {str(row["hw_id"]): {"hw_id": str(row["hw_id"]), "pos_id": int(row["pos_id"]), "ip": row.get("ip")}
               for row in rows}
    if len(indexed) != len(rows):
        raise HTTPException(409, "Duplicate hardware identity in fleet configuration")
    return indexed


def _target_revision(deps: Any) -> tuple[str, str]:
    try:
        gcs = deps.get_gcs_git_report() or {}
    except Exception:
        gcs = {}
    return str(gcs.get("branch") or ""), str(gcs.get("commit") or "")


def _target_evidence(deps: Any, targets, branch: str, commit: str) -> dict:
    with deps.data_lock_git_status:
        software = {str(hw): report for hw, report in deps.git_status_data_all_drones.items()}
    heartbeats = _safe_heartbeats(deps)
    results = {}
    for target in targets:
        hw = target["hw_id"]
        presence = _presence_for_hw_id(deps, hw, heartbeats)
        report = software.get(hw) or {}
        error_code = None
        if not presence["fresh"]:
            error_code = "offline"
        elif not branch or branch == "unknown" or not commits_match(commit, commit):
            error_code = "gcs_revision_unknown"
        elif (_git_row_status(report, {"commit": commit}, deps.Params)[0] == GitStatus.UNKNOWN
                or report.get("error")
                or str(report.get("hw_id", hw)) != hw):
            error_code = "version_unknown"
        results[hw] = {**target, "presence": presence, "ok": error_code is None, "error_code": error_code}
        if error_code:
            results[hw]["error"] = {"offline": "Aircraft offline", "version_unknown": "Version unavailable",
                                    "gcs_revision_unknown": "GCS version unavailable"}[error_code]
        else:
            results[hw].update(planned_command="UPDATE_CODE", target_branch=branch, target_commit=commit, warnings=[])
    return results


def _build_git_sync_dry_run(deps: Any, request_payload: FleetGitSyncDryRunRequest) -> dict[str, Any]:
    by_hw = _configured_git_targets(deps)
    if request_payload.pos_ids is not None and request_payload.hw_ids is not None:
        raise HTTPException(422, "Choose either hardware IDs or position IDs")
    if request_payload.hw_ids is not None:
        requested = set(request_payload.hw_ids)
        if requested - by_hw.keys():
            raise HTTPException(409, "Selected aircraft configuration has changed")
        targets = [v for k, v in by_hw.items() if k in requested]
    elif request_payload.pos_ids is not None:
        positions = set(request_payload.pos_ids)
        targets = [t for t in by_hw.values() if t["pos_id"] in positions]
        if {t["pos_id"] for t in targets} != positions:
            raise HTTPException(409, "Selected aircraft configuration has changed")
    else:
        targets = list(by_hw.values())

    branch, commit = _target_revision(deps)
    results = _target_evidence(deps, targets, branch, commit)
    operation_id = f"git-sync-{uuid.uuid4().hex}"
    return {"schema": GIT_SYNC_SCHEMA, "job_id": operation_id, "kind": "git-sync-dry-run",
            "target_branch": branch, "target_commit": commit, "results": results,
            "targets": [target for target in targets if results[target["hw_id"]]["ok"]],
            "created_at": now_ms(), "applied": False, "confirmation_token": secrets.token_urlsafe(32)}


def _check_review(deps, record):
    """Dispatch only the exact identities, positions, endpoints and revision the operator reviewed."""
    status, targets = record["status"], record["targets"]
    if not targets:
        raise HTTPException(409, "No eligible aircraft in this preview")
    branch, commit = _target_revision(deps)
    if (branch, commit) != (status["target_branch"], status["target_commit"]):
        raise HTTPException(409, "GCS revision changed. Review aircraft again.")
    current = _configured_git_targets(deps)
    if any(current.get(t["hw_id"]) != t for t in targets):
        raise HTTPException(409, "Aircraft identity or endpoint changed. Review aircraft again.")
    if not all(row["ok"] for row in _target_evidence(deps, targets, branch, commit).values()):
        raise HTTPException(409, "Aircraft presence or version changed. Review aircraft again.")


def create_git_router(deps: Any) -> APIRouter:
    router = APIRouter()
    publisher = LatestObservationPublisher(
        lambda: _build_git_status_response(deps).model_dump(mode="json"),
        lambda body: {
            "type": "git_status", "timestamp": body["timestamp"], "data": body,
            "sync_in_progress": body["sync_in_progress"],
        },
        interval=5.0,
    )

    @router.get("/api/v1/git/status", response_model=GitStatusSnapshotResponse | GitStatusResponse, tags=["Git"])
    async def get_git_status(protocol_version: int = Query(0, ge=0, le=1)):
        """Get git status from all drones."""
        if protocol_version == 1:
            return JSONResponse(publisher.current().http_body())
        return _build_git_status_response(deps)

    @router.get("/api/v1/fleet/git-sync", tags=["Git"])
    async def get_fleet_git_sync_table():
        """Return Fleet Ops git-sync table state without mutating drones."""
        return _build_fleet_git_sync_table(deps)

    router.include_router(create_fleet_git_sync_router(deps, _build_git_sync_dry_run, _check_review))

    @router.websocket("/ws/git-status")
    async def websocket_git_status(websocket: WebSocket):
        """Stream the same git-status payload shape exposed by GET /api/v1/git/status."""
        auth_context = await authorize_websocket(websocket)
        if auth_context is None:
            return
        await websocket.accept()
        deps.log_system_event("Git status WebSocket client connected", "INFO", "websocket")

        try:
            await serve_observations(websocket, publisher, auth_context=auth_context)
        finally:
            deps.log_system_event("Git status WebSocket client disconnected", "INFO", "websocket")

    return router
