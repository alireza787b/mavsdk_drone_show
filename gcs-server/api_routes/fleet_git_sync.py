"""Preview, apply, and reattach to reviewed fleet software updates."""

import asyncio
import hashlib
import hmac
import os
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from command_execution_policy import CommandSubmissionAuthority
from command_submission import submit_tracked_command
from command_tracker import CommandCompletionAuthority
from fleet_git_operations import ACTIVE_PHASES, GitOperationStore, GitUpdateStatus, update_phase
from schemas import FleetGitSyncApplyResponse, SubmitCommandRequest
from src.enums import Mission

FLEET_OPS_MUTATION_TOKEN_ENV = "MDS_FLEET_OPS_MUTATION_TOKEN"


class FleetGitSyncDryRunRequest(BaseModel):
    hw_ids: list[str] | None = None
    pos_ids: list[int] | None = None
    include_offline: bool = False


class GitSyncActionConfirmation(BaseModel):
    operator: str | None = None
    acknowledged_risks: bool = False
    confirmation_token: str | None = None


class FleetGitSyncApplyRequest(BaseModel):
    dry_run_id: str
    confirmation: GitSyncActionConfirmation


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


def _legacy_receipt(status):
    rows = status["per_aircraft_state"].values()
    synced = sorted(row["pos_id"] for row in rows if row["state"] == "verified")
    failed = sorted(row["pos_id"] for row in rows if row["state"] == "unconfirmed")
    return FleetGitSyncApplyResponse(success=status["phase"] == "completed", message=status["message"],
                                     synced_drones=synced, failed_drones=failed, total_attempted=len(synced)+len(failed),
                                     target_branch=status["target_branch"], target_commit=status["target_commit"])


async def _wait_for_tracked_dispatch(deps: Any, command_id: str) -> dict[str, Any] | None:
    """Wait only for bounded dispatch classification, never mission completion."""

    timeout_sec = max(
        1.0,
        min(
            60.0,
            float(getattr(deps.Params, "GCS_FLEET_DISPATCH_DEADLINE_SEC", 15.0))
            + float(getattr(deps.Params, "GCS_COMMAND_HTTP_TIMEOUT_SEC", 5.0))
            + 2.0,
        ),
    )
    deadline = time.monotonic() + timeout_sec
    tracker = deps.get_command_tracker()
    last_status = None
    while time.monotonic() < deadline:
        last_status = await tracker.get_status(command_id)
        if last_status is None:
            return None
        phase = str(last_status.get("phase") or "")
        acks = last_status.get("acks") or {}
        if phase == "terminal" or int(acks.get("received", 0)) >= int(
            acks.get("expected", 0)
        ):
            return last_status
        await asyncio.sleep(0.1)
    return last_status


