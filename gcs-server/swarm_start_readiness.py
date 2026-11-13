"""Read-only cluster review using node admission, not a parallel flight policy."""
from fastapi import HTTPException


async def read_start_admissions(deps, drones, *, scoped=False):
    decisions = await deps.get_fleet_rpc_service().review_swarm_start(drones)
    if scoped:
        for row in decisions.values():
            if row.get('status') == 'ready' and row.get('scoped_start_supported') is not True:
                row.update(status='blocked', message='Update aircraft software for selected Start', valid_for_ms=0)
    return decisions


async def require_start_admissions(deps, drones, *, scoped=False):
    decisions = await read_start_admissions(deps, drones, scoped=scoped)
    missing = [str(d['hw_id']) for d in drones if decisions.get(str(d['hw_id']), {}).get('status') != 'ready']
    if missing:
        first = missing[0]
        decision = decisions.get(first, {})
        raise HTTPException(409, detail={
            'message': f"Swarm not started — {decision.get('message', 'Checking aircraft')} · Drone {first}",
            'start_admissions': decisions,
            'dispatched': False,
        })


async def read_reference_admissions(deps, ids):
    """Sources must be explicit native observations, never cached GCS presence."""
    requested = set(ids)
    drones = [d for d in deps.load_config() if str(d['hw_id']) in requested]
    decisions = await deps.get_fleet_rpc_service().review_swarm_references(drones)
    follows = {str(row['hw_id']): str(row.get('follow', 0)) for row in deps.load_swarm()}
    for hw, row in decisions.items():
        if row.get('swarm_active') and str(row.get('live_follow')) != follows.get(hw):
            row.update(status='waiting', message='Formation update pending', valid_for_ms=0)
    return decisions


async def require_reference_admissions(deps, ids):
    if not ids:
        return
    decisions = await read_reference_admissions(deps, ids)
    for hw in ids:
        row = decisions.get(hw, {})
        if row.get('status') != 'ready' or row.get('valid_for_ms', 0) <= 0:
            raise HTTPException(409, detail={
                'message': f"Leader reference {hw}: {row.get('message', 'Checking aircraft')}",
                'reference_admissions': decisions, 'dispatched': False,
            })
