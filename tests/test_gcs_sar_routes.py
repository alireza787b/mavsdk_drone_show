from threading import Lock
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sar.coverage_planner import SHAPELY_AVAILABLE
from sar.routes import create_sar_router


pytestmark = pytest.mark.skipif(not SHAPELY_AVAILABLE, reason="shapely not installed")


def _make_deps():
    return SimpleNamespace(
        telemetry_data_all_drones={
            "1": {
                "pos_id": 0,
                "hw_id": "1",
                "position_lat": 47.0,
                "position_long": 8.0,
            }
        },
        telemetry_lock=Lock(),
        load_config=lambda: [{"pos_id": 0, "hw_id": "1", "ip": "10.0.0.1"}],
        send_commands_to_selected=lambda *_args, **_kwargs: {"result_summary": "accepted"},
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
    assert "/api/sar/mission/launch" in routes
    assert "/api/sar/mission/{mission_id}/status" in routes
    assert "/api/sar/mission/{mission_id}/pause" in routes
    assert "/api/sar/mission/{mission_id}/resume" in routes
    assert "/api/sar/mission/{mission_id}/abort" in routes
    assert "/api/sar/mission/{mission_id}/progress" in routes
    assert "/api/sar/poi" in routes
    assert "/api/sar/poi/{poi_id}" in routes
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
        }
    }

    with TestClient(app) as client:
        response = client.post("/api/sar/mission/plan", json=_plan_request())

    assert response.status_code == 200
    plans = response.json()["plans"]
    assert plans
    assert plans[0]["hw_id"] == "7"
