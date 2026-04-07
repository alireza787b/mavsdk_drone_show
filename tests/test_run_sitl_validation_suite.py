import importlib.util
import json
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


def _build_args(suite, tmp_path, **overrides):
    values = {
        "base_url": "http://127.0.0.1:5000",
        "repo_root": tmp_path,
        "validator_root": tmp_path / "validators",
        "python": "/venv/bin/python",
        "template": suite.TEMPLATE_OPERATOR_REGRESSION,
        "plan_file": None,
        "modes": None,
        "drone_ids": [1, 2, 3],
        "config_metadata_suffix": "-CFG",
        "config_origin_altitude_delta": 0.5,
        "config_swarm_put_offset_delta": 1.25,
        "config_swarm_patch_offset_delta": 2.0,
        "import_source_dir": None,
        "expected_show_count": 5,
        "skip_initial_reset": False,
        "skip_pre_drone_show_reset": False,
        "final_reset": True,
        "skip_drone_show_internal_reset": False,
        "actions_takeoff_min_gain": 4.0,
        "actions_post_rtl_airborne_gain": 2.0,
        "smart_swarm_skip_reassign": False,
        "smart_swarm_takeoff_min_gain": 4.0,
        "smart_swarm_horizontal_tolerance": 5.0,
        "smart_swarm_altitude_tolerance": 1.5,
        "smart_swarm_formation_min_timeout": 45,
        "smart_swarm_max_velocity": 3.0,
        "smart_swarm_stability_samples": 3,
        "prepare_short_profile": True,
        "short_profile_altitude_gain": 12.0,
        "short_profile_entry_delay": 8.0,
        "short_profile_leg_duration": 10.0,
        "trajectory_horiz_tolerance": 18.0,
        "trajectory_vert_tolerance": 8.0,
        "trajectory_min_altitude_gain": 2.0,
        "trajectory_formation_timeout": 120,
        "integrated_takeoff_min_gain": 4.0,
        "integrated_formation_horizontal_tolerance": 8.0,
        "integrated_formation_altitude_tolerance": 2.0,
        "integrated_formation_min_timeout": 45,
        "integrated_max_velocity": 3.0,
        "integrated_stability_samples": 2,
        "integrated_follower_spacing_m": 8.0,
        "integrated_reassign_offset_m": 6.0,
        "integrated_trajectory_altitude_gain": 12.0,
        "integrated_trajectory_entry_delay": 8.0,
        "integrated_trajectory_leg_duration": 14.0,
        "integrated_precision_move_north": 4.0,
        "integrated_precision_move_east": 2.0,
        "integrated_precision_move_up": 0.5,
        "integrated_precision_move_speed": 1.0,
        "integrated_precision_move_tolerance": 0.9,
        "integrated_precision_move_start_threshold": 1.0,
    }
    values.update(overrides)

    class _Args:
        pass

    args = _Args()
    for key, value in values.items():
        setattr(args, key, value)
    return args


def test_build_suite_steps_uses_operator_template_and_actions_validator(tmp_path):
    suite = _load_module()
    args = _build_args(suite, tmp_path)

    steps = suite.build_suite_steps(args, tmp_path / "artifacts")

    assert [step.name for step in steps] == [
        "reset_before_suite",
        suite.MODE_CONFIGURATION,
        "reset_before_drone_show",
        suite.MODE_DRONE_SHOW,
        suite.MODE_ACTIONS,
        suite.MODE_SMART_SWARM,
        suite.MODE_SWARM_TRAJECTORY,
        "reset_after_suite",
    ]
    assert steps[0].command == ["bash", "multiple_sitl/create_dockers.sh", "3"]
    assert steps[1].validator == suite.MODE_CONFIGURATION
    assert steps[1].json_path == tmp_path / "artifacts" / "configuration.json"
    assert "--metadata-suffix=-CFG" in steps[1].command
    assert steps[2].command == ["bash", "multiple_sitl/create_dockers.sh", "3"]
    assert steps[4].validator == suite.MODE_ACTIONS
    assert steps[4].json_path == tmp_path / "artifacts" / "actions.json"
    assert "--post-rtl-airborne-gain" in steps[4].command
    assert "--prepare-short-profile" in steps[6].command
    assert steps[7].command == ["bash", "multiple_sitl/create_dockers.sh", "3"]


def test_build_suite_steps_inserts_reset_before_late_drone_show_from_modes(tmp_path):
    suite = _load_module()
    args = _build_args(
        suite,
        tmp_path,
        template=suite.TEMPLATE_MISSION_REGRESSION,
        modes=[suite.MODE_SMART_SWARM, suite.MODE_DRONE_SHOW],
        drone_ids=[4, 5, 6],
        skip_initial_reset=True,
    )

    steps = suite.build_suite_steps(args, tmp_path / "artifacts")

    assert [step.name for step in steps] == [
        suite.MODE_SMART_SWARM,
        "reset_before_drone_show",
        suite.MODE_DRONE_SHOW,
        "reset_after_suite",
    ]
    assert steps[1].command == ["bash", "multiple_sitl/create_dockers.sh", "3", "--start-id", "4", "--start-ip", "5"]


