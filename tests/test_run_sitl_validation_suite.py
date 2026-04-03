import importlib.util
import sys
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "run_sitl_validation_suite.py"
    spec = importlib.util.spec_from_file_location("run_sitl_validation_suite", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_suite_steps_includes_initial_reset_and_per_mode_reports(tmp_path):
    suite = _load_module()

    class _Args:
        base_url = "http://127.0.0.1:5000"
        repo_root = tmp_path
        validator_root = tmp_path / "validators"
        python = "/venv/bin/python"
        modes = [suite.MODE_DRONE_SHOW, suite.MODE_SMART_SWARM, suite.MODE_SWARM_TRAJECTORY]
        drone_ids = [1, 2, 3]
        import_source_dir = None
        expected_show_count = 5
        skip_initial_reset = False
        skip_pre_drone_show_reset = False
        skip_drone_show_internal_reset = False
        smart_swarm_skip_reassign = False
        smart_swarm_takeoff_min_gain = 4.0
        smart_swarm_horizontal_tolerance = 5.0
        smart_swarm_altitude_tolerance = 1.5
        smart_swarm_formation_min_timeout = 45
        smart_swarm_max_velocity = 3.0
        smart_swarm_stability_samples = 3
        prepare_short_profile = True
        short_profile_altitude_gain = 12.0
        short_profile_entry_delay = 8.0
        short_profile_leg_duration = 10.0
        trajectory_horiz_tolerance = 18.0
        trajectory_vert_tolerance = 8.0
        trajectory_min_altitude_gain = 2.0
        trajectory_formation_timeout = 120

    steps = suite.build_suite_steps(_Args(), tmp_path / "artifacts")

    assert [step.name for step in steps] == [
        "reset_before_suite",
        "drone_show",
        "smart_swarm",
        "swarm_trajectory",
    ]
    assert steps[0].cwd == tmp_path
    assert steps[1].cwd == tmp_path / "validators"
    assert steps[1].json_path == tmp_path / "artifacts" / "drone_show.json"
    assert steps[1].command[steps[1].command.index("--repo-root") + 1] == str(tmp_path)
    assert "--json-output" in steps[2].command
    assert "--prepare-short-profile" in steps[3].command


def test_build_suite_steps_inserts_reset_before_late_drone_show(tmp_path):
    suite = _load_module()

    class _Args:
        base_url = "http://127.0.0.1:5000"
        repo_root = tmp_path
        validator_root = tmp_path / "validators"
        python = "/venv/bin/python"
        modes = [suite.MODE_SMART_SWARM, suite.MODE_DRONE_SHOW]
        drone_ids = [4, 5, 6]
        import_source_dir = None
        expected_show_count = 5
        skip_initial_reset = True
        skip_pre_drone_show_reset = False
        skip_drone_show_internal_reset = False
        smart_swarm_skip_reassign = False
        smart_swarm_takeoff_min_gain = 4.0
        smart_swarm_horizontal_tolerance = 5.0
        smart_swarm_altitude_tolerance = 1.5
        smart_swarm_formation_min_timeout = 45
        smart_swarm_max_velocity = 3.0
        smart_swarm_stability_samples = 3
        prepare_short_profile = True
        short_profile_altitude_gain = 12.0
        short_profile_entry_delay = 8.0
        short_profile_leg_duration = 10.0
        trajectory_horiz_tolerance = 18.0
        trajectory_vert_tolerance = 8.0
        trajectory_min_altitude_gain = 2.0
        trajectory_formation_timeout = 120

    steps = suite.build_suite_steps(_Args(), tmp_path / "artifacts")

    assert [step.name for step in steps] == [
        "smart_swarm",
        "reset_before_drone_show",
        "drone_show",
    ]
    assert steps[1].command == ["bash", "multiple_sitl/create_dockers.sh", "3", "--start-id", "4", "--start-ip", "5"]


def test_parse_modes_rejects_unknown_values():
    suite = _load_module()

    try:
        suite.parse_modes("drone_show,unknown")
    except Exception as exc:
        assert "Unsupported validation mode" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected invalid mode parse to fail")
