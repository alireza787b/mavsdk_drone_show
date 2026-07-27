"""Static and fail-fast checks for the production GCS launcher."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "run_gcs_dashboard_service.sh"


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _launcher_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    checkout = tmp_path / "portable checkout"
    launcher = checkout / "tools" / SCRIPT.name
    launcher.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, launcher)
    (checkout / "gcs-server").mkdir()
    (checkout / "app" / "dashboard" / "drone-dashboard" / "build").mkdir(
        parents=True
    )
    (checkout / "tools" / "spa_static_server.py").touch()

    event_log = tmp_path / "service events.log"
    venv = tmp_path / "portable venv"
    process_stub = """#!/usr/bin/env bash
set -euo pipefail

role="${MDS_TEST_ROLE:?}"
printf '%s:start:%s:%s:%s:mode=%s:auth=%s:api_auth=%s\n' \
  "${role}" "$0" "${PWD}" "$*" "${MDS_MODE:-unset}" \
  "${MDS_AUTH_ENABLED:-unset}" \
  "${MDS_API_AUTH_ENABLED:-unset}" >> "${MDS_TEST_EVENT_LOG:?}"
trap 'printf "%s:term\\n" "${role}" >> "${MDS_TEST_EVENT_LOG}"; exit 0' TERM INT

if [[ "${role}" == "static" ]]; then
  mode="${MDS_TEST_STATIC_MODE:-wait}"
  exit_code="${MDS_TEST_STATIC_EXIT_CODE:-0}"
else
  mode="${MDS_TEST_API_MODE:-wait}"
  exit_code="${MDS_TEST_API_EXIT_CODE:-0}"
fi

if [[ "${mode}" == "exit" ]]; then
  other_role="api"
  if [[ "${role}" == "api" ]]; then
    other_role="static"
  fi
  for _ in $(seq 1 100); do
    if grep -q "^${other_role}:start:" "${MDS_TEST_EVENT_LOG}"; then
      break
    fi
    sleep 0.01
  done
  exit "${exit_code}"
fi

while true; do
  sleep 0.05
