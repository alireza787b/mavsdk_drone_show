import importlib.util
import csv
from pathlib import Path


def _load_validator_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "validate_swarm_trajectory_runtime.py"
    spec = importlib.util.spec_from_file_location("validate_swarm_trajectory_runtime", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_estimate_command_completion_timeout_includes_rtl_window():
    validator = _load_validator_module()

    timeout = validator.estimate_command_completion_timeout(
        500.0,
        end_behavior="return_home",
        relative_altitude_m=250.0,
    )

    assert timeout >= 500 + validator.calculate_swarm_rtl_completion_timeout(250.0)


def test_estimate_command_completion_timeout_for_land_current_is_shorter_than_rtl():
    validator = _load_validator_module()

    rtl_timeout = validator.estimate_command_completion_timeout(
        500.0,
        end_behavior="return_home",
        relative_altitude_m=250.0,
    )
    land_timeout = validator.estimate_command_completion_timeout(
        500.0,
        end_behavior="land_current",
        relative_altitude_m=250.0,
    )

    assert land_timeout < rtl_timeout


def test_max_processed_duration_seconds_filters_to_selected_drones(tmp_path):
    validator = _load_validator_module()
    processed_dir = tmp_path / "shapes_sitl" / "swarm_trajectory" / "processed"
    processed_dir.mkdir(parents=True)

    for drone_id, duration in ((1, 120.0), (2, 240.0), (3, 360.0)):
        with (processed_dir / f"Drone {drone_id}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["t", "alt"])
            writer.writeheader()
            writer.writerow({"t": 0, "alt": 1200})
            writer.writerow({"t": duration, "alt": 1300})

    assert validator.max_processed_duration_seconds(tmp_path, drone_ids=[1, 2]) == 240.0


def test_max_processed_relative_altitude_uses_processed_peak_over_baseline(tmp_path):
    validator = _load_validator_module()
    processed_dir = tmp_path / "shapes_sitl" / "swarm_trajectory" / "processed"
    processed_dir.mkdir(parents=True)

    with (processed_dir / "Drone 4.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["t", "alt"])
        writer.writeheader()
        writer.writerow({"t": 0, "alt": 1370.0})
        writer.writerow({"t": 50, "alt": 2600.0})

    with (processed_dir / "Drone 5.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["t", "alt"])
        writer.writeheader()
        writer.writerow({"t": 0, "alt": 1369.0})
        writer.writerow({"t": 50, "alt": 2400.0})

    baselines = {4: 1278.0, 5: 1278.0}

    assert validator.max_processed_relative_altitude_m(tmp_path, baselines, drone_ids=[4, 5]) == 1322.0
