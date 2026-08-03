from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api_routes.commands import create_command_router
from command_submission import (
    _ensure_sitl_callback_endpoint_matches,
    estimate_max_target_relative_altitude_m,
)
from command_execution_policy import (
    mission_requires_launch_armability_probe,
    resolve_mission_type,
)
from command_submission_pipeline import SITLCallbackEndpointMismatchError
from command_tracker import CommandIdempotencyConflictError, CommandCreationResult
from src.enums import Mission
from tests.helpers.command_submission import DeferredSubmissionCoordinator
from tests.helpers.fake_fleet_rpc import FakeFleetRPC


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
        self.created_commands = {}

    async def get_statistics(self):
        return self.statistics

    async def get_status(self, command_id):
        if self.replay_command and self.replay_command.get("command_id") == command_id:
            return self.replay_command
        return self.created_commands.get(command_id)

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
        self.created_commands["cmd-1"] = {
            "command_id": "cmd-1",
            "idempotency_key": kwargs.get("idempotency_key"),
            "mission_type": kwargs["mission_type"],
            "mission_name": f"MISSION_{kwargs['mission_type']}",
            "target_drones": list(kwargs["target_drones"]),
            "status": "created",
            "phase": "preparing",
            "outcome": None,
            "acks": {
                "expected": len(kwargs["target_drones"]),
                "received": 0,
                "accepted": 0,
                "offline": 0,
                "rejected": 0,
                "errors": 0,
                "details": {},
            },
        }
        return CommandCreationResult(command_id="cmd-1", replayed=False)

    async def create_command(self, **kwargs):
        del kwargs
        return "cmd-1"

    async def mark_submitted(self, command_id):
        del command_id
        return True

    async def get_callback_capabilities(self, command_id):
        del command_id
        return {"1": "c" * 43}

    async def record_ack(self, *args, **kwargs):
        del args, kwargs
        return None

    async def record_execution(self, **kwargs):
        del kwargs
        return True

    async def record_execution_start(self, **kwargs):
        del kwargs
        return True

    async def fail_command_before_dispatch(self, command_id, reason):
        del command_id, reason
        return True


def _make_deps():
    deps = SimpleNamespace()
    deps.current_tracker = _DummyTracker()
    deps.get_command_tracker = lambda: deps.current_tracker
    deps.command_submission_coordinator = DeferredSubmissionCoordinator()
    deps.get_command_submission_coordinator = lambda: deps.command_submission_coordinator
    deps.fleet_rpc = FakeFleetRPC()
    deps.get_fleet_rpc_service = lambda: deps.fleet_rpc
    deps.Mission = Mission
    deps.Params = SimpleNamespace(
        sim_mode=False,
        GCS_TELEMETRY_REQUEST_TIMEOUT_SEC=1.0,
        drone_api_port=5001,
        get_drone_home_URI="get-home-pos",
    )
    deps.telemetry_lock = nullcontext()
    deps.telemetry_data_all_drones = {}
    deps.resolve_mission_type = resolve_mission_type
    deps.mission_requires_launch_armability_probe = mission_requires_launch_armability_probe
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


def test_sitl_command_guard_rejects_callback_endpoint_split():
    deps = _make_deps()
    deps.Params.sim_mode = True
    deps.Params.GCS_IP = "172.18.0.1"
    deps.Params.gcs_api_port = 5030
    deps.sitl_control_service = SimpleNamespace(
        callback_endpoint_mismatches=lambda targets: [{
            "name": "drone-1",
            "hw_id": "1",
            "observed_ip": "172.18.0.1",
            "observed_port": 5111,
            "expected_ip": "172.18.0.1",
            "expected_port": 5030,
        }]
    )
    warnings = []
    deps.log_system_warning = lambda *args: warnings.append(args)

    with pytest.raises(SITLCallbackEndpointMismatchError) as raised:
        _ensure_sitl_callback_endpoint_matches(deps, ["1"])

    assert "callbacks are routed to a different GCS process" in str(raised.value)
    assert warnings


def test_sitl_command_guard_is_disabled_for_real_mode():
    deps = _make_deps()
    deps.Params.sim_mode = False
    deps.sitl_control_service = SimpleNamespace(
        callback_endpoint_mismatches=lambda _targets: (_ for _ in ()).throw(
            AssertionError("guard should not inspect Docker in real mode")
        )
    )

    _ensure_sitl_callback_endpoint_matches(deps, ["1"])


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
    assert "target_drone_ids must be a JSON array of hardware ID strings" in response.text


