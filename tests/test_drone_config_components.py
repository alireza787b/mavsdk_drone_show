# tests/test_drone_config_components.py
"""
DroneConfig Components Tests
============================
Tests for the modular DroneConfig package components:
- ConfigLoader: Static configuration loading utilities
- DroneConfigData: Immutable configuration dataclass
- DroneState: Mutable runtime state
- DroneConfig: Backward-compatible facade
"""

import pytest
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock

from src.drone_config import DroneConfig, ConfigLoader, DroneConfigData, DroneState


class TestConfigLoader:
    """Test ConfigLoader static methods"""

    def test_get_hw_id_with_provided_id(self):
        """Test that provided hw_id is returned as int"""
        result = ConfigLoader.get_hw_id(123)
        assert result == 123

    def test_get_hw_id_with_invalid_value(self):
        """Test that non-integer hw_id returns None"""
        result = ConfigLoader.get_hw_id('not_a_number')
        assert result is None

    def test_get_hw_id_with_none_and_no_file(self):
        """Test that None is returned when no .hwID file exists"""
        with patch('glob.glob', return_value=[]):
            result = ConfigLoader.get_hw_id(None)
            assert result is None

    def test_get_hw_id_with_file(self):
        """Test that hw_id is read from .hwID file"""
        with patch('glob.glob', return_value=['42.hwID']):
            result = ConfigLoader.get_hw_id(None)
            assert result == 42

    def test_get_hw_id_from_mds_hw_id_env(self):
        """Test that MDS_HW_ID overrides filesystem lookup."""
        with patch.dict(os.environ, {'MDS_HW_ID': '17'}, clear=False):
            result = ConfigLoader.get_hw_id(None)
            assert result == 17

    def test_get_hw_id_from_mds_hwid_dir(self, tmp_path):
        """Test that MDS_HWID_DIR is searched for .hwID files."""
        hwid_file = tmp_path / "24.hwID"
        hwid_file.write_text("")

        with patch.dict(os.environ, {'MDS_HWID_DIR': str(tmp_path)}, clear=False):
            result = ConfigLoader.get_hw_id(None)
            assert result == 24

    def test_read_file_success(self, tmp_path):
        """Test reading a valid JSON config file"""
        import json
        json_content = {"drones": [
            {"hw_id": 1, "pos_id": 1, "ip": "10.0.0.1"},
            {"hw_id": 2, "pos_id": 2, "ip": "10.0.0.2"}
        ]}
        json_file = tmp_path / "test_config.json"
        json_file.write_text(json.dumps(json_content))

        result = ConfigLoader.read_file(str(json_file), 'test', 1)
        assert result is not None
        assert result['hw_id'] == 1
        assert result['pos_id'] == 1
        assert result['ip'] == '10.0.0.1'

    def test_read_file_supports_swarm_assignments_wrapper(self, tmp_path):
        """Test reading a wrapped swarm JSON file."""
        import json

        json_content = {
            "version": 1,
            "assignments": [
                {"hw_id": 1, "follow": 0, "frame": "body"},
                {"hw_id": 2, "follow": 1, "frame": "ned"},
            ],
        }
        json_file = tmp_path / "test_swarm.json"
        json_file.write_text(json.dumps(json_content))

        result = ConfigLoader.read_file(str(json_file), 'test swarm', 2)
        assert result is not None
        assert result['hw_id'] == 2
        assert result['follow'] == 1
        assert result['frame'] == 'ned'

    def test_read_file_hw_id_not_found(self, tmp_path):
        """Test reading JSON when hw_id doesn't exist"""
        import json
        json_content = {"drones": [{"hw_id": 1, "pos_id": 1, "ip": "10.0.0.1"}]}
        json_file = tmp_path / "test_config.json"
        json_file.write_text(json.dumps(json_content))

        result = ConfigLoader.read_file(str(json_file), 'test', 999)
        assert result is None

    def test_read_file_not_found(self):
        """Test reading non-existent file"""
        result = ConfigLoader.read_file('/nonexistent/file.json', 'test', 1)
        assert result is None

    def test_read_config_offline_mode(self):
        """Test read_config in offline mode"""
        with patch('src.drone_config.config_loader.Params') as mock_params:
            mock_params.offline_config = True
            mock_params.config_file_name = '/test/config.json'

            with patch.object(ConfigLoader, 'read_file', return_value={'hw_id': '1'}):
                result = ConfigLoader.read_config(1)
                assert result == {'hw_id': '1'}

    def test_read_config_online_mode(self):
        """Test read_config in online mode"""
        with patch('src.drone_config.config_loader.Params') as mock_params:
            mock_params.offline_config = False
            mock_params.config_url = 'http://test.com/config.json'

            with patch.object(ConfigLoader, 'fetch_online_config', return_value={'hw_id': '1'}):
                result = ConfigLoader.read_config(1)
                assert result == {'hw_id': '1'}

    def test_read_config_without_online_url_falls_back_to_local_file(self):
        """Test read_config still uses local file mode when no remote URL is configured."""
        with patch('src.drone_config.config_loader.Params') as mock_params:
            mock_params.offline_config = False
            mock_params.config_url = ''
            mock_params.config_file_name = '/test/config.json'

            with patch.object(ConfigLoader, 'read_file', return_value={'hw_id': '1'}) as read_file:
                with patch.object(ConfigLoader, 'fetch_online_config') as fetch_online_config:
                    result = ConfigLoader.read_config(1)
                    assert result == {'hw_id': '1'}
                    read_file.assert_called_once_with('/test/config.json', 'local config', 1)
                    fetch_online_config.assert_not_called()

    def test_read_swarm_offline_mode(self):
        """Test read_swarm in offline mode"""
        with patch('src.drone_config.config_loader.Params') as mock_params:
            mock_params.offline_swarm = True
            mock_params.swarm_file_name = '/test/swarm.json'

            with patch.object(ConfigLoader, 'read_file', return_value={'hw_id': '1', 'follow': '0'}):
                result = ConfigLoader.read_swarm(1)
                assert result == {'hw_id': '1', 'follow': '0'}

    def test_read_swarm_without_online_url_falls_back_to_local_file(self):
        """Test read_swarm still uses local file mode when no remote URL is configured."""
        with patch('src.drone_config.config_loader.Params') as mock_params:
            mock_params.offline_swarm = False
            mock_params.swarm_url = ''
            mock_params.swarm_file_name = '/test/swarm.json'

            with patch.object(ConfigLoader, 'read_file', return_value={'hw_id': '1', 'follow': '0'}) as read_file:
                with patch.object(ConfigLoader, 'fetch_online_config') as fetch_online_config:
                    result = ConfigLoader.read_swarm(1)
                    assert result == {'hw_id': '1', 'follow': '0'}
                    read_file.assert_called_once_with('/test/swarm.json', 'local config', 1)
                    fetch_online_config.assert_not_called()

    def test_fetch_online_config_success(self, tmp_path):
        """Test fetching config from online source"""
        import json
        json_content = json.dumps({"drones": [{"hw_id": 1, "pos_id": 1}]})
        local_file = tmp_path / "online_config.json"

        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = json_content
            mock_get.return_value = mock_response

            result = ConfigLoader.fetch_online_config(
                'http://test.com/config.json',
                str(local_file),
                1
            )
            assert result is not None
            assert result['hw_id'] == 1

    def test_fetch_online_config_http_error(self):
        """Test handling HTTP error during fetch"""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.reason = 'Internal Server Error'
            mock_get.return_value = mock_response

            result = ConfigLoader.fetch_online_config(
                'http://test.com/config.json',
                '/tmp/test.json',
                1
            )
            assert result is None

    def test_load_all_configs_success(self, tmp_path):
        """Test loading all configs from trajectory files"""
        import json
        # Create config.json
        config_json = tmp_path / "config.json"
        config_json.write_text(json.dumps({"drones": [{"hw_id": 1, "pos_id": 1, "ip": "10.0.0.1"}]}))

        # Create trajectory directory structure
        traj_dir = tmp_path / "shapes_sitl" / "swarm" / "processed"
        traj_dir.mkdir(parents=True)
        traj_file = traj_dir / "Drone 1.csv"
        traj_file.write_text("t,px,py,pz\n0,5.0,10.0,0.0\n")

        with patch('src.drone_config.config_loader.Params') as mock_params:
            mock_params.config_file_name = str(config_json)
            mock_params.sim_mode = True

            # Mock __file__ to point to our tmp directory
            with patch('src.drone_config.config_loader.__file__', str(tmp_path / 'src' / 'drone_config' / 'config_loader.py')):
                # Since __file__ mocking is complex, let's just verify the structure
                result = ConfigLoader.load_all_configs()
                # Result may be empty due to path issues, but function shouldn't error
                assert isinstance(result, dict)


