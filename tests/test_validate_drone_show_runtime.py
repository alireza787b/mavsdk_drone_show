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
            assert path == "/api/v1/origin/deviations"
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
            assert path == "/api/v1/origin/deviations"
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
            assert path == "/api/v1/origin/deviations"
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
    assert events == [("idle", [1, 2, 3], 15), ("deviation", [1, 2, 3])]


def test_wait_for_show_launch_ready_retries_transient_deviation_failure(monkeypatch):
    validator = _load_validator()
    events = []
    baseline = {"1": {"position_alt": 10.0}}
    attempts = {"count": 0}

    def fake_wait_for_idle(client, ids, timeout=120):
        events.append(("idle", list(ids), timeout))
        return baseline

    def fake_check_deviation_signal(client, ids):
        attempts["count"] += 1
        events.append(("deviation", list(ids), attempts["count"]))
        if attempts["count"] == 1:
            raise RuntimeError("stale deviation snapshot")

    monkeypatch.setattr(validator, "wait_for_idle", fake_wait_for_idle)
    monkeypatch.setattr(validator, "check_deviation_signal", fake_check_deviation_signal)
    monkeypatch.setattr(validator.time, "sleep", lambda *_args, **_kwargs: None)

    result = validator.wait_for_show_launch_ready(object(), [1, 2, 3], timeout=30)

    assert result == baseline
    assert events == [
        ("idle", [1, 2, 3], 15),
        ("deviation", [1, 2, 3], 1),
        ("idle", [1, 2, 3], 15),
        ("deviation", [1, 2, 3], 2),
    ]


def test_wait_for_live_launch_probe_ready_polls_selected_drone_ips(monkeypatch):
    validator = _load_validator()
    events = []

    class _Client:
        def get_telemetry(self):
            events.append(("telemetry",))
            return {
                "1": {"telemetry_available": True, "ip": "172.18.0.2"},
                "2": {"telemetry_available": True, "ip": "172.18.0.3"},
                "3": {"telemetry_available": True, "ip": "172.18.0.4"},
            }

        def probe_live_armability(self, drone_ip, require_global_position=True):
            events.append(("probe", drone_ip, require_global_position))
            return {"ready": True, "summary": "Ready for launch"}

    result = validator.wait_for_live_launch_probe_ready(_Client(), [1, 2, 3], timeout=5)

    assert result == {
        "1": {"ready": True, "summary": "Ready for launch"},
        "2": {"ready": True, "summary": "Ready for launch"},
        "3": {"ready": True, "summary": "Ready for launch"},
    }
    assert events == [
        ("telemetry",),
        ("probe", "172.18.0.2", True),
        ("probe", "172.18.0.3", True),
        ("probe", "172.18.0.4", True),
    ]


def test_wait_for_dispatch_readiness_checks_geometry_then_live_probe(monkeypatch):
    validator = _load_validator()
    events = []
    baseline = {"1": {"position_alt": 10.0}}

    def fake_wait_for_show_launch_ready(client, ids, timeout=120):
        events.append(("show_launch_ready", list(ids), timeout))
        return baseline

    def fake_wait_for_live_launch_probe_ready(client, ids, timeout=120):
        events.append(("live_probe_ready", list(ids), timeout))
        return {"1": {"ready": True}}

    monkeypatch.setattr(validator, "wait_for_show_launch_ready", fake_wait_for_show_launch_ready)
    monkeypatch.setattr(validator, "wait_for_live_launch_probe_ready", fake_wait_for_live_launch_probe_ready)

    result = validator.wait_for_dispatch_readiness(object(), [1, 2, 3], timeout=77)

    assert result == baseline
    assert events == [
        ("show_launch_ready", [1, 2, 3], 77),
        ("live_probe_ready", [1, 2, 3], 77),
    ]


def test_run_show_mode_requires_launch_ready_before_dispatch(monkeypatch):
    validator = _load_validator()
    events = []

    class _Client:
        def submit_command(self, mission_type, ids, label, **kwargs):
            events.append(("submit", mission_type, list(ids), label, kwargs))
            return {"command_id": "cmd-1"}

    def fake_wait_for_dispatch_readiness(client, ids, timeout=120):
        events.append(("dispatch_ready", list(ids), timeout))
        return {"1": {"position_alt": 10.0}}

    def fake_wait_for_command(client, command_id, desired_phase=None, terminal=False, timeout=90):
        events.append(("wait_for_command", command_id, desired_phase, terminal, timeout))
        return {"outcome": "completed"}

    def fake_wait_for_idle(client, ids, timeout=120):
        events.append(("wait_for_idle", list(ids), timeout))
        return {}

    monkeypatch.setattr(validator, "wait_for_dispatch_readiness", fake_wait_for_dispatch_readiness)
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

    assert events[0] == ("dispatch_ready", [1, 2, 3], 120)
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


