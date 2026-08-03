#src/drone_communicator.py
import socket
import threading
import struct
import select
import time
import os
import re
import math
import tempfile
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from functions.data_utils import safe_float, safe_get, safe_int
from mds_logging import get_logger
from src.command_contract import GroundTestSafetyAcknowledgement, PrecisionMoveRequest
from src.command_installation import (
    CommandInstallationRejected,
    CommandInstallationResult,
    CommandInstallationUncertain,
    PreparedCommandInstallation,
    ensure_private_directory,
    semantic_payload_digest,
    stage_json_artifact,
    stage_json_target_removal,
)
from src.enums import Mission, State
from src.telemetry_display import build_altitude_report, build_gps_report
from src.drone_config import DroneConfig
from src.params import Params
from src.swarm_runtime_state import read_runtime_swarm_assignment
from src.telemetry_subscription_manager import TelemetrySubscriptionManager


logger = get_logger("drone_comm")

_MISSING_COMMAND_FIELD = object()

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
        self._command_install_lock = threading.RLock()

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

    @staticmethod
    def _is_valid_global_position(position: Any) -> bool:
        if not isinstance(position, dict):
            return False
        try:
            lat = float(position.get("lat"))
            lon = float(position.get("long", position.get("lon", position.get("lng"))))
        except (TypeError, ValueError):
            return False
        if not all(math.isfinite(value) for value in [lat, lon]):
            return False
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return False
        return abs(lat) > 0.000001 or abs(lon) > 0.000001

    @staticmethod
    def _age_ms(now_ms: int, timestamp_ms: Any) -> Optional[int]:
        timestamp = safe_int(timestamp_ms)
        if timestamp <= 0:
            return None
        return max(0, now_ms - timestamp)

    def _position_unavailable_reason(self, global_position_valid: bool) -> Optional[str]:
        if global_position_valid:
            return None
        gps_fix_type = safe_int(getattr(self.drone_config, "gps_fix_type", 0))
        if gps_fix_type >= 3:
            return "GPS fix present, waiting for valid PX4 global position."
        if gps_fix_type > 0:
            return "GPS fix is not 3D yet."
        return "No GPS fix reported."

    @staticmethod
    def _distance_to_home_m(position: Any, home_position: Any) -> Optional[float]:
        """Return horizontal great-circle distance to cached home, or None when unavailable."""
        if not isinstance(position, dict) or not isinstance(home_position, dict):
            return None

        try:
            lat = float(position.get("lat"))
            lon = float(position.get("long", position.get("lon", position.get("lng"))))
            home_lat = float(home_position.get("lat"))
            home_lon = float(home_position.get("long", home_position.get("lon", home_position.get("lng"))))
        except (TypeError, ValueError):
            return None

        if not all(math.isfinite(value) for value in [lat, lon, home_lat, home_lon]):
            return None

        if abs(lat) < 0.000001 and abs(lon) < 0.000001:
            return None

        earth_radius_m = 6_371_000.0
        lat_1 = math.radians(lat)
        lat_2 = math.radians(home_lat)
        delta_lat = math.radians(home_lat - lat)
        delta_lon = math.radians(home_lon - lon)
        haversine = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat_1) * math.cos(lat_2) * (math.sin(delta_lon / 2) ** 2)
        )
        return 2 * earth_radius_m * math.atan2(math.sqrt(haversine), math.sqrt(max(0.0, 1 - haversine)))

    def _build_swarm_state(self, live_swarm: Dict[str, Any], emitted_at_ms: int) -> Dict[str, Any]:
        local_ned = dict(getattr(self.drone_config, "local_position_ned", {}) or {})
        telemetry_timestamp_ms = self._resolve_telemetry_timestamp_ms()
        global_position_timestamp_ms = safe_int(getattr(self.drone_config, "global_position_timestamp_ms", 0))
        global_position_valid = (
            bool(getattr(self.drone_config, "global_position_valid", False))
            and self._is_valid_global_position(getattr(self.drone_config, "position", None))
        )
        altitude_report = build_altitude_report(
            position=getattr(self.drone_config, "position", None),
            local_position_ned=local_ned,
            gps_fix_type=getattr(self.drone_config, "gps_fix_type", 0),
            global_position_timestamp_ms=global_position_timestamp_ms,
            relative_altitude_m=getattr(self.drone_config, "relative_altitude_m", None),
            baro_altitude_m=getattr(self.drone_config, "baro_altitude_m", None),
            baro_timestamp_ms=getattr(self.drone_config, "baro_timestamp_ms", 0),
            now_ms=emitted_at_ms,
        )

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
            "global_position_valid": global_position_valid,
            "global_position_timestamp_ms": global_position_timestamp_ms,
            "position_source": str(getattr(self.drone_config, "position_source", "unavailable")),
            "source_frame": "local_ned" if safe_int(local_ned.get("time_boot_ms")) > 0 else "global_lla_ned",
            "source_time_boot_ms": safe_int(local_ned.get("time_boot_ms")),
            "altitude_report": altitude_report,
            "altitude_display_m": altitude_report.get("display_m"),
            "altitude_source": altitude_report.get("source"),
            "relative_altitude_m": altitude_report.get("relative_home_m"),
            "baro_altitude_m": altitude_report.get("baro_m"),
            "local_position_north": safe_float(local_ned.get("x")),
            "local_position_east": safe_float(local_ned.get("y")),
            "local_position_down": safe_float(local_ned.get("z")),
            "local_position_timestamp_ms": safe_int(local_ned.get("timestamp_ms")),
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

    def process_command(self, command_data: Dict[str, Any]) -> CommandInstallationResult:
        """Prepare and atomically install one command under one local lock."""
        with self._command_install_lock:
            prepared = self._prepare_command(command_data)
            return self._commit_prepared_command(prepared)

    def _runtime_payload_directory(self) -> Path:
        configured_root = getattr(self.params, "command_runtime_dir", None)
        runtime_root = (
            Path(configured_root)
            if configured_root
            else Path(tempfile.gettempdir()) / f"mds-command-runtime-{os.geteuid()}"
        )
        safe_hw_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(self.drone_config.hw_id)) or "unknown"
        runtime_directory = runtime_root / f"drone-{safe_hw_id[:64]}"
        ensure_private_directory(runtime_directory)
        return runtime_directory

    @staticmethod
    def _safe_artifact_identifier(value: Any) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_-]", "", str(value or ""))
        return normalized[:48] or "pending"

    def _runtime_artifact_target(self, prefix: str, payload: Any, identifier: Any) -> Path:
        digest = semantic_payload_digest(payload)
        return self._runtime_payload_directory() / (
            f"{prefix}_{self._safe_artifact_identifier(identifier)}_{digest}.json"
        )

    @staticmethod
    def _normalize_origin(origin_data: Any) -> Dict[str, Any]:
        if not isinstance(origin_data, dict):
            raise ValueError("origin must be a JSON object")
        try:
            latitude = float(origin_data["lat"])
            longitude = float(origin_data["lon"])
            altitude = float(origin_data.get("alt", 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("origin requires numeric lat, lon, and alt values") from exc
        if not all(math.isfinite(value) for value in (latitude, longitude, altitude)):
            raise ValueError("origin values must be finite")
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            raise ValueError("origin latitude/longitude is outside the valid range")
        normalized = dict(origin_data)
        normalized.update({"lat": latitude, "lon": longitude, "alt": altitude})
        return normalized

    @staticmethod
    def _parse_command_header(command_data: Dict[str, Any]) -> Tuple[int, int]:
        try:
            mission_value = command_data["mission_type"]
            trigger_time_value = command_data["trigger_time"]
        except KeyError as exc:
            raise ValueError(f"Missing required field in command data: {exc}") from exc

        mission = int(mission_value)
        if mission not in Mission._value2member_map_:
            raise ValueError(f"Unknown mission command: {mission}")
        trigger_time = int(trigger_time_value)
        if trigger_time < 0:
            raise ValueError("trigger_time must be non-negative")
        return mission, trigger_time

    def _prepare_command(self, command_data: Dict[str, Any]) -> PreparedCommandInstallation:
        """Validate a command and stage all files without publishing mutation."""
        if not isinstance(command_data, dict):
            raise CommandInstallationRejected(
                "Command data must be a JSON object",
                phase="preparation",
            )

        artifacts = []
        try:
            mission, trigger_time = self._parse_command_header(command_data)
            command_id = command_data.get("command_id")
            normalized_command_id = str(command_id).strip() if command_id is not None else None
            if normalized_command_id == "":
                normalized_command_id = None

            # Clear every mission-specific value first.  A newly accepted
            # command therefore cannot accidentally inherit options from the
            # previous command family.
            updates: List[Tuple[str, Any]] = [
                ("runtime_takeoff_altitude", None),
                ("update_branch", None),
                ("ground_test_request_file", None),
                ("quickscout_mission_id", None),
                ("quickscout_waypoints_file", None),
                ("quickscout_return_behavior", None),
                ("precision_move_request_file", None),
                ("auto_global_origin", command_data.get("auto_global_origin")),
                ("use_global_setpoints", command_data.get("use_global_setpoints")),
            ]

            if (
                mission == Mission.DRONE_SHOW_FROM_CSV.value
                and command_data.get("auto_global_origin")
            ):
                origin_directory = Path.home() / ".mavsdk_drone_show"
                ensure_private_directory(origin_directory)
                origin_target = origin_directory / "command_origin.json"
                if "origin" in command_data:
                    origin_data = self._normalize_origin(command_data["origin"])
                    artifacts.append(
                        stage_json_artifact(
                            target=origin_target,
                            payload=origin_data,
                            purpose="command origin",
                        )
                    )
                else:
                    # command_origin.json is single-use. A new command that
                    # deliberately falls back to GCS/cache must not inherit an
                    # older pending command's attached origin.
                    artifacts.append(
                        stage_json_target_removal(
                            target=origin_target,
                            purpose="stale command origin",
                        )
                    )

            if mission == Mission.TAKE_OFF.value:
                assigned_altitude = float(
                    command_data.get("takeoff_altitude", self.params.default_takeoff_alt)
                )
                max_altitude = float(self.params.max_takeoff_alt)
                if not math.isfinite(assigned_altitude) or assigned_altitude <= 0:
                    raise ValueError("takeoff_altitude must be a positive finite number")
                if not math.isfinite(max_altitude) or max_altitude <= 0:
                    raise ValueError("Configured maximum takeoff altitude is invalid")
                updates.append(("takeoff_altitude", min(assigned_altitude, max_altitude)))
            elif mission == Mission.QUICKSCOUT.value:
                waypoints = command_data.get("waypoints")
                if not isinstance(waypoints, list) or not waypoints:
                    raise ValueError("QuickScout command missing waypoints")
                mission_id = str(command_data.get("mission_id", "unknown"))
                return_behavior = str(command_data.get("return_behavior", "return_home"))
                target = self._runtime_artifact_target(
                    "quickscout",
                    waypoints,
                    normalized_command_id or mission_id,
                )
                artifacts.append(
                    stage_json_artifact(
                        target=target,
                        payload=waypoints,
                        purpose="QuickScout waypoints",
                    )
                )
                updates.extend(
                    [
                        ("quickscout_mission_id", mission_id),
                        ("quickscout_waypoints_file", str(target)),
                        ("quickscout_return_behavior", return_behavior),
                    ]
                )
            elif mission == Mission.PRECISION_MOVE.value:
                precision_move = PrecisionMoveRequest.from_action_payload(command_data)
                precision_payload = precision_move.model_dump(mode="json")
                target = self._runtime_artifact_target(
                    "precision_move",
                    precision_payload,
                    normalized_command_id,
                )
                artifacts.append(
                    stage_json_artifact(
                        target=target,
                        payload=precision_payload,
                        purpose="Precision Move request",
                    )
                )
                updates.append(("precision_move_request_file", str(target)))
            elif mission == Mission.UPDATE_CODE.value:
                updates.append(("update_branch", command_data.get("update_branch")))
            elif mission == Mission.TEST.value:
                acknowledgement = GroundTestSafetyAcknowledgement.model_validate(
                    command_data.get("ground_test_safety")
                )
                acknowledgement.validate_for_runtime(
                    sim_mode=bool(getattr(self.params, "sim_mode", False))
                )
                request_payload = {
                    "ground_test_safety": acknowledgement.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                }
                target = self._runtime_artifact_target(
                    "ground_test",
                    request_payload,
                    normalized_command_id,
                )
                artifacts.append(
                    stage_json_artifact(
                        target=target,
                        payload=request_payload,
                        purpose="Arm/Disarm Ground Test safety acknowledgement",
                    )
                )
                updates.append(
                    (
                        "ground_test_request_file",
                        str(target),
                    )
                )

            # State is intentionally published last.  current_command_id is
            # part of this same transaction, not an API-side follow-up write.
            updates.extend(
                [
                    ("mission", mission),
                    ("trigger_time", trigger_time),
                    ("current_command_id", normalized_command_id),
                    ("state", State.MISSION_READY.value),
                ]
            )

            logger.info(
                "Prepared command installation: mission=%s trigger_time=%s command_id=%s artifacts=%s",
                Mission(mission).name,
                trigger_time,
                normalized_command_id,
                len(artifacts),
            )
            return PreparedCommandInstallation(
                mission=mission,
                trigger_time=trigger_time,
                hw_id=self.drone_config.hw_id,
                command_id=normalized_command_id,
                config_updates=tuple(updates),
                artifacts=tuple(artifacts),
            )
        except CommandInstallationRejected:
            raise
        except BaseException as exc:
            cleanup_errors = []
            for artifact in reversed(artifacts):
                try:
                    artifact.discard()
                except BaseException as cleanup_exc:
                    cleanup_errors.append(cleanup_exc)
            if cleanup_errors:
                logger.error(
                    "Command preparation cleanup left staging debris: %s",
                    "; ".join(str(error) for error in cleanup_errors),
                )
            detail = str(exc).strip() or type(exc).__name__
            raise CommandInstallationRejected(
                f"Command preparation failed: {detail}",
                phase="preparation",
                cause=exc,
            ) from exc

    @staticmethod
    def _restore_config_field(config: Any, field_name: str, previous_value: Any) -> None:
        if previous_value is _MISSING_COMMAND_FIELD:
            try:
                delattr(config, field_name)
            except AttributeError:
                pass
            return
        setattr(config, field_name, previous_value)

    def _commit_prepared_command(
        self,
        prepared: PreparedCommandInstallation,
    ) -> CommandInstallationResult:
        """Commit staged artifacts and config, or restore the exact prior command."""
        if prepared.committed:
            raise CommandInstallationRejected(
                "Prepared command was already committed",
                phase="precondition",
            )
        if prepared.hw_id != self.drone_config.hw_id:
            try:
                prepared.discard()
            except Exception:
                logger.exception("Failed to discard a prepared command for the wrong node")
            raise CommandInstallationRejected(
                "Prepared command target no longer matches this node",
                phase="precondition",
            )

        # The prepared update plan is the only config-field authority. Deriving
        # the snapshot/rollback order from it prevents new mission fields from
        # being added to commit logic but forgotten in a duplicate rollback
        # list. Reversing the exact update order also handles facade aliases
        # such as takeoff_altitude/runtime_takeoff_altitude correctly.
        config_field_order = tuple(
            dict.fromkeys(field_name for field_name, _value in prepared.config_updates)
        )
        config_snapshot = {
            field_name: getattr(self.drone_config, field_name, _MISSING_COMMAND_FIELD)
            for field_name in config_field_order
        }
        mapping_key = prepared.hw_id
        mapping_existed = mapping_key in self.drones
        prior_mapping_value = self.drones.get(mapping_key)
        phase = "artifact_commit"

        try:
            for artifact in prepared.artifacts:
                artifact.commit()

            phase = "config_commit"
            for field_name, value in prepared.config_updates:
                setattr(self.drone_config, field_name, value)

            phase = "registry_commit"
            self.drones[mapping_key] = self.drone_config
            prepared.committed = True
        except BaseException as exc:
            rollback_errors: List[BaseException] = []

            for field_name in reversed(config_field_order):
                try:
                    self._restore_config_field(
                        self.drone_config,
                        field_name,
                        config_snapshot[field_name],
                    )
                except BaseException as rollback_exc:
                    rollback_errors.append(rollback_exc)

            try:
                if mapping_existed:
                    self.drones[mapping_key] = prior_mapping_value
                else:
                    self.drones.pop(mapping_key, None)
            except BaseException as rollback_exc:
                rollback_errors.append(rollback_exc)

            for artifact in reversed(prepared.artifacts):
                try:
                    artifact.rollback()
                except BaseException as rollback_exc:
                    rollback_errors.append(rollback_exc)

            detail = str(exc).strip() or type(exc).__name__
            if rollback_errors:
                rollback_detail = "; ".join(
                    str(error).strip() or type(error).__name__
                    for error in rollback_errors
                )
                raise CommandInstallationUncertain(
                    f"Command installation failed during {phase}; rollback was incomplete: "
                    f"{rollback_detail}",
                    phase=phase,
                    rollback_errors=rollback_errors,
                    cause=exc,
                ) from exc

            raise CommandInstallationRejected(
                f"Command installation failed during {phase}: {detail}",
                phase=phase,
                cause=exc,
            ) from exc

        for artifact in prepared.artifacts:
            try:
                artifact.finalize()
            except BaseException:
                # Cleanup debris does not reverse a fully committed command.
                logger.exception(
                    "Committed command but could not retire artifact backup for %s",
                    artifact.purpose,
                )

        result = CommandInstallationResult(
            committed=True,
            mission=prepared.mission,
            trigger_time=prepared.trigger_time,
            state=int(self.drone_config.state),
            command_id=prepared.command_id,
            artifact_paths=prepared.artifact_paths,
        )
        self._log_updated_configuration()
        return result

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
        global_position_valid = (
            bool(getattr(self.drone_config, "global_position_valid", False))
            and self._is_valid_global_position(getattr(self.drone_config, "position", None))
        )
        gps_fix_type = safe_int(getattr(self.drone_config, 'gps_fix_type', 0))
        gps_raw_timestamp_ms = safe_int(getattr(self.drone_config, "gps_raw_timestamp_ms", 0))
        global_position_timestamp_ms = safe_int(getattr(self.drone_config, "global_position_timestamp_ms", 0))
        gps_raw_altitude_m = getattr(self.drone_config, "gps_raw_altitude_m", None)
        try:
            gps_raw_altitude_m = float(gps_raw_altitude_m) if gps_raw_altitude_m is not None else None
        except (TypeError, ValueError):
            gps_raw_altitude_m = None

        raw_local_ned = getattr(self.drone_config, "local_position_ned", None)
        local_ned = dict(raw_local_ned) if isinstance(raw_local_ned, dict) else {}
        local_time_boot_ms = safe_int(local_ned.get("time_boot_ms"))
        altitude_report = build_altitude_report(
            position=getattr(self.drone_config, "position", None),
            local_position_ned=local_ned,
            gps_fix_type=gps_fix_type,
            global_position_timestamp_ms=global_position_timestamp_ms,
            relative_altitude_m=getattr(self.drone_config, "relative_altitude_m", None),
            baro_altitude_m=getattr(self.drone_config, "baro_altitude_m", None),
            baro_timestamp_ms=getattr(self.drone_config, "baro_timestamp_ms", 0),
            now_ms=now_ms,
        )
        gps_report = build_gps_report(
            fix_type=gps_fix_type,
            satellites_visible=getattr(self.drone_config, "satellites_visible", 0),
            hdop=getattr(self.drone_config, "hdop", None),
            vdop=getattr(self.drone_config, "vdop", None),
        )

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
            "battery_remaining_percent": getattr(
                self.drone_config,
                "battery_remaining_percent",
                None,
            ),
            "battery_charge_state": getattr(self.drone_config, "battery_charge_state", None),
            "battery_fault_bitmask": getattr(self.drone_config, "battery_fault_bitmask", None),
            "battery_timestamp_ms": safe_int(
                getattr(self.drone_config, "battery_timestamp_ms", 0)
            ),
            "battery_age_ms": self._age_ms(
                now_ms,
                getattr(self.drone_config, "battery_timestamp_ms", 0),
            ),
            "follow_mode": safe_int(safe_get(live_swarm, 'follow')),  # Follow mode in swarm operation
            "update_time": safe_int(self.drone_config.last_update_timestamp),  # Timestamp of the last telemetry update
            "flight_mode": safe_int(self.drone_config.custom_mode),  # PX4 flight mode (from HEARTBEAT.custom_mode)
            "base_mode": safe_int(self.drone_config.base_mode),  # MAVLink base mode flags
            "system_status": safe_int(self.drone_config.system_status),  # MAVLink system status (e.g., STANDBY, ACTIVE)
            "is_armed": bool(self.drone_config.is_armed),  # Armed status from base_mode flags
            "heartbeat_timestamp_ms": safe_int(
                getattr(self.drone_config, "heartbeat_timestamp_ms", 0)
            ),
            "heartbeat_age_ms": self._age_ms(
                now_ms,
                getattr(self.drone_config, "heartbeat_timestamp_ms", 0),
            ),
            "is_ready_to_arm": bool(self.drone_config.is_ready_to_arm),  # Pre-arm checks status
            "home_position_set": bool(getattr(self.drone_config, 'px4_home_position_set', False)),
            "home_position_source": str(getattr(self.drone_config, 'home_position_source', 'unknown')),
            "distance_to_home_m": self._distance_to_home_m(
                getattr(self.drone_config, "position", None),
                getattr(self.drone_config, "home_position", None),
            ) if global_position_valid else None,
            "global_position_valid": global_position_valid,
            "global_position_timestamp_ms": global_position_timestamp_ms,
            "global_position_age_ms": self._age_ms(now_ms, global_position_timestamp_ms),
            "gps_raw_valid": gps_fix_type >= 3,
            "gps_raw_timestamp_ms": gps_raw_timestamp_ms,
            "gps_raw_age_ms": self._age_ms(now_ms, gps_raw_timestamp_ms),
            "gps_raw_altitude_m": gps_raw_altitude_m,
            "altitude_report": altitude_report,
            "altitude_display_m": altitude_report.get("display_m"),
            "altitude_source": altitude_report.get("source"),
            "relative_altitude_m": altitude_report.get("relative_home_m"),
            "baro_altitude_m": altitude_report.get("baro_m"),
            "baro_timestamp_ms": safe_int(getattr(self.drone_config, "baro_timestamp_ms", 0)),
            "baro_age_ms": self._age_ms(now_ms, getattr(self.drone_config, "baro_timestamp_ms", 0)),
            "local_position_ok": local_time_boot_ms > 0,
            "local_position_north": safe_float(local_ned.get("x")),
            "local_position_east": safe_float(local_ned.get("y")),
            "local_position_down": safe_float(local_ned.get("z")),
            "local_position_time_boot_ms": local_time_boot_ms,
            "local_position_timestamp_ms": safe_int(local_ned.get("timestamp_ms")),
            "position_source": str(getattr(self.drone_config, "position_source", "unavailable")),
            "position_unavailable_reason": self._position_unavailable_reason(global_position_valid),
            "readiness_status": str(getattr(self.drone_config, 'readiness_status', 'unknown')),
            "readiness_summary": str(getattr(self.drone_config, 'readiness_summary', 'Readiness unavailable')),
            "readiness_checks": list(getattr(self.drone_config, 'readiness_checks', []) or []),
            "preflight_blockers": list(getattr(self.drone_config, 'preflight_blockers', []) or []),
            "preflight_warnings": list(getattr(self.drone_config, 'preflight_warnings', []) or []),
            "status_messages": list(getattr(self.drone_config, 'status_messages', []) or []),
            "preflight_last_update": safe_int(getattr(self.drone_config, 'preflight_last_update', 0)),
            "hdop": safe_float(self.drone_config.hdop),  # Horizontal dilution of precision
            "vdop": safe_float(self.drone_config.vdop),  # Vertical dilution of precision
            "gps_fix_type": gps_fix_type,  # GPS fix status
            "gps_report": gps_report,
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
