# tests/test_gcs_api_http.py
"""
GCS API HTTP Endpoint Tests
============================
Comprehensive test suite for GCS Server FastAPI HTTP endpoints.

Tests all major endpoint categories:
- Health & System endpoints
- Configuration management
- Telemetry retrieval
- Heartbeat handling
- Origin management
- Show import and management
- Git operations
- Swarm trajectory management

Author: MAVSDK Drone Show Test Team
Last Updated: 2025-12-27
"""

import pytest
import json
import time
import tempfile
import os
import signal
import sys
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO

# Mock signal.signal BEFORE any imports that might use it
_original_signal = signal.signal
def _safe_signal(sig, handler):
    """Safe signal registration that works in threads"""
    try:
        return _original_signal(sig, handler)
    except ValueError:
        # In a thread, just return None
        return None

signal.signal = _safe_signal

# Path configuration is handled by conftest.py

from tests.conftest import SyncASGITestClient


# Mock the background services before importing the app
@pytest.fixture(autouse=True)
def mock_background_services():
    """Mock background services to prevent actual polling during tests"""
    with patch('app_fastapi.BackgroundServices') as mock_services:
        mock_instance = Mock()
        mock_instance.start = Mock()
        mock_instance.stop = Mock()
        mock_services.return_value = mock_instance
        yield mock_services


@pytest.fixture
def mock_config():
    """Mock drone configuration"""
    return [
        {
            'pos_id': 1,
            'hw_id': '1',
            'ip': '192.168.1.101',
            'connection_str': 'udp://:14540'
        },
        {
            'pos_id': 2,
            'hw_id': '2',
            'ip': '192.168.1.102',
            'connection_str': 'udp://:14541'
        }
    ]


@pytest.fixture
def mock_telemetry_data():
    """Mock telemetry data for all drones - mirrors live storage with int keys and ids."""
    return {
        1: {
            'pos_id': 0,
            'hw_id': 1,
            'state': 'idle',
            'mission': 0,
            'last_mission': 0,
            'trigger_time': 0,
            'flight_mode': 65536,
            'base_mode': 81,
            'system_status': 4,
            'is_armed': False,
            'is_ready_to_arm': True,
            'home_position_set': True,
            'readiness_status': 'ready',
            'readiness_summary': 'Ready to fly',
            'readiness_checks': [
                {
                    'id': 'px4',
                    'label': 'PX4 arming report',
                    'ready': True,
                    'detail': 'No active PX4 preflight blockers',
                }
            ],
            'preflight_blockers': [],
            'preflight_warnings': [],
            'status_messages': [],
            'preflight_last_update': 1700000000000,
            'battery_voltage': 12.6,
            'position_lat': 35.123456,
            'position_long': -120.654321,
            'position_alt': 488.5,
            'velocity_north': 0.0,
            'velocity_east': 0.0,
            'velocity_down': 0.0,
            'yaw': 180.0,
            'follow_mode': 0,
            'update_time': '2026-03-21 12:00:00',
            'hdop': 0.8,
            'vdop': 1.1,
            'gps_fix_type': 3,
            'satellites_visible': 12,
            'ip': '192.168.1.101',
            'heartbeat_last_seen': 1700000000000,
            'heartbeat_network_info': {},
            'heartbeat_first_seen': 1699999999000,
            'timestamp': 1700000000000,
        },
        2: {
            'pos_id': 1,
            'hw_id': 2,
            'state': 'idle',
            'mission': 0,
            'last_mission': 0,
            'trigger_time': 0,
            'flight_mode': 65536,
            'base_mode': 81,
            'system_status': 4,
            'is_armed': False,
            'is_ready_to_arm': False,
            'home_position_set': True,
            'readiness_status': 'blocked',
            'readiness_summary': 'Preflight Fail: ekf2 missing data',
            'readiness_checks': [
                {
                    'id': 'px4',
                    'label': 'PX4 arming report',
                    'ready': False,
                    'detail': '1 active PX4 preflight blocker(s)',
                }
            ],
            'preflight_blockers': [
                {
                    'source': 'px4',
                    'severity': 'error',
                    'message': 'Preflight Fail: ekf2 missing data',
                    'timestamp': 1700000000000,
                }
            ],
            'preflight_warnings': [],
            'status_messages': [],
            'preflight_last_update': 1700000000000,
            'battery_voltage': 12.4,
            'position_lat': 35.123457,
            'position_long': -120.654322,
            'position_alt': 488.6,
            'velocity_north': 0.0,
            'velocity_east': 0.0,
            'velocity_down': 0.0,
            'yaw': 180.0,
            'follow_mode': 0,
            'update_time': '2026-03-21 12:00:00',
            'hdop': 1.2,
            'vdop': 1.5,
            'gps_fix_type': 3,
            'satellites_visible': 10,
            'ip': '192.168.1.102',
            'heartbeat_last_seen': 1700000000000,
            'heartbeat_network_info': {},
            'heartbeat_first_seen': 1699999999000,
            'timestamp': 1700000000000,
        }
    }


@pytest.fixture
def mock_origin():
    """Mock origin data"""
    return {
        'lat': 35.123456,
        'lon': -120.654321,
        'alt': 488.0,
        'timestamp': '2025-11-22T12:00:00',
        'alt_source': 'manual'
    }


@pytest.fixture
def test_client(mock_config, mock_telemetry_data):
    """Create FastAPI test client with mocked dependencies"""
    with patch('app_fastapi.load_config', return_value=mock_config):
        with patch('app_fastapi.telemetry_data_all_drones', mock_telemetry_data):
            from app_fastapi import app
            client = SyncASGITestClient(app)
            yield client


# ============================================================================
# Health & System Tests
# ============================================================================

class TestHealthEndpoints:
    """Test health check and system status endpoints"""

    def test_ping_endpoint(self, test_client):
        """Test /ping health check endpoint"""
        response = test_client.get("/ping")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert 'timestamp' in data

    def test_health_endpoint(self, test_client):
        """Test /health health check endpoint"""
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert 'timestamp' in data


class TestSwarmTrajectoryPolicyEndpoint:
    """Test Swarm Trajectory runtime policy endpoint."""

    def test_returns_runtime_policy_from_params(self, test_client):
        response = test_client.get("/api/swarm/trajectory/policy")

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["policy"]["speed"]["absolute_max"] == pytest.approx(20.0)
        assert payload["policy"]["timing"]["derived_time_step_s"] == pytest.approx(0.1)
        assert payload["policy"]["terrain"]["default_safe_clearance_m"] >= payload["policy"]["terrain"]["min_safe_clearance_m"]


class TestBackgroundTelemetryHelpers:
    """Test live telemetry shaping used by the FastAPI background poller."""

    def test_build_background_telemetry_record_merges_heartbeat_metadata(self):
        from app_fastapi import _build_background_telemetry_record, last_heartbeats

        with patch.dict(last_heartbeats, {
            '1': {
                'timestamp': 1700000000123,
                'first_seen': 1699999999.0,
                'network_info': {'reachable': True},
            }
        }, clear=True):
            payload = _build_background_telemetry_record(
                1,
                '192.168.1.101',
                {
                    'hw_id': 1,
                    'position_lat': 35.123456,
                    'position_long': -120.654321,
                    'position_alt': 488.5,
                    'timestamp': 1700000000999,
                },
            )

        assert payload['hw_id'] == '1'
        assert payload['ip'] == '192.168.1.101'
        assert payload['heartbeat_last_seen'] == 1700000000123
        assert payload['heartbeat_first_seen'] == 1699999999000
        assert payload['heartbeat_network_info'] == {'reachable': True}

    def test_build_background_telemetry_record_marks_stale_local_feed_unavailable(self):
        from app_fastapi import _build_background_telemetry_record, last_heartbeats

        stale_update_time = int(time.time()) - 45

        with patch.dict(last_heartbeats, {
            '2': {
                'timestamp': 1700000001123,
                'first_seen': 1700000000.0,
                'network_info': {'reachable': True},
            }
        }, clear=True):
            payload = _build_background_telemetry_record(
                2,
                '192.168.1.102',
                {
                    'hw_id': 2,
                    'position_lat': 35.123456,
                    'position_long': -120.654321,
                    'position_alt': 488.5,
                    'update_time': stale_update_time,
                    'is_ready_to_arm': True,
                    'readiness_status': 'ready',
                    'readiness_summary': 'Ready to fly',
                },
            )

        assert payload['telemetry_available'] is False
        assert 'stale' in payload['telemetry_error'].lower()
        assert payload['is_ready_to_arm'] is False
        assert payload['readiness_status'] == 'unknown'
        assert payload['preflight_blockers']


