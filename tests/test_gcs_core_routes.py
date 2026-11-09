from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
import time

import pytest
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
    assert "/api/v1/fleet/action-readiness" in routes
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


def test_core_router_action_readiness_is_target_scoped_and_fresh():
    deps = _make_deps()
    now = time.time()
    deps.last_telemetry_time = {"1": now}
    deps.get_all_heartbeats = lambda: {
        "1": {
            "hw_id": "1",
            "timestamp": int(now * 1000),
        }
    }
    app = FastAPI()
    app.include_router(create_core_router(deps))

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/fleet/action-readiness",
            params=[("target_drone_ids", "1")],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_drone_ids"] == ["1"]
    assert payload["all_targets_ready"] is True
    assert payload["ready_target_count"] == 1
    assert payload["unavailable_target_ids"] == []
    assert payload["targets"][0]["live"] is True
    assert payload["targets"][0]["ready_to_arm"] is True


def test_core_router_action_readiness_rejects_stale_telemetry_with_fresh_heartbeat():
    deps = _make_deps()
    now = time.time()
    deps.last_telemetry_time = {"1": now - 300}
    deps.get_all_heartbeats = lambda: {
        "1": {
            "hw_id": "1",
            "timestamp": int(now * 1000),
        }
    }
    app = FastAPI()
    app.include_router(create_core_router(deps))

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/fleet/action-readiness",
            params=[("target_drone_ids", "1")],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["all_targets_ready"] is False
    assert payload["ready_target_count"] == 0
    assert payload["unavailable_target_ids"] == ["1"]
    assert payload["targets"][0]["live"] is False
    assert payload["targets"][0]["telemetry_available"] is True
    assert payload["targets"][0]["ready_to_arm"] is True
    assert payload["targets"][0]["ready"] is False


@pytest.mark.parametrize("target_count", [64, 65, 100, 101])
def test_core_router_action_readiness_capacity_is_bounded_and_uses_cached_evidence(target_count):
    deps = _make_deps()
    now = time.time()
    target_ids = [str(index) for index in range(target_count, 0, -1)]
    deps.telemetry_data_all_drones = {
        hw_id: {"hw_id": hw_id, "telemetry_available": True, "is_ready_to_arm": True}
        for hw_id in target_ids
    }
    deps.last_telemetry_time = {hw_id: now for hw_id in target_ids}
    deps.load_config = Mock(return_value=[{"hw_id": hw_id} for hw_id in target_ids])
    deps.get_all_heartbeats = Mock(return_value={})
    deps.data_lock = MagicMock()
    deps.get_fleet_rpc_service = Mock(side_effect=AssertionError("Readiness must not probe nodes"))
    app = FastAPI()
    app.include_router(create_core_router(deps))

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/fleet/action-readiness",
            params=[("target_drone_ids", hw_id) for hw_id in target_ids],
        )

    deps.get_fleet_rpc_service.assert_not_called()
    if target_count > 100:
        assert response.status_code == 422
        deps.load_config.assert_not_called()
        deps.get_all_heartbeats.assert_not_called()
        deps.data_lock.__enter__.assert_not_called()
        return

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_drone_ids"] == target_ids
    assert [target["hw_id"] for target in payload["targets"]] == target_ids
    assert payload["all_targets_ready"] is True
    assert payload["ready_target_count"] == target_count
    assert payload["unavailable_target_ids"] == []
    assert all(target["configured"] and target["ready"] for target in payload["targets"])
    deps.load_config.assert_called_once_with()
    deps.get_all_heartbeats.assert_called_once_with()
    deps.data_lock.__enter__.assert_called_once_with()
    deps.data_lock.__exit__.assert_called_once_with(None, None, None)


def test_core_router_action_readiness_preserves_first_seen_order_with_mixed_evidence():
    deps = _make_deps()
    now = time.time()
    deps.telemetry_data_all_drones = {
        "1": {"hw_id": "1", "telemetry_available": True, "is_ready_to_arm": True},
        "2": {"hw_id": "2", "telemetry_available": True, "is_ready_to_arm": True},
        "3": {"hw_id": "3", "telemetry_available": False, "is_ready_to_arm": True},
        "5": {"hw_id": "5", "telemetry_available": True, "is_ready_to_arm": False},
        "6": {"hw_id": "6", "telemetry_available": True, "is_ready_to_arm": "true"},
    }
    deps.last_telemetry_time = {hw_id: now for hw_id in deps.telemetry_data_all_drones}
    deps.last_telemetry_time["2"] = now - 300
    deps.get_all_heartbeats = Mock(return_value={
        "2": {"hw_id": "2", "received_at_gcs_ms": int(now * 1000)},
    })
    deps.load_config = Mock(return_value=[{"hw_id": str(index)} for index in range(1, 7)])
    requested_ids = ["6", "1", "2", "6", "3", "4", "2", "5", "7"]
    ordered_ids = ["6", "1", "2", "3", "4", "5", "7"]
    app = FastAPI()
    app.include_router(create_core_router(deps))

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/fleet/action-readiness",
            params=[("target_drone_ids", hw_id) for hw_id in requested_ids],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_drone_ids"] == ordered_ids
    assert [target["hw_id"] for target in payload["targets"]] == ordered_ids
    assert payload["all_targets_ready"] is False
    assert payload["ready_target_count"] == 1
    assert payload["unavailable_target_ids"] == ["6", "2", "3", "4", "5", "7"]
    targets = {target["hw_id"]: target for target in payload["targets"]}
    assert targets["1"]["ready"] is True
    assert targets["2"]["presence_state"] == "live"
    assert targets["2"]["live"] is False
    assert targets["3"]["telemetry_available"] is False
    assert targets["4"]["presence_state"] == "never_seen"
    assert targets["4"]["ready_to_arm"] is None
    assert targets["5"]["ready_to_arm"] is False
    assert targets["6"]["ready_to_arm"] is None
    assert targets["7"]["configured"] is False
    assert targets["7"]["presence_state"] == "never_seen"
    deps.load_config.assert_called_once_with()
    deps.get_all_heartbeats.assert_called_once_with()


def test_core_router_heartbeats_include_configured_never_seen_nodes():
    deps = _make_deps()
    deps.get_all_heartbeats = lambda: {}
    deps.telemetry_data_all_drones = {}
    deps.last_telemetry_time = {}
    deps.load_config = lambda: [
        {"hw_id": "1", "pos_id": 1, "ip": "10.0.0.1"},
        {"hw_id": "2", "pos_id": 2, "ip": "10.0.0.2"},
    ]
    app = FastAPI()
    app.include_router(create_core_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/v1/fleet/heartbeats")

    assert response.status_code == 200
    data = response.json()
    assert data["online_count"] == 0
    assert data["state_counts"]["never_seen"] == 2
    rows = {item["hw_id"]: item for item in data["heartbeats"]}
    assert rows["1"]["presence_state"] == "never_seen"
    assert rows["1"]["presence"]["configured"] is True