done
"""
    python_stub = venv / "bin" / "python3"
    gunicorn_stub = venv / "bin" / "gunicorn"
    _write_executable(
        python_stub,
        process_stub.replace(
            'role="${MDS_TEST_ROLE:?}"', 'role="static"'
        ),
    )
    _write_executable(
        gunicorn_stub,
        process_stub.replace('role="${MDS_TEST_ROLE:?}"', 'role="api"'),
    )
    return launcher, venv, event_log


def _launcher_env(venv: Path, event_log: Path, **overrides: str) -> dict[str, str]:
    return {
        **os.environ,
        "MDS_GCS_ENV_FILE": str(event_log.parent / "missing.env"),
        "MDS_VENV_PATH": str(venv),
        "MDS_TEST_EVENT_LOG": str(event_log),
        **overrides,
    }


def _wait_for_events(event_log: Path, expected: set[str], timeout: float = 3) -> str:
    deadline = time.monotonic() + timeout
    content = ""
    while time.monotonic() < deadline:
        if event_log.exists():
            content = event_log.read_text(encoding="utf-8")
            if all(event in content for event in expected):
                return content
        time.sleep(0.02)
    pytest.fail(f"Timed out waiting for events {expected!r}; saw {content!r}")


def test_gcs_dashboard_service_rejects_multiple_workers_before_startup(tmp_path):
    launcher, venv, event_log = _launcher_fixture(tmp_path)
    env = {
        **_launcher_env(venv, event_log),
        "MDS_GCS_WORKERS": "2",
    }

    result = subprocess.run(
        ["bash", str(launcher)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 64
    assert "MDS_GCS_WORKERS must be 1" in result.stderr
    assert "spa_static_server" not in result.stderr
    assert not event_log.exists()


def test_gcs_dashboard_service_rejects_retired_demo_profile(tmp_path):
    launcher, venv, event_log = _launcher_fixture(tmp_path)
    env_file = tmp_path / "gcs.env"
    env_file.write_text(
        "\n".join(
            (
                "MDS_SAFE_PRODUCTION_DEMO=true",
                "MDS_MODE=sitl",
                "MDS_API_AUTH_ENABLED=true",
            )
        ),
        encoding="utf-8",
    )
    env = _launcher_env(venv, event_log, MDS_GCS_ENV_FILE=str(env_file))

    result = subprocess.run(
        ["bash", str(launcher)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 64
    assert "MDS_SAFE_PRODUCTION_DEMO is no longer supported" in result.stderr
    assert not event_log.exists()


@pytest.mark.parametrize(
    ("failed_role", "expected_status", "terminated_role"),
    (
        ("static", 23, "api"),
        ("api", 24, "static"),
    ),
)
def test_gcs_dashboard_service_fails_with_either_child_and_stops_sibling(
    tmp_path, failed_role, expected_status, terminated_role
):
    launcher, venv, event_log = _launcher_fixture(tmp_path)
    env = _launcher_env(
        venv,
        event_log,
        **{
            f"MDS_TEST_{failed_role.upper()}_MODE": "exit",
            f"MDS_TEST_{failed_role.upper()}_EXIT_CODE": str(expected_status),
        },
    )

    result = subprocess.run(
        ["bash", str(launcher)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    events = event_log.read_text(encoding="utf-8")
    assert result.returncode == expected_status
    assert "static:start:" in events
    assert "api:start:" in events
    assert f"{terminated_role}:term" in events
    assert str(venv / "bin") in events
    assert str(launcher.parents[1]) in events
    assert "/opt/mds/venv" not in launcher.read_text(encoding="utf-8")


def test_gcs_dashboard_service_preserves_explicit_mode_and_machine_auth(tmp_path):
    launcher, venv, event_log = _launcher_fixture(tmp_path)
    env = _launcher_env(
        venv,
        event_log,
        MDS_MODE="sitl",
        MDS_AUTH_ENABLED="true",
        MDS_API_AUTH_ENABLED="true",
        MDS_SAFE_PRODUCTION_DEMO="FALSE",
        MDS_TEST_API_MODE="exit",
        MDS_TEST_API_EXIT_CODE="25",
    )

    result = subprocess.run(
        ["bash", str(launcher)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    events = event_log.read_text(encoding="utf-8")
    assert result.returncode == 25
    assert events.count("mode=sitl:auth=true:api_auth=true") == 2


def test_gcs_dashboard_service_defaults_to_warned_trusted_lab_auth_posture(tmp_path):
    launcher, venv, event_log = _launcher_fixture(tmp_path)
    env = _launcher_env(
        venv,
        event_log,
        MDS_TEST_API_MODE="exit",
        MDS_TEST_API_EXIT_CODE="27",
    )

    result = subprocess.run(
        ["bash", str(launcher)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    events = event_log.read_text(encoding="utf-8")
    assert result.returncode == 27
    assert events.count("mode=real:auth=false:api_auth=unset") == 2
    assert "trusted lab/SITL network" in result.stderr


def test_gcs_dashboard_service_uses_active_virtualenv_as_fallback(tmp_path):
    launcher, venv, event_log = _launcher_fixture(tmp_path)
    env = _launcher_env(
        venv,
        event_log,
        MDS_TEST_STATIC_MODE="exit",
        MDS_TEST_STATIC_EXIT_CODE="26",
    )
    env.pop("MDS_VENV_PATH")
    env["VIRTUAL_ENV"] = str(venv)

    result = subprocess.run(
        ["bash", str(launcher)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 26
    assert str(venv / "bin") in event_log.read_text(encoding="utf-8")


def test_gcs_dashboard_service_treats_clean_child_exit_as_failure(tmp_path):
    launcher, venv, event_log = _launcher_fixture(tmp_path)
    env = _launcher_env(
        venv,
        event_log,
        MDS_TEST_STATIC_MODE="exit",
        MDS_TEST_STATIC_EXIT_CODE="0",
    )

    result = subprocess.run(
        ["bash", str(launcher)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 1
    assert "exited unexpectedly" in result.stderr
    assert "api:term" in event_log.read_text(encoding="utf-8")


def test_gcs_dashboard_service_sigterm_stops_and_reaps_both_children(tmp_path):
    launcher, venv, event_log = _launcher_fixture(tmp_path)
    process = subprocess.Popen(
        ["bash", str(launcher)],
        cwd=tmp_path,
        env=_launcher_env(venv, event_log),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_events(event_log, {"static:start:", "api:start:"})
        process.terminate()
        _, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    events = _wait_for_events(event_log, {"static:term", "api:term"})
    assert process.returncode == 143
    assert "static:term" in events
    assert "api:term" in events
    assert stderr.count("trusted lab/SITL network") == 1