# ============================================================================
# Configuration Tests
# ============================================================================

class TestConfigurationEndpoints:
    """Test drone configuration endpoints"""

    def test_get_config(self, test_client, mock_config):
        """Test GET /get-config-data"""
        response = test_client.get("/get-config-data")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]['pos_id'] == 1
        assert data[0]['hw_id'] == '1'

    @patch('app_fastapi.save_config')
    @patch('app_fastapi.validate_and_process_config')
    def test_save_config(self, mock_validate, mock_save, test_client, mock_config):
        """Test POST /save-config-data"""
        mock_validate.return_value = {'updated_config': mock_config}

        response = test_client.post("/save-config-data", json=mock_config)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] == True
        assert 'updated_count' in data

    @patch('app_fastapi.validate_and_process_config')
    def test_validate_config(self, mock_validate, test_client, mock_config):
        """Test POST /validate-config"""
        mock_validate.return_value = {
            'updated_config': mock_config,
            'summary': {
                'duplicates_count': 0,
                'missing_trajectories_count': 0,
                'role_swaps_count': 0
            }
        }

        response = test_client.post("/validate-config", json=mock_config)
        assert response.status_code == 200
        data = response.json()
        assert 'summary' in data

    def test_save_config_rejects_invalid_format(self, test_client):
        """Test POST /save-config-data preserves 400 for invalid client payload shape."""
        response = test_client.post("/save-config-data", json={"not": "a-list"})
        assert response.status_code == 400
        assert response.json()['detail'] == "Invalid configuration data format"


# ============================================================================
# Telemetry Tests
# ============================================================================

class TestTelemetryEndpoints:
    """Test telemetry endpoints"""

    def test_get_telemetry_legacy(self, test_client, mock_telemetry_data):
        """Test GET /telemetry (legacy endpoint)"""
        response = test_client.get("/telemetry")
        assert response.status_code == 200
        assert 'x-mds-server-time' in response.headers
        data = response.json()
        assert isinstance(data, dict)
        assert '1' in data
        assert data['1']['battery_voltage'] == 12.6

    def test_get_telemetry_typed(self, test_client):
        """Test GET /api/telemetry (typed endpoint)"""
        response = test_client.get("/api/telemetry")
        assert response.status_code == 200
        assert 'x-mds-server-time' in response.headers
        data = response.json()
        assert 'telemetry' in data
        assert 'total_drones' in data
        assert 'online_drones' in data
        assert data['telemetry']['1']['readiness_status'] == 'ready'
        assert data['telemetry']['2']['preflight_blockers'][0]['message'] == 'Preflight Fail: ekf2 missing data'


# ============================================================================
# Heartbeat Tests
# ============================================================================

class TestHeartbeatEndpoints:
    """Test heartbeat endpoints"""

    @patch('app_fastapi.handle_heartbeat_post')
    def test_post_heartbeat(self, mock_handle, test_client):
        """Test POST /heartbeat"""
        heartbeat_data = {
            'pos_id': 0,
            'hw_id': '1',
            'detected_pos_id': 1,
            'ip': '172.18.0.2',
            'network_info': {'wifi': {'ssid': 'test'}},
            'timestamp': 1700000000000
        }

        response = test_client.post("/heartbeat", json=heartbeat_data)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] == True
        mock_handle.assert_called_once()
        kwargs = mock_handle.call_args.kwargs
        assert kwargs['hw_id'] == '1'
        assert kwargs['detected_pos_id'] == 1
        assert kwargs['ip'] == '172.18.0.2'

    @patch('app_fastapi.get_all_heartbeats')
    def test_get_heartbeats(self, mock_get_heartbeats, test_client):
        """Test GET /get-heartbeats"""
        # get_all_heartbeats returns a dict keyed by hw_id
        mock_get_heartbeats.return_value = {
            '1': {'pos_id': 0, 'hw_id': '1', 'detected_pos_id': 1, 'ip': 'unknown', 'timestamp': 1700000000000},
            '2': {'pos_id': 1, 'hw_id': '2', 'detected_pos_id': 2, 'ip': '172.18.0.22', 'timestamp': 1700000000000}
        }

        response = test_client.get("/get-heartbeats")
        assert response.status_code == 200
        data = response.json()
        assert 'heartbeats' in data
        assert data['total_drones'] == 2
        heartbeats = {item['hw_id']: item for item in data['heartbeats']}
        assert heartbeats['1']['detected_pos_id'] == 1
        assert heartbeats['1']['ip'] == '192.168.1.101'
        assert heartbeats['2']['ip'] == '172.18.0.22'


# ============================================================================
# Origin Tests
# ============================================================================

