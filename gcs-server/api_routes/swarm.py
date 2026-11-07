"""Swarm configuration and leader-reassignment routes."""

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from auth_runtime import authorize_websocket
from formation_watch import FormationWatch, matches_etag

from schemas import (
    SwarmAssignment,
    SwarmAssignmentPatchRequest,
    SwarmAssignmentUpdateResponse,
    SwarmConfig,
    SwarmConfigSaveResponse,
    SwarmConfigApplyRequest,
    SwarmPublishRequest,
    SwarmCapturePreviewRequest,
    SwarmCapturePreviewResponse,
)
from src.smart_swarm_contract import topology_revision
from src.gcs_api_routes import GCS_WS_SWARM_CONFIG_ROUTE
from swarm_design_service import formation_status, validate_apply_observation
from swarm_configuration_guard import configuration_lock
from swarm_capture_service import capture_preview, inactive_scope, read_inactive_scope, recheck_inactive_scope


def _normalize_swarm_hw_id(value: Any) -> Optional[int]:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _extract_swarm_assignments(payload: Any):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("assignments"), list):
        return payload["assignments"]
    return None


def _build_swarm_config_resource(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "assignments": assignments,
        "revision": topology_revision(assignments),
    }


def _parse_swarm_config_payload(payload: Any) -> list[dict[str, Any]]:
    assignments = _extract_swarm_assignments(payload)
    if assignments is None:
        raise HTTPException(
            status_code=400,
            detail="Swarm config payload must be a list or an object with an assignments array",
        )
    if not assignments:
        raise HTTPException(status_code=400, detail="No swarm data provided")
    return assignments


def _would_create_swarm_cycle(assignments: list[dict[str, Any]], hw_id: Any, follow: Any) -> bool:
    normalized_hw_id = _normalize_swarm_hw_id(hw_id)
    normalized_follow = _normalize_swarm_hw_id(follow)
    if normalized_hw_id is None or normalized_follow is None:
        return False

    follow_map = {}
    for entry in assignments:
        entry_hw_id = _normalize_swarm_hw_id(entry.get("hw_id"))
        if entry_hw_id is None:
            continue
        try:
            follow_map[entry_hw_id] = int(entry.get("follow", 0))
        except (TypeError, ValueError):
            follow_map[entry_hw_id] = 0

    follow_map[normalized_hw_id] = normalized_follow

    visited = {normalized_hw_id}
    current = normalized_follow
    while current > 0:
        if current in visited:
            return True
        visited.add(current)
        current = int(follow_map.get(current, 0) or 0)

    return False


def _validate_swarm_cycle_constraints(payload: Any) -> None:
    assignments = _extract_swarm_assignments(payload)
    if assignments is None:
        return

    known_hw_ids = {
        _normalize_swarm_hw_id(entry.get("hw_id"))
        for entry in assignments
    }
    known_hw_ids.discard(None)
    if len(known_hw_ids) != len(assignments):
        raise HTTPException(status_code=400, detail="Swarm hardware IDs must be unique and positive")

    for entry in assignments:
        hw_id = _normalize_swarm_hw_id(entry.get("hw_id"))
        try:
            follow = int(entry.get("follow", 0))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="follow must be zero or a valid leader hw_id") from exc

        if hw_id is None:
            raise HTTPException(status_code=400, detail="Each swarm assignment requires a valid positive hw_id")
        if follow < 0:
            raise HTTPException(status_code=400, detail="follow must be zero or a valid leader hw_id")
        if follow == hw_id:
            raise HTTPException(status_code=400, detail=f"A drone cannot follow itself (hw_id={hw_id})")
        if follow > 0 and follow not in known_hw_ids:
            raise HTTPException(status_code=400, detail=f"Leader hw_id={follow} is not present in swarm config")
        if _would_create_swarm_cycle(assignments, hw_id, follow):
            raise HTTPException(status_code=400, detail=f"Follow update would create a cycle for hw_id={hw_id}")


def _swarm_git_result_failed(git_result: Any) -> bool:
    return isinstance(git_result, dict) and git_result.get("success") is False


def _swarm_git_result_not_pushed(git_result: Any) -> bool:
    if not isinstance(git_result, dict) or git_result.get("success") is False:
        return False
    return git_result.get("pushed") is False or git_result.get("auto_push_enabled") is False


def _build_swarm_save_message(should_commit: bool, git_result: Any) -> tuple[str, str, str]:
    if not should_commit:
        return "success", "Swarm configuration saved locally", "INFO"

    if _swarm_git_result_failed(git_result):
        message = "Swarm configuration saved locally, but git commit/push failed"
        if git_result.get("message"):
            message = f"{message}: {git_result['message']}"
        return "git_failed", message, "WARNING"

    if _swarm_git_result_not_pushed(git_result):
        message = "Swarm configuration saved and committed locally, but it was not pushed to remote"
        if isinstance(git_result, dict) and git_result.get("message"):
            message = git_result["message"]
        return "git_not_pushed", message, "WARNING"

    if isinstance(git_result, dict) and git_result.get("message"):
        return "success", git_result["message"], "INFO"

    return "success", "Swarm configuration saved and committed successfully", "INFO"


