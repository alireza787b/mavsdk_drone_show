import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("psutil", MagicMock())
sys.modules.setdefault("requests", MagicMock())
mavsdk_module = types.ModuleType("mavsdk")
mavsdk_module.System = MagicMock()
mavsdk_module.__path__ = []
sys.modules.setdefault("mavsdk", mavsdk_module)
sys.modules.setdefault("mavsdk.system", types.SimpleNamespace(System=MagicMock()))
offboard_module = types.ModuleType("mavsdk.offboard")
class _DummyOffboardError(Exception):
    pass

for name in (
    "PositionNedYaw",
    "VelocityBodyYawspeed",
    "PositionGlobalYaw",
    "VelocityNedYaw",
    "AccelerationNed",
):
    setattr(offboard_module, name, MagicMock())
offboard_module.OffboardError = _DummyOffboardError
sys.modules.setdefault("mavsdk.offboard", offboard_module)
telemetry_module = types.ModuleType("mavsdk.telemetry")
telemetry_module.FlightMode = types.SimpleNamespace(
    HOLD=types.SimpleNamespace(name="HOLD"),
    RETURN_TO_LAUNCH=types.SimpleNamespace(name="RETURN_TO_LAUNCH"),
)
telemetry_module.LandedState = types.SimpleNamespace(LANDING="LANDING", ON_GROUND="ON_GROUND")
sys.modules.setdefault("mavsdk.telemetry", telemetry_module)
class _DummyActionError(Exception):
    pass

sys.modules.setdefault("mavsdk.action", types.SimpleNamespace(ActionError=_DummyActionError))

from src import mission_startup


def _health(**overrides):
    base = {
        "is_armable": True,
        "is_global_position_ok": True,
        "is_home_position_ok": True,
        "is_local_position_ok": True,
        "is_gyrometer_calibration_ok": True,
        "is_accelerometer_calibration_ok": True,
        "is_magnetometer_calibration_ok": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _health_stream(samples):
    async def _stream():
        for sample in samples:
            yield sample
    return _stream


@pytest.mark.asyncio
async def test_wait_until_offboard_armable_returns_when_armable():
    drone = MagicMock()
    drone.telemetry.health = _health_stream([_health()])

    result = await mission_startup.wait_until_offboard_armable(
        drone,
        require_global_position=True,
    )

    assert result.is_armable is True


@pytest.mark.asyncio
async def test_wait_until_offboard_armable_times_out_when_armability_never_clears(monkeypatch):
    async def _stuck_stream():
        while True:
            yield _health(is_armable=False)

    drone = MagicMock()
    drone.telemetry.health = _stuck_stream
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_POLL_SEC", 0.01)

    with pytest.raises(TimeoutError, match="Timed out waiting for MAVSDK pre-arm health"):
        await mission_startup.wait_until_offboard_armable(
            drone,
            require_global_position=True,
        )


@pytest.mark.asyncio
async def test_arm_with_preflight_gate_retries_command_denied(monkeypatch):
    drone = MagicMock()
    drone.action.arm = AsyncMock(side_effect=[mission_startup.ActionError("COMMAND_DENIED"), None])

    wait_mock = AsyncMock()
    monkeypatch.setattr(mission_startup, "wait_until_offboard_armable", wait_mock)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_RETRY_DELAY_SEC", 0.0)
    monkeypatch.setattr(mission_startup.asyncio, "sleep", AsyncMock())

    await mission_startup.arm_with_preflight_gate(
        drone,
        require_global_position=True,
    )

    assert wait_mock.await_count == 2
    assert drone.action.arm.await_count == 2
