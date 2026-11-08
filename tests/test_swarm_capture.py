"""Capture is a frozen draft operation, never a launch or configuration write."""
import asyncio
import math
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import navpy
import pytest
from fastapi import FastAPI, HTTPException

from api_routes.swarm import create_swarm_router
from schemas import SwarmCapturePreviewRequest, SwarmConfigApplyRequest
from src.smart_swarm_contract import topology_revision
from swarm_capture_service import capture_preview, captured_assignments, planned_heights, validate_inactive_sample
from swarm_configuration_guard import configuration_lock


def _assignments():
    return [
        dict(hw_id=1, follow=0, offset_x=0., offset_y=0., offset_z=0., frame='ned'),
        dict(hw_id=2, follow=1, offset_x=5., offset_y=0., offset_z=2., frame='ned'),
        dict(hw_id=3, follow=2, offset_x=5., offset_y=0., offset_z=-.5, frame='ned'),
        dict(hw_id=4, follow=1, offset_x=0., offset_y=5., offset_z=1., frame='ned'),
        dict(hw_id=5, follow=0, offset_x=0., offset_y=0., offset_z=0., frame='body', note='unrelated'),
    ]


def _record(hw, round_index=0, *, north=0., east=0., altitude=120., heading=90., grounded=False):
    lat, lon, _ = navpy.ned2lla([north, east, 0], 35., 51., altitude, latlon_unit='deg', alt_unit='m', model='wgs84')
    emitted = 1_000_000 + round_index * 1000
    return {'sample': {
        'hw_id': int(hw), 'position_lat': float(lat), 'position_long': float(lon), 'position_alt': altitude,
        'global_position_valid': True, 'position_source': 'global_position_int', 'gps_fix_type': 3,
        'global_position_timestamp_ms': emitted, 'attitude_timestamp_ms': emitted,
        'emitted_at_ms': emitted, 'yaw_deg': heading, 'yaw_rate_deg_s': 0.,
        'velocity_north': 0., 'velocity_east': 0., 'velocity_down': 0.,
        # Per-aircraft local coordinates are deliberately unrelated and unusable.
        'local_position_north': 10000. * int(hw), 'local_position_down': -999., 'follow_mode': 1,
        'capture_activity': {'schema_version': 1, 'state': 0, 'mission': 0, 'swarm_active': False,
            'flight_mode': 4 << 16 | 3 << 24,
            'heartbeat_timestamp_ms': emitted - 900, 'landed_state_timestamp_ms': emitted - 900,
            'valid_for_ms': 14100, 'is_armed': not grounded, 'landed_state': 1 if grounded else 2},
    }, 'round_trip_ms': 1, 'received_at_ms': int(time.time() * 1000), 'received_monotonic': time.monotonic()}


def _deps(monkeypatch, *, mutate=None, commands=None):
    assignments = _assignments()
    tracker = SimpleNamespace(get_active_commands=AsyncMock(return_value=commands or []))
    rounds = []

    async def sample(drones):
        index = len(rounds)
        rounds.append([str(d['hw_id']) for d in drones])
        records = {str(d['hw_id']): _record(str(d['hw_id']), index,
                   north=(int(d['hw_id']) - 1) * 5., east=(int(d['hw_id']) - 1) * 2.) for d in drones}
        if mutate:
            mutate(records, index)
        return records

    rpc = SimpleNamespace(read_swarm_samples=AsyncMock(side_effect=sample), dispatch=AsyncMock(), prepare_launch=AsyncMock())
    deps = SimpleNamespace(load_swarm=lambda: assignments, load_config=lambda: [
        {'hw_id': str(m['hw_id']), 'ip': '127.0.0.1'} for m in assignments],
        get_command_tracker=lambda: tracker, get_fleet_rpc_service=lambda: rpc,
        save_swarm=Mock(), git_operations=Mock(), log_system_event=Mock(),
        Params=SimpleNamespace(GIT_AUTO_PUSH=False), BASE_DIR='/tmp/capture-unit',
        telemetry_data_all_drones={str(m['hw_id']): {'telemetry_available': True,
            'telemetry_timestamp_ms': int(time.time() * 1000)} for m in assignments})
    monkeypatch.setattr('swarm_capture_service.CAPTURE_DWELL_SEC', 0)
    return deps, rpc, tracker


