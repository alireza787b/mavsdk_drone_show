"""Read-only cluster review using node admission, not a parallel flight policy."""
from fastapi import HTTPException


async def read_start_admissions(deps, drones):
    return await deps.get_fleet_rpc_service().review_swarm_start(drones)


async def require_start_admissions(deps, drones):
    decisions = await read_start_admissions(deps, drones)
    missing = [str(d['hw_id']) for d in drones if decisions.get(str(d['hw_id']), {}).get('status') != 'ready']
    if missing:
        first = missing[0]
        decision = decisions.get(first, {})
        raise HTTPException(409, detail={
            'message': f"Swarm not started — {decision.get('message', 'Checking aircraft')} · Drone {first}",
            'start_admissions': decisions,
            'dispatched': False,
        })
