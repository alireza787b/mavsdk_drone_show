import importlib.util
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

    timeout = validator.estimate_command_completion_timeout(500.0, end_behavior="return_home")

    assert timeout >= 500 + validator.Params.SWARM_TRAJECTORY_RTL_COMPLETION_TIMEOUT + 60


def test_estimate_command_completion_timeout_for_land_current_is_shorter_than_rtl():
    validator = _load_validator_module()

    rtl_timeout = validator.estimate_command_completion_timeout(500.0, end_behavior="return_home")
    land_timeout = validator.estimate_command_completion_timeout(500.0, end_behavior="land_current")

    assert land_timeout < rtl_timeout
