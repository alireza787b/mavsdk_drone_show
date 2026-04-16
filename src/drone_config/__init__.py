# src/drone_config/__init__.py
"""
Drone Configuration Package
===========================
Modular drone configuration management following SOLID principles.

This package provides:
- ConfigLoader: Static utilities for loading configuration files
- DroneConfigData: Immutable configuration data
- DroneState: Mutable runtime state
- DroneConfig: Backward-compatible facade combining all components

Usage (backward compatible):
    from src.drone_config import DroneConfig
    config = DroneConfig(drones, hw_id=1)

Usage (new modular approach):
    from src.drone_config import ConfigLoader, DroneConfigData, DroneState
    hw_id = ConfigLoader.get_hw_id()
    config_data = DroneConfigData(...)
    state = DroneState(drones)
"""

from typing import Dict, Any, Optional, List

from src.params import Params
from src.drone_config.config_loader import ConfigLoader
from src.drone_config.drone_config_data import DroneConfigData
from src.drone_config.drone_state import DroneState

# Export components for modular usage
__all__ = ['DroneConfig', 'ConfigLoader', 'DroneConfigData', 'DroneState']


class DroneConfig:
    """
    Backward-compatible facade for drone configuration.

    This class maintains the exact same API as the original DroneConfig,
    but delegates to the new modular components internally.

    All existing code using DroneConfig continues to work unchanged.
    """

    def __init__(self, drones: Optional[Dict] = None, hw_id: Optional[int] = None):
        """
        Initialize drone configuration.

        Args:
            drones: Dictionary of all drones in the swarm
            hw_id: Optional hardware ID. If not provided, read from .hwID file.
        """
        # TODO(deferred): Validate config on drone boot — query GCS for
        # duplicate pos_ids and refuse to arm if collision detected.
        # See docs/TODO_deferred.md #5

        # Load configuration using static loader
        self._hw_id = ConfigLoader.get_hw_id(hw_id)
        config = ConfigLoader.read_config(self._hw_id) if self._hw_id else None
        swarm = ConfigLoader.read_swarm(self._hw_id) if self._hw_id else None
        all_configs = ConfigLoader.load_all_configs()

        # Determine pos_id from config or hw_id
        pos_id = int(config.get('pos_id', self._hw_id)) if config else (int(self._hw_id) if self._hw_id else 0)

        # Create immutable config data
        self._config_data = DroneConfigData(
            hw_id=self._hw_id or 0,
            config=config or {},
            swarm=swarm,
            pos_id=pos_id,
            takeoff_altitude=Params.default_takeoff_alt,
            all_configs=all_configs
        )

        # Create mutable state
        self._state = DroneState(drones)

    # =========================================================================
    # Configuration Properties (from DroneConfigData)
    # =========================================================================

    @property
    def hw_id(self) -> int:
        """Hardware ID of this drone."""
        return self._config_data.hw_id

    @property
    def config(self) -> Dict[str, Any]:
        """Configuration dictionary from config.json."""
        return self._config_data.config

    @property
    def swarm(self) -> Optional[Dict[str, Any]]:
        """Swarm configuration dictionary."""
        return self._config_data.swarm

    @property
    def pos_id(self) -> int:
        """Position ID for show choreography."""
        return self._config_data.pos_id

    @property
    def takeoff_altitude(self) -> float:
        """Takeoff altitude - runtime value or default from config."""
        if self._state.runtime_takeoff_altitude is not None:
            return self._state.runtime_takeoff_altitude
        return self._config_data.takeoff_altitude

    @takeoff_altitude.setter
    def takeoff_altitude(self, value: float):
        """Set runtime takeoff altitude for current command."""
        self._state.runtime_takeoff_altitude = value

    @property
    def runtime_takeoff_altitude(self) -> Optional[float]:
        """Direct access to runtime takeoff altitude override."""
        return self._state.runtime_takeoff_altitude

    @runtime_takeoff_altitude.setter
    def runtime_takeoff_altitude(self, value: Optional[float]):
        """Set or clear runtime takeoff altitude override."""
        self._state.runtime_takeoff_altitude = value

    @property
    def all_configs(self) -> Dict[int, Dict[str, float]]:
        """All drone position configurations."""
        return self._config_data.all_configs

    # =========================================================================
    # State Properties (from DroneState) - Getters and Setters
    # =========================================================================

    @property
    def detected_pos_id(self) -> int:
        return self._state.detected_pos_id

    @detected_pos_id.setter
    def detected_pos_id(self, value: int):
        self._state.detected_pos_id = value

    @property
    def state(self) -> int:
        return self._state.state

    @state.setter
    def state(self, value: int):
        self._state.state = value

    @property
    def mission(self) -> int:
        return self._state.mission

    @mission.setter
    def mission(self, value: int):
        self._state.mission = value

    @property
    def last_mission(self) -> int:
        return self._state.last_mission

    @last_mission.setter
    def last_mission(self, value: int):
        self._state.last_mission = value

    @property
    def trigger_time(self) -> float:
        return self._state.trigger_time

    @trigger_time.setter
    def trigger_time(self, value: float):
        self._state.trigger_time = value

    @property
    def drone_setup(self) -> Any:
        return self._state.drone_setup

    @drone_setup.setter
    def drone_setup(self, value: Any):
        self._state.drone_setup = value

    @property
    def current_command_id(self) -> Optional[str]:
        return self._state.current_command_id

    @current_command_id.setter
    def current_command_id(self, value: Optional[str]):
        self._state.current_command_id = value

    @property
    def update_branch(self) -> Optional[str]:
        return self._state.update_branch

    @update_branch.setter
    def update_branch(self, value: Optional[str]):
        self._state.update_branch = value

    @property
    def reboot_after_params(self) -> Optional[bool]:
        return self._state.reboot_after_params

    @reboot_after_params.setter
    def reboot_after_params(self, value: Optional[bool]):
        self._state.reboot_after_params = value

    @property
    def quickscout_mission_id(self) -> Optional[str]:
        return self._state.quickscout_mission_id

    @quickscout_mission_id.setter
    def quickscout_mission_id(self, value: Optional[str]):
        self._state.quickscout_mission_id = value

    @property
    def quickscout_waypoints_file(self) -> Optional[str]:
        return self._state.quickscout_waypoints_file

    @quickscout_waypoints_file.setter
    def quickscout_waypoints_file(self, value: Optional[str]):
        self._state.quickscout_waypoints_file = value

    @property
    def quickscout_return_behavior(self) -> Optional[str]:
        return self._state.quickscout_return_behavior

    @quickscout_return_behavior.setter
    def quickscout_return_behavior(self, value: Optional[str]):
        self._state.quickscout_return_behavior = value

    @property
    def precision_move_request_file(self) -> Optional[str]:
        return self._state.precision_move_request_file

    @precision_move_request_file.setter
    def precision_move_request_file(self, value: Optional[str]):
        self._state.precision_move_request_file = value

    @property
    def auto_global_origin(self) -> Optional[bool]:
        return self._state.auto_global_origin

    @auto_global_origin.setter
    def auto_global_origin(self, value: Optional[bool]):
        self._state.auto_global_origin = value

    @property
    def use_global_setpoints(self) -> Optional[bool]:
        return self._state.use_global_setpoints

    @use_global_setpoints.setter
    def use_global_setpoints(self, value: Optional[bool]):
        self._state.use_global_setpoints = value

    @property
    def position(self) -> Dict[str, float]:
        return self._state.position

    @position.setter
    def position(self, value: Dict[str, float]):
        self._state.position = value

    @property
    def velocity(self) -> Dict[str, float]:
        return self._state.velocity

    @velocity.setter
    def velocity(self, value: Dict[str, float]):
        self._state.velocity = value

    @property
    def yaw(self) -> float:
        return self._state.yaw

    @yaw.setter
    def yaw(self, value: float):
        self._state.yaw = value

    @property
    def yaw_rate_deg_s(self) -> float:
        return self._state.yaw_rate_deg_s

    @yaw_rate_deg_s.setter
    def yaw_rate_deg_s(self, value: float):
        self._state.yaw_rate_deg_s = value

    @property
    def telemetry_timestamp_ms(self) -> int:
        return self._state.telemetry_timestamp_ms

    @telemetry_timestamp_ms.setter
    def telemetry_timestamp_ms(self, value: int):
        self._state.telemetry_timestamp_ms = value

    @property
    def telemetry_sequence(self) -> int:
        return self._state.telemetry_sequence

    @telemetry_sequence.setter
    def telemetry_sequence(self, value: int):
        self._state.telemetry_sequence = value

    @property
    def battery(self) -> float:
        return self._state.battery

    @battery.setter
    def battery(self, value: float):
        self._state.battery = value

    @property
    def last_update_timestamp(self) -> float:
        return self._state.last_update_timestamp

    @last_update_timestamp.setter
    def last_update_timestamp(self, value: float):
        self._state.last_update_timestamp = value

    @property
    def home_position(self) -> Any:
        return self._state.home_position

    @home_position.setter
    def home_position(self, value: Any):
        self._state.home_position = value

    @property
    def px4_home_position_set(self) -> bool:
        return self._state.px4_home_position_set

    @px4_home_position_set.setter
    def px4_home_position_set(self, value: bool):
        self._state.px4_home_position_set = value

    @property
    def home_position_source(self) -> str:
        return self._state.home_position_source

    @home_position_source.setter
    def home_position_source(self, value: str):
        self._state.home_position_source = value

    @property
    def gps_global_origin(self) -> Any:
        return self._state.gps_global_origin

    @gps_global_origin.setter
    def gps_global_origin(self, value: Any):
        self._state.gps_global_origin = value

    @property
    def target_drone(self) -> Any:
        return self._state.target_drone

    @target_drone.setter
    def target_drone(self, value: Any):
        self._state.target_drone = value

    @property
    def drones(self) -> Optional[Dict]:
        return self._state.drones

    @drones.setter
    def drones(self, value: Optional[Dict]):
        self._state.drones = value

    @property
    def hdop(self) -> float:
        return self._state.hdop

    @hdop.setter
    def hdop(self, value: float):
        self._state.hdop = value

    @property
    def vdop(self) -> float:
        return self._state.vdop

    @vdop.setter
    def vdop(self, value: float):
        self._state.vdop = value

    @property
    def gps_fix_type(self) -> int:
        return self._state.gps_fix_type

    @gps_fix_type.setter
    def gps_fix_type(self, value: int):
        self._state.gps_fix_type = value

    @property
    def satellites_visible(self) -> int:
        return self._state.satellites_visible

    @satellites_visible.setter
    def satellites_visible(self, value: int):
        self._state.satellites_visible = value

    @property
    def base_mode(self) -> int:
        return self._state.base_mode

    @base_mode.setter
    def base_mode(self, value: int):
        self._state.base_mode = value

    @property
    def custom_mode(self) -> int:
        return self._state.custom_mode

    @custom_mode.setter
    def custom_mode(self, value: int):
        self._state.custom_mode = value

    @property
    def system_status(self) -> int:
        return self._state.system_status

    @system_status.setter
    def system_status(self, value: int):
        self._state.system_status = value

    @property
    def is_armed(self) -> bool:
        return self._state.is_armed

    @is_armed.setter
    def is_armed(self, value: bool):
        self._state.is_armed = value

    @property
    def is_ready_to_arm(self) -> bool:
        return self._state.is_ready_to_arm

    @is_ready_to_arm.setter
    def is_ready_to_arm(self, value: bool):
        self._state.is_ready_to_arm = value

    @property
    def readiness_status(self) -> str:
        return self._state.readiness_status

    @readiness_status.setter
    def readiness_status(self, value: str):
        self._state.readiness_status = value

    @property
    def readiness_summary(self) -> str:
        return self._state.readiness_summary

    @readiness_summary.setter
    def readiness_summary(self, value: str):
        self._state.readiness_summary = value

    @property
    def readiness_checks(self) -> List[Dict[str, Any]]:
        return self._state.readiness_checks

    @readiness_checks.setter
    def readiness_checks(self, value: List[Dict[str, Any]]):
        self._state.readiness_checks = value

    @property
    def preflight_blockers(self) -> List[Dict[str, Any]]:
        return self._state.preflight_blockers

    @preflight_blockers.setter
    def preflight_blockers(self, value: List[Dict[str, Any]]):
        self._state.preflight_blockers = value

    @property
    def preflight_warnings(self) -> List[Dict[str, Any]]:
        return self._state.preflight_warnings

    @preflight_warnings.setter
    def preflight_warnings(self, value: List[Dict[str, Any]]):
        self._state.preflight_warnings = value

    @property
    def status_messages(self) -> List[Dict[str, Any]]:
        return self._state.status_messages

    @status_messages.setter
    def status_messages(self, value: List[Dict[str, Any]]):
        self._state.status_messages = value

    @property
    def preflight_last_update(self) -> int:
        return self._state.preflight_last_update

    @preflight_last_update.setter
    def preflight_last_update(self, value: int):
        self._state.preflight_last_update = value

    @property
    def local_position_ned(self) -> Dict[str, float]:
        return self._state.local_position_ned

    @local_position_ned.setter
    def local_position_ned(self, value: Dict[str, float]):
        self._state.local_position_ned = value

    @property
    def is_gyrometer_calibration_ok(self) -> bool:
        return self._state.is_gyrometer_calibration_ok

    @is_gyrometer_calibration_ok.setter
    def is_gyrometer_calibration_ok(self, value: bool):
        self._state.is_gyrometer_calibration_ok = value

    @property
    def is_accelerometer_calibration_ok(self) -> bool:
        return self._state.is_accelerometer_calibration_ok

    @is_accelerometer_calibration_ok.setter
    def is_accelerometer_calibration_ok(self, value: bool):
        self._state.is_accelerometer_calibration_ok = value

    @property
    def is_magnetometer_calibration_ok(self) -> bool:
        return self._state.is_magnetometer_calibration_ok

    @is_magnetometer_calibration_ok.setter
    def is_magnetometer_calibration_ok(self, value: bool):
        self._state.is_magnetometer_calibration_ok = value

    # =========================================================================
    # Methods (delegating to appropriate component)
    # =========================================================================

    def get_hw_id(self, hw_id: Optional[int] = None) -> Optional[int]:
        """Get hardware ID (static method wrapper for backward compatibility)."""
        return ConfigLoader.get_hw_id(hw_id)

    def read_file(self, filename: str, source: str, hw_id: int) -> Optional[Dict[str, Any]]:
        """Read CSV file (static method wrapper for backward compatibility)."""
        return ConfigLoader.read_file(filename, source, hw_id)

    def read_config(self) -> Optional[Dict[str, Any]]:
        """Read configuration file."""
        return ConfigLoader.read_config(self._hw_id)

    def read_swarm(self) -> Optional[Dict[str, Any]]:
        """Read swarm configuration file."""
        return ConfigLoader.read_swarm(self._hw_id)

    def fetch_online_config(self, url: str, local_filename: str) -> Optional[Dict[str, Any]]:
        """Fetch online configuration."""
        return ConfigLoader.fetch_online_config(url, local_filename, self._hw_id)

    def load_all_configs(self) -> Dict[int, Dict[str, float]]:
        """Load all drone configurations."""
        return ConfigLoader.load_all_configs()

    def find_target_drone(self) -> None:
        """Find target drone for swarm following."""
        self._state.find_target_drone(self._hw_id, self._config_data.swarm)

    def radian_to_degrees_heading(self, yaw_radians: float) -> float:
        """Convert radians to degrees heading (0-360)."""
        return DroneState.radian_to_degrees_heading(yaw_radians)

    def get_serial_port(self) -> str:
        """Get serial port configuration."""
        return self._config_data.get_serial_port()

    def get_baudrate(self) -> int:
        """Get baudrate configuration."""
        return self._config_data.get_baudrate()

    def update(self, **kwargs) -> None:
        """
        Update drone state from telemetry data.

        Only updates mutable state fields (not configuration).
        Used by drone_communicator for telemetry updates.

        Args:
            **kwargs: Field names and values to update
        """
        # Map telemetry field names to internal state field names
        field_mapping = {
            'battery_voltage': 'battery',
            'update_time': 'last_update_timestamp'
        }

        # Set of mutable fields that can be updated from telemetry
        mutable_fields = {
            'state', 'mission', 'trigger_time', 'position', 'velocity',
            'yaw', 'battery', 'last_update_timestamp', 'hdop', 'vdop',
            'gps_fix_type', 'satellites_visible', 'is_armed', 'is_ready_to_arm'
        }

        for key, value in kwargs.items():
            # Map telemetry field name to internal field name
            field = field_mapping.get(key, key)

            if field in mutable_fields and hasattr(self, field):
                try:
                    setattr(self, field, value)
                except AttributeError:
                    # Skip fields that don't have setters
                    pass