def _request(deps, **overrides):
    return SwarmCapturePreviewRequest.model_validate({
        'revision': topology_revision(deps.load_swarm()), 'assignments': deepcopy(deps.load_swarm()),
        'cluster_id': '1', 'frame': 'ned', 'height_mode': 'keep', **overrides})


@pytest.mark.asyncio
@pytest.mark.parametrize('frame', ['ned', 'body'])
@pytest.mark.parametrize('grounded', [False, True])
async def test_capture_returns_frozen_full_draft_without_writes_or_commands(monkeypatch, frame, grounded):
    def mutate(records, index):
        for record in records.values():
            record['sample']['capture_activity'].update(is_armed=not grounded, landed_state=1 if grounded else 2)
    deps, rpc, _ = _deps(monkeypatch, mutate=mutate)
    original = deepcopy(deps.load_swarm())
    result = await capture_preview(deps, _request(deps, frame=frame, leader_hw_id='3'))
    by_id = {str(m['hw_id']): m for m in result['assignments']}
    assert result['saved'] is False and result['commands_sent'] is False
    assert result['flight_state'] == ('grounded' if grounded else 'airborne')
    assert result['recommended_height_mode'] == ('level' if grounded else 'current')
    # Recommendation does not reinterpret an explicit or legacy keep request.
    assert result['height_mode'] == 'keep'
    assert result['revision'] == topology_revision(original)
    assert result['cluster_id'] == '3'
    assert len(result['observations']) == 4
    assert {hw: m['follow'] for hw, m in by_id.items()} == {'1': 2, '2': 3, '3': 0, '4': 1, '5': 0}
    assert by_id['1']['offset_z'] == -2
    assert by_id['2']['offset_z'] == .5
    assert by_id['4']['offset_z'] == 1
    assert by_id['5'] == original[4]
    assert result['observations']['3']['planned_up_m'] == 1.5
    if frame == 'body':
        assert by_id['1']['offset_x'] == pytest.approx(-2, abs=.01)
        assert by_id['1']['offset_y'] == pytest.approx(5, abs=.01)
    else:
        assert by_id['1']['offset_x'] == pytest.approx(-5, abs=.01)
        assert by_id['1']['offset_y'] == pytest.approx(-2, abs=.01)
    assert deps.load_swarm() == original
    deps.save_swarm.assert_not_called()
    deps.git_operations.assert_not_called()
    rpc.dispatch.assert_not_awaited()
    rpc.prepare_launch.assert_not_awaited()
    assert rpc.read_swarm_samples.await_count == 2


@pytest.mark.asyncio
async def test_capture_level_and_keep_do_not_import_noisy_measured_height(monkeypatch):
    def noisy_height(records, index):
        for record in records.values():
            record['sample']['position_alt'] += 20 * index
    deps, _, _ = _deps(monkeypatch, mutate=noisy_height)
    result = await capture_preview(deps, _request(deps, height_mode='level'))
    assert all(m['offset_z'] == 0 for m in result['assignments'] if m['hw_id'] != 5)
    assert result['observations']['2']['planned_up_m'] == 2


@pytest.mark.asyncio
async def test_current_airborne_heights_use_common_msl_and_preserve_other_clusters(monkeypatch):
    def measured(records, index):
        for hw, record in records.items():
            record['sample']['position_alt'] = 120 + int(hw) * .7
            record['sample']['relative_altitude_m'] = 500 * int(hw)
    deps, _, _ = _deps(monkeypatch, mutate=measured)
    result = await capture_preview(deps, _request(deps, height_mode='current', leader_hw_id='3'))
    by_id = {str(m['hw_id']): m for m in result['assignments']}
    assert result['current_heights_available'] is True
    assert by_id['1']['offset_z'] == pytest.approx(-.7)
    assert by_id['2']['offset_z'] == pytest.approx(-.7)
    assert by_id['4']['offset_z'] == pytest.approx(2.1)
    assert by_id['5'] == deps.load_swarm()[4]
    assert result['observations']['3']['current_up_m'] == pytest.approx(1.4)


