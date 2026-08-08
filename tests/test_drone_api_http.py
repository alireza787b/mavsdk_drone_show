# tests/test_drone_api_http.py
"""
HTTP REST Endpoint Tests
=========================
Tests for all HTTP REST endpoints in the Drone API Server.
"""

import pytest
import asyncio
import httpx
import logging
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock
from src.command_installation import CommandInstallationRejected, CommandInstallationResult
from src.command_contract import DroneCommandRequest
from src.enums import Mission, State
from src.launch_preparation_protocol import (
    LAUNCH_PREPARATION_TOKEN_HEADER,
    LaunchPreparationBinding,
)
from mds_logging.api_schemas import OnboardUlogDownloadJob, OnboardUlogDownloadJobResponse
from src.security.auth import (
    AuthService,
    AuthSettings,
    MACHINE_CREDENTIAL_HEADER,
    ULOG_OP_DOWNLOAD_CONTENT,
    ULOG_OP_DOWNLOAD_CREATE,
    ULOG_OP_DOWNLOAD_DELETE,
    ULOG_OP_ERASE,
    ULOG_OP_FILES_READ,
    ULOG_OP_POLICY_READ,
    ULOG_OP_SUMMARY_READ,
)
from src.ulog_service import UlogJobConflictError, UlogTransportTimeoutError


def _commit_mock_command(mock_drone_config, command_data):
    """Apply and prove the same typed install contract as DroneCommunicator."""
    mission_type = int(command_data["mission_type"])
    trigger_time = int(command_data["trigger_time"])
    command_id = command_data.get("command_id")
    mock_drone_config.mission = mission_type
    mock_drone_config.trigger_time = trigger_time
    mock_drone_config.current_command_id = command_id
    mock_drone_config.state = 1
    return CommandInstallationResult(
        committed=True,
        mission=mission_type,
        trigger_time=trigger_time,
        state=1,
        command_id=command_id,
        artifact_paths=(),
    )


def _set_fresh_airborne_state(mock_drone_config, *, relative_altitude_m=5.0):
    now_ms = time.time_ns() // 1_000_000
    mock_drone_config.is_armed = True
    mock_drone_config.heartbeat_timestamp_ms = now_ms
    mock_drone_config.global_position_timestamp_ms = now_ms
    mock_drone_config.relative_altitude_m = relative_altitude_m
    mock_drone_config.px4_home_position_set = True


def _ready_launch_probe(hw_id="1"):
    now_ms = int(time.time() * 1_000)
    return {
        "hw_id": str(hw_id),
        "success": True,
        "ready": True,
        "summary": "ready for mission startup",
        "observation": {
            "schema_version": 1,
            "observation_id": f"route-test-{now_ms}",
            "source": "test.health+battery",
            "observed_at_ms": now_ms,
            "valid_until_ms": now_ms + 2_000,
            "require_global_position": True,
            "ready": True,
            "blockers": [],
            "checks": {"armable": True},
            "battery": {"remaining_percent": 80.0},
        },
        "remaining_valid_ms": 2_000,
        "server_processing_ms": 1,
    }


def _prepared_launch_headers(api_server, command):
    """Issue node-local authority for focused command-route unit tests."""
    parsed = DroneCommandRequest.model_validate(command)
    token, _ = api_server._launch_preparation_store.issue(
        LaunchPreparationBinding.from_command(parsed)
    )
    api_server._probe_live_armability = AsyncMock(
        return_value=_ready_launch_probe(api_server.drone_config.hw_id)
    )
    return {LAUNCH_PREPARATION_TOKEN_HEADER: token}


@pytest.fixture
def ulog_machine_headers(api_server, monkeypatch, tmp_path):
    auth_dir = tmp_path / "machine-auth"
    token_file = auth_dir / "node-token"
    monkeypatch.setenv("MDS_API_TOKENS_FILE", str(auth_dir / "api_tokens.json"))
    monkeypatch.setenv("MDS_AUTH_USERS_FILE", str(auth_dir / "users.json"))
    monkeypatch.setenv("MDS_AUTH_SESSION_SECRET_FILE", str(auth_dir / "session_secret"))
    monkeypatch.setenv("MDS_AUTH_CSRF_SECRET_FILE", str(auth_dir / "csrf_secret"))
    monkeypatch.setenv("MDS_GCS_API_TOKEN_FILE", str(token_file))

    service = AuthService(AuthSettings.from_env())
    created = service.store.create_token(
        "drone-1",
        scopes=["drone"],
        ttl_seconds=3600,
    )
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(f"{created['token']}\n", encoding="utf-8")

    def build(
        operation: str,
        *,
        audience: str | None = None,
        now_epoch: int | None = None,
        ttl_seconds: int = 15,
    ) -> dict[str, str]:
        credential = service.issue_machine_credential(
            audience=audience or f"mds-drone:{api_server.drone_config.hw_id}",
            operation=operation,
            ttl_seconds=ttl_seconds,
            now_epoch=now_epoch,
        )
        return {MACHINE_CREDENTIAL_HEADER: credential}

    return build


