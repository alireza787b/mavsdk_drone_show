"""Git status and repo sync routes for the GCS FastAPI app."""

import asyncio
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from git_status import commits_match
from schemas import (
    DroneGitStatus,
    GitStatus,
    GitStatusResponse,
    GitStatusStreamMessage,
    SyncReposRequest,
    SyncReposResponse,
)


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

            transformed_git_status[str(hw_id)] = DroneGitStatus(
                pos_id=int(drone_info.get("pos_id", hw_id)),
                hw_id=str(hw_id),
                ip=drone_info.get("ip", "unknown"),
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
                last_check=int(time.time() * 1000),
                last_sync=None,
            )

    synced_count = len([status for status in transformed_git_status.values() if status.in_sync_with_gcs])

    return GitStatusResponse(
        git_status=transformed_git_status,
        total_drones=len(transformed_git_status),
        synced_count=synced_count,
        needs_sync_count=len(transformed_git_status) - synced_count,
        gcs_status=gcs_status,
        sync_in_progress=deps._sync_state["active"],
        timestamp=int(time.time() * 1000),
    )


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
            branch = (gcs_status or {}).get("branch") or getattr(deps.Params, "GIT_BRANCH", "main-candidate")
            expected_commit = (gcs_status or {}).get("commit", "")
            command_data = {
                "mission_type": 103,
                "trigger_time": 0,
                "update_branch": branch,
            }

            drones_config = deps.load_config()
            target_drones, skipped_offline = deps._select_sync_target_drones(drones_config, sync_request.pos_ids)
            if sync_request.pos_ids:
                command_data["pos_ids"] = sync_request.pos_ids

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