@pytest.mark.asyncio
@pytest.mark.parametrize('grounded,unstable', [(True, False), (False, True)])
async def test_current_height_capability_is_native_and_mode_specific(monkeypatch, grounded, unstable):
    def evidence(records, index):
        if grounded:
            records['2']['sample']['capture_activity'].update(is_armed=False, landed_state=1)
        if unstable:
            records['2']['sample']['position_alt'] += index * 2
    deps, _, _ = _deps(monkeypatch, mutate=evidence)
    snapshot = await capture_preview(deps, _request(deps))
    assert snapshot['current_heights_available'] is False
    assert snapshot['current_heights_reason']
    # A direct API client cannot bypass the disabled UI option.
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps, height_mode='current'))
    assert error.value.detail['code'] == 'capture_current_heights_unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario,expected_state', [
    ('mixed_members', 'mixed'),
    ('changed_epoch', 'mixed'),
    ('disarmed_airborne', 'mixed'),
    ('unstable_airborne_height', 'airborne'),
])
async def test_capture_height_recommendation_never_guesses_for_uncertain_or_unstable_states(monkeypatch, scenario, expected_state):
    def evidence(records, index):
        if scenario == 'mixed_members':
            records['2']['sample']['capture_activity'].update(is_armed=False, landed_state=1)
        elif scenario == 'changed_epoch' and index == 0:
            for record in records.values():
                record['sample']['capture_activity'].update(is_armed=False, landed_state=1)
        elif scenario == 'disarmed_airborne':
            records['2']['sample']['capture_activity'].update(is_armed=False, landed_state=2)
        elif scenario == 'unstable_airborne_height':
            records['2']['sample']['position_alt'] += index * 2
    deps, rpc, _ = _deps(monkeypatch, mutate=evidence)
    result = await capture_preview(deps, _request(deps, height_mode='level'))
    assert result['flight_state'] == expected_state
    assert result['recommended_height_mode'] is None
    assert result['current_heights_available'] is False
    assert result['height_mode'] == 'level'
    deps.save_swarm.assert_not_called()
    rpc.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_grounded_recommendation_does_not_misclassify_armed_ground_as_airborne(monkeypatch):
    def evidence(records, index):
        for record in records.values():
            record['sample']['capture_activity'].update(is_armed=True, landed_state=1)
    deps, _, _ = _deps(monkeypatch, mutate=evidence)
    result = await capture_preview(deps, _request(deps))
    assert result['flight_state'] == 'grounded'
    assert result['recommended_height_mode'] == 'level'
    assert result['current_heights_available'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value,code', [
    ('global_position_timestamp_ms', 0, 'capture_timestamp_invalid'),
    ('global_position_timestamp_ms', 9999999, 'capture_timestamp_invalid'),
    ('global_position_timestamp_ms', 998000, 'capture_position_stale'),
    ('attitude_timestamp_ms', 998000, 'capture_heading_stale'),
    ('global_position_valid', False, 'capture_position_invalid'),
    ('position_source', 'gps_raw', 'capture_position_invalid'),
    ('gps_fix_type', 2, 'capture_position_invalid'),
    ('position_alt', math.nan, 'capture_position_invalid'),
    ('velocity_north', 2., 'capture_aircraft_moving'),
    ('yaw_rate_deg_s', 10., 'capture_aircraft_turning'),
    ('hw_id', 99, 'capture_telemetry_unavailable'),
    ('capture_activity', None, 'capture_activity_unavailable'),
])
async def test_capture_rejects_unusable_sample_before_mutation(monkeypatch, field, value, code):
    deps, rpc, _ = _deps(monkeypatch, mutate=lambda records, _: records['2']['sample'].update({field: value}))
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps, frame='body'))
    assert error.value.detail['code'] == code
    assert error.value.detail['hw_id'] == '2'
    deps.save_swarm.assert_not_called()
    rpc.dispatch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('change,code', [
    ({'swarm_active': True}, 'capture_swarm_active'),
    ({'state': 1, 'mission': 2}, 'capture_action_active'),
    ({'state': 2, 'mission': 10}, 'capture_action_active'),
    ({'valid_for_ms': 0}, 'capture_activity_stale'),
    ({'landed_state': 3}, 'capture_flight_state_unavailable'),
    ({'flight_mode': 4 << 16 | 2 << 24}, 'capture_action_active'),
    ({'flight_mode': 4 << 16 | 5 << 24}, 'capture_action_active'),
    ({'flight_mode': 4 << 16 | 6 << 24}, 'capture_action_active'),
    ({'flight_mode': 4 << 16 | 8 << 24}, 'capture_action_active'),
    ({'flight_mode': 0}, 'capture_flight_state_unavailable'),
])
async def test_capture_uses_current_activity_not_saved_follow_mode(monkeypatch, change, code):
    deps, _, _ = _deps(monkeypatch,
        mutate=lambda records, _: records['2']['sample']['capture_activity'].update(change))
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps))
    assert error.value.detail['code'] == code
    deps.save_swarm.assert_not_called()


