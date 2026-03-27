import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

for module_name in ("aiogrpc", "psutil", "requests"):
    sys.modules.setdefault(module_name, MagicMock())
sys.modules.setdefault(
    "tenacity",
    types.SimpleNamespace(
        retry=lambda *args, **kwargs: (lambda func: func),
        stop_after_attempt=lambda *args, **kwargs: None,
        wait_fixed=lambda *args, **kwargs: None,
    ),
)

import swarm_trajectory_mission as stm


async def _stream_once(value):
    yield value


def _stream_side_effect(values):
    iterator = iter(values)

    def _factory():
        async def _stream():
            yield next(iterator)

        return _stream()

    return _factory


@pytest.mark.asyncio
async def test_wait_for_rtl_completion_returns_after_touchdown_and_disarm():
    drone = MagicMock()
    drone.telemetry.landed_state.return_value = _stream_once(stm.LandedState.ON_GROUND)
    drone.telemetry.armed.return_value = _stream_once(False)

    await stm.wait_for_rtl_completion(drone)


@pytest.mark.asyncio
async def test_execute_end_behavior_return_home_waits_for_rtl_completion():
    drone = MagicMock()
    drone.action.hold = AsyncMock()
    drone.action.return_to_launch = AsyncMock()

    with patch.object(stm, "stop_offboard_mode", new=AsyncMock()) as stop_offboard_mode:
        with patch.object(stm, "wait_for_rtl_completion", new=AsyncMock()) as wait_for_rtl_completion:
            await stm.execute_end_behavior(
                drone,
                "return_home",
                launch_lat=35.0,
                launch_lon=51.0,
                launch_alt=1200.0,
            )

    stop_offboard_mode.assert_awaited_once()
    drone.action.hold.assert_awaited_once()
    drone.action.return_to_launch.assert_awaited_once()
    wait_for_rtl_completion.assert_awaited_once_with(drone, home_lat=35.0, home_lon=51.0)


@pytest.mark.asyncio
async def test_wait_for_rtl_completion_issues_explicit_disarm_after_touchdown_grace(monkeypatch):
    drone = MagicMock()
    drone.telemetry.landed_state.side_effect = _stream_side_effect(
        [stm.LandedState.ON_GROUND, stm.LandedState.ON_GROUND]
    )
    drone.telemetry.armed.side_effect = _stream_side_effect([True, False])

    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_DISARM_GRACE_SEC", 0)
    monkeypatch.setattr(stm, "calculate_swarm_rtl_completion_timeout", lambda altitude: 30)
    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(return_value=25.0)):
        with patch.object(stm, "disarm_drone", new=AsyncMock()) as disarm_drone:
            await stm.wait_for_rtl_completion(drone)

    disarm_drone.assert_awaited_once_with(drone)


@pytest.mark.asyncio
async def test_wait_for_rtl_completion_forces_land_when_stalled_over_home(monkeypatch):
    drone = MagicMock()
    drone.telemetry.landed_state.side_effect = _stream_side_effect([object(), object()])
    drone.telemetry.armed.side_effect = _stream_side_effect([True, True])

    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_HOME_STALL_TRIGGER_SEC", 0)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_HOME_STALL_RADIUS_M", 25.0)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_STALL_DESCENT_EPS_MPS", 0.3)
    monkeypatch.setattr(stm, "calculate_swarm_rtl_completion_timeout", lambda altitude: 1200)

    local_state = {
        "position_lat": 35.0,
        "position_long": 51.0,
        "velocity_down": 0.0,
    }

    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(return_value=1200.0)):
        with patch.object(stm, "_get_local_drone_state_snapshot", return_value=local_state):
            with patch.object(stm, "perform_landing", new=AsyncMock()) as perform_landing:
                await stm.wait_for_rtl_completion(drone, home_lat=35.0, home_lon=51.0)

    perform_landing.assert_awaited_once_with(drone)


@pytest.mark.asyncio
async def test_controlled_landing_delegates_to_native_land_when_above_precision_window(monkeypatch):
    drone = MagicMock()
    monkeypatch.setattr(stm.Params, "CONTROLLED_LANDING_ALTITUDE", 2.0)

    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(return_value=15.0)):
        with patch.object(stm, "stop_offboard_mode", new=AsyncMock()) as stop_offboard_mode:
            with patch.object(stm, "perform_landing", new=AsyncMock()) as perform_landing:
                await stm.controlled_landing(drone)

    stop_offboard_mode.assert_awaited_once_with(drone)
    perform_landing.assert_awaited_once_with(drone)


@pytest.mark.asyncio
async def test_perform_landing_requires_disarm_before_returning(monkeypatch):
    drone = MagicMock()
    drone.action.land = AsyncMock()
    drone.telemetry.landed_state.side_effect = _stream_side_effect(
        [stm.LandedState.ON_GROUND, stm.LandedState.ON_GROUND]
    )
    drone.telemetry.armed.side_effect = _stream_side_effect([True, False])

    monkeypatch.setattr(stm.Params, "LAND_ACTION_TOUCHDOWN_DISARM_GRACE_SEC", 0)
    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(return_value=12.0)):
        with patch.object(stm, "disarm_drone", new=AsyncMock()) as disarm_drone:
            await stm.perform_landing(drone)

    drone.action.land.assert_awaited_once()
    disarm_drone.assert_awaited_once_with(drone)
