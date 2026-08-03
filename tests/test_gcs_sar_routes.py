from threading import Lock
from types import SimpleNamespace
import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from command_execution_policy import (
    mission_requires_launch_armability_probe,
    resolve_mission_type,
)
from command_tracker import CommandTracker
from src.enums import Mission
from schemas import CommandSubmissionReceipt
from sar.coverage_planner import SHAPELY_AVAILABLE
from sar.routes import create_sar_router
from tests.helpers.command_submission import InlineSubmissionCoordinator
from tests.helpers.fake_fleet_rpc import FakeFleetRPC


pytestmark = pytest.mark.skipif(not SHAPELY_AVAILABLE, reason="shapely not installed")


@pytest.fixture(autouse=True)
def reset_quickscout_state(tmp_path, monkeypatch):
    monkeypatch.setenv("MDS_QUICKSCOUT_DB_PATH", str(tmp_path / "quickscout.sqlite3"))
    import sar.service as svc
    import sar.store as store

    svc._service_instance = None
    store._store_instance = None
    yield
    svc._service_instance = None
    store._store_instance = None


def _make_deps(drone_count=1):
    tracker = CommandTracker(max_commands=20)
    coordinator = InlineSubmissionCoordinator()
    fleet_rpc = FakeFleetRPC()
    telemetry = {
        str(index + 1): {
            "pos_id": index,
            "hw_id": str(index + 1),
            "position_lat": 47.0 + index * 0.001,
            "position_long": 8.0 + index * 0.001,
            "gps_fix_type": 3,
            "global_position_valid": True,
            "global_position_timestamp_ms": int(time.time() * 1000),
            "timestamp": time.time(),
            "telemetry_available": True,
        }
        for index in range(drone_count)
    }
    config = [
        {"pos_id": index, "hw_id": str(index + 1), "ip": f"10.0.0.{index + 1}"}
        for index in range(drone_count)
    ]
    return SimpleNamespace(
        telemetry_data_all_drones=telemetry,
        telemetry_lock=Lock(),
        current_tracker=tracker,
        get_command_tracker=lambda: tracker,
        get_command_submission_coordinator=lambda: coordinator,
        get_fleet_rpc_service=lambda: fleet_rpc,
        fleet_rpc=fleet_rpc,
        Mission=Mission,
        load_config=lambda: config,
        get_expected_position_from_trajectory=lambda _pos_id, _sim_mode: (0.0, 0.0),
        build_desired_launch_positions_report=lambda drones, origin_lat, origin_lon, origin_alt=0.0, heading_deg=0.0, sim_mode=False, trajectory_resolver=None: {
            "origin": {"lat": origin_lat, "lon": origin_lon, "alt": origin_alt},
            "positions": [
                {
                    "pos_id": drone["pos_id"],
                    "hw_id": drone["hw_id"],
                    "latitude": origin_lat,
                    "longitude": origin_lon,
                    "altitude": origin_alt,
                    "north": 0.0,
                    "east": 0.0,
                    "trajectory_north": 0.0,
                    "trajectory_east": 0.0,
                }
                for drone in drones
            ],
            "total_drones": len(drones),
            "heading": heading_deg,
        },
        resolve_mission_type=resolve_mission_type,
        mission_requires_launch_armability_probe=mission_requires_launch_armability_probe,
        load_origin=lambda: None,
        skybrush_dir="/tmp/skybrush",
        processed_dir="/tmp/processed",
        shapes_dir="/tmp/shapes",
        get_swarm_trajectory_folders=lambda: {"processed": "/tmp/processed"},
        estimate_command_tracking_timeout_ms=lambda *args, **kwargs: 1000,
        swarm_trajectory_service=SimpleNamespace(
            get_processing_status_payload=lambda: {"status": {"processed_drones": [], "follow_map": {}}},
            validate_target_scope_for_swarm_trajectory=lambda **_kwargs: [],
        ),
        log_system_event=lambda *args, **kwargs: None,
        log_system_warning=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
        Params=SimpleNamespace(
            sim_mode=False,
            GCS_COMMAND_PREPARATION_PROVISIONAL_TIMEOUT_MS=300_000,
            GCS_TELEMETRY_REQUEST_TIMEOUT_SEC=1.0,
            drone_api_port=5001,
        ),
    )


