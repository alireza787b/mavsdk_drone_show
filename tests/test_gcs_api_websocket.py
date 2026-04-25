"""Focused contract tests for the canonical GCS WebSocket streams."""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.core import create_core_router
from api_routes.git_status import create_git_router


def _make_core_deps():
    now_ms = int(time.time() * 1000)
    return SimpleNamespace(
        MDS_VERSION="test-version",
        telemetry_data_all_drones={
            1: {
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
                "update_time": "2026-04-04 00:00:00",
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
                "timestamp": now_ms,
                "network_info": {"wifi": {"ssid": "mds", "signal_strength_percent": 88}},
            }
        },
        get_network_info_from_heartbeats=lambda: {
            "1": {"pos_id": 1, "ip": "10.0.0.1", "reachable": True, "last_check": now_ms}
        },
        load_config=lambda: [{"hw_id": "1", "ip": "10.0.0.1"}],
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def _make_git_deps():
    return SimpleNamespace(
        Params=SimpleNamespace(GIT_BRANCH="main-candidate"),
        load_config=lambda: [{"hw_id": "1", "pos_id": 1, "ip": "10.0.0.1"}],
        get_gcs_git_report=lambda: {"branch": "main-candidate", "commit": "abc12345"},
        git_status_data_all_drones={
            "1": {
                "status": "clean",
                "branch": "main-candidate",
                "commit": "abc12345",
                "commit_message": "test commit",
                "uncommitted_changes": [],
            }
        },
        data_lock_git_status=threading.Lock(),
        _sync_state={"active": False, "started_at": None, "results": None},
        _sync_lock=asyncio.Lock(),
        _select_sync_target_drones=lambda drones_config, pos_ids: (drones_config, []),
        _verify_sync_targets=AsyncMock(return_value=([1], [])),
        send_commands_to_all=Mock(return_value={"results": {"1": {"category": "accepted"}}}),
        send_commands_to_selected=Mock(return_value={"results": {"1": {"category": "accepted"}}}),
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def test_telemetry_websocket_streams_typed_message():
    app = FastAPI()
    app.include_router(create_core_router(_make_core_deps()))

    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry") as websocket:
            payload = websocket.receive_json()

    assert payload["type"] == "telemetry"
    assert isinstance(payload["timestamp"], int)
    assert "1" in payload["data"]
    assert payload["data"]["1"]["battery_voltage"] == 12.4
    assert payload["data"]["1"]["position_lat"] == 35.0


def test_heartbeat_websocket_streams_normalized_heartbeat_list():
    app = FastAPI()
    app.include_router(create_core_router(_make_core_deps()))

    with TestClient(app) as client:
        with client.websocket_connect("/ws/heartbeats") as websocket:
            payload = websocket.receive_json()

    assert payload["type"] == "heartbeat"
    assert isinstance(payload["timestamp"], int)
    assert isinstance(payload["data"], list)
    assert len(payload["data"]) == 1
    assert payload["data"][0]["hw_id"] == "1"
    assert payload["data"][0]["online"] is True
    assert payload["data"][0]["presence_state"] == "live"
    assert payload["data"][0]["heartbeat_age_sec"] >= 0


def test_git_status_websocket_streams_snapshot_shape():
    app = FastAPI()
    app.include_router(create_git_router(_make_git_deps()))

    with TestClient(app) as client:
        with client.websocket_connect("/ws/git-status") as websocket:
            payload = websocket.receive_json()

    assert payload["type"] == "git_status"
    assert isinstance(payload["timestamp"], int)
    assert payload["sync_in_progress"] is False
    assert payload["data"]["total_drones"] == 1
    assert payload["data"]["synced_count"] == 1
    assert payload["data"]["git_status"]["1"]["status"] == "synced"
    assert payload["data"]["gcs_status"]["branch"] == "main-candidate"


def test_websocket_invalid_endpoint():
    app = FastAPI()
    app.include_router(create_core_router(_make_core_deps()))
    app.include_router(create_git_router(_make_git_deps()))

    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/nonexistent"):
                pass
