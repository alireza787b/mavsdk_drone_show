"""ConfigLoader first trajectory waypoint must reject non-finite px/py."""
import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.drone_config.config_loader import ConfigLoader


def _write_traj(path: Path, px, py):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t", "px", "py", "pz"])
        w.writeheader()
        w.writerow({"t": "0", "px": px, "py": py, "pz": "0"})


@pytest.mark.parametrize("px,py", [("inf", "0"), ("0", "nan"), ("nan", "inf")])
def test_load_all_configs_rejects_nonfinite_first_waypoint(tmp_path, monkeypatch, px, py):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"drones": [{"pos_id": 1}]}))
    shapes = tmp_path / "shapes" / "swarm" / "processed"
    _write_traj(shapes / "Drone 1.csv", px, py)

    import src.drone_config.config_loader as cl

    monkeypatch.setattr(cl.Params, "config_file_name", str(cfg), raising=False)
    monkeypatch.setattr(cl.Params, "sim_mode", False, raising=False)

    # Point project_root resolution: loader uses parents of __file__
    # So place shapes relative to real project; instead patch join path by
    # monkeypatching os.path.exists and open via tmp shapes under repo.

    project_root = Path(cl.__file__).resolve().parent.parent.parent
    real_shapes = project_root / "shapes" / "swarm" / "processed"
    real_shapes.mkdir(parents=True, exist_ok=True)
    target = real_shapes / "Drone 1.csv"
    backup = None
    if target.exists():
        backup = target.read_text()
    try:
        _write_traj(target, px, py)
        # Prefer isolated config path only
        with patch.object(cl.Params, "config_file_name", str(cfg)):
            with patch.object(cl.Params, "sim_mode", False):
                result = ConfigLoader.load_all_configs()
        assert 1 in result
        assert result[1]["x"] == 0.0
        assert result[1]["y"] == 0.0
    finally:
        if backup is not None:
            target.write_text(backup)
        elif target.exists():
            target.unlink()


def test_load_all_configs_keeps_finite_first_waypoint(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"drones": [{"pos_id": 42}]}))
    import src.drone_config.config_loader as cl

    project_root = Path(cl.__file__).resolve().parent.parent.parent
    real_shapes = project_root / "shapes" / "swarm" / "processed"
    real_shapes.mkdir(parents=True, exist_ok=True)
    target = real_shapes / "Drone 42.csv"
    backup = target.read_text() if target.exists() else None
    try:
        _write_traj(target, "1.5", "-2.25")
        with patch.object(cl.Params, "config_file_name", str(cfg)):
            with patch.object(cl.Params, "sim_mode", False):
                result = ConfigLoader.load_all_configs()
        assert result[42]["x"] == pytest.approx(1.5)
        assert result[42]["y"] == pytest.approx(-2.25)
    finally:
        if backup is not None:
            target.write_text(backup)
        elif target.exists():
            target.unlink()
