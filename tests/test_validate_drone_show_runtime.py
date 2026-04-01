import importlib.util
import sys
from pathlib import Path

import pytest


def _load_validator():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "validate_drone_show_runtime.py"
    spec = importlib.util.spec_from_file_location("validate_drone_show_runtime", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_check_deviation_signal_allows_subset_when_unselected_drones_have_no_telemetry():
    validator = _load_validator()

    class _Client:
        def get_json(self, path):
            assert path == "/get-position-deviations"
            return {
                "deviations": {
                    "1": {"status": "ok", "current": {"lat": 1}},
                    "2": {"status": "warning", "current": {"lat": 2}},
                    "3": {"status": "ok", "current": {"lat": 3}},
                    "4": {"status": "no_telemetry", "current": None},
                    "5": {"status": "no_telemetry", "current": None},
                },
                "summary": {"online": 3, "no_telemetry": 2},
            }

    validator.check_deviation_signal(_Client(), [1, 2, 3])


def test_check_deviation_signal_rejects_selected_drone_without_live_telemetry():
    validator = _load_validator()

    class _Client:
        def get_json(self, path):
            assert path == "/get-position-deviations"
            return {
                "deviations": {
                    "1": {"status": "ok", "current": {"lat": 1}},
                    "2": {"status": "no_telemetry", "current": None},
                    "3": {"status": "warning", "current": {"lat": 3}},
                },
                "summary": {"online": 2, "no_telemetry": 1},
            }

    with pytest.raises(RuntimeError, match="Deviation endpoint missing live telemetry"):
        validator.check_deviation_signal(_Client(), [1, 2, 3])


def test_check_deviation_signal_rejects_selected_launch_blockers():
    validator = _load_validator()

    class _Client:
        def get_json(self, path):
            assert path == "/get-position-deviations"
            return {
                "deviations": {
                    "1": {"status": "ok", "current": {"lat": 1}},
                    "2": {"status": "error", "current": {"lat": 2}, "message": "Deviation exceeds error threshold"},
                    "3": {"status": "warning", "current": {"lat": 3}},
                    "4": {"status": "no_telemetry", "current": None},
                },
                "summary": {"online": 3, "no_telemetry": 1, "errors": 1},
            }

    with pytest.raises(RuntimeError, match="launch-blocking placement errors"):
        validator.check_deviation_signal(_Client(), [1, 2, 3])
