"""The direct native FC-reboot action requires bounded live safe-state evidence."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import actions
from src.action_safety import ActionSafetyError


async def _stable(value):
    yield value
    await asyncio.Event().wait()


def _drone(*, armed=False, landed_state="ON_GROUND", connected=True, landed_capability=True):
    drone = SimpleNamespace(
        action=SimpleNamespace(reboot=AsyncMock()),
        core=SimpleNamespace(connection_state=lambda: _stable(SimpleNamespace(is_connected=connected))),
        armed_value=armed,
    )
    drone.telemetry = SimpleNamespace(armed=lambda: _stable(drone.armed_value))
    if landed_capability:
        drone.telemetry.landed_state = lambda: _stable(landed_state)
    return drone


@pytest.fixture(autouse=True)
def _bounded_action_fixture(monkeypatch):
    original_sleep = asyncio.sleep

    async def yield_without_delay(_duration):
        await original_sleep(0)

    monkeypatch.setattr(actions, "_optional_led_controller", lambda: None)
    monkeypatch.setattr(actions.asyncio, "sleep", yield_without_delay)
    monkeypatch.setattr(actions, "ACTION_STATE_OBSERVATION_TIMEOUT_SEC", 0.03)
    monkeypatch.setattr(actions, "_LAST_ACTION_FAILURE", None)
    monkeypatch.setattr(actions, "_LAST_FINAL_VEHICLE_STATE", None)
    monkeypatch.setattr(actions, "RETURN_CODE", 0)


async def test_direct_fc_reboot_allows_confirmed_disarmed_ground_without_gps_or_health():
    drone = _drone()
    await actions.reboot(drone, fc_flag=True, sys_flag=False)
    drone.action.reboot.assert_awaited_once()


@pytest.mark.parametrize("force_reboot", [True, False])
async def test_direct_fc_reboot_armed_state_cannot_be_forced(force_reboot):
    drone = _drone(armed=True)
    with pytest.raises(ActionSafetyError) as failure:
        await actions.reboot(drone, fc_flag=True, sys_flag=False, force_reboot=force_reboot)
    assert failure.value.code == "FC_REBOOT_REQUIRES_SAFE_STATE"
    assert failure.value.phase == "precondition"
    drone.action.reboot.assert_not_awaited()


@pytest.mark.parametrize("armed,landed", [(None, "ON_GROUND"), (False, None), (False, "IN_AIR"), (False, "LANDING"), (False, "UNKNOWN")])
async def test_direct_fc_reboot_does_not_infer_ground_or_disarm(armed, landed):
    drone = _drone(armed=armed, landed_state=landed)
    with pytest.raises(ActionSafetyError):
        await actions.reboot(drone, fc_flag=True, sys_flag=False)
    drone.action.reboot.assert_not_awaited()


async def test_direct_fc_reboot_rejects_disconnected_state():
    drone = _drone(connected=False)
    with pytest.raises(ActionSafetyError) as failure:
        await actions.reboot(drone, fc_flag=True, sys_flag=False)
    assert failure.value.code == "FC_REBOOT_STATE_UNAVAILABLE"
    drone.action.reboot.assert_not_awaited()


async def test_available_but_silent_landed_authority_times_out_and_blocks():
    drone = _drone()

    async def silent_landed_state():
        await asyncio.Event().wait()
        yield "ON_GROUND"

    drone.telemetry.landed_state = silent_landed_state
    started = time.monotonic()
    with pytest.raises(ActionSafetyError) as failure:
        await actions.reboot(drone, fc_flag=True, sys_flag=False)
    assert time.monotonic() - started < 0.5
    assert failure.value.code == "FC_REBOOT_STATE_UNAVAILABLE"
    drone.action.reboot.assert_not_awaited()


async def test_replayed_stale_native_landed_state_does_not_admit_reboot():
    drone = _drone(landed_state=SimpleNamespace(
        name="ON_GROUND", _mds_source_timestamp_ms=int(time.time()*1000) - 10_000,
    ))
    with pytest.raises(ActionSafetyError) as failure:
        await actions.reboot(drone, fc_flag=True, sys_flag=False)
    assert failure.value.code == "FC_REBOOT_STATE_UNAVAILABLE"
    assert failure.value.evidence["observation"]["fields"]["landed_state"]["freshness"] == "stale"
    drone.action.reboot.assert_not_awaited()


async def test_missing_landed_capability_uses_live_disarm_without_inventing_ground(monkeypatch):
    drone = _drone(landed_capability=False)
    original_observe = actions.observe_authoritative_vehicle_state
    observer = AsyncMock(side_effect=original_observe)
    monkeypatch.setattr(actions, "observe_authoritative_vehicle_state", observer)
    await actions.reboot(drone, fc_flag=True, sys_flag=False)
    assert observer.await_args.kwargs["required_fields"] == ("armed",)
    drone.action.reboot.assert_awaited_once()


async def test_state_is_sampled_after_preparation_immediately_before_reboot(monkeypatch):
    drone = _drone(armed=False)
    original_sleep = asyncio.sleep

    async def arm_during_preparation(duration):
        if duration == 0.5:
            drone.armed_value = True
        await original_sleep(0)

    monkeypatch.setattr(actions.asyncio, "sleep", arm_during_preparation)
    with pytest.raises(ActionSafetyError):
        await actions.reboot(drone, fc_flag=True, sys_flag=False)
    drone.action.reboot.assert_not_awaited()


async def test_native_action_runner_reports_typed_failure_without_reboot():
    drone = _drone(armed=True)
    result = await actions._run_reboot_fc(SimpleNamespace(drone=drone), None)
    assert result is False
    assert actions._LAST_ACTION_FAILURE.code == "FC_REBOOT_REQUIRES_SAFE_STATE"
    drone.action.reboot.assert_not_awaited()