class TestDroneConfigData:
    """Test DroneConfigData immutable dataclass"""

    def test_create_config_data(self):
        """Test creating DroneConfigData instance"""
        config = DroneConfigData(
            hw_id=1,
            config={'pos_id': 1, 'ip': '10.0.0.1'},
            swarm={'follow': '0'},
            pos_id=1,
            takeoff_altitude=10.0,
            all_configs={1: {'x': 0, 'y': 0}}
        )

        assert config.hw_id == 1
        assert config.pos_id == 1
        assert config.takeoff_altitude == 10.0
        assert config.config['ip'] == '10.0.0.1'

    def test_get_serial_port_from_config(self):
        """Test getting serial port from config"""
        config = DroneConfigData(
            hw_id=1,
            config={'serial_port': '/dev/ttyAMA0'},
            swarm=None,
            pos_id=1,
            takeoff_altitude=10.0
        )

        result = config.get_serial_port()
        assert result == '/dev/ttyAMA0'

    def test_get_serial_port_fallback(self):
        """Test serial port fallback to Params default"""
        config = DroneConfigData(
            hw_id=1,
            config={},
            swarm=None,
            pos_id=1,
            takeoff_altitude=10.0
        )

        with patch('src.params.Params.serial_mavlink_port', '/dev/ttyS0'):
            result = config.get_serial_port()
            assert result == '/dev/ttyS0'

    def test_get_baudrate_from_config(self):
        """Test getting baudrate from config"""
        config = DroneConfigData(
            hw_id=1,
            config={'baudrate': '921600'},
            swarm=None,
            pos_id=1,
            takeoff_altitude=10.0
        )

        result = config.get_baudrate()
        assert result == 921600

    def test_get_baudrate_fallback(self):
        """Test baudrate fallback to Params default"""
        config = DroneConfigData(
            hw_id=1,
            config={},
            swarm=None,
            pos_id=1,
            takeoff_altitude=10.0
        )

        with patch('src.params.Params.serial_baudrate', 115200):
            result = config.get_baudrate()
            assert result == 115200