class TestOriginEndpoints:
    """Test origin management endpoints"""

    @patch('app_fastapi.load_origin')
    def test_get_origin(self, mock_load, test_client, mock_origin):
        """Test GET /get-origin"""
        mock_load.return_value = mock_origin

        response = test_client.get("/get-origin")
        assert response.status_code == 200
        data = response.json()
        assert data['lat'] == 35.123456
        assert data['lon'] == -120.654321

    @patch('app_fastapi.load_origin')
    def test_get_origin_v1(self, mock_load, test_client, mock_origin):
        """Test GET /api/v1/origin"""
        mock_load.return_value = mock_origin

        response = test_client.get("/api/v1/origin")
        assert response.status_code == 200
        data = response.json()
        assert data['lat'] == 35.123456
        assert data['lon'] == -120.654321
        assert data['source'] == 'manual'

    @patch('app_fastapi.save_origin')
    def test_set_origin(self, mock_save, test_client):
        """Test POST /set-origin"""
        # API uses short field names: lat, lon, alt
        origin_data = {
            'lat': 35.123456,
            'lon': -120.654321,
            'alt': 488.0
        }

        response = test_client.post("/set-origin", json=origin_data)
        assert response.status_code == 200
        data = response.json()
        assert data['lat'] == origin_data['lat']

    @patch('app_fastapi.save_origin')
    def test_put_origin_v1(self, mock_save, test_client):
        """Test PUT /api/v1/origin"""
        origin_data = {
            'lat': 35.123456,
            'lon': -120.654321,
            'alt': 488.0,
        }

        response = test_client.request("PUT", "/api/v1/origin", json=origin_data)
        assert response.status_code == 200
        data = response.json()
        assert data['lat'] == origin_data['lat']
        assert data['source'] == 'manual'

    @patch('app_fastapi.save_origin')
    def test_put_origin_v1_defaults_optional_altitude_to_zero(self, mock_save, test_client):
        """Test PUT /api/v1/origin defaults missing altitude to zero."""
        origin_data = {
            'lat': 35.123456,
            'lon': -120.654321,
        }

        response = test_client.request("PUT", "/api/v1/origin", json=origin_data)
        assert response.status_code == 200
        data = response.json()
        assert data['alt'] == 0.0
        mock_save.assert_called_once()
        saved_origin = mock_save.call_args.args[0]
        assert saved_origin['alt'] == 0.0

    @patch('app_fastapi.load_origin')
    def test_get_gps_global_origin(self, mock_load, test_client, mock_origin):
        """Test GET /get-gps-global-origin"""
        mock_load.return_value = mock_origin

        response = test_client.get("/get-gps-global-origin")
        assert response.status_code == 200
        data = response.json()
        assert data['has_origin'] == True

    @patch('app_fastapi.load_origin')
    def test_get_gps_global_origin_v1(self, mock_load, test_client, mock_origin):
        """Test GET /api/v1/navigation/global-origin"""
        mock_load.return_value = mock_origin

        response = test_client.get("/api/v1/navigation/global-origin")
        assert response.status_code == 200
        data = response.json()
        assert data['has_origin'] == True

    @patch('app_fastapi.load_origin')
    def test_get_origin_for_drone(self, mock_load, test_client, mock_origin):
        """Test GET /get-origin-for-drone"""
        mock_load.return_value = mock_origin

        response = test_client.get("/get-origin-for-drone")
        assert response.status_code == 200
        data = response.json()
        assert data['lat'] == 35.123456
        assert data['source'] == 'manual'

    @patch('app_fastapi.load_origin')
    def test_get_origin_bootstrap_v1(self, mock_load, test_client, mock_origin):
        """Test GET /api/v1/origin/bootstrap"""
        mock_load.return_value = mock_origin

        response = test_client.get("/api/v1/origin/bootstrap")
        assert response.status_code == 200
        data = response.json()
        assert data['lat'] == 35.123456
        assert data['source'] == 'manual'
        assert isinstance(data['timestamp'], int)

    @patch('app_fastapi.save_origin')
    @patch('app_fastapi.compute_origin_from_drone')
    @patch('app_fastapi.get_expected_position_from_trajectory')
    def test_compute_origin(
        self,
        mock_get_expected_position,
        mock_compute_origin,
        mock_save_origin,
        test_client,
    ):
        """Test POST /compute-origin"""
        mock_get_expected_position.return_value = (10.0, 5.0)
        mock_compute_origin.return_value = (35.555, -120.777)

        response = test_client.post('/compute-origin', json={
            'current_lat': 35.123456,
            'current_lon': -120.654321,
            'pos_id': 1,
        })

        assert response.status_code == 200
        assert response.json() == {
            'status': 'success',
            'lat': 35.555,
            'lon': -120.777,
        }
        mock_compute_origin.assert_called_once_with(35.123456, -120.654321, 10.0, 5.0)
        mock_save_origin.assert_not_called()

    @patch('app_fastapi.save_origin')
    @patch('app_fastapi.compute_origin_from_drone')
    @patch('app_fastapi.get_expected_position_from_trajectory')
    def test_compute_origin_v1(
        self,
        mock_get_expected_position,
        mock_compute_origin,
        mock_save_origin,
        test_client,
    ):
        """Test POST /api/v1/origin/compute"""
        mock_get_expected_position.return_value = (10.0, 5.0)
        mock_compute_origin.return_value = (35.555, -120.777)

        response = test_client.post('/api/v1/origin/compute', json={
            'current_lat': 35.123456,
            'current_lon': -120.654321,
            'pos_id': 1,
        })

        assert response.status_code == 200
        assert response.json() == {
            'status': 'success',
            'lat': 35.555,
            'lon': -120.777,
        }
        mock_compute_origin.assert_called_once_with(35.123456, -120.654321, 10.0, 5.0)
        mock_save_origin.assert_not_called()


# ============================================================================
# Show Management Tests
# ============================================================================

