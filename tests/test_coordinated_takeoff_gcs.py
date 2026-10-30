"""All-armed barrier uses journal decisions, native leases and scoped authority."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from command_tracker import CommandTracker, CommandCallbackAuthenticationError
from src.coordinated_takeoff_contract import TakeoffStageRequest, TakeoffStageResponse
from api_routes.takeoff import create_takeoff_router


async def operation(*, state_dir=None, acknowledge=True):
    tracker = CommandTracker(state_dir=state_dir)
    command_id = await tracker.create_command(mission_type=10, target_drones=['1', '2'], params={'takeoff_mode': 'coordinated'})
    await tracker.initialize_coordinated_takeoff(command_id, SimpleNamespace())
    capabilities = await tracker.get_callback_capabilities(command_id)
    if acknowledge:
        for hw in ['1', '2']:
            await tracker.record_ack(command_id, hw, category='accepted')
    return tracker, command_id, capabilities


async def report(tracker, command_id, capabilities, hw, sequence, challenge=None, **kwargs):
    request = TakeoffStageRequest(command_id=command_id, hw_id=hw, sequence=sequence,
        state=kwargs.pop('state', 'armed_ready'), armed=True, landed_state=kwargs.pop('landed_state', 'ON_GROUND'),
        lease_remaining_ms=kwargs.pop('lease_remaining_ms', 7000), challenge=challenge, **kwargs)
    response = await tracker.record_takeoff_stage(request, capabilities[hw])
    return TakeoffStageResponse.model_validate(response).model_dump()


@pytest.mark.asyncio
async def test_all_armed_barrier_requires_fresh_challenge_and_every_ack():
    tracker, cid, caps = await operation(acknowledge=False)
    a = await report(tracker, cid, caps, '1', 0)
    b = await report(tracker, cid, caps, '2', 0)
    assert a['decision'] == b['decision'] == 'wait'
    a = await report(tracker, cid, caps, '1', 1, a['challenge'])
    b = await report(tracker, cid, caps, '2', 1, b['challenge'])
    assert a['decision'] == b['decision'] == 'wait'
    for hw in ['1', '2']:
        await tracker.record_ack(cid, hw, category='accepted')
    a = await report(tracker, cid, caps, '1', 2, a['challenge'])
    b = await report(tracker, cid, caps, '2', 2, b['challenge'])
    assert a['decision'] == b['decision'] == 'release'
    assert a['release_at_unix_ms'] == b['release_at_unix_ms']
    status = await tracker.get_status(cid)
    assert status['coordinated_takeoff']['armed_count'] == 2
    assert '_coordinated_takeoff' not in status['params']
    assert 'challenge' not in str(status)


@pytest.mark.asyncio
async def test_delayed_challenge_or_node_failure_never_releases(monkeypatch):
    tracker, cid, caps = await operation()
    import coordinated_takeoff as module
    now = [100.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    a = await report(tracker, cid, caps, '1', 0)
    now[0] += 1.1
    a = await report(tracker, cid, caps, '1', 1, a['challenge'])
    assert a['decision'] == 'wait'
    failed = await report(tracker, cid, caps, '2', 0, state='failed', reason='PX4 rejected arming')
    assert failed['decision'] == 'abort'
    assert (await report(tracker, cid, caps, '1', 2, a['challenge']))['decision'] == 'abort'


@pytest.mark.asyncio
async def test_short_armed_lease_aborts_group():
    tracker, cid, caps = await operation()
    a = await report(tracker, cid, caps, '1', 0)
    b = await report(tracker, cid, caps, '2', 0)
    await report(tracker, cid, caps, '1', 1, a['challenge'])
    assert (await report(tracker, cid, caps, '2', 1, b['challenge'], lease_remaining_ms=100))['decision'] == 'abort'


@pytest.mark.asyncio
async def test_normal_climb_does_not_expire_ground_heartbeat(monkeypatch):
    tracker, cid, caps = await operation()
    import coordinated_takeoff as module
    now = [100.]
    wall = [1000.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(module.time, 'time', lambda: wall[0])
    a = await report(tracker, cid, caps, '1', 0)
    b = await report(tracker, cid, caps, '2', 0)
    a = await report(tracker, cid, caps, '1', 1, a['challenge'])
    b = await report(tracker, cid, caps, '2', 1, b['challenge'])
    assert b['decision'] == 'release'
    now[0] += 10
    wall[0] += 10
    assert (await report(tracker, cid, caps, '1', 2, a['challenge'], state='airborne', landed_state='IN_AIR'))['decision'] == 'release'
    assert (await report(tracker, cid, caps, '2', 2, b['challenge'], state='airborne', landed_state='IN_AIR'))['decision'] == 'release'
    assert (await tracker.get_status(cid))['coordinated_takeoff']['phase'] == 'airborne'


@pytest.mark.asyncio
async def test_restart_and_cancel_fence_late_ready(tmp_path):
    tracker, cid, caps = await operation(state_dir=str(tmp_path))
    a = await report(tracker, cid, caps, '1', 0)
    tracker.close()
    restored = CommandTracker(state_dir=str(tmp_path))
    assert (await report(restored, cid, caps, '1', 1, a['challenge']))['decision'] == 'abort'
    restored.close()
    tracker, cid, caps = await operation()
    await tracker.abort_coordinated_takeoff(cid, 'Launch cancelled', before_release_only=True)
    assert (await report(tracker, cid, caps, '2', 0))['decision'] == 'abort'


@pytest.mark.asyncio
async def test_callback_auth_and_replay_do_not_refresh_evidence():
    tracker, cid, caps = await operation()
    a = await report(tracker, cid, caps, '1', 0)
    again = await report(tracker, cid, caps, '1', 0)
    assert a['challenge'] == again['challenge']
    caps['2'] = 'wrong'
    with pytest.raises(CommandCallbackAuthenticationError):
        await report(tracker, cid, caps, '2', 0)


@pytest.mark.asyncio
async def test_heartbeats_do_not_fsync_or_persist_challenge(tmp_path):
    tracker, cid, caps = await operation(state_dir=str(tmp_path))
    a = await report(tracker, cid, caps, '1', 0)
    a = await report(tracker, cid, caps, '1', 1, a['challenge'])
    tracker._persist_command_locked = AsyncMock()
    for sequence in range(2, 8):
        a = await report(tracker, cid, caps, '1', sequence, a['challenge'])
    tracker._persist_command_locked.assert_not_awaited()
    durable, _ = tracker._journal.load()
    assert 'challenge' not in str(durable)
    assert 'monotonic' not in str(durable)
    tracker.close()


@pytest.mark.asyncio
async def test_readiness_and_cancel_routes_are_compact_and_never_arm():
    tracker, cid, caps = await operation()
    service = SimpleNamespace(review_takeoff=AsyncMock(return_value={
        hw: dict(hw_id=hw, status='ready', reason='Ready', valid_for_ms=1500, coordinated_takeoff_supported=True)
        for hw in ['1', '2']}))
    deps = SimpleNamespace(Params=SimpleNamespace(), get_command_tracker=lambda: tracker,
        get_fleet_rpc_service=lambda: service, load_config=lambda: [dict(hw_id=hw) for hw in ['1', '2']])
    app = FastAPI()
    app.include_router(create_takeoff_router(deps))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        ready = await client.get('/api/v1/commands/takeoff-readiness', params=[('target_drone_ids', '1'), ('target_drone_ids', '2')])
        assert ready.json()['ready'] and ready.json()['valid_for_ms'] == 1500
        assert (await client.get('/api/v1/commands/takeoff-readiness', params={'target_drone_ids': '3'})).status_code == 409
        assert (await client.post(f'/api/v1/commands/{cid}/cancel-launch')).json()['coordinated_takeoff']['phase'] == 'aborted'
        assert (await client.post('/api/v1/command-reports/takeoff-stage', json=dict(command_id=cid, hw_id='1', sequence=1,
            state='armed_ready', armed=True, landed_state='ON_GROUND', lease_remaining_ms=7000))).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,count,expected', [(None, 2, 'coordinated'), ('independent', 2, 'independent'), (None, 1, 'independent')])
async def test_submission_defaults_only_multiaircraft_to_coordinated(mode, count, expected):
    from tests.test_command_submission_async import _submission_deps
    from command_submission import submit_tracked_command
    from schemas import SubmitCommandRequest
    deps, tracker, coordinator = _submission_deps(fleet_config=[dict(hw_id=str(i), pos_id=i, ip='127.0.0.1') for i in range(1, count+1)])
    await coordinator.start()
    try:
        receipt = await submit_tracked_command(deps, SubmitCommandRequest(mission_type=10,
            target_drone_ids=[str(i) for i in range(1, count+1)], **({'takeoff_mode': mode} if mode else {})))
        for _ in range(100):
            status = await tracker.get_status(receipt.command_id)
            if status['acks']['received']:
                break
            await asyncio.sleep(.01)
        assert status['params']['takeoff_mode'] == expected
        assert bool(status['coordinated_takeoff']) == (expected == 'coordinated')
        assert deps.get_fleet_rpc_service().dispatch_calls[0]['command_data']['takeoff_mode'] == expected
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_preparation_rejects_old_node_without_coordinated_capability():
    from fleet_rpc import FleetRPCService
    from tests.test_fleet_rpc import _params, _drones, _callback_capabilities, _prepared_launch_payload
    async def respond(request):
        return httpx.Response(200, json=_prepared_launch_payload(request))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = FleetRPCService(_params(), client=client)
        drones = _drones(2)
        result = await service.prepare_launch(drones, dict(command_id='old-node', mission_type=10,
            takeoff_mode='coordinated'), callback_capabilities=_callback_capabilities(drones))
        assert not result['all_prepared'] and not result['preparation_tokens']
        assert all('Update aircraft' in row['summary'] for row in result['results'].values())


@pytest.mark.asyncio
async def test_recovery_fences_old_stage_and_requires_conditional_hold(monkeypatch):
    from api_routes.takeoff import fail_coordinated_takeoff
    tracker, cid, caps = await operation()
    state = tracker._commands[cid].params['_coordinated_takeoff']
    state.update(phase='released', release_at_unix_ms=1)
    rpc = SimpleNamespace(review_takeoff_recovery=AsyncMock(return_value=['2']))
    deps = SimpleNamespace(get_command_tracker=lambda: tracker, get_fleet_rpc_service=lambda: rpc,
        load_config=lambda: [dict(hw_id=hw) for hw in ['1', '2']])
    submit = AsyncMock()
    monkeypatch.setattr('command_submission.submit_tracked_command', submit)
    await fail_coordinated_takeoff(deps, cid, 'PX4 rejected climb', '1')
    request = submit.await_args.args[1]
    assert request.expected_control_command_id == cid and request.target_drone_ids == ['2']
    assert (await report(tracker, cid, caps, '2', 0))['decision'] == 'abort'


def test_machine_route_is_not_a_public_operator_bypass():
    from auth_runtime import _is_machine_endpoint
    assert _is_machine_endpoint('POST', '/api/v1/command-reports/takeoff-stage')
    assert not _is_machine_endpoint('POST', '/api/v1/commands/id/cancel-launch')
    assert not _is_machine_endpoint('GET', '/api/v1/commands/takeoff-readiness')


@pytest.mark.asyncio
@pytest.mark.parametrize('identity,remaining,expected', [('1', 3000, 'ready'), ('2', 3000, 'unavailable'), ('1', 0, 'unavailable')])
async def test_native_readiness_verifies_identity_and_fresh_ground_lease(identity, remaining, expected):
    from fleet_rpc import FleetRPCService
    from tests.test_fleet_rpc import _params, _drones
    calls = []
    async def respond(request):
        calls.append((request.method, request.url.params.get('mission_type')))
        return httpx.Response(200, json=dict(hw_id=identity, success=True, ready=True,
            summary='Ready', coordinated_takeoff_supported=True, remaining_valid_ms=remaining, server_processing_ms=0,
            observation=dict(schema_version=1, observation_id='test-ground', source='test', observed_at_ms=100,
                valid_until_ms=5000, require_global_position=True, ready=True, mission_type=10,
                admission=dict(predicate='takeoff_ground_disarmed', ready=True, checks={
                    key: True for key in ['connection_live', 'connection_continuous', 'armed_fresh', 'landed_state_fresh', 'disarmed', 'on_ground']}))))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        value = (await FleetRPCService(_params(), client=client).review_takeoff(_drones(1)))['1']
        assert value['status'] == expected
        assert calls == [('GET', '10')]


@pytest.mark.asyncio
@pytest.mark.parametrize('duration_ms,processing_ms,remaining_ms,expected', [
    (1408, 1408, 976, 'ready'), (1600, 1408, 100, 'unavailable'), (0, 1408, 976, 'unavailable'),
])
async def test_readiness_ages_only_transport_not_live_probe_duration(monkeypatch, duration_ms, processing_ms, remaining_ms, expected):
    from fleet_rpc import FleetRPCService
    from tests.test_fleet_rpc import _params, _drones
    import fleet_rpc
    clock = [100.]
    monkeypatch.setattr(fleet_rpc.time, 'monotonic', lambda: clock[0])
    async def respond(request):
        clock[0] += duration_ms / 1000
        return httpx.Response(200, json=dict(hw_id='1', success=True, ready=True,
            summary='Ready', coordinated_takeoff_supported=True, remaining_valid_ms=remaining_ms, server_processing_ms=processing_ms,
            observation=dict(schema_version=1, observation_id='test-ground', source='test', observed_at_ms=100,
                valid_until_ms=5000, require_global_position=True, ready=True, mission_type=10,
                admission=dict(predicate='takeoff_ground_disarmed', ready=True, checks={
                    key: True for key in ['connection_live', 'connection_continuous', 'armed_fresh', 'landed_state_fresh', 'disarmed', 'on_ground']}))))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        value = (await FleetRPCService(_params(), client=client).review_takeoff(_drones(1)))['1']
        assert value['status'] == expected
        if expected == 'ready':
            assert 970 <= value['valid_for_ms'] <= 976


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,landed,age,expected', [((4, 2), 2, 0, ['1']), ((3, 0), 2, 0, []), ((4, 5), 2, 0, []), ((4, 2), 1, 0, []), ((4, 2), 2, 1200, [])])
async def test_recovery_never_selects_pilot_takeover_rtl_ground_or_stale(mode, landed, age, expected):
    from fleet_rpc import FleetRPCService
    from tests.test_fleet_rpc import _params, _drones
    async def respond(request):
        return httpx.Response(200, json=dict(hw_id='1', flight_mode=(mode[0] << 16) | (mode[1] << 24),
            is_armed=True, landed_state=landed, heartbeat_age_ms=age, landed_state_age_ms=age))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await FleetRPCService(_params(), client=client).review_takeoff_recovery(_drones(1)) == expected
