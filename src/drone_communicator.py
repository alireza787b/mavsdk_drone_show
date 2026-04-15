#src/drone_communicator.py
import socket
import threading
import struct
import select
import time
import re
import json
from typing import Dict, Any, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from functions.data_utils import safe_float, safe_get, safe_int
from mds_logging import get_logger
from src.command_contract import PrecisionMoveRequest
from src.enums import Mission, State

logger = get_logger("drone_comm")
from src.drone_config import DroneConfig
from src.params import Params
from src.swarm_runtime_state import read_runtime_swarm_assignment
from src.telemetry_subscription_manager import TelemetrySubscriptionManager

class DroneCommunicator:
    """
    Handles communication with drones, including telemetry and command processing.
    """

    def __init__(self, drone_config: DroneConfig, params: Params, drones: Dict[str, DroneConfig]):
        """
        Initialize the DroneCommunicator with configuration and drone data.

        Args:
            drone_config (DroneConfig): Configuration for the current drone.
            params (Params): Global parameters.
            drones (Dict[str, DroneConfig]): Dictionary of all drones.
        """
        self.drone_config = drone_config
        self.params = params
        self.drones = drones
        self.enable_udp_telemetry = params.enable_udp_telemetry
        self.sock = self._initialize_socket() if self.enable_udp_telemetry else None
        self.stop_flag = threading.Event()
        self.nodes: List[Dict[str, Any]] = None
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.drone_state: Dict[str, Any] = None

        # Initialize TelemetrySubscriptionManager
        self.subscription_manager = TelemetrySubscriptionManager(drones)

        # Subscribe to all drones if the parameter is enabled
        if params.enable_default_subscriptions:
            self.subscription_manager.subscribe_to_all()

        # Initialize api_server as None; it will be injected later
        self.api_server = None

    def set_api_server(self, api_server):
        """Setter for injecting DroneAPIServer dependency after initialization."""
        self.api_server = api_server

    def _get_live_swarm_assignment(self) -> Dict[str, Any]:
        """Return the freshest known swarm assignment for this drone."""
        current_swarm = getattr(self.drone_config, "swarm", {}) or {}
        if not isinstance(current_swarm, dict):
            current_swarm = {}
        runtime_swarm = read_runtime_swarm_assignment()

        if (
            isinstance(runtime_swarm, dict)
            and runtime_swarm
            and safe_int(runtime_swarm.get("hw_id")) == safe_int(self.drone_config.hw_id)
        ):
            return runtime_swarm

        try:
            latest_swarm = self.drone_config.read_swarm()
        except Exception as exc:
            logger.debug(
                "Falling back to cached swarm assignment for hw_id=%s: %s",
                safe_int(self.drone_config.hw_id),
                exc,
            )
            latest_swarm = None

        if isinstance(latest_swarm, dict) and latest_swarm:
            return latest_swarm

        return current_swarm

    def _resolve_telemetry_timestamp_ms(self) -> int:
        telemetry_timestamp_ms = safe_int(getattr(self.drone_config, "telemetry_timestamp_ms", 0))
        if telemetry_timestamp_ms > 0:
            return telemetry_timestamp_ms

        update_time_seconds = safe_float(getattr(self.drone_config, "last_update_timestamp", 0))
        if update_time_seconds > 0:
            return int(update_time_seconds * 1000)
        return 0

    def _build_swarm_state(self, live_swarm: Dict[str, Any], emitted_at_ms: int) -> Dict[str, Any]:
        local_ned = dict(getattr(self.drone_config, "local_position_ned", {}) or {})
        telemetry_timestamp_ms = self._resolve_telemetry_timestamp_ms()

        return {
            "hw_id": safe_int(self.drone_config.hw_id),
            "pos_id": safe_int(self.drone_config.pos_id),
            "follow_mode": safe_int(safe_get(live_swarm, "follow")),
            "position_lat": safe_float(safe_get(self.drone_config.position, "lat")),
            "position_long": safe_float(safe_get(self.drone_config.position, "long")),
            "position_alt": safe_float(safe_get(self.drone_config.position, "alt")),
            "velocity_north": safe_float(safe_get(self.drone_config.velocity, "north")),
            "velocity_east": safe_float(safe_get(self.drone_config.velocity, "east")),
            "velocity_down": safe_float(safe_get(self.drone_config.velocity, "down")),
            "yaw": safe_float(self.drone_config.yaw),
            "yaw_deg": safe_float(self.drone_config.yaw),
            "yaw_rate_deg_s": safe_float(getattr(self.drone_config, "yaw_rate_deg_s", 0.0)),
            "telemetry_timestamp_ms": telemetry_timestamp_ms,
            "stream_seq": safe_int(getattr(self.drone_config, "telemetry_sequence", 0)),
            "source_frame": "local_ned" if safe_int(local_ned.get("time_boot_ms")) > 0 else "global_lla_ned",
            "source_time_boot_ms": safe_int(local_ned.get("time_boot_ms")),
            "local_position_north": safe_float(local_ned.get("x")),
            "local_position_east": safe_float(local_ned.get("y")),
            "local_position_down": safe_float(local_ned.get("z")),
            "local_velocity_north": safe_float(local_ned.get("vx")),
            "local_velocity_east": safe_float(local_ned.get("vy")),
            "local_velocity_down": safe_float(local_ned.get("vz")),
            "emitted_at_ms": emitted_at_ms,
        }

    def _initialize_socket(self) -> socket.socket:
        """Initialize and return a UDP socket for telemetry."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Use per-drone mavlink_port for UDP telemetry binding
        udp_port = int(self.drone_config.config.get('mavlink_port', 14550))
        sock.bind(('0.0.0.0', udp_port))
        sock.setblocking(False)
        return sock

    @staticmethod
    def _normalize_update_time_ms(value: Any) -> int:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return 0

        if numeric_value <= 0:
            return 0

        if numeric_value < 1_000_000_000_000:
            numeric_value *= 1000.0

        return int(numeric_value)

    def _local_mavlink_stale_threshold_ms(self) -> int:
        def _coerce_positive_int(value: Any, default: int) -> int:
            try:
                return max(1, int(value))
            except (TypeError, ValueError):
                return default

        configured_timeout = getattr(self.params, 'LOCAL_MAVLINK_STALE_TIMEOUT_SEC', None)
        try:
            configured_timeout_value = float(configured_timeout)
        except (TypeError, ValueError):
            configured_timeout_value = None

        if configured_timeout_value is None or configured_timeout_value <= 0:
            configured_timeout = (
                _coerce_positive_int(getattr(self.params, 'LOCAL_MAVLINK_TIMEOUT_SEC', 5), 5)
                * _coerce_positive_int(getattr(self.params, 'LOCAL_MAVLINK_RECONNECT_AFTER_TIMEOUTS', 3), 3)
            )
            configured_timeout_value = float(configured_timeout)

        return max(1000, int(configured_timeout_value * 1000))

    @staticmethod
    def _build_stale_telemetry_blocker(message: str, timestamp_ms: int) -> Dict[str, Any]:
        return {
            "source": "telemetry",
            "severity": "warning",
            "message": message,
            "timestamp": timestamp_ms,
        }

    def send_telem(self, packet: bytes, ip: str, port: int) -> None:
        """
        Send telemetry packet to the specified IP and port.

        Args:
            packet (bytes): Telemetry data packet.
            ip (str): Destination IP address.
            port (int): Destination port number.
        """
        if self.enable_udp_telemetry and self.sock:
            try:
                self.sock.sendto(packet, (ip, port))
            except OSError as e:
                logger.error(f"Failed to send telemetry: {e}")

    def get_nodes(self) -> List[Dict[str, Any]]:
        """Retrieve node information from config file."""
        if self.nodes is None:
            try:
                import json
                with open(Params.config_file_name, "r") as f:
                    data = json.load(f)
                self.nodes = data.get('drones', data) if isinstance(data, dict) else data
            except FileNotFoundError:
                logger.error("Config file not found")
                self.nodes = []
            except Exception as e:
                logger.error(f"Error reading config: {e}")
                self.nodes = []
        return self.nodes

    def update_drone_config(self, hw_id: str, **kwargs) -> None:
        """
        Update the configuration of a specific drone.

        Args:
            hw_id (str): Hardware ID of the drone to update.
            **kwargs: Arbitrary keyword arguments for drone configuration.
        """
        drone = self.drones.get(hw_id)
        if drone:
            for key, value in kwargs.items():
                setattr(drone, key, value)
            self.drones[hw_id] = drone
        else:
            logger.warning(f"Attempted to update non-existent drone: {hw_id}")

    def process_command(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process incoming command data and update drone configuration.

        Args:
            command_data (Dict[str, Any]): A dictionary containing command information.

        Required fields:
            - mission_type (int): The mission code.
            - trigger_time (int): The time to trigger the mission.

        Optional fields:
            - hw_id (str): Hardware ID.
            - pos_id (str): Position ID.
            - state (str): Drone state.
            - origin (dict): Phase 2 origin data (lat, lon, alt)
            - auto_global_origin (bool): Phase 2 mode flag
        """
        logger.info(f"Received command data: {command_data}")

        try:
            mission_value = (
                command_data["mission_type"]
                if "mission_type" in command_data
                else command_data["missionType"]
            )
            trigger_time_value = (
                command_data["trigger_time"]
                if "trigger_time" in command_data
                else command_data["triggerTime"]
            )
            mission = int(mission_value)
            trigger_time = int(trigger_time_value)

        except KeyError as e:
            logger.error(f"Missing required field in command data: {e}")
            raise ValueError(f"Missing required field in command data: {e}") from e

        # Phase 2: Save origin from command if present
        if command_data.get('auto_global_origin') and 'origin' in command_data:
            try:
                from pathlib import Path
                import json

                origin_data = command_data['origin']
                cache_dir = Path.home() / '.mavsdk_drone_show'
                cache_dir.mkdir(parents=True, exist_ok=True)

                origin_file = cache_dir / 'command_origin.json'
                with open(origin_file, 'w') as f:
                    json.dump(origin_data, f, indent=2)

                logger.info(f"🌍 Phase 2: Saved origin from command to {origin_file}")
                logger.info(f"   Origin: lat={origin_data.get('lat', 'N/A'):.6f}, "
                           f"lon={origin_data.get('lon', 'N/A'):.6f}, "
                           f"alt={origin_data.get('alt', 'N/A'):.1f}m")
            except Exception as e:
                logger.error(f"Failed to save command origin: {e}")

        # hw_id and pos_id are immutable - use the drone's configured values
        hw_id = self.drone_config.hw_id

        # Phase 2: Store flags in drone_config (safe - just storing references)
        self.drone_config.auto_global_origin = command_data.get('auto_global_origin', None)
        self.drone_config.use_global_setpoints = command_data.get('use_global_setpoints', None)

        if self.drone_config.auto_global_origin is not None:
            logger.info(f"🌍 Phase 2: auto_global_origin={self.drone_config.auto_global_origin}")
        if self.drone_config.use_global_setpoints is not None:
            logger.info(f"🌍 Phase 2: use_global_setpoints={self.drone_config.use_global_setpoints}")

        # ATOMIC: Process mission-specific data FIRST (may fail)
        # State is only updated if mission processing succeeds
        try:
            self._process_mission_command(mission, command_data)
        except Exception as e:
            logger.error(f"Mission processing failed: {e}. State unchanged.")
            raise ValueError(f"Mission processing failed: {e}") from e

        # Only update state AFTER successful mission processing
        self._update_drone_state(State.MISSION_READY.value, trigger_time)

        self._log_updated_configuration()
        self.drones[hw_id] = self.drone_config
        return {
            "mission": mission,
            "trigger_time": trigger_time,
            "state": self.drone_config.state,
        }

    def _update_drone_state(self, state: int, trigger_time: int) -> None:
        """Update mutable drone state values.

        Note: hw_id and pos_id are immutable configuration values loaded from
        the drone's .hwID file and config. They cannot be changed at runtime.
        Only state and trigger_time are mutable runtime values.
        """
        self.drone_config.state = state
        self.drone_config.trigger_time = trigger_time

    def _process_mission_command(self, mission: int, command_data: Dict[str, Any]) -> None:
        """Process the mission command based on its type."""
        # Log the incoming mission command and data
        logger.info(f"Processing mission command: {mission}, with data: {command_data}")

        if mission == Mission.TAKE_OFF.value:
            self._handle_takeoff_command(command_data)
        elif mission == Mission.QUICKSCOUT.value:
            self._handle_quickscout_command(command_data)
        elif mission == Mission.PRECISION_MOVE.value:
            self._handle_precision_move_command(command_data)
        elif mission in Mission._value2member_map_:
            self._handle_standard_mission(mission, command_data)
        else:
            # Log the error before raising an exception
            logger.error(f"Unknown mission command: {mission}")
            raise ValueError(f"Unknown mission command: {mission}")
    

    def _handle_takeoff_command(self, command_data: Dict[str, Any]) -> None:
        """Handle the takeoff command, setting altitude and mission."""
        default_altitude = self.params.default_takeoff_alt
        assigned_altitude = command_data.get("takeoff_altitude", default_altitude)
        self.drone_config.takeoff_altitude = min(float(assigned_altitude), self.params.max_takeoff_alt)
        logger.info(f"Takeoff command received. Assigned altitude: {self.drone_config.takeoff_altitude}m")
        self.drone_config.mission = Mission.TAKE_OFF.value
        self.drone_config.state = State.MISSION_READY.value  # Mission loaded, waiting for trigger

    def _handle_standard_mission(self, mission: int, command_data: Dict[str, Any]) -> None:
        """Handle standard (non-takeoff) mission commands."""
        mission_enum = Mission(mission)
        logger.info(f"{mission_enum.name.replace('_', ' ').title()} command received.")

        if mission == Mission.UPDATE_CODE.value:
            self.drone_config.update_branch = command_data.get('update_branch')
        elif mission == Mission.APPLY_COMMON_PARAMS.value:
            self.drone_config.reboot_after_params = bool(
                command_data.get('reboot_after_params', getattr(self.params, 'reboot_after_params', False))
            )

        self.drone_config.mission = mission
        self.drone_config.state = State.MISSION_READY.value  # Mission loaded, waiting for trigger

    def _write_runtime_payload_file(self, prefix: str, payload: Any, *identifiers: Any) -> str:
        safe_parts = [re.sub(r'[^a-zA-Z0-9_-]', '', str(part)) for part in identifiers if part not in (None, "")]
        suffix = "_".join(part for part in safe_parts if part)
        file_name = f"{prefix}_{suffix}.json" if suffix else f"{prefix}.json"
        payload_path = Path("/tmp") / file_name
        with payload_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        return str(payload_path)

    def _handle_quickscout_command(self, command_data: Dict[str, Any]) -> None:
        """Handle QuickScout SAR mission command - extract waypoints and store."""
        waypoints = command_data.get('waypoints', [])
        mission_id = command_data.get('mission_id', 'unknown')
        return_behavior = command_data.get('return_behavior', 'return_home')
        hw_id = self.drone_config.hw_id

        if not waypoints:
            raise ValueError("QuickScout command missing waypoints")

        waypoints_file = self._write_runtime_payload_file("quickscout", waypoints, hw_id, mission_id)
        logger.info(f"QuickScout waypoints written to {waypoints_file} ({len(waypoints)} waypoints)")

        # Store mission parameters on drone_config
        self.drone_config.quickscout_mission_id = mission_id
        self.drone_config.quickscout_waypoints_file = waypoints_file
        self.drone_config.quickscout_return_behavior = return_behavior
        self.drone_config.mission = Mission.QUICKSCOUT.value
        self.drone_config.state = State.MISSION_READY.value

    def _handle_precision_move_command(self, command_data: Dict[str, Any]) -> None:
        """Handle precision-move command payload installation."""
        precision_move = PrecisionMoveRequest.from_action_payload(command_data)
        command_id = command_data.get("command_id", "pending")
        request_file = self._write_runtime_payload_file(
            "precision_move",
            precision_move.model_dump(mode="json"),
            self.drone_config.hw_id,
            command_id,
        )

        self.drone_config.precision_move_request_file = request_file
        self.drone_config.mission = Mission.PRECISION_MOVE.value
        self.drone_config.state = State.MISSION_READY.value
        logger.info(
            "Precision Move command installed: frame=%s request_file=%s",
            precision_move.frame.value,
            request_file,
        )

    def _log_updated_configuration(self) -> None:
        """Log the updated drone configuration."""
        logger.info(
            f"Updated drone configuration: "
            f"hw_id={self.drone_config.hw_id}, "
            f"pos_id={self.drone_config.pos_id}, "
            f"state={self.drone_config.state}, "
            f"mission={self.drone_config.mission}, "
            f"trigger_time={self.drone_config.trigger_time}"
        )

    def process_packet(self, data: bytes) -> None:
        """
        Process incoming telemetry packet.

        Args:
            data (bytes): Raw telemetry packet data.
        """
        try:
            header, terminator = struct.unpack('BB', data[0:1] + data[-1:])
            if header == 77 and terminator == 88 and len(data) == Params.telem_packet_size:
                telemetry_data = struct.unpack(Params.telem_struct_fmt, data)
                hw_id = telemetry_data[1]
                if hw_id not in self.drones:
                    logger.info(f"Receiving Telemetry from NEW Drone ID= {hw_id}")
                    self.drones[hw_id] = DroneConfig(self.drones, hw_id)
                self._update_drone_config_from_telemetry(hw_id, telemetry_data)
            else:
                logger.error(f"Received packet of incorrect size or header. Got {len(data)} bytes.")
        except struct.error as e:
            logger.error(f"Failed to unpack telemetry data: {e}")

    def _update_drone_config_from_telemetry(self, hw_id: int, telemetry_data: tuple) -> None:
        """
        Update drone configuration based on received telemetry data.

        Args:
            hw_id (int): Hardware ID of the drone.
            telemetry_data (tuple): Unpacked telemetry data.
        """
        position = {'lat': telemetry_data[6], 'long': telemetry_data[7], 'alt': telemetry_data[8]}
        velocity = {'north': telemetry_data[9], 'east': telemetry_data[10], 'down': telemetry_data[11]}
        self.drones[hw_id].update(
            state=telemetry_data[3],
            mission=telemetry_data[4],
            trigger_time=telemetry_data[5],
            position=position,
            velocity=velocity,
            yaw=telemetry_data[12],
            battery_voltage=telemetry_data[13],
            update_time=telemetry_data[15]
        )
        # TODO: Remember to also add hdop and flight mode using HTTP FLASK

    def get_drone_state(self) -> Dict[str, Any]:
        """
        Retrieve and return the current state of the drone.

        This includes various telemetry data such as position, velocity, yaw, 
        battery voltage, and MAVLink-specific fields like flight mode and system status.

        Returns:
            dict: A dictionary containing the current state of the drone.
        """
        

        # Debug logging for flight mode issues
        if self.drone_config.custom_mode == 0 and self.drone_config.is_armed:
            logger.warning(f"[DRONE {self.drone_config.hw_id}] ⚠️ custom_mode=0 while armed! "
                          f"base_mode={self.drone_config.base_mode}, system_status={self.drone_config.system_status}")

        live_swarm = self._get_live_swarm_assignment()

        now_ms = int(time.time() * 1000)

        self.drone_state = {
            "hw_id": safe_int(self.drone_config.hw_id),  # Hardware ID of the drone
            "pos_id": safe_int(self.drone_config.pos_id),  # Position ID
            "detected_pos_id": safe_int(self.drone_config.detected_pos_id),  # Auto Detected Position ID
            "state": safe_int(self.drone_config.state),  # Current state of the drone
            "mission": safe_int(self.drone_config.mission),  # Current mission state
            "last_mission": safe_int(self.drone_config.last_mission),  # Last mission state
            "trigger_time": safe_int(self.drone_config.trigger_time),  # Time of the last trigger event
            "position_lat": safe_float(safe_get(self.drone_config.position, 'lat')),  # Latitude of the current position
            "position_long": safe_float(safe_get(self.drone_config.position, 'long')),  # Longitude of the current position
            "position_alt": safe_float(safe_get(self.drone_config.position, 'alt')),  # Altitude of the current position
            "velocity_north": safe_float(safe_get(self.drone_config.velocity, 'north')),  # Velocity towards north
            "velocity_east": safe_float(safe_get(self.drone_config.velocity, 'east')),  # Velocity towards east
            "velocity_down": safe_float(safe_get(self.drone_config.velocity, 'down')),  # Velocity downwards
            "yaw": safe_float(self.drone_config.yaw),  # Yaw angle of the drone
            "battery_voltage": safe_float(self.drone_config.battery),  # Current battery voltage
            "follow_mode": safe_int(safe_get(live_swarm, 'follow')),  # Follow mode in swarm operation
            "update_time": safe_int(self.drone_config.last_update_timestamp),  # Timestamp of the last telemetry update
            "flight_mode": safe_int(self.drone_config.custom_mode),  # PX4 flight mode (from HEARTBEAT.custom_mode)
            "base_mode": safe_int(self.drone_config.base_mode),  # MAVLink base mode flags
            "system_status": safe_int(self.drone_config.system_status),  # MAVLink system status (e.g., STANDBY, ACTIVE)
            "is_armed": bool(self.drone_config.is_armed),  # Armed status from base_mode flags
            "is_ready_to_arm": bool(self.drone_config.is_ready_to_arm),  # Pre-arm checks status
            "home_position_set": bool(getattr(self.drone_config, 'px4_home_position_set', False)),
            "home_position_source": str(getattr(self.drone_config, 'home_position_source', 'unknown')),
            "readiness_status": str(getattr(self.drone_config, 'readiness_status', 'unknown')),
            "readiness_summary": str(getattr(self.drone_config, 'readiness_summary', 'Readiness unavailable')),
            "readiness_checks": list(getattr(self.drone_config, 'readiness_checks', []) or []),
            "preflight_blockers": list(getattr(self.drone_config, 'preflight_blockers', []) or []),
            "preflight_warnings": list(getattr(self.drone_config, 'preflight_warnings', []) or []),
            "status_messages": list(getattr(self.drone_config, 'status_messages', []) or []),
            "preflight_last_update": safe_int(getattr(self.drone_config, 'preflight_last_update', 0)),
            "hdop": safe_float(self.drone_config.hdop),  # Horizontal dilution of precision
            "vdop": safe_float(self.drone_config.vdop),  # Vertical dilution of precision
            "gps_fix_type": safe_int(getattr(self.drone_config, 'gps_fix_type', 0)),  # GPS fix status
            "satellites_visible": safe_int(getattr(self.drone_config, 'satellites_visible', 0)),  # Number of satellites
            "ip": self.drone_config.config.get('ip', 'N/A')  # Drone IP address
        }

        update_time_ms = self._normalize_update_time_ms(self.drone_state.get("update_time"))
        telemetry_age_ms = (now_ms - update_time_ms) if update_time_ms > 0 else None
        stale_threshold_ms = self._local_mavlink_stale_threshold_ms()

        self.drone_state["telemetry_last_update_age_ms"] = telemetry_age_ms
        self.drone_state["telemetry_stale_threshold_ms"] = stale_threshold_ms

        if update_time_ms <= 0:
            self.drone_state["telemetry_available"] = False
            self.drone_state["telemetry_error"] = "Waiting for PX4 telemetry."
        elif telemetry_age_ms is not None and telemetry_age_ms > stale_threshold_ms:
            stale_message = (
                f"Local MAVLink telemetry is stale ({telemetry_age_ms / 1000.0:.1f}s since last update). "
                "Readiness is currently unavailable."
            )
            self.drone_state.update({
                "telemetry_available": False,
                "telemetry_error": stale_message,
                "is_ready_to_arm": False,
                "readiness_status": "unknown",
                "readiness_summary": stale_message,
                "preflight_blockers": [self._build_stale_telemetry_blocker(stale_message, now_ms)],
                "preflight_warnings": [],
                "preflight_last_update": now_ms,
            })
        else:
            self.drone_state["telemetry_available"] = True
            self.drone_state["telemetry_error"] = None

        return self.drone_state

    def get_swarm_state(self) -> Dict[str, Any]:
        """Return the high-rate Smart Swarm state payload."""
        live_swarm = self._get_live_swarm_assignment()
        emitted_at_ms = int(time.time() * 1000)
        return self._build_swarm_state(live_swarm, emitted_at_ms)


    def send_drone_state(self) -> None:
        """Continuously send drone state as telemetry."""
        udp_ip = Params.GCS_IP  # Use centralized GCS IP from Params
        udp_port = Params.gcs_api_port  # Default port for UDP telemetry

        while not self.stop_flag.is_set():
            drone_state = self.get_drone_state()
            packet = self._create_telemetry_packet(drone_state)

            if Params.broadcast_mode:
                self._broadcast_telemetry(packet, drone_state['hw_id'])
            self.executor.submit(self.send_telem, packet, udp_ip, udp_port)
            time.sleep(Params.TELEM_SEND_INTERVAL)

    def _create_telemetry_packet(self, drone_state: Dict[str, Any]) -> bytes:
        """Create a telemetry packet from the drone state."""
        return struct.pack(
            Params.telem_struct_fmt,
            77,  # Header
            drone_state['hw_id'],
            drone_state['pos_id'],
            drone_state['state'],
            drone_state['mission'],
            drone_state['trigger_time'],
            drone_state['position_lat'],
            drone_state['position_long'],
            drone_state['position_alt'],
            drone_state['velocity_north'],
            drone_state['velocity_east'],
            drone_state['velocity_down'],
            drone_state['yaw'],
            drone_state['battery_voltage'],
            drone_state['follow_mode'],
            drone_state['update_time'],
            88  # Terminator
        )

    def _broadcast_telemetry(self, packet: bytes, sender_hw_id: int) -> None:
        """Broadcast telemetry to all nodes except the sender."""
        nodes = self.get_nodes()
        for node in nodes:
            if int(node["hw_id"]) != sender_hw_id:
                self.executor.submit(self.send_telem, packet, node["ip"], int(node["mavlink_port"]))

    def read_packets(self) -> None:
        """Continuously read incoming packets and process them."""
        while not self.stop_flag.is_set():
            if self.sock:
                ready = select.select([self.sock], [], [], Params.income_packet_check_interval)
                if ready[0]:
                    try:
                        data, addr = self.sock.recvfrom(1024)
                        self.process_packet(data)
                    except OSError as e:
                        logger.error(f"Error receiving packet: {e}")
            
            # Handle swarm mission if active
            if self.drone_config.mission == Mission.SMART_SWARM.value and self.drone_config.state != 0 and int(self.drone_config.swarm.get('follow', 0)) != 0:
                self.drone_config.calculate_setpoints()

    def start_communication(self) -> None:
        """Start communication threads for telemetry and command processing."""
        if Params.enable_udp_telemetry:
            self.telemetry_thread = threading.Thread(target=self.send_drone_state)
            self.command_thread = threading.Thread(target=self.read_packets)
            self.telemetry_thread.start()
            self.command_thread.start()

        # Note: API server is now started in coordinator.py, not here
        # This keeps the separation of concerns clean

    def stop_communication(self) -> None:
        """Stop all communication threads and clean up resources."""
        self.stop_flag.set()
        if Params.enable_udp_telemetry:
            self.telemetry_thread.join()
            self.command_thread.join()
        # API server is managed separately in coordinator.py
        self.executor.shutdown()

        if self.sock:
            self.sock.close()
