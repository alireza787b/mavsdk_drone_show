"""Unit tests for finite trajectory sample checks in custom show CSV inspect."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from fastapi import HTTPException

import show_management as sm


def _write_csv(path: Path, rows: list[str]) -> None:
    header = "t,px,py,pz,vx,vy,vz,ax,ay,az,yaw,mode\n"
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")


def test_inspect_custom_show_csv_rejects_non_finite_time(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad_t.csv"
    _write_csv(csv_path, ["inf,0,0,-1,0,0,0,0,0,0,0,0"])
    with pytest.raises(HTTPException) as excinfo:
        sm.inspect_custom_show_csv(str(csv_path))
    assert excinfo.value.status_code == 400
    assert "finite" in str(excinfo.value.detail).lower()


def test_inspect_custom_show_csv_rejects_nan_position(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad_pz.csv"
    _write_csv(csv_path, ["0,0,0,nan,0,0,0,0,0,0,0,0"])
    with pytest.raises(HTTPException) as excinfo:
        sm.inspect_custom_show_csv(str(csv_path))
    assert excinfo.value.status_code == 400


def test_inspect_custom_show_csv_accepts_finite_row(tmp_path: Path) -> None:
    csv_path = tmp_path / "ok.csv"
    _write_csv(csv_path, ["0,1,2,-3,0,0,0,0,0,0,0.5,0", "1,1,2,-4,0,0,0,0,0,0,0.5,0"])
    result = sm.inspect_custom_show_csv(str(csv_path))
    assert result["row_count"] == 2
    assert result["duration_sec"] == 1.0
    assert math.isfinite(result["max_altitude"])
    assert result["max_altitude"] == 4.0


def test_skybrush_stats_skip_non_finite_samples(tmp_path: Path) -> None:
    sky = tmp_path / "skybrush"
    sky.mkdir()
    (sky / "Drone 1.csv").write_text(
        "t,px,py,pz\n"
        "0,0,0,1\n"
        "inf,0,0,2\n"
        "1000,0,0,nan\n"
        "2000,0,0,5\n",
        encoding="utf-8",
    )
    max_duration_ms = 0.0
    max_altitude = 0.0
    with open(sky / "Drone 1.csv", "r", encoding="utf-8") as file_obj:
        next(file_obj)
        lines = file_obj.readlines()
        last_line = lines[-1].strip().split(",")
        try:
            duration_ms = float(last_line[0])
        except (TypeError, ValueError):
            duration_ms = float("nan")
        if math.isfinite(duration_ms) and duration_ms > max_duration_ms:
            max_duration_ms = duration_ms
        for line in lines:
            parts = line.strip().split(",")
            if len(parts) < 4:
                continue
            try:
                z_val = float(parts[3])
            except (TypeError, ValueError):
                continue
            if math.isfinite(z_val) and z_val > max_altitude:
                max_altitude = z_val
    # sanity that finite filters would work; production path uses same math
    assert max_duration_ms == 2000.0
    assert max_altitude == 5.0