class TestShowManagementEndpoints:
    """Test show import and management endpoints"""

    def test_import_show_rejects_non_zip(self, test_client):
        """Test POST /import-show rejects non-ZIP uploads early"""
        files = {'file': ('bad_show.txt', BytesIO(b'not-a-zip'), 'text/plain')}

        response = test_client.post("/import-show", files=files)

        assert response.status_code == 400
        assert 'ZIP' in response.json()['detail']

    def test_import_show_accepts_nested_zip_and_returns_summary(self, test_client, monkeypatch, tmp_path):
        """Test POST /import-show stages nested CSVs and returns the new summary payload"""
        import app_fastapi

        live_skybrush = tmp_path / 'shapes_sitl' / 'swarm' / 'skybrush'
        live_processed = tmp_path / 'shapes_sitl' / 'swarm' / 'processed'
        live_plots = tmp_path / 'shapes_sitl' / 'swarm' / 'plots'
        temp_dir = tmp_path / 'temp'
        for path in (live_skybrush, live_processed, live_plots, temp_dir):
            path.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(app_fastapi, 'BASE_DIR', str(tmp_path))
        monkeypatch.setattr(app_fastapi, 'skybrush_dir', str(live_skybrush))
        monkeypatch.setattr(app_fastapi, 'processed_dir', str(live_processed))
        monkeypatch.setattr(app_fastapi, 'plots_directory', str(live_plots))
        monkeypatch.setattr(app_fastapi.Params, 'GIT_AUTO_PUSH', False, raising=False)

        def fake_clear_show_directories(_base_dir):
            for directory in (live_skybrush, live_processed, live_plots):
                for entry in directory.iterdir():
                    if entry.is_file():
                        entry.unlink()

        def fake_run_formation_process(base_dir, skybrush_dir=None, processed_dir=None, plots_dir=None):
            assert sorted(os.listdir(skybrush_dir)) == ['Drone 1.csv', 'Drone 2.csv']

            for filename in ('Drone 1.csv', 'Drone 2.csv'):
                with open(os.path.join(processed_dir, filename), 'w', encoding='utf-8') as fh:
                    fh.write('idx,t,px,py,pz,vx,vy,vz,ax,ay,az,yaw,mode,ledr,ledg,ledb\n0,0,0,0,0,0,0,0,0,0,0,0,70,255,0,0\n')

            for filename in ('drone_1_path.jpg', 'drone_2_path.jpg', 'combined_drone_paths.jpg'):
                with open(os.path.join(plots_dir, filename), 'wb') as fh:
                    fh.write(b'jpg')

            return {
                'success': True,
                'message': 'ok',
                'input_count': 2,
                'processed_count': 2,
                'plot_count': 3,
                'processed_files': ['Drone 1.csv', 'Drone 2.csv'],
            }

        monkeypatch.setattr(app_fastapi, 'clear_show_directories', fake_clear_show_directories)
        monkeypatch.setattr(app_fastapi, 'run_formation_process', fake_run_formation_process)

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as archive:
            archive.writestr('nested/export/Drone 1.csv', 'Time [msec],x [m],y [m],z [m],Red,Green,Blue\n0,0,0,0,255,0,0\n')
            archive.writestr('deep/Drone 2.csv', 'Time [msec],x [m],y [m],z [m],Red,Green,Blue\n0,0,0,0,255,0,0\n')
        zip_buffer.seek(0)

        files = {'file': ('test_show.zip', zip_buffer, 'application/zip')}
        response = test_client.post("/import-show", files=files)

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['files_processed'] == 2
        assert data['raw_files_found'] == 2
        assert data['plots_generated'] == 3
        assert any('flattened' in warning.lower() for warning in data['warnings'])
        assert len(data['next_steps']) == 2

    @patch('os.listdir')
    @patch('os.path.exists', return_value=True)
    def test_get_show_info(self, mock_exists, mock_listdir, test_client):
        """Test GET /get-show-info"""
        mock_listdir.return_value = ['Drone 1.csv', 'Drone 2.csv']

        with patch('builtins.open', create=True) as mock_open:
            mock_file = MagicMock()
            mock_file.__enter__.return_value.__iter__.return_value = [
                't [ms],x [m],y [m],z [m],yaw [deg]\n',
                '0,0,0,0,0\n',
                '60000,1.0,1.0,5.0,0\n'
            ]
            mock_open.return_value = mock_file

            response = test_client.get("/get-show-info")

        assert response.status_code == 200
        data = response.json()
        assert 'drone_count' in data
        assert 'max_altitude' in data

    def test_get_custom_show_info(self, test_client, monkeypatch, tmp_path):
        """Test GET /get-custom-show-info reports active custom CSV metadata."""
        import app_fastapi

        shapes_dir = tmp_path / 'shapes_sitl'
        shapes_dir.mkdir(parents=True, exist_ok=True)
        (shapes_dir / 'active.csv').write_text(
            'idx,t,px,py,pz,vx,vy,vz,ax,ay,az,yaw,mode,ledr,ledg,ledb\n'
            '0,0.0,0.0,0.0,-0.0,0,0,0,0,0,0,0,70,0,0,255\n'
            '1,2.5,1.0,2.0,-5.0,0,0,0,0,0,0,0,70,0,0,255\n',
            encoding='utf-8',
        )
        (shapes_dir / 'trajectory_plot.png').write_bytes(b'png')

        monkeypatch.setattr(app_fastapi, 'shapes_dir', str(shapes_dir))

        response = test_client.get('/get-custom-show-info')

        assert response.status_code == 200
        data = response.json()
        assert data['exists'] is True
        assert data['filename'] == 'active.csv'
        assert data['row_count'] == 2
        assert data['duration_sec'] == 2.5
        assert data['max_altitude'] == 5.0
        assert data['preview_exists'] is True
        assert data['execution_mode'] == 'local per-drone replay'
        assert 't' in data['required_columns']

    def test_import_custom_show_accepts_valid_protocol_csv(self, test_client, monkeypatch, tmp_path):
        """Test POST /import-custom-show validates, stages, and activates a custom CSV."""
        import app_fastapi

        shapes_dir = tmp_path / 'shapes_sitl'
        temp_dir = tmp_path / 'temp'
        shapes_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(app_fastapi, 'BASE_DIR', str(tmp_path))
        monkeypatch.setattr(app_fastapi, 'shapes_dir', str(shapes_dir))
        monkeypatch.setattr(app_fastapi.Params, 'GIT_AUTO_PUSH', False, raising=False)

        def fake_generate_preview(points, preview_path):
            assert len(points) == 2
            Path(preview_path).write_bytes(b'png')

        monkeypatch.setattr(app_fastapi, '_generate_custom_show_preview', fake_generate_preview)

        csv_buffer = BytesIO(
            b't,px,py,pz,vx,vy,vz,ax,ay,az,yaw,mode\n'
            b'0.0,0.0,0.0,-0.0,0,0,0,0,0,0,0,70\n'
            b'2.5,1.0,2.0,-5.0,0,0,0,0,0,0,5,70\n'
        )

        files = {'file': ('custom_show.csv', csv_buffer, 'text/csv')}
        response = test_client.post('/import-custom-show', files=files)

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['stored_as'] == 'active.csv'
        assert data['row_count'] == 2
        assert data['duration_sec'] == 2.5
        assert data['preview_generated'] is True
        assert (shapes_dir / 'active.csv').exists()
        assert (shapes_dir / 'trajectory_plot.png').exists()

    def test_import_custom_show_rejects_missing_protocol_columns(self, test_client, monkeypatch, tmp_path):
        """Test POST /import-custom-show rejects non-protocol CSV files."""
        import app_fastapi

        shapes_dir = tmp_path / 'shapes_sitl'
        temp_dir = tmp_path / 'temp'
        shapes_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(app_fastapi, 'BASE_DIR', str(tmp_path))
        monkeypatch.setattr(app_fastapi, 'shapes_dir', str(shapes_dir))
        monkeypatch.setattr(app_fastapi.Params, 'GIT_AUTO_PUSH', False, raising=False)

        files = {'file': ('bad_custom_show.csv', BytesIO(b't,px,py\n0,0,0\n'), 'text/csv')}
        response = test_client.post('/import-custom-show', files=files)

        assert response.status_code == 400
        assert 'required protocol columns' in response.json()['detail']

    def test_get_position_deviations_supports_string_hw_id_telemetry_keys(
        self,
        test_client,
        monkeypatch,
        mock_config,
        mock_origin,
    ):
        """Live background telemetry stores string hw_id keys; deviation checks must still resolve them."""
        import app_fastapi

        string_keyed_telemetry = {
            "1": {
                "hw_id": "1",
                "position_lat": mock_origin["lat"],
                "position_long": mock_origin["lon"],
            },
            "2": {
                "hw_id": "2",
                "position_lat": mock_origin["lat"],
                "position_long": mock_origin["lon"],
            },
        }

        monkeypatch.setattr(app_fastapi, 'telemetry_data_all_drones', string_keyed_telemetry)
        monkeypatch.setattr(app_fastapi, 'load_config', lambda: mock_config)
        monkeypatch.setattr(app_fastapi, 'load_origin', lambda: mock_origin)
        monkeypatch.setattr(app_fastapi, 'get_expected_position_from_trajectory', lambda *args, **kwargs: (0.0, 0.0))

        response = test_client.get('/get-position-deviations')

        assert response.status_code == 200
        data = response.json()
        assert data['summary']['online'] == 2
        assert data['summary']['no_telemetry'] == 0
        assert data['deviations']['1']['current'] is not None
        assert data['deviations']['2']['current'] is not None

    def test_get_comprehensive_metrics_recalculates_stale_cache(self, test_client, monkeypatch, tmp_path):
        """Stale saved metrics must be ignored when the processed drone count changes."""
        import app_fastapi

        swarm_dir = tmp_path / 'shapes_sitl' / 'swarm'
        processed = swarm_dir / 'processed'
        processed.mkdir(parents=True, exist_ok=True)

        for drone_id in range(1, 6):
            (processed / f'Drone {drone_id}.csv').write_text('idx,t,px,py,pz\n0,0,0,0,0\n', encoding='utf-8')

        stale_metrics = {
            'basic_metrics': {
                'drone_count': 6,
                'duration_seconds': 12.0,
                'max_altitude_m': 9.0,
            }
        }
        metrics_file = swarm_dir / 'comprehensive_metrics.json'
        metrics_file.write_text(json.dumps(stale_metrics), encoding='utf-8')

        refreshed_metrics = {
            'basic_metrics': {
                'drone_count': 5,
                'duration_seconds': 25.0,
                'max_altitude_m': 14.0,
            }
        }
        refresh_calls = []

        monkeypatch.setattr(app_fastapi, 'shapes_dir', str(tmp_path / 'shapes_sitl'))
        monkeypatch.setattr(app_fastapi, 'processed_dir', str(processed))
        monkeypatch.setattr(app_fastapi, 'METRICS_AVAILABLE', True)

        def fake_refresh(show_filename=None):
            refresh_calls.append(show_filename)
            metrics_file.write_text(json.dumps(refreshed_metrics), encoding='utf-8')
            return refreshed_metrics

        monkeypatch.setattr(app_fastapi, '_refresh_saved_show_metrics', fake_refresh)

        response = test_client.get('/get-comprehensive-metrics')

        assert response.status_code == 200
        assert response.json()['basic_metrics']['drone_count'] == 5
        assert refresh_calls == [None]

    def test_validate_trajectory_preserves_fail_status_when_warnings_also_exist(self, test_client, monkeypatch, tmp_path):
        """A safety FAIL must not be downgraded to WARNING later in the same validation pass."""
        import app_fastapi

        class DummyMetricsEngine:
            def __init__(self, processed_dir):
                self.processed_dir = processed_dir

            def load_drone_data(self):
                return True

            def calculate_comprehensive_metrics(self):
                return {
                    'safety_metrics': {
                        'safety_status': 'UNSAFE',
                        'collision_warnings_count': 2,
                    },
                    'performance_metrics': {
                        'max_velocity_ms': 18.0,
                    },
                    'formation_metrics': {
                        'formation_quality': 'Degraded',
                    },
                }

        monkeypatch.setattr(app_fastapi, 'METRICS_AVAILABLE', True)
        monkeypatch.setattr(app_fastapi, 'DroneShowMetrics', DummyMetricsEngine)
        monkeypatch.setattr(app_fastapi, 'processed_dir', str(tmp_path / 'processed'))

        response = test_client.post('/validate-trajectory')

        assert response.status_code == 200
        data = response.json()
        assert data['validation_status'] == 'FAIL'
        assert any('Safety issue' in issue for issue in data['issues'])
        assert any('collision warnings' in issue for issue in data['issues'])
        assert any('High velocity' in issue for issue in data['issues'])

    @patch('app_fastapi.git_operations')
    def test_deploy_show_accepts_json_content_type_with_charset(self, mock_git_operations, test_client):
        """The deploy route should parse standard JSON content-type variants, not only an exact match."""
        mock_git_operations.return_value = {
            'success': True,
            'message': 'ok',
            'commit': 'abc12345',
        }

        response = test_client.post(
            '/deploy-show',
            data=json.dumps({'message': 'Deploy via API'}),
            headers={'content-type': 'application/json; charset=utf-8'},
        )

        assert response.status_code == 200
        assert response.json()['success'] is True
        mock_git_operations.assert_called_once()
        assert mock_git_operations.call_args.args[1] == 'Deploy via API'


