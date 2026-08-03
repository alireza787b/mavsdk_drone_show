import asyncio
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

from src import mission_startup  # noqa: E402 - dependency stubs must be installed first


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


def _battery(*, remaining_percent=80.0, voltage_v=16.0):
    return SimpleNamespace(
        remaining_percent=remaining_percent,
        voltage_v=voltage_v,
    )


def _battery_stream(samples):
    async def _stream():
        for sample in samples:
            yield sample
    return _stream


async def _connected_stream():
    yield SimpleNamespace(is_connected=True)
    await asyncio.Event().wait()


def _connected_drone():
    drone = MagicMock()
    drone.core.connection_state = _connected_stream
    return drone


@pytest.mark.asyncio
async def test_wait_until_offboard_armable_returns_when_armable():
    drone = _connected_drone()
    drone.telemetry.health = _health_stream([_health()])
    drone.telemetry.battery = _battery_stream([_battery(remaining_percent=82.0, voltage_v=15.7)])

    result = await mission_startup.wait_until_offboard_armable(
        drone,
        require_global_position=True,
    )

    assert result["armable"] is True
    assert result["ready"] is True
    observation = result["observation"]
    assert observation["schema_version"] == 1
    assert observation["observation_id"].startswith("safety-")
    assert observation["source"] == "mavsdk.connected_safety_snapshot"
    assert observation["valid_until_ms"] > observation["observed_at_ms"]
    assert observation["require_global_position"] is True
    assert observation["ready"] is True
    assert observation["blockers"] == []
    assert observation["checks"] == {
        "connection_live": True,
        "connection_fresh": True,
        "connection_continuous": True,
        "source_boot_stable": True,
        "health_sample_received": True,
        "health_fresh": True,
        "armable": True,
        "global_position_ok": True,
        "home_position_ok": True,
        "local_position_ok": True,
        "gyro_ok": True,
        "accel_ok": True,
        "mag_ok": True,
        "battery_sample_received": True,
        "battery_remaining_available": True,
        "battery_fresh": True,
        "battery_reserve_ok": True,
    }
    assert observation["safety_snapshot"]["connection_live"] is True
    assert observation["safety_snapshot"]["fields"]["health"]["source_freshness"] == "unknown"
    assert result["battery"]["remaining_percent"] == pytest.approx(82.0)
    assert result["battery"]["voltage_v"] == pytest.approx(15.7)
    assert result["battery"]["minimum_remaining_percent"] == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_wait_until_offboard_armable_times_out_when_armability_never_clears(monkeypatch):
    async def _stuck_stream():
        while True:
            yield _health(is_armable=False)

    drone = _connected_drone()
    drone.telemetry.health = _stuck_stream
    drone.telemetry.battery = _battery_stream([_battery()])
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_POLL_SEC", 0.01)

    with pytest.raises(TimeoutError, match="Timed out waiting for MAVSDK pre-arm health"):
        await mission_startup.wait_until_offboard_armable(
            drone,
            require_global_position=True,
        )


@pytest.mark.asyncio
async def test_wait_until_offboard_armable_resubscribes_after_stream_end():
    drone = _connected_drone()

    async def _first_stream():
        yield _health(is_armable=False)

    async def _second_stream():
        yield _health()

    drone.telemetry.health = MagicMock(side_effect=[_first_stream(), _second_stream()])
    drone.telemetry.battery = _battery_stream([_battery()])

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

    drone = _connected_drone()
    drone.telemetry.health = _stuck_stream
    drone.telemetry.battery = _battery_stream([_battery()])
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_POLL_SEC", 0.01)

    result = await mission_startup.probe_offboard_armability(
        drone,
        require_global_position=True,
    )

    assert result["ready"] is False
    assert result["timed_out"] is True
    assert "PX4 armability" in result["blockers"]
    assert result["observation"]["ready"] is False
    assert result["observation"]["blockers"] == result["blockers"]


@pytest.mark.asyncio
async def test_probe_offboard_armability_marks_missing_health_observation_expired(monkeypatch):
    async def _no_health_samples():
        await asyncio.Event().wait()
        yield  # pragma: no cover - keeps this an async generator

    drone = _connected_drone()
    drone.telemetry.health = _no_health_samples
    drone.telemetry.battery = _battery_stream([_battery()])
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC", 0.03)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_POLL_SEC", 0.01)

    result = await mission_startup.probe_offboard_armability(
        drone,
        require_global_position=True,
    )

    observation = result["observation"]
    assert result["timed_out"] is True
    assert result["blockers"] == ["health stream"]
    assert observation["checks"]["health_sample_received"] is False
    assert observation["valid_until_ms"] == 0
    assert observation["checks"]["battery_sample_received"] is True


