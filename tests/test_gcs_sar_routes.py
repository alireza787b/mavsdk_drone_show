from threading import Lock
from types import SimpleNamespace
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from command_tracker import CommandTracker
from enums import Mission
from sar.coverage_planner import SHAPELY_AVAILABLE
from sar.routes import create_sar_router


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


def _make_deps():
    tracker = CommandTracker(max_commands=20)
    return SimpleNamespace(
        telemetry_data_all_drones={
            "1": {
                "pos_id": 0,
                "hw_id": "1",
                "position_lat": 47.0,
                "position_long": 8.0,
                "gps_fix_type": 3,
                "global_position_valid": True,
                "global_position_timestamp_ms": int(time.time() * 1000),
                "timestamp": time.time(),
                "telemetry_available": True,
            }
        },
        telemetry_lock=Lock(),
        current_tracker=tracker,
        get_command_tracker=lambda: tracker,
        Mission=Mission,
        load_config=lambda: [{"pos_id": 0, "hw_id": "1", "ip": "10.0.0.1"}],
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
        resolve_mission_type=lambda mission_type: (
            mission_type if isinstance(mission_type, Mission) else Mission(int(mission_type))
        ),
        mission_requires_launch_armability_probe=lambda _mission: False,
        probe_live_armability_for_drones=lambda *_args, **_kwargs: {
            "all_ready": True,
            "blocked_ids": [],
            "unavailable_ids": [],
            "results": {},
        },
        send_commands_to_selected=lambda _drones, _payload, target_ids: {
            "success": len(target_ids),
            "offline": 0,
            "rejected": 0,
            "errors": 0,
            "result_summary": f"{len(target_ids)} accepted",
            "results": {
                str(target_id): {"success": True, "category": "accepted"}
                for target_id in target_ids
            },
        },
        send_commands_to_all=lambda drones, payload: {
            "success": len(drones),
            "offline": 0,
            "rejected": 0,
            "errors": 0,
            "result_summary": f"{len(drones)} accepted",
            "results": {
                str(drone["hw_id"]): {"success": True, "category": "accepted"}
                for drone in drones
            },
        },
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
            GCS_TELEMETRY_REQUEST_TIMEOUT_SEC=1.0,
            drone_api_port=5001,
        ),
    )


def _plan_request():
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
        "pos_ids": [0],
    }


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
    assert "/api/sar/mission/{mission_id}/resume" in routes
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


def test_sar_launch_uses_tracked_command_response():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        response = client.post("/api/sar/mission/launch", params={"mission_id": mission_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["drones_launched"] == 1
    assert payload["submissions"][0]["command"]["command_id"]
    assert payload["submissions"][0]["command"]["target_drones"] == ["1"]


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
    assert launched.status_code == 200
    assert launched.json()["success"] is True


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
        response = client.post(
            f"/api/sar/mission/{mission_id}/abort",
            params={"return_behavior": "hold_position"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["return_behavior"] == "hold_position"
    assert payload["command"]["mission_type"] == Mission.HOLD.value
    assert payload["effect"] == "command_accepted"


def test_sar_resume_returns_replan_guidance():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sar_router(deps))

    with TestClient(app) as client:
        planned = client.post("/api/sar/mission/plan", json=_plan_request())
        mission_id = planned.json()["mission_id"]
        client.post("/api/sar/mission/launch", params={"mission_id": mission_id})
        client.post(f"/api/sar/mission/{mission_id}/pause")
        response = client.post(f"/api/sar/mission/{mission_id}/resume")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["effect"] == "replan_required"
    assert "follow-up package" in payload["operator_guidance"].lower()


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