@pytest.mark.asyncio
async def test_capture_checks_position_dwell_and_sample_coherence(monkeypatch):
    def skew(records, index):
        records['2']['received_monotonic'] -= .6
    deps, _, _ = _deps(monkeypatch, mutate=skew)
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps))
    assert error.value.detail['code'] == 'capture_samples_incoherent'

    def drift(records, index):
        if index:
            records['2']['sample']['position_lat'] += .0001
    deps, _, _ = _deps(monkeypatch, mutate=drift)
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps))
    assert error.value.detail['code'] == 'capture_aircraft_moving'


@pytest.mark.asyncio
async def test_capture_rejects_repeated_position_and_turning_during_dwell(monkeypatch):
    def repeat(records, index):
        records['2']['sample']['global_position_timestamp_ms'] = records['2']['sample']['emitted_at_ms']
        if index:
            records['2']['sample']['global_position_timestamp_ms'] -= 1000
    deps, _, _ = _deps(monkeypatch, mutate=repeat)
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps))
    # The repeated source is stale before it can claim a stationary dwell.
    assert error.value.detail['code'] in {'capture_position_stale', 'capture_position_not_advancing'}

    deps, _, _ = _deps(monkeypatch,
        mutate=lambda records, index: records['2']['sample'].update(yaw_deg=90 + index * 10))
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps, frame='body'))
    assert error.value.detail['code'] == 'capture_aircraft_turning'


@pytest.mark.asyncio
async def test_capture_revision_and_topology_fail_before_native_reads(monkeypatch):
    deps, rpc, _ = _deps(monkeypatch)
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps, revision='0' * 64))
    assert error.value.detail['code'] == 'capture_revision_conflict'
    invalid = deepcopy(deps.load_swarm())
    invalid[1]['follow'] = 3
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps, assignments=invalid))
    assert error.value.detail['code'] == 'capture_topology_invalid'
    rpc.read_swarm_samples.assert_not_awaited()


@pytest.mark.asyncio
async def test_capture_requires_whole_known_fleet_draft_before_native_reads(monkeypatch):
    deps, rpc, _ = _deps(monkeypatch)
    for assignments in (deps.load_swarm()[:-1], [*deps.load_swarm(), {'hw_id': 99, 'follow': 0}]):
        with pytest.raises(HTTPException) as error:
            await capture_preview(deps, _request(deps, assignments=assignments))
        assert error.value.detail['code'] == 'capture_fleet_changed'
    deps.load_config = lambda: [{'hw_id': str(i)} for i in range(1, 5)]
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps))
    assert error.value.detail['code'] == 'capture_identity_invalid'
    rpc.read_swarm_samples.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_offboard_does_not_imply_smart_swarm_following(monkeypatch):
    deps, _, _ = _deps(monkeypatch,
        mutate=lambda records, _: records['2']['sample']['capture_activity'].update(flight_mode=6 << 16))
    assert (await capture_preview(deps, _request(deps)))['commands_sent'] is False


