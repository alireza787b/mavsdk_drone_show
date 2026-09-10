"""Session coordination must not create flight authority or fake engagement."""
import logging
from threading import Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from command_tracker import CommandTracker, CommandCallbackAuthenticationError
from smart_swarm_service import build_preview, runtime_summary, start_cluster
from smart_swarm_src.control_authority import ControlAuthority
from smart_swarm_src.session_runtime import SwarmSessionRuntime
from src.smart_swarm_contract import (
    SmartSwarmSession, SwarmStartRequest, SwarmRuntimeReport,
    normalize_topology, topology_revision,
)


def snapshot():
    members = normalize_topology([{'hw_id': 1, 'follow': 0}, {'hw_id': 2, 'follow': 1, 'offset_x': 6}])
    return SmartSwarmSession(assignments=members, revision=topology_revision(members), expected_hw_ids=['1', '2'])


async def tracked_session():
    tracker = CommandTracker()
    session = snapshot()
    command_id = await tracker.create_command(2, ['1', '2'], {'smart_swarm': session.model_dump()}, timeout_ms=45000)
    await tracker.mark_submitted(command_id)
    capabilities = await tracker.get_callback_capabilities(command_id)

    async def report(hw, phase='ready', sequence=1, **overrides):
        payload = dict(command_id=command_id, hw_id=hw, phase=phase, sequence=sequence,
                       follow='0' if hw == '1' else '1', role='leader' if hw == '1' else 'follower',
                       revision=session.revision)
        payload.update(overrides)
        return await tracker.record_swarm_runtime(SwarmRuntimeReport(**payload), capabilities[hw])

    return tracker, command_id, report


@pytest.mark.asyncio
async def test_all_roles_acknowledge_before_engagement_and_active_needs_real_reports():
    tracker, cid, report = await tracked_session()
    await tracker.record_execution_start(cid, '1', (await tracker.get_callback_capabilities(cid))['1'])
    assert (await report('1'))['engage'] is False
    assert runtime_summary(tracker._commands[cid].params, ['1', '2'])['state'] == 'starting'
    assert (await report('2'))['engage'] is True
    await report('1', 'active', 2)
    assert runtime_summary(tracker._commands[cid].params, ['1', '2'])['state'] == 'degraded'
    await report('2', 'active', 2)
    assert runtime_summary(tracker._commands[cid].params, ['1', '2'])['state'] == 'active'


@pytest.mark.asyncio
async def test_rejected_or_terminated_role_cannot_unlock_other_role():
    tracker, cid, report = await tracked_session()
    await report('2', 'failed')
    result = await report('1')
    assert result['abort'] and not result['engage']


@pytest.mark.asyncio
async def test_wrong_revision_and_replayed_sequence_do_not_replace_role_evidence():
    tracker, cid, report = await tracked_session()
    assert (await report('2', revision='0' * 64))['abort']
    await report('1', sequence=2)
    await report('1', 'failed', sequence=1)
    assert tracker._commands[cid].params['_swarm_runtime']['1']['phase'] == 'ready'
    with pytest.raises(CommandCallbackAuthenticationError):
        await tracker.record_swarm_runtime(SwarmRuntimeReport(
            command_id=cid, hw_id='2', sequence=1, role='follower', follow='1',
            revision=snapshot().revision, phase='ready'), 'incorrect')


def test_expired_tracking_is_unconfirmed_not_falsely_stopped():
    params = {'smart_swarm': snapshot().model_dump(), '_swarm_runtime': {
        '1': {'phase': 'active', 'received_at_ms': 1000},
        '2': {'phase': 'active', 'received_at_ms': 1000},
    }}
    assert runtime_summary(params, ['1', '2'], now_ms=20000)['state'] == 'degraded'
    assert runtime_summary(params, ['1', '2'], terminal=True)['state'] == 'unconfirmed'


@pytest.mark.parametrize('mode', ['RETURN_TO_LAUNCH', 'LAND', 'POSCTL', 'HOLD'])
def test_follower_pilot_takeover_latches_and_cannot_reengage(mode):
    authority = ControlAuthority()
    authority.update_armed(True)
    authority.expect('OFFBOARD', now=10)
    authority.update_mode('OFFBOARD', leader=False, now=10)
    authority.update_mode(mode, leader=False, now=11)
    assert authority.takeover_reason
    assert not authority.expect('OFFBOARD', now=12)
    assert not authority.owns_fresh_offboard(now=12)


def test_leader_manual_modes_and_internal_failover_hold_are_not_takeover():
    authority = ControlAuthority()
    authority.update_armed(True)
    for mode in ['POSCTL', 'HOLD', 'MISSION']:
        authority.update_mode(mode, leader=True)
        assert authority.takeover_reason is None
    assert authority.never_requested_follower_control()
    authority.expect('OFFBOARD')
    authority.update_mode('OFFBOARD', leader=False)
    authority.expect('HOLD')
    authority.update_mode('HOLD', leader=False)
    assert authority.takeover_reason is None
    assert authority.expect('OFFBOARD')


def test_stale_mode_cannot_authorize_follower_control():
    authority = ControlAuthority()
    authority.update_armed(True)
    authority.update_mode('OFFBOARD', leader=False, now=10)
    assert authority.owns_fresh_offboard(now=12)
    assert not authority.owns_fresh_offboard(now=13)


@pytest.mark.asyncio
async def test_takeover_during_start_barrier_never_reports_ready(monkeypatch):
    monkeypatch.delenv('MDS_SWARM_CONTEXT_FD', raising=False)
    runtime = SwarmSessionRuntime(SimpleNamespace(), logging.getLogger(__name__))
    runtime.report = AsyncMock(return_value={'engage': True})
    authority = ControlAuthority()
    authority.update_mode('LAND', leader=False)
    with pytest.raises(RuntimeError, match='cancelled'):
        await runtime.wait_for_cluster(2, 1, snapshot().revision, authority=authority)
    runtime.report.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_dashboard_preview_is_advisory_and_does_not_silently_exclude(monkeypatch):
    session = snapshot()
    deps = SimpleNamespace(load_swarm=lambda: [m.model_dump() for m in session.assignments],
                           telemetry_lock=Lock(), telemetry_data_all_drones={},
                           get_command_tracker=lambda: CommandTracker())
    preview = build_preview(deps)
    assert preview['clusters'][0]['available_hw_ids'] == []
    submit = AsyncMock(return_value='submitted')
    monkeypatch.setattr('command_submission.submit_tracked_command', submit)
    request = SwarmStartRequest(cluster_id='1', revision=session.revision, idempotency_key='test')
    assert await start_cluster(deps, request) == 'submitted'
    assert submit.call_args.args[1].target_drone_ids == ['1', '2']
    with pytest.raises(HTTPException) as caught:
        await start_cluster(deps, request.model_copy(update={'excluded_hw_ids': ['2']}))
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_start_retry_recovers_same_command_after_layout_changed():
    tracker = CommandTracker()
    session = snapshot()
    cid = (await tracker.create_or_replay_command(2, ['1', '2'],
        {'smart_swarm': session.model_dump()}, idempotency_key='retry')).command_id
    deps = SimpleNamespace(get_command_tracker=lambda: tracker,
                           load_swarm=lambda: [])
    request = SwarmStartRequest(cluster_id='1', revision=session.revision, idempotency_key='retry')
    result = await start_cluster(deps, request)
    assert result.command_id == cid and result.replayed
    with pytest.raises(HTTPException) as caught:
        await start_cluster(deps, request.model_copy(update={'excluded_hw_ids': ['2']}))
    assert caught.value.status_code == 409