@pytest.mark.parametrize(
    ("raw_remaining", "expected_percent"),
    [(0.0, 0.0), (0.76, 0.76), (1.0, 1.0), (76.0, 76.0), (100.0, 100.0)],
)
def test_battery_remaining_preserves_mavsdk_percentage_points(raw_remaining, expected_percent):
    assert mission_startup._normalize_remaining_percent(raw_remaining) == pytest.approx(expected_percent)


@pytest.mark.parametrize("raw_remaining", [-1.0, 100.01, float("nan"), float("inf"), None])
def test_battery_remaining_rejects_values_outside_mavsdk_contract(raw_remaining):
    assert mission_startup._normalize_remaining_percent(raw_remaining) is None


@pytest.mark.asyncio
async def test_mavsdk_percentage_points_are_preserved_at_the_contract_boundary(monkeypatch):
    drone = _connected_drone()
    drone.telemetry.health = _health_stream([_health()])
    drone.telemetry.battery = _battery_stream([_battery(remaining_percent=80.0)])
    monkeypatch.setattr(mission_startup.Params, "LAUNCH_BATTERY_MIN_REMAINING_PERCENT", 30.0)

    result = await mission_startup.probe_offboard_armability(
        drone,
        require_global_position=True,
    )

    assert result["battery"]["remaining_percent"] == pytest.approx(80.0)
    assert result["battery"]["reserve_ok"] is True
    assert result["ready"] is True


@pytest.mark.asyncio
async def test_launch_readiness_blocks_below_configured_battery_reserve(monkeypatch):
    drone = _connected_drone()
    drone.telemetry.health = _health_stream([_health()])
    drone.telemetry.battery = _battery_stream([_battery(remaining_percent=24.0, voltage_v=15.1)])
    monkeypatch.setattr(mission_startup.Params, "LAUNCH_BATTERY_MIN_REMAINING_PERCENT", 35.0)

    result = await mission_startup.probe_offboard_armability(
        drone,
        require_global_position=True,
    )

    assert result["health_ready"] is True
    assert result["ready"] is False
    assert result["battery"]["remaining_percent"] == pytest.approx(24.0)
    assert result["battery"]["minimum_remaining_percent"] == pytest.approx(35.0)
    assert result["battery"]["fresh"] is True
    assert "battery reserve 24.0% below minimum 35.0%" in result["blockers"]

    with pytest.raises(mission_startup.LaunchReadinessError) as exc_info:
        drone.telemetry.health = _health_stream([_health()])
        drone.telemetry.battery = _battery_stream([_battery(remaining_percent=24.0, voltage_v=15.1)])
        await mission_startup.wait_until_offboard_armable(
            drone,
            require_global_position=True,
        )

    assert exc_info.value.code == "BATTERY_RESERVE_LOW"
    assert exc_info.value.battery["voltage_v"] == pytest.approx(15.1)


@pytest.mark.asyncio
async def test_real_launch_readiness_fails_closed_without_battery_remaining(monkeypatch):
    async def _unknown_battery_stream():
        yield _battery(remaining_percent=float("nan"), voltage_v=15.9)
        await asyncio.Event().wait()

    drone = _connected_drone()
    drone.telemetry.health = _health_stream([_health()])
    drone.telemetry.battery = _unknown_battery_stream
    monkeypatch.setattr(mission_startup.Params, "sim_mode", False)
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC", 0.03)

    result = await mission_startup.probe_offboard_armability(
        drone,
        require_global_position=True,
    )

    assert result["ready"] is False
    assert result["battery"]["sample_received"] is True
    assert result["battery"]["remaining_percent"] is None
    assert result["battery"]["voltage_v"] == pytest.approx(15.9)
    assert "battery remaining estimate unavailable" in result["blockers"]


