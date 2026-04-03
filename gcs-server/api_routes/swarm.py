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


def create_swarm_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/get-swarm-data", tags=["Swarm"])
    async def get_swarm():
        try:
            return JSONResponse(content=deps.load_swarm())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/save-swarm-data", tags=["Swarm"])
    async def save_swarm_route(request: Request, commit: Optional[bool] = Query(None)):
        try:
            swarm_data = await request.json()

            if not swarm_data:
                raise HTTPException(status_code=400, detail="No swarm data provided")

            _validate_swarm_cycle_constraints(swarm_data)

            deps.log_system_event("💾 Swarm configuration update received", "INFO", "swarm")
            deps.save_swarm(swarm_data)
            deps.log_system_event("✅ Swarm configuration saved successfully", "INFO", "swarm")

            should_commit = commit if commit is not None else deps.Params.GIT_AUTO_PUSH
            git_result = None

            if should_commit:
                loop = asyncio.get_event_loop()
                git_result = await loop.run_in_executor(
                    None, deps.git_operations, deps.BASE_DIR, "config: update swarm.json via dashboard"
                )

            return JSONResponse(content={
                "status": "success",
                "message": "Swarm data saved successfully",
                "git_result": git_result,
            })

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/request-new-leader", tags=["Swarm"])
    async def request_new_leader(request: Request):
        try:
            data = await request.json()

            if not data:
                raise HTTPException(status_code=400, detail="No leader update data provided")

            try:
                hw_id = int(data.get("hw_id"))
                follow = int(data.get("follow", 0))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="hw_id and follow must be integers") from exc

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
                f"Smart Swarm leader update saved for hw_id={hw_id}: follow={follow}",
                "INFO",
                "swarm",
            )

            return JSONResponse(content={
                "status": "success",
                "message": "Leader request processed",
                "assignment": updated_assignment,
            })
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
