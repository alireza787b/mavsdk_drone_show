"""Fail-closed finite checks for drone_show_src.utils helpers."""
import csv
import importlib.util
import math
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Stub heavy imports used at module import time
sys.modules.setdefault("mavsdk", MagicMock())
sys.modules.setdefault("mavsdk.system", MagicMock())
offboard = types.ModuleType("mavsdk.offboard")
offboard.PositionNedYaw = MagicMock()
sys.modules.setdefault("mavsdk.offboard", offboard)
sys.modules.setdefault("numpy", MagicMock())
sys.modules.setdefault("pyproj", MagicMock())
sys.modules.setdefault("navpy", MagicMock())
sys.modules.setdefault("src.params", MagicMock())

spec = importlib.util.spec_from_file_location(
    "drone_show_src_utils_under_test",
    ROOT / "drone_show_src" / "utils.py",
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_clamp_led_happy():
    assert mod.clamp_led_value(128) == 128
    assert mod.clamp_led_value(300) == 255
    assert mod.clamp_led_value(-5) == 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "nan", "nope", None])
def test_clamp_led_rejects_nonfinite(bad):
    assert mod.clamp_led_value(bad) == 0


def test_expected_position_happy(tmp_path, monkeypatch):
    base = tmp_path / "shapes" / "swarm" / "processed"
    base.mkdir(parents=True)
    path = base / "Drone 1.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["px", "py", "pz", "t"])
        w.writeheader()
        w.writerow({"px": "10.5", "py": "-3.25", "pz": "0", "t": "0"})

    monkeypatch.chdir(tmp_path)
    north, east = mod.get_expected_position_from_trajectory(1, sim_mode=False)
    assert north == 10.5
    assert east == -3.25


@pytest.mark.parametrize("px,py", [("nan", "1"), ("1", "inf"), ("-inf", "2"), ("1e400", "0")])
def test_expected_position_rejects_nonfinite(tmp_path, monkeypatch, px, py):
    base = tmp_path / "shapes" / "swarm" / "processed"
    base.mkdir(parents=True)
    path = base / "Drone 2.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["px", "py"])
        w.writeheader()
        w.writerow({"px": px, "py": py})

    monkeypatch.chdir(tmp_path)
    assert mod.get_expected_position_from_trajectory(2, sim_mode=False) == (None, None)
