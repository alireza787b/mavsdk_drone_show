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
    wait_for_rtl_completion.assert_awaited_once_with(drone)