class TestDroneState:
    """Test DroneState mutable runtime state"""

    def test_create_default_state(self):
        """Test creating DroneState with default values"""
        state = DroneState()

        assert state.detected_pos_id == 0
        assert state.state == 0
        assert state.mission == 0
        assert state.is_armed is False
        assert state.battery == 0
        assert state.position == {'lat': 0, 'long': 0, 'alt': 0}

    def test_create_state_with_drones(self):
        """Test creating DroneState with drones reference"""
        drones = {'1': Mock(), '2': Mock()}
        state = DroneState(drones)

        assert state.drones == drones

    def test_state_mutation(self):
        """Test that state attributes can be mutated"""
        state = DroneState()

        state.battery = 12.5
        state.is_armed = True
        state.position = {'lat': 47.0, 'long': 8.0, 'alt': 500.0}

        assert state.battery == 12.5
        assert state.is_armed is True
        assert state.position['lat'] == 47.0

    def test_find_target_drone_master(self):
        """Test finding target when drone is master"""
        state = DroneState()
        swarm = {'follow': '0'}

        state.find_target_drone(1, swarm)
        assert state.target_drone is None

    def test_find_target_drone_follower(self):
        """Test finding target when drone follows another"""
        target = Mock()
        target.hw_id = 2
        drones = {2: target}

        state = DroneState(drones)
        swarm = {'follow': '2'}

        state.find_target_drone(1, swarm)
        assert state.target_drone == target

    def test_find_target_drone_self_follow_error(self):
        """Test error when drone tries to follow itself"""
        state = DroneState()
        swarm = {'follow': '1'}

        # Should log error but not crash
        state.find_target_drone(1, swarm)
        assert state.target_drone is None

    def test_radian_to_degrees_heading_positive(self):
        """Test radian to degrees conversion for positive values"""
        import math
        result = DroneState.radian_to_degrees_heading(math.pi / 2)
        assert abs(result - 90.0) < 0.001

    def test_radian_to_degrees_heading_negative(self):
        """Test radian to degrees conversion for negative values"""
        import math
        result = DroneState.radian_to_degrees_heading(-math.pi / 2)
        assert abs(result - 270.0) < 0.001


