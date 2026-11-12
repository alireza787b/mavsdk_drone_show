import urllib.error
import pytest
from tools import validate_px4_params_runtime as runtime

from tools.validate_px4_params_runtime import (
    _selected_drone_api_health_snapshot,
    build_qgc_file,
    choose_param_value,
    select_baseline_rows,
    run_patch_job,
    restore_baseline,
)


def test_patch_validator_reviews_then_polls_and_replays_only_the_same_receipt():
    calls = []
    class Client:
        def post_json(self, path, body):
            calls.append((path, body))
            if path == runtime.GCS_PX4_PARAMS_REVIEWS_ROUTE:
                return {"review_id": "r1", "review_hash": "h1", "blocked": False}
            return {"job_id": "j1", "status": "queued"}
        def get_json(self, path):
            calls.append((path, None))
            return {"job_id": "j1", "status": "completed", "terminal": True}
    result = run_patch_job(Client(), drone_ids=[1], source="manual", entries=[{"name": "TEST"}])
    assert result["job_id"] == "j1"
    assert calls[0][0] == runtime.GCS_PX4_PARAMS_REVIEWS_ROUTE
    assert calls[1][1] == calls[3][1]
    assert calls[1][1]["review_id"] == "r1"
    assert "entries" not in calls[1][1]


def test_health_check_tolerates_connection_refused_during_startup(monkeypatch):
    calls = []
    class Client:
        def get_json(self, path, *, timeout):
            calls.append(path)
            if len(calls) == 1:
                raise urllib.error.URLError("connection refused")
            return {"status": "ok"}
    def poll(predicate, **kwargs):
        assert predicate() is False
        assert predicate() == {"status": "ok"}
    monkeypatch.setattr(runtime, "wait_for", poll)
    runtime.wait_for_health(Client())
    assert len(calls) == 2


def test_restore_attempts_later_aircraft_even_when_first_read_fails(monkeypatch):
    seen = []
    def refresh(client, ids, *, component_id):
        seen.extend(ids)
        if ids == [1]:
            raise RuntimeError("unreachable")
        return {"2": {"snapshot": {"snapshot_id": "s2"}, "rows": [{"name": "TEST", "value": 3, "value_type": "int"}]}}
    monkeypatch.setattr(runtime, "refresh_snapshots", refresh)
    with pytest.raises(RuntimeError, match="H1: unreachable"):
        restore_baseline(object(), {"1": {"value": 2, "value_type": "int"}, "2": {"value": 3, "value_type": "int"}},
                         drone_ids=[1, 2], component_id=1, param_name="TEST")
    assert seen == [1, 2]


def test_restore_accepts_only_a_freshly_observed_matching_baseline(monkeypatch):
    monkeypatch.setattr(runtime, "refresh_snapshots", lambda *args, **kwargs: {
        "1": {"snapshot": {"snapshot_id": "fresh"}, "rows": [{"name": "TEST", "value": 3, "value_type": "int"}]}})
    monkeypatch.setattr(runtime, "run_patch_job", lambda *args, **kwargs: pytest.fail("No repair write needed"))
    evidence = restore_baseline(object(), {"1": {"value": 3, "value_type": "int"}}, drone_ids=[1], component_id=1, param_name="TEST")
    assert evidence == [{"hw_id": "1", "outcome": "already_at_baseline", "snapshot_id": "fresh"}]


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


def test_select_baseline_rows_normalizes_selected_ids_to_string_keys():
    baseline_rows = {
        "1": {"name": "PARAM_A"},
        "2": {"name": "PARAM_B"},
    }

    assert select_baseline_rows(baseline_rows, [1, 2]) == {
        "1": {"name": "PARAM_A"},
        "2": {"name": "PARAM_B"},
    }
