"""Fail-closed local relative-altitude snapshot (non-finite telemetry)."""
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.setdefault("psutil", MagicMock())
sys.modules.setdefault("requests", MagicMock())
mavsdk_module = types.ModuleType("mavsdk")
mavsdk_module.System = MagicMock()
mavsdk_module.telemetry = MagicMock()
mavsdk_module.action = MagicMock()
mavsdk_module.__path__ = []
sys.modules.setdefault("mavsdk", mavsdk_module)
sys.modules.setdefault("mavsdk.system", types.SimpleNamespace(System=MagicMock()))
offboard_module = types.ModuleType("mavsdk.offboard")
for name in (
    "PositionNedYaw",
    "VelocityBodyYawspeed",
    "PositionGlobalYaw",
    "VelocityNedYaw",
    "AccelerationNed",
):
    setattr(offboard_module, name, MagicMock())
offboard_module.OffboardError = type("OffboardError", (Exception,), {})
sys.modules.setdefault("mavsdk.offboard", offboard_module)
telemetry_module = types.ModuleType("mavsdk.telemetry")
telemetry_module.FlightMode = types.SimpleNamespace(HOLD=types.SimpleNamespace(name="HOLD"))
telemetry_module.LandedState = types.SimpleNamespace(LANDING="LANDING", ON_GROUND="ON_GROUND")
sys.modules.setdefault("mavsdk.telemetry", telemetry_module)
sys.modules.setdefault(
    "mavsdk.action", types.SimpleNamespace(ActionError=type("ActionError", (Exception,), {}))
)

# Stub heavy local packages often pulled by actions import chain
for mod_name in (
    "src.led_controller",
    "src.drone_config",
    "navpy",
    "pyproj",
):
    sys.modules.setdefault(mod_name, MagicMock())

import actions  # noqa: E402


def test_local_rel_alt_happy_path(monkeypatch):
    monkeypatch.setattr(
        actions,
        "_get_local_drone_state_snapshot",
        lambda timeout=1.0: {"position_alt": 120.5},
    )
    monkeypatch.setattr(
        actions,
        "_get_local_home_position_snapshot",
        lambda timeout=1.0: {"altitude": 100.0},
    )
    assert actions._get_local_relative_altitude_snapshot() == pytest.approx(20.5)


@pytest.mark.parametrize(
    "pos_alt, home_alt",
    [
        (float("nan"), 100.0),
        (120.0, float("nan")),
        (float("inf"), 100.0),
        (120.0, float("-inf")),
        ("nan", 100.0),
        (None, 100.0),
        (120.0, None),
        ("nope", 100.0),
    ],
)
def test_local_rel_alt_rejects_bad(monkeypatch, pos_alt, home_alt):
    monkeypatch.setattr(
        actions,
        "_get_local_drone_state_snapshot",
        lambda timeout=1.0: {"position_alt": pos_alt},
    )
    monkeypatch.setattr(
        actions,
        "_get_local_home_position_snapshot",
        lambda timeout=1.0: {"altitude": home_alt},
    )
    assert actions._get_local_relative_altitude_snapshot() is None


def test_local_rel_alt_missing_snapshots(monkeypatch):
    monkeypatch.setattr(actions, "_get_local_drone_state_snapshot", lambda timeout=1.0: None)
    monkeypatch.setattr(
        actions, "_get_local_home_position_snapshot", lambda timeout=1.0: {"altitude": 1.0}
    )
    assert actions._get_local_relative_altitude_snapshot() is None
