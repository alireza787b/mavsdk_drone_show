from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.commands import _estimate_max_target_relative_altitude_m, create_command_router
from command_tracker import CommandIdempotencyConflictError, CommandCreationResult


class _DummyTracker:
    def __init__(self, *, statistics=None, replay_command=None, replay_conflict=False):
        self.statistics = statistics or {
            "total_commands": 0,
            "successful_commands": 0,
            "failed_commands": 0,
            "partial_commands": 0,
            "timeout_commands": 0,
            "cancelled_commands": 0,
            "active_commands": 0,
            "tracked_commands": 0,
            "success_rate": 0.0,
        }
        self.replay_command = replay_command
        self.replay_conflict = replay_conflict
        self.create_calls = []

    async def get_statistics(self):
        return self.statistics

    async def get_status(self, command_id):
        if self.replay_command and self.replay_command.get("command_id") == command_id:
            return self.replay_command
        del command_id
        return None

    async def get_recent(self, **kwargs):
        del kwargs
        return []

    async def get_active_commands(self):
        return []

    async def lookup_command_by_idempotency_key(self, idempotency_key, *, request_fingerprint=None):
        del request_fingerprint
        if self.replay_conflict:
            raise CommandIdempotencyConflictError(
                f"idempotency_key '{idempotency_key}' is already bound to a different command payload"
            )
        if idempotency_key and self.replay_command:
            return self.replay_command
        return None

    async def create_or_replay_command(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.replay_conflict:
            raise CommandIdempotencyConflictError("replay conflict")
        return CommandCreationResult(command_id="cmd-1", replayed=False)

    async def create_command(self, **kwargs):
        del kwargs
        return "cmd-1"

    async def mark_submitted(self, command_id):
        del command_id
        return None

    async def record_ack(self, *args, **kwargs):
        del args, kwargs
        return None

    async def record_execution(self, **kwargs):
        del kwargs
        return True

    async def record_execution_start(self, **kwargs):
        del kwargs
        return True


class _MissionMember:
    def __init__(self, value, name):
        self.value = value
        self.name = name

    def __eq__(self, other):
        if isinstance(other, _MissionMember):
            return self.value == other.value
        return self.value == other

    def __hash__(self):
        return hash(self.value)


class _MissionShim:
    TAKE_OFF = _MissionMember(10, "TAKE_OFF")
    SWARM_TRAJECTORY = _MissionMember(4, "SWARM_TRAJECTORY")
    LAND = _MissionMember(101, "LAND")
    RETURN_RTL = _MissionMember(102, "RETURN_RTL")

    _by_value = {
        4: SWARM_TRAJECTORY,
        10: TAKE_OFF,
        101: LAND,
        102: RETURN_RTL,
    }
    _by_name = {
        "SWARM_TRAJECTORY": SWARM_TRAJECTORY,
        "TAKE_OFF": TAKE_OFF,
        "LAND": LAND,
        "RETURN_RTL": RETURN_RTL,
    }

    def __call__(self, value):
        return self._by_value[int(value)]


def _make_deps():
    deps = SimpleNamespace()
    deps.current_tracker = _DummyTracker()
    deps.get_command_tracker = lambda: deps.current_tracker
    deps.Mission = _MissionShim()
    deps.Params = SimpleNamespace(
        GCS_TELEMETRY_REQUEST_TIMEOUT_SEC=1.0,
        drone_api_port=5001,
        get_drone_home_URI="get-home-pos",
    )
    deps.telemetry_lock = nullcontext()
    deps.telemetry_data_all_drones = {}
    deps.resolve_mission_type = lambda mission_type: (
        deps.Mission._by_name.get(str(mission_type).upper())
        if str(mission_type).upper() in deps.Mission._by_name
        else deps.Mission._by_value.get(int(mission_type))
    )
    deps.mission_requires_launch_armability_probe = lambda mission: False
    deps.probe_live_armability_for_drones = lambda *args, **kwargs: {
        "all_ready": True,
        "blocked_ids": [],
        "unavailable_ids": [],
        "results": {},
    }
    deps.send_commands_to_all = lambda *args, **kwargs: {
        "success": 1,
        "offline": 0,
        "rejected": 0,
        "errors": 0,
        "result_summary": "1 accepted",
        "results": {"1": {"success": True, "category": "accepted"}},
    }
    deps.send_commands_to_selected = deps.send_commands_to_all
    deps.load_config = lambda: [{"hw_id": 1, "pos_id": 1, "ip": "127.0.0.1"}]
    deps.load_origin = lambda: None
    deps.skybrush_dir = "/tmp/skybrush"
    deps.processed_dir = "/tmp/processed"
    deps.shapes_dir = "/tmp/shapes"
    deps.get_swarm_trajectory_folders = lambda: {"processed": "/tmp/processed"}
    deps.estimate_command_tracking_timeout_ms = lambda *args, **kwargs: 1000
    deps.swarm_trajectory_service = SimpleNamespace(
        get_processing_status_payload=lambda: {"status": {"processed_drones": [], "follow_map": {}}},
        validate_target_scope_for_swarm_trajectory=lambda **kwargs: [],
    )
    deps.log_system_event = lambda *args, **kwargs: None
    deps.log_system_warning = lambda *args, **kwargs: None
    deps.log_system_error = lambda *args, **kwargs: None
    return deps


def test_command_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/commands" in routes
    assert "/api/v1/commands/policy/precision-move" in routes
    assert "/api/v1/commands/{command_id}" in routes
    assert "/api/v1/commands/recent" in routes
    assert "/api/v1/commands/active" in routes
    assert "/api/v1/commands/statistics" in routes
    assert "/api/v1/command-reports/execution-result" in routes
    assert "/api/v1/command-reports/execution-start" in routes
    assert "/submit_command" not in routes
    assert "/command/{command_id}" not in routes
    assert "/commands/recent" not in routes
    assert "/commands/active" not in routes
    assert "/commands/statistics" not in routes
    assert "/command/{command_id}/cancel" not in routes
    assert "/command/execution-result" not in routes
    assert "/command/execution-start" not in routes


def test_command_router_statistics_uses_live_tracker_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    deps.current_tracker = _DummyTracker(
        statistics={
            "total_commands": 7,
            "successful_commands": 5,
            "failed_commands": 1,
            "partial_commands": 1,
            "timeout_commands": 0,
            "cancelled_commands": 0,
            "active_commands": 2,
            "tracked_commands": 7,
            "success_rate": 71.4,
        }
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/commands/statistics")

    assert response.status_code == 200
    assert response.json()["total_commands"] == 7
    assert response.json()["active_commands"] == 2


def test_command_router_precision_move_policy_uses_runtime_params():
    deps = _make_deps()
    deps.Params = SimpleNamespace(
        PRECISION_MOVE_DEFAULT_SPEED_MPS=1.25,
        PRECISION_MOVE_DEFAULT_POSITION_TOLERANCE_M=0.2,
        PRECISION_MOVE_DEFAULT_YAW_TOLERANCE_DEG=6.0,
        PRECISION_MOVE_DEFAULT_SETTLE_TIME_SEC=1.5,
        PRECISION_MOVE_DEFAULT_TIMEOUT_SEC=40.0,
        PRECISION_MOVE_MAX_TRANSLATION_M=120.0,
        PRECISION_MOVE_MAX_SPEED_MPS=6.0,
        PRECISION_MOVE_MIN_POSITION_TOLERANCE_M=0.08,
        PRECISION_MOVE_MAX_TIMEOUT_SEC=200.0,
        PRECISION_MOVE_MIN_AIRBORNE_ALTITUDE_M=0.4,
        PRECISION_MOVE_CONTROL_RATE_HZ=12.0,
        GCS_TELEMETRY_REQUEST_TIMEOUT_SEC=1.0,
        drone_api_port=5001,
        get_drone_home_URI="get-home-pos",
    )
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/v1/commands/policy/precision-move")

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "precision_move"
    assert body["defaults"]["speed_m_s"] == 1.25
    assert body["defaults"]["position_tolerance_m"] == 0.2
    assert body["limits"]["max_translation_m"] == 120.0
    assert body["execution"]["immediate_only"] is True
    assert body["execution"]["supported_frames"] == ["body", "ned"]


def test_command_router_submit_rejects_malformed_json():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            data="{bad",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "json_invalid"


def test_command_router_submit_rejects_non_object_json():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/commands", json=["not", "an", "object"])

    assert response.status_code == 422


def test_command_router_submit_rejects_invalid_target_drones_shape():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={"mission_type": 10, "trigger_time": 0, "target_drone_ids": "1"},
        )

    assert response.status_code == 422
    assert "target_drone_ids must be an array of drone identifiers" in response.text


def test_command_router_submit_accepts_snake_case_aliases():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={"mission_type": "TAKE_OFF", "trigger_time": 0, "target_drone_ids": ["1"]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mission_type"] == 10
    assert body["target_drones"] == ["1"]


def test_command_router_submit_rejects_unmatched_target_drones():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={"missionType": 10, "triggerTime": 0, "target_drones": ["99"]},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "No configured drones matched target_drone_ids"


def test_command_router_submit_replays_existing_idempotent_command_without_redispatch():
    replay_command = {
        "command_id": "cmd-existing",
        "idempotency_key": "retry-123",
        "mission_type": 10,
        "mission_name": "TAKE_OFF",
        "target_drones": ["1"],
        "status": "executing",
        "phase": "pending_execution",
        "outcome": None,
        "created_at": 1000,
        "submitted_at": 1001,
        "execution_started_at": None,
        "completed_at": None,
        "timeout_at": 5000,
        "updated_at": 1002,
        "acks": {
            "expected": 1,
            "received": 0,
            "accepted": 0,
            "offline": 0,
            "rejected": 0,
            "errors": 0,
            "result_summary": "pending",
            "details": {},
        },
        "executions": {
            "expected": 0,
            "started": 0,
            "active": 0,
            "received": 0,
            "succeeded": 0,
            "failed": 0,
            "details": {},
        },
        "late_reports": {
            "acks": {"received": 0, "accepted": 0, "offline": 0, "rejected": 0, "errors": 0, "details": {}},
            "execution_starts": {"received": 0, "details": {}},
            "executions": {"received": 0, "succeeded": 0, "failed": 0, "details": {}},
        },
        "progress": {
            "stage": "pending_execution",
            "label": "Accepted, waiting for execution start",
            "message": "Waiting for execution start reports from 1 drone(s).",
            "ack_pending": 1,
            "accepted": 0,
            "execution_pending": 1,
            "active": 0,
            "completed": 0,
            "remaining": 0,
            "scheduled_trigger_time": None,
        },
        "error_summary": None,
    }
    deps = _make_deps()
    deps.current_tracker = _DummyTracker(replay_command=replay_command)
    deps.send_commands_to_all = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dispatch should not run"))
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={
                "mission_type": 10,
                "trigger_time": 0,
                "idempotency_key": "retry-123",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["command_id"] == "cmd-existing"
    assert body["idempotency_key"] == "retry-123"
    assert body["replayed"] is True
    assert body["status"] == "submitted"


def test_command_router_submit_rejects_conflicting_idempotency_key_reuse():
    deps = _make_deps()
    deps.current_tracker = _DummyTracker(replay_conflict=True)
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={
                "mission_type": 10,
                "trigger_time": 0,
                "idempotency_key": "retry-123",
            },
        )

    assert response.status_code == 409
    assert "idempotency_key" in response.json()["detail"]


def test_estimate_max_target_relative_altitude_uses_home_altitude_field(monkeypatch):
    deps = _make_deps()
    deps.telemetry_data_all_drones = {
        "1": {
            "position_alt": 512.0,
        }
    }

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"altitude": 500.0}

    def _fake_get(url, timeout):
        del url, timeout
        return _Response()

    monkeypatch.setattr("requests.get", _fake_get)

    value = _estimate_max_target_relative_altitude_m(
        deps,
        [{"hw_id": 1, "ip": "127.0.0.1"}],
        ["1"],
    )

    assert value == 12.0
