from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import node_boot_status as node_boot_status_module
from api_routes.core import create_core_router


def _reset_node_boot_status():
    node_boot_status_module.node_boot_statuses.clear()


def _make_deps():
    return SimpleNamespace(
        MDS_VERSION="test",
        Params=SimpleNamespace(heartbeat_interval=10, TELEMETRY_POLLING_TIMEOUT=5),
        telemetry_data_all_drones={},
        last_telemetry_time={},
        data_lock=None,
        load_config=lambda: [{"hw_id": "2", "pos_id": 2, "ip": "10.0.0.2"}],
        get_all_heartbeats=lambda: {},
        get_network_info_from_heartbeats=lambda: {},
        handle_heartbeat_post=lambda **kwargs: {"accepted": True, "message": "Heartbeat received"},
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def test_node_boot_status_route_accepts_progress_without_heartbeat_presence():
    _reset_node_boot_status()
    app = FastAPI()
    app.include_router(create_core_router(_make_deps()))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/fleet/node-boot-status",
            json={
                "hw_id": "2",
                "pos_id": 2,
                "runtime_mode": "real",
                "phase": "fetch",
                "status": "running",
                "message": "Fetching repository updates",
                "timestamp": 1700000000000,
            },
        )
        listing = client.get("/api/v1/fleet/node-boot-status")

    assert response.status_code == 200
    assert response.json()["node"]["phase"] == "fetch"
    assert response.json()["node"]["pos_id"] == 2
    assert response.json()["node"]["ip"] == "10.0.0.2"
    assert response.json()["node"]["identity_trust"] == "config_bound"
    assert response.json()["node"]["source_ip_matched"] is False
    assert response.json()["node"]["timestamp"] != 1700000000000
    assert listing.status_code == 200
    body = listing.json()
    assert body["total_nodes"] == 1
    assert body["nodes"]["2"]["message"] == "Fetching repository updates"


def test_node_boot_status_rejects_missing_hw_id():
    _reset_node_boot_status()
    app = FastAPI()
    app.include_router(create_core_router(_make_deps()))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/fleet/node-boot-status",
            json={"hw_id": "", "phase": "fetch"},
        )

    assert response.status_code == 422


def test_node_boot_status_rejects_unconfigured_hw_id():
    _reset_node_boot_status()
    app = FastAPI()
    app.include_router(create_core_router(_make_deps()))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/fleet/node-boot-status",
            json={"hw_id": "99", "phase": "fetch"},
        )
        listing = client.get("/api/v1/fleet/node-boot-status")

    assert response.status_code == 400
    assert "unconfigured hw_id=99" in response.json()["detail"]
    assert listing.json()["total_nodes"] == 0


def test_node_boot_status_rejects_mismatched_config_identity_claims():
    _reset_node_boot_status()
    app = FastAPI()
    app.include_router(create_core_router(_make_deps()))

    with TestClient(app) as client:
        wrong_pos = client.post(
            "/api/v1/fleet/node-boot-status",
            json={"hw_id": "2", "pos_id": 99, "phase": "fetch"},
        )
        wrong_ip = client.post(
            "/api/v1/fleet/node-boot-status",
            json={"hw_id": "2", "ip": "10.0.0.99", "phase": "fetch"},
        )
        listing = client.get("/api/v1/fleet/node-boot-status")

    assert wrong_pos.status_code == 400
    assert "pos_id does not match" in wrong_pos.json()["detail"]
    assert wrong_ip.status_code == 400
    assert "ip does not match" in wrong_ip.json()["detail"]
    assert listing.json()["total_nodes"] == 0


def test_node_boot_status_uses_server_time_and_prunes_stale_reports(monkeypatch):
    _reset_node_boot_status()
    node_boot_status_module.node_boot_statuses["old"] = {
        "hw_id": "old",
        "phase": "fetch",
        "status": "running",
        "timestamp": 1,
        "first_seen": 1,
    }
    monkeypatch.setattr(node_boot_status_module, "_now_ms", lambda: 2_000_000)

    result = node_boot_status_module.handle_node_boot_status_post(
        hw_id="2",
        phase="fetch",
        status="running",
        timestamp=999_999_999_999,
        allowed_hw_ids={"2"},
    )

    assert result["node"]["timestamp"] == 2_000_000
    assert "old" not in node_boot_status_module.get_all_node_boot_statuses()
