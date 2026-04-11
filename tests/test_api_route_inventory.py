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
        "/api/v1/system/health",
        "/api/v1/fleet/telemetry",
        "/api/v1/fleet/heartbeats",
        "/api/v1/fleet/candidates",
        "/api/v1/fleet/candidates/{candidate_id}",
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
        "/api/v1/px4-params/policy",
        "/api/v1/px4-params/profiles",
        "/api/v1/px4-params/profiles/{profile_id}",
        "/api/v1/px4-params/patch-jobs/{job_id}",
        "/api/v1/px4-params/snapshots/{snapshot_id}",
        "/api/v1/px4-params/snapshots/{snapshot_id}/rows",
        "/api/v1/commands/recent",
        "/api/v1/commands/active",
        "/api/v1/commands/statistics",
        "/api/v1/commands/policy/precision-move",
        "/api/v1/commands/{command_id}",
        "/api/v1/system/gcs-config",
        "/api/v1/swarm-trajectories/leaders",
        "/api/v1/swarm-trajectories/recommendation",
        "/api/v1/swarm-trajectories/status",
        "/api/v1/swarm-trajectories/policy",
        "/api/v1/swarm-trajectories/download/{drone_id}",
        "/api/v1/swarm-trajectories/download-kml/{drone_id}",
        "/api/v1/swarm-trajectories/download-cluster-kml/{leader_id}",
        "/api/v1/swarm-trajectories/plots/{filename}",
        "/api/logs/sources",
        "/api/logs/sessions",
        "/api/logs/sessions/{session_id}",
        "/api/logs/stream",
        "/api/logs/drone/{drone_id}/sessions",
        "/api/logs/drone/{drone_id}/sessions/{session_id}",
        "/api/logs/drone/{drone_id}/stream",
        "/api/logs/drone/{drone_id}/ulog/policy",
        "/api/logs/drone/{drone_id}/ulog/files",
        "/api/logs/drone/{drone_id}/ulog/downloads/{job_id}",
        "/api/logs/drone/{drone_id}/ulog/downloads/{job_id}/content",
        "/api/sar/missions",
        "/api/sar/mission/{mission_id}/workspace",
        "/api/sar/mission/{mission_id}/status",
        "/api/sar/mission/{mission_id}/handoff",
        "/api/sar/findings",
    },
    "POST": {
        "/api/v1/fleet/heartbeats",
        "/api/v1/fleet/candidates/announce",
        "/api/v1/config/fleet/validation",
        "/api/v1/commands",
        "/api/v1/command-reports/execution-result",
        "/api/v1/command-reports/execution-start",
        "/api/v1/git/sync-operations",
        "/api/v1/origin/compute",
        "/api/v1/px4-params/diff",
        "/api/v1/px4-params/imports/qgc",
        "/api/v1/px4-params/imports/mds",
        "/api/v1/px4-params/patch-jobs",
        "/api/v1/px4-params/snapshots",
        "/api/v1/shows/skybrush/import",
        "/api/v1/shows/custom/import",
        "/api/v1/shows/skybrush/deployments",
        "/api/v1/swarm-trajectories/upload/{leader_id}",
        "/api/v1/swarm-trajectories/process",
        "/api/v1/swarm-trajectories/clear-processed",
        "/api/v1/swarm-trajectories/clear",
        "/api/v1/swarm-trajectories/clear-leader/{leader_id}",
        "/api/v1/swarm-trajectories/clear-drone/{drone_id}",
        "/api/v1/swarm-trajectories/commit",
        "/api/logs/frontend",
        "/api/logs/export",
        "/api/logs/drone/{drone_id}/export",
        "/api/logs/drone/{drone_id}/ulog/files/{log_id}/download",
        "/api/logs/drone/{drone_id}/ulog/erase-all",
        "/api/logs/config",
        "/api/v1/fleet/candidates/{candidate_id}/accept",
        "/api/v1/fleet/candidates/{candidate_id}/replace",
        "/api/v1/fleet/candidates/{candidate_id}/recover",
        "/api/v1/fleet/candidates/{candidate_id}/reject",
        "/api/v1/fleet/candidates/{candidate_id}/ignore",
        "/api/sar/mission/plan",
        "/api/sar/mission/launch",
        "/api/sar/mission/{mission_id}/pause",
        "/api/sar/mission/{mission_id}/resume",
        "/api/sar/mission/{mission_id}/abort",
        "/api/sar/mission/{mission_id}/progress",
        "/api/sar/findings",
        "/api/sar/elevation/batch",
    },
    "PATCH": {
        "/api/v1/config/swarm/assignments/{hw_id}",
        "/api/sar/findings/{finding_id}",
    },
    "DELETE": {
        "/api/logs/drone/{drone_id}/ulog/downloads/{job_id}",
        "/api/v1/swarm-trajectories/remove/{leader_id}",
        "/api/sar/findings/{finding_id}",
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
        "/api/v1/drone/state",
        "/api/v1/preflight/armability",
        "/api/v1/navigation/home",
        "/api/v1/navigation/global-origin",
        "/api/v1/navigation/position-deviation",
        "/api/v1/git/status",
        "/api/v1/system/health",
        "/api/v1/network/status",
        "/api/v1/swarm/config",
        "/api/v1/telemetry/local-position",
        "/api/v1/px4-params/policy",
        "/api/v1/px4-params/snapshots/current",
        "/api/v1/px4-params/values/{name}",
        "/api/v1/ulog/policy",
        "/api/v1/ulog/files",
        "/api/v1/ulog/downloads/{job_id}",
        "/api/v1/ulog/downloads/{job_id}/content",
        "/ping",
        "/api/logs/sessions",
        "/api/logs/sessions/{session_id}",
        "/api/logs/stream",
    },
    "POST": {
        "/api/v1/drone/commands",
        "/api/v1/px4-params/snapshots/refresh",
        "/api/v1/px4-params/patches/apply",
        "/api/v1/ulog/files/{log_id}/download",
        "/api/v1/ulog/erase-all",
    },
    "PATCH": {
        "/api/v1/px4-params/values/{name}",
    },
    "DELETE": {
        "/api/v1/ulog/downloads/{job_id}",
    },
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
    assert ("GET", "/get-heartbeats") not in route_index
    assert ("GET", "/get-network-status") not in route_index
    assert ("POST", "/heartbeat") not in route_index
    assert ("POST", "/drone-heartbeat") not in route_index
    assert ("GET", "/git-status") not in route_index
    assert ("POST", "/sync-repos") not in route_index
    assert ("GET", "/get-gcs-git-status") not in route_index
    assert ("GET", "/get-drone-git-status/{drone_id}") not in route_index
    assert ("GET", "/get-gcs-config") not in route_index
    assert ("POST", "/save-gcs-config") not in route_index
    assert ("GET", "/get-network-info") not in route_index
    assert ("GET", "/static/plots/{filename}") not in route_index
    assert ("POST", "/submit_command") not in route_index
    assert ("GET", "/command/{command_id}") not in route_index
    assert ("GET", "/commands/recent") not in route_index
    assert ("GET", "/commands/active") not in route_index
    assert ("GET", "/commands/statistics") not in route_index
    assert ("POST", "/command/{command_id}/cancel") not in route_index
    assert ("POST", "/api/v1/commands/{command_id}/cancel") not in route_index
    assert ("POST", "/command/execution-start") not in route_index
    assert ("POST", "/command/execution-result") not in route_index
    assert ("GET", "/get-origin") not in route_index
    assert ("POST", "/set-origin") not in route_index
    assert ("GET", "/get-gps-global-origin") not in route_index
    assert ("GET", "/elevation") not in route_index
    assert ("GET", "/get-origin-for-drone") not in route_index
    assert ("GET", "/get-position-deviations") not in route_index
    assert ("POST", "/compute-origin") not in route_index
    assert ("GET", "/get-desired-launch-positions") not in route_index
    assert ("GET", "/get-config-data") not in route_index
    assert ("POST", "/save-config-data") not in route_index
    assert ("POST", "/validate-config") not in route_index
    assert ("GET", "/get-drone-positions") not in route_index
    assert ("GET", "/get-trajectory-first-row") not in route_index
    assert ("GET", "/get-swarm-data") not in route_index
    assert ("POST", "/save-swarm-data") not in route_index
    assert ("POST", "/request-new-leader") not in route_index
    assert ("POST", "/import-show") not in route_index
    assert ("GET", "/download-raw-show") not in route_index
    assert ("GET", "/download-processed-show") not in route_index
    assert ("GET", "/get-show-info") not in route_index
    assert ("GET", "/get-custom-show-info") not in route_index
    assert ("POST", "/import-custom-show") not in route_index
    assert ("GET", "/get-comprehensive-metrics") not in route_index
    assert ("GET", "/get-safety-report") not in route_index
    assert ("POST", "/validate-trajectory") not in route_index
    assert ("POST", "/deploy-show") not in route_index
    assert ("GET", "/get-show-plots") not in route_index
    assert ("GET", "/get-show-plots/{filename}") not in route_index
    assert ("GET", "/get-custom-show-image") not in route_index
    assert ("GET", "/api/swarm/leaders") not in route_index
    assert ("POST", "/api/swarm/trajectory/upload/{leader_id}") not in route_index
    assert ("POST", "/api/swarm/trajectory/process") not in route_index
    assert ("GET", "/api/swarm/trajectory/recommendation") not in route_index
    assert ("GET", "/api/swarm/trajectory/status") not in route_index
    assert ("GET", "/api/swarm/trajectory/policy") not in route_index
    assert ("POST", "/api/swarm/trajectory/clear-processed") not in route_index
    assert ("POST", "/api/swarm/trajectory/clear") not in route_index
    assert ("POST", "/api/swarm/trajectory/clear-leader/{leader_id}") not in route_index
    assert ("DELETE", "/api/swarm/trajectory/remove/{leader_id}") not in route_index
    assert ("GET", "/api/swarm/trajectory/download/{drone_id}") not in route_index
    assert ("GET", "/api/swarm/trajectory/download-kml/{drone_id}") not in route_index
    assert ("GET", "/api/swarm/trajectory/download-cluster-kml/{leader_id}") not in route_index
    assert ("POST", "/api/swarm/trajectory/clear-drone/{drone_id}") not in route_index
    assert ("POST", "/api/swarm/trajectory/commit") not in route_index


def test_drone_business_route_inventory(drone_app):
    actual_http, route_index = _collect_http_routes(drone_app)
    actual_ws = _collect_ws_routes(drone_app)

    assert actual_http == DRONE_EXPECTED_HTTP
    assert actual_ws == DRONE_EXPECTED_WS
    assert ("GET", "/ping") in route_index


def test_drone_legacy_alias_routes_retired(drone_app):
    _, route_index = _collect_http_routes(drone_app)

    assert ("GET", "/get_drone_state") not in route_index
    assert ("GET", "/api/live-armability") not in route_index
    assert ("POST", "/api/send-command") not in route_index
    assert ("GET", "/get-home-pos") not in route_index
    assert ("GET", "/get-gps-global-origin") not in route_index
    assert ("GET", "/get-git-status") not in route_index
    assert ("GET", "/get-position-deviation") not in route_index
    assert ("GET", "/get-network-status") not in route_index
    assert ("GET", "/get-swarm-data") not in route_index
    assert ("GET", "/get-local-position-ned") not in route_index