@pytest.mark.asyncio
async def test_stock_sitl_launch_uses_actual_battery_telemetry_without_bypass(monkeypatch):
    drone = _connected_drone()
    drone.telemetry.health = _health_stream([_health()])
    drone.telemetry.battery = _battery_stream([_battery(remaining_percent=80.0, voltage_v=16.0)])
    monkeypatch.setattr(mission_startup.Params, "sim_mode", True)

    result = await mission_startup.probe_offboard_armability(
        drone,
        require_global_position=True,
    )

    assert result["ready"] is True
    assert result["battery"]["remaining_percent"] == pytest.approx(80.0)
    assert result["battery"]["sample_received"] is True
    assert result["battery"]["fresh"] is True


@pytest.mark.asyncio
async def test_launch_readiness_does_not_use_pack_voltage_threshold(monkeypatch):
    drone = _connected_drone()
    drone.telemetry.health = _health_stream([_health()])
    drone.telemetry.battery = _battery_stream([_battery(remaining_percent=90.0, voltage_v=3.7)])
    monkeypatch.setattr(mission_startup.Params, "LAUNCH_BATTERY_MIN_REMAINING_PERCENT", 30.0)

    result = await mission_startup.probe_offboard_armability(
        drone,
        require_global_position=True,
    )

    assert result["ready"] is True
    assert result["battery"]["voltage_v"] == pytest.approx(3.7)


@pytest.mark.asyncio
async def test_arm_with_preflight_gate_retries_command_denied(monkeypatch):
    drone = _connected_drone()

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
    drone = _connected_drone()
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


@pytest.mark.asyncio
async def test_arm_denial_raises_typed_error_with_bounded_correlated_status_text(monkeypatch):
    drone = _connected_drone()

    class _CommandDeniedError(Exception):
        def __str__(self):
            return "COMMAND_DENIED"

    async def _status_text_stream():
        for index in range(12):
            text = f"diagnostic {index}"
            if index == 11:
                text = "Arming denied: Resolve system health failures first"
            yield SimpleNamespace(type=SimpleNamespace(name="ERROR"), text=text)
        await asyncio.Event().wait()

    observation = {
        "schema_version": 1,
        "observation_id": "health-test",
        "source": "mavsdk.health",
        "observed_at_ms": 1,
        "valid_until_ms": 2,
        "require_global_position": True,
        "ready": True,
        "blockers": [],
        "checks": {"armable": True},
    }
    drone.telemetry.status_text = _status_text_stream
    drone.action.arm = AsyncMock(side_effect=_CommandDeniedError())
    monkeypatch.setattr(mission_startup, "ActionError", _CommandDeniedError)
    monkeypatch.setattr(
        mission_startup,
        "wait_until_offboard_armable",
        AsyncMock(return_value={"ready": True, "observation": observation}),
    )
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(mission_startup, "_STATUS_TEXT_POST_DENIAL_SEC", 0.01)

    with pytest.raises(mission_startup.LaunchPreflightError) as exc_info:
        await mission_startup.arm_with_preflight_gate(
            drone,
            require_global_position=True,
        )

    error = exc_info.value
    assert error.code == "ARM_COMMAND_DENIED"
    assert error.phase == "arming"
    assert error.observation == observation
    assert 1 <= len(error.evidence) <= mission_startup._STATUS_TEXT_MAX_ITEMS
    assert error.evidence[-1]["text"] == "Arming denied: Resolve system health failures first"
    assert all(set(item) == {"observed_at_ms", "severity", "text"} for item in error.evidence)
    assert all(len(item["text"]) <= mission_startup._STATUS_TEXT_MAX_CHARS for item in error.evidence)
    assert "specific failing PX4 health item is unknown" in str(error)


@pytest.mark.asyncio
async def test_non_denial_action_error_preserves_mavsdk_error(monkeypatch):
    drone = _connected_drone()

    class _OtherActionError(Exception):
        def __str__(self):
            return "RESULT_BUSY"

    async def _status_text_stream():
        await asyncio.Event().wait()
        yield  # pragma: no cover - keeps this an async generator

    drone.telemetry.status_text = _status_text_stream
    drone.action.arm = AsyncMock(side_effect=_OtherActionError())
    monkeypatch.setattr(mission_startup, "ActionError", _OtherActionError)
    monkeypatch.setattr(
        mission_startup,
        "wait_until_offboard_armable",
        AsyncMock(return_value={"ready": True, "observation": {}}),
    )
    monkeypatch.setattr(mission_startup.Params, "OFFBOARD_ARM_MAX_ATTEMPTS", 1)

    with pytest.raises(_OtherActionError, match="RESULT_BUSY"):
        await mission_startup.arm_with_preflight_gate(
            drone,
            require_global_position=True,
        )
