from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.core import create_core_router


def _make_deps():
    return SimpleNamespace(
        MDS_VERSION="test-version",
        telemetry_data_all_drones={
            "1": {
                "pos_id": 1,
                "hw_id": 1,
                "state": "idle",
                "mission": 0,
                "last_mission": 0,
                "position_lat": 35.0,
                "position_long": -120.0,
                "position_alt": 488.0,
                "velocity_north": 0.0,
                "velocity_east": 0.0,
                "velocity_down": 0.0,
                "yaw": 180.0,
                "battery_voltage": 12.4,
                "follow_mode": 0,
                "update_time": "2026-04-03 00:00:00",
                "timestamp": 1_700_000_000_000,
                "flight_mode": 65536,
                "base_mode": 81,
                "system_status": 4,
                "is_armed": False,
                "is_ready_to_arm": True,
                "hdop": 0.8,
                "vdop": 1.1,
                "gps_fix_type": 3,
                "satellites_visible": 12,
                "ip": "10.0.0.1",
                "telemetry_available": True,
            }
        },
        Params=SimpleNamespace(TELEMETRY_POLLING_TIMEOUT=10),
        handle_heartbeat_post=Mock(),
        get_all_heartbeats=lambda: {
            "1": {
                "hw_id": "1",
                "pos_id": 1,
                "ip": "10.0.0.1",
                "timestamp": 1_700_000_000_000,
                "network_info": {"wifi": {"ssid": "mds", "signal_strength_percent": 88}},
            }
        },
        get_network_info_from_heartbeats=lambda: {
            "1": {"pos_id": 1, "ip": "10.0.0.1", "reachable": True, "last_check": 1_700_000_000_000}
        },
        load_config=lambda: [{"hw_id": "1", "ip": "10.0.0.1"}],
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def test_core_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_core_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/system/health" in routes
    assert "/api/v1/fleet/telemetry" in routes
    assert "/api/v1/fleet/heartbeats" in routes
    assert "/api/v1/fleet/network-status" in routes
    assert "/ws/telemetry" in routes
    assert "/ws/heartbeats" in routes


def test_core_router_uses_live_dependency_attributes_after_router_creation():
    deps = _make_deps()
    initial_handle = deps.handle_heartbeat_post

    app = FastAPI()
    app.include_router(create_core_router(deps))

    replacement_handle = Mock(return_value={"message": "Heartbeat received", "accepted": True})
    deps.handle_heartbeat_post = replacement_handle

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/fleet/heartbeats",
            json={
                "pos_id": 1,
                "hw_id": "1",
                "ip": "10.0.0.1",
                "timestamp": 1_700_000_000_000,
                "network_info": {"wifi": {"ssid": "mds", "signal_strength_percent": 88}},
            },
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    initial_handle.assert_not_called()
    replacement_handle.assert_called_once()


def test_core_router_typed_telemetry_sets_server_time_header():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_core_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/v1/fleet/telemetry")

    assert response.status_code == 200
    assert response.headers["X-MDS-Server-Time"].isdigit()
    assert response.json()["total_drones"] == 1
