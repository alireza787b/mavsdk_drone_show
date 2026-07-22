import asyncio
import math
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

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

    assert result["armable"] is True
    assert result["ready"] is True


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
async def test_wait_until_offboard_armable_resubscribes_after_stream_end():
    drone = MagicMock()

    async def _first_stream():
        yield _health(is_armable=False)

    async def _second_stream():
        yield _health()

    drone.telemetry.health = MagicMock(side_effect=[_first_stream(), _second_stream()])

    result = await mission_startup.wait_until_offboard_armable(
        drone,
        require_global_position=True,
    )

    assert result["armable"] is True
    assert drone.telemetry.health.call_count == 2


@pytest.mark.asyncio
async def test_probe_offboard_armability_returns_last_state_on_timeout(monkeypatch):
    async def _stuck_stream():
        while True:
            yield _health(is_armable=False, is_home_position_ok=False)

    drone = MagicMock()
    drone.telemetry.health = _stuck_stream
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_POLL_SEC", 0.01)

    result = await mission_startup.probe_offboard_armability(
        drone,
        require_global_position=True,
    )

    assert result["ready"] is False
    assert result["timed_out"] is True
    assert "PX4 armability" in result["blockers"]


@pytest.mark.asyncio
async def test_arm_with_preflight_gate_retries_command_denied(monkeypatch):
    drone = MagicMock()

    class _CommandDeniedError(Exception):
        def __str__(self):
            return "COMMAND_DENIED"

    monkeypatch.setattr(mission_startup, "ActionError", _CommandDeniedError)
    drone.action.arm = AsyncMock(side_effect=[_CommandDeniedError(), None])

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
    assert drone.action.arm.call_count == 2


@pytest.mark.asyncio
async def test_arm_with_preflight_gate_retries_timed_out_arm_rpc(monkeypatch):
    drone = MagicMock()
    drone.action.arm = AsyncMock(return_value=None)
    wait_for_calls = {"count": 0}

    real_wait_for = asyncio.wait_for

    async def _wait_for_with_first_timeout(awaitable, timeout):
        wait_for_calls["count"] += 1
        if wait_for_calls["count"] == 1:
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError()
        return await real_wait_for(awaitable, timeout)

    wait_mock = AsyncMock()
    monkeypatch.setattr(mission_startup, "wait_until_offboard_armable", wait_mock)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_RETRY_DELAY_SEC", 0.0)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_ACTION_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(mission_startup.asyncio, "wait_for", _wait_for_with_first_timeout)

    await mission_startup.arm_with_preflight_gate(
        drone,
        require_global_position=True,
    )

    assert wait_mock.await_count == 2
    assert drone.action.arm.call_count == 2



def test_positive_finite_float_helper_rejects_nonfinite():
    assert mission_startup._positive_finite_float(float("nan"), 15.0) == 15.0
    assert mission_startup._positive_finite_float(float("inf"), 15.0) == 15.0
    assert mission_startup._positive_finite_float(-1.0, 15.0) == 15.0
    assert mission_startup._positive_finite_float("nope", 15.0) == 15.0
    assert mission_startup._positive_finite_float(3.5, 15.0) == 3.5


def test_non_negative_finite_float_helper_allows_zero():
    assert mission_startup._non_negative_finite_float(0.0, 2.0) == 0.0
    assert mission_startup._non_negative_finite_float(float("nan"), 2.0) == 2.0
    assert mission_startup._non_negative_finite_float(float("-inf"), 2.0) == 2.0


def test_probe_offboard_armability_falls_back_from_nonfinite_timeout(monkeypatch):
    async def _stuck_stream():
        while True:
            yield _health(is_armable=False)

    drone = MagicMock()
    drone.telemetry.health = _stuck_stream
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC", float("inf"))
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_POLL_SEC", float("nan"))

    original = mission_startup._positive_finite_float

    def _fast_default(value, default):
        result = original(value, default)
        try:
            parsed = float(value)
            bad = not (math.isfinite(parsed) and parsed > 0)
        except (TypeError, ValueError):
            bad = True
        if bad:
            return 0.05 if float(default) >= 1.0 else 0.01
        return result

    monkeypatch.setattr(mission_startup, "_positive_finite_float", _fast_default)

    result = asyncio.run(
        mission_startup.probe_offboard_armability(
            drone,
            require_global_position=True,
        )
    )
    assert result["timed_out"] is True
    assert result["ready"] is False


def test_arm_with_preflight_gate_uses_finite_arm_timeout_budget(monkeypatch):
    drone = MagicMock()
    drone.action.arm = AsyncMock(return_value=None)
    wait_mock = AsyncMock()
    monkeypatch.setattr(mission_startup, "wait_until_offboard_armable", wait_mock)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_RETRY_DELAY_SEC", float("nan"))
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_ACTION_TIMEOUT_SEC", float("inf"))
    captured = {}
    real_wait_for = asyncio.wait_for

    async def _capture(awaitable, timeout):
        captured["timeout"] = timeout
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(mission_startup.asyncio, "wait_for", _capture)
    asyncio.run(mission_startup.arm_with_preflight_gate(drone, require_global_position=True))
    assert math.isfinite(captured["timeout"])
    assert captured["timeout"] >= 1.0
