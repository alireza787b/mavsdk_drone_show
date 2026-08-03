import json
import math
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.command_installation import (
    CommandInstallationRejected,
    CommandInstallationResult,
)
from src.drone_communicator import DroneCommunicator
from src.enums import Mission, State


class FailOnceConfig(SimpleNamespace):
    """Config double that can inject one setter failure and then permit rollback."""

    def arm_set_failure(self, field_name: str) -> None:
        object.__setattr__(self, "_fail_field", field_name)
        object.__setattr__(self, "_failure_fired", False)

    def __setattr__(self, field_name, value):
        if (
            field_name == getattr(self, "_fail_field", None)
            and not getattr(self, "_failure_fired", False)
        ):
            object.__setattr__(self, "_failure_fired", True)
            raise OSError(f"injected setter failure: {field_name}")
        object.__setattr__(self, field_name, value)


def _build_communicator(tmp_path: Path, monkeypatch, *, config_type=FailOnceConfig):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = config_type(
        hw_id="1",
        pos_id=1,
        state=State.MISSION_READY.value,
        mission=Mission.TAKE_OFF.value,
        trigger_time=123,
        current_command_id="old-command",
        update_branch="old-branch",
        quickscout_mission_id="old-mission",
        quickscout_waypoints_file="/old/quickscout.json",
        quickscout_return_behavior="hold",
        precision_move_request_file="/old/precision.json",
        auto_global_origin=True,
        use_global_setpoints=True,
        takeoff_altitude=17.0,
        runtime_takeoff_altitude=17.0,
    )
    params = SimpleNamespace(
        enable_udp_telemetry=False,
        enable_default_subscriptions=False,
        default_takeoff_alt=10.0,
        max_takeoff_alt=100.0,
        command_runtime_dir=str(tmp_path / "runtime"),
    )
    drones = {config.hw_id: config}
    return DroneCommunicator(config, params, drones), config, drones


def _command_snapshot(config):
    fields = (
        "state",
        "mission",
        "trigger_time",
        "current_command_id",
        "update_branch",
        "quickscout_mission_id",
        "quickscout_waypoints_file",
        "quickscout_return_behavior",
        "precision_move_request_file",
        "auto_global_origin",
        "use_global_setpoints",
        "takeoff_altitude",
        "runtime_takeoff_altitude",
    )
    return {field: getattr(config, field) for field in fields}


def _transaction_debris(root: Path):
    if not root.exists():
        return []
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and (".stage-" in path.name or ".backup-" in path.name)
    ]


def test_invalid_origin_rejects_without_mutating_prior_command_or_origin(
    tmp_path,
    monkeypatch,
):
    communicator, config, _drones = _build_communicator(tmp_path, monkeypatch)
    origin_dir = tmp_path / "home" / ".mavsdk_drone_show"
    origin_dir.mkdir(parents=True)
    origin_file = origin_dir / "command_origin.json"
    original_bytes = b'{"lat":35.0,"lon":51.0,"alt":1278.0}\n'
    origin_file.write_bytes(original_bytes)
    before = _command_snapshot(config)

    with pytest.raises(CommandInstallationRejected) as failure:
        communicator.process_command(
            {
                "mission_type": Mission.DRONE_SHOW_FROM_CSV.value,
                "trigger_time": 0,
                "command_id": "new-command",
                "auto_global_origin": True,
                "origin": {"lat": 95.0, "lon": 51.0, "alt": 1278.0},
            }
        )

    assert failure.value.phase == "preparation"
    assert _command_snapshot(config) == before
    assert origin_file.read_bytes() == original_bytes
    assert _transaction_debris(tmp_path) == []


def test_non_finite_quickscout_payload_rejects_without_publishing_file_or_config(
    tmp_path,
    monkeypatch,
):
    communicator, config, _drones = _build_communicator(tmp_path, monkeypatch)
    before = _command_snapshot(config)

    with pytest.raises(CommandInstallationRejected) as failure:
        communicator.process_command(
            {
                "mission_type": Mission.QUICKSCOUT.value,
                "trigger_time": 0,
                "command_id": "new-command",
                "mission_id": "survey-a",
                "waypoints": [{"lat": math.nan, "lon": 51.0}],
            }
        )

    assert failure.value.phase == "preparation"
    assert _command_snapshot(config) == before
    assert not any((tmp_path / "runtime").rglob("quickscout_*.json"))
    assert _transaction_debris(tmp_path) == []


