import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

import sequential_return_service as module
from api_routes.swarm_runtime import create_swarm_runtime_router
from sequential_return_service import SequentialReturnRequest, SequentialReturnService
from command_tracker import CommandTracker


def make_service(tmp_path, monkeypatch, *, fail_hold=False):
    calls = []
    statuses = {}

    async def submit(deps, command):
        command_id = f"cmd-{len(calls)}"
        calls.append((command, asyncio.get_running_loop().time()))
        now = int(time.time() * 1000)
        succeeded = not (fail_hold and command.mission_type == 102)
        statuses[command_id] = {
            "status": "completed" if succeeded else "failed",
            "phase": "terminal",
            "error_summary": "Hold rejected" if fail_hold else None,
            "timeout_at": now + 60000,
            "completed_at": now,
            "executions": {"details": {hw_id: {"success": succeeded} for hw_id in command.target_drone_ids}},
        }
        return SimpleNamespace(command_id=command_id)

    monkeypatch.setattr(module, "submit_tracked_command", submit)
    tracker = SimpleNamespace(get_status=AsyncMock(side_effect=lambda key: statuses[key]),
                              get_active_commands=AsyncMock(return_value=[]),
                              lookup_command_by_idempotency_key=AsyncMock(return_value=None))

    async def get_recovery_progress(command_id, *, idempotency_key=None, dispatch_ids=()):
        status = None
        if command_id:
            status = await tracker.get_status(command_id)
            if status:
                status = {'command_id': command_id, **status}
        elif idempotency_key:
            status = await tracker.lookup_command_by_idempotency_key(idempotency_key)
        return status, {key: statuses[key].get('submitted_at') for key in dispatch_ids if key in statuses}

    tracker.get_recovery_progress = get_recovery_progress
    deps = SimpleNamespace(
        Params=SimpleNamespace(GCS_COMMAND_STATE_DIR=str(tmp_path)),
        load_config=lambda: [{"hw_id": "1"}, {"hw_id": "2"}],
        get_command_tracker=lambda: tracker,
        telemetry_lock=threading.Lock(),
        telemetry_data_all_drones={
            key: dict(is_armed=True, flight_mode=(4 << 16) | (3 << 24),
                      heartbeat_timestamp_ms=int(time.time() * 1000))
            for key in ("1", "2")
        },
    )
    service = SequentialReturnService(deps)
    deps.sequential_return_service = service
    return service, calls, deps


def request(**overrides):
    return SequentialReturnRequest(**{
        "target_drone_ids": ["2", "1"], "delay_sec": 1, "idempotency_key": "test-return",
        **overrides,
    })


@pytest.mark.asyncio
async def test_five_readers_distinguish_tracking_from_dispatch_without_full_serialization(tmp_path, monkeypatch):
    service, _, deps = make_service(tmp_path, monkeypatch)
    tracker = CommandTracker()
    deps.get_command_tracker = lambda: tracker
    rtl_id = await tracker.create_command(mission_type=104, target_drones=['2'])
    job = {'return_id': 'existing', 'target_drone_ids': ['2', '1'], 'state': 'dispatching',
           'hold_command_id': None, 'commands': [{'hw_id': '2', 'command_id': rtl_id}]}
    monkeypatch.setattr(tracker, '_command_to_dict', lambda *_: pytest.fail('Full tracker snapshot serialized'))

    async def counts():
        snapshots = await asyncio.gather(*(service.observe(job.copy()) for _ in range(5)))
        return [snapshot['rtl_dispatched_count'] for snapshot in snapshots]

    assert await counts() == [0] * 5
    assert await tracker.mark_submitted(rtl_id)
    assert await counts() == [1] * 5
    assert 'rtl_dispatched_count' not in job
    job['commands'] = [{'hw_id': '2', 'command_id': 'no-longer-retained'}]
    assert await counts() == [None] * 5