@pytest.mark.parametrize(
    "payload,error_text",
    [
        (
            {"mission_type": 10, "trigger_time": 0},
            "Command target is required; use target_scope='all' for the whole fleet",
        ),
        (
            {"mission_type": 10, "trigger_time": 0, "target_drone_ids": []},
            "target_drone_ids must contain at least one hardware ID",
        ),
        (
            {
                "mission_type": 10,
                "trigger_time": 0,
                "target_drone_ids": ["1"],
                "target_scope": "all",
            },
            "Use target_drone_ids or target_scope, not both",
        ),
    ],
)
def test_command_router_submit_requires_one_unambiguous_target_selection(payload, error_text):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/commands", json=payload)

    assert response.status_code == 422
    assert error_text in response.text


def test_command_router_submit_accepts_snake_case_aliases():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={"mission_type": "TAKE_OFF", "trigger_time": 0, "target_drone_ids": ["1"]},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["accepted_for_tracking"] is True
    assert body["mission_type"] == 10
    assert body["target_drones"] == ["1"]


def test_command_router_ground_test_requires_safety_acknowledgement():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={"mission_type": 100, "trigger_time": 0, "target_drone_ids": ["1"]},
        )

    assert response.status_code == 422
    assert "ground_test_safety acknowledgement is required" in response.text


def test_command_router_real_mode_rejects_sitl_ground_test_exemption_before_tracking():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={
                "mission_type": 100,
                "trigger_time": 0,
                "target_drone_ids": ["1"],
                "ground_test_safety": {"mode": "sitl_not_applicable"},
            },
        )

    assert response.status_code == 409
    assert "Real-aircraft Arm/Disarm Ground Test" in response.json()["detail"]
    assert deps.current_tracker.create_calls == []


def test_command_router_sitl_mode_requires_explicit_sitl_ground_test_exemption():
    deps = _make_deps()
    deps.Params.sim_mode = True
    # This test exercises the acknowledgement boundary, not Docker callback
    # endpoint discovery.
    deps.sitl_control_service = SimpleNamespace(callback_endpoint_mismatches=lambda _targets: [])
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        wrong_mode = client.post(
            "/api/v1/commands",
            json={
                "mission_type": 100,
                "trigger_time": 0,
                "target_drone_ids": ["1"],
                "ground_test_safety": {
                    "mode": "operator_acknowledged",
                    "props_removed": True,
                    "airframe_secured": True,
                    "area_clear": True,
                },
            },
        )
        accepted = client.post(
            "/api/v1/commands",
            json={
                "mission_type": 100,
                "trigger_time": 0,
                "target_drone_ids": ["1"],
                "ground_test_safety": {"mode": "sitl_not_applicable"},
            },
        )

    assert wrong_mode.status_code == 409
    assert "SITL Arm/Disarm Ground Test" in wrong_mode.json()["detail"]
    assert accepted.status_code == 202
    assert deps.current_tracker.create_calls[0]["params"]["ground_test_safety"] == {
        "mode": "sitl_not_applicable",
    }


def test_command_router_submit_rejects_legacy_envelope_fields():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={"missionType": 10, "triggerTime": 0, "target_drones": ["99"]},
        )

    assert response.status_code == 422
    assert "Unsupported command-submit field(s)" in response.text
    assert "canonical snake_case contract" in response.text


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
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/commands",
            json={
                "mission_type": 10,
                "trigger_time": 0,
                "target_scope": "all",
                "idempotency_key": "retry-123",
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["accepted_for_tracking"] is True
    assert body["command_id"] == "cmd-existing"
    assert body["idempotency_key"] == "retry-123"
    assert body["replayed"] is True
    assert body["tracking_url"] == "/api/v1/commands/cmd-existing"
    assert "status" not in body
    assert deps.fleet_rpc.dispatch_calls == []


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
                "target_scope": "all",
                "idempotency_key": "retry-123",
            },
        )

    assert response.status_code == 409
    assert "idempotency_key" in response.json()["detail"]