def test_config_commit_failure_rolls_back_quickscout_artifact_and_every_field(
    tmp_path,
    monkeypatch,
):
    communicator, config, drones = _build_communicator(tmp_path, monkeypatch)
    before = _command_snapshot(config)
    config.arm_set_failure("mission")

    with pytest.raises(CommandInstallationRejected) as failure:
        communicator.process_command(
            {
                "mission_type": Mission.QUICKSCOUT.value,
                "trigger_time": 0,
                "command_id": "new-command",
                "mission_id": "survey-a",
                "return_behavior": "return_home",
                "waypoints": [{"lat": 35.0, "lon": 51.0}],
            }
        )

    assert failure.value.phase == "config_commit"
    assert _command_snapshot(config) == before
    assert drones[config.hw_id] is config
    assert not any((tmp_path / "runtime").rglob("quickscout_*.json"))
    assert _transaction_debris(tmp_path) == []


def test_config_commit_failure_restores_exact_previous_command_origin(
    tmp_path,
    monkeypatch,
):
    communicator, config, _drones = _build_communicator(tmp_path, monkeypatch)
    origin_dir = tmp_path / "home" / ".mavsdk_drone_show"
    origin_dir.mkdir(parents=True)
    origin_file = origin_dir / "command_origin.json"
    original_bytes = b'{"source":"old","lat":35.0,"lon":51.0,"alt":1278.0}\n'
    origin_file.write_bytes(original_bytes)
    origin_file.chmod(0o640)
    before = _command_snapshot(config)
    config.arm_set_failure("mission")

    with pytest.raises(CommandInstallationRejected) as failure:
        communicator.process_command(
            {
                "mission_type": Mission.DRONE_SHOW_FROM_CSV.value,
                "trigger_time": 0,
                "command_id": "new-command",
                "auto_global_origin": True,
                "origin": {"lat": 36.0, "lon": 52.0, "alt": 1300.0},
            }
        )

    assert failure.value.phase == "config_commit"
    assert _command_snapshot(config) == before
    assert origin_file.read_bytes() == original_bytes
    assert stat.S_IMODE(origin_file.stat().st_mode) == 0o640
    assert _transaction_debris(tmp_path) == []


def test_fallback_origin_command_removes_stale_single_use_origin_only_after_commit(
    tmp_path,
    monkeypatch,
):
    communicator, config, _drones = _build_communicator(tmp_path, monkeypatch)
    origin_dir = tmp_path / "home" / ".mavsdk_drone_show"
    origin_dir.mkdir(parents=True)
    origin_file = origin_dir / "command_origin.json"
    origin_file.write_text('{"source":"old"}\n', encoding="utf-8")

    result = communicator.process_command(
        {
            "mission_type": Mission.DRONE_SHOW_FROM_CSV.value,
            "trigger_time": 0,
            "command_id": "fallback-command",
            "auto_global_origin": True,
        }
    )

    assert isinstance(result, CommandInstallationResult)
    assert result.committed is True
    assert result.command_id == "fallback-command"
    assert config.current_command_id == "fallback-command"
    assert not origin_file.exists()
    assert _transaction_debris(tmp_path) == []


def test_successful_quickscout_install_returns_typed_proof_and_private_artifact(
    tmp_path,
    monkeypatch,
):
    communicator, config, drones = _build_communicator(tmp_path, monkeypatch)

    result = communicator.process_command(
        {
            "mission_type": Mission.QUICKSCOUT.value,
            "trigger_time": 0,
            "command_id": "quickscout-command",
            "mission_id": "survey-a",
            "return_behavior": "return_home",
            "waypoints": [{"lat": 35.0, "lon": 51.0}],
        }
    )

    assert result == CommandInstallationResult(
        committed=True,
        mission=Mission.QUICKSCOUT.value,
        trigger_time=0,
        state=State.MISSION_READY.value,
        command_id="quickscout-command",
        artifact_paths=result.artifact_paths,
    )
    assert len(result.artifact_paths) == 1
    artifact = Path(result.artifact_paths[0])
    assert json.loads(artifact.read_text(encoding="utf-8")) == [
        {"lat": 35.0, "lon": 51.0}
    ]
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
    assert config.quickscout_waypoints_file == str(artifact)
    assert config.current_command_id == "quickscout-command"
    assert config.precision_move_request_file is None
    assert config.update_branch is None
    assert drones[config.hw_id] is config
    assert _transaction_debris(tmp_path) == []
