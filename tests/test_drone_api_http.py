# tests/test_drone_api_http.py
"""
HTTP REST Endpoint Tests
=========================
Tests for all HTTP REST endpoints in the Drone API Server.
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, Mock
from fastapi.testclient import TestClient
from src.enums import Mission


class TestHealthCheck:
    """Test health check endpoint"""

    def test_ping_success(self, test_client):
        """Test /ping endpoint returns ok"""
        response = test_client.get("/ping")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


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
        assert data["summary"] == "ready for mission startup"
        assert data["require_global_position"] is True

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
        assert result["timed_out"] is True
        assert "Timed out" in result["summary"]
        wait_mock.assert_not_awaited()

    def test_get_drone_state_no_data(self, test_client, mock_drone_communicator):
        """Test canonical drone-state endpoint when no data available"""
        mock_drone_communicator.get_drone_state.return_value = None

        response = test_client.get("/api/v1/drone/state")

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
        assert data["results"][0]["actual_value"] == 42


class TestCommands:
    """Test command endpoint"""

    def test_send_command_success(self, test_client, sample_command, mock_drone_communicator):
        """Test sending command to drone - new CommandAckResponse format"""
        response = test_client.post("/api/v1/drone/commands", json=sample_command)

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
        assert call_args['trigger_time'] == int(sample_command['triggerTime'])

    def test_send_command_accepts_snake_case_aliases(self, test_client, mock_drone_communicator):
        response = test_client.post(
            "/api/v1/drone/commands",
            json={"mission_type": "TAKE_OFF", "trigger_time": 0, "takeoff_altitude": 12},
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

    def test_send_precision_move_command_success(self, test_client, mock_drone_communicator, mock_drone_config):
        mock_drone_config.is_armed = True
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

    @pytest.mark.asyncio
    async def test_report_pending_command_superseded_uses_canonical_execution_result_route(self, api_server, monkeypatch):
        captured = {}

        class DummyResponse:
            status_code = 200

        def fake_post(url, json, timeout):
            captured['url'] = url
            captured['json'] = json
            captured['timeout'] = timeout
            return DummyResponse()

        monkeypatch.setattr("src.drone_api_server.requests.post", fake_post)
        api_server.drone_config.drone_setup = None

        await api_server._report_pending_command_superseded("cmd-123", 10)

        assert captured['url'] == "http://172.18.0.1:5000/api/v1/command-reports/execution-result"
        assert captured['json']['command_id'] == "cmd-123"
        assert captured['json']['success'] is False
        assert captured['timeout'] == 5

    def test_get_origin_from_gcs_uses_canonical_bootstrap_route(self, api_server, monkeypatch):
        captured = {}

        class DummyResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"lat": 35.0, "lon": 51.0, "alt": 1200.0}

        def fake_get(url, timeout):
            captured['url'] = url
            captured['timeout'] = timeout
            return DummyResponse()

        monkeypatch.setattr("src.drone_api_server.requests.get", fake_get)

        origin = api_server._get_origin_from_gcs()

        assert captured['url'] == "http://172.18.0.1:5000/api/v1/origin/bootstrap"
        assert captured['timeout'] == 5
        assert origin == {'lat': 35.0, 'lon': 51.0}

    def test_send_command_different_mission_types(self, test_client, mock_drone_communicator):
        """Test different mission types with new response format"""
        # Use valid mission type codes that exist in the Mission enum
        mission_types = [10, 101, 102, 104, 105]  # TAKE_OFF, LAND, HOLD, RETURN_RTL, KILL_TERMINATE

        for mission_type in mission_types:
            mock_drone_communicator.process_command.reset_mock()
            command = {"missionType": str(mission_type), "triggerTime": "0"}
            response = test_client.post("/api/v1/drone/commands", json=command)

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
        mock_drone_config.mission = 10
        mock_drone_config.trigger_time = 12345
        mock_drone_config.current_command_id = "cmd-123"

        response = test_client.post(
            "/api/v1/drone/commands",
            json={"missionType": "10", "triggerTime": "12345", "command_id": "cmd-123"},
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
                "mission_type": 10,
                "trigger_time": 0,
                "state": 0,
                "phase": "completed",
            }),
        )

        response = test_client.post(
            "/api/v1/drone/commands",
            json={"missionType": "10", "triggerTime": "0", "command_id": "cmd-123"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert "already completed" in data["message"]
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
            json={"missionType": "101", "triggerTime": "0", "command_id": "new-cmd"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
        assert mock_drone_config.current_command_id == "old-cmd"
        supersede_report.assert_not_awaited()

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
            json={"missionType": "0", "triggerTime": "0", "command_id": "cancel-1"},
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

    def test_get_git_status(self, test_client, monkeypatch):
        """Test canonical drone git-status endpoint"""
        # Mock git commands
        def mock_execute_git_command(self, command):
            git_responses = {
                ('git', 'rev-parse', '--abbrev-ref', 'HEAD'): 'main-candidate',
                ('git', 'rev-parse', 'HEAD'): 'abc123def456',
                ('git', 'show', '-s', '--format=%an', 'abc123def456'): 'Test User',
                ('git', 'show', '-s', '--format=%ae', 'abc123def456'): 'test@example.com',
                ('git', 'show', '-s', '--format=%cd', '--date=iso-strict', 'abc123def456'): '2025-11-22T10:00:00+00:00',
                ('git', 'show', '-s', '--format=%B', 'abc123def456'): 'test commit',
                ('git', 'config', '--get', 'remote.origin.url'): 'git@github.com:test/repo.git',
                ('git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'): 'origin/main-candidate',
                ('git', 'status', '--porcelain'): ''
            }
            return git_responses.get(tuple(command), '')

        # Monkeypatch the method
        from src.drone_api_server import DroneAPIServer
        monkeypatch.setattr(DroneAPIServer, '_execute_git_command', mock_execute_git_command)

        response = test_client.get("/api/v1/git/status")

        assert response.status_code == 200
        data = response.json()

        assert 'branch' in data
        assert 'commit' in data
        assert 'status' in data
        assert data['status'] == 'clean'


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

    def test_v1_get_drone_state_success(self, test_client):
        response = test_client.get("/api/v1/drone/state")

        assert response.status_code == 200
        data = response.json()
        assert data["pos_id"] == 1
        assert "timestamp" in data
        assert "server_time" in data

    def test_v1_send_command_alias(self, test_client, sample_command):
        response = test_client.post("/api/v1/drone/commands", json=sample_command)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in {"accepted", "rejected"}
        assert "timestamp" in data

    def test_v1_live_armability(self, test_client, monkeypatch):
        from src.drone_api_server import DroneAPIServer

        async def _mock_probe(self, require_global_position=True):
            return {
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
