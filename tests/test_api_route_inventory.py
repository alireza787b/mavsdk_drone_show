# tests/test_api_route_inventory.py
"""
Route inventory guardrails for the current public API surface.

This test freezes the active business routes before the API cleanup/migration
program starts. Any route additions, removals, or method changes should update
this file deliberately as part of the contract change.
"""

import signal
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute


_ORIGINAL_SIGNAL = signal.signal
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_GCS_SERVER = _PROJECT_ROOT / "gcs-server"
_SRC_DIR = _PROJECT_ROOT / "src"

for _path in (str(_PROJECT_ROOT), str(_GCS_SERVER), str(_SRC_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _safe_signal(sig, handler):
    try:
        return _ORIGINAL_SIGNAL(sig, handler)
    except ValueError:
        return None


signal.signal = _safe_signal

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
DOC_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


GCS_EXPECTED_HTTP = {
    "GET": {
        "/ping",
        "/health",
        "/telemetry",
        "/api/telemetry",
        "/api/v1/system/health",
        "/api/v1/fleet/telemetry",
        "/api/v1/fleet/heartbeats",
        "/api/v1/fleet/network-status",
        "/get-heartbeats",
        "/get-network-status",
        "/get-config-data",
        "/get-drone-positions",
        "/get-trajectory-first-row",
        "/get-swarm-data",
        "/command/{command_id}",
        "/commands/recent",
        "/commands/active",
        "/commands/statistics",
        "/git-status",
        "/get-origin",
        "/get-gps-global-origin",
        "/api/swarm/leaders",
        "/api/swarm/trajectory/recommendation",
        "/api/swarm/trajectory/status",
        "/api/swarm/trajectory/policy",
        "/api/swarm/trajectory/download/{drone_id}",
        "/api/swarm/trajectory/download-kml/{drone_id}",
        "/api/swarm/trajectory/download-cluster-kml/{leader_id}",
        "/download-raw-show",
        "/download-processed-show",
        "/get-show-info",
        "/get-custom-show-info",
        "/get-comprehensive-metrics",
        "/get-safety-report",
        "/get-show-plots/{filename}",
        "/get-show-plots",
        "/get-custom-show-image",
        "/elevation",
        "/get-origin-for-drone",
        "/get-position-deviations",
        "/get-desired-launch-positions",
        "/get-gcs-config",
        "/get-gcs-git-status",
        "/get-drone-git-status/{drone_id}",
        "/get-network-info",
        "/static/plots/{filename}",
        "/api/logs/sources",
        "/api/logs/sessions",
        "/api/logs/sessions/{session_id}",
        "/api/logs/stream",
        "/api/logs/drone/{drone_id}/sessions",
        "/api/logs/drone/{drone_id}/sessions/{session_id}",
        "/api/logs/drone/{drone_id}/stream",
        "/api/sar/mission/{mission_id}/status",
        "/api/sar/poi",
    },
    "POST": {
        "/heartbeat",
        "/drone-heartbeat",
        "/api/v1/fleet/heartbeats",
        "/save-config-data",
        "/validate-config",
        "/save-swarm-data",
        "/submit_command",
        "/command/{command_id}/cancel",
        "/command/execution-result",
        "/command/execution-start",
        "/sync-repos",
        "/set-origin",
        "/import-show",
        "/api/swarm/trajectory/upload/{leader_id}",
        "/api/swarm/trajectory/process",
        "/api/swarm/trajectory/clear-processed",
        "/api/swarm/trajectory/clear",
        "/api/swarm/trajectory/clear-leader/{leader_id}",
        "/api/swarm/trajectory/clear-drone/{drone_id}",
        "/api/swarm/trajectory/commit",
        "/import-custom-show",
        "/validate-trajectory",
        "/deploy-show",
        "/compute-origin",
        "/save-gcs-config",
        "/request-new-leader",
        "/api/logs/frontend",
        "/api/logs/export",
        "/api/logs/drone/{drone_id}/export",
        "/api/logs/config",
        "/api/sar/mission/plan",
        "/api/sar/mission/launch",
        "/api/sar/mission/{mission_id}/pause",
        "/api/sar/mission/{mission_id}/resume",
        "/api/sar/mission/{mission_id}/abort",
        "/api/sar/mission/{mission_id}/progress",
        "/api/sar/poi",
        "/api/sar/elevation/batch",
    },
    "PATCH": {
        "/api/sar/poi/{poi_id}",
    },
    "DELETE": {
        "/api/swarm/trajectory/remove/{leader_id}",
        "/api/sar/poi/{poi_id}",
    },
    "PUT": set(),
}

GCS_EXPECTED_WS = {
    "/ws/telemetry",
    "/ws/heartbeats",
    "/ws/git-status",
}

DRONE_EXPECTED_HTTP = {
    "GET": {
        "/get_drone_state",
        "/api/live-armability",
        "/api/v1/drone/state",
        "/api/v1/preflight/armability",
        "/api/v1/navigation/home",
        "/api/v1/navigation/global-origin",
        "/api/v1/system/health",
        "/api/v1/network/status",
        "/api/v1/swarm/config",
        "/api/v1/telemetry/local-position",
        "/get-home-pos",
        "/get-gps-global-origin",
        "/get-git-status",
        "/ping",
        "/get-position-deviation",
        "/get-network-status",
        "/get-swarm-data",
        "/get-local-position-ned",
        "/api/logs/sessions",
        "/api/logs/sessions/{session_id}",
        "/api/logs/stream",
    },
    "POST": {
        "/api/send-command",
        "/api/v1/drone/commands",
    },
    "PATCH": set(),
    "DELETE": set(),
    "PUT": set(),
}

DRONE_EXPECTED_WS = {
    "/ws/drone-state",
}


def _collect_http_routes(app):
    route_map = {method: set() for method in HTTP_METHODS}
    route_index = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in DOC_PATHS:
            continue
        for method in sorted((route.methods or set()) & HTTP_METHODS):
            route_map[method].add(route.path)
            route_index[(method, route.path)] = route
    return route_map, route_index


def _collect_ws_routes(app):
    return {
        route.path
        for route in app.routes
        if isinstance(route, APIWebSocketRoute)
    }


def _find_duplicate_http_method_paths(app):
    seen = set()
    duplicates = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in DOC_PATHS:
            continue
        for method in sorted((route.methods or set()) & HTTP_METHODS):
            key = (method, route.path)
            if key in seen:
                duplicates.add(key)
            seen.add(key)
    return duplicates


@pytest.fixture
def gcs_app():
    with patch("app_fastapi.BackgroundServices") as mock_services:
        mock_instance = Mock()
        mock_instance.start = Mock()
        mock_instance.stop = Mock()
        mock_services.return_value = mock_instance
        from app_fastapi import app
        yield app


@pytest.fixture
def drone_app():
    params = Mock()
    params.config_file_name = "config_sitl.json"
    params.swarm_file_name = "swarm_sitl.json"

    drone_config = Mock()
    drone_config.hw_id = 1
    drone_config.pos_id = 1
    drone_config.state = 0

    drone_communicator = Mock()

    with patch.dict(sys.modules, {"aiogrpc": Mock()}):
        from src.drone_api_server import DroneAPIServer

        api_server = DroneAPIServer(params, drone_config)
        api_server.set_drone_communicator(drone_communicator)
        yield api_server.app


def test_gcs_business_route_inventory(gcs_app):
    actual_http, _ = _collect_http_routes(gcs_app)
    actual_ws = _collect_ws_routes(gcs_app)

    assert actual_http == GCS_EXPECTED_HTTP
    assert actual_ws == GCS_EXPECTED_WS


def test_gcs_business_route_inventory_has_no_duplicate_method_paths(gcs_app):
    assert _find_duplicate_http_method_paths(gcs_app) == set()


def test_gcs_legacy_alias_routes_and_deprecations(gcs_app):
    _, route_index = _collect_http_routes(gcs_app)

    assert route_index[("GET", "/api/v1/system/health")].endpoint is route_index[("GET", "/health")].endpoint
    assert route_index[("GET", "/ping")].endpoint is route_index[("GET", "/health")].endpoint
    assert route_index[("GET", "/api/v1/fleet/telemetry")].endpoint is route_index[("GET", "/api/telemetry")].endpoint
    assert route_index[("GET", "/api/v1/fleet/heartbeats")].endpoint is route_index[("GET", "/get-heartbeats")].endpoint
    assert route_index[("GET", "/api/v1/fleet/network-status")].endpoint is route_index[("GET", "/get-network-status")].endpoint
    assert route_index[("POST", "/api/v1/fleet/heartbeats")].endpoint is route_index[("POST", "/heartbeat")].endpoint
    assert route_index[("POST", "/heartbeat")].endpoint is route_index[("POST", "/drone-heartbeat")].endpoint

    assert route_index[("GET", "/get-gcs-git-status")].deprecated is True
    assert route_index[("GET", "/get-drone-git-status/{drone_id}")].deprecated is True


def test_drone_business_route_inventory(drone_app):
    actual_http, route_index = _collect_http_routes(drone_app)
    actual_ws = _collect_ws_routes(drone_app)

    assert actual_http == DRONE_EXPECTED_HTTP
    assert actual_ws == DRONE_EXPECTED_WS

    assert route_index[("GET", "/api/v1/drone/state")].endpoint is route_index[("GET", "/get_drone_state")].endpoint
    assert route_index[("GET", "/api/v1/preflight/armability")].endpoint is route_index[("GET", "/api/live-armability")].endpoint
    assert route_index[("POST", "/api/v1/drone/commands")].endpoint is route_index[("POST", "/api/send-command")].endpoint
    assert route_index[("GET", "/api/v1/navigation/home")].endpoint is route_index[("GET", "/get-home-pos")].endpoint
    assert route_index[("GET", "/api/v1/navigation/global-origin")].endpoint is route_index[("GET", "/get-gps-global-origin")].endpoint
    assert route_index[("GET", "/api/v1/network/status")].endpoint is route_index[("GET", "/get-network-status")].endpoint
    assert route_index[("GET", "/api/v1/swarm/config")].endpoint is route_index[("GET", "/get-swarm-data")].endpoint
    assert route_index[("GET", "/api/v1/telemetry/local-position")].endpoint is route_index[("GET", "/get-local-position-ned")].endpoint
