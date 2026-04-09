import urllib.error

from tools.validate_px4_params_runtime import (
    _selected_drone_api_health_snapshot,
    build_qgc_file,
    choose_param_value,
)


def test_choose_param_value_advances_float_within_bounds():
    row = {
        "name": "MPC_XY_VEL_MAX",
        "value_type": "float",
        "value": 12.0,
        "min_value": 0.0,
        "max_value": 20.0,
    }

    assert choose_param_value(row, delta=1.0) == 13.0


def test_choose_param_value_flips_direction_when_upper_bound_would_be_exceeded():
    row = {
        "name": "MPC_XY_VEL_MAX",
        "value_type": "float",
        "value": 19.8,
        "min_value": 0.0,
        "max_value": 20.0,
    }

    assert choose_param_value(row, delta=1.0) == 18.8


def test_build_qgc_file_uses_qgroundcontrol_header_and_types():
    payload = build_qgc_file(
        hw_id="2",
        component_id=1,
        name="MPC_XY_VEL_MAX",
        value=12.5,
        value_type="float",
    )

    assert payload.startswith("# QGroundControl Parameter File")
    assert "2\t1\tMPC_XY_VEL_MAX\t12.5\t9" in payload


def test_selected_drone_api_health_snapshot_returns_telemetry_when_all_targets_are_ready():
    calls = []

    class _Client:
        def get_telemetry(self):
            return {
                "1": {"ip": "10.0.0.1"},
                "2": {"ip": "10.0.0.2"},
            }

        def get_drone_json(self, drone_ip, path, *, timeout=20.0):
            calls.append((drone_ip, path, timeout))
            return {"status": "ok"}

    telemetry = _selected_drone_api_health_snapshot(_Client(), [1, 2])

    assert telemetry == {
        "1": {"ip": "10.0.0.1"},
        "2": {"ip": "10.0.0.2"},
    }
    assert calls == [
        ("10.0.0.1", "/api/v1/system/health", 5.0),
        ("10.0.0.2", "/api/v1/system/health", 5.0),
    ]


def test_selected_drone_api_health_snapshot_returns_false_when_probe_is_unreachable():
    class _Client:
        def get_telemetry(self):
            return {
                "1": {"ip": "10.0.0.1"},
            }

        def get_drone_json(self, drone_ip, path, *, timeout=20.0):
            raise urllib.error.URLError("connection refused")

    assert _selected_drone_api_health_snapshot(_Client(), [1]) is False
