"""Swarm configuration and leader-reassignment routes."""

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse


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


def _apply_swarm_assignment_patch(deps: Any, hw_id: int, data: dict[str, Any]) -> dict[str, Any]:
    try:
        follow = int(data.get("follow", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="follow must be zero or a valid leader hw_id") from exc

    if hw_id <= 0:
        raise HTTPException(status_code=400, detail="hw_id must be a positive integer")
    if follow < 0:
        raise HTTPException(status_code=400, detail="follow must be zero or a valid leader hw_id")
    if follow == hw_id:
        raise HTTPException(status_code=400, detail="A drone cannot follow itself")

    swarm_data = deps.load_swarm()
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

    @router.get("/api/v1/config/swarm", tags=["Swarm"])
    async def get_swarm_config():
        try:
            return JSONResponse(content=_build_swarm_config_resource(deps.load_swarm()))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put("/api/v1/config/swarm", tags=["Swarm"])
    async def put_swarm_config(request: Request, commit: Optional[bool] = Query(None)):
        try:
            swarm_data = _parse_swarm_config_payload(await request.json())
            _validate_swarm_cycle_constraints(swarm_data)

            deps.log_system_event("💾 Swarm configuration update received", "INFO", "swarm")
            deps.save_swarm(swarm_data)
            deps.log_system_event("✅ Swarm configuration saved successfully", "INFO", "swarm")

            should_commit = commit if commit is not None else deps.Params.GIT_AUTO_PUSH
            git_result = None

            if should_commit:
                loop = asyncio.get_running_loop()
                git_result = await loop.run_in_executor(
                    None, deps.git_operations, deps.BASE_DIR, "config: update swarm.json via dashboard"
                )

            return JSONResponse(content={
                "status": "success",
                "message": "Swarm configuration saved successfully",
                "config": _build_swarm_config_resource(swarm_data),
                "git_result": git_result,
            })

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.patch("/api/v1/config/swarm/assignments/{hw_id}", tags=["Swarm"])
    async def patch_swarm_assignment(hw_id: int, request: Request):
        try:
            data = await request.json()

            if not isinstance(data, dict):
                raise HTTPException(status_code=400, detail="Swarm assignment patch must be a JSON object")

            payload_hw_id = data.get("hw_id")
            if payload_hw_id is not None and _normalize_swarm_hw_id(payload_hw_id) != hw_id:
                raise HTTPException(status_code=400, detail="Payload hw_id must match the path hw_id")

            data = {
                **data,
                "hw_id": hw_id,
            }

            if len(data) == 1:
                raise HTTPException(status_code=400, detail="No swarm assignment changes provided")
            updated_assignment = _apply_swarm_assignment_patch(deps, hw_id, data)

            return JSONResponse(content={
                "status": "success",
                "message": "Swarm assignment updated",
                "assignment": updated_assignment,
            })
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