def _plan_request(pos_ids=None):
    return {
        "search_area": {
            "type": "polygon",
            "points": [
                {"lat": 47.0, "lng": 8.0},
                {"lat": 47.002, "lng": 8.0},
                {"lat": 47.002, "lng": 8.002},
                {"lat": 47.0, "lng": 8.002},
            ],
        },
        "survey_config": {
            "sweep_width_m": 30,
            "overlap_percent": 10,
            "cruise_altitude_msl": 50,
            "survey_altitude_agl": 40,
            "cruise_speed_ms": 10,
            "survey_speed_ms": 5,
            "use_terrain_following": False,
        },
        "pos_ids": [0] if pos_ids is None else pos_ids,
    }


def _record_execution_start(tracker, command_id, hw_id):
    capabilities = asyncio.run(tracker.get_callback_capabilities(command_id))
    asyncio.run(
        tracker.record_execution_start(
            command_id,
            hw_id,
            callback_capability=capabilities[hw_id],
        )
    )


def _record_execution_result(tracker, command_id, hw_id, *, success=True):
    capabilities = asyncio.run(tracker.get_callback_capabilities(command_id))
    asyncio.run(
        tracker.record_execution(
            command_id,
            hw_id,
            success=success,
            error_message=None if success else "runtime failure",
            callback_capability=capabilities[hw_id],
        )
    )


def _launch_with_execution_start(client, deps, mission_id, hw_id="1"):
    launched = client.post("/api/sar/mission/launch", params={"mission_id": mission_id})
    assert launched.status_code == 202
    command_id = launched.json()["latest_command_batch"]["receipt"]["command_id"]
    _record_execution_start(deps.current_tracker, command_id, hw_id)
    status = client.get(f"/api/sar/mission/{mission_id}/status")
    assert status.status_code == 200
    assert status.json()["drone_states"][hw_id]["state"] == "executing"
    return command_id


def test_sar_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/sar/mission/plan" in routes
    assert "/api/sar/mission/plan/jobs" in routes
    assert "/api/sar/mission/plan/jobs/{job_id}" in routes
    assert "/api/sar/mission/plan/jobs/{job_id}/cancel" in routes
    assert "/api/sar/missions" in routes
    assert "/api/sar/mission/launch" in routes
    assert "/api/sar/mission/{mission_id}/revalidate-launch" in routes
    assert "/api/sar/mission/{mission_id}/workspace" in routes
    assert "/api/sar/mission/{mission_id}/status" in routes
    assert "/api/sar/mission/{mission_id}/handoff" in routes
    assert "/api/sar/mission/{mission_id}/pause" in routes
    assert "/api/sar/mission/{mission_id}/resume" not in routes
    assert "/api/sar/mission/{mission_id}/abort" in routes
    assert "/api/sar/mission/{mission_id}/progress" in routes
    assert "/api/sar/findings" in routes
    assert "/api/sar/findings/{finding_id}" in routes
    assert "/api/sar/elevation/batch" in routes


def test_sar_router_uses_live_dependency_attributes_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    deps.load_config = lambda: [{"pos_id": 0, "hw_id": "7", "ip": "10.0.0.7"}]
    deps.telemetry_data_all_drones = {
        "7": {
            "pos_id": 0,
            "hw_id": "7",
            "position_lat": 47.0,
            "position_long": 8.0,
            "gps_fix_type": 3,
            "global_position_valid": True,
            "global_position_timestamp_ms": int(time.time() * 1000),
            "timestamp": time.time(),
            "telemetry_available": True,
        }
    }

    with TestClient(app) as client:
        response = client.post("/api/sar/mission/plan", json=_plan_request())

    assert response.status_code == 200
    plans = response.json()["plans"]
    assert plans
    assert plans[0]["hw_id"] == "7"