class TestHealthCheck:
    """Test health check endpoint"""

    def test_ping_success(self, test_client):
        """Test /ping endpoint returns ok"""
        response = test_client.get("/ping")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_v1_health_survives_ulog_capability_probe_failure(self, test_client, api_server, monkeypatch):
        """Health must remain usable when optional ULog capability probing fails."""
        monkeypatch.setattr(api_server, "_build_ulog_capability", Mock(side_effect=RuntimeError("ulog probe failed")))

        response = test_client.get("/api/v1/system/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["ulog_capability"]["available"] is False
        assert data["ulog_capability"]["missing_dependency"] == "ulog_capability_probe_failed"


class TestDroneStateTelemetryFields:
    def test_state_preserves_altitude_policy_evidence(self, api_server):
        payload = api_server._serialize_drone_state_payload(
            {
                "pos_id": 1,
                "detected_pos_id": 1,
                "state": 0,
                "mission": 0,
                "last_mission": 0,
                "position_lat": 35.7,
                "position_long": 51.2,
                "position_alt": 1298.2,
                "velocity_north": 0.0,
                "velocity_east": 0.0,
                "velocity_down": 0.0,
                "yaw": 0.0,
                "battery_voltage": 16.2,
                "battery_remaining_percent": 72.0,
                "battery_charge_state": 1,
                "battery_fault_bitmask": 0,
                "battery_timestamp_ms": 1732270245000,
                "battery_age_ms": 250,
                "flight_mode": 0,
                "base_mode": 0,
                "system_status": 3,
                "is_armed": False,
                "is_ready_to_arm": True,
                "hdop": 0.7,
                "vdop": 1.1,
                "gps_fix_type": 3,
                "satellites_visible": 10,
                "ip": "172.18.0.2",
                "update_time": 1732270245,
                "altitude_report": {
                    "display_m": 20.2,
                    "source": "local_ned",
                    "label": "LCL",
                    "local_up_m": 20.2,
                },
                "altitude_display_m": 20.2,
                "altitude_source": "local_ned",
                "relative_altitude_m": None,
                "local_position_down": -20.2,
            }
        )

        assert payload["altitude_report"]["display_m"] == 20.2
        assert payload["altitude_source"] == "local_ned"
        assert payload["local_position_down"] == -20.2
        assert payload["battery_remaining_percent"] == 72.0
        assert payload["battery_charge_state"] == 1
        assert payload["battery_fault_bitmask"] == 0
        assert payload["battery_timestamp_ms"] == 1732270245000
        assert payload["battery_age_ms"] == 250


class TestNodeEnvironment:
    """Test node-local env inspection and mutation endpoints."""

    def test_get_node_env_uses_registry_metadata(self, test_client, monkeypatch, tmp_path):
        local_env = tmp_path / "local.env"
        identity_file = tmp_path / "node_identity.json"
        local_env.write_text("MDS_MODE=real\nMDS_CONNECTIVITY_BACKEND=smart-wifi-manager\n", encoding="utf-8")
        identity_file.write_text('{"hw_id": 1, "runtime_mode": "real"}\n', encoding="utf-8")
        monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(local_env))
        monkeypatch.setenv("MDS_NODE_IDENTITY_FILE", str(identity_file))

        response = test_client.get("/api/v1/system/env")

        assert response.status_code == 200
        data = response.json()
        assert data["config_path"] == str(local_env)
        assert data["config_present"] is True
        assert data["summary"]["runtime_mode"] == "real"
        connectivity = next(item for item in data["values"] if item["name"] == "MDS_CONNECTIVITY_BACKEND")
        assert connectivity["value"] == "smart-wifi-manager"
        assert connectivity["editable"] is True
        assert connectivity["source_of_truth"] == "/etc/mds/local.env"

    def test_update_node_env_persists_registry_approved_value(self, test_client, monkeypatch, tmp_path):
        local_env = tmp_path / "local.env"
        local_env.write_text("MDS_CONNECTIVITY_BACKEND=smart-wifi-manager\n", encoding="utf-8")
        monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(local_env))

        response = test_client.request(
            "PUT",
            "/api/v1/system/env",
            json={"updates": {"MDS_CONNECTIVITY_BACKEND": "none"}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["changed_keys"] == ["MDS_CONNECTIVITY_BACKEND"]
        assert data["restart_required"] is True
        assert "MDS_CONNECTIVITY_BACKEND=none" in local_env.read_text(encoding="utf-8")

    def test_update_node_env_rejects_wrong_scope(self, test_client, monkeypatch, tmp_path):
        local_env = tmp_path / "local.env"
        monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(local_env))

        response = test_client.request(
            "PUT",
            "/api/v1/system/env",
            json={"updates": {"MDS_MODE": "real"}},
        )

        assert response.status_code == 422
        assert "cannot be written to node" in response.json()["detail"]


class TestSidecarProfileProxy:
    """Test node-local sidecar profile proxy routes."""

    def test_profile_proxy_uses_loopback_sidecar_api(self, test_client, monkeypatch):
        captured = {}

        class DummyResponse:
            status_code = 200
            text = "{}"

            @staticmethod
            def json():
                return {"dry_run_id": "node-plan", "confirmation_token": "node-token"}

        def fake_post(url, json, headers, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            captured["timeout"] = timeout
            return DummyResponse()

        monkeypatch.delenv("MDS_SIDECAR_PROFILE_TOKEN", raising=False)
        monkeypatch.delenv("SMART_WIFI_MANAGER_API_TOKEN", raising=False)
        monkeypatch.setattr("src.drone_api_server.requests.post", fake_post)

        response = test_client.post(
            "/api/v1/sidecars/smart-wifi-manager/profiles/import",
            json={"mode": "fleet-merge", "dry_run": True},
        )

        assert response.status_code == 200
        assert captured["url"] == "http://127.0.0.1:9080/api/v1/profiles/import"
        assert captured["json"]["dry_run"] is True
        assert captured["headers"] == {}
        assert captured["timeout"] == 10

    def test_profile_apply_refreshes_mds_reconcile_state(self, test_client, monkeypatch, tmp_path):
        repo_root = tmp_path / "repo"
        helper = repo_root / "tools" / "reconcile_connectivity.sh"
        helper.parent.mkdir(parents=True)
        helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        captured = {}

        class DummyResponse:
            status_code = 200
            text = "{}"

            @staticmethod
            def json():
                return {"applied": True}

        def fake_post(url, json, headers, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            captured["timeout"] = timeout
            return DummyResponse()

        def fake_run(command, cwd, stdout, stderr, timeout, check):
            captured["refresh_command"] = command
            captured["refresh_cwd"] = cwd
            captured["refresh_timeout"] = timeout
            return Mock(returncode=0)

        monkeypatch.setenv("MDS_REPO_ROOT", str(repo_root))
        monkeypatch.setattr("src.drone_api_server.os.geteuid", lambda: 0)
        monkeypatch.setattr("src.drone_api_server.requests.post", fake_post)
        monkeypatch.setattr("src.drone_api_server.subprocess.run", fake_run)

        response = test_client.post(
            "/api/v1/sidecars/smart-wifi-manager/profiles/apply",
            json={"dry_run_id": "node-plan"},
        )

        assert response.status_code == 200
        assert response.json()["applied"] is True
        assert response.json()["mds_reconcile_refresh"] == {"ok": True, "status": "success"}
        assert captured["url"] == "http://127.0.0.1:9080/api/v1/profiles/apply"
        assert captured["refresh_command"] == [str(helper), "apply", "--force", "--quiet"]
        assert captured["refresh_cwd"] == str(repo_root)
        assert captured["refresh_timeout"] == 60

    def test_profile_import_uses_local_reconcile_preview_for_legacy_mode_error(self, test_client, monkeypatch, tmp_path):
        repo_root = tmp_path / "repo"
        helper = repo_root / "tools" / "reconcile_connectivity.sh"
        helper.parent.mkdir(parents=True)
        helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        captured = {"posts": []}

        class ErrorResponse:
            status_code = 500
            text = '{"error":"mode must be manage, observe, or disabled"}'

            @staticmethod
            def json():
                return {"error": "mode must be manage, observe, or disabled"}

        def fake_post(url, json, headers, timeout):
            captured["posts"].append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return ErrorResponse()

        def fake_run(command, cwd, capture_output, text, timeout, check):
            captured["status_command"] = command
            captured["status_cwd"] = cwd
            return Mock(
                returncode=0,
                stdout=(
                    "backend=smart-wifi-manager\n"
                    "ref=v2.1.11\n"
                    "mode=fleet-merge\n"
                    "desired_config_hash=desired-control\n"
                    "applied_config_hash=old-control\n"
                    "config_hash_match=false\n"
                    "service_status=active\n"
                ),
            )

        monkeypatch.setenv("MDS_REPO_ROOT", str(repo_root))
        monkeypatch.setattr("src.drone_api_server.requests.post", fake_post)
        monkeypatch.setattr("src.drone_api_server.subprocess.run", fake_run)

        response = test_client.post(
            "/api/v1/sidecars/smart-wifi-manager/profiles/import",
            json={"mode": "fleet-merge", "dry_run": True},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["dry_run_id"].startswith("mds-local-reconcile-")
        assert payload["mutation_path"] == "mds-local-reconcile-helper"
        assert payload["runtime"]["config_hash_match"] == "false"
        assert len(captured["posts"]) == 1
        assert captured["status_command"] == [str(helper), "status", "--quiet"]
        assert captured["status_cwd"] == str(repo_root)

    def test_profile_import_repairs_smart_wifi_service_mode_then_retries(self, test_client, monkeypatch, tmp_path):
        repo_root = tmp_path / "repo"
        install_dir = tmp_path / "smart-wifi-manager"
        configure = install_dir / "configure_smart_wifi_manager.sh"
        configure.parent.mkdir(parents=True)
        configure.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        captured = {"posts": []}

        class ErrorResponse:
            status_code = 500
            text = '{"error":"mode must be manage, observe, or disabled"}'

            @staticmethod
            def json():
                return {"error": "mode must be manage, observe, or disabled"}

        class SuccessResponse:
            status_code = 200
            text = "{}"

            @staticmethod
            def json():
                return {"dry_run_id": "node-plan", "confirmation_token": "node-token"}

        def fake_post(url, json, headers, timeout):
            captured["posts"].append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return ErrorResponse() if len(captured["posts"]) == 1 else SuccessResponse()

        def fake_run(command, cwd, stdout, stderr, timeout, check):
            captured["repair_command"] = command
            captured["repair_cwd"] = cwd
            return Mock(returncode=0)

        monkeypatch.setenv("MDS_REPO_ROOT", str(repo_root))
        monkeypatch.setenv("MDS_SMART_WIFI_MANAGER_INSTALL_DIR", str(install_dir))
        monkeypatch.setattr("src.drone_api_server.os.geteuid", lambda: 0)
        monkeypatch.setattr("src.drone_api_server.requests.post", fake_post)
        monkeypatch.setattr("src.drone_api_server.subprocess.run", fake_run)

        response = test_client.post(
            "/api/v1/sidecars/smart-wifi-manager/profiles/import",
            json={"mode": "fleet-merge", "dry_run": True},
        )

        assert response.status_code == 200
        assert response.json()["dry_run_id"] == "node-plan"
        assert response.json()["mds_mode_repair"] == {"ok": True, "status": "success"}
        assert len(captured["posts"]) == 2
        assert captured["repair_command"] == [
            str(configure),
            "--headless",
            "--config",
            "/etc/smart-wifi-manager/config.json",
            "--mode",
            "manage",
        ]
        assert captured["repair_cwd"] == str(repo_root)

    def test_profile_import_uses_local_reconcile_preview_when_token_missing(self, test_client, monkeypatch, tmp_path):
        repo_root = tmp_path / "repo"
        helper = repo_root / "tools" / "reconcile_connectivity.sh"
        helper.parent.mkdir(parents=True)
        helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        captured = {}

        class ErrorResponse:
            status_code = 403
            text = '{"error":"SMART_WIFI_MANAGER_API_TOKEN is required for remote mutating requests"}'

            @staticmethod
            def json():
                return {"error": "SMART_WIFI_MANAGER_API_TOKEN is required for remote mutating requests"}

        def fake_post(url, json, headers, timeout):
            captured["url"] = url
            return ErrorResponse()

        def fake_run(command, cwd, capture_output, text, timeout, check):
            captured["status_command"] = command
            captured["status_cwd"] = cwd
            return Mock(
                returncode=0,
                stdout=(
                    "backend=smart-wifi-manager\n"
                    "ref=v2.1.11\n"
                    "mode=fleet-merge\n"
                    "desired_config_hash=desired-control\n"
                    "applied_config_hash=old-control\n"
                    "config_hash_match=false\n"
                    "service_status=active\n"
                ),
            )

        monkeypatch.setenv("MDS_REPO_ROOT", str(repo_root))
        monkeypatch.setattr("src.drone_api_server.requests.post", fake_post)
        monkeypatch.setattr("src.drone_api_server.subprocess.run", fake_run)

        response = test_client.post(
            "/api/v1/sidecars/smart-wifi-manager/profiles/import",
            json={"mode": "fleet-merge", "dry_run": True},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["dry_run"] is True
        assert payload["dry_run_id"].startswith("mds-local-reconcile-")
        assert payload["confirmation_token"]
        assert payload["mutation_path"] == "mds-local-reconcile-helper"
        assert payload["runtime"]["config_hash_match"] == "false"
        assert captured["url"] == "http://127.0.0.1:9080/api/v1/profiles/import"
        assert captured["status_command"] == [str(helper), "status", "--quiet"]
        assert captured["status_cwd"] == str(repo_root)

    def test_profile_apply_uses_local_reconcile_when_token_missing(self, test_client, monkeypatch, tmp_path):
        repo_root = tmp_path / "repo"
        helper = repo_root / "tools" / "reconcile_connectivity.sh"
        helper.parent.mkdir(parents=True)
        helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        captured = {}

        class ErrorResponse:
            status_code = 403
            text = '{"error":"SMART_WIFI_MANAGER_API_TOKEN is required for remote mutating requests"}'

            @staticmethod
            def json():
                return {"error": "SMART_WIFI_MANAGER_API_TOKEN is required for remote mutating requests"}

        def fake_post(url, json, headers, timeout):
            captured["url"] = url
            return ErrorResponse()

        def fake_run(command, cwd, stdout, stderr, timeout, check):
            captured["apply_command"] = command
            captured["apply_cwd"] = cwd
            return Mock(returncode=0)

        monkeypatch.setenv("MDS_REPO_ROOT", str(repo_root))
        monkeypatch.setattr("src.drone_api_server.os.geteuid", lambda: 0)
        monkeypatch.setattr("src.drone_api_server.requests.post", fake_post)
        monkeypatch.setattr("src.drone_api_server.subprocess.run", fake_run)

        response = test_client.post(
            "/api/v1/sidecars/smart-wifi-manager/profiles/apply",
            json={"dry_run_id": "mds-local-reconcile-plan", "confirmation": {"token": "node-token"}},
        )

        assert response.status_code == 200
        assert response.json()["applied"] is True
        assert response.json()["mutation_path"] == "mds-local-reconcile-helper"
        assert response.json()["mds_reconcile_refresh"] == {"ok": True, "status": "success"}
        assert captured["url"] == "http://127.0.0.1:9080/api/v1/profiles/apply"
        assert captured["apply_command"] == [str(helper), "apply", "--force", "--quiet"]
        assert captured["apply_cwd"] == str(repo_root)

    def test_profile_apply_uses_local_reconcile_for_legacy_mode_error(self, test_client, monkeypatch, tmp_path):
        repo_root = tmp_path / "repo"
        helper = repo_root / "tools" / "reconcile_connectivity.sh"
        helper.parent.mkdir(parents=True)
        helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        captured = {}

        class ErrorResponse:
            status_code = 500
            text = '{"error":"mode must be manage, observe, or disabled"}'

            @staticmethod
            def json():
                return {"error": "mode must be manage, observe, or disabled"}

        def fake_post(url, json, headers, timeout):
            captured["url"] = url
            return ErrorResponse()

        def fake_run(command, cwd, stdout, stderr, timeout, check):
            captured["apply_command"] = command
            captured["apply_cwd"] = cwd
            return Mock(returncode=0)

        monkeypatch.setenv("MDS_REPO_ROOT", str(repo_root))
        monkeypatch.setattr("src.drone_api_server.os.geteuid", lambda: 0)
        monkeypatch.setattr("src.drone_api_server.requests.post", fake_post)
        monkeypatch.setattr("src.drone_api_server.subprocess.run", fake_run)

        response = test_client.post(
            "/api/v1/sidecars/smart-wifi-manager/profiles/apply",
            json={"dry_run_id": "mds-local-reconcile-plan", "confirmation": {"token": "node-token"}},
        )

        assert response.status_code == 200
        assert response.json()["applied"] is True
        assert response.json()["mutation_path"] == "mds-local-reconcile-helper"
        assert captured["url"] == "http://127.0.0.1:9080/api/v1/profiles/apply"
        assert captured["apply_command"] == [str(helper), "apply", "--force", "--quiet"]
        assert captured["apply_cwd"] == str(repo_root)

    def test_profile_proxy_rejects_unknown_action(self, test_client):
        response = test_client.post(
            "/api/v1/sidecars/smart-wifi-manager/profiles/delete-all",
            json={},
        )

        assert response.status_code == 404


class TestDroneState:
    """Test drone state endpoint"""

    def test_get_drone_state_success(self, test_client, mock_drone_communicator):
        """Test canonical drone-state endpoint returns valid state"""
        response = test_client.get("/api/v1/drone/state")

        assert response.status_code == 200
        data = response.json()

        # Verify key fields
        assert 'pos_id' in data
        assert 'position_lat' in data
        assert 'position_alt' in data
        assert 'battery_voltage' in data
        assert 'is_armed' in data
        assert 'timestamp' in data
        assert 'readiness_status' in data
        assert 'readiness_summary' in data

        # Verify values
        assert data['pos_id'] == 1
        assert data['battery_voltage'] == 12.6
        assert data['is_armed'] is False

    def test_get_live_armability_success(self, test_client, monkeypatch):
        from src.drone_api_server import DroneAPIServer

        async def _mock_probe(self, require_global_position=True):
            return {
                "hw_id": "1",
                "success": True,
                "ready": True,
                "summary": "ready for mission startup",
                "blockers": [],
                "armable": True,
                "global_position_ok": True,
                "home_position_ok": True,
                "local_position_ok": True,
                "gyro_ok": True,
                "accel_ok": True,
                "mag_ok": True,
                "health_ready": True,
                "health_age_ms": 25,
                "battery": {
                    "remaining_percent": 81.0,
                    "minimum_remaining_percent": 30.0,
                    "voltage_v": 16.0,
                    "fresh": True,
                    "reserve_ok": True,
                },
                "observation": {
                    "schema_version": 1,
                    "observation_id": "health-test-1",
                    "source": "mavsdk_health",
                    "observed_at_ms": 100,
                    "valid_until_ms": 2_100,
                    "require_global_position": require_global_position,
                    "ready": True,
                    "blockers": [],
                },
                "remaining_valid_ms": 1_900,
                "server_processing_ms": 100,
                "timed_out": False,
                "elapsed_sec": 0.2,
                "require_global_position": require_global_position,
                "timestamp": 123,
                "probe_error": None,
            }

        monkeypatch.setattr(DroneAPIServer, "_probe_live_armability", _mock_probe)

        response = test_client.get("/api/v1/preflight/armability")

        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["hw_id"] == "1"
        assert data["summary"] == "ready for mission startup"
        assert data["require_global_position"] is True
        assert data["battery"]["remaining_percent"] == 81.0
        assert data["battery"]["minimum_remaining_percent"] == 30.0
        assert data["battery"]["fresh"] is True

    def test_resolve_live_probe_connection_uses_runtime_ports(
        self,
        api_server,
        mock_drone_config,
        mock_params,
    ):
        from src.constants import NetworkDefaults

        mock_params.DEFAULT_GRPC_PORT = NetworkDefaults.GRPC_BASE_PORT
        mock_params.mavsdk_port = 14540
        grpc_port, system_address = api_server._resolve_live_probe_connection()

        assert grpc_port == NetworkDefaults.GRPC_BASE_PORT
        assert system_address == "udp://:14540"

    @pytest.mark.asyncio
    async def test_probe_live_armability_starts_temporary_server(self, api_server, monkeypatch, mock_params):
        import src.drone_api_server as drone_api_server

        mock_params.DEFAULT_GRPC_PORT = 50040
        mock_params.mavsdk_port = 14540
        mock_params.LIVE_ARMABILITY_PROBE_TIMEOUT_SEC = 6.0
        fake_process = object()
        captured = {}

        class FakeSystem:
            def __init__(self, mavsdk_server_address, port):
                captured["mavsdk_server_address"] = mavsdk_server_address
                captured["grpc_port"] = port

            async def connect(self, system_address):
                captured["system_address"] = system_address

        async def _fake_ensure(self, grpc_port, udp_port):
            captured["ensure"] = (grpc_port, udp_port)
            return fake_process, True

        def _fake_stop(self, process):
            captured["stopped_process"] = process

        async def _fake_wait(self, drone):
            captured["wait_called"] = True

        async def _fake_probe(drone, require_global_position, timeout, logger):
            captured["probe_timeout"] = timeout
            return {
                "ready": True,
                "summary": "ready for mission startup",
                "blockers": [],
                "armable": True,
                "global_position_ok": True,
                "home_position_ok": True,
                "local_position_ok": True,
                "gyro_ok": True,
                "accel_ok": True,
                "mag_ok": True,
                "observation": {
                    "schema_version": 1,
                    "observation_id": "health-test-route-1",
                    "source": "mavsdk_health",
                    "observed_at_ms": 100,
                    "valid_until_ms": 2_100,
                    "require_global_position": require_global_position,
                    "ready": True,
                    "blockers": [],
                },
                "remaining_valid_ms": 1_900,
                "server_processing_ms": 100,
                "timed_out": False,
                "elapsed_sec": 0.1,
                "require_global_position": require_global_position,
            }

        monkeypatch.setattr(drone_api_server, "System", FakeSystem)
        monkeypatch.setattr(drone_api_server.DroneAPIServer, "_ensure_live_probe_server", _fake_ensure)
        monkeypatch.setattr(drone_api_server.DroneAPIServer, "_stop_live_probe_server", _fake_stop)
        monkeypatch.setattr(drone_api_server.DroneAPIServer, "_wait_for_mavsdk_connection", _fake_wait)
        monkeypatch.setattr(drone_api_server, "probe_offboard_armability", _fake_probe)

        result = await api_server._probe_live_armability(require_global_position=True)

        assert result["success"] is True
        assert result["hw_id"] == "1"
        assert captured["ensure"] == (50040, 14540)
        assert captured["mavsdk_server_address"] == "127.0.0.1"
        assert captured["grpc_port"] == 50040
        assert captured["system_address"] == "udp://:14540"
        assert captured["wait_called"] is True
        assert captured["stopped_process"] is fake_process

    @pytest.mark.asyncio
    async def test_probe_live_armability_bounds_connect_wait(self, api_server, monkeypatch, mock_params):
        import src.drone_api_server as drone_api_server

        mock_params.DEFAULT_GRPC_PORT = 50040
        mock_params.mavsdk_port = 14540
        mock_params.LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC = 0.01
        mock_params.LIVE_ARMABILITY_PROBE_TIMEOUT_SEC = 6.0

        class FakeSystem:
            def __init__(self, mavsdk_server_address, port):
                self.mavsdk_server_address = mavsdk_server_address
                self.port = port

            async def connect(self, system_address):
                await asyncio.sleep(1.0)

        async def _fake_ensure(self, grpc_port, udp_port):
            return None, False

        wait_mock = AsyncMock()

        monkeypatch.setattr(drone_api_server, "System", FakeSystem)
        monkeypatch.setattr(drone_api_server.DroneAPIServer, "_ensure_live_probe_server", _fake_ensure)
        monkeypatch.setattr(drone_api_server.DroneAPIServer, "_wait_for_mavsdk_connection", wait_mock)

        result = await api_server._probe_live_armability(require_global_position=True)

        assert result["success"] is False
        assert result["hw_id"] == "1"
        assert result["timed_out"] is True
        assert "Timed out" in result["summary"]
        wait_mock.assert_not_awaited()

    def test_get_drone_state_no_data(self, test_client, mock_drone_communicator):
        """Test canonical drone-state endpoint when no data available"""
        mock_drone_communicator.get_drone_state.return_value = None

        response = test_client.get("/api/v1/drone/state")

        assert response.status_code == 404
        assert 'detail' in response.json()

    def test_get_swarm_state_success(self, test_client):
        response = test_client.get("/api/v1/swarm/state")

        assert response.status_code == 200
        data = response.json()
        assert data["hw_id"] == 1
        assert data["source_frame"] == "local_ned"
        assert data["telemetry_timestamp_ms"] == 1732270245000
        assert data["stream_seq"] == 7

    def test_get_swarm_state_no_data(self, test_client, mock_drone_communicator):
        mock_drone_communicator.get_swarm_state.return_value = None

        response = test_client.get("/api/v1/swarm/state")

        assert response.status_code == 404
        assert 'detail' in response.json()

    def test_get_px4_param_policy(self, test_client):
        response = test_client.get("/api/v1/px4-params/policy")

        assert response.status_code == 200
        data = response.json()
        assert data["subsystem"] == "px4_params"
        assert data["docs"]["base_url"].startswith("https://docs.px4.io/")

    def test_refresh_px4_param_snapshot_success(self, test_client, api_server, monkeypatch):
        class FakeParamPlugin:
            async def get_all_params(self):
                from mavsdk.param import AllParams, IntParam

                return AllParams(
                    int_params=[IntParam("MAV_SYS_ID", 1)],
                    float_params=[],
                    custom_params=[],
                )

        class FakeComponentInformation:
            async def access_float_params(self):
                return []

        fake_drone = type(
            "FakeDrone",
            (),
            {
                "param": FakeParamPlugin(),
                "component_information": FakeComponentInformation(),
            },
        )()

        async def fake_with_local_system(operation):
            return await operation(fake_drone)

        monkeypatch.setattr(api_server, "_with_local_mavsdk_system", fake_with_local_system)

        response = test_client.post("/api/v1/px4-params/snapshots/refresh", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["snapshot"]["total_params"] == 1
        assert data["rows"][0]["name"] == "MAV_SYS_ID"

        cached = test_client.get("/api/v1/px4-params/snapshots/current")
        assert cached.status_code == 200
        assert cached.json()["snapshot"]["total_params"] == 1

    def test_refresh_px4_param_snapshot_reports_missing_mavsdk_server(
        self,
        test_client,
        api_server,
        monkeypatch,
        tmp_path,
    ):
        import src.drone_api_server as drone_api_server

        async def fake_with_local_system(operation):
            raise FileNotFoundError("mavsdk_server binary not found")

        monkeypatch.setattr(drone_api_server, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(api_server, "_with_local_mavsdk_system", fake_with_local_system)

        response = test_client.post("/api/v1/px4-params/snapshots/refresh", json={})

        assert response.status_code == 424
        detail = response.json()["detail"]
        assert detail["error"] == "mavsdk_server_missing"
        assert detail["action"] == "refresh_px4_param_snapshot"
        assert detail["mavsdk_capability"]["mavsdk_server_present"] is False

    def test_refresh_px4_param_snapshot_reports_missing_mavsdk_server_with_ulog_fallback(
        self,
        test_client,
        api_server,
        monkeypatch,
        tmp_path,
    ):
        import src.drone_api_server as drone_api_server

        async def fake_with_local_system(operation):
            raise FileNotFoundError("mavsdk_server binary not found")

        fallback_dir = tmp_path / "ulog"
        fallback_dir.mkdir()
        monkeypatch.setattr(drone_api_server, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(api_server, "_with_local_mavsdk_system", fake_with_local_system)
        monkeypatch.setattr(api_server._ulog_service, "filesystem_fallback_dirs", lambda: [fallback_dir])

        response = test_client.post("/api/v1/px4-params/snapshots/refresh", json={})

        assert response.status_code == 424
        detail = response.json()["detail"]
        assert detail["error"] == "mavsdk_server_missing"
        assert detail["mavsdk_capability"]["available"] is False
        assert detail["mavsdk_capability"]["filesystem_fallback_configured"] is False

    def test_set_px4_param_value_rejected_while_armed(self, test_client, mock_drone_config):
        mock_drone_config.is_armed = True

        response = test_client.request(
            "PATCH",
            "/api/v1/px4-params/values/MAV_SYS_ID",
            json={
                "component_id": 1,
                "value_type": "int",
                "value": 3,
                "verify_readback": True,
            },
        )

        assert response.status_code == 409
        assert "armed" in response.json()["detail"]

    def test_apply_px4_param_patch_success(self, test_client, api_server, monkeypatch):
        class FakeParamPlugin:
            def __init__(self):
                self.values = {"MAV_SYS_ID": 1}

            async def set_param_int(self, name, value):
                self.values[name] = int(value)

            async def get_param_int(self, name):
                return self.values[name]

            async def get_param_float(self, name):
                raise RuntimeError("wrong type")

            async def get_param_custom(self, name):
                raise RuntimeError("wrong type")

        fake_drone = type(
            "FakeDrone",
            (),
            {
                "param": FakeParamPlugin(),
                "component_information": None,
            },
        )()

        async def fake_with_local_system(operation):
            return await operation(fake_drone)

        monkeypatch.setattr(api_server, "_with_local_mavsdk_system", fake_with_local_system)

        response = test_client.post(
            "/api/v1/px4-params/patches/apply",
            json={
                "source": "api",
                "verify_readback": True,
                "entries": [
                    {
                        "component_id": 1,
                        "name": "MAV_SYS_ID",
                        "value_type": "int",
                        "value": 42,
                    }
                ],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["applied_count"] == 1
        assert data["failed_count"] == 0
        assert data["verified_count"] == 1

    def test_get_onboard_ulog_policy(self, test_client, ulog_machine_headers):
        response = test_client.get(
            "/api/v1/ulog/policy",
            headers=ulog_machine_headers(ULOG_OP_POLICY_READ),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["hw_id"] == "1"
        assert data["policy"]["download_supported"] is True
        assert data["policy"]["single_delete_supported"] is False
        assert "ulog_capability" in data
        assert "mavsdk_server_present" in data["ulog_capability"]

    def test_list_onboard_ulog_files_success(
        self,
        test_client,
        api_server,
        monkeypatch,
        ulog_machine_headers,
    ):
        async def fake_with_local_system(operation):
            return await operation(object())

        monkeypatch.setattr(api_server, "_with_local_ulog_system", fake_with_local_system)
        monkeypatch.setattr(
            api_server._ulog_service,
            "list_entries",
            AsyncMock(
                return_value={
                    "hw_id": "1",
                    "pos_id": 1,
                    "count": 1,
                    "files": [{"id": 5, "date_utc": "2026-04-11T10:00:00Z", "size_bytes": 512}],
                    "policy": api_server._ulog_service.build_policy().policy.model_dump(),
                    "timestamp": 123,
                }
            ),
        )

        response = test_client.get(
            "/api/v1/ulog/files",
            headers=ulog_machine_headers(ULOG_OP_FILES_READ),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["files"][0]["id"] == 5

    def test_list_onboard_ulog_files_reports_missing_mavsdk_server(
        self,
        test_client,
        api_server,
        monkeypatch,
        tmp_path,
        ulog_machine_headers,
    ):
        import src.drone_api_server as drone_api_server

        async def fake_with_local_system(operation):
            raise FileNotFoundError("mavsdk_server binary not found")

        monkeypatch.setattr(drone_api_server, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(api_server, "_with_local_ulog_system", fake_with_local_system)
        monkeypatch.setattr(api_server._ulog_service, "filesystem_fallback_dirs", lambda: [])

        response = test_client.get(
            "/api/v1/ulog/files",
            headers=ulog_machine_headers(ULOG_OP_FILES_READ),
        )

        assert response.status_code == 424
        detail = response.json()["detail"]
        assert detail["error"] == "mavsdk_server_missing"
        assert detail["ulog_capability"]["mavsdk_server_present"] is False

    def test_ulog_summary_transport_timeout_is_not_reported_as_parser_timeout(
        self,
        test_client,
        api_server,
        monkeypatch,
        ulog_machine_headers,
    ):
        async def timed_out_before_operation(_operation):
            raise TimeoutError()

        monkeypatch.setattr(
            api_server,
            "_with_local_ulog_system",
            timed_out_before_operation,
        )
        monkeypatch.setattr(
            api_server.params,
            "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC",
            5.0,
        )

        response = test_client.get(
            "/api/v1/ulog/files/9/summary",
            headers=ulog_machine_headers(ULOG_OP_SUMMARY_READ),
        )

        assert response.status_code == 504
        detail = response.json()["detail"]
        assert detail["code"] == "ulog_transport_timeout"
        assert detail["error"] == "ulog_transport_timeout"
        assert detail["error"] != "ulog_summary_timeout"
        assert detail["stage"] == "transport_setup"
        assert detail["timeout_seconds"] == 5.0
        assert detail["retryable"] is True
        assert "node-local MAVSDK ULog transport" in detail["message"]

    def test_ulog_parser_timeout_keeps_distinct_typed_result(
        self,
        test_client,
        api_server,
        monkeypatch,
        ulog_machine_headers,
    ):
        from mds_logging.ulog_analysis import UlogSummaryTimeoutError

        async def parser_timed_out(_operation):
            raise UlogSummaryTimeoutError(
                "ULog summary timed out after 90 second(s)"
            )

        monkeypatch.setattr(
            api_server,
            "_with_local_ulog_system",
            parser_timed_out,
        )

        response = test_client.get(
            "/api/v1/ulog/files/9/summary",
            headers=ulog_machine_headers(ULOG_OP_SUMMARY_READ),
        )

        assert response.status_code == 504
        detail = response.json()["detail"]
        assert detail["code"] == "ulog_summary_timeout"
        assert detail["error"] == "ulog_summary_timeout"
        assert "stage" not in detail

    @pytest.mark.asyncio
    async def test_ulog_rpc_connect_timeout_carries_exact_setup_stage(
        self,
        api_server,
        monkeypatch,
    ):
        import src.drone_api_server as drone_api_server

        class SlowSystem:
            def __init__(self, **_kwargs):
                pass

            async def connect(self, **_kwargs):
                await asyncio.sleep(1)

        monkeypatch.setattr(drone_api_server, "System", SlowSystem)
        monkeypatch.setattr(
            api_server,
            "_ensure_live_probe_server",
            AsyncMock(return_value=(None, False)),
        )
        monkeypatch.setattr(
            api_server.params,
            "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC",
            0.001,
        )

        with pytest.raises(UlogTransportTimeoutError) as exc_info:
            await api_server._with_local_ulog_system(AsyncMock())

        assert exc_info.value.code == "ulog_transport_timeout"
        assert exc_info.value.stage == "mavsdk_rpc_connect"
        assert exc_info.value.timeout_seconds == 0.001
        assert "opening the node-local MAVSDK RPC channel" in str(exc_info.value)

    def test_create_onboard_ulog_download_job_success(
        self,
        test_client,
        api_server,
        monkeypatch,
        ulog_machine_headers,
    ):
        scheduled = []

        async def fake_with_local_system(operation):
            return await operation(object())

        def fake_create_task(coro):
            scheduled.append(True)
            coro.close()
            return Mock()

        monkeypatch.setattr(api_server, "_with_local_ulog_system", fake_with_local_system)
        monkeypatch.setattr(
            api_server._ulog_service,
            "create_download_job",
            AsyncMock(
                return_value=OnboardUlogDownloadJobResponse(
                    job=OnboardUlogDownloadJob(
                        job_id="job-1",
                        hw_id="1",
                        pos_id=1,
                        log_id=9,
                        date_utc="2026-04-11T10:00:00Z",
                        size_bytes=256,
                        status="queued",
                        progress=0.0,
                        staged_filename="1-job.ulg",
                        download_filename="mds-ulog_P1_H1_20260411T100000Z_L9.ulg",
                        created_at=1,
                        updated_at=1,
                        expires_at=2,
                        error=None,
                    ),
                    timestamp=1,
                )
            ),
        )
        monkeypatch.setattr(api_server, "_run_ulog_download_job", AsyncMock(return_value=None))
        monkeypatch.setattr(asyncio, "create_task", fake_create_task)

        headers = ulog_machine_headers(ULOG_OP_DOWNLOAD_CREATE)
        headers["X-MDS-ULog-Job-Token"] = "test-capability"
        response = test_client.post(
            "/api/v1/ulog/files/9/download",
            json={},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["job"]["job_id"] == "job-1"
        assert scheduled == [True]
        assert (
            api_server._ulog_service.create_download_job.await_args.kwargs["access_token"]
            == "test-capability"
        )

    def test_create_onboard_ulog_download_requires_capability(
        self,
        test_client,
        ulog_machine_headers,
    ):
        response = test_client.post(
            "/api/v1/ulog/files/9/download",
            json={},
            headers=ulog_machine_headers(ULOG_OP_DOWNLOAD_CREATE),
        )

        assert response.status_code == 401

    def test_download_onboard_ulog_stream_holds_verified_file_lease(
        self,
        test_client,
        api_server,
        monkeypatch,
        tmp_path,
        ulog_machine_headers,
    ):
        staged_path = tmp_path / "staged.ulg"
        staged_path.write_bytes(b"ulog-stream")
        lifecycle = []
        job = OnboardUlogDownloadJob(
            job_id="job-1",
            hw_id="1",
            pos_id=1,
            log_id=9,
            date_utc="2026-04-11T10:00:00Z",
            size_bytes=11,
            status="ready",
            progress=1.0,
            staged_filename="1-job.ulg",
            download_filename="mds-ulog_P1_H1_L9.ulg",
            created_at=1,
            updated_at=1,
            expires_at=2,
            error=None,
        )

        @asynccontextmanager
        async def fake_lease(job_id):
            assert job_id == "job-1"
            lifecycle.append("entered")
            with staged_path.open("rb") as file_handle:
                try:
                    yield file_handle, staged_path, job
                finally:
                    lifecycle.append("exited")

        monkeypatch.setattr(
            api_server,
            "_assert_ulog_job_access",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            api_server._ulog_service,
            "lease_ready_file",
            fake_lease,
        )

        headers = ulog_machine_headers(ULOG_OP_DOWNLOAD_CONTENT)
        headers["X-MDS-ULog-Job-Token"] = "test-capability"
        response = test_client.get(
            "/api/v1/ulog/downloads/job-1/content",
            headers=headers,
        )

        assert response.status_code == 200
        assert response.content == b"ulog-stream"
        assert response.headers["content-length"] == "11"
        assert "mds-ulog_P1_H1_L9.ulg" in response.headers["content-disposition"]
        assert lifecycle == ["entered", "exited"]

    def test_delete_onboard_ulog_maps_active_job_conflict(
        self,
        test_client,
        api_server,
        monkeypatch,
        ulog_machine_headers,
    ):
        monkeypatch.setattr(
            api_server,
            "_assert_ulog_job_access",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            api_server._ulog_service,
            "delete_job",
            AsyncMock(side_effect=UlogJobConflictError("job is active")),
        )

        headers = ulog_machine_headers(ULOG_OP_DOWNLOAD_DELETE)
        headers["X-MDS-ULog-Job-Token"] = "test-capability"
        response = test_client.delete(
            "/api/v1/ulog/downloads/job-1",
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "ulog_job_conflict"

    def test_erase_all_onboard_ulogs_rejected_while_armed(
        self,
        test_client,
        mock_drone_config,
        ulog_machine_headers,
    ):
        mock_drone_config.is_armed = True

        response = test_client.post(
            "/api/v1/ulog/erase-all",
            headers=ulog_machine_headers(ULOG_OP_ERASE),
        )

        assert response.status_code == 409
        assert "armed" in response.json()["detail"]

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/v1/ulog/policy"),
            ("GET", "/api/v1/ulog/files"),
            ("GET", "/api/v1/ulog/files/1/summary"),
            ("POST", "/api/v1/ulog/files/1/download"),
            ("GET", "/api/v1/ulog/downloads/job-1"),
            ("DELETE", "/api/v1/ulog/downloads/job-1"),
            ("GET", "/api/v1/ulog/downloads/job-1/content"),
            ("POST", "/api/v1/ulog/erase-all"),
        ],
    )
    def test_every_onboard_ulog_endpoint_requires_machine_credential(
        self,
        test_client,
        ulog_machine_headers,
        method,
        path,
    ):
        assert ulog_machine_headers
        response = test_client.request(method, path, json={})

        assert response.status_code == 401
        assert response.json()["detail"] == "GCS machine credential is required."

    def test_onboard_ulog_policy_allows_zero_config_trusted_network_demo(
        self,
        test_client,
        monkeypatch,
    ):
        monkeypatch.delenv("MDS_GCS_API_TOKEN_FILE", raising=False)

        response = test_client.get("/api/v1/ulog/policy")

        assert response.status_code == 200

    def test_onboard_ulog_fails_closed_when_configured_token_is_unavailable(
        self,
        test_client,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setenv(
            "MDS_GCS_API_TOKEN_FILE",
            str(tmp_path / "missing-node-token"),
        )

        response = test_client.get("/api/v1/ulog/policy")

        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Node machine authentication is configured but unavailable."
        )

    def test_onboard_ulog_rejects_expired_machine_credential(
        self,
        test_client,
        ulog_machine_headers,
    ):
        response = test_client.get(
            "/api/v1/ulog/policy",
            headers=ulog_machine_headers(
                ULOG_OP_POLICY_READ,
                now_epoch=100,
                ttl_seconds=1,
            ),
        )

        assert response.status_code == 401

    def test_onboard_ulog_rejects_wrong_audience(
        self,
        test_client,
        ulog_machine_headers,
    ):
        response = test_client.get(
            "/api/v1/ulog/policy",
            headers=ulog_machine_headers(
                ULOG_OP_POLICY_READ,
                audience="mds-drone:2",
            ),
        )

        assert response.status_code == 401

    def test_onboard_ulog_rejects_wrong_operation_scope(
        self,
        test_client,
        ulog_machine_headers,
    ):
        response = test_client.get(
            "/api/v1/ulog/files",
            headers=ulog_machine_headers(ULOG_OP_POLICY_READ),
        )

        assert response.status_code == 401

    def test_onboard_ulog_rejects_tampered_machine_credential(
        self,
        test_client,
        ulog_machine_headers,
    ):
        headers = ulog_machine_headers(ULOG_OP_POLICY_READ)
        credential = headers[MACHINE_CREDENTIAL_HEADER]
        headers[MACHINE_CREDENTIAL_HEADER] = (
            credential[:-1] + ("A" if credential[-1] != "A" else "B")
        )

        response = test_client.get("/api/v1/ulog/policy", headers=headers)

        assert response.status_code == 401

    def test_onboard_ulog_rejects_immediate_machine_credential_replay(
        self,
        test_client,
        ulog_machine_headers,
    ):
        headers = ulog_machine_headers(ULOG_OP_POLICY_READ)

        first = test_client.get("/api/v1/ulog/policy", headers=headers)
        replay = test_client.get("/api/v1/ulog/policy", headers=headers)

        assert first.status_code == 200
        assert replay.status_code == 401


class TestCommands:
    """Test command endpoint"""

    @pytest.mark.parametrize("mission_type", [123, Mission.UNKNOWN.value])
    def test_send_command_rejects_non_executable_mission_before_mutation(
        self,
        test_client,
        mock_drone_communicator,
        mission_type,
    ):
        response = test_client.post(
            "/api/v1/drone/commands",
            json={"mission_type": mission_type, "trigger_time": 0},
        )

        assert response.status_code == 422
        assert "executable mission" in response.text
        mock_drone_communicator.process_command.assert_not_called()

    def test_send_command_success(
        self,
        test_client,
        api_server,
        mock_drone_communicator,
    ):
        """Test sending command to drone - new CommandAckResponse format"""
        command = {
            "mission_type": Mission.TAKE_OFF.value,
            "trigger_time": 0,
            "command_id": "takeoff-success",
            "target_hw_id": "1",
            "command_report_capability": "cap-" + ("x" * 39),
            "takeoff_altitude": 10.0,
        }
        response = test_client.post(
            "/api/v1/drone/commands",
            json=command,
            headers=_prepared_launch_headers(api_server, command),
        )

        assert response.status_code == 200
        data = response.json()

        # New response format uses CommandAckResponse
        assert data['status'] == 'accepted'
        assert 'message' in data
        assert 'hw_id' in data
        assert 'pos_id' in data
        assert 'mission_type' in data
        assert data['mission_type'] == 10  # TAKE_OFF

        # Verify command was processed
        mock_drone_communicator.process_command.assert_called_once()
        call_args = mock_drone_communicator.process_command.call_args[0][0]
        assert call_args['mission_type'] == 10
        assert call_args['trigger_time'] == 0

    def test_send_command_rejects_target_identity_mismatch_before_state_mutation(
        self,
        test_client,
        mock_drone_communicator,
        mock_drone_config,
    ):
        command = {
            "mission_type": Mission.TAKE_OFF.value,
            "trigger_time": 0,
            "command_id": "wrong-target",
            "target_hw_id": "2",
            "command_report_capability": "cap-" + ("x" * 39),
        }

        response = test_client.post("/api/v1/drone/commands", json=command)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
        assert data["error_code"] == "E108"
        assert data["hw_id"] == "1"
        assert "Intended hardware ID=2" in data["error_detail"]
        mock_drone_communicator.process_command.assert_not_called()
        assert mock_drone_config.current_command_id is None

    def test_send_command_accepts_canonical_prepared_launch_envelope(
        self,
        test_client,
        api_server,
        mock_drone_communicator,
    ):
        command = {
            "mission_type": "TAKE_OFF",
            "trigger_time": 0,
            "command_id": "canonical-takeoff",
            "target_hw_id": "1",
            "command_report_capability": "cap-" + ("x" * 39),
            "takeoff_altitude": 12,
        }
        response = test_client.post(
            "/api/v1/drone/commands",
            json=command,
            headers=_prepared_launch_headers(api_server, command),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["mission_type"] == 10

        mock_drone_communicator.process_command.assert_called_once()
        call_args = mock_drone_communicator.process_command.call_args[0][0]
        assert call_args["mission_type"] == 10
        assert call_args["trigger_time"] == 0
        assert call_args["takeoff_altitude"] == 12.0

    def test_ground_test_requires_typed_safety_acknowledgement(
        self,
        test_client,
        mock_drone_communicator,
    ):
        response = test_client.post(
            "/api/v1/drone/commands",
            json={"mission_type": Mission.TEST.value, "trigger_time": 0},
        )

        assert response.status_code == 422
        assert "ground_test_safety acknowledgement is required" in response.text
        mock_drone_communicator.process_command.assert_not_called()

    def test_sitl_ground_test_accepts_only_explicit_not_applicable_mode(
        self,
        test_client,
        mock_drone_communicator,
    ):
        rejected = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.TEST.value,
                "trigger_time": 0,
                "ground_test_safety": {
                    "mode": "operator_acknowledged",
                    "props_removed": True,
                    "airframe_secured": True,
                    "area_clear": True,
                },
            },
        )
        accepted = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.TEST.value,
                "trigger_time": 0,
                "ground_test_safety": {"mode": "sitl_not_applicable"},
            },
        )

        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert "SITL Arm/Disarm Ground Test" in rejected.json()["error_detail"]
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "accepted"
        call_args = mock_drone_communicator.process_command.call_args[0][0]
        assert call_args["ground_test_safety"] == {"mode": "sitl_not_applicable"}

    def test_real_ground_test_accepts_only_complete_operator_acknowledgement(
        self,
        test_client,
        api_server,
        mock_drone_communicator,
    ):
        api_server.params.sim_mode = False
        rejected = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.TEST.value,
                "trigger_time": 0,
                "ground_test_safety": {"mode": "sitl_not_applicable"},
            },
        )
        accepted = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.TEST.value,
                "trigger_time": 0,
                "ground_test_safety": {
                    "mode": "operator_acknowledged",
                    "props_removed": True,
                    "airframe_secured": True,
                    "area_clear": True,
                },
            },
        )

        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert "Real-aircraft Arm/Disarm Ground Test" in rejected.json()["error_detail"]
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "accepted"
        call_args = mock_drone_communicator.process_command.call_args[0][0]
        assert call_args["ground_test_safety"] == {
            "mode": "operator_acknowledged",
            "props_removed": True,
            "airframe_secured": True,
            "area_clear": True,
        }

    def test_send_precision_move_command_success(self, test_client, mock_drone_communicator, mock_drone_config):
        _set_fresh_airborne_state(mock_drone_config)
        response = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": "PRECISION_MOVE",
                "trigger_time": 0,
                "precision_move": {
                    "frame": "body",
                    "translation_m": {"forward": 1.0, "up": 0.5},
                    "yaw": {"mode": "relative_delta", "degrees": 15.0},
                    "speed_m_s": 1.0,
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["mission_type"] == Mission.PRECISION_MOVE.value

        mock_drone_communicator.process_command.assert_called_once()
        call_args = mock_drone_communicator.process_command.call_args[0][0]
        assert call_args["precision_move"]["frame"] == "body"

    def test_send_precision_move_requires_zero_trigger(self, test_client, mock_drone_communicator):
        response = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.PRECISION_MOVE.value,
                "trigger_time": 5,
                "precision_move": {
                    "frame": "body",
                    "translation_m": {"forward": 1.0},
                },
            },
        )

        assert response.status_code == 422
        mock_drone_communicator.process_command.assert_not_called()

    @pytest.mark.parametrize("mission_type", [Mission.HOLD.value, Mission.PRECISION_MOVE.value])
    def test_airborne_commands_reject_stale_armed_heartbeat_before_install(
        self,
        test_client,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
        mission_type,
    ):
        now_ms = time.time_ns() // 1_000_000
        mock_drone_config.is_armed = True
        mock_drone_config.heartbeat_timestamp_ms = now_ms - 16_000
        mock_drone_config.global_position_timestamp_ms = now_ms
        mock_drone_config.relative_altitude_m = 5.0
        command = {"mission_type": mission_type, "trigger_time": 0}
        if mission_type == Mission.PRECISION_MOVE.value:
            command["precision_move"] = {
                "frame": "body",
                "translation_m": {"forward": 1.0},
            }

        response = test_client.post("/api/v1/drone/commands", json=command)

        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
        assert "heartbeat/arming evidence is stale" in response.json()["error_detail"]
        mock_drone_communicator.process_command.assert_not_called()

    def test_hold_rejects_stale_relative_altitude_even_with_fresh_armed_heartbeat(
        self,
        test_client,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
    ):
        now_ms = time.time_ns() // 1_000_000
        mock_drone_config.is_armed = True
        mock_drone_config.heartbeat_timestamp_ms = now_ms
        mock_drone_config.global_position_timestamp_ms = now_ms - 16_000
        mock_drone_config.relative_altitude_m = 5.0
        mock_drone_config.px4_home_position_set = True

        response = test_client.post(
            "/api/v1/drone/commands",
            json={"mission_type": Mission.HOLD.value, "trigger_time": 0},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
        assert "altitude evidence is stale" in response.json()["error_detail"]
        mock_drone_communicator.process_command.assert_not_called()

    def test_hold_rejects_raw_relative_altitude_when_px4_home_is_not_set(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
    ):
        _set_fresh_airborne_state(mock_drone_config, relative_altitude_m=60.0)
        mock_drone_config.px4_home_position_set = False

        response = test_client.post(
            "/api/v1/drone/commands",
            json={"mission_type": Mission.HOLD.value, "trigger_time": 0},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
        assert "home position is not established" in response.json()["error_detail"]
        mock_drone_communicator.process_command.assert_not_called()

    def test_hold_rejects_armed_ground_state_before_install(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
    ):
        _set_fresh_airborne_state(mock_drone_config, relative_altitude_m=0.1)

        response = test_client.post(
            "/api/v1/drone/commands",
            json={"mission_type": Mission.HOLD.value, "trigger_time": 0},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
        assert "airborne admission requires" in response.json()["error_detail"]
        mock_drone_communicator.process_command.assert_not_called()

    def test_hold_accepts_only_fresh_cached_airborne_evidence_then_action_rechecks(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
    ):
        _set_fresh_airborne_state(mock_drone_config, relative_altitude_m=4.0)

        response = test_client.post(
            "/api/v1/drone/commands",
            json={"mission_type": Mission.HOLD.value, "trigger_time": 0},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "accepted"
        mock_drone_communicator.process_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_report_pending_command_superseded_uses_canonical_execution_result_route(self, api_server, monkeypatch):
        captured = {}

        class DummyResponse:
            status_code = 200

        def fake_post(url, json, timeout, **kwargs):
            captured['url'] = url
            captured['json'] = json
            captured['timeout'] = timeout
            captured['headers'] = kwargs.get('headers')
            return DummyResponse()

        monkeypatch.setattr("src.drone_api_server.requests.post", fake_post)
        api_server.drone_config.drone_setup = None

        await api_server._report_pending_command_superseded("cmd-123", 10)

        assert captured['url'] == "http://172.18.0.1:5030/api/v1/command-reports/execution-result"
        assert captured['json']['command_id'] == "cmd-123"
        assert captured['json']['success'] is False
        assert captured['json']['outcome'] == "superseded"
        assert captured['timeout'] == 5
        assert captured['headers'] == {}

    def test_get_origin_from_gcs_uses_canonical_bootstrap_route(self, api_server, monkeypatch):
        captured = {}

        class DummyResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"lat": 35.0, "lon": 51.0, "alt": 1200.0}

        def fake_get(url, timeout, **kwargs):
            captured['url'] = url
            captured['timeout'] = timeout
            captured['headers'] = kwargs.get('headers')
            return DummyResponse()

        monkeypatch.setattr("src.drone_api_server.requests.get", fake_get)

        origin = api_server._get_origin_from_gcs()

        assert captured['url'] == "http://172.18.0.1:5030/api/v1/origin/bootstrap"
        assert captured['timeout'] == 5
        assert captured['headers'] == {}
        assert origin == {'lat': 35.0, 'lon': 51.0}

    def test_get_origin_from_gcs_origin_not_set_logs_once(self, api_server, monkeypatch, caplog):
        from src.drone_api_server import DroneAPIServer

        DroneAPIServer._origin_fetch_error_logged = False
        DroneAPIServer._origin_fetch_last_issue = None

        class DummyResponse:
            status_code = 404
            text = ""

            @staticmethod
            def json():
                return {"detail": "Origin not set. Use dashboard to set origin."}

        def fake_get(url, timeout, **kwargs):
            return DummyResponse()

        monkeypatch.setattr("src.drone_api_server.requests.get", fake_get)

        with caplog.at_level(logging.INFO):
            assert api_server._get_origin_from_gcs() is None
            assert api_server._get_origin_from_gcs() is None

        messages = [record.message for record in caplog.records]
        assert messages.count(
            "GCS origin is not set yet; pos_id auto-detection will wait for dashboard origin."
        ) == 1
        assert all("GCS responded with status code" not in message for message in messages)

    def test_send_command_different_mission_types(
        self,
        test_client,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
    ):
        """Test different mission types with new response format"""
        # Use valid mission type codes that exist in the Mission enum
        mission_types = [10, 101, 102, 104, 105]  # TAKE_OFF, LAND, HOLD, RETURN_RTL, KILL_TERMINATE
        # HOLD is a flight-mode command and correctly requires an airborne vehicle.
        _set_fresh_airborne_state(mock_drone_config)

        for mission_type in mission_types:
            mock_drone_communicator.process_command.reset_mock()
            command = {"mission_type": mission_type, "trigger_time": 0}
            headers = None
            if mission_type == Mission.TAKE_OFF.value:
                command.update(
                    {
                        "command_id": "mission-types-takeoff",
                        "target_hw_id": "1",
                        "command_report_capability": "cap-" + ("x" * 39),
                    }
                )
                headers = _prepared_launch_headers(api_server, command)
            response = test_client.post(
                "/api/v1/drone/commands",
                json=command,
                headers=headers,
            )

            assert response.status_code == 200
            data = response.json()
            # New format returns 'accepted' status
            assert data['status'] == 'accepted'
            assert data['mission_type'] == mission_type

    def test_send_command_duplicate_delivery_returns_idempotent_ack(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
    ):
        mock_drone_config.state = 1
        mock_drone_config.mission = Mission.TEST_LED.value
        mock_drone_config.trigger_time = 12345
        mock_drone_config.current_command_id = "cmd-123"

        response = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.TEST_LED.value,
                "trigger_time": 12345,
                "command_id": "cmd-123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert "idempotent ACK" in data["message"]
        mock_drone_communicator.process_command.assert_not_called()

    def test_send_command_duplicate_delivery_after_completion_returns_idempotent_ack(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
    ):
        mock_drone_config.state = 0
        mock_drone_config.mission = 0
        mock_drone_config.trigger_time = 0
        mock_drone_config.current_command_id = None
        mock_drone_config.drone_setup = Mock(
            running_processes={},
            get_recent_command_record=Mock(return_value={
                "mission_type": Mission.TEST_LED.value,
                "trigger_time": 0,
                "state": 0,
                "phase": "completed",
            }),
        )

        response = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.TEST_LED.value,
                "trigger_time": 0,
                "command_id": "cmd-123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert "already completed" in data["message"]
        mock_drone_communicator.process_command.assert_not_called()

    def test_same_command_id_and_normalized_semantic_payload_replays_without_execution(
        self,
        test_client,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
    ):
        def install(command_data):
            return _commit_mock_command(mock_drone_config, command_data)

        mock_drone_communicator.process_command.side_effect = install

        original = {
            "mission_type": "TAKE_OFF",
            "trigger_time": 0,
            "takeoff_altitude": 12,
            "command_id": "cmd-semantic-replay",
            "target_hw_id": "1",
            "command_report_capability": "cap-" + ("x" * 39),
        }
        first = test_client.post(
            "/api/v1/drone/commands",
            json=original,
            headers=_prepared_launch_headers(api_server, original),
        )
        replay = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": 10,
                "trigger_time": 0,
                "takeoff_altitude": 12.0,
                "command_id": "cmd-semantic-replay",
                "target_hw_id": "1",
                "command_report_capability": "cap-" + ("x" * 39),
            },
        )

        assert first.status_code == 200
        assert replay.status_code == 200
        assert replay.json()["status"] == "accepted"
        assert replay.json()["replayed"] is True
        assert replay.json()["command_phase"] == "pending_execution"
        mock_drone_communicator.process_command.assert_called_once()

    def test_command_id_semantic_mismatch_is_rejected_before_second_mutation(
        self,
        test_client,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
    ):
        def install(command_data):
            return _commit_mock_command(mock_drone_config, command_data)

        mock_drone_communicator.process_command.side_effect = install
        original = {
            "mission_type": 10,
            "trigger_time": 0,
            "takeoff_altitude": 10,
            "command_id": "cmd-semantic-conflict",
            "target_hw_id": "1",
            "command_report_capability": "cap-" + ("x" * 39),
        }

        first = test_client.post(
            "/api/v1/drone/commands",
            json=original,
            headers=_prepared_launch_headers(api_server, original),
        )
        conflicting = test_client.post(
            "/api/v1/drone/commands",
            json={**original, "takeoff_altitude": 20},
        )

        assert first.status_code == 200
        assert conflicting.status_code == 200
        data = conflicting.json()
        assert data["status"] == "rejected"
        assert data["error_code"] == "E109"
        assert "takeoff_altitude" in data["error_detail"]
        assert mock_drone_config.current_command_id == "cmd-semantic-conflict"
        mock_drone_communicator.process_command.assert_called_once()

    def test_terminal_command_replay_preserves_outcome_without_reexecution(
        self,
        test_client,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
    ):
        def install(command_data):
            return _commit_mock_command(mock_drone_config, command_data)

        mock_drone_communicator.process_command.side_effect = install
        command = {
            "mission_type": 10,
            "trigger_time": 0,
            "takeoff_altitude": 10,
            "command_id": "cmd-terminal-replay",
            "target_hw_id": "1",
            "command_report_capability": "cap-" + ("x" * 39),
        }
        first = test_client.post(
            "/api/v1/drone/commands",
            json=command,
            headers=_prepared_launch_headers(api_server, command),
        )
        assert first.status_code == 200

        mock_drone_config.current_command_id = None
        mock_drone_config.mission = Mission.NONE.value
        mock_drone_config.state = 0
        mock_drone_config.drone_setup = type(
            "TerminalHistory",
            (),
            {
                "running_processes": {},
                "get_recent_command_record": staticmethod(
                    lambda _command_id: {
                        "mission_type": Mission.TAKE_OFF.value,
                        "trigger_time": 0,
                        "state": 0,
                        "phase": "completed",
                    }
                ),
            },
        )()

        replay = test_client.post("/api/v1/drone/commands", json=command)

        assert replay.status_code == 200
        data = replay.json()
        assert data["status"] == "accepted"
        assert data["replayed"] is True
        assert data["command_phase"] == "terminal"
        assert data["command_outcome"] == "completed"
        assert "already completed" in data["message"]
        mock_drone_communicator.process_command.assert_called_once()

    def test_rejected_command_replay_is_stable_after_state_changes(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
    ):
        command = {
            "mission_type": Mission.HOLD.value,
            "trigger_time": 0,
            "command_id": "cmd-rejected-replay",
        }

        first = test_client.post("/api/v1/drone/commands", json=command)
        mock_drone_config.is_armed = True
        replay = test_client.post("/api/v1/drone/commands", json=command)

        assert first.json()["status"] == "rejected"
        assert replay.json()["status"] == "rejected"
        assert replay.json()["replayed"] is True
        assert replay.json()["command_outcome"] == "rejected"
        mock_drone_communicator.process_command.assert_not_called()

    def test_send_command_does_not_supersede_pending_command_when_install_fails(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
        monkeypatch,
    ):
        mock_drone_config.state = 1
        mock_drone_config.mission = 10
        mock_drone_config.current_command_id = "old-cmd"
        mock_drone_communicator.process_command.side_effect = ValueError("install failed")

        from src.drone_api_server import DroneAPIServer

        supersede_report = AsyncMock()
        monkeypatch.setattr(DroneAPIServer, "_report_pending_command_superseded", supersede_report)

        response = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.LAND.value,
                "trigger_time": 0,
                "command_id": "new-cmd",
            },
        )

        assert response.status_code == 503
        data = response.json()["detail"]
        assert data["status"] == "delivery_unknown"
        assert data["command_phase"] == "outcome_unknown"
        assert mock_drone_config.current_command_id == "old-cmd"
        supersede_report.assert_not_awaited()

        retry = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.LAND.value,
                "trigger_time": 0,
                "command_id": "new-cmd",
            },
        )
        assert retry.status_code == 503
        assert retry.json()["detail"]["replayed"] is True
        mock_drone_communicator.process_command.assert_called_once()

    def test_verified_transaction_rollback_is_a_stable_definite_rejection(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
    ):
        mock_drone_config.state = State.MISSION_READY.value
        mock_drone_config.mission = Mission.TAKE_OFF.value
        mock_drone_config.current_command_id = "old-command"
        mock_drone_communicator.process_command.side_effect = CommandInstallationRejected(
            "injected config commit fault; prior command restored",
            phase="config_commit",
        )
        command = {
            "mission_type": Mission.LAND.value,
            "trigger_time": 0,
            "command_id": "rollback-command",
        }

        first = test_client.post("/api/v1/drone/commands", json=command)
        replay = test_client.post("/api/v1/drone/commands", json=command)

        assert first.status_code == 200
        assert first.json()["status"] == "rejected"
        assert first.json()["command_outcome"] == "rejected"
        assert "config_commit" in first.json()["error_detail"]
        assert mock_drone_config.current_command_id == "old-command"
        assert replay.status_code == 200
        assert replay.json()["status"] == "rejected"
        assert replay.json()["replayed"] is True
        mock_drone_communicator.process_command.assert_called_once()

    def test_send_command_binds_command_id_at_commit_under_scheduler_transaction(
        self,
        test_client,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
    ):
        observed = {}

        def _install(command_data):
            observed["current_command_id_during_install"] = mock_drone_config.current_command_id
            return _commit_mock_command(mock_drone_config, command_data)

        mock_drone_communicator.process_command.side_effect = _install

        command = {
            "mission_type": Mission.TAKE_OFF.value,
            "trigger_time": 0,
            "command_id": "cmd-race",
            "target_hw_id": "1",
            "command_report_capability": "cap-" + ("x" * 39),
        }
        response = test_client.post(
            "/api/v1/drone/commands",
            json=command,
            headers=_prepared_launch_headers(api_server, command),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert observed["current_command_id_during_install"] is None
        assert mock_drone_config.current_command_id == "cmd-race"

    def test_send_command_clears_staged_command_id_when_install_fails_without_previous_pending_command(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
    ):
        mock_drone_config.state = 0
        mock_drone_config.mission = 0
        mock_drone_config.current_command_id = None
        mock_drone_communicator.process_command.side_effect = ValueError("install failed")

        response = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.TEST_LED.value,
                "trigger_time": 0,
                "command_id": "new-cmd",
            },
        )

        assert response.status_code == 503
        data = response.json()["detail"]
        assert data["status"] == "delivery_unknown"
        assert mock_drone_config.current_command_id is None

        retry = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.TEST_LED.value,
                "trigger_time": 0,
                "command_id": "new-cmd",
            },
        )
        assert retry.status_code == 503
        mock_drone_communicator.process_command.assert_called_once()

    def test_fault_after_core_state_mutation_binds_uncertain_command_and_never_reexecutes(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
    ):
        def mutate_then_fail(command_data):
            mock_drone_config.mission = command_data["mission_type"]
            mock_drone_config.trigger_time = command_data["trigger_time"]
            mock_drone_config.state = 1
            raise RuntimeError("fault after mission state install")

        mock_drone_communicator.process_command.side_effect = mutate_then_fail
        command = {
            "mission_type": Mission.TEST_LED.value,
            "trigger_time": 0,
            "command_id": "cmd-post-mutation",
        }

        first = test_client.post("/api/v1/drone/commands", json=command)
        replay = test_client.post("/api/v1/drone/commands", json=command)

        assert first.status_code == 503
        assert first.json()["detail"]["status"] == "delivery_unknown"
        assert mock_drone_config.current_command_id == "cmd-post-mutation"
        assert replay.status_code == 503
        assert replay.json()["detail"]["command_outcome"] == "unknown"
        assert replay.json()["detail"]["replayed"] is True
        mock_drone_communicator.process_command.assert_called_once()

        mock_drone_config.current_command_id = None
        mock_drone_config.mission = Mission.NONE.value
        mock_drone_config.state = 0
        mock_drone_config.drone_setup = type(
            "ReconciledHistory",
            (),
            {
                "running_processes": {},
                "get_recent_command_record": staticmethod(
                    lambda _command_id: {
                        "mission_type": Mission.TEST_LED.value,
                        "trigger_time": 0,
                        "state": 0,
                        "phase": "completed",
                    }
                ),
            },
        )()
        reconciled = test_client.post("/api/v1/drone/commands", json=command)

        assert reconciled.status_code == 200
        assert reconciled.json()["status"] == "accepted"
        assert reconciled.json()["command_phase"] == "terminal"
        assert reconciled.json()["command_outcome"] == "completed"
        mock_drone_communicator.process_command.assert_called_once()

    def test_post_commit_reporting_fault_preserves_definite_acceptance(
        self,
        test_client,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
        monkeypatch,
    ):
        mock_drone_config.state = 1
        mock_drone_config.mission = Mission.TAKE_OFF.value
        mock_drone_config.current_command_id = "old-command"

        def install(command_data):
            return _commit_mock_command(mock_drone_config, command_data)

        async def fail_report(*_args, **_kwargs):
            raise RuntimeError("report transport failed")

        mock_drone_communicator.process_command.side_effect = install
        monkeypatch.setattr(api_server, "_report_pending_command_superseded", fail_report)
        command = {
            "mission_type": Mission.LAND.value,
            "trigger_time": 0,
            "command_id": "cmd-committed",
        }

        response = test_client.post("/api/v1/drone/commands", json=command)
        replay = test_client.post("/api/v1/drone/commands", json=command)

        assert response.status_code == 200
        assert response.json()["status"] == "accepted"
        assert mock_drone_config.current_command_id == "cmd-committed"
        assert replay.status_code == 200
        assert replay.json()["status"] == "accepted"
        assert replay.json()["replayed"] is True
        mock_drone_communicator.process_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_slow_supersede_callback_does_not_hold_transaction_or_delay_cancel(
        self,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
        monkeypatch,
    ):
        report_started = asyncio.Event()
        release_report = asyncio.Event()

        async def slow_report(*_args, **_kwargs):
            report_started.set()
            await release_report.wait()

        async def cancel_active_command(_message):
            mock_drone_config.mission = Mission.NONE.value
            mock_drone_config.trigger_time = 0
            mock_drone_config.state = 0
            mock_drone_config.current_command_id = None
            return True, "cancelled"

        def install(command_data):
            return _commit_mock_command(mock_drone_config, command_data)

        mock_drone_config.state = 1
        mock_drone_config.mission = Mission.TAKE_OFF.value
        mock_drone_config.current_command_id = "old-pending"
        mock_drone_config.drone_setup = type(
            "CancelableSetup",
            (),
            {"cancel_active_command": staticmethod(cancel_active_command)},
        )()
        mock_drone_communicator.process_command.side_effect = install
        monkeypatch.setattr(api_server, "_report_pending_command_superseded", slow_report)

        transport = httpx.ASGITransport(app=api_server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            land = await client.post(
                "/api/v1/drone/commands",
                json={"mission_type": 101, "trigger_time": 0, "command_id": "land-first"},
            )
            await asyncio.wait_for(report_started.wait(), timeout=1)
            cancel = await asyncio.wait_for(
                client.post(
                    "/api/v1/drone/commands",
                    json={"mission_type": 0, "trigger_time": 0, "command_id": "cancel-second"},
                ),
                timeout=0.5,
            )

        release_report.set()
        await asyncio.gather(*tuple(api_server._command_followup_tasks), return_exceptions=True)

        assert land.json()["status"] == "accepted"
        assert cancel.json()["status"] == "accepted"
        assert mock_drone_config.state == 0

    def test_idempotency_registry_uses_bounded_terminal_lru_history(
        self,
        test_client,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
    ):
        api_server._command_idempotency_max_records = 32

        def install(command_data):
            return _commit_mock_command(mock_drone_config, command_data)

        mock_drone_communicator.process_command.side_effect = install

        for index in range(40):
            response = test_client.post(
                "/api/v1/drone/commands",
                json={
                    "mission_type": Mission.TEST_LED.value,
                    "trigger_time": 0,
                    "command_id": f"bounded-{index}",
                },
            )
            assert response.status_code == 200
            mock_drone_config.current_command_id = None
            mock_drone_config.mission = Mission.NONE.value
            mock_drone_config.state = 0

        assert len(api_server._command_idempotency_records) == 32
        assert "bounded-0" not in api_server._command_idempotency_records
        assert "bounded-39" in api_server._command_idempotency_records

    def test_idempotency_registry_rejects_at_protected_capacity_instead_of_evicting_active_ids(
        self,
        test_client,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
    ):
        api_server._command_idempotency_max_records = 32
        running_processes = {}
        mock_drone_config.drone_setup = type(
            "ActiveHistory",
            (),
            {
                "running_processes": running_processes,
                "get_recent_command_record": staticmethod(lambda _command_id: None),
            },
        )()

        def install(command_data):
            return _commit_mock_command(mock_drone_config, command_data)

        mock_drone_communicator.process_command.side_effect = install

        for index in range(32):
            command_id = f"protected-{index}"
            response = test_client.post(
                "/api/v1/drone/commands",
                json={
                    "mission_type": Mission.TEST_LED.value,
                    "trigger_time": 0,
                    "command_id": command_id,
                },
            )
            assert response.json()["status"] == "accepted"
            running_processes[command_id] = type(
                "ProcessRecord",
                (),
                {
                    "command_id": command_id,
                    "mission_type": Mission.TEST_LED.value,
                    "trigger_time": 0,
                },
            )()
            mock_drone_config.current_command_id = None
            mock_drone_config.mission = Mission.NONE.value
            mock_drone_config.state = 0

        overflow = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.TEST_LED.value,
                "trigger_time": 0,
                "command_id": "protected-overflow",
            },
        )

        assert overflow.status_code == 200
        assert overflow.json()["status"] == "rejected"
        assert "protected capacity" in overflow.json()["message"]
        assert len(api_server._command_idempotency_records) == 32
        assert "protected-0" in api_server._command_idempotency_records
        assert "protected-overflow" not in api_server._command_idempotency_records
        assert mock_drone_communicator.process_command.call_count == 32

    @pytest.mark.asyncio
    async def test_concurrent_cancel_takeoff_and_land_are_serialized_without_torn_state(
        self,
        api_server,
        mock_drone_config,
        mock_drone_communicator,
        monkeypatch,
    ):
        cancel_started = asyncio.Event()
        allow_cancel_to_finish = asyncio.Event()
        operation_order = []

        async def cancel_active_command(_message):
            operation_order.append("cancel-start")
            cancel_started.set()
            await allow_cancel_to_finish.wait()
            mock_drone_config.mission = Mission.NONE.value
            mock_drone_config.trigger_time = 0
            mock_drone_config.state = 0
            mock_drone_config.current_command_id = None
            operation_order.append("cancel-end")
            return True, "cancelled"

        def install(command_data):
            operation_order.append(f"install-{command_data['mission_type']}")
            return _commit_mock_command(mock_drone_config, command_data)

        mock_drone_config.state = 2
        mock_drone_config.mission = Mission.HOVER_TEST.value
        mock_drone_config.current_command_id = "running-old"
        mock_drone_config.drone_setup = type(
            "CancelableSetup",
            (),
            {"cancel_active_command": staticmethod(cancel_active_command)},
        )()
        mock_drone_communicator.process_command.side_effect = install
        monkeypatch.setattr(
            api_server,
            "_report_pending_command_superseded",
            AsyncMock(),
        )
        takeoff_command = {
            "mission_type": Mission.TAKE_OFF.value,
            "trigger_time": 0,
            "command_id": "takeoff-new",
            "target_hw_id": "1",
            "command_report_capability": "cap-" + ("x" * 39),
        }
        takeoff_headers = _prepared_launch_headers(api_server, takeoff_command)

        transport = httpx.ASGITransport(app=api_server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            cancel_task = asyncio.create_task(
                client.post(
                    "/api/v1/drone/commands",
                    json={"mission_type": 0, "trigger_time": 0, "command_id": "cancel-new"},
                )
            )
            await asyncio.wait_for(cancel_started.wait(), timeout=1)
            takeoff_task = asyncio.create_task(
                client.post(
                    "/api/v1/drone/commands",
                    json=takeoff_command,
                    headers=takeoff_headers,
                )
            )
            await asyncio.sleep(0)
            land_task = asyncio.create_task(
                client.post(
                    "/api/v1/drone/commands",
                    json={"mission_type": 101, "trigger_time": 0, "command_id": "land-new"},
                )
            )
            await asyncio.sleep(0.02)
            assert mock_drone_communicator.process_command.call_count == 0

            allow_cancel_to_finish.set()
            responses = await asyncio.gather(cancel_task, takeoff_task, land_task)

        assert [response.json()["status"] for response in responses] == [
            "accepted",
            "accepted",
            "accepted",
        ]
        assert operation_order == ["cancel-start", "cancel-end", "install-10", "install-101"]
        assert mock_drone_config.mission == Mission.LAND.value
        assert mock_drone_config.current_command_id == "land-new"

    @pytest.mark.asyncio
    async def test_cancelled_cross_thread_lock_waiter_does_not_orphan_scheduler_lock(
        self,
        api_server,
    ):
        shared_lock = api_server._command_state_transaction_lock
        assert shared_lock.acquire(blocking=False)
        guard = api_server._command_transaction_guard()
        waiter = asyncio.create_task(guard.__anext__())
        try:
            await asyncio.sleep(0.02)
            waiter.cancel()
            shared_lock.release()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert shared_lock.acquire(blocking=False)
            shared_lock.release()
        finally:
            if shared_lock.locked():
                shared_lock.release()
            await guard.aclose()

    def test_cancel_command_clears_active_mission_without_process_launch(
        self,
        test_client,
        mock_drone_config,
        mock_drone_communicator,
    ):
        cancel_helper = AsyncMock(return_value=(True, "Cancel command accepted; active mission cleared."))
        mock_drone_config.drone_setup = Mock(cancel_active_command=cancel_helper)
        mock_drone_config.state = 2
        mock_drone_config.mission = 4
        mock_drone_config.current_command_id = None

        response = test_client.post(
            "/api/v1/drone/commands",
            json={"mission_type": 0, "trigger_time": 0, "command_id": "cancel-1"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["new_state"] == 0
        cancel_helper.assert_awaited_once()
        mock_drone_communicator.process_command.assert_not_called()


class TestPositionData:
    """Test position-related endpoints"""

    def test_get_home_position(self, test_client, mock_drone_config):
        """Test canonical home-position endpoint"""
        response = test_client.get("/api/v1/navigation/home")

        assert response.status_code == 200
        data = response.json()

        assert 'latitude' in data
        assert 'longitude' in data
        assert 'altitude' in data
        assert 'timestamp' in data

        assert data['latitude'] == 47.397742
        assert data['longitude'] == 8.545594

    def test_get_gps_global_origin(self, test_client, mock_drone_config):
        """Test canonical GPS global-origin endpoint"""
        response = test_client.get("/api/v1/navigation/global-origin")

        assert response.status_code == 200
        data = response.json()

        assert 'latitude' in data
        assert 'longitude' in data
        assert 'altitude' in data
        assert 'origin_time_usec' in data
        assert 'timestamp' in data

    def test_get_local_position_ned(self, test_client, mock_drone_config):
        """Test canonical LOCAL_POSITION_NED endpoint"""
        response = test_client.get("/api/v1/telemetry/local-position")

        assert response.status_code == 200
        data = response.json()

        assert 'time_boot_ms' in data
        assert 'x' in data
        assert 'y' in data
        assert 'z' in data
        assert 'vx' in data
        assert 'vy' in data
        assert 'vz' in data
        assert 'timestamp' in data

        # Verify NED coordinates
        assert data['x'] == 0.5
        assert data['y'] == -0.3
        assert data['z'] == -5.2

    def test_get_local_position_ned_no_data(self, test_client, mock_drone_config):
        """Test canonical LOCAL_POSITION_NED endpoint when no data available"""
        # Set time_boot_ms to 0 (indicates no data)
        mock_drone_config.local_position_ned['time_boot_ms'] = 0

        response = test_client.get("/api/v1/telemetry/local-position")

        assert response.status_code == 404
        assert 'NED data not available' in response.json()['detail']


class TestGitStatus:
    """Test git status endpoint"""

    def test_get_git_status(self, test_client, api_server, monkeypatch):
        """Test canonical drone git-status endpoint"""
        from src import drone_api_server
        monkeypatch.setattr(
            drone_api_server,
            'get_local_git_report',
            lambda repo_path=None: {
                'branch': 'main-candidate',
                'commit': 'abc123def456',
                'author_name': 'Test User',
                'author_email': 'test@example.com',
                'commit_date': '2025-11-22T10:00:00+00:00',
                'commit_message': 'test commit',
                'remote_url': 'git@github.com:test/repo.git',
                'tracking_branch': 'origin/main-candidate',
                'status': 'clean',
                'uncommitted_changes': [],
                'commits_ahead': 0,
                'commits_behind': 0,
                'repo_access_mode': 'https_token_file',
                'git_auth_health_status': 'healthy',
                'git_auth_health_summary': 'HTTPS token-file access is configured and readable for node sync.',
                'git_auth_health_issues': [],
            },
        )
        monkeypatch.setattr(
            drone_api_server,
            'build_mavlink_runtime_summary',
            lambda repo_root: {
                'status_source': 'script',
                'management_mode': 'fleet-merge',
                'repo_url': 'https://github.com/demo/mavlink-anywhere.git',
                'ref': 'v3.0.10',
                'repo_web_url': 'https://github.com/demo/mavlink-anywhere/tree/v3.0.10',
                'install_dir': '/opt/mavlink-anywhere',
                'install_dir_present': True,
                'runtime_present': True,
                'runtime_head': 'abc1234',
                'router_binary_present': True,
                'router_service_status': 'active',
                'dashboard_enabled': True,
                'dashboard_listen': '0.0.0.0:9070',
                'dashboard_service_status': 'active',
            },
        )
        monkeypatch.setattr(
            drone_api_server,
            'build_connectivity_runtime_summary',
            lambda repo_root: {
                'status_source': 'script',
                'backend': 'smart-wifi-manager',
                'repo_url': 'https://github.com/demo/smart-wifi-manager.git',
                'ref': 'v2.1.11',
                'repo_web_url': 'https://github.com/demo/smart-wifi-manager/tree/v2.1.11',
                'install_dir': '/opt/smart-wifi-manager',
                'install_dir_present': True,
                'mode': 'observe',
                'import_mode': 'replace',
                'profile_path': '/etc/smart-wifi-manager/config.json',
                'profile_present': True,
                'dashboard_listen': '127.0.0.1:9080',
                'service_status': 'active',
            },
        )
        monkeypatch.setattr(
            drone_api_server,
            'read_git_sync_runtime_summary',
            lambda: {
                'status': 'success',
                'summary': 'Git synchronization completed successfully · Coordinator restart scheduled',
                'last_run_at_ms': 1770000000000,
                'updated_units': ['coordinator.service'],
                'service_reload_status': 'updated',
                'service_reload_message': 'Systemd unit updates were applied successfully.',
                'deferred_unit_actions': ['git_sync_mds.service:next_invocation'],
                'coordinator_restart_scheduled': True,
                'connectivity_reconcile_status': 'success',
                'mavlink_runtime_reconcile_status': 'success',
                'mavsdk_runtime_status': 'provisioned',
                'requirements_update_status': 'unchanged',
            },
        )
        monkeypatch.setattr(
            drone_api_server,
            'build_node_env_summary_safe',
            lambda: {
                'status_source': 'registry',
                'registry_version': 1,
                'registry_hash': 'abc123',
                'local_env_path': '/etc/mds/local.env',
                'local_env_present': True,
                'node_identity_path': '/etc/mds/node_identity.json',
                'node_identity_present': True,
                'runtime_mode': 'real',
                'runtime_mode_source': 'env:MDS_MODE',
                'hw_id': 1,
                'hw_id_source': 'env:MDS_HW_ID',
                'configured_key_count': 7,
                'configured_node_key_count': 5,
                'registered_node_key_count': 20,
                'unknown_keys': [],
                'deprecated_keys': [],
                'warnings': [],
            },
        )
        response = test_client.get("/api/v1/git/status")

        assert response.status_code == 200
        data = response.json()

        assert data['hw_id'] == str(api_server.drone_config.hw_id)
        assert 'branch' in data
        assert 'commit' in data
        assert 'status' in data
        assert data['status'] == 'clean'
        assert data['repo_access_mode'] == 'https_token_file'
        assert data['git_auth_health_status'] == 'healthy'
        assert data['mavlink_runtime']['router_service_status'] == 'active'
        assert data['mavlink_runtime']['tool'] == 'mavlink-anywhere'
        assert data['connectivity_runtime']['service_status'] == 'active'
        assert data['connectivity_runtime']['tool'] == 'smart-wifi-manager'
        assert data['git_sync_runtime']['service_reload_status'] == 'updated'
        assert data['git_sync_runtime']['mavsdk_runtime_status'] == 'provisioned'
        assert data['git_sync_runtime']['deferred_unit_actions'] == ['git_sync_mds.service:next_invocation']
        assert data['git_sync_runtime']['coordinator_restart_scheduled'] is True
        assert data['git_sync_runtime']['recovery_action'] == 'none'
        assert data['env_runtime']['registry_hash'] == 'abc123'
        assert data['env_runtime']['configured_node_key_count'] == 5

    def test_get_git_status_resolves_detached_head(self, test_client, monkeypatch):
        """Drone git status should expose a usable branch name from detached worktrees."""
        from src import drone_api_server
        monkeypatch.setattr(
            drone_api_server,
            'get_local_git_report',
            lambda repo_path=None: {
                'branch': 'main-candidate',
                'commit': 'abc123def456',
                'author_name': 'Test User',
                'author_email': 'test@example.com',
                'commit_date': '2025-11-22T10:00:00+00:00',
                'commit_message': 'test commit',
                'remote_url': 'git@github.com:test/repo.git',
                'tracking_branch': '',
                'status': 'clean',
                'uncommitted_changes': [],
                'commits_ahead': 0,
                'commits_behind': 0,
            },
        )
        monkeypatch.setattr(drone_api_server, 'build_mavlink_runtime_summary', lambda repo_root: None)
        monkeypatch.setattr(drone_api_server, 'build_connectivity_runtime_summary', lambda repo_root: None)
        monkeypatch.setattr(drone_api_server, 'read_git_sync_runtime_summary', lambda: None)
        monkeypatch.setattr(drone_api_server, 'build_node_env_summary_safe', lambda: None)

        response = test_client.get("/api/v1/git/status")

        assert response.status_code == 200
        data = response.json()
        assert data['branch'] == 'main-candidate'

    def test_get_git_status_without_tracking_branch(self, test_client, monkeypatch):
        """Custom branches without an upstream should still return 200 and zero sync deltas."""
        from src import drone_api_server
        monkeypatch.setattr(
            drone_api_server,
            'get_local_git_report',
            lambda repo_path=None: {
                'branch': 'smart-swarm-runtime-phase1-20260415',
                'commit': 'eda03f00',
                'author_name': 'Test User',
                'author_email': 'test@example.com',
                'commit_date': '2026-04-16T10:00:00+00:00',
                'commit_message': 'Fix Smart Swarm leader reassignment runtime',
                'remote_url': 'git@github.com:test/repo.git',
                'tracking_branch': '',
                'status': 'clean',
                'uncommitted_changes': [],
                'commits_ahead': 0,
                'commits_behind': 0,
            },
        )
        monkeypatch.setattr(drone_api_server, 'build_mavlink_runtime_summary', lambda repo_root: None)
        monkeypatch.setattr(drone_api_server, 'build_connectivity_runtime_summary', lambda repo_root: None)
        monkeypatch.setattr(drone_api_server, 'read_git_sync_runtime_summary', lambda: None)
        monkeypatch.setattr(drone_api_server, 'build_node_env_summary_safe', lambda: None)

        response = test_client.get("/api/v1/git/status")

        assert response.status_code == 200
        data = response.json()
        assert data['branch'] == 'smart-swarm-runtime-phase1-20260415'
        assert data['tracking_branch'] == ''
        assert data['commits_ahead'] == 0
        assert data['commits_behind'] == 0


class TestNetworkStatus:
    """Test network status endpoint"""

    def test_get_network_status(self, test_client, monkeypatch):
        """Test canonical network-status endpoint"""
        # Mock network info method
        def mock_get_network_info(self):
            return {
                "wifi": {
                    "ssid": "TestNetwork",
                    "signal_strength_percent": 85
                },
                "ethernet": {
                    "interface": "eth0",
                    "connection_name": "Wired"
                },
                "timestamp": 1732270245000
            }

        from src.drone_api_server import DroneAPIServer
        monkeypatch.setattr(DroneAPIServer, '_get_network_info', mock_get_network_info)

        response = test_client.get("/api/v1/network/status")

        assert response.status_code == 200
        data = response.json()

        assert 'wifi' in data
        assert 'ethernet' in data
        assert 'timestamp' in data
        assert data['wifi']['ssid'] == 'TestNetwork'


class TestErrorHandling:
    """Test error handling"""

    def test_404_not_found(self, test_client):
        """Test non-existent endpoint returns 404"""
        response = test_client.get("/non-existent-endpoint")

        assert response.status_code == 404

    def test_invalid_command_data(self, test_client):
        """Test sending invalid command data"""
        response = test_client.post("/api/v1/drone/commands", json={})

        assert response.status_code == 422


class TestDroneRouteSurface:
    """Test the current canonical drone API surface."""

    def test_route_inventory_includes_canonical_core_surfaces(self, test_client):
        routes = {route.path for route in test_client.app.routes}

        expected_routes = {
            "/api/v1/drone/state",
            "/api/v1/preflight/armability",
            "/api/v1/drone/commands",
            "/api/v1/navigation/home",
            "/api/v1/navigation/global-origin",
            "/api/v1/git/status",
            "/ping",
            "/api/v1/navigation/position-deviation",
            "/api/v1/system/health",
            "/api/v1/network/status",
            "/api/v1/swarm/config",
            "/api/v1/telemetry/local-position",
            "/api/v1/px4-params/policy",
            "/api/v1/px4-params/snapshots/current",
            "/api/v1/px4-params/snapshots/refresh",
            "/api/v1/px4-params/patches/apply",
            "/api/v1/ulog/policy",
            "/api/v1/ulog/files",
            "/api/v1/ulog/files/{log_id}/download",
            "/api/v1/ulog/downloads/{job_id}",
            "/api/v1/ulog/downloads/{job_id}/content",
            "/api/v1/ulog/erase-all",
            "/ws/drone-state",
            "/api/logs/sessions",
            "/api/logs/sessions/{session_id}",
            "/api/logs/stream",
        }

        assert expected_routes.issubset(routes)

    def test_v1_health_success(self, test_client):
        response = test_client.get("/api/v1/system/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data
        assert "version" in data
        assert "ulog_capability" in data
        assert "mavsdk_server_present" in data["ulog_capability"]

    def test_v1_get_drone_state_success(self, test_client):
        response = test_client.get("/api/v1/drone/state")

        assert response.status_code == 200
        data = response.json()
        assert data["pos_id"] == 1
        assert "timestamp" in data
        assert "server_time" in data

    def test_v1_send_command_uses_canonical_contract(self, test_client):
        response = test_client.post(
            "/api/v1/drone/commands",
            json={
                "mission_type": Mission.TEST_LED.value,
                "trigger_time": 0,
                "command_id": "route-surface-command",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in {"accepted", "rejected"}
        assert "timestamp" in data

    def test_v1_live_armability(self, test_client, monkeypatch):
        from src.drone_api_server import DroneAPIServer

        async def _mock_probe(self, require_global_position=True):
            return {
                "hw_id": "1",
                "success": True,
                "ready": True,
                "summary": "ready for mission startup",
                "blockers": [],
                "armable": True,
                "global_position_ok": True,
                "home_position_ok": True,
                "local_position_ok": True,
                "gyro_ok": True,
                "accel_ok": True,
                "mag_ok": True,
                "observation": {
                    "schema_version": 1,
                    "observation_id": "health-test-route-1",
                    "source": "mavsdk_health",
                    "observed_at_ms": 100,
                    "valid_until_ms": 2_100,
                    "require_global_position": require_global_position,
                    "ready": True,
                    "blockers": [],
                },
                "remaining_valid_ms": 1_900,
                "server_processing_ms": 100,
                "timed_out": False,
                "elapsed_sec": 0.2,
                "require_global_position": require_global_position,
                "timestamp": 123,
                "probe_error": None,
            }

        monkeypatch.setattr(DroneAPIServer, "_probe_live_armability", _mock_probe)

        response = test_client.get("/api/v1/preflight/armability")

        assert response.status_code == 200
        assert response.json()["ready"] is True

    def test_v1_navigation_home(self, test_client):
        response = test_client.get("/api/v1/navigation/home")

        assert response.status_code == 200
        data = response.json()
        assert "latitude" in data
        assert "longitude" in data

    def test_v1_navigation_global_origin(self, test_client):
        response = test_client.get("/api/v1/navigation/global-origin")

        assert response.status_code == 200
        data = response.json()
        assert "latitude" in data
        assert "longitude" in data

    def test_v1_network_status(self, test_client, monkeypatch):
        def mock_get_network_info(self):
            return {
                "wifi": {
                    "ssid": "TestNetwork",
                    "signal_strength_percent": 85
                },
                "ethernet": {
                    "interface": "eth0",
                    "connection_name": "Wired"
                },
                "timestamp": 1732270245000
            }

        from src.drone_api_server import DroneAPIServer
        monkeypatch.setattr(DroneAPIServer, '_get_network_info', mock_get_network_info)

        response = test_client.get("/api/v1/network/status")

        assert response.status_code == 200
        assert response.json()["wifi"]["ssid"] == "TestNetwork"
