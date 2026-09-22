from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from command_tracker import CommandTracker
from smart_swarm_src.assignment_recovery import LocalRecoveryOverride, recovery_assignment
from src.smart_swarm_contract import normalize_topology, topology_revision, SmartSwarmSession, SwarmRecoveryRequest
from swarm_recovery_service import apply_session_recovery


def chain():
    return {m['hw_id']: m for m in normalize_topology([
        {'hw_id': 1, 'follow': 0},
        {'hw_id': 2, 'follow': 1, 'offset_x': 6, 'offset_z': -2},
        {'hw_id': 3, 'follow': 2, 'offset_x': 6, 'offset_y': 3, 'offset_z': -1},
        {'hw_id': 4, 'follow': 3, 'offset_x': 2},
    ])}


def test_recursive_upstream_recovery_preserves_geometry():
    assignments = chain()
    target = recovery_assignment('3', '1', assignments)
    assert (target['offset_x'], target['offset_y'], target['offset_z']) == (12, 3, -3)
    assert recovery_assignment('4', '1', assignments)['offset_x'] == 14
    assert assignments['3']['follow'] == '2'


def test_body_frame_is_not_guessed_after_ancestor_disappears():
    assignments = chain()
    assignments['2']['frame'] = 'body'
    with pytest.raises(ValueError, match='body-frame'):
        recovery_assignment('3', '1', assignments)
    assert recovery_assignment('3', '0', assignments)['follow'] == 0


def test_local_hold_is_not_undone_by_unchanged_saved_assignment():
    original = chain()['3']
    effective = dict(original, follow=0)
    override = LocalRecoveryOverride()
    override.remember(original, effective)
    assert override.resolve(dict(original)) == effective
    edited = dict(original, follow='1', offset_x=12)
    assert override.resolve(edited) == edited
    assert override.assignment is None


@pytest.mark.asyncio
async def test_recovery_auth_and_revision_protect_other_nodes_and_operator_edits():
    assignments = list(chain().values())
    session = SmartSwarmSession(assignments=assignments, revision=topology_revision(assignments),
                               expected_hw_ids=['1', '2', '3', '4'])
    tracker = CommandTracker()
    cid = await tracker.create_command(2, session.expected_hw_ids, {'smart_swarm': session.model_dump()})
    capabilities = await tracker.get_callback_capabilities(cid)
    saved = []
    deps = SimpleNamespace(get_command_tracker=lambda: tracker, load_swarm=lambda: assignments,
                           save_swarm=lambda data: saved.append(data), log_system_event=Mock(),
                           Params=SimpleNamespace(SMART_SWARM_LEADER_LOSS_STRATEGY='upstream_or_hold'))
    request = SwarmRecoveryRequest(command_id=cid, hw_id='3', revision=session.revision, follow=1)
    with pytest.raises(HTTPException) as caught:
        await apply_session_recovery(deps, request, capabilities['2'])
    assert caught.value.status_code == 403
    with pytest.raises(HTTPException) as caught:
        await apply_session_recovery(deps, request.model_copy(update={'revision': '0' * 64}), capabilities['3'])
    assert caught.value.status_code == 409 and not saved
    result = await apply_session_recovery(deps, request, capabilities['3'])
    assert result['assignment']['follow'] == 1
    assert result['assignment']['offset_x'] == 12
    assert result['persisted'] is False
    assert not saved
    assert assignments[2]['follow'] == '2'

    deps.Params.SMART_SWARM_LEADER_LOSS_STRATEGY = 'hold_recover'
    with pytest.raises(HTTPException) as caught:
        await apply_session_recovery(deps, request, capabilities['3'])
    assert caught.value.status_code == 409
    assert not saved