def test_sar_launch_queues_one_tracked_batch_with_exact_per_target_payloads(monkeypatch):
    deps = _make_deps(drone_count=2)
    submissions = []

    async def fake_submit(_deps, request, **kwargs):
        submissions.append((request, kwargs))
        return CommandSubmissionReceipt(
            command_id="quickscout-command-1",
            idempotency_key=request.idempotency_key,
            replayed=False,
            mission_type=Mission.QUICKSCOUT.value,
            mission_name=Mission.QUICKSCOUT.name,
            target_drones=list(request.target_drone_ids),
            tracking_url="/api/v1/commands/quickscout-command-1",
            message="Tracked command queued.",
            timestamp=1_700_000_000_000,
        )

    monkeypatch.setattr("sar.service.submit_tracked_command", fake_submit)
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request([0, 1]))
        mission_id = planned.json()["mission_id"]
        response = client.post("/api/sar/mission/launch", params={"mission_id": mission_id})
        unavailable_status = client.get(f"/api/sar/mission/{mission_id}/status")

    assert response.status_code == 202
    payload = response.json()
    assert len(submissions) == 1
    request, kwargs = submissions[0]
    assert request.trigger_time == 0
    assert request.waypoints is None
    assert request.target_drone_ids == ["1", "2"]
    assert request.idempotency_key == f"quickscout:{mission_id}:launch:1"
    assert list(kwargs["per_target_payloads"]) == ["1", "2"]
    assert all(set(fragment) == {"waypoints"} for fragment in kwargs["per_target_payloads"].values())
    assert all(fragment["waypoints"] for fragment in kwargs["per_target_payloads"].values())
    assert "schedule_after_preparation" not in kwargs
    batch = payload["latest_command_batch"]
    assert batch["action"] == "launch"
    assert batch["attempt"] == 1
    assert batch["state"] == "queued"
    assert list(batch["targets"]) == ["1", "2"]
    assert all(target["state"] == "queued" for target in batch["targets"].values())
    assert batch["receipt"]["command_id"] == "quickscout-command-1"
    assert "tracking_timeout_ms" not in batch["receipt"]
    assert "success" not in payload
    assert "submissions" not in payload
    assert unavailable_status.json()["state"] == "ready"
    assert unavailable_status.json()["latest_command_batch"]["state"] == "tracking_unavailable"


def test_sar_launch_ack_does_not_mutate_mission_state():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        launched = client.post("/api/sar/mission/launch", params={"mission_id": mission_id})
        status = client.get(f"/api/sar/mission/{mission_id}/status")

    assert launched.status_code == 202
    assert status.status_code == 200
    payload = status.json()
    assert payload["state"] == "ready"
    assert payload["drone_states"]["1"]["state"] == "ready"
    assert payload["operation_phase"] == "launch_queued"
    assert payload["latest_command_batch"]["state"] == "accepted"
    assert payload["latest_command_batch"]["trigger_time"] > 0


def test_sar_status_reconciles_partial_launch_only_from_execution_evidence():
    deps = _make_deps(drone_count=2)
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request([0, 1]))
        mission_id = planned.json()["mission_id"]
        launched = client.post("/api/sar/mission/launch", params={"mission_id": mission_id})
        command_id = launched.json()["latest_command_batch"]["receipt"]["command_id"]
        _record_execution_start(deps.current_tracker, command_id, "1")
        status = client.get(f"/api/sar/mission/{mission_id}/status")

    payload = status.json()
    assert payload["state"] == "executing"
    assert payload["operation_phase"] == "launch_partial"
    assert payload["drone_states"]["1"]["state"] == "executing"
    assert payload["drone_states"]["2"]["state"] == "ready"
    assert payload["latest_command_batch"]["targets"]["1"]["state"] == "executing"
    assert payload["latest_command_batch"]["targets"]["2"]["state"] == "accepted"


