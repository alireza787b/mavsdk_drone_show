"""Focused integration tests for Smart Swarm's runtime safety boundaries."""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
import types
from unittest.mock import Mock

import pytest


class _FakeLeaderKalmanFilter:
    """Minimal estimator double used to exercise the runtime integration path."""

    def __init__(self):
        self.updates = []
        self.last_update_time = None

    def update(self, measurement, measurement_time):
        if self.last_update_time is not None and measurement_time <= self.last_update_time:
            return
        self.updates.append((dict(measurement), measurement_time))
        self.last_update_time = measurement_time

    def predict(self, current_time):
        if not self.updates:
            return [0.0] * 6
        self.last_update_time = current_time
        measurement = self.updates[-1][0]
        return [
            measurement["pos_n"],
            measurement["pos_e"],
            measurement["pos_d"],
            measurement["vel_n"],
            measurement["vel_e"],
            measurement["vel_d"],
        ]


@pytest.fixture(scope="module")
def swarm_runtime():
    """Import the runtime with light doubles for optional node dependencies."""

    module_names = (
        "smart_swarm",
        "smart_swarm_src.kalman_filter",
        "psutil",
        "tenacity",
    )
    saved_modules = {name: sys.modules.get(name) for name in module_names}

    psutil_stub = types.ModuleType("psutil")
    tenacity_stub = types.ModuleType("tenacity")
    tenacity_stub.retry = lambda *_args, **_kwargs: lambda function: function
    tenacity_stub.stop_after_attempt = lambda *_args, **_kwargs: object()
    tenacity_stub.wait_fixed = lambda *_args, **_kwargs: object()
    kalman_stub = types.ModuleType("smart_swarm_src.kalman_filter")
    kalman_stub.LeaderKalmanFilter = _FakeLeaderKalmanFilter

    sys.modules["psutil"] = psutil_stub
    sys.modules["tenacity"] = tenacity_stub
    sys.modules["smart_swarm_src.kalman_filter"] = kalman_stub
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
    swarm_runtime.LEADER_KALMAN_FILTER = _FakeLeaderKalmanFilter()
    swarm_runtime.leader_unreachable_count = 3
    swarm_runtime.LAST_LEADER_SAMPLE_REJECTION_CODE = None
    swarm_runtime.IS_LEADER = False
    swarm_runtime.OWN_STATE.clear()
    swarm_runtime.FOLLOWER_TASKS.clear()
    monkeypatch.setattr(
        swarm_runtime.Params,
        "SMART_SWARM_USE_LOCAL_NED_WHEN_VALID",
        False,
    )
    yield
    swarm_runtime.FOLLOWER_TASKS.clear()


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
    # Runtime age is anchored to the producer's motion timestamp, while the
    # estimator keeps a monotonic local receipt clock.
    assert swarm_runtime.LEADER_STATE["update_time"] == pytest.approx(41.9)
    assert swarm_runtime.LEADER_STATE["received_monotonic"] == pytest.approx(42.0)
    assert swarm_runtime.LEADER_STATE["stream_seq"] == 7
    assert swarm_runtime.LEADER_STATE["source_age_sec"] == pytest.approx(0.1)
    assert swarm_runtime.leader_unreachable_count == 0
    assert len(swarm_runtime.LEADER_KALMAN_FILTER.updates) == 1
    assert swarm_runtime.LEADER_KALMAN_FILTER.updates[0][1] == pytest.approx(42.0)


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
    assert len(swarm_runtime.LEADER_KALMAN_FILTER.updates) == 1


def test_new_source_motion_updates_estimator_after_intervening_prediction(
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
    swarm_runtime.LEADER_KALMAN_FILTER.predict(42.1)

    clock.update(epoch_ms=now_ms + 200, monotonic=42.2)
    newer = _valid_global_sample(now_ms + 200)
    newer.update(stream_seq=8, position_lat=47.397752)

    assert swarm_runtime.apply_leader_state_sample(newer, "websocket")
    assert len(swarm_runtime.LEADER_KALMAN_FILTER.updates) == 2
    assert swarm_runtime.LEADER_KALMAN_FILTER.updates[-1][1] == pytest.approx(42.2)


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
    assert swarm_runtime.LEADER_KALMAN_FILTER.updates == []
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

    await swarm_runtime.execute_failsafe(drone, reason="test leader loss")

    assert events == ["offboard.stop", "action.hold"]
    led.set_color.assert_called_once_with(255, 0, 0)


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