@pytest.mark.asyncio
async def test_hold_then_ordered_rtl_with_minimum_interval(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch)
    job = await service.start(request())
    await service.task
    assert [(c.mission_type, c.target_drone_ids) for c, _ in calls] == [
        (102, ["2", "1"]), (104, ["2"]), (104, ["1"]),
    ]
    assert calls[2][1] - calls[1][1] >= 1
    assert service.get(job["return_id"])["state"] == "dispatched"
    assert service.latest()["commands"][0]["hw_id"] == "2"


@pytest.mark.asyncio
async def test_rejection_stops_queue_before_any_rtl(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch, fail_hold=True)
    await service.start(request())
    await service.task
    assert len(calls) == 1
    assert service.latest()["state"] == "failed"
    assert service.latest()["message"] == "Hold not confirmed: Hold rejected. No RTL commands sent."


def test_offline_return_target_is_named_without_implying_any_rtl_was_sent():
    status = {"acks": {"details": {"1": {"category": "accepted"},
                                     "3": {"category": "offline", "message": "No route to host"}}}}
    assert module.command_failure_reason(status) == "Drone 3: unavailable"


@pytest.mark.asyncio
async def test_omitted_active_follower_is_rejected_before_any_hold(tmp_path, monkeypatch):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    deps.get_command_tracker().get_active_commands.return_value = [{
        'command_id': 'swarm', 'mission_type': 2, 'target_drones': ['1','2'],
        'params': {'smart_swarm': {'assignments': [{'hw_id':'1','follow':'0'}, {'hw_id':'2','follow':'1'}]}},
    }]
    with pytest.raises(HTTPException) as exc:
        await service.start(request(target_drone_ids=['1']))
    assert exc.value.status_code == 409 and 'Include following aircraft 2' in exc.value.detail
    assert calls == []


@pytest.mark.asyncio
async def test_uncertain_first_rtl_is_not_reported_as_never_sent(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch)
    original_submit = module.submit_tracked_command
    async def uncertain_submit(deps, command):
        if command.mission_type == 104:
            raise RuntimeError('RTL receipt uncertain')
        return await original_submit(deps, command)
    monkeypatch.setattr(module, 'submit_tracked_command', uncertain_submit)
    await service.start(request())
    await service.task
    job = service.latest()
    assert job['uncertain_dispatch_hw_id'] == '2'
    assert job['commands'] == []
    assert 'may still be delivered' in job['message']