def test_execution_callback_routes_require_exact_command_target_capability():
    import asyncio

    from command_tracker import CommandTracker
    from src.gcs_api_routes import GCS_COMMAND_REPORT_CAPABILITY_HEADER

    tracker = CommandTracker(max_commands=10)
    command_id = asyncio.run(
        tracker.create_command(mission_type=10, target_drones=["1"])
    )
    capability = asyncio.run(tracker.get_callback_capabilities(command_id))["1"]
    deps = _make_deps()
    deps.current_tracker = tracker
    app = FastAPI()
    app.include_router(create_command_router(deps))
    start_payload = {"command_id": command_id, "hw_id": "1"}

    with TestClient(app) as client:
        missing = client.post(
            "/api/v1/command-reports/execution-start",
            json=start_payload,
        )
        wrong = client.post(
            "/api/v1/command-reports/execution-start",
            json=start_payload,
            headers={GCS_COMMAND_REPORT_CAPABILITY_HEADER: "x" * 43},
        )
        spoofed_hw = client.post(
            "/api/v1/command-reports/execution-start",
            json={"command_id": command_id, "hw_id": "2"},
            headers={GCS_COMMAND_REPORT_CAPABILITY_HEADER: capability},
        )
        accepted_start = client.post(
            "/api/v1/command-reports/execution-start",
            json=start_payload,
            headers={GCS_COMMAND_REPORT_CAPABILITY_HEADER: capability},
        )
        result_payload = {
            "command_id": command_id,
            "hw_id": "1",
            "success": True,
            "duration_ms": 25,
        }
        accepted_result = client.post(
            "/api/v1/command-reports/execution-result",
            json=result_payload,
            headers={GCS_COMMAND_REPORT_CAPABILITY_HEADER: capability},
        )
        replayed_result = client.post(
            "/api/v1/command-reports/execution-result",
            json=result_payload,
            headers={GCS_COMMAND_REPORT_CAPABILITY_HEADER: capability},
        )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert spoofed_hw.status_code == 403
    assert missing.json()["detail"] == wrong.json()["detail"] == spoofed_hw.json()["detail"] == (
        "Command callback authentication failed"
    )
    assert accepted_start.status_code == 200
    assert accepted_result.status_code == 200
    assert replayed_result.status_code == 200
    status = asyncio.run(tracker.get_status(command_id))
    assert status["outcome"] == "completed"
    assert status["executions"]["received"] == 1


def test_terminal_command_keeps_authenticated_late_execution_as_evidence_only():
    import asyncio

    from command_tracker import CommandTracker
    from src.gcs_api_routes import GCS_COMMAND_REPORT_CAPABILITY_HEADER

    tracker = CommandTracker(max_commands=10)
    command_id = asyncio.run(
        tracker.create_command(mission_type=10, target_drones=["1"])
    )
    capability = asyncio.run(tracker.get_callback_capabilities(command_id))["1"]
    asyncio.run(
        tracker.record_ack(
            command_id,
            "1",
            category="rejected",
            error_code="E202",
        )
    )
    deps = _make_deps()
    deps.current_tracker = tracker
    app = FastAPI()
    app.include_router(create_command_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/command-reports/execution-result",
            json={
                "command_id": command_id,
                "hw_id": "1",
                "success": True,
                "duration_ms": 25,
            },
            headers={GCS_COMMAND_REPORT_CAPABILITY_HEADER: capability},
        )

    assert response.status_code == 200
    status = asyncio.run(tracker.get_status(command_id))
    assert status["phase"] == "terminal"
    assert status["outcome"] == "failed"
    assert status["acks"]["accepted"] == 0
    assert status["executions"]["received"] == 0
    assert status["late_reports"]["executions"]["received"] == 1


def test_estimate_max_target_relative_altitude_uses_cached_relative_altitude_without_rpc(monkeypatch):
    deps = _make_deps()
    deps.telemetry_data_all_drones = {
        "1": {
            "position_alt": 512.0,
            "relative_altitude_m": 12.0,
        }
    }

    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("timeout sizing must not issue a per-node HTTP request")
        ),
    )

    value = estimate_max_target_relative_altitude_m(
        deps,
        [{"hw_id": 1, "ip": "127.0.0.1"}],
        ["1"],
    )

    assert value == 12.0
