import sys
import types
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("psutil", MagicMock())

mavsdk_module = types.ModuleType("mavsdk")
mavsdk_module.System = MagicMock()
mavsdk_system_module = types.ModuleType("mavsdk.system")
mavsdk_system_module.System = MagicMock()
mavsdk_telemetry_module = types.ModuleType("mavsdk.telemetry")
mavsdk_telemetry_module.FlightMode = types.SimpleNamespace(HOLD=types.SimpleNamespace(name="HOLD"))
mavsdk_telemetry_module.LandedState = types.SimpleNamespace(LANDING="LANDING", ON_GROUND="ON_GROUND")
mavsdk_module.telemetry = mavsdk_telemetry_module
mavsdk_module.action = MagicMock()
sys.modules.setdefault("mavsdk", mavsdk_module)
sys.modules.setdefault("mavsdk.system", mavsdk_system_module)
sys.modules.setdefault("mavsdk.telemetry", mavsdk_telemetry_module)
sys.modules.setdefault("mavsdk.action", types.SimpleNamespace(ActionError=Exception))

from src.action_runners.base import ActionExecutionContext, ActionInvocation
from src.action_runners.precision_move import (
    LocalMoveSnapshot,
    _body_to_ned_translation,
    precision_move,
)


class _DummyPositionNedYaw:
    def __init__(self, north_m, east_m, down_m, yaw_deg):
        self.north_m = north_m
        self.east_m = east_m
        self.down_m = down_m
        self.yaw_deg = yaw_deg


class _DummyVelocityNedYaw:
    def __init__(self, north_m_s, east_m_s, down_m_s, yaw_deg):
        self.north_m_s = north_m_s
        self.east_m_s = east_m_s
        self.down_m_s = down_m_s
        self.yaw_deg = yaw_deg


class _DummyOffboardError(Exception):
    pass


class _DummyOffboard:
    def __init__(self):
        self.commands = []
        self.started = False
        self.stopped = False

    async def set_position_velocity_ned(self, position, velocity):
        self.commands.append((position, velocity))

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


class _DummyTelemetry:
    async def flight_mode(self):
        yield types.SimpleNamespace(name="HOLD")


class _DummyDrone:
    def __init__(self):
        self.offboard = _DummyOffboard()
        self.telemetry = _DummyTelemetry()


def test_body_to_ned_translation_respects_heading():
    north_m, east_m = _body_to_ned_translation(2.0, 4.0, 90.0)

    assert north_m == pytest.approx(-4.0)
    assert east_m == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_precision_move_converges_and_hands_off_to_hold(monkeypatch):
    snapshots = iter(
        [
            LocalMoveSnapshot(0.0, 0.0, -2.0, 90.0, True, True, "HOLD"),
            LocalMoveSnapshot(0.0, 0.0, -2.0, 90.0, True, True, "HOLD"),
            LocalMoveSnapshot(-4.0, 2.0, -3.0, 120.0, True, True, "OFFBOARD"),
            LocalMoveSnapshot(-4.0, 2.0, -3.0, 120.0, True, True, "OFFBOARD"),
            LocalMoveSnapshot(-4.0, 2.0, -3.0, 120.0, True, True, "OFFBOARD"),
        ]
    )
    monkeypatch.setattr(
        "src.action_runners.precision_move._read_local_move_snapshot",
        lambda timeout=1.0: next(snapshots),
    )
    monkeypatch.setattr(
        "src.action_runners.precision_move._read_local_relative_altitude",
        lambda timeout=1.0: 2.0,
    )
    monkeypatch.setattr(
        "src.action_runners.precision_move._load_offboard_types",
        lambda: (_DummyOffboardError, _DummyPositionNedYaw, _DummyVelocityNedYaw),
    )

    drone = _DummyDrone()
    context = ActionExecutionContext(drone=drone, hw_id="1", logger=MagicMock())
    invocation = ActionInvocation(
        action="precision_move",
        request_payload={
            "frame": "body",
            "translation_m": {"forward": 2.0, "right": 4.0, "up": 1.0},
            "yaw": {"mode": "relative_delta", "degrees": 30.0},
            "speed_m_s": 1.0,
            "position_tolerance_m": 0.15,
            "yaw_tolerance_deg": 5.0,
            "settle_time_sec": 0.01,
            "timeout_sec": 5.0,
        },
    )

    await precision_move(context, invocation)

    assert drone.offboard.started is True
    assert drone.offboard.stopped is True
    final_position, final_velocity = drone.offboard.commands[-1]
    assert final_position.north_m == pytest.approx(-4.0)
    assert final_position.east_m == pytest.approx(2.0)
    assert final_position.down_m == pytest.approx(-3.0)
    assert final_position.yaw_deg == pytest.approx(120.0)
    assert final_velocity.north_m_s == pytest.approx(0.0)
    assert final_velocity.east_m_s == pytest.approx(0.0)
    assert final_velocity.down_m_s == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_precision_move_requires_payload():
    context = ActionExecutionContext(drone=_DummyDrone(), hw_id="1", logger=MagicMock())
    invocation = ActionInvocation(action="precision_move", request_payload=None)

    with pytest.raises(ValueError, match="requires --request-json or --request-file"):
        await precision_move(context, invocation)
