"""Normal and advanced UI use the same saved-cluster and runtime contract."""
from fastapi import APIRouter, Header, HTTPException
from src.smart_swarm_contract import SwarmStartRequest, SwarmRuntimeReport
from src.gcs_api_routes import GCS_COMMAND_REPORT_CAPABILITY_HEADER
from command_tracker import CommandCallbackAuthenticationError
from smart_swarm_service import build_preview, start_cluster


def create_swarm_runtime_router(deps):
    router = APIRouter(tags=["Smart Swarm"])

    @router.get("/api/v1/swarm/runtime/preview")
    async def preview():
        try:
            return build_preview(deps)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/v1/swarm/runtime/start", status_code=202)
    async def start(request: SwarmStartRequest):
        return await start_cluster(deps, request)

    @router.post("/api/v1/command-reports/swarm-runtime")
    async def report(payload: SwarmRuntimeReport, capability: str | None = Header(
        None, alias=GCS_COMMAND_REPORT_CAPABILITY_HEADER,
    )):
        try:
            return await deps.get_command_tracker().record_swarm_runtime(payload, capability)
        except CommandCallbackAuthenticationError as exc:
            raise HTTPException(403, str(exc)) from exc

    return router
