import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("psutil", MagicMock())

mavsdk_module = types.ModuleType("mavsdk")
mavsdk_module.System = MagicMock()
mavsdk_system_module = types.ModuleType("mavsdk.system")
mavsdk_system_module.System = MagicMock()
mavsdk_telemetry_module = types.ModuleType("mavsdk.telemetry")
mavsdk_telemetry_module.FlightMode = types.SimpleNamespace(
    HOLD=types.SimpleNamespace(name="HOLD"),
    RETURN_TO_LAUNCH=types.SimpleNamespace(name="RETURN_TO_LAUNCH"),
)
mavsdk_telemetry_module.LandedState = types.SimpleNamespace(LANDING="LANDING", ON_GROUND="ON_GROUND")
mavsdk_module.telemetry = mavsdk_telemetry_module
mavsdk_module.action = MagicMock()
mavsdk_offboard_module = types.ModuleType("mavsdk.offboard")
for name in (
    "PositionNedYaw",
    "VelocityBodyYawspeed",
    "PositionGlobalYaw",
    "VelocityNedYaw",
    "AccelerationNed",
):
    setattr(mavsdk_offboard_module, name, MagicMock())
mavsdk_offboard_module.OffboardError = Exception
sys.modules.setdefault("mavsdk", mavsdk_module)
sys.modules.setdefault("mavsdk.system", mavsdk_system_module)
sys.modules.setdefault("mavsdk.telemetry", mavsdk_telemetry_module)
sys.modules.setdefault("mavsdk.offboard", mavsdk_offboard_module)
sys.modules.setdefault("mavsdk.action", types.SimpleNamespace(ActionError=Exception))

import actions


class _DummyTelemetry:
    def __init__(self, samples):
        self._samples = samples

    async def health(self):
        for sample in self._samples:
            yield sample


class _DummyDrone:
    def __init__(self, samples):
        self.telemetry = _DummyTelemetry(samples)


@pytest.mark.asyncio
async def test_ensure_ready_for_flight_uses_local_home_fallback(mocker):
    mocker.patch(
        "actions._get_local_drone_state_snapshot",
        return_value={"home_position_set": True},
    )

    drone = _DummyDrone([
        SimpleNamespace(is_global_position_ok=True, is_home_position_ok=False),
    ])

    assert await actions.ensure_ready_for_flight(drone, timeout=1) is True


@pytest.mark.asyncio
async def test_wait_until_relative_altitude_uses_local_fallback_after_mavsdk_timeout(mocker):
    wait_mock = mocker.patch(
        "actions.wait_for_telemetry_condition",
        new=mocker.AsyncMock(side_effect=TimeoutError("mavsdk timeout")),
    )
    mocker.patch("actions._get_local_relative_altitude_snapshot", return_value=8.6)
    drone = SimpleNamespace(telemetry=SimpleNamespace(position=MagicMock()))

    result = await actions.wait_until_relative_altitude(drone, 8.0, timeout=1)

    wait_mock.assert_awaited_once()
    assert result == 8.6


@pytest.mark.asyncio
async def test_wait_until_relative_altitude_raises_when_fallback_is_still_below_target(mocker):
    mocker.patch(
        "actions.wait_for_telemetry_condition",
        new=mocker.AsyncMock(side_effect=TimeoutError("mavsdk timeout")),
    )
    mocker.patch("actions._get_local_relative_altitude_snapshot", return_value=4.2)
    drone = SimpleNamespace(telemetry=SimpleNamespace(position=MagicMock()))

    with pytest.raises(TimeoutError, match="mavsdk timeout"):
        await actions.wait_until_relative_altitude(drone, 8.0, timeout=1)


def test_calculate_land_disarm_timeout_defaults_to_minimum_when_altitude_unknown():
    assert actions.calculate_land_disarm_timeout(None) == actions.Params.LAND_ACTION_MIN_DISARM_WAIT_SEC


def test_calculate_land_disarm_timeout_scales_with_altitude_and_respects_cap():
    timeout = actions.calculate_land_disarm_timeout(1200.0)

    assert timeout > actions.Params.LAND_ACTION_MIN_DISARM_WAIT_SEC
    assert timeout <= actions.Params.LAND_ACTION_MAX_DISARM_WAIT_SEC