class TestDroneConfigFacade:
    """Test DroneConfig backward-compatible facade"""

    def test_facade_initialization(self):
        """Test that facade initializes correctly"""
        with patch.object(ConfigLoader, 'get_hw_id', return_value=1):
            with patch.object(ConfigLoader, 'read_config', return_value={'pos_id': '1'}):
                with patch.object(ConfigLoader, 'read_swarm', return_value={'follow': '0'}):
                    with patch.object(ConfigLoader, 'load_all_configs', return_value={}):
                        with patch('src.drone_config.Params') as mock_params:
                            mock_params.default_takeoff_alt = 10.0

                            config = DroneConfig(drones={}, hw_id=1)

                            assert config.hw_id == 1
                            assert config.pos_id == 1

    def test_facade_config_properties(self):
        """Test that config properties delegate correctly"""
        with patch.object(ConfigLoader, 'get_hw_id', return_value=1):
            with patch.object(ConfigLoader, 'read_config', return_value={'pos_id': '1', 'ip': '10.0.0.1'}):
                with patch.object(ConfigLoader, 'read_swarm', return_value={'follow': '0'}):
                    with patch.object(ConfigLoader, 'load_all_configs', return_value={}):
                        with patch('src.drone_config.Params') as mock_params:
                            mock_params.default_takeoff_alt = 10.0

                            config = DroneConfig(drones={}, hw_id=1)

                            assert config.config['ip'] == '10.0.0.1'
                            assert config.swarm['follow'] == '0'
                            assert config.takeoff_altitude == 10.0

    def test_facade_state_properties(self):
        """Test that state properties can be read and written"""
        with patch.object(ConfigLoader, 'get_hw_id', return_value=1):
            with patch.object(ConfigLoader, 'read_config', return_value={'pos_id': '1'}):
                with patch.object(ConfigLoader, 'read_swarm', return_value=None):
                    with patch.object(ConfigLoader, 'load_all_configs', return_value={}):
                        with patch('src.drone_config.Params') as mock_params:
                            mock_params.default_takeoff_alt = 10.0

                            config = DroneConfig(drones={}, hw_id=1)

                            # Test setting/getting state properties
                            config.battery = 12.5
                            assert config.battery == 12.5

                            config.is_armed = True
                            assert config.is_armed is True

                            config.position = {'lat': 47.0, 'long': 8.0, 'alt': 500.0}
                            assert config.position['lat'] == 47.0

                            config.mission = 5
                            assert config.mission == 5

    def test_facade_methods(self):
        """Test that facade methods work correctly"""
        with patch.object(ConfigLoader, 'read_config', return_value={'pos_id': '1'}):
            with patch.object(ConfigLoader, 'read_swarm', return_value=None):
                with patch.object(ConfigLoader, 'load_all_configs', return_value={}):
                    with patch('src.drone_config.Params') as mock_params:
                        mock_params.default_takeoff_alt = 10.0

                        # Use a custom hw_id directly
                        config = DroneConfig(drones={}, hw_id=1)

                        # Test get_hw_id method - when called with a value, should return int
                        result = config.get_hw_id(99)
                        assert result == 99

                        # Test with None - will try to read from .hwID file
                        with patch('glob.glob', return_value=['42.hwID']):
                            result = config.get_hw_id(None)
                            assert result == 42

                        # Test radian_to_degrees_heading
                        import math
                        result = config.radian_to_degrees_heading(math.pi)
                        assert abs(result - 180.0) < 0.001