# ============================================================================
# GCS Management & Static Asset Tests
# ============================================================================

class TestGCSManagementEndpoints:
    """Test GCS management, network, and static asset endpoints."""

    def test_get_gcs_config(self, test_client, monkeypatch):
        import app_fastapi

        monkeypatch.setattr(app_fastapi.Params, 'sim_mode', True, raising=False)
        monkeypatch.setattr(app_fastapi.Params, 'gcs_api_port', 3030, raising=False)
        monkeypatch.setattr(app_fastapi.Params, 'GIT_AUTO_PUSH', False, raising=False)
        monkeypatch.setattr(app_fastapi.Params, 'acceptable_deviation', 4.5, raising=False)

        response = test_client.get('/get-gcs-config')

        assert response.status_code == 200
        assert response.json() == {
            'sim_mode': True,
            'gcs_port': 3030,
            'git_auto_push': False,
            'acceptable_deviation': 4.5,
        }

    def test_save_gcs_config_returns_explicit_stub_ack(self, test_client):
        response = test_client.post('/save-gcs-config', json={'sim_mode': True})

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['status'] == 'success'
        assert data['persisted'] is False
        assert data['warnings']

    @patch('app_fastapi.get_network_info_from_heartbeats')
    def test_get_network_info(self, mock_network_info, test_client):
        mock_network_info.return_value = [
            {'hw_id': '1', 'wifi': {'ssid': 'mds-net'}},
            {'hw_id': '2', 'ethernet': {'interface': 'eth0'}},
        ]

        response = test_client.get('/get-network-info')

        assert response.status_code == 200
        assert response.json()[0]['hw_id'] == '1'
        assert response.json()[1]['ethernet']['interface'] == 'eth0'

    def test_static_plot_serving(self, test_client, monkeypatch, tmp_path):
        import app_fastapi

        plots_dir = tmp_path / 'plots'
        plots_dir.mkdir(parents=True, exist_ok=True)
        plot_file = plots_dir / 'drone_1.jpg'
        plot_file.write_bytes(b'jpg')

        monkeypatch.setattr(
            app_fastapi,
            'get_swarm_trajectory_folders',
            lambda: {'plots': str(plots_dir)},
        )

        response = test_client.get('/static/plots/drone_1.jpg')

        assert response.status_code == 200
        assert response.content == b'jpg'


# ============================================================================
# Git Status Tests
# ============================================================================

class TestGitStatusEndpoints:
    """Test git status endpoints"""

    @patch('app_fastapi.git_status_data_all_drones', {
        '1': {'status': 'clean', 'branch': 'main', 'commit': 'abc12345', 'uncommitted_changes': []},
        '2': {'status': 'clean', 'branch': 'main', 'commit': 'abc12345', 'uncommitted_changes': []}
    })
    @patch('app_fastapi.get_gcs_git_report')
    @patch('app_fastapi.load_config')
    def test_get_git_status(self, mock_load_config, mock_gcs_git_report, test_client):
        """Test GET /git-status"""
        mock_load_config.return_value = [
            {'hw_id': 1, 'pos_id': 1, 'ip': '10.0.0.1'},
            {'hw_id': 2, 'pos_id': 2, 'ip': '10.0.0.2'},
        ]
        mock_gcs_git_report.return_value = {'branch': 'main', 'commit': 'abc12345'}
        response = test_client.get("/git-status")
        assert response.status_code == 200
        data = response.json()
        assert 'git_status' in data
        assert 'synced_count' in data
        assert data['git_status']['1']['commit'] == 'abc12345'
        assert data['git_status']['1']['ip'] == '10.0.0.1'
        assert data['git_status']['1']['in_sync_with_gcs'] is True
        assert data['needs_sync_count'] == 0

    @patch('app_fastapi.git_status_data_all_drones', {
        '1': {'status': 'clean', 'branch': 'main-candidate', 'commit': 'old12345', 'uncommitted_changes': []},
        '2': {'status': 'clean', 'branch': 'main-candidate', 'commit': 'old12345', 'uncommitted_changes': []}
    })
    @patch('app_fastapi.get_gcs_git_report')
    @patch('app_fastapi.load_config')
    def test_get_git_status_counts_out_of_sync_with_gcs(
        self,
        mock_load_config,
        mock_gcs_git_report,
        test_client,
    ):
        """GET /git-status should flag clean-but-behind drones as out of sync with GCS."""
        mock_load_config.return_value = [
            {'hw_id': 1, 'pos_id': 1, 'ip': '10.0.0.1'},
            {'hw_id': 2, 'pos_id': 2, 'ip': '10.0.0.2'},
        ]
        mock_gcs_git_report.return_value = {'branch': 'main-candidate', 'commit': 'new67890'}

        response = test_client.get("/git-status")

        assert response.status_code == 200
        data = response.json()
        assert data['synced_count'] == 0
        assert data['needs_sync_count'] == 2
        assert data['git_status']['1']['in_sync_with_gcs'] is False

    @patch('app_fastapi.get_gcs_git_report')
    def test_get_gcs_git_status(self, mock_report, test_client):
        """Test GET /get-gcs-git-status"""
        mock_report.return_value = {'branch': 'main', 'status': 'clean'}

        response = test_client.get("/get-gcs-git-status")
        assert response.status_code == 200

    @patch('app_fastapi._verify_sync_targets')
    @patch('app_fastapi.send_commands_to_all')
    @patch('app_fastapi.get_gcs_git_report')
    @patch('app_fastapi.load_config')
    def test_sync_repos_verifies_actual_convergence(
        self,
        mock_load_config,
        mock_gcs_git_report,
        mock_send_commands,
        mock_verify_targets,
        test_client,
    ):
        """POST /sync-repos should only report success after repo convergence is verified."""
        mock_load_config.return_value = [
            {'hw_id': '1', 'pos_id': 1, 'ip': '10.0.0.1'},
            {'hw_id': '2', 'pos_id': 2, 'ip': '10.0.0.2'},
        ]
        mock_gcs_git_report.return_value = {
            'branch': 'main-candidate',
            'commit': 'abc123def456',
        }
        mock_send_commands.return_value = {
            'results': {
                '1': {'category': 'accepted'},
                '2': {'category': 'accepted'},
            }
        }
        mock_verify_targets.return_value = ([1], [2])

        response = test_client.post('/sync-repos', json={})

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert data['synced_drones'] == [1]
        assert data['failed_drones'] == [2]
        assert 'partially verified' in data['message']


# ============================================================================
# Swarm Management Tests
# ============================================================================

