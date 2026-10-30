"""No aircraft: bounded node barrier and callback failures use fake SDK state."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import time

import pytest

from src.action_runners.coordinated_takeoff import CoordinatedTakeoffGate
from src.action_safety import ActionSafetyError
from src.coordinated_takeoff_contract import TakeoffStageResponse


def gate():
    return CoordinatedTakeoffGate(dict(command_id="test-op", hw_id="2", url="http://127.0.0.1/callback", capability="x" * 43))


def ground():
    return SimpleNamespace(complete=True, armed=True, on_ground=True, landed_state="ON_GROUND")


@pytest.mark.asyncio
@pytest.mark.parametrize("auto,expected", [(10,8), (4,3.5), (-1,8)])
async def test_actual_px4_timeout_caps_local_lease_without_writing_parameters(auto, expected):
    item = gate()
    drone = SimpleNamespace(param=SimpleNamespace(get_param_float=AsyncMock(return_value=auto)),
        telemetry=SimpleNamespace(set_rate_landed_state=AsyncMock(), set_rate_position=AsyncMock()))
    await item.prepare(drone)
    assert item.lease_seconds == expected
    drone.param.get_param_float.assert_awaited_once_with("COM_DISARM_PRFLT")
    drone.telemetry.set_rate_landed_state.assert_awaited_once_with(5)
    drone.telemetry.set_rate_position.assert_awaited_once_with(5)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [1, float("nan")])
async def test_unusable_auto_disarm_window_rejects_before_arm(value):
    item = gate()
    drone = SimpleNamespace(param=SimpleNamespace(get_param_float=AsyncMock(return_value=value)))
    with pytest.raises(ActionSafetyError):
        await item.prepare(drone)


@pytest.mark.asyncio
async def test_missing_px4_timeout_rejects_before_arm():
    item = gate()
    with pytest.raises(ActionSafetyError):
        await item.prepare(SimpleNamespace())


@pytest.mark.asyncio
async def test_lease_starts_at_arm_attempt_and_bounds_a_stuck_arm_rpc(monkeypatch):
    monkeypatch.delattr(asyncio, "timeout", raising=False)
    item = gate()
    item.lease_seconds = .01
    async def arm(on_attempt):
        assert item.deadline is None
        on_attempt()
        await asyncio.sleep(1)
    with pytest.raises(ActionSafetyError, match="arming window expired"):
        await item.arm(arm)


@pytest.mark.asyncio
async def test_external_arm_cancellation_remains_cancellation_and_cancels_the_rpc(monkeypatch):
    monkeypatch.delattr(asyncio, "timeout", raising=False)
    item = gate()
    item.lease_seconds = 8
    started, stopped = asyncio.Event(), asyncio.Event()
    async def arm(on_attempt):
        on_attempt()
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    task = asyncio.create_task(item.arm(arm))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_successful_arm_cancels_its_expiry_timer(monkeypatch):
    monkeypatch.delattr(asyncio, "timeout", raising=False)
    item = gate()
    item.lease_seconds = .01
    async def arm(on_attempt):
        on_attempt()
    await item.arm(arm)
    await asyncio.sleep(.02)
    assert not asyncio.current_task().cancelled()


@pytest.mark.asyncio
async def test_waits_for_release_then_returns_fresh_ground_evidence(monkeypatch):
    item = gate()
    item.deadline = time.monotonic() + 1
    release_at = int((time.time()+.05)*1000)
    async def report(*args):
        return TakeoffStageResponse(decision="release", release_at_unix_ms=release_at,
            server_time_unix_ms=int(time.time()*1000), challenge="z"*16)
    item.report = AsyncMock(side_effect=report)
    observe = AsyncMock(return_value=ground())
    result = await item.wait_for_release(None, observe)
    assert result.on_ground and item.released
    assert observe.await_count >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["abort", "clock_skew", "expired_release", "changed_release", "missing_armed", "expired_lease"])
async def test_never_releases_invalid_or_expired_group(mode):
    item = gate()
    item.deadline = time.monotonic() + (-1 if mode=="expired_lease" else 1)
    sample = ground()
    if mode == "missing_armed":
        sample.armed = False
    count = 0
    async def report(*args):
        nonlocal count
        count += 1
        if mode == "abort":
            return TakeoffStageResponse(decision="abort", reason="Peer failed")
        return TakeoffStageResponse(decision="release",
            release_at_unix_ms=int((time.time()+(-1 if mode=="expired_release" else .4+count*.01))*1000),
            server_time_unix_ms=int((time.time()+(2 if mode=="clock_skew" else 0))*1000), challenge="z"*16)
    item.report = AsyncMock(side_effect=report)
    with pytest.raises(ActionSafetyError):
        await item.wait_for_release(None, AsyncMock(return_value=sample))
    assert not item.released


@pytest.mark.parametrize("fault", [None, "new_command", "pilot_position", "rtl", "land", "stale", "unknown", "completed"])
def test_conditional_hold_fences_effective_owner_and_fresh_native_takeoff(fault):
    from src.drone_api_server import DroneAPIServer
    from src.enums import Mission
    api = object.__new__(DroneAPIServer)
    now = int(time.time()*1000)
    api.drone_config = SimpleNamespace(current_command_id=None, mission=Mission.TAKE_OFF.value,
        drone_setup=SimpleNamespace(_active_mission_command_id="original"), is_armed=True,
        landed_state=2, heartbeat_timestamp_ms=now, landed_state_timestamp_ms=now,
        custom_mode=(4<<16)|(2<<24))
    c = api.drone_config
    if fault == "new_command": c.current_command_id = "new"
    if fault == "pilot_position": c.custom_mode = 3<<16
    if fault == "rtl": c.custom_mode = (4<<16)|(5<<24)
    if fault == "land": c.custom_mode = (4<<16)|(6<<24)
    if fault == "stale": c.heartbeat_timestamp_ms = now-2000
    if fault == "unknown": c.landed_state = None
    if fault == "completed": c.drone_setup._active_mission_command_id = None
    assert api._conditional_takeoff_hold_ready("original") is (fault is None)