def test_build_suite_steps_reads_plan_file_with_step_overrides(tmp_path):
    suite = _load_module()
    plan_file = tmp_path / "suite-plan.json"
    plan_file.write_text(
        json.dumps(
            {
                "steps": [
                    {"validator": suite.MODE_ACTIONS, "options": {"actions_takeoff_min_gain": 5.5}},
                    {"kind": "reset", "name": "mid_suite_reset", "drone_ids": [7, 8, 9]},
                    {
                        "validator": suite.MODE_SWARM_TRAJECTORY,
                        "name": "trajectory_short_profile",
                        "drone_ids": [7, 8, 9],
                        "options": {
                            "prepare_short_profile": False,
                            "trajectory_formation_timeout": 180,
                        },
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    args = _build_args(suite, tmp_path, plan_file=plan_file, drone_ids=[1, 2, 3])

    steps = suite.build_suite_steps(args, tmp_path / "artifacts")

    assert [step.name for step in steps] == [
        "reset_before_suite",
        suite.MODE_ACTIONS,
        "mid_suite_reset",
        "trajectory_short_profile",
        "reset_after_suite",
    ]
    assert steps[1].drone_ids == (1, 2, 3)
    assert steps[1].command[steps[1].command.index("--takeoff-min-gain") + 1] == "5.5"
    assert steps[2].command == ["bash", "multiple_sitl/create_dockers.sh", "3", "--start-id", "7", "--start-ip", "8"]
    assert "--prepare-short-profile" not in steps[3].command
    assert steps[3].command[steps[3].command.index("--formation-timeout") + 1] == "180"
    assert steps[4].command == ["bash", "multiple_sitl/create_dockers.sh", "3"]


def test_list_templates_mentions_operator_and_actions_templates():
    suite = _load_module()

    output = suite.list_templates()

    assert suite.TEMPLATE_OPERATOR_REGRESSION in output
    assert suite.TEMPLATE_ACTIONS_ONLY in output
    assert suite.TEMPLATE_CONFIG_ONLY in output
    assert suite.TEMPLATE_INTEGRATED_ONLY in output
    assert suite.MODE_ACTIONS in output
    assert suite.MODE_CONFIGURATION in output
    assert suite.MODE_INTEGRATED_RUNTIME in output


def test_write_suite_summary_skips_side_effects_in_dry_run(tmp_path):
    suite = _load_module()
    summary_path = tmp_path / "suite-summary.json"

    suite.write_suite_summary(summary_path, {"status": "dry_run"}, dry_run=True)

    assert summary_path.exists() is False


def test_parse_modes_rejects_unknown_values():
    suite = _load_module()

    try:
        suite.parse_modes("drone_show,unknown")
    except Exception as exc:
        assert "Unsupported validation mode" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected invalid mode parse to fail")


def test_git_metadata_tolerates_non_git_paths(tmp_path):
    suite = _load_module()

    metadata = suite.git_metadata(tmp_path / "plain-dir")

    assert metadata == {
        "path": str(tmp_path / "plain-dir"),
        "head": None,
        "branch": None,
        "dirty": None,
    }


def test_list_bundled_plans_reports_curated_entries(tmp_path):
    suite = _load_module()
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    (bundled_dir / "actions_core.json").write_text(
        json.dumps(
            {
                "title": "Actions Core",
                "description": "Takeoff, hold, RTL override, land",
                "steps": [{"validator": suite.MODE_ACTIONS}],
            }
        ),
        encoding="utf-8",
    )
    suite.BUNDLED_PLAN_DIR = bundled_dir

    output = suite.list_bundled_plans()

    assert "actions_core" in output
    assert "Actions Core" in output
    assert "Takeoff, hold, RTL override, land" in output


def test_parse_args_resolves_plan_name_to_bundled_plan(tmp_path, monkeypatch):
    suite = _load_module()
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    (bundled_dir / "smart_swarm_runtime.json").write_text(
        json.dumps(
            {
                "title": "Smart Swarm Runtime",
                "steps": [{"validator": suite.MODE_SMART_SWARM}],
            }
        ),
        encoding="utf-8",
    )
    suite.BUNDLED_PLAN_DIR = bundled_dir

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_sitl_validation_suite.py",
            "--plan-name",
            "smart_swarm_runtime",
        ],
    )

    args = suite.parse_args()

    assert args.plan_name == "smart_swarm_runtime"
    assert args.plan_file == (bundled_dir / "smart_swarm_runtime.json").resolve()


def test_build_suite_steps_uses_bundled_plan_name(tmp_path):
    suite = _load_module()
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    plan_path = bundled_dir / "config_then_drone_show.json"
    plan_path.write_text(
        json.dumps(
            {
                "title": "Config Then Drone Show",
                "steps": [
                    {"validator": suite.MODE_CONFIGURATION},
                    {"validator": suite.MODE_DRONE_SHOW},
                ],
            }
        ),
        encoding="utf-8",
    )
    suite.BUNDLED_PLAN_DIR = bundled_dir
    args = _build_args(
        suite,
        tmp_path,
        template=suite.TEMPLATE_ACTIONS_ONLY,
        plan_file=plan_path,
        plan_name="config_then_drone_show",
    )

    steps = suite.build_suite_steps(args, tmp_path / "artifacts")

    assert [step.name for step in steps] == [
        "reset_before_suite",
        suite.MODE_CONFIGURATION,
        "reset_before_drone_show",
        suite.MODE_DRONE_SHOW,
        "reset_after_suite",
    ]


def test_build_suite_steps_supports_integrated_runtime_mode(tmp_path):
    suite = _load_module()
    args = _build_args(
        suite,
        tmp_path,
        template=suite.TEMPLATE_INTEGRATED_ONLY,
        modes=[suite.MODE_INTEGRATED_RUNTIME],
    )

    steps = suite.build_suite_steps(args, tmp_path / "artifacts")

    assert [step.name for step in steps] == [
        "reset_before_suite",
        suite.MODE_INTEGRATED_RUNTIME,
        "reset_after_suite",
    ]
    assert steps[1].validator == suite.MODE_INTEGRATED_RUNTIME
    assert steps[1].json_path == tmp_path / "artifacts" / "integrated_runtime.json"
    assert "tools/validate_integrated_runtime.py" in steps[1].command
    assert "--precision-move-east" in steps[1].command
