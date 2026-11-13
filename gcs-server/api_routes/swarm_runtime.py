"""Normal and advanced UI use the same saved-cluster and runtime contract."""
import time
from fastapi import APIRouter, Header, HTTPException, Query
from src.smart_swarm_contract import SwarmStartRequest, SwarmRuntimeReport, SwarmRecoveryRequest
from src.gcs_api_routes import GCS_COMMAND_REPORT_CAPABILITY_HEADER
from command_tracker import CommandCallbackAuthenticationError
from smart_swarm_service import build_preview, start_cluster, resolve_start_scope
from swarm_recovery_service import apply_session_recovery
from sequential_return_service import SequentialReturnRequest
from swarm_start_readiness import read_start_admissions, read_reference_admissions


def create_swarm_runtime_router(deps):
    router = APIRouter(tags=["Smart Swarm"])

    @router.get("/api/v1/swarm/runtime/preview")
    async def preview(cluster_id: str | None = None, check_start: bool = False,
                      target_hw_ids: list[str] | None = Query(default=None)):
        try:
            result = build_preview(deps)
            result['observed_at_ms'] = int(time.time() * 1000)
            if hasattr(deps, 'get_command_tracker'):
                result['runtime_nodes'] = await deps.get_command_tracker().swarm_node_evidence(
                    [m['hw_id'] for c in result['clusters'] for m in c['members']], result['revision'])
            if check_start:
                cluster = next((c for c in result['clusters'] if c['cluster_id'] == cluster_id), None)
                if cluster is None:
                    raise HTTPException(409, 'Select a saved formation')
                ids = {m['hw_id'] for m in cluster['members']}
                references = []
                if target_hw_ids is not None:
                    selected, references, _ = resolve_start_scope(cluster, SwarmStartRequest(
                        cluster_id=cluster_id, revision=result['revision'], target_hw_ids=target_hw_ids,
                        idempotency_key='read-only-preview'))
                    ids = set(selected)
                    result['reference_hw_ids'] = references
                    result['reference_admissions'] = await read_reference_admissions(deps, references) if references else {}
                drones = [d for d in deps.load_config() if str(d['hw_id']) in ids]
                result['start_admissions'] = await read_start_admissions(deps, drones, scoped=bool(references))
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
            tracker = deps.get_command_tracker()
            references = await tracker.pending_swarm_references(payload, capability)
            until = 0
            if references:
                decisions = await read_reference_admissions(deps, references)
                remaining = min((decisions.get(hw, {}).get('valid_for_ms', 0)
                    if decisions.get(hw, {}).get('status') == 'ready' else 0) for hw in references)
                until = time.monotonic() + max(0, remaining) / 1000
            return await tracker.record_swarm_runtime(payload, capability, reference_valid_until=until)
        except CommandCallbackAuthenticationError as exc:
            raise HTTPException(403, str(exc)) from exc

    @router.post("/api/v1/command-reports/swarm-recovery")
    async def recover(payload: SwarmRecoveryRequest, capability: str | None = Header(
        None, alias=GCS_COMMAND_REPORT_CAPABILITY_HEADER,
    )):
        return await apply_session_recovery(deps, payload, capability)

    return router