def test_reset_sitl_fleet_recreates_selected_contiguous_fleet(monkeypatch, tmp_path):
    validator = _load_validator()
    calls = []

    def fake_run(cmd, cwd, check, capture_output, text, env):
        calls.append(("run", cmd, cwd, check, capture_output, text, env is not None))

        class _Completed:
            stdout = "line-1\nline-2\nAll 3 instance(s) created and verified ready.\n"
            stderr = ""

        return _Completed()

    def fake_wait_for_show_launch_ready(client, ids, timeout=120):
        calls.append(("wait", list(ids), timeout))
        return {"1": {"position_alt": 10.0}}

    monkeypatch.setattr(validator.subprocess, "run", fake_run)
    monkeypatch.setattr(validator, "wait_for_show_launch_ready", fake_wait_for_show_launch_ready)

    result = validator.reset_sitl_fleet(object(), tmp_path, [1, 2, 3], timeout=91)

    assert result == {"1": {"position_alt": 10.0}}
    assert calls[0][:4] == (
        "run",
        ["bash", "multiple_sitl/create_dockers.sh", "3"],
        tmp_path,
        True,
    )
    assert calls[1] == ("wait", [1, 2, 3], 91)


def test_reset_sitl_fleet_rejects_non_contiguous_selection():
    validator = _load_validator()

    with pytest.raises(RuntimeError, match="contiguous drone IDs"):
        validator.reset_sitl_fleet(object(), Path("/tmp/repo"), [1, 3], timeout=10)


def test_submit_show_command_with_retry_rechecks_launch_ready_after_http_400(monkeypatch):
    validator = _load_validator()
    events = []

    class _Client:
        def __init__(self):
            self.calls = 0

        def submit_command(self, mission_type, ids, label, **kwargs):
            self.calls += 1
            events.append(("submit", self.calls, mission_type, list(ids), label, kwargs))
            if self.calls == 1:
                response = type(
                    "Response",
                    (),
                    {
                        "status_code": 400,
                        "text": '{"detail":"Live launch readiness probe failed. Drone 1: transient armability gate"}',
                        "json": lambda self: {"detail": "Live launch readiness probe failed. Drone 1: transient armability gate"},
                    },
                )()
                raise validator.requests.HTTPError("bad request", response=response)
            return {"command_id": "cmd-2"}

    def fake_wait_for_dispatch_readiness(client, ids, timeout=120):
        events.append(("dispatch_ready", list(ids), timeout))
        return {"1": {"position_alt": 10.0}}

    monkeypatch.setattr(validator, "wait_for_dispatch_readiness", fake_wait_for_dispatch_readiness)
    monkeypatch.setattr(validator.time, "sleep", lambda *_args, **_kwargs: None)

    response = validator.submit_show_command_with_retry(
        _Client(),
        validator.SHOW_MISSION,
        [1, 2, 3],
        "demo",
        trigger_time=0,
        auto_global_origin=False,
        use_global_setpoints=False,
        readiness_timeout=45,
    )

    assert response == {"command_id": "cmd-2"}
    assert events == [
        ("submit", 1, validator.SHOW_MISSION, [1, 2, 3], "demo", {
            "trigger_time": 0,
            "auto_global_origin": False,
            "use_global_setpoints": False,
        }),
        ("dispatch_ready", [1, 2, 3], 45),
        ("submit", 2, validator.SHOW_MISSION, [1, 2, 3], "demo", {
            "trigger_time": 0,
            "auto_global_origin": False,
            "use_global_setpoints": False,
        }),
    ]


def test_submit_show_command_with_retry_does_not_retry_unrelated_http_400(monkeypatch):
    validator = _load_validator()

    class _Client:
        def submit_command(self, mission_type, ids, label, **kwargs):
            response = type(
                "Response",
                (),
                {
                    "status_code": 400,
                    "text": '{"detail":"Unsafe Swarm Trajectory target set"}',
                    "json": lambda self: {"detail": "Unsafe Swarm Trajectory target set"},
                },
            )()
            raise validator.requests.HTTPError("bad request", response=response)

    monkeypatch.setattr(validator, "wait_for_dispatch_readiness", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not retry")))

    with pytest.raises(validator.requests.HTTPError):
        validator.submit_show_command_with_retry(
            _Client(),
            validator.SHOW_MISSION,
            [1, 2, 3],
            "demo",
            trigger_time=0,
            auto_global_origin=False,
            use_global_setpoints=False,
            readiness_timeout=45,
        )