@pytest.mark.asyncio
@pytest.mark.parametrize('result_delay_ms', [31500, 60000, 60001])
async def test_hold_uses_tracked_deadline_and_requires_a_timely_terminal_result(tmp_path, monkeypatch, result_delay_ms):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    tracker = deps.get_command_tracker()
    default_status = tracker.get_status.side_effect
    finished = int(time.time() * 1000)
    submitted = finished - result_delay_ms

    async def get_status(command_id):
        status = default_status(command_id)
        if command_id == 'cmd-0':
            return {**status, 'submitted_at': submitted,
                    'timeout_at': submitted + 60000, 'completed_at': finished}
        return status

    tracker.get_status.side_effect = get_status
    await service.start(request())
    await service.task
    if result_delay_ms <= 60000:
        assert service.latest()['state'] == 'dispatched'
        assert [(item.mission_type, item.target_drone_ids) for item, _ in calls] == [
            (102, ['2', '1']), (104, ['2']), (104, ['1']),
        ]
    else:
        assert service.latest()['state'] == 'failed'
        assert 'after its tracked confirmation deadline' in service.latest()['message']
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_pending_hold_uses_revised_tracker_deadline_and_records_late_report_for_display(tmp_path, monkeypatch):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    tracker = deps.get_command_tracker()
    now = int(time.time() * 1000)
    pending_status = dict(status='in_progress', phase='in_progress', submitted_at=now - 60000,
                          timeout_at=now + 250, executions={'details': {'2': {'success': True}}})
    current_status = [pending_status]
    hold_sampled = asyncio.Event()

    async def get_status(command_id):
        assert command_id == 'cmd-0'
        hold_sampled.set()
        return current_status[0]

    tracker.get_status.side_effect = get_status
    monkeypatch.setattr(module, 'CONFIRMATION_POLL_SEC', .001)
    submitted = await service.start(request())
    await hold_sampled.wait()
    in_progress = await service.observe(service.latest())
    assert in_progress['hold_confirmation']['confirmed_now'] == ['2']
    assert in_progress['hold_confirmation']['pending_now'] == ['1']
    assert in_progress['hold_confirmation']['deadline_at_ms'] == now + 250
    current_status[0] = {**pending_status, 'timeout_at': now - 1}
    await asyncio.wait_for(service.task, timeout=.2)
    stopped = service.get(submitted['return_id'])
    assert stopped['state'] == 'failed'
    assert 'deadline expired' in stopped['message']
    assert stopped['hold_confirmation']['deadline_at_ms'] == now - 1
    assert stopped['hold_confirmation']['confirmed_at_stop'] == ['2']
    assert stopped['hold_confirmation']['pending_at_stop'] == ['1']
    assert len(calls) == 1

    current_status[0] = {**current_status[0], 'status': 'timeout', 'phase': 'terminal',
                         'late_reports': {'executions': {'details': {'1': {'success': True}}}}}
    before = service.path.read_bytes()
    reported = await service.observe(service.get(submitted['return_id']))
    assert reported['state'] == 'failed'
    assert reported['commands'] == []
    assert reported['hold_confirmation']['confirmed_at_stop'] == ['2']
    assert reported['hold_confirmation']['pending_at_stop'] == ['1']
    assert reported['hold_confirmation']['confirmed_now'] == ['2', '1']
    assert reported['hold_confirmation']['pending_now'] == []
    assert service.path.read_bytes() == before
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_legacy_stop_reports_current_evidence_without_inventing_history(tmp_path, monkeypatch):
    service, _, deps = make_service(tmp_path, monkeypatch)
    deps.get_command_tracker().get_status.side_effect = None
    deps.get_command_tracker().get_status.return_value = {
        'timeout_at': 6500,
        'executions': {'details': {'1': {'success': True}, '3': {'success': True}}},
    }
    job = {'return_id': 'previous', 'target_drone_ids': ['2', '1'], 'state': 'failed',
           'hold_command_id': 'hold', 'commands': []}
    reported = await service.observe(job.copy())
    assert 'hold_confirmation' not in job
    assert reported['hold_confirmation'] == dict(deadline_at_ms=6500, stopped_at_ms=None,
                                                  confirmed_at_stop=None, pending_at_stop=None,
                                                  confirmed_now=['1'], pending_now=['2'])


@pytest.mark.asyncio
async def test_stopped_hold_with_uncertain_receipt_recovers_only_by_lookup(tmp_path, monkeypatch):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    tracker = deps.get_command_tracker()
    tracker.lookup_command_by_idempotency_key.return_value = {
        'command_id': 'existing-hold', 'executions': {'details': {'2': {'success': True}}},
    }
    job = {'return_id': 'stopped-before-receipt', 'target_drone_ids': ['2', '1'], 'state': 'cancelled',
           'hold_command_id': None, 'commands': []}
    reported = await service.observe(job.copy())
    tracker.lookup_command_by_idempotency_key.assert_awaited_once_with('sequential-return:stopped-before-receipt:hold')
    assert reported['hold_command_id'] == 'existing-hold'
    assert reported['hold_confirmation']['confirmed_now'] == ['2']
    assert reported['hold_confirmation']['pending_now'] == ['1']
    assert reported['hold_confirmation']['confirmed_at_stop'] is None
    assert calls == []