def test_sar_pause_changes_state_only_after_successful_execution_result():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        _launch_with_execution_start(client, deps, mission_id)
        paused = client.post(f"/api/sar/mission/{mission_id}/pause")
        command_id = paused.json()["latest_command_batch"]["receipt"]["command_id"]
        ack_status = client.get(f"/api/sar/mission/{mission_id}/status").json()
        _record_execution_result(deps.current_tracker, command_id, "1", success=True)
        executed_status = client.get(f"/api/sar/mission/{mission_id}/status").json()

    assert paused.status_code == 202
    assert ack_status["state"] == "executing"
    assert ack_status["latest_command_batch"]["state"] == "accepted"
    assert executed_status["state"] == "paused"
    assert executed_status["operation_phase"] == "holding"
    assert executed_status["latest_command_batch"]["state"] == "completed"


def test_sar_partial_launch_pause_targets_only_tracker_confirmed_active_assignments():
    deps = _make_deps(drone_count=2)
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request([0, 1]))
        mission_id = planned.json()["mission_id"]
        _launch_with_execution_start(client, deps, mission_id, hw_id="1")
        paused = client.post(f"/api/sar/mission/{mission_id}/pause")

    assert paused.status_code == 202
    assert paused.json()["latest_command_batch"]["receipt"]["target_drones"] == ["1"]


def test_sar_pause_rejects_assignment_without_launch_execution_evidence():
    deps = _make_deps(drone_count=2)
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request([0, 1]))
        mission_id = planned.json()["mission_id"]
        _launch_with_execution_start(client, deps, mission_id, hw_id="1")
        paused = client.post(
            f"/api/sar/mission/{mission_id}/pause",
            params={"pos_ids": [1]},
        )

    assert paused.status_code == 409
    assert paused.json()["detail"]["code"] == "quickscout_control_targets_not_actionable"
    assert paused.json()["detail"]["details"]["ineligible_hw_ids"] == ["2"]


def test_sar_abort_applies_return_behavior_only_after_successful_execution_result():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        _launch_with_execution_start(client, deps, mission_id)
        aborted = client.post(
            f"/api/sar/mission/{mission_id}/abort",
            params={"return_behavior": "hold_position"},
        )
        command_id = aborted.json()["latest_command_batch"]["receipt"]["command_id"]
        before_execution = client.get(f"/api/sar/mission/{mission_id}/workspace").json()
        _record_execution_result(deps.current_tracker, command_id, "1", success=True)
        after_execution = client.get(f"/api/sar/mission/{mission_id}/workspace").json()

    assert aborted.status_code == 202
    assert before_execution["operation"]["state"] == "executing"
    assert before_execution["operation"]["return_behavior"] == "return_home"
    assert after_execution["operation"]["state"] == "aborted"
    assert after_execution["operation"]["return_behavior"] == "hold_position"
    assert after_execution["status"]["operation_phase"] == "return_commanded"


def test_sar_configured_origin_plan_is_staged_without_live_telemetry():
    deps = _make_deps()
    deps.telemetry_data_all_drones = {}
    deps.load_origin = lambda: {
        "lat": 47.0,
        "lon": 8.0,
        "alt": 500.0,
        "alt_source": "manual",
        "timestamp": "2026-05-16T00:00:00",
    }
    request = {
        **_plan_request(),
        "position_source_mode": "configured_origin",
    }
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/sar/mission/plan", json=request)

    assert response.status_code == 200
    payload = response.json()
    assert payload["position_source_mode"] == "configured_origin"
    assert payload["launchable"] is False
    assert payload["requires_revalidation"] is True
    assert payload["planning_origin"]["lat"] == 47.0
    assert payload["position_sources"][0]["source"] == "configured_origin_slot"
    assert payload["position_sources"][0]["approximate"] is True


def test_sar_configured_origin_launch_requires_revalidation_token():
    deps = _make_deps()
    deps.load_origin = lambda: {
        "lat": 47.0,
        "lon": 8.0,
        "alt": 500.0,
        "alt_source": "manual",
        "timestamp": "2026-05-16T00:00:00",
    }
    request = {
        **_plan_request(),
        "position_source_mode": "configured_origin",
    }
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=request)
        mission_id = planned.json()["mission_id"]
        response = client.post("/api/sar/mission/launch", params={"mission_id": mission_id})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "quickscout_launch_revalidation_required"