class TestSwarmEndpoints:
    """Test swarm configuration endpoints"""

    @patch('app_fastapi.load_swarm')
    def test_get_swarm_data(self, mock_load, test_client):
        """Test GET /get-swarm-data"""
        mock_load.return_value = {'hierarchies': {}}

        response = test_client.get("/get-swarm-data")
        assert response.status_code == 200

    @patch('app_fastapi.load_swarm')
    def test_get_swarm_config_v1_returns_envelope(self, mock_load, test_client):
        """Test GET /api/v1/config/swarm"""
        mock_load.return_value = [{'hw_id': 1, 'follow': 0}]

        response = test_client.get("/api/v1/config/swarm")

        assert response.status_code == 200
        assert response.json() == {
            'version': 1,
            'assignments': [{'hw_id': 1, 'follow': 0}],
        }

    @patch('app_fastapi.save_swarm')
    def test_save_swarm_data(self, mock_save, test_client):
        """Test POST /save-swarm-data"""
        swarm_data = [{'hw_id': 1, 'follow': 0}]

        response = test_client.post("/save-swarm-data?commit=false", json=swarm_data)
        assert response.status_code == 200

    @patch('app_fastapi.save_swarm')
    def test_put_swarm_config_v1(self, mock_save, test_client):
        """Test PUT /api/v1/config/swarm"""
        swarm_data = {'version': 1, 'assignments': [{'hw_id': 1, 'follow': 0}]}

        response = test_client.request("PUT", "/api/v1/config/swarm?commit=false", json=swarm_data)

        assert response.status_code == 200
        assert response.json()['status'] == 'success'
        assert response.json()['config'] == swarm_data

    @patch('app_fastapi.save_swarm')
    def test_save_swarm_data_rejects_cycles(self, mock_save, test_client):
        """Test POST /save-swarm-data rejects cyclic follow chains."""
        swarm_data = [
            {'hw_id': 1, 'follow': 2, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
            {'hw_id': 2, 'follow': 1, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        ]

        response = test_client.post("/save-swarm-data", json=swarm_data)

        assert response.status_code == 400
        assert 'cycle' in response.json()['detail']
        mock_save.assert_not_called()

    @patch('app_fastapi.save_swarm')
    @patch('app_fastapi.load_swarm')
    def test_request_new_leader_updates_swarm_assignment(self, mock_load, mock_save, test_client):
        """Test POST /request-new-leader persists a single drone assignment update."""
        mock_load.return_value = [
            {'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
            {'hw_id': 2, 'follow': 1, 'offset_x': 5, 'offset_y': 0, 'offset_z': 0, 'frame': 'body'},
        ]

        response = test_client.post(
            "/request-new-leader",
            json={'hw_id': 2, 'follow': 0, 'offset_x': 7, 'offset_y': 1, 'offset_z': 2, 'frame': 'ned'},
        )

        assert response.status_code == 200
        assert response.json()['status'] == 'success'
        saved_swarm = mock_save.call_args[0][0]
        assert saved_swarm[1]['hw_id'] == 2
        assert saved_swarm[1]['follow'] == 0
        assert saved_swarm[1]['offset_x'] == 7.0
        assert saved_swarm[1]['offset_y'] == 1.0
        assert saved_swarm[1]['offset_z'] == 2.0
        assert saved_swarm[1]['frame'] == 'ned'

    @patch('app_fastapi.save_swarm')
    @patch('app_fastapi.load_swarm')
    def test_patch_swarm_assignment_v1_updates_swarm_assignment(self, mock_load, mock_save, test_client):
        """Test PATCH /api/v1/config/swarm/assignments/{hw_id} persists a single assignment update."""
        mock_load.return_value = [
            {'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
            {'hw_id': 2, 'follow': 1, 'offset_x': 5, 'offset_y': 0, 'offset_z': 0, 'frame': 'body'},
        ]

        response = test_client.request(
            "PATCH",
            "/api/v1/config/swarm/assignments/2",
            json={'follow': 0, 'offset_x': 7, 'offset_y': 1, 'offset_z': 2, 'frame': 'ned'},
        )

        assert response.status_code == 200
        assert response.json()['status'] == 'success'
        saved_swarm = mock_save.call_args[0][0]
        assert saved_swarm[1]['hw_id'] == 2
        assert saved_swarm[1]['follow'] == 0
        assert saved_swarm[1]['offset_x'] == 7.0
        assert saved_swarm[1]['offset_y'] == 1.0
        assert saved_swarm[1]['offset_z'] == 2.0
        assert saved_swarm[1]['frame'] == 'ned'

    @patch('app_fastapi.save_swarm')
    @patch('app_fastapi.load_swarm')
    def test_request_new_leader_partial_update_preserves_offsets(self, mock_load, mock_save, test_client):
        """Test POST /request-new-leader keeps existing offsets/frame when only follow changes."""
        mock_load.return_value = [
            {'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
            {'hw_id': 2, 'follow': 1, 'offset_x': 5, 'offset_y': 2, 'offset_z': 3, 'frame': 'body'},
        ]

        response = test_client.post(
            "/request-new-leader",
            json={'hw_id': 2, 'follow': 0},
        )

        assert response.status_code == 200
        saved_swarm = mock_save.call_args[0][0]
        assert saved_swarm[1]['hw_id'] == 2
        assert saved_swarm[1]['follow'] == 0
        assert saved_swarm[1]['offset_x'] == 5
        assert saved_swarm[1]['offset_y'] == 2
        assert saved_swarm[1]['offset_z'] == 3
        assert saved_swarm[1]['frame'] == 'body'

    @patch('app_fastapi.load_swarm')
    def test_request_new_leader_rejects_self_follow(self, mock_load, test_client):
        """Test POST /request-new-leader rejects invalid self-follow changes."""
        mock_load.return_value = [
            {'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        ]

        response = test_client.post(
            "/request-new-leader",
            json={'hw_id': 1, 'follow': 1},
        )

        assert response.status_code == 400
        assert response.json()['detail'] == 'A drone cannot follow itself'

    @patch('app_fastapi.load_swarm')
    def test_request_new_leader_rejects_cycle_creation(self, mock_load, test_client):
        """Test POST /request-new-leader rejects updates that would create a follow loop."""
        mock_load.return_value = [
            {'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
            {'hw_id': 2, 'follow': 1, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
            {'hw_id': 3, 'follow': 2, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        ]

        response = test_client.post(
            "/request-new-leader",
            json={'hw_id': 1, 'follow': 3},
        )

        assert response.status_code == 400
        assert response.json()['detail'] == 'Follow update would create a cycle for hw_id=1'

    @patch('app_fastapi.load_swarm')
    def test_request_new_leader_rejects_cycle(self, mock_load, test_client):
        """Test POST /request-new-leader rejects updates that introduce a cycle."""
        mock_load.return_value = [
            {'hw_id': 1, 'follow': 0, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
            {'hw_id': 2, 'follow': 1, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0, 'frame': 'ned'},
        ]

        response = test_client.post(
            "/request-new-leader",
            json={'hw_id': 1, 'follow': 2},
        )

        assert response.status_code == 400
        assert 'cycle' in response.json()['detail']


# ============================================================================
# Swarm Trajectory Tests
# ============================================================================

class TestSwarmTrajectoryEndpoints:
    """Test swarm trajectory route registration after FastAPI migration."""

    def test_swarm_trajectory_routes_registered(self):
        """All routes used by the React page should be present on FastAPI."""
        from app_fastapi import app

        route_paths = {route.path for route in app.routes}

        expected_paths = {
            '/api/swarm/leaders',
            '/api/swarm/trajectory/upload/{leader_id}',
            '/api/swarm/trajectory/process',
            '/api/swarm/trajectory/recommendation',
            '/api/swarm/trajectory/status',
            '/api/swarm/trajectory/clear-processed',
            '/api/swarm/trajectory/clear',
            '/api/swarm/trajectory/clear-leader/{leader_id}',
            '/api/swarm/trajectory/remove/{leader_id}',
            '/api/swarm/trajectory/download/{drone_id}',
            '/api/swarm/trajectory/download-kml/{drone_id}',
            '/api/swarm/trajectory/download-cluster-kml/{leader_id}',
            '/api/swarm/trajectory/clear-drone/{drone_id}',
            '/api/swarm/trajectory/commit',
        }

        missing_paths = expected_paths - route_paths
        assert not missing_paths, f"Missing swarm trajectory routes: {sorted(missing_paths)}"


# ============================================================================
# Command Tests
# ============================================================================

class TestCommandEndpoints:
    """Test command submission endpoints"""

    def test_submit_command_rejects_malformed_json(self, test_client):
        response = test_client.post(
            "/submit_command",
            data="{bad",
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Malformed JSON request body"

    @patch('app_fastapi.probe_live_armability_for_drones')
    @patch('app_fastapi.send_commands_to_all')
    @patch('app_fastapi.load_config')
    def test_submit_command(self, mock_load, mock_send, mock_probe, test_client, mock_config):
        """Test POST /submit_command - new SubmitCommandResponse format"""
        mock_load.return_value = mock_config
        mock_probe.return_value = {
            'all_ready': True,
            'blocked_ids': [],
            'unavailable_ids': [],
            'results': {},
        }
        # Mock needs all expected fields from the updated command.py
        mock_send.return_value = {
            'success': 2, 'failed': 0, 'offline': 0, 'rejected': 0, 'errors': 0,
            'result_summary': '2 accepted', 'results': {
                '1': {'success': True, 'category': 'accepted'},
                '2': {'success': True, 'category': 'accepted'}
            }
        }

        # New format requires missionType and triggerTime
        command_data = {
            'missionType': 10,  # TAKE_OFF
            'triggerTime': 0
        }

        response = test_client.post("/submit_command", json=command_data)
        assert response.status_code == 200
        data = response.json()

        # New response format
        assert 'command_id' in data
        assert data['status'] == 'submitted'
        assert data['mission_type'] == 10
        assert 'mission_name' in data
        assert 'target_drones' in data
        assert 'submitted_count' in data
        assert data['tracking_phase'] == 'pending_execution'
        assert data['tracking_timeout_ms'] > 0

    @patch('app_fastapi.load_origin')
    @patch('app_fastapi.probe_live_armability_for_drones')
    @patch('app_fastapi.send_commands_to_all')
    @patch('app_fastapi.load_config')
    def test_submit_command_preserves_valid_zero_origin_coordinates(
        self,
        mock_load,
        mock_send,
        mock_probe,
        mock_load_origin,
        test_client,
        mock_config,
    ):
        mock_load.return_value = mock_config
        mock_load_origin.return_value = {
            'lat': 0.0,
            'lon': 0.0,
            'alt': 4.5,
            'timestamp': '2026-04-03T00:00:00',
            'alt_source': 'manual',
        }
        mock_probe.return_value = {
            'all_ready': True,
            'blocked_ids': [],
            'unavailable_ids': [],
            'results': {},
        }
        mock_send.return_value = {
            'success': 2, 'failed': 0, 'offline': 0, 'rejected': 0, 'errors': 0,
            'result_summary': '2 accepted', 'results': {
                '1': {'success': True, 'category': 'accepted'},
                '2': {'success': True, 'category': 'accepted'}
            }
        }

        response = test_client.post("/submit_command", json={
            'missionType': 10,
            'triggerTime': 0,
            'auto_global_origin': True,
        })

        assert response.status_code == 200
        sent_payload = mock_send.call_args[0][1]
        assert sent_payload['origin']['lat'] == 0.0
        assert sent_payload['origin']['lon'] == 0.0
        assert sent_payload['origin']['alt'] == 4.5

    @patch('app_fastapi.probe_live_armability_for_drones')
    @patch('app_fastapi.send_commands_to_selected')
    @patch('app_fastapi.load_config')
    @patch('app_fastapi.get_swarm_trajectory_folders')
    @patch('app_fastapi.swarm_trajectory_service.get_processing_status_payload')
    def test_submit_command_swarm_trajectory_uses_selected_processed_timeout_budget(
        self,
        mock_status,
        mock_folders,
        mock_load,
        mock_send_selected,
        mock_probe,
        test_client,
        mock_config,
        tmp_path,
    ):
        mock_load.return_value = mock_config
        mock_probe.return_value = {
            'all_ready': True,
            'blocked_ids': [],
            'unavailable_ids': [],
            'results': {},
        }
        mock_send_selected.return_value = {
            'success': 1, 'failed': 0, 'offline': 0, 'rejected': 0, 'errors': 0,
            'result_summary': '1 accepted', 'results': {
                '1': {'success': True, 'category': 'accepted'}
            }
        }
        mock_status.return_value = {
            'status': {
                'processed_drones': [1, 2],
                'follow_map': {'1': 0, '2': 1},
            }
        }

        processed_dir = tmp_path / "swarm_trajectory" / "processed"
        processed_dir.mkdir(parents=True)
        (processed_dir / "Drone 1.csv").write_text("t,alt\n0,10\n100,25\n", encoding="utf-8")
        (processed_dir / "Drone 2.csv").write_text("t,alt\n0,10\n500,25\n", encoding="utf-8")
        mock_folders.return_value = {
            'base': str(tmp_path / "swarm_trajectory"),
            'raw': str(tmp_path / "swarm_trajectory" / "raw"),
            'processed': str(processed_dir),
            'plots': str(tmp_path / "swarm_trajectory" / "plots"),
        }

        response = test_client.post(
            "/submit_command",
            json={
                'missionType': 4,
                'triggerTime': 0,
                'target_drones': ['1'],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data['tracking_timeout_ms'] == 540000
        assert data['tracking_phase'] == 'pending_execution'
        mock_send_selected.assert_called_once()

    def test_cancel_command_endpoint_fails_closed_until_live_dispatch_is_wired(self, test_client):
        response = test_client.post("/command/test-command-id/cancel")

        assert response.status_code == 409
        assert "missionType=0" in response.json()["detail"]

    @patch('app_fastapi.probe_live_armability_for_drones')
    @patch('app_fastapi.load_config')
    def test_submit_command_rejects_takeoff_when_live_probe_fails(
        self,
        mock_load,
        mock_probe,
        test_client,
        mock_config,
    ):
        mock_load.return_value = mock_config
        mock_probe.return_value = {
            'all_ready': False,
            'blocked_ids': ['1'],
            'unavailable_ids': [],
            'results': {
                '1': {
                    'summary': 'waiting for PX4 armability',
                },
            },
        }

        response = test_client.post(
            "/submit_command",
            json={
                'missionType': 10,
                'triggerTime': 0,
            },
        )

        assert response.status_code == 400
        assert 'Live launch readiness probe failed' in response.json()['detail']

    @patch('app_fastapi.send_commands_to_selected')
    @patch('app_fastapi.load_config')
    @patch('app_fastapi.swarm_trajectory_service.get_processing_status_payload')
    def test_submit_command_rejects_invalid_swarm_trajectory_subset(
        self,
        mock_status,
        mock_load,
        mock_send_selected,
        test_client,
        mock_config,
    ):
        mock_load.return_value = mock_config
        mock_status.return_value = {
            'status': {
                'processed_drones': [1, 2, 3],
                'follow_map': {'1': 0, '2': 1, '3': 2},
            }
        }

        response = test_client.post(
            "/submit_command",
            json={
                'missionType': 4,
                'triggerTime': 0,
                'target_drones': ['2', '3'],
            },
        )

        assert response.status_code == 400
        assert 'Unsafe Swarm Trajectory target set' in response.json()['detail']
        mock_send_selected.assert_not_called()

    @patch('app_fastapi.load_config')
    def test_submit_command_rejects_unmatched_target_drones(
        self,
        mock_load,
        test_client,
        mock_config,
    ):
        mock_load.return_value = mock_config

        response = test_client.post(
            "/submit_command",
            json={
                'missionType': 10,
                'triggerTime': 0,
                'target_drones': ['999'],
            },
        )

        assert response.status_code == 400
        assert response.json()['detail'] == 'No configured drones matched target_drones'


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling"""

    def test_404_not_found(self, test_client):
        """Test 404 error for non-existent endpoint"""
        response = test_client.get("/nonexistent-endpoint")
        assert response.status_code == 404

    def test_invalid_json(self, test_client):
        """Test handling of invalid JSON in POST request"""
        response = test_client.post(
            "/save-config-data",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code in [400, 422, 500]


class TestAPIV1Aliases:
    """Test canonical v1 aliases for the current GCS API surface."""

    def test_route_inventory_includes_legacy_and_v1_core_surfaces(self, test_client):
        routes = {route.path for route in test_client.app.routes}

        expected_routes = {
            "/ping",
            "/health",
            "/api/v1/system/health",
            "/telemetry",
            "/api/telemetry",
            "/api/v1/fleet/telemetry",
            "/heartbeat",
            "/drone-heartbeat",
            "/api/v1/fleet/heartbeats",
            "/get-heartbeats",
            "/get-network-status",
            "/api/v1/fleet/network-status",
            "/api/v1/config/fleet",
            "/api/v1/config/fleet/validation",
            "/api/v1/config/fleet/trajectory-start-positions",
            "/api/v1/config/fleet/trajectory-start-positions/{pos_id}",
            "/api/v1/config/swarm",
            "/api/v1/config/swarm/assignments/{hw_id}",
            "/api/v1/origin",
            "/api/v1/navigation/global-origin",
            "/api/v1/origin/elevation",
            "/api/v1/origin/bootstrap",
            "/api/v1/origin/deviations",
            "/api/v1/origin/compute",
            "/api/v1/origin/launch-positions",
            "/api/v1/commands",
            "/api/v1/commands/{command_id}",
            "/api/v1/commands/recent",
            "/api/v1/commands/active",
            "/api/v1/commands/statistics",
            "/api/v1/commands/{command_id}/cancel",
            "/api/v1/command-reports/execution-start",
            "/api/v1/command-reports/execution-result",
            "/get-config-data",
            "/save-config-data",
            "/validate-config",
            "/get-drone-positions",
            "/get-trajectory-first-row",
            "/get-swarm-data",
            "/save-swarm-data",
            "/submit_command",
            "/command/{command_id}",
            "/commands/recent",
            "/commands/active",
            "/commands/statistics",
            "/command/{command_id}/cancel",
            "/command/execution-start",
            "/command/execution-result",
            "/git-status",
            "/sync-repos",
            "/get-origin",
            "/set-origin",
            "/get-gps-global-origin",
            "/elevation",
            "/get-origin-for-drone",
            "/get-position-deviations",
            "/compute-origin",
            "/get-desired-launch-positions",
            "/import-show",
            "/download-raw-show",
            "/download-processed-show",
            "/get-show-info",
            "/get-custom-show-info",
            "/import-custom-show",
            "/get-comprehensive-metrics",
            "/get-safety-report",
            "/validate-trajectory",
            "/deploy-show",
            "/get-show-plots/{filename}",
            "/get-show-plots",
            "/get-custom-show-image",
            "/get-gcs-config",
            "/save-gcs-config",
            "/get-gcs-git-status",
            "/get-drone-git-status/{drone_id}",
            "/get-network-info",
            "/request-new-leader",
            "/api/swarm/leaders",
            "/api/swarm/trajectory/upload/{leader_id}",
            "/api/swarm/trajectory/process",
            "/api/swarm/trajectory/recommendation",
            "/api/swarm/trajectory/status",
            "/api/swarm/trajectory/policy",
            "/api/swarm/trajectory/clear-processed",
            "/api/swarm/trajectory/clear",
            "/api/swarm/trajectory/clear-leader/{leader_id}",
            "/api/swarm/trajectory/remove/{leader_id}",
            "/api/swarm/trajectory/download/{drone_id}",
            "/api/swarm/trajectory/download-kml/{drone_id}",
            "/api/swarm/trajectory/download-cluster-kml/{leader_id}",
            "/api/swarm/trajectory/clear-drone/{drone_id}",
            "/api/swarm/trajectory/commit",
            "/api/logs/sources",
            "/api/logs/sessions",
            "/api/logs/sessions/{session_id}",
            "/api/logs/stream",
            "/api/logs/frontend",
            "/api/logs/export",
            "/api/logs/drone/{drone_id}/export",
            "/api/logs/drone/{drone_id}/sessions",
            "/api/logs/drone/{drone_id}/sessions/{session_id}",
            "/api/logs/drone/{drone_id}/stream",
            "/api/logs/config",
            "/api/sar/mission/plan",
            "/api/sar/mission/launch",
            "/api/sar/mission/{mission_id}/status",
            "/api/sar/mission/{mission_id}/pause",
            "/api/sar/mission/{mission_id}/resume",
            "/api/sar/mission/{mission_id}/abort",
            "/api/sar/mission/{mission_id}/progress",
            "/api/sar/poi",
            "/api/sar/poi/{poi_id}",
            "/api/sar/elevation/batch",
            "/ws/telemetry",
            "/ws/heartbeats",
            "/ws/git-status",
        }

        assert expected_routes.issubset(routes)

    def test_v1_health_alias(self, test_client):
        response = test_client.get("/api/v1/system/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data
        assert "version" in data

    def test_v1_fleet_telemetry_alias(self, test_client):
        response = test_client.get("/api/v1/fleet/telemetry")

        assert response.status_code == 200
        data = response.json()
        assert "telemetry" in data
        assert "total_drones" in data
        assert "online_drones" in data

    def test_v1_fleet_heartbeat_post_alias(self, test_client):
        payload = {
            "hw_id": "1",
            "pos_id": 1,
            "detected_pos_id": 1,
            "ip": "192.168.1.101",
            "timestamp": 1700000000000,
            "network_info": {},
        }

        response = test_client.post("/api/v1/fleet/heartbeats", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Heartbeat received"

    def test_v1_fleet_heartbeats_alias(self, test_client):
        response = test_client.get("/api/v1/fleet/heartbeats")

        assert response.status_code == 200
        data = response.json()
        assert "heartbeats" in data
        assert "online_count" in data
        assert "timestamp" in data

    def test_v1_fleet_network_status_alias(self, test_client):
        response = test_client.get("/api/v1/fleet/network-status")

        assert response.status_code == 200
        data = response.json()
        assert "network_status" in data
        assert "reachable_count" in data
        assert "timestamp" in data

    def test_v1_fleet_config_alias(self, test_client):
        response = test_client.get("/api/v1/config/fleet")

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @patch('app_fastapi.save_config')
    @patch('app_fastapi.validate_and_process_config')
    def test_v1_fleet_config_put_alias(self, mock_validate, mock_save, test_client, mock_config):
        del mock_save
        mock_validate.return_value = {'updated_config': mock_config}

        response = test_client.request("PUT", "/api/v1/config/fleet", json=mock_config)

        assert response.status_code == 200
        assert response.json()["success"] is True

    @patch('app_fastapi.validate_and_process_config')
    def test_v1_fleet_config_validation_alias(self, mock_validate, test_client, mock_config):
        mock_validate.return_value = {'updated_config': mock_config, 'summary': {}}

        response = test_client.post("/api/v1/config/fleet/validation", json=mock_config)

        assert response.status_code == 200
        assert "summary" in response.json()

    def test_v1_fleet_trajectory_start_positions_alias(self, test_client):
        response = test_client.get("/api/v1/config/fleet/trajectory-start-positions")

        assert response.status_code == 200
        assert isinstance(response.json(), list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