@pytest.mark.asyncio
async def test_capture_rechecks_revision_after_sampling(monkeypatch):
    deps, _, _ = _deps(monkeypatch)
    original = deps.get_fleet_rpc_service().read_swarm_samples.side_effect
    calls = 0
    async def changed(drones):
        nonlocal calls
        result = await original(drones)
        calls += 1
        if calls == 2:
            deps.load_swarm()[1]['offset_x'] = 88
        return result
    deps.get_fleet_rpc_service().read_swarm_samples.side_effect = changed
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps))
    assert error.value.detail['code'] == 'capture_revision_conflict'
    deps.save_swarm.assert_not_called()


@pytest.mark.asyncio
async def test_pending_start_prevents_capture_without_native_reads(monkeypatch):
    deps, rpc, _ = _deps(monkeypatch, commands=[{'mission_type': 2, 'target_drones': ['1', '2']}])
    with pytest.raises(HTTPException) as error:
        await capture_preview(deps, _request(deps))
    assert error.value.detail['code'] == 'capture_swarm_active'
    rpc.read_swarm_samples.assert_not_awaited()


def test_frozen_geometry_rederive_does_not_resample_or_change_other_clusters():
    draft = _assignments()
    heights = planned_heights(draft)
    observations = {str(i): dict(north_m=i * 5., east_m=i * 2., planned_up_m=heights[str(i)], heading_deg=90.)
                    for i in range(1, 5)}
    before = deepcopy(draft)
    result = captured_assignments(draft, observations, ['1', '2', '3', '4'], '3', 'body', 'keep')
    assert draft == before
    assert result[4] == before[4]
    assert result[0]['offset_z'] == -2
    assert result[1]['offset_z'] == .5


@pytest.mark.asyncio
@pytest.mark.parametrize('active', [False, True])
async def test_inactive_apply_guard_never_changes_ordinary_apply_semantics(monkeypatch, active):
    deps, rpc, tracker = _deps(monkeypatch)
    if active:
        tracker.get_active_commands.return_value = [{'mission_type': 2, 'target_drones': ['2']}]
    app = FastAPI()
    app.include_router(create_swarm_router(deps))
    candidate = deepcopy(deps.load_swarm())
    candidate[1]['offset_x'] = 9
    payload = {'revision': topology_revision(deps.load_swarm()), 'assignments': candidate,
               'require_inactive_hw_ids': ['2']}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.put('/api/v1/config/swarm?commit=false', json=payload)
    assert response.status_code == (409 if active else 200)
    if active:
        assert response.json()['detail']['code'] == 'capture_swarm_active'
        deps.save_swarm.assert_not_called()
    else:
        deps.save_swarm.assert_called_once()
        assert 'require_inactive_hw_ids' not in deps.save_swarm.call_args.args[0][1]
        assert {str(d['hw_id']) for d in rpc.read_swarm_samples.call_args.args[0]} == {'1', '2', '3'}


@pytest.mark.asyncio
async def test_start_registered_during_inactive_read_is_rejected_at_write(monkeypatch):
    deps, rpc, tracker = _deps(monkeypatch)
    original = rpc.read_swarm_samples.side_effect
    async def race(drones):
        samples = await original(drones)
        tracker.get_active_commands.return_value = [{'mission_type': 2, 'target_drones': ['2']}]
        return samples
    rpc.read_swarm_samples.side_effect = race
    app = FastAPI()
    app.include_router(create_swarm_router(deps))
    candidate = deepcopy(deps.load_swarm())
    candidate[1]['offset_x'] = 9
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.put('/api/v1/config/swarm?commit=false', json={
            'revision': topology_revision(deps.load_swarm()), 'assignments': candidate,
            'require_inactive_hw_ids': ['1', '2', '3', '4']})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'capture_swarm_active'
    deps.save_swarm.assert_not_called()


@pytest.mark.asyncio
async def test_inactive_apply_checks_native_activity_even_without_tracker_session(monkeypatch):
    deps, _, _ = _deps(monkeypatch,
        mutate=lambda records, _: records['2']['sample']['capture_activity'].update(swarm_active=True))
    app = FastAPI()
    app.include_router(create_swarm_router(deps))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.put('/api/v1/config/swarm?commit=false', json={
            'revision': topology_revision(deps.load_swarm()), 'assignments': deps.load_swarm(),
            'require_inactive_hw_ids': ['1', '2', '3', '4']})
    assert response.status_code == 409
    deps.save_swarm.assert_not_called()


