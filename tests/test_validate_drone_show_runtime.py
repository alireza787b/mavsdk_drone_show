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


def test_wait_for_show_launch_ready_checks_deviation_after_idle(monkeypatch):
    validator = _load_validator()
    events = []
    baseline = {"1": {"position_alt": 10.0}}

    def fake_wait_for_idle(client, ids, timeout=120):
        events.append(("idle", list(ids), timeout))
        return baseline

    def fake_check_deviation_signal(client, ids):
        events.append(("deviation", list(ids)))

    monkeypatch.setattr(validator, "wait_for_idle", fake_wait_for_idle)
    monkeypatch.setattr(validator, "check_deviation_signal", fake_check_deviation_signal)

    result = validator.wait_for_show_launch_ready(object(), [1, 2, 3], timeout=77)

    assert result == baseline
    assert events == [("idle", [1, 2, 3], 77), ("deviation", [1, 2, 3])]


def test_run_show_mode_requires_launch_ready_before_dispatch(monkeypatch):
    validator = _load_validator()
    events = []

    class _Client:
        def submit_command(self, mission_type, ids, label, **kwargs):
            events.append(("submit", mission_type, list(ids), label, kwargs))
            return {"command_id": "cmd-1"}

    def fake_wait_for_show_launch_ready(client, ids, timeout=120):
        events.append(("launch_ready", list(ids), timeout))
        return {"1": {"position_alt": 10.0}}

    def fake_wait_for_command(client, command_id, desired_phase=None, terminal=False, timeout=90):
        events.append(("wait_for_command", command_id, desired_phase, terminal, timeout))
        return {"outcome": "completed"}

    def fake_wait_for_idle(client, ids, timeout=120):
        events.append(("wait_for_idle", list(ids), timeout))
        return {}

    monkeypatch.setattr(validator, "wait_for_show_launch_ready", fake_wait_for_show_launch_ready)
    monkeypatch.setattr(validator, "wait_for_command", fake_wait_for_command)
    monkeypatch.setattr(validator, "wait_for_idle", fake_wait_for_idle)

    validator.run_show_mode(
        _Client(),
        [1, 2, 3],
        label="demo",
        auto_global_origin=True,
        use_global_setpoints=True,
        show_timeout=180,
    )

    assert events[0] == ("launch_ready", [1, 2, 3], 120)
    assert events[1][0] == "submit"


def test_api_client_get_json_retries_after_connection_reset(monkeypatch):
    validator = _load_validator()

    class _Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class _Session:
        def __init__(self, responses):
            self.responses = list(responses)
            self.headers = {}
            self.closed = False

        def get(self, url, timeout):
            outcome = self.responses.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def close(self):
            self.closed = True

    first = _Session([validator.requests.ConnectionError("connection reset by peer")])
    second = _Session([_Response({"status": "ok"})])
    sessions = [first, second]

    monkeypatch.setattr(validator.requests, "Session", lambda: sessions.pop(0))

    client = validator.ApiClient("http://example.test")

    assert client.get_json("/health") == {"status": "ok"}
    assert first.closed is True
