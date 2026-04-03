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
        "/api/v1/fleet/network-details",
        "/api/v1/config/fleet",
        "/api/v1/config/fleet/trajectory-start-positions",
        "/api/v1/config/fleet/trajectory-start-positions/{pos_id}",
        "/api/v1/config/swarm",
        "/api/v1/git/status",
        "/api/v1/shows/skybrush",
        "/api/v1/shows/custom",
        "/api/v1/shows/skybrush/metrics",
        "/api/v1/shows/skybrush/safety-report",
        "/api/v1/shows/skybrush/validation",
        "/api/v1/shows/skybrush/archives/raw",
        "/api/v1/shows/skybrush/archives/processed",
        "/api/v1/shows/skybrush/plots",
        "/api/v1/shows/skybrush/plots/{filename}",
        "/api/v1/shows/custom/preview",
        "/api/v1/origin",
        "/api/v1/navigation/global-origin",
        "/api/v1/origin/elevation",
        "/api/v1/origin/bootstrap",
        "/api/v1/origin/deviations",
        "/api/v1/origin/launch-positions",
        "/api/v1/commands/recent",
        "/api/v1/commands/active",
        "/api/v1/commands/statistics",
        "/api/v1/commands/{command_id}",
        "/api/v1/system/gcs-config",
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
        "/get-network-info",
        "/api/v1/swarm-trajectories/plots/{filename}",
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
        "/api/v1/config/fleet/validation",
        "/api/v1/commands",
        "/api/v1/commands/{command_id}/cancel",
        "/api/v1/command-reports/execution-result",
        "/api/v1/command-reports/execution-start",
        "/api/v1/git/sync-operations",
        "/api/v1/origin/compute",
        "/api/v1/shows/skybrush/import",
        "/api/v1/shows/custom/import",
        "/api/v1/shows/skybrush/deployments",
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
        "/api/v1/config/swarm/assignments/{hw_id}",
        "/api/sar/poi/{poi_id}",
    },
    "DELETE": {
        "/api/swarm/trajectory/remove/{leader_id}",
        "/api/sar/poi/{poi_id}",
    },
    "PUT": {
        "/api/v1/config/fleet",
        "/api/v1/config/swarm",
        "/api/v1/origin",
        "/api/v1/system/gcs-config",
    },
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
    assert route_index[("GET", "/api/v1/config/fleet")].endpoint is route_index[("GET", "/get-config-data")].endpoint
    assert route_index[("PUT", "/api/v1/config/fleet")].endpoint is route_index[("POST", "/save-config-data")].endpoint
    assert route_index[("POST", "/api/v1/config/fleet/validation")].endpoint is route_index[("POST", "/validate-config")].endpoint
    assert route_index[("GET", "/api/v1/config/fleet/trajectory-start-positions")].endpoint is route_index[("GET", "/get-drone-positions")].endpoint
    assert route_index[("POST", "/api/v1/commands")].endpoint is route_index[("POST", "/submit_command")].endpoint
    assert route_index[("GET", "/api/v1/commands/{command_id}")].endpoint is route_index[("GET", "/command/{command_id}")].endpoint
    assert route_index[("GET", "/api/v1/commands/recent")].endpoint is route_index[("GET", "/commands/recent")].endpoint
    assert route_index[("GET", "/api/v1/commands/active")].endpoint is route_index[("GET", "/commands/active")].endpoint
    assert route_index[("GET", "/api/v1/commands/statistics")].endpoint is route_index[("GET", "/commands/statistics")].endpoint
    assert route_index[("POST", "/api/v1/commands/{command_id}/cancel")].endpoint is route_index[("POST", "/command/{command_id}/cancel")].endpoint
    assert route_index[("POST", "/api/v1/command-reports/execution-start")].endpoint is route_index[("POST", "/command/execution-start")].endpoint
    assert route_index[("POST", "/api/v1/command-reports/execution-result")].endpoint is route_index[("POST", "/command/execution-result")].endpoint
    assert route_index[("GET", "/api/v1/git/status")].endpoint is route_index[("GET", "/git-status")].endpoint
    assert route_index[("POST", "/api/v1/git/sync-operations")].endpoint is route_index[("POST", "/sync-repos")].endpoint
    assert route_index[("GET", "/api/v1/config/fleet/trajectory-start-positions/{pos_id}")].endpoint is not route_index[("GET", "/get-trajectory-first-row")].endpoint
    assert route_index[("GET", "/api/v1/config/swarm")].endpoint is not route_index[("GET", "/get-swarm-data")].endpoint
    assert route_index[("PUT", "/api/v1/config/swarm")].endpoint is not route_index[("POST", "/save-swarm-data")].endpoint
    assert route_index[("PATCH", "/api/v1/config/swarm/assignments/{hw_id}")].endpoint is not route_index[("POST", "/request-new-leader")].endpoint
    assert route_index[("GET", "/api/v1/origin")].endpoint is route_index[("GET", "/get-origin")].endpoint
    assert route_index[("PUT", "/api/v1/origin")].endpoint is route_index[("POST", "/set-origin")].endpoint
    assert route_index[("GET", "/api/v1/navigation/global-origin")].endpoint is route_index[("GET", "/get-gps-global-origin")].endpoint
    assert route_index[("GET", "/api/v1/origin/elevation")].endpoint is route_index[("GET", "/elevation")].endpoint
    assert route_index[("GET", "/api/v1/origin/deviations")].endpoint is route_index[("GET", "/get-position-deviations")].endpoint
    assert route_index[("POST", "/api/v1/origin/compute")].endpoint is route_index[("POST", "/compute-origin")].endpoint
    assert route_index[("GET", "/api/v1/origin/launch-positions")].endpoint is route_index[("GET", "/get-desired-launch-positions")].endpoint
    assert route_index[("POST", "/api/v1/shows/skybrush/import")].endpoint is route_index[("POST", "/import-show")].endpoint
    assert route_index[("GET", "/api/v1/shows/skybrush/archives/raw")].endpoint is route_index[("GET", "/download-raw-show")].endpoint
    assert route_index[("GET", "/api/v1/shows/skybrush/archives/processed")].endpoint is route_index[("GET", "/download-processed-show")].endpoint
    assert route_index[("GET", "/api/v1/shows/skybrush")].endpoint is route_index[("GET", "/get-show-info")].endpoint
    assert route_index[("GET", "/api/v1/shows/custom")].endpoint is route_index[("GET", "/get-custom-show-info")].endpoint
    assert route_index[("POST", "/api/v1/shows/custom/import")].endpoint is route_index[("POST", "/import-custom-show")].endpoint
    assert route_index[("GET", "/api/v1/shows/skybrush/metrics")].endpoint is route_index[("GET", "/get-comprehensive-metrics")].endpoint
    assert route_index[("GET", "/api/v1/shows/skybrush/safety-report")].endpoint is route_index[("GET", "/get-safety-report")].endpoint
    assert route_index[("GET", "/api/v1/shows/skybrush/validation")].endpoint is route_index[("POST", "/validate-trajectory")].endpoint
    assert route_index[("POST", "/api/v1/shows/skybrush/deployments")].endpoint is route_index[("POST", "/deploy-show")].endpoint
    assert route_index[("GET", "/api/v1/shows/skybrush/plots")].endpoint is route_index[("GET", "/get-show-plots")].endpoint
    assert route_index[("GET", "/api/v1/shows/skybrush/plots/{filename}")].endpoint is route_index[("GET", "/get-show-plots/{filename}")].endpoint
    assert route_index[("GET", "/api/v1/shows/custom/preview")].endpoint is route_index[("GET", "/get-custom-show-image")].endpoint
    assert route_index[("GET", "/api/v1/system/gcs-config")].endpoint is route_index[("GET", "/get-gcs-config")].endpoint
    assert route_index[("PUT", "/api/v1/system/gcs-config")].endpoint is route_index[("POST", "/save-gcs-config")].endpoint
    assert route_index[("GET", "/api/v1/fleet/network-details")].endpoint is route_index[("GET", "/get-network-info")].endpoint
    assert route_index[("GET", "/api/v1/swarm-trajectories/plots/{filename}")].endpoint is route_index[("GET", "/static/plots/{filename}")].endpoint

    assert ("GET", "/get-gcs-git-status") not in route_index
    assert ("GET", "/get-drone-git-status/{drone_id}") not in route_index


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