@pytest.mark.asyncio
async def test_ordinary_active_apply_does_not_acquire_capture_preconditions(monkeypatch):
    deps, rpc, tracker = _deps(monkeypatch)
    revision = topology_revision(deps.load_swarm())
    tracker.get_active_commands.return_value = [{
        'mission_type': 2, 'target_drones': ['1', '2'],
        'params': {'smart_swarm': {'revision': revision}},
        'swarm_runtime': {'nodes': {hw: {'follow': parent, 'phase': 'active',
            'received_at_ms': int(time.time() * 1000), 'revision': revision,
            'applied_revision': revision} for hw, parent in [('1', '0'), ('2', '1')]}}}]
    app = FastAPI()
    app.include_router(create_swarm_router(deps))
    candidate = deepcopy(deps.load_swarm())
    candidate[1]['offset_x'] = 9
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.put('/api/v1/config/swarm?commit=false', json={
            'revision': revision, 'assignments': candidate})
    assert response.status_code == 200
    deps.save_swarm.assert_called_once()
    rpc.read_swarm_samples.assert_not_awaited()


@pytest.mark.asyncio
async def test_capture_http_contract_is_preview_only(monkeypatch):
    deps, rpc, _ = _deps(monkeypatch)
    app = FastAPI()
    app.include_router(create_swarm_router(deps))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/v1/config/swarm/capture-preview',
            json=_request(deps, frame='body').model_dump())
    assert response.status_code == 200
    assert response.json()['saved'] is False and response.json()['commands_sent'] is False
    assert response.json()['headings']['2'] == 90
    assert response.json()['observations']['3']['planned_up_m'] == 1.5
    deps.save_swarm.assert_not_called()
    deps.git_operations.assert_not_called()
    rpc.dispatch.assert_not_awaited()


def test_inactive_apply_requires_valid_revision_and_hardware_scope():
    from pydantic import ValidationError
    for payload in ({'require_inactive_hw_ids': ['1']},
                    {'revision': 'a' * 64, 'require_inactive_hw_ids': ['bad']},
                    {'revision': 'a' * 64, 'require_inactive_hw_ids': ['01']}):
        with pytest.raises(ValidationError):
            SwarmConfigApplyRequest.model_validate({'assignments': _assignments(), **payload})


def test_native_capture_activity_uses_existing_lifetime_not_subsecond_pose_limit():
    from src.drone_communicator import DroneCommunicator
    from src.drone_api_server import SwarmStateResponse
    communicator = DroneCommunicator.__new__(DroneCommunicator)
    communicator.params = SimpleNamespace(LOCAL_MAVLINK_STALE_TIMEOUT_SEC=15)
    communicator.drone_config = SimpleNamespace(
        hw_id=1, pos_id=1, state=0, mission=0, position={'lat': 35., 'long': 51., 'alt': 120.},
        custom_mode=4 << 16 | 3 << 24,
        velocity={'north': 0., 'east': 0., 'down': 0.}, yaw=90., global_position_valid=True,
        global_position_timestamp_ms=1_000_000, attitude_timestamp_ms=1_000_000,
        telemetry_timestamp_ms=1_000_000, gps_fix_type=3, position_source='global_position_int',
        heartbeat_timestamp_ms=999100, landed_state_timestamp_ms=999100,
        landed_state=2, is_armed=True)
    payload = communicator._build_swarm_state({'follow': 2}, 1_000_000)
    typed = SwarmStateResponse.model_validate(payload).model_dump()
    assert typed['capture_activity']['valid_for_ms'] == 14100
    assert typed['capture_activity']['swarm_active'] is False
    assert typed['attitude_timestamp_ms'] == 1_000_000
    validate_inactive_sample({'sample': typed, 'round_trip_ms': 1, 'received_monotonic': time.monotonic()}, '1')
    assert communicator._build_swarm_state({'follow': 2, 'active': True}, 1_000_000)['capture_activity']['swarm_active']
