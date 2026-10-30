"""Compact native takeoff review and command-bound launch coordination."""
import time
from fastapi import APIRouter, Header, HTTPException, Query

from command_tracker import CommandCallbackAuthenticationError
from src.coordinated_takeoff_contract import TakeoffStageRequest, TakeoffStageResponse
from src.gcs_api_routes import GCS_COMMAND_REPORT_CAPABILITY_HEADER


async def fail_coordinated_takeoff(deps, command_id, reason, failed_hw_id=None):
    tracker = deps.get_command_tracker()
    status = await tracker.get_status(command_id)
    if not status or not status.get('coordinated_takeoff'):
        return
    await tracker.abort_coordinated_takeoff(command_id, reason)
    if not status['coordinated_takeoff'].get('release_at_unix_ms'):
        return
    # Resolve recovery through normal tracked commands, not raw MAVLink. The
    # expected owner is checked again by each node under its command lock.
    peers = [row for row in deps.load_config() if str(row['hw_id']) in status['target_drones']
             and str(row['hw_id']) != failed_hw_id]
    ids = await deps.get_fleet_rpc_service().review_takeoff_recovery(peers)
    if not ids:
        return
    from command_submission import submit_tracked_command
    from schemas import SubmitCommandRequest
    from src.enums import Mission
    try:
        await submit_tracked_command(deps, SubmitCommandRequest(
            mission_type=Mission.HOLD.value, trigger_time=0, target_drone_ids=ids,
            expected_control_command_id=command_id,
            idempotency_key=f'takeoff-recovery:{command_id}:{":".join(sorted(ids))}',
        ))
    except Exception as exc:
        deps.log_system_warning(f'Takeoff group recovery unconfirmed for {command_id}: {exc}', 'command')


def create_takeoff_router(deps):
    router = APIRouter(tags=['Commands'])

    @router.get('/api/v1/commands/takeoff-readiness')
    async def readiness(target_drone_ids: list[str] = Query(...)):
        started = time.monotonic()
        known = {str(row['hw_id']): row for row in deps.load_config()}
        if not target_drone_ids or len(set(target_drone_ids)) != len(target_drone_ids) or not set(target_drone_ids) <= set(known):
            raise HTTPException(409, 'Review the selected aircraft')
        values = await deps.get_fleet_rpc_service().review_takeoff([known[hw] for hw in target_drone_ids])
        targets = [values[hw] for hw in target_drone_ids]
        ready = all(row['status'] == 'ready' for row in targets)
        return dict(targets=targets, ready=ready,
                    valid_for_ms=min((row.get('valid_for_ms', 0) for row in targets), default=0),
                    server_processing_ms=max(0, int((time.monotonic() - started) * 1000)))

    @router.post('/api/v1/commands/{command_id}/cancel-launch')
    async def cancel(command_id: str):
        tracker = deps.get_command_tracker()
        status = await tracker.get_status(command_id)
        if not status:
            raise HTTPException(404, 'Takeoff operation not found')
        if status.get('mission_type') != 10 or (status.get('params') or {}).get('takeoff_mode') != 'coordinated':
            raise HTTPException(409, 'No coordinated takeoff operation')
        if not status.get('coordinated_takeoff'):
            await tracker.initialize_coordinated_takeoff(command_id, deps.Params)
        try:
            snapshot = await tracker.abort_coordinated_takeoff(command_id, 'Launch cancelled', before_release_only=True)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if status.get('submitted_at') is None:
            await tracker.cancel_command(command_id, 'Launch cancelled before dispatch')
        return dict(command_id=command_id, coordinated_takeoff=snapshot)

    @router.post('/api/v1/command-reports/takeoff-stage', response_model=TakeoffStageResponse)
    async def stage(report: TakeoffStageRequest, capability: str | None = Header(
        None, alias=GCS_COMMAND_REPORT_CAPABILITY_HEADER,
    )):
        try:
            result = await deps.get_command_tracker().record_takeoff_stage(report, capability)
        except CommandCallbackAuthenticationError as exc:
            raise HTTPException(403, str(exc)) from exc
        if report.state == 'failed':
            await fail_coordinated_takeoff(deps, report.command_id, report.reason or 'A required aircraft failed takeoff', report.hw_id)
        return result

    return router
