"""Focused integration tests for Smart Swarm's runtime safety boundaries."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import types
from unittest.mock import Mock
from unittest.mock import AsyncMock

import pytest
from smart_swarm_src.control_authority import ControlAuthority


REPO_ROOT = Path(__file__).resolve().parents[1]
SIGNAL_HARNESS = REPO_ROOT / "tests" / "helpers" / "smart_swarm_signal_harness.py"


@pytest.fixture(scope="module")
def swarm_runtime():
    """Import the runtime with light doubles for optional node dependencies."""

    module_names = (
        "smart_swarm",
        "psutil",
        "tenacity",
    )
    saved_modules = {name: sys.modules.get(name) for name in module_names}

    psutil_stub = types.ModuleType("psutil")
    tenacity_stub = types.ModuleType("tenacity")
    tenacity_stub.retry = lambda *_args, **_kwargs: lambda function: function
    tenacity_stub.stop_after_attempt = lambda *_args, **_kwargs: object()
    tenacity_stub.wait_fixed = lambda *_args, **_kwargs: object()

    sys.modules["psutil"] = psutil_stub
    sys.modules["tenacity"] = tenacity_stub
    sys.modules.pop("smart_swarm", None)

    runtime = importlib.import_module("smart_swarm")
    try:
        yield runtime
    finally:
        for name, previous in saved_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.fixture(autouse=True)
def reset_swarm_runtime_state(swarm_runtime, monkeypatch):
    """Keep module globals and timing policy isolated between boundary tests."""

    swarm_runtime.LEADER_STATE.clear()
    swarm_runtime.LEADER_HW_ID = "1"
    swarm_runtime.REFERENCE_POS = {
        "latitude": 47.397742,
        "longitude": 8.545594,
        "altitude": 488.0,
    }
    swarm_runtime.leader_unreachable_count = 3
    swarm_runtime.LAST_LEADER_SAMPLE_REJECTION_CODE = None
    swarm_runtime.IS_LEADER = False
    swarm_runtime.OWN_STATE.clear()
    swarm_runtime.FOLLOWER_TASKS.clear()
    monkeypatch.setattr(swarm_runtime, 'CONTROL_AUTHORITY', None)
    monkeypatch.setattr(
        swarm_runtime.Params,
        "SMART_SWARM_USE_LOCAL_NED_WHEN_VALID",
        False,
    )
    yield
    swarm_runtime.FOLLOWER_TASKS.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['HOLD', 'RETURN_TO_LAUNCH', 'LAND'])
async def test_shutdown_without_follower_authority_preserves_pilot_mode(swarm_runtime, monkeypatch, mode):
    authority = ControlAuthority()
    authority.update_armed(True)
    authority.update_mode(mode, leader=True)
    monkeypatch.setattr(swarm_runtime, 'CONTROL_AUTHORITY', authority)
    drone = types.SimpleNamespace(offboard=types.SimpleNamespace(stop=AsyncMock()),
                                  action=types.SimpleNamespace(hold=AsyncMock()))
    result = await swarm_runtime.execute_failsafe(drone, reason='startup rejected')
    assert result.control_preserved
    drone.offboard.stop.assert_not_awaited()
    drone.action.hold.assert_not_awaited()


@pytest.mark.asyncio
async def test_pilot_takeover_during_zero_seed_prevents_offboard_start(swarm_runtime, monkeypatch):
    authority = ControlAuthority()
    authority.update_armed(True)
    authority.update_mode('HOLD', leader=False)
    monkeypatch.setattr(swarm_runtime, 'CONTROL_AUTHORITY', authority)
    async def seed(_value):
        authority.update_mode('RETURN_TO_LAUNCH', leader=False)
    drone = types.SimpleNamespace(offboard=types.SimpleNamespace(set_velocity_body=seed, start=AsyncMock()))
    assert not await swarm_runtime.ensure_offboard_active_for_follower(drone, logging.getLogger(__name__), 'test')
    drone.offboard.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_follower_handover_waits_for_action_motion_lease(swarm_runtime, monkeypatch, tmp_path):
    from src.mavsdk_server_ownership import MotionControlLease
    monkeypatch.setattr("src.mavsdk_server_ownership.tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(swarm_runtime, 'FOLLOWER_MOTION_LEASE', None)
    borrowed = MotionControlLease.acquire(swarm_runtime.Params.DEFAULT_GRPC_PORT)
    drone = types.SimpleNamespace(offboard=types.SimpleNamespace(
        set_velocity_body=AsyncMock(), start=AsyncMock()))
    try:
        assert not await swarm_runtime.ensure_offboard_active_for_follower(
            drone, logging.getLogger(__name__), 'role change')
        drone.offboard.set_velocity_body.assert_not_awaited()
        drone.offboard.start.assert_not_awaited()
        borrowed.release()
        assert await swarm_runtime.ensure_offboard_active_for_follower(
            drone, logging.getLogger(__name__), 'role change retry')
        drone.offboard.start.assert_awaited_once()
    finally:
        borrowed.release()
        await swarm_runtime.cancel_follower_tasks(logging.getLogger(__name__))


def _valid_global_sample(now_ms: int) -> dict:
    return {
        "hw_id": 1,
        "position_lat": 47.397742,
        "position_long": 8.545594,
        "position_alt": 498.0,
        "velocity_north": 1.0,
        "velocity_east": -0.5,
        "velocity_down": 0.1,
        "yaw_deg": 25.0,
        "yaw_rate_deg_s": 2.0,
        "global_position_valid": True,
        "global_position_timestamp_ms": now_ms - 100,
        "telemetry_timestamp_ms": now_ms - 50,
        "emitted_at_ms": now_ms - 20,
        "stream_seq": 7,
    }


def test_apply_leader_state_sample_accepts_fresh_authoritative_global_motion(
    swarm_runtime,
    monkeypatch,
):
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(
        swarm_runtime,
        "time",
        types.SimpleNamespace(time=lambda: now_ms / 1000.0, monotonic=lambda: 42.0),
    )

    accepted = swarm_runtime.apply_leader_state_sample(
        _valid_global_sample(now_ms),
        "websocket",
    )

    assert accepted is True
    assert swarm_runtime.LEADER_STATE["source_frame"] == "global_lla_ned"
    # Runtime prediction and freshness share the producer's motion timestamp.
    assert swarm_runtime.LEADER_STATE["update_time"] == pytest.approx(41.9)
    assert swarm_runtime.LEADER_STATE["received_monotonic"] == pytest.approx(42.0)
    assert swarm_runtime.LEADER_STATE["stream_seq"] == 7
    assert swarm_runtime.LEADER_STATE["source_age_sec"] == pytest.approx(0.1)
    assert swarm_runtime.leader_unreachable_count == 0


def test_apply_leader_state_sample_rejects_frozen_motion_timestamp_on_fresh_packet(
    swarm_runtime,
    monkeypatch,
):
    now_ms = 1_800_000_000_000
    clock = {"epoch_ms": now_ms, "monotonic": 42.0}
    monkeypatch.setattr(
        swarm_runtime,
        "time",
        types.SimpleNamespace(
            time=lambda: clock["epoch_ms"] / 1000.0,
            monotonic=lambda: clock["monotonic"],
        ),
    )
    first = _valid_global_sample(now_ms)
    assert swarm_runtime.apply_leader_state_sample(first, "websocket") is True

    clock.update(epoch_ms=now_ms + 100, monotonic=42.1)
    repeated = dict(first)
    repeated.update(
        stream_seq=8,
        telemetry_timestamp_ms=now_ms + 100,
        emitted_at_ms=now_ms + 100,
        position_lat=47.5,
    )

    assert swarm_runtime.apply_leader_state_sample(repeated, "websocket") is False
    assert swarm_runtime.LEADER_STATE["stream_seq"] == 7
    assert swarm_runtime.LEADER_STATE["pos_n"] == pytest.approx(0.0, abs=1e-6)


def test_new_source_motion_replaces_sample_after_intervening_prediction(
    swarm_runtime,
    monkeypatch,
):
    now_ms = 1_800_000_000_000
    clock = {"epoch_ms": now_ms, "monotonic": 42.0}
    monkeypatch.setattr(
        swarm_runtime,
        "time",
        types.SimpleNamespace(
            time=lambda: clock["epoch_ms"] / 1000.0,
            monotonic=lambda: clock["monotonic"],
        ),
    )
    assert swarm_runtime.apply_leader_state_sample(
        _valid_global_sample(now_ms),
        "websocket",
    )
    swarm_runtime.project_leader_motion(swarm_runtime.LEADER_STATE, now_s=42.1, max_prediction_s=1)

    clock.update(epoch_ms=now_ms + 200, monotonic=42.2)
    newer = _valid_global_sample(now_ms + 200)
    newer.update(stream_seq=8, position_lat=47.397752)

    assert swarm_runtime.apply_leader_state_sample(newer, "websocket")
    assert swarm_runtime.LEADER_STATE['stream_seq'] == 8
    assert swarm_runtime.LEADER_STATE['update_time'] == pytest.approx(42.1)


@pytest.mark.parametrize(
    ("case", "expected_code"),
    (
        ("wrong_leader", "leader_mismatch"),
        ("invalid_global_position", "global_position_invalid"),
        ("stale_global_position", "source_timestamp_stale"),
    ),
)
def test_apply_leader_state_sample_rejects_untrusted_motion_without_mutating_state(
    swarm_runtime,
    monkeypatch,
    case,
    expected_code,
):
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(
        swarm_runtime,
        "time",
        types.SimpleNamespace(time=lambda: now_ms / 1000.0, monotonic=lambda: 42.0),
    )
    sample = _valid_global_sample(now_ms)
    if case == "wrong_leader":
        sample["hw_id"] = 2
    elif case == "invalid_global_position":
        sample["global_position_valid"] = False
    else:
        sample["global_position_timestamp_ms"] = now_ms - int(
            (float(swarm_runtime.Params.SMART_SWARM_SOURCE_MAX_AGE_SEC) + 0.1) * 1000
        )

    swarm_runtime.LEADER_STATE.update({"sentinel": "unchanged"})
    accepted = swarm_runtime.apply_leader_state_sample(sample, "websocket")

    assert accepted is False
    assert swarm_runtime.LEADER_STATE == {"sentinel": "unchanged"}
    assert swarm_runtime.LAST_LEADER_SAMPLE_REJECTION_CODE == expected_code


def test_leader_motion_confidence_has_full_ramp_and_zero_regions(
    swarm_runtime,
    monkeypatch,
):
    monkeypatch.setattr(swarm_runtime.Params, "SMART_SWARM_SOURCE_MAX_AGE_SEC", 0.75)
    monkeypatch.setattr(swarm_runtime.Params, "SMART_SWARM_STREAM_PREDICT_GRACE_SEC", 1.0)

    assert swarm_runtime._leader_motion_confidence(0.75) == pytest.approx(1.0)
    assert swarm_runtime._leader_motion_confidence(1.25) == pytest.approx(0.5)
    assert swarm_runtime._leader_motion_confidence(1.75) == pytest.approx(0.0)
    assert swarm_runtime._leader_motion_confidence(10.0) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_execute_failsafe_stops_offboard_then_holds_without_raw_setpoint(
    swarm_runtime,
    monkeypatch,
):
    events = []

    class _Offboard:
        async def stop(self):
            events.append("offboard.stop")

        async def set_velocity_ned(self, *_args, **_kwargs):
            events.append("offboard.set_velocity_ned")

    class _Action:
        async def hold(self):
            events.append("action.hold")

    led = Mock()
    monkeypatch.setattr(
        swarm_runtime.LEDController,
        "get_instance",
        staticmethod(lambda: led),
    )
    drone = types.SimpleNamespace(offboard=_Offboard(), action=_Action())

    result = await swarm_runtime.execute_failsafe(drone, reason="test leader loss")

    assert events == ["offboard.stop", "action.hold"]
    assert result.completed is True
    led.set_color.assert_called_once_with(255, 0, 0)


@pytest.mark.asyncio
async def test_shutdown_handoff_attempts_hold_after_offboard_stop_timeout(
    swarm_runtime,
    monkeypatch,
):
    events = []

    class _Offboard:
        async def stop(self):
            events.append("offboard.stop.started")
            await asyncio.Event().wait()

    class _Action:
        async def hold(self):
            events.append("action.hold")

    monkeypatch.setattr(
        swarm_runtime.LEDController,
        "get_instance",
        staticmethod(lambda: Mock()),
    )
    drone = types.SimpleNamespace(offboard=_Offboard(), action=_Action())

    result = await swarm_runtime.execute_failsafe(
        drone,
        reason="test process shutdown",
        operation_timeout_sec=0.01,
    )

    assert events == ["offboard.stop.started", "action.hold"]
    assert result.offboard_stop_completed is False
    assert result.hold_requested is True
    assert result.completed is True


@pytest.mark.asyncio
async def test_runtime_boundary_repeats_authoritative_airborne_observation(
    swarm_runtime,
    monkeypatch,
):
    observation = types.SimpleNamespace(airborne=True)

    async def observe(_drone):
        return observation

    monkeypatch.setattr(swarm_runtime, "observe_authoritative_vehicle_state", observe)

    assert (
        await swarm_runtime.require_authoritative_airborne_state(object())
        is observation
    )


@pytest.mark.asyncio
async def test_runtime_boundary_rejects_non_airborne_authoritative_state(
    swarm_runtime,
    monkeypatch,
):
    observation = types.SimpleNamespace(
        airborne=False,
        as_dict=lambda: {
            "armed": True,
            "landed_state": "ON_GROUND",
            "relative_altitude_m": 0.1,
        },
    )

    async def observe(_drone):
        return observation

    monkeypatch.setattr(swarm_runtime, "observe_authoritative_vehicle_state", observe)

    with pytest.raises(RuntimeError, match="armed IN_AIR vehicle"):
        await swarm_runtime.require_authoritative_airborne_state(object())


@pytest.mark.asyncio
async def test_own_yaw_stream_requests_control_rate_and_updates_monotonic_state(
    swarm_runtime,
    monkeypatch,
):
    rate_calls = []
    sample_seen = asyncio.Event()

    class _Telemetry:
        async def set_rate_attitude_euler(self, rate_hz):
            rate_calls.append(rate_hz)

        async def attitude_euler(self):
            yield types.SimpleNamespace(yaw_deg=37.5)
            sample_seen.set()
            await asyncio.Event().wait()

    swarm_runtime.OWN_STATE.clear()
    task = asyncio.create_task(
        swarm_runtime.update_own_attitude(types.SimpleNamespace(telemetry=_Telemetry()))
    )
    await sample_seen.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert rate_calls == [float(swarm_runtime.Params.SMART_SWARM_CONTROL_RATE_HZ)]
    assert swarm_runtime.OWN_STATE["yaw_deg"] == pytest.approx(37.5)
    assert swarm_runtime.OWN_STATE["yaw_updated_monotonic"] > 0


@pytest.mark.asyncio
async def test_control_loop_fails_over_when_initial_leader_lock_never_arrives(
    swarm_runtime,
    monkeypatch,
):
    real_sleep = swarm_runtime.asyncio.sleep
    clock = {"now": 100.0}
    failover_calls = []

    async def advancing_sleep(seconds):
        clock["now"] += seconds
        await real_sleep(0)

    async def failover(_drone, _logger, reason):
        failover_calls.append(reason)
        swarm_runtime.IS_LEADER = True

    class _Offboard:
        async def set_velocity_ned(self, _command):
            return None

    swarm_runtime.IS_LEADER = False
    swarm_runtime.LEADER_STATE.clear()
    swarm_runtime.OWN_STATE.clear()
    swarm_runtime.OWN_STATE.update({
        "pos_n": 0.0,
        "pos_e": 0.0,
        "pos_d": -5.0,
        "vel_n": 0.0,
        "vel_e": 0.0,
        "vel_d": 0.0,
        "updated_monotonic": 100.0,
        "yaw_deg": 0.0,
        "yaw_updated_monotonic": 100.0,
    })
    monkeypatch.setattr(swarm_runtime.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(swarm_runtime.asyncio, "sleep", advancing_sleep)
    monkeypatch.setattr(swarm_runtime, "handle_leader_unavailability", failover)
    monkeypatch.setattr(
        swarm_runtime.Params,
        "SMART_SWARM_HARD_STALE_TIMEOUT_SEC",
        0.15,
    )
    monkeypatch.setattr(
        swarm_runtime.Params,
        "SMART_SWARM_OWN_STATE_MAX_AGE_SEC",
        10.0,
    )
    monkeypatch.setattr(
        swarm_runtime.LEDController,
        "get_instance",
        staticmethod(lambda: Mock()),
    )

    await swarm_runtime.control_loop(
        types.SimpleNamespace(offboard=_Offboard())
    )

    assert failover_calls == ["initial leader motion unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', ['recover', 'lost', 'own_stale', 'takeover', 'changed_mode', 'election'])
async def test_leader_recovery_holds_without_rewriting_roles(swarm_runtime, monkeypatch, scenario):
    runtime = swarm_runtime
    clock = {'now': 100.0}
    original_sleep = asyncio.sleep
    authority = ControlAuthority()
    authority.follower_owned = True
    authority.armed = True
    authority.landed = 'IN_AIR'
    authority.internal_hold = True
    authority.update_mode('HOLD', leader=False, now=100)
    monkeypatch.setattr(runtime, 'CONTROL_AUTHORITY', authority)
    monkeypatch.setattr(runtime, 'LEADER_FAILOVER_IN_PROGRESS', False)
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: clock['now'])
    monkeypatch.setattr(runtime.Params, 'SMART_SWARM_LEADER_RECOVERY_WAIT_SEC', 3.0)
    monkeypatch.setattr(runtime.Params, 'SMART_SWARM_LEADER_RECOVERY_STABLE_SEC', 1.0)
    monkeypatch.setattr(runtime.Params, 'SMART_SWARM_LEADER_LOSS_STRATEGY',
                        'upstream_or_hold' if scenario == 'election' else 'hold_recover')
    hold, elect = AsyncMock(), AsyncMock()
    monkeypatch.setattr(runtime, 'execute_failsafe', hold)
    monkeypatch.setattr(runtime, 'elect_new_leader', elect)
    def samples():
        now = clock['now']
        runtime.OWN_STATE.update(pos_n=0, pos_e=0, pos_d=-5,
            vel_n=0, vel_e=0, vel_d=0, yaw_deg=0,
            updated_monotonic=0 if scenario == 'own_stale' else now,
            yaw_updated_monotonic=now)
        authority.update_mode('HOLD', leader=False, now=now)
        if now >= 100.5 and scenario not in {'lost', 'election'}:
            runtime.LEADER_STATE['update_time'] = now
        if now >= 100.8 and scenario in {'takeover', 'changed_mode'}:
            authority.update_mode('RTL' if scenario == 'takeover' else 'POSITION', leader=False, now=now)
    async def sleep(seconds):
        clock['now'] += seconds
        samples()
        await original_sleep(0)
    samples()
    monkeypatch.setattr(runtime.asyncio, 'sleep', sleep)
    result = await runtime.handle_leader_unavailability(object(), logging.getLogger(__name__), 'test loss')
    assert result is (scenario in {'recover', 'election'})
    hold.assert_awaited_once()
    assert elect.await_count == (1 if scenario == 'election' else 0)
    assert runtime.LEADER_HW_ID == '1'
    assert runtime.IS_LEADER is False
    assert not runtime.LEADER_FAILOVER_IN_PROGRESS
    if scenario in {'lost', 'own_stale'}:
        assert runtime.RUNTIME_PHASE == 'holding'
        assert 'Stop Swarm' in runtime.RUNTIME_DETAIL


class _AwaitableTaskProbe:
    def __init__(self):
        self.cancel_count = 0
        self.await_count = 0

    def done(self):
        return False

    def cancel(self):
        self.cancel_count += 1

    def __await__(self):
        self.await_count += 1
        if False:
            yield None
        return None


@pytest.mark.asyncio
async def test_cancel_follower_tasks_does_not_cancel_or_await_calling_task(
    swarm_runtime,
    monkeypatch,
):
    current = _AwaitableTaskProbe()
    sibling = _AwaitableTaskProbe()
    monkeypatch.setattr(swarm_runtime.asyncio, "current_task", lambda: current)
    swarm_runtime.FOLLOWER_TASKS.update(
        {"control_task": current, "leader_update_task": sibling}
    )

    await swarm_runtime.cancel_follower_tasks(logging.getLogger(__name__))

    assert current.cancel_count == 0
    assert current.await_count == 0
    assert sibling.cancel_count == 1
    assert sibling.await_count == 1
    assert swarm_runtime.FOLLOWER_TASKS == {}


@pytest.mark.asyncio
async def test_runtime_shutdown_is_ordered_bounded_and_idempotent(
    swarm_runtime,
    monkeypatch,
):
    events = []

    async def background_task(name):
        try:
            await asyncio.Event().wait()
        finally:
            events.append(f"{name}.cancelled")

    update_task = asyncio.create_task(background_task("config"))
    leader_task = asyncio.create_task(background_task("leader"))
    control_task = asyncio.create_task(background_task("control"))
    await asyncio.sleep(0)
    swarm_runtime.FOLLOWER_TASKS.update(
        leader_update_task=leader_task,
        control_task=control_task,
    )

    class _Offboard:
        async def stop(self):
            events.append("offboard.stop")

    class _Action:
        async def hold(self):
            events.append("action.hold")

    monkeypatch.setattr(
        swarm_runtime.LEDController,
        "get_instance",
        staticmethod(lambda: Mock()),
    )
    monkeypatch.setattr(
        swarm_runtime,
        "stop_mavsdk_server",
        lambda _server, timeout_sec: events.append("mavsdk.stop"),
    )

    lifecycle = swarm_runtime.SmartSwarmRuntimeLifecycle(
        logging.getLogger(__name__),
        cancel_follower_tasks=swarm_runtime.cancel_follower_tasks,
        vehicle_handoff=swarm_runtime.execute_failsafe,
        stop_mavsdk_server=swarm_runtime.stop_mavsdk_server,
        shutdown_budget_sec=1.0,
    )
    lifecycle.drone = types.SimpleNamespace(offboard=_Offboard(), action=_Action())
    lifecycle.mavsdk_server = object()
    lifecycle.swarm_update_task = update_task

    first_result = await lifecycle.shutdown("test SIGTERM")
    second_result = await lifecycle.shutdown("duplicate shutdown")

    assert first_result is True
    assert second_result is True
    assert events.count("offboard.stop") == 1
    assert events.count("action.hold") == 1
    assert events.count("mavsdk.stop") == 1
    assert events.index("leader.cancelled") < events.index("offboard.stop")
    assert events.index("control.cancelled") < events.index("offboard.stop")
    assert events.index("offboard.stop") < events.index("action.hold")
    assert events.index("action.hold") < events.index("mavsdk.stop")
    assert swarm_runtime.FOLLOWER_TASKS == {}


@pytest.mark.asyncio
async def test_runtime_process_returns_false_when_hold_handoff_is_unconfirmed(
    swarm_runtime,
    monkeypatch,
):
    class _Offboard:
        async def stop(self):
            return None

    class _Action:
        async def hold(self):
            raise RuntimeError("injected HOLD failure")

    async def fake_runtime(lifecycle):
        lifecycle.drone = types.SimpleNamespace(
            offboard=_Offboard(),
            action=_Action(),
        )

    monkeypatch.setattr(
        swarm_runtime.LEDController,
        "get_instance",
        staticmethod(lambda: Mock()),
    )
    monkeypatch.setattr(swarm_runtime, "run_smart_swarm", fake_runtime)

    completed = await swarm_runtime.run_smart_swarm_process(
        logging.getLogger(__name__)
    )

    assert completed is False


def test_shutdown_signal_handler_uses_first_signal_and_cancels_once(swarm_runtime):
    callbacks = {}

    class _Loop:
        def add_signal_handler(self, handled_signal, callback, *args):
            callbacks[handled_signal] = (callback, args)

    class _Task:
        cancel_count = 0

        def cancel(self):
            self.cancel_count += 1

    task = _Task()
    state, installed = swarm_runtime.install_shutdown_signal_handlers(
        _Loop(),
        task,
        logging.getLogger(__name__),
    )

    callback, args = callbacks[signal.SIGTERM]
    callback(*args)
    repeated_callback, repeated_args = callbacks[signal.SIGINT]
    repeated_callback(*repeated_args)

    assert state.received_signal == "SIGTERM"
    assert installed == [signal.SIGTERM, signal.SIGINT]
    assert task.cancel_count == 1


def test_real_sigterm_stops_setpoints_then_hands_vehicle_to_hold(tmp_path):
    process = subprocess.Popen(
        [sys.executable, str(SIGNAL_HARNESS), str(tmp_path)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    deadline = time.monotonic() + 5.0
    while not (tmp_path / "started").exists() and time.monotonic() < deadline:
        if process.poll() is not None:
            break
        time.sleep(0.01)

    assert (tmp_path / "started").exists(), process.communicate(timeout=1)
    process.send_signal(signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 0, (stdout, stderr)
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["events"] == [
        "control.cancelled",
        "offboard.stop",
        "action.hold",
    ]
