# src/drone_config/drone_state.py
"""
Drone State
===========
Mutable runtime state for drone operations.

This class holds all state that changes during drone operation,
including telemetry, mission state, and sensor data.
"""

import logging
import math
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class DroneState:
    """
    Mutable runtime state for a drone.

    Contains all state that changes during operation, including:
    - Telemetry data (position, velocity, attitude)
    - Mission state (current mission, trigger time)
    - GPS data (hdop, vdop, fix type, satellites)
    - MAVLink status (armed, flight mode, system status)
    - Sensor calibration status

    Attributes:
        detected_pos_id: Detected position ID (0 = undetected)
        state: Current state code
        mission: Current mission code
        last_mission: Previous mission code
        trigger_time: Time of last trigger event
        drone_setup: Reference to DroneSetup instance
        auto_global_origin: Phase 2 auto-correction mode
        use_global_setpoints: Local/Global mode flag
        position: GPS position dict {lat, long, alt}
        velocity: Velocity dict {north, east, down}
        yaw: Yaw angle in degrees
        battery: Battery voltage in volts
        last_update_timestamp: Timestamp of last telemetry update
        home_position: Home position from autopilot
        gps_global_origin: GPS global origin data
        target_drone: Target drone for swarm operations
        drones: Reference to all drones dict
        hdop: Horizontal dilution of precision
        vdop: Vertical dilution of precision
        gps_fix_type: GPS fix status (0-6)
        satellites_visible: Number of visible satellites
        base_mode: MAVLink base mode flags
        custom_mode: PX4-specific flight mode
        system_status: System status code
        is_armed: Whether drone is armed
        is_ready_to_arm: Whether pre-arm checks pass
        local_position_ned: Local NED position data
        is_gyrometer_calibration_ok: Gyro calibration status
        is_accelerometer_calibration_ok: Accelerometer calibration status
        is_magnetometer_calibration_ok: Magnetometer calibration status
    """

    def __init__(self, drones: Optional[Dict] = None):
        """
        Initialize drone state with default values.

        Args:
            drones: Optional reference to all drones dictionary
        """
        # Mission state
        self.detected_pos_id: int = 0
        self.state: int = 0
        self.mission: int = 0
        self.last_mission: int = 0
        self.trigger_time: float = 0
        self.drone_setup: Any = None
        self.current_command_id: Optional[str] = None  # For command tracking
        self.runtime_takeoff_altitude: Optional[float] = None  # Runtime override for takeoff command

        # Phase 2: Auto Global Origin Correction flags
        self.auto_global_origin: Optional[bool] = None
        self.use_global_setpoints: Optional[bool] = None

        # Telemetry: Position, velocity, attitude
        self.position: Dict[str, float] = {'lat': 0, 'long': 0, 'alt': 0}
        self.velocity: Dict[str, float] = {'north': 0, 'east': 0, 'down': 0}
        self.yaw: float = 0

        # Battery
        self.battery: float = 0
        self.last_update_timestamp: float = 0

        # Home and origin positions
        self.home_position: Any = None
        self.px4_home_position_set: bool = False
        self.home_position_source: str = "unknown"
        self.gps_global_origin: Any = None

        # Swarm references
        self.target_drone: Any = None
        self.drones: Optional[Dict] = drones

        # GPS quality data
        self.hdop: float = 0
        self.vdop: float = 0
        self.gps_fix_type: int = 0  # 0=No GPS, 1=No Fix, 2=2D, 3=3D, 4=DGPS, 5=RTK Float, 6=RTK Fixed
        self.satellites_visible: int = 0

        # MAVLink HEARTBEAT message fields
        self.base_mode: int = 0
        self.custom_mode: int = 0
        self.system_status: int = 0

        # Derived flags
        self.is_armed: bool = False
        self.is_ready_to_arm: bool = False
        self.readiness_status: str = "unknown"
        self.readiness_summary: str = "Waiting for PX4 telemetry"
        self.readiness_checks: list[Dict[str, Any]] = []
        self.preflight_blockers: list[Dict[str, Any]] = []
        self.preflight_warnings: list[Dict[str, Any]] = []
        self.status_messages: list[Dict[str, Any]] = []
        self.preflight_last_update: int = 0

        # LOCAL_POSITION_NED data
        self.local_position_ned: Dict[str, float] = {
            'time_boot_ms': 0,
            'x': 0.0,
            'y': 0.0,
            'z': 0.0,
            'vx': 0.0,
            'vy': 0.0,
            'vz': 0.0
        }

        # Sensor calibration statuses
        self.is_gyrometer_calibration_ok: bool = False
        self.is_accelerometer_calibration_ok: bool = False
        self.is_magnetometer_calibration_ok: bool = False

    def find_target_drone(self, hw_id: int, swarm: Optional[Dict]) -> None:
        """
        Determine which drone this drone should follow in a swarm.

        TODO(deferred): Auto-update follow chains when role swaps occur.
        Currently follow references hw_id; if a drone is replaced, followers
        lose their target. See docs/TODO_deferred.md #2

        Args:
            hw_id: This drone's hardware ID
            swarm: Swarm configuration dictionary
        """
        if swarm is None:
            logger.warning(f"Drone {hw_id} has no swarm configuration.")
            return

        follow_hw_id = int(swarm.get('follow', 0))
        if follow_hw_id == 0:
            logger.info(f"Drone {hw_id} is a master drone and not following anyone.")
        elif str(follow_hw_id) == str(hw_id):
            logger.error(f"Drone {hw_id} is set to follow itself. This is not allowed.")
        else:
            if self.drones:
                self.target_drone = self.drones.get(follow_hw_id)
                if self.target_drone:
                    logger.info(f"Drone {hw_id} is following drone {self.target_drone.hw_id}")
                else:
                    logger.error(f"No target drone found for drone with hw_id: {hw_id}")
            else:
                logger.error(f"Drones dictionary not available for drone {hw_id}")

    @staticmethod
    def radian_to_degrees_heading(yaw_radians: float) -> float:
        """
        Convert yaw from radians to degrees and normalize to 0-360.

        Args:
            yaw_radians: Yaw angle in radians

        Returns:
            Yaw angle in degrees (0-360)
        """
        yaw_degrees = math.degrees(yaw_radians)
        return yaw_degrees if yaw_degrees >= 0 else yaw_degrees + 360
