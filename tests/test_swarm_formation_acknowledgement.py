from smart_swarm_src.formation_acknowledgement import effective_revision
from src.smart_swarm_contract import topology_revision
import pytest


MEMBERS = [{'hw_id': 1, 'follow': 0}, {'hw_id': 2, 'follow': 1, 'offset_x': 6}]


def acknowledgement(**overrides):
    state = dict(is_leader=False, follow='1', offsets={'x': 6, 'y': 0, 'z': 0},
                 frame='ned', controller_running=True)
    state.update(overrides)
    return effective_revision(MEMBERS, 2, **state)


def test_config_read_is_not_effective_controller_acknowledgement():
    assert acknowledgement(offsets={'x': 2, 'y': 0, 'z': 0}) is None
    assert acknowledgement(frame='body') is None
    assert acknowledgement(follow='3') is None
    assert acknowledgement(is_leader=True) is None


def test_cancelled_or_missing_controller_cannot_acknowledge_installation():
    assert acknowledgement(controller_running=False) is None
    assert acknowledgement(takeover=True) is None


def test_matching_live_controller_acknowledges_configuration_not_arrival():
    assert acknowledgement() == topology_revision(MEMBERS)


def test_leader_does_not_require_a_follower_controller():
    assert effective_revision(MEMBERS, 1, is_leader=True, follow='0',
                              offsets={'x': 0, 'y': 0, 'z': 0}, frame='ned',
                              controller_running=False) == topology_revision(MEMBERS)


@pytest.mark.asyncio
async def test_tracker_retains_applied_revision_without_mutating_start_snapshot():
    from command_tracker import CommandTracker
    from src.smart_swarm_contract import SmartSwarmSession, SwarmRuntimeReport, normalize_topology
    initial = topology_revision(MEMBERS)
    session = SmartSwarmSession(assignments=normalize_topology(MEMBERS), revision=initial, expected_hw_ids=['1', '2'])
    tracker = CommandTracker()
    command = await tracker.create_command(2, ['1', '2'], {'smart_swarm': session.model_dump()}, timeout_ms=45000)
    await tracker.mark_submitted(command)
    capability = (await tracker.get_callback_capabilities(command))['2']
    await tracker.record_swarm_runtime(SwarmRuntimeReport(
        command_id=command, hw_id='2', sequence=1, role='follower', follow='1',
        revision=initial, phase='ready'), capability)
    changed = topology_revision([MEMBERS[0], {**MEMBERS[1], 'offset_x': 8}])
    await tracker.record_swarm_runtime(SwarmRuntimeReport(
        command_id=command, hw_id='2', sequence=2, role='follower', follow='1',
        revision=changed, applied_revision=changed, phase='tracking'), capability)
    status = await tracker.get_status(command)
    assert status['swarm_runtime']['nodes']['2']['applied_revision'] == changed
    assert status['params']['smart_swarm']['revision'] == initial
