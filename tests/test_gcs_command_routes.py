from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.commands import create_command_router


class _DummyTracker:
    def __init__(self, *, statistics=None):
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

    async def get_statistics(self):
        return self.statistics

    async def get_status(self, command_id):
        del command_id
        return None

    async def get_recent(self, **kwargs):
        del kwargs
        return []

    async def get_active_commands(self):
        return []

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


def _make_deps():
    deps = SimpleNamespace()
    deps.current_tracker = _DummyTracker()
    deps.get_command_tracker = lambda: deps.current_tracker
    deps.Mission = SimpleNamespace(SWARM_TRAJECTORY="swarm", LAND="land", RETURN_RTL="rtl")
    deps.Params = SimpleNamespace(
        GCS_TELEMETRY_REQUEST_TIMEOUT_SEC=1.0,
        drone_api_port=5001,
        get_drone_home_URI="get-home-pos",
    )
    deps.telemetry_lock = nullcontext()
    deps.telemetry_data_all_drones = {}
    deps.resolve_mission_type = lambda mission_type: None
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
    assert "/api/v1/commands/{command_id}" in routes
    assert "/api/v1/commands/recent" in routes
    assert "/api/v1/commands/active" in routes
    assert "/api/v1/commands/statistics" in routes
    assert "/api/v1/commands/{command_id}/cancel" in routes
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

    assert response.status_code == 400
    assert response.json()["detail"] == "Malformed JSON request body"


def test_command_router_submit_rejects_non_object_json():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/commands", json=["not", "an", "object"])

    assert response.status_code == 400
    assert response.json()["detail"] == "Request body must be a JSON object"


def test_command_router_submit_rejects_invalid_target_drones_shape():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={"missionType": 10, "triggerTime": 0, "target_drones": "1"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "target_drones must be an array of drone identifiers"


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
    assert response.json()["detail"] == "No configured drones matched target_drones"


def test_command_router_cancel_endpoint_stays_fail_closed():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/commands/test-command-id/cancel")

    assert response.status_code == 409
    assert "missionType=0" in response.json()["detail"]
    assert "/api/v1/commands" in response.json()["detail"]