def create_fleet_git_sync_router(deps, prepare_preview, check_preview) -> APIRouter:
    router = APIRouter()
    # The status feed remains available when the durable maintenance store is offline.
    # Only a preview, apply, or receipt lookup opens this store.
    journal = None
    journal_lock = threading.Lock()
    workers = set()

    def get_journal():
        nonlocal journal
        with journal_lock:
            if journal is None:
                journal = GitOperationStore(deps.Params)
            return journal

    @router.post("/api/v1/fleet/git-sync/dry-run", tags=["Git"])
    async def dry_run_fleet_git_sync(sync_request: FleetGitSyncDryRunRequest, http_request: Request):
        _require_mutation_authority(http_request)

        def prepare():
            preview = prepare_preview(deps, sync_request)
            return {**preview, **get_journal().create(preview)}

        return await asyncio.to_thread(prepare)

    @router.get("/api/v1/fleet/git-sync/operations/{operation_id}", response_model=GitUpdateStatus, tags=["Git"])
    async def git_update_status(operation_id: str):
        record = await asyncio.to_thread(lambda: get_journal().lookup(operation_id))
        return record["status"]

    async def execute(record, lease):
        store = get_journal()
        status, targets = record["status"], record["targets"]
        async def save(phase, message, **details):
            update_phase(record, phase, message, **details)
            await asyncio.to_thread(store.save, record)
        try:
            receipt = await submit_tracked_command(
                deps, SubmitCommandRequest(mission_type=Mission.UPDATE_CODE.value, trigger_time=0,
                    update_branch=status["target_branch"], target_drone_ids=[t["hw_id"] for t in targets],
                    idempotency_key=f"fleet-git-sync:{status['operation_id']}"),
                authority=CommandSubmissionAuthority.FLEET_OPS_GIT_SYNC,
            )
            tracker = deps.get_command_tracker()
            capabilities = await tracker.get_callback_capabilities(receipt.command_id)
            await _wait_for_tracked_dispatch(deps, receipt.command_id)
            await save("verifying", "Checking aircraft revisions")
            async def progress(verified):
                await save("verifying", "Checking aircraft revisions", verified=verified)
            verified, _ = await deps._verify_sync_targets(targets, expected_branch=status["target_branch"],
                                                          expected_commit=status["target_commit"], on_verified=progress)
            verified = set(map(str, verified))
            completion = {t["hw_id"]: {"success": t["hw_id"] in verified, "error_message": None if t["hw_id"] in verified
                          else "Could not verify the reviewed revision and clean worktree before the deadline"} for t in targets}
            await tracker.record_authoritative_completion(receipt.command_id, completion,
                completion_authority=CommandCompletionAuthority.FLEET_GIT_POSTCONDITION, callback_capabilities=capabilities)
            phase = "completed" if len(verified) == len(targets) else "partial" if verified else "failed"
            await save(phase, f"Verified {len(verified)} of {len(targets)} aircraft", verified=verified,
                       error_code=None if phase == "completed" else "verification_timeout")
            result = _legacy_receipt(status)
            deps._sync_state["results"] = {"synced": result.synced_drones, "failed": result.failed_drones}
        except asyncio.CancelledError:
            await save("interrupted", "Update interrupted. Check aircraft software.", error_code="gcs_interrupted")
            raise
        except Exception as exc:
            deps.log_system_error(f"Fleet Git update {status['operation_id']} failed: {type(exc).__name__}", "git")
            await save("failed", "Update could not be confirmed. Check aircraft software.", error_code="update_unconfirmed")
        finally:
            deps._sync_state["active"] = False
            os.close(lease)
        return status

    @router.post("/api/v1/fleet/git-sync/apply", response_model=FleetGitSyncApplyResponse | GitUpdateStatus, tags=["Git"])
    async def apply_fleet_git_sync(sync_request: FleetGitSyncApplyRequest, http_request: Request, background: bool = False):
        _require_mutation_authority(http_request)
        op = sync_request.dry_run_id
        store = await asyncio.to_thread(get_journal)
        task = None
        async with deps._sync_lock:
            record = await asyncio.to_thread(store.lookup, op)
            status = record["status"]
            supplied = sync_request.confirmation
            if not supplied.acknowledged_risks or not hmac.compare_digest(
                    hashlib.sha256((supplied.confirmation_token or "").encode()).hexdigest(), record["proof"]):
                raise HTTPException(400, "A confirmed preview is required")
            if status["phase"] == "expired":
                raise HTTPException(409, status["message"])
            if status["phase"] == "review":
                lease = store.try_lease()
                if lease is None or deps._sync_state["active"]:
                    if lease is not None:
                        os.close(lease)
                    raise HTTPException(409, "Another update is in progress")
                try:
                    # Re-read under the cross-process lease before claiming a write.
                    record = await asyncio.to_thread(lambda: store.reconcile(store.read(op)))
                    status = record["status"]
                    if status["phase"] == "review":
                        try:
                            await asyncio.to_thread(check_preview, deps, record)
                        except HTTPException as error:
                            if error.status_code == 409:
                                update_phase(record, "expired", str(error.detail), error_code="preview_changed")
                                await asyncio.to_thread(store.save, record)
                            raise
                        update_phase(record, "applying", "Updating aircraft")
                        await asyncio.to_thread(store.save, record)
                        deps._sync_state.update(active=True, started_at=time.time(), results=None)
                        task = asyncio.create_task(execute(record, lease))
                        workers.add(task)
                        task.add_done_callback(workers.discard)
                        lease = None  # Ownership passes to the worker.
                    elif status["phase"] == "expired":
                        raise HTTPException(409, status["message"])
                finally:
                    if lease is not None:
                        os.close(lease)

        if background:
            return JSONResponse(status_code=202 if status["phase"] in ACTIVE_PHASES else 200, content=status)
        if task:
            status = await asyncio.shield(task)
        while status["phase"] in ACTIVE_PHASES:
            await asyncio.sleep(0.5)
            status = (await asyncio.to_thread(store.lookup, op))["status"]
        return _legacy_receipt(status)

    return router
