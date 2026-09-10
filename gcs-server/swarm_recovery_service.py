"""Narrow per-node, capability-authorized failover writeback, not an election."""
import hmac

from fastapi import HTTPException

from api_routes.swarm import _apply_swarm_assignment_patch
from smart_swarm_src.assignment_recovery import recovery_assignment
from smart_swarm_src.failover import choose_leader_loss_response
from src.smart_swarm_contract import normalize_topology, topology_revision


async def apply_session_recovery(deps, request, capability):
    tracker = deps.get_command_tracker()
    try:
        capabilities = await tracker.get_callback_capabilities(request.command_id)
    except (KeyError, RuntimeError):
        capabilities = {}
    expected = capabilities.get(request.hw_id)
    if not expected or not capability or not hmac.compare_digest(expected, capability):
        raise HTTPException(403, 'Command callback authentication failed')
    status = await tracker.get_status(request.command_id)
    if not status or status.get('mission_type') != 2 or not status.get('params', {}).get('smart_swarm'):
        raise HTTPException(409, 'No tracked swarm session')
    # No await between the revision check and canonical save: a stale node
    # cannot overwrite newer operator-edited leader/offset geometry.
    members = normalize_topology(deps.load_swarm() or [])
    if topology_revision(members) != request.revision:
        raise HTTPException(409, 'Swarm layout changed; recovery write not applied')
    assignments = {m['hw_id']: m for m in members}
    own = assignments.get(request.hw_id)
    if own is None:
        raise HTTPException(409, 'Swarm assignment removed')
    strategy = getattr(deps.Params, 'SMART_SWARM_LEADER_LOSS_STRATEGY', 'upstream_or_hold')
    if request.follow:
        choice = choose_leader_loss_response(request.hw_id, own['follow'], assignments, strategy)
        if choice['action'] != 'follow' or choice['leader_hw_id'] != str(request.follow):
            raise HTTPException(409, 'Recovery target is not the configured failover choice')
    try:
        assignment = recovery_assignment(request.hw_id, request.follow, assignments, strategy=strategy)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    updated = _apply_swarm_assignment_patch(deps, int(request.hw_id), assignment)
    return {'status': 'success', 'assignment': updated}