def _apply_swarm_assignment_patch(deps: Any, hw_id: int, data: dict[str, Any]) -> dict[str, Any]:
    try:
        # Offset/frame-only edits must preserve the existing relationship.
        # Defaulting an omitted follow field to 0 silently promotes a follower.
        existing_swarm = deps.load_swarm()
        existing = next((entry for entry in existing_swarm if int(entry.get("hw_id", 0)) == hw_id), None)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Swarm assignment for hw_id={hw_id} not found")
        follow = int(data["follow"]) if "follow" in data else int(existing.get("follow", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="follow must be zero or a valid leader hw_id") from exc

    if hw_id <= 0:
        raise HTTPException(status_code=400, detail="hw_id must be a positive integer")
    if follow < 0:
        raise HTTPException(status_code=400, detail="follow must be zero or a valid leader hw_id")
    if follow == hw_id:
        raise HTTPException(status_code=400, detail="A drone cannot follow itself")

    swarm_data = existing_swarm
    if not swarm_data:
        raise HTTPException(status_code=404, detail="Swarm configuration is empty")

    assignment_index = next(
        (idx for idx, entry in enumerate(swarm_data) if int(entry.get("hw_id", 0)) == hw_id),
        None,
    )
    if assignment_index is None:
        raise HTTPException(status_code=404, detail=f"Swarm assignment for hw_id={hw_id} not found")

    if follow != 0 and not any(int(entry.get("hw_id", 0)) == follow for entry in swarm_data):
        raise HTTPException(status_code=400, detail=f"Leader hw_id={follow} is not present in swarm config")

    updated_assignment = dict(swarm_data[assignment_index])
    updated_assignment["follow"] = follow

    projected_swarm = list(swarm_data)
    projected_swarm[assignment_index] = updated_assignment
    _validate_swarm_cycle_constraints(projected_swarm)

    try:
        if "offset_x" in data:
            updated_assignment["offset_x"] = float(data["offset_x"])
        if "offset_y" in data:
            updated_assignment["offset_y"] = float(data["offset_y"])
        if "offset_z" in data:
            updated_assignment["offset_z"] = float(data["offset_z"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="offset_x, offset_y, and offset_z must be numeric",
        ) from exc

    if "frame" in data:
        frame = str(data["frame"]).strip().lower()
        if frame not in {"ned", "body"}:
            raise HTTPException(status_code=400, detail="frame must be 'ned' or 'body'")
        updated_assignment["frame"] = frame

    swarm_data[assignment_index] = updated_assignment
    deps.save_swarm(swarm_data)
    deps.log_system_event(
        f"Smart Swarm assignment update saved for hw_id={hw_id}: follow={follow}",
        "INFO",
        "swarm",
    )
    return updated_assignment


def create_swarm_router(deps: Any) -> APIRouter:
    router = APIRouter()
    write_lock = asyncio.Lock()
    watch = FormationWatch(lambda: deps.load_swarm())

    @router.websocket(GCS_WS_SWARM_CONFIG_ROUTE)
    async def watch_swarm_config(websocket: WebSocket):
        if await authorize_websocket(websocket, machine_endpoint=True) is None:
            return
        await websocket.accept()
        try:
            async with watch.subscribe() as updates:
                while True:
                    try:
                        resource = await asyncio.wait_for(updates.get(), timeout=15)
                        message = {"type": "swarm_config", "data": resource}
                    except asyncio.TimeoutError:
                        message = {"type": "heartbeat"}
                    await asyncio.wait_for(websocket.send_json(message), timeout=5)
        except (WebSocketDisconnect, OSError, asyncio.TimeoutError, RuntimeError):
            # Slow/disconnected clients recover with a fresh snapshot, not replay.
            return

    @router.get("/api/v1/config/swarm/status", tags=["Swarm"])
    async def get_swarm_status():
        return await formation_status(deps)

    @router.post("/api/v1/config/swarm/capture-preview", response_model=SwarmCapturePreviewResponse, tags=["Swarm"])
    async def preview_capture(payload: SwarmCapturePreviewRequest):
        return await capture_preview(deps, payload)

    @router.post("/api/v1/config/swarm/publish", response_model=SwarmConfigSaveResponse, tags=["Swarm"])
    async def publish_swarm(payload: SwarmPublishRequest):
        # Publishing persists the already-applied resource; it cannot install a draft.
        async with write_lock:
            assignments = deps.load_swarm() or []
            if payload.revision != topology_revision(assignments):
                raise HTTPException(409, "Swarm layout changed; review the applied formation before publishing")
            loop = asyncio.get_running_loop()
            git_result = await loop.run_in_executor(
                None, deps.git_operations, deps.BASE_DIR, "config: publish applied swarm formation"
            )
            status, message, _ = _build_swarm_save_message(True, git_result)
            return SwarmConfigSaveResponse(
                status=status, message=message,
                config=SwarmConfig.model_validate(_build_swarm_config_resource(assignments)),
                git_result=git_result,
            )

    @router.get("/api/v1/config/swarm", response_model=SwarmConfig, tags=["Swarm"])
    async def get_swarm_config(request: Request, response: Response):
        try:
            resource = _build_swarm_config_resource(deps.load_swarm())
            headers = {"ETag": f'"{resource["revision"]}"', "Cache-Control": "no-cache"}
            if matches_etag(request.headers.get("if-none-match"), resource["revision"]):
                return Response(status_code=304, headers=headers)
            response.headers.update(headers)
            return SwarmConfig.model_validate(resource)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put("/api/v1/config/swarm", response_model=SwarmConfigSaveResponse, tags=["Swarm"])
    async def put_swarm_config(payload: SwarmConfigApplyRequest, commit: Optional[bool] = Query(None)):
        async with write_lock:
            return await save_swarm_config(payload, commit)

    async def save_swarm_config(payload, commit):
        try:
            swarm_data = [assignment.model_dump(exclude_none=True) for assignment in payload.assignments]
            if not swarm_data:
                raise HTTPException(status_code=400, detail="No swarm data provided")
            _validate_swarm_cycle_constraints(swarm_data)

            before = deps.load_swarm() or []
            current_revision = topology_revision(before)
            if payload.revision and payload.revision != current_revision:
                raise HTTPException(
                    status_code=409,
                    detail="Swarm layout changed since this draft was loaded; refresh and review the changes.",
                )

            # Revision-aware editors receive reachability/installation receipts.
            # Legacy PUT remains wire compatible during node/dashboard rollout.
            if payload.revision:
                await validate_apply_observation(deps, before, swarm_data, payload.acknowledged_unavailable_hw_ids)
                if topology_revision(deps.load_swarm() or []) != current_revision:
                    raise HTTPException(409, "Swarm layout changed during review; reload before applying")

            protected = inactive_scope(before, swarm_data, payload.require_inactive_hw_ids) if payload.require_inactive_hw_ids else []
            observations = await read_inactive_scope(deps, protected) if protected else None

            deps.log_system_event("💾 Swarm configuration update received", "INFO", "swarm")
            async with configuration_lock(deps):
                if payload.revision and topology_revision(deps.load_swarm() or []) != current_revision:
                    raise HTTPException(409, "Swarm layout changed during review; reload before applying")
                if protected:
                    await recheck_inactive_scope(deps, protected, observations)
                deps.save_swarm(swarm_data)
            deps.log_system_event("✅ Swarm configuration saved successfully", "INFO", "swarm")

            should_commit = commit if commit is not None else deps.Params.GIT_AUTO_PUSH
            git_result = None

            if should_commit:
                loop = asyncio.get_running_loop()
                git_result = await loop.run_in_executor(
                    None, deps.git_operations, deps.BASE_DIR, "config: update swarm.json via dashboard"
                )
            status, message, log_level = _build_swarm_save_message(should_commit, git_result)
            deps.log_system_event(
                f"Smart Swarm save completed: status={status} commit_requested={should_commit} message={message}",
                log_level,
                "swarm",
            )

            return SwarmConfigSaveResponse(
                status=status,
                message=message,
                config=SwarmConfig(
                    version=int(payload.version),
                    assignments=payload.assignments,
                    revision=topology_revision(swarm_data),
                ),
                git_result=git_result,
                application=await formation_status(deps, swarm_data) if payload.revision else None,
            )

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.patch("/api/v1/config/swarm/assignments/{hw_id}", response_model=SwarmAssignmentUpdateResponse, tags=["Swarm"])
    async def patch_swarm_assignment(hw_id: int, payload: SwarmAssignmentPatchRequest):
        async with write_lock:
            return await patch_assignment(hw_id, payload)

    async def patch_assignment(hw_id, payload):
        try:
            data = payload.model_dump(exclude_unset=True, exclude_none=True,
                                      exclude={"revision", "acknowledged_unavailable_hw_ids"})

            if not data:
                raise HTTPException(status_code=400, detail="No swarm assignment changes provided")
            if payload.revision:
                before = deps.load_swarm() or []
                if topology_revision(before) != payload.revision:
                    raise HTTPException(409, "Swarm layout changed; refresh before applying")
                proposed = [dict(entry) for entry in before]
                member = next((entry for entry in proposed if int(entry["hw_id"]) == hw_id), None)
                if member is None:
                    raise HTTPException(404, "Swarm assignment not found")
                member.update(data)
                _validate_swarm_cycle_constraints(proposed)
                await validate_apply_observation(deps, before, proposed, payload.acknowledged_unavailable_hw_ids)
                if topology_revision(deps.load_swarm() or []) != payload.revision:
                    raise HTTPException(409, "Swarm layout changed during review; reload before applying")
            async with configuration_lock(deps):
                if payload.revision and topology_revision(deps.load_swarm() or []) != payload.revision:
                    raise HTTPException(409, "Swarm layout changed during review; reload before applying")
                updated_assignment = _apply_swarm_assignment_patch(deps, hw_id, {"hw_id": hw_id, **data})

            return SwarmAssignmentUpdateResponse(
                status="success",
                message="Swarm assignment updated",
                assignment=SwarmAssignment.model_validate(updated_assignment),
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
