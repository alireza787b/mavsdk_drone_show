"""Normal and advanced UI use the same saved-cluster and runtime contract."""
from fastapi import APIRouter, Header, HTTPException
from src.smart_swarm_contract import SwarmStartRequest, SwarmRuntimeReport, SwarmRecoveryRequest
from src.gcs_api_routes import GCS_COMMAND_REPORT_CAPABILITY_HEADER
from command_tracker import CommandCallbackAuthenticationError
from smart_swarm_service import build_preview, start_cluster
from swarm_recovery_service import apply_session_recovery
from sequential_return_service import SequentialReturnRequest
from swarm_start_readiness import read_start_admissions


def create_swarm_runtime_router(deps):
    router = APIRouter(tags=["Smart Swarm"])

    @router.get("/api/v1/swarm/runtime/preview")
    async def preview(cluster_id: str | None = None, check_start: bool = False):
        try:
            result = build_preview(deps)
            if check_start:
                cluster = next((c for c in result['clusters'] if c['cluster_id'] == cluster_id), None)
                if cluster is None:
                    raise HTTPException(409, 'Select a saved formation')
                ids = {m['hw_id'] for m in cluster['members']}
                drones = [d for d in deps.load_config() if str(d['hw_id']) in ids]
                result['start_admissions'] = await read_start_admissions(deps, drones)
            return result
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/v1/swarm/runtime/start", status_code=202)
    async def start(request: SwarmStartRequest):
        return await start_cluster(deps, request)

    @router.get("/api/v1/swarm/runtime/sequential-return")
    async def latest_return():
        return deps.sequential_return_service.latest()

    @router.post("/api/v1/swarm/runtime/sequential-return", status_code=202)
    async def sequential_return(request: SequentialReturnRequest):
        return await deps.sequential_return_service.start(request)

    @router.get("/api/v1/swarm/runtime/sequential-return/{return_id}")
    async def return_status(return_id: str):
        return deps.sequential_return_service.get(return_id)

    @router.post("/api/v1/swarm/runtime/sequential-return/{return_id}/cancel")
    async def cancel_return(return_id: str):
        return await deps.sequential_return_service.cancel(return_id)

    @router.post("/api/v1/command-reports/swarm-runtime")
    async def report(payload: SwarmRuntimeReport, capability: str | None = Header(
        None, alias=GCS_COMMAND_REPORT_CAPABILITY_HEADER,
    )):
        try:
            return await deps.get_command_tracker().record_swarm_runtime(payload, capability)
        except CommandCallbackAuthenticationError as exc:
            raise HTTPException(403, str(exc)) from exc

    @router.post("/api/v1/command-reports/swarm-recovery")
    async def recover(payload: SwarmRecoveryRequest, capability: str | None = Header(
        None, alias=GCS_COMMAND_REPORT_CAPABILITY_HEADER,
    )):
        return await apply_session_recovery(deps, payload, capability)

    return router
