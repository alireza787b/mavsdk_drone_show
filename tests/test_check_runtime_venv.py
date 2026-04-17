from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "check_runtime_venv.py"


def _create_venv(tmp_path: Path) -> Path:
    venv_dir = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    return venv_dir


def test_check_runtime_venv_accepts_healthy_venv(tmp_path):
    venv_dir = _create_venv(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--venv", str(venv_dir), "--module", "json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "ok python=" in result.stdout


def test_check_runtime_venv_rejects_version_mismatch(tmp_path):
    venv_dir = _create_venv(tmp_path)
    pyvenv_cfg = venv_dir / "pyvenv.cfg"
    lines = pyvenv_cfg.read_text(encoding="utf-8").splitlines()
    updated = []
    for line in lines:
        if line.startswith("version ="):
            updated.append("version = 0.0.0")
        else:
            updated.append(line)
    pyvenv_cfg.write_text("\n".join(updated) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--venv", str(venv_dir), "--module", "json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "venv interpreter version mismatch" in result.stderr


def test_check_runtime_venv_rejects_missing_module(tmp_path):
    venv_dir = _create_venv(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--venv", str(venv_dir), "--module", "definitely_missing_module"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "venv module import failure" in result.stderr
