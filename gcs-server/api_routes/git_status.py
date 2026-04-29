"""Git status and repo sync routes for the GCS FastAPI app."""

import asyncio
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth_runtime import authorize_websocket
from git_status import commits_match
from schemas import (
    DroneConnectivityRuntimeStatus,
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

            mavlink_runtime = None
            if raw_mavlink_runtime:
                dashboard_enabled = bool(raw_mavlink_runtime.get("dashboard_enabled", False))
                access = (
                    {"dashboard_access_mode": "disabled", "dashboard_url": None}
                    if not dashboard_enabled
                    else resolve_dashboard_access(drone_ip, raw_mavlink_runtime.get("dashboard_listen"))
                )
                mavlink_runtime = DroneMavlinkRuntimeStatus(
                    status_source=raw_mavlink_runtime.get("status_source", "unknown"),
                    management_mode=raw_mavlink_runtime.get("management_mode", "unknown"),
                    ref=raw_mavlink_runtime.get("ref", "unknown"),
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
                )

            connectivity_runtime = None
            if raw_connectivity_runtime:
                access = resolve_dashboard_access(drone_ip, raw_connectivity_runtime.get("dashboard_listen"))
                connectivity_runtime = DroneConnectivityRuntimeStatus(
                    status_source=raw_connectivity_runtime.get("status_source", "unknown"),
                    backend=raw_connectivity_runtime.get("backend", "unknown"),
                    ref=raw_connectivity_runtime.get("ref", "unknown"),
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
                    requirements_update_status=raw_git_sync_runtime.get("requirements_update_status", "unknown"),
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

    timeout = float(getattr(deps.Params, "TELEMETRY_POLLING_TIMEOUT", 30.0) or 30.0)
    now = time.time()
    online_hw_ids: set[str] = set()

    for hw_id, heartbeat in heartbeats.items():
        if not isinstance(heartbeat, dict):
            continue
        timestamp = heartbeat.get("timestamp")
        try:
            heartbeat_age_sec = now - (float(timestamp) / 1000.0)
        except (TypeError, ValueError):
            continue
        if 0 <= heartbeat_age_sec < timeout:
            online_hw_ids.add(str(hw_id))

    return online_hw_ids


def create_git_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/git/status", response_model=GitStatusResponse, tags=["Git"])
    async def get_git_status():
        """Get git status from all drones."""
        return _build_git_status_response(deps)

    @router.post("/api/v1/git/sync-operations", response_model=SyncReposResponse, tags=["Git"])
    async def sync_repos(sync_request: SyncReposRequest):
        """Sync git repositories on target drones by dispatching UPDATE_CODE."""
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

        try:
            deps._sync_state["active"] = True
            deps._sync_state["started_at"] = time.time()
            deps._sync_state["results"] = None

            gcs_status = deps.get_gcs_git_report()
            branch = (gcs_status or {}).get("branch") or getattr(deps.Params, "GIT_BRANCH", "main")
            expected_commit = (gcs_status or {}).get("commit", "")
            command_data = {
                "mission_type": 103,
                "trigger_time": 0,
                "update_branch": branch,
            }

            drones_config = deps.load_config()
            target_drones, skipped_offline = deps._select_sync_target_drones(drones_config, sync_request.pos_ids)

            if not target_drones:
                return SyncReposResponse(
                    success=False,
                    message="No eligible target drones found for sync",
                    synced_drones=[],
                    failed_drones=skipped_offline,
                    total_attempted=0,
                    target_branch=branch,
                    target_commit=expected_commit,
                )

            if sync_request.pos_ids:
                target_hw_ids = [str(drone["hw_id"]) for drone in target_drones]
                results = deps.send_commands_to_selected(drones_config, command_data, target_hw_ids)
            else:
                results = deps.send_commands_to_all(drones_config, command_data)

            accepted_hw_ids = []
            failed_hw_ids = []
            hw_to_pos = {str(drone["hw_id"]): int(drone.get("pos_id", drone["hw_id"])) for drone in drones_config}
            per_drone_results = results.get("results", {})
            for hw_id, drone_result in per_drone_results.items():
                category = drone_result.get("category", "error") if isinstance(drone_result, dict) else "error"
                if category == "accepted":
                    accepted_hw_ids.append(str(hw_id))
                else:
                    failed_hw_ids.append(str(hw_id))

            if not per_drone_results:
                success_count = results.get("success", 0)
                total_count = results.get("total", 0)
                if success_count > 0:
                    accepted_hw_ids = [str(drone["hw_id"]) for drone in target_drones[:success_count]]
                if total_count > success_count:
                    failed_hw_ids = [str(drone["hw_id"]) for drone in target_drones[success_count:]]

            accepted_targets = [drone for drone in target_drones if str(drone["hw_id"]) in set(accepted_hw_ids)]
            verified_synced, verification_failed = await deps._verify_sync_targets(
                accepted_targets,
                expected_branch=branch,
                expected_commit=expected_commit,
            )

            immediate_failed = {
                hw_to_pos.get(str(hw_id), 0)
                for hw_id in failed_hw_ids
                if hw_to_pos.get(str(hw_id), 0)
            }
            failed = sorted(immediate_failed.union(set(verification_failed)))
            synced = verified_synced

            deps._sync_state["results"] = {"synced": synced, "failed": failed}

            total_attempted = len(target_drones)
            skipped_count = len(skipped_offline)
            verified_count = len(synced)
            failed_count = len(failed)
            success = total_attempted > 0 and verified_count == total_attempted

            if success:
                message = f"Sync verified: {verified_count} of {total_attempted} drones now match GCS"
            elif verified_count > 0:
                message = (
                    f"Sync partially verified: {verified_count} of {total_attempted} drones updated; "
                    f"{failed_count} failed or timed out"
                )
            else:
                message = f"Sync failed: 0 of {total_attempted} drones matched GCS after dispatch"

            if skipped_count > 0 and not sync_request.pos_ids:
                message += f" ({skipped_count} offline config entries skipped)"

            return SyncReposResponse(
                success=success,
                message=message,
                synced_drones=synced,
                failed_drones=failed,
                total_attempted=total_attempted,
                target_branch=branch,
                target_commit=expected_commit,
            )
        except Exception as exc:
            deps.log_system_error(f"Sync repos failed: {exc}", "git")
            return SyncReposResponse(
                success=False,
                message=f"Sync operation failed: {exc}",
                synced_drones=[],
                failed_drones=[],
                total_attempted=0,
                target_branch=None,
                target_commit=None,
            )
        finally:
            deps._sync_state["active"] = False

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