def test_sar_configured_origin_revalidate_issues_launch_token():
    deps = _make_deps()
    deps.load_origin = lambda: {
        "lat": 47.0,
        "lon": 8.0,
        "alt": 500.0,
        "alt_source": "manual",
        "timestamp": "2026-05-16T00:00:00",
    }
    request = {
        **_plan_request(),
        "position_source_mode": "configured_origin",
    }
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=request)
        mission_id = planned.json()["mission_id"]
        revalidated = client.post(f"/api/sar/mission/{mission_id}/revalidate-launch")
        token = revalidated.json()["token"]
        launched = client.post(
            "/api/sar/mission/launch",
            params={"mission_id": mission_id},
            json={"revalidation_token": token},
        )

    assert revalidated.status_code == 200
    assert revalidated.json()["launchable"] is True
    assert revalidated.json()["slot_errors_m"]["0"] == pytest.approx(0.0)
    assert launched.status_code == 202
    assert launched.json()["latest_command_batch"]["action"] == "launch"
    assert launched.json()["latest_command_batch"]["state"] == "queued"


def test_sar_lists_persisted_missions_for_recovery():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        response = client.get("/api/sar/missions", params={"limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["missions"][0]["mission_id"] == mission_id
    assert payload["missions"][0]["drone_count"] == 1


def test_sar_workspace_returns_persisted_operation_and_status():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        response = client.get(f"/api/sar/mission/{mission_id}/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"]["mission_id"] == mission_id
    assert payload["status"]["mission_id"] == mission_id
    assert payload["operation"]["plans"]
    assert payload["status"]["operation_phase"] == "ready_to_launch"


def test_sar_handoff_returns_compact_operator_bundle():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        finding = client.post(
            "/api/sar/findings",
            params={"mission_id": mission_id},
            json={
                "lat": 47.0,
                "lng": 8.0,
                "summary": "Thermal contact",
                "type": "person",
                "priority": "high",
                "evidence_refs": ["img://capture-1"],
            },
        )
        finding_id = finding.json()["id"]
        client.patch(
            f"/api/sar/findings/{finding_id}",
            json={"status": "confirmed", "notes": "Operator confirmed thermal plus visual"},
        )
        response = client.get(f"/api/sar/mission/{mission_id}/handoff")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mission_id"] == mission_id
    assert payload["finding_count"] == 1
    assert payload["confirmed_finding_count"] == 1
    assert payload["evidence_ref_count"] == 1
    assert payload["findings"][0]["summary"] == "Thermal contact"
    assert "Thermal contact" in payload["brief_text"]


def test_sar_abort_respects_hold_position_behavior():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        _launch_with_execution_start(client, deps, mission_id)
        response = client.post(
            f"/api/sar/mission/{mission_id}/abort",
            params={"return_behavior": "hold_position"},
        )
        status = client.get(f"/api/sar/mission/{mission_id}/status")

    assert response.status_code == 202
    payload = response.json()
    batch = payload["latest_command_batch"]
    assert batch["action"] == "abort"
    assert batch["return_behavior"] == "hold_position"
    assert batch["receipt"]["mission_type"] == Mission.HOLD.value
    assert status.json()["state"] == "executing"
    assert status.json()["latest_command_batch"]["state"] == "accepted"


def test_sar_abort_rejects_invalid_return_behavior():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        response = client.post(
            f"/api/sar/mission/{mission_id}/abort",
            params={"return_behavior": "manual_override"},
        )

    assert response.status_code == 422


def test_sar_abort_rejects_unknown_pos_id_instead_of_raw_target():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        _launch_with_execution_start(client, deps, mission_id)
        response = client.post(
            f"/api/sar/mission/{mission_id}/abort",
            params={"pos_ids": [99]},
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "quickscout_unknown_pos_ids"


def test_sar_progress_is_tracker_gated_and_never_changes_lifecycle_state():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        initial_status = client.get(f"/api/sar/mission/{mission_id}/status").json()
        total_waypoints = initial_status["drone_states"]["1"]["total_waypoints"]
        progress_payload = {
            "hw_id": "1",
            "current_waypoint_index": total_waypoints,
            "total_waypoints": total_waypoints,
            "distance_covered_m": 150.0,
        }

        before_execution = client.post(
            f"/api/sar/mission/{mission_id}/progress",
            json=progress_payload,
        )
        legacy_state = client.post(
            f"/api/sar/mission/{mission_id}/progress",
            json={**progress_payload, "state": "completed"},
        )

        _launch_with_execution_start(client, deps, mission_id)
        applied = client.post(
            f"/api/sar/mission/{mission_id}/progress",
            json=progress_payload,
        )
        stale = client.post(
            f"/api/sar/mission/{mission_id}/progress",
            json={**progress_payload, "current_waypoint_index": 0, "distance_covered_m": 0},
        )
        status = client.get(f"/api/sar/mission/{mission_id}/status").json()

    assert before_execution.status_code == 409
    assert before_execution.json()["detail"]["code"] == "quickscout_progress_before_execution"
    assert legacy_state.status_code == 422
    assert applied.status_code == 200
    assert applied.json() == {
        "mission_id": mission_id,
        "hw_id": "1",
        "applied": True,
        "message": "Progress metrics updated.",
    }
    assert stale.status_code == 200
    assert stale.json()["applied"] is False
    assert status["drone_states"]["1"]["coverage_percent"] == 100.0
    assert status["drone_states"]["1"]["state"] == "executing"
    assert status["state"] == "executing"


def test_sar_resume_endpoint_is_removed():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        response = client.post(f"/api/sar/mission/{mission_id}/resume")

    assert response.status_code == 404


def test_sar_plan_accepts_last_known_point_template():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    request = {
        "mission_template": "last_known_point",
        "search_area": {
            "type": "point",
            "center": {"lat": 47.0, "lng": 8.0},
            "radius_m": 120,
        },
        "survey_config": {
            "sweep_width_m": 30,
            "overlap_percent": 10,
            "cruise_altitude_msl": 50,
            "survey_altitude_agl": 40,
            "cruise_speed_ms": 10,
            "survey_speed_ms": 5,
            "use_terrain_following": False,
        },
        "pos_ids": [0],
    }

    with TestClient(app) as client:
        response = client.post("/api/sar/mission/plan", json=request)

    assert response.status_code == 200
    assert response.json()["plans"]


def test_sar_plan_accepts_corridor_search_template_area_summary():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    request = {
        "mission_template": "corridor_search",
        "search_area": {
            "type": "line",
            "path": [
                {"lat": 47.0, "lng": 8.0},
                {"lat": 47.001, "lng": 8.001},
                {"lat": 47.003, "lng": 8.002},
            ],
            "corridor_width_m": 80,
        },
        "survey_config": {
            "sweep_width_m": 30,
            "overlap_percent": 10,
            "cruise_altitude_msl": 50,
            "survey_altitude_agl": 40,
            "cruise_speed_ms": 10,
            "survey_speed_ms": 5,
            "use_terrain_following": False,
        },
        "pos_ids": [0],
    }

    with TestClient(app) as client:
        response = client.post("/api/sar/mission/plan", json=request)

    assert response.status_code == 200
    assert response.json()["plans"]


def test_sar_plan_accepts_corridor_search_template_multi_vertex():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    request = {
        "mission_template": "corridor_search",
        "search_area": {
            "type": "line",
            "path": [
                {"lat": 47.0, "lng": 8.0},
                {"lat": 47.002, "lng": 8.002},
                {"lat": 47.004, "lng": 8.004},
            ],
            "corridor_width_m": 90,
        },
        "survey_config": {
            "sweep_width_m": 30,
            "overlap_percent": 10,
            "cruise_altitude_msl": 50,
            "survey_altitude_agl": 40,
            "cruise_speed_ms": 10,
            "survey_speed_ms": 5,
            "use_terrain_following": False,
        },
        "pos_ids": [0],
    }

    with TestClient(app) as client:
        response = client.post("/api/sar/mission/plan", json=request)

    assert response.status_code == 200
    assert response.json()["plans"]