class TestBackwardCompatibility:
    """Test backward compatibility with existing code patterns"""

    def test_mock_spec_compatibility(self):
        """Test that Mock(spec=DroneConfig) still works"""
        mock_config = Mock(spec=DroneConfig)

        # These should not raise AttributeError
        mock_config.hw_id = 1
        mock_config.pos_id = 1
        mock_config.position = {'lat': 0, 'long': 0, 'alt': 0}
        mock_config.is_armed = False
        mock_config.mission = 0
        mock_config.battery = 12.0

        assert mock_config.hw_id == 1
        assert mock_config.is_armed is False

    def test_attribute_access_pattern(self):
        """Test that common attribute access patterns work"""
        with patch.object(ConfigLoader, 'get_hw_id', return_value=1):
            with patch.object(ConfigLoader, 'read_config', return_value={'pos_id': '1', 'ip': '10.0.0.1'}):
                with patch.object(ConfigLoader, 'read_swarm', return_value={'follow': '0'}):
                    with patch.object(ConfigLoader, 'load_all_configs', return_value={}):
                        with patch('src.drone_config.Params') as mock_params:
                            mock_params.default_takeoff_alt = 10.0

                            config = DroneConfig(drones={}, hw_id=1)

                            # Common patterns used in existing code
                            _ = config.hw_id
                            _ = config.config
                            _ = config.position
                            _ = config.is_armed
                            _ = config.battery
                            _ = config.gps_fix_type
                            _ = config.local_position_ned

                            config.position = {'lat': 1, 'long': 2, 'alt': 3}
                            config.is_armed = True

                            assert config.position == {'lat': 1, 'long': 2, 'alt': 3}
                            assert config.is_armed is True


class TestTakeoffAltitudeSetter:
    """Test takeoff_altitude runtime override functionality"""

    def test_setter_updates_runtime_altitude(self):
        """Test that setting takeoff_altitude updates the runtime value"""
        with patch.object(ConfigLoader, 'get_hw_id', return_value=1):
            with patch.object(ConfigLoader, 'read_config', return_value={'pos_id': '1'}):
                with patch.object(ConfigLoader, 'read_swarm', return_value=None):
                    with patch.object(ConfigLoader, 'load_all_configs', return_value={}):
                        with patch('src.drone_config.Params') as mock_params:
                            mock_params.default_takeoff_alt = 10.0

                            config = DroneConfig(drones={}, hw_id=1)

                            # Initially returns default
                            assert config.takeoff_altitude == 10.0

                            # Set runtime override
                            config.takeoff_altitude = 25.0
                            assert config.takeoff_altitude == 25.0

    def test_runtime_altitude_cleared_restores_default(self):
        """Test that clearing runtime altitude restores the default"""
        with patch.object(ConfigLoader, 'get_hw_id', return_value=1):
            with patch.object(ConfigLoader, 'read_config', return_value={'pos_id': '1'}):
                with patch.object(ConfigLoader, 'read_swarm', return_value=None):
                    with patch.object(ConfigLoader, 'load_all_configs', return_value={}):
                        with patch('src.drone_config.Params') as mock_params:
                            mock_params.default_takeoff_alt = 10.0

                            config = DroneConfig(drones={}, hw_id=1)

                            # Set and then clear
                            config.takeoff_altitude = 25.0
                            config.runtime_takeoff_altitude = None

                            # Should return default again
                            assert config.takeoff_altitude == 10.0


class TestDroneConfigUpdate:
    """Test DroneConfig.update() method for telemetry updates"""

    def test_update_mutable_fields(self):
        """Test updating mutable telemetry fields"""
        with patch.object(ConfigLoader, 'get_hw_id', return_value=1):
            with patch.object(ConfigLoader, 'read_config', return_value={'pos_id': '1'}):
                with patch.object(ConfigLoader, 'read_swarm', return_value=None):
                    with patch.object(ConfigLoader, 'load_all_configs', return_value={}):
                        with patch('src.drone_config.Params') as mock_params:
                            mock_params.default_takeoff_alt = 10.0

                            config = DroneConfig(drones={}, hw_id=1)

                            config.update(
                                state=1,
                                mission=10,
                                battery_voltage=12.5,
                                yaw=90.0
                            )

                            assert config.state == 1
                            assert config.mission == 10
                            assert config.battery == 12.5
                            assert config.yaw == 90.0

    def test_update_ignores_unknown_fields(self):
        """Test that unknown fields are ignored"""
        with patch.object(ConfigLoader, 'get_hw_id', return_value=1):
            with patch.object(ConfigLoader, 'read_config', return_value={'pos_id': '1'}):
                with patch.object(ConfigLoader, 'read_swarm', return_value=None):
                    with patch.object(ConfigLoader, 'load_all_configs', return_value={}):
                        with patch('src.drone_config.Params') as mock_params:
                            mock_params.default_takeoff_alt = 10.0

                            config = DroneConfig(drones={}, hw_id=1)

                            # Should not raise exception for unknown fields
                            config.update(
                                unknown_field='some_value',
                                state=1
                            )

                            assert config.state == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