@pytest.mark.asyncio
async def test_takeover_while_hold_receipts_are_pending_stops_before_any_rtl(tmp_path, monkeypatch):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    tracker = deps.get_command_tracker()
    now = int(time.time() * 1000)
    telemetry = deps.telemetry_data_all_drones
    tracker.get_status.side_effect = None
    tracker.get_status.return_value = dict(status='in_progress', phase='in_progress', submitted_at=now - 100,
                                          timeout_at=now + 60000)
    hold_sampled = asyncio.Event()
    observe_telemetry = service._observe_hold_telemetry

    def observe(*args):
        ready = observe_telemetry(*args)
        if ready:
            hold_sampled.set()
        return ready

    monkeypatch.setattr(service, '_observe_hold_telemetry', observe)
    monkeypatch.setattr(module, 'CONFIRMATION_POLL_SEC', .001)
    await service.start(request())
    await hold_sampled.wait()
    telemetry['2'] = {**telemetry['2'], 'flight_mode': 1 << 16, 'heartbeat_timestamp_ms': now - 200}
    await asyncio.sleep(.005)
    assert service.latest()['state'] == 'holding'
    telemetry['2']['heartbeat_timestamp_ms'] = int(time.time() * 1000)
    await asyncio.wait_for(service.task, timeout=.2)
    assert 'left armed Hold' in service.latest()['message']
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_takeover_while_first_rtl_confirmation_is_pending_stops_rest(tmp_path, monkeypatch):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    tracker = deps.get_command_tracker()
    default_status = tracker.get_status.side_effect
    rtl_sampled = asyncio.Event()

    async def get_status(command_id):
        if command_id == 'cmd-1':
            rtl_sampled.set()
            return {'status': 'in_progress', 'phase': 'in_progress'}
        return default_status(command_id)

    tracker.get_status.side_effect = get_status
    monkeypatch.setattr(module, 'CONFIRMATION_POLL_SEC', .001)
    await service.start(request())
    await asyncio.wait_for(rtl_sampled.wait(), timeout=1)
    deps.telemetry_data_all_drones['1']['flight_mode'] = 1 << 16
    await asyncio.wait_for(service.task, timeout=1)
    stopped = service.latest()
    assert stopped['state'] == 'failed'
    assert 'no longer in armed Hold' in stopped['message']
    assert [entry['hw_id'] for entry in stopped['commands']] == ['2']
    assert [(item.mission_type, item.target_drone_ids) for item, _ in calls] == [(102, ['2', '1']), (104, ['2'])]


@pytest.mark.asyncio
async def test_cancel_in_flight_rtl_preserves_uncertainty_and_never_replays(tmp_path, monkeypatch):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    original_submit = module.submit_tracked_command
    rtl_entered = asyncio.Event()

    async def submit(deps, command):
        receipt = await original_submit(deps, command)
        if command.mission_type == 104:
            rtl_entered.set()
            await asyncio.Future()
        return receipt

    monkeypatch.setattr(module, 'submit_tracked_command', submit)
    job = await service.start(request())
    await asyncio.wait_for(rtl_entered.wait(), timeout=1)
    active = await service.observe(service.latest())
    assert active['uncertain_dispatch_hw_id'] is None
    stopped = await service.cancel(job['return_id'])
    assert stopped['state'] == 'cancelled'
    assert stopped['commands'] == []
    assert stopped['uncertain_dispatch_hw_id'] == '2'
    assert 'may still be delivered' in stopped['message']
    restored = SequentialReturnService(deps)
    assert await restored.start(request()) == stopped
    assert restored.task is None
    assert [(item.mission_type, item.target_drone_ids) for item, _ in calls] == [(102, ['2', '1']), (104, ['2'])]


@pytest.mark.asyncio
async def test_new_following_work_during_hold_blocks_before_first_rtl(tmp_path, monkeypatch):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    follower = {'command_id':'new-follow', 'mission_type':2, 'target_drones':['3'],
                'params':{'smart_swarm':{'assignments':[{'hw_id':'1','follow':'0'},{'hw_id':'3','follow':'1'}]}}}
    deps.get_command_tracker().get_active_commands.side_effect = [[], [follower]]
    await service.start(request())
    await service.task
    assert len(calls) == 1 and calls[0][0].mission_type == 102
    assert 'Include following aircraft 3' in service.latest()['message']
    assert service.latest()['commands'] == []


@pytest.mark.asyncio
async def test_first_rtl_failure_stops_remaining_aircraft(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch)
    original_wait = service._wait_command

    async def wait_command(job, command, **kwargs):
        if command["hw_id"] == "2":
            raise RuntimeError("PX4 rejected Return")
        return await original_wait(job, command, **kwargs)

    service._wait_command = wait_command
    await service.start(request())
    await service.task
    assert [(c.mission_type, c.target_drone_ids) for c, _ in calls] == [(102, ["2", "1"]), (104, ["2"])]
    assert service.latest()["state"] == "failed"
    assert service.latest()["message"] == "PX4 rejected Return"


@pytest.mark.asyncio
async def test_cancel_pending_preserves_issued_command(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch)
    job = await service.start(request(delay_sec=10))
    while service.latest()["state"] != "waiting":
        await asyncio.sleep(0)
    await service.cancel(job["return_id"])
    assert [c.mission_type for c, _ in calls] == [102, 104]
    assert service.latest()["state"] == "cancelled"
    assert len(service.latest()["commands"]) == 1


@pytest.mark.asyncio
async def test_retry_and_refresh_do_not_duplicate_and_restart_does_not_resume(tmp_path, monkeypatch):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    job = await service.start(request(delay_sec=10))
    assert (await service.start(request(delay_sec=10)))["return_id"] == job["return_id"]
    with pytest.raises(HTTPException) as conflict:
        await service.start(request(delay_sec=20))
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException):
        await service.start(request(idempotency_key="another"))
    while service.latest()["state"] != "waiting":
        await asyncio.sleep(0)
    restored = SequentialReturnService(deps)
    assert restored.latest()["state"] == "interrupted"
    assert restored.task is None
    await service.close()
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["pilot", "disarm", "stale"])
async def test_waiting_aircraft_takeover_or_link_loss_stops_remaining(tmp_path, monkeypatch, change):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    original_command = service._command

    async def command(job, mission, targets, suffix):
        command_id = await original_command(job, mission, targets, suffix)
        if mission.value == 104:
            if change == "pilot":
                deps.telemetry_data_all_drones["1"]["flight_mode"] = 3 << 16
            elif change == "disarm":
                deps.telemetry_data_all_drones["1"]["is_armed"] = False
            else:
                deps.telemetry_data_all_drones["1"].update(
                    heartbeat_timestamp_ms=1,
                    heartbeat_last_seen=int(time.time() * 1000),
                    telemetry_timestamp_ms=int(time.time() * 1000),
                )
        return command_id

    service._command = command
    await service.start(request())
    await service.task
    assert len(calls) == 2
    assert service.latest()["state"] == "failed"


@pytest.mark.asyncio
async def test_new_operator_command_cancels_pending_return(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch)
    await service.start(request(delay_sec=10))
    while service.latest()["state"] != "waiting":
        await asyncio.sleep(0)
    await service.supersede(["99"])
    assert service.latest()["state"] == "waiting"
    await service.supersede(["1"])
    assert service.latest()["state"] == "cancelled"
    assert 'A newer command' in service.latest()['message']
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_routes_default_interval_and_retry(tmp_path, monkeypatch):
    service, _, deps = make_service(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(create_swarm_runtime_router(deps))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        route = "/api/v1/swarm/runtime/sequential-return"
        assert (await client.get(route)).json() is None
        response = await client.post(route, json={"target_drone_ids": ["2", "1"], "idempotency_key": "api"})
        assert response.status_code == 202
        job = response.json()
        assert job["delay_sec"] == 10
        detail = (await client.get(f"{route}/{job['return_id']}")).json()
        assert detail["target_drone_ids"] == ["2", "1"]
        assert detail["hold_confirmation"]["confirmed_at_stop"] is None
        assert (await client.post(f"{route}/{job['return_id']}/cancel")).json()["state"] == "cancelled"


@pytest.mark.parametrize("changes", [
    {"target_drone_ids": []}, {"target_drone_ids": ["1", "01"]},
    {"target_drone_ids": ["0"]}, {"delay_sec": 0}, {"delay_sec": float("nan")},
    {"delay_sec": 301},
])
def test_invalid_requests(changes):
    with pytest.raises(ValidationError):
        request(**changes)
