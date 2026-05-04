#src\local_mavlink_controller.py
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from pymavlink import mavutil


STATUS_TEXT_RETENTION_MS = 120000
STATUS_TEXT_MAX_MESSAGES = 8
STATUS_TEXT_BUFFER_RETENTION_S = 5

class LocalMavlinkController:
    """
    The LocalMavlinkController class manages telemetry data received from the local Mavlink connection.
    It reads incoming Mavlink messages in a separate thread and updates the drone_config object accordingly.
    
    Args:
        drone_config: A configuration object which contains drone details like position, velocity, etc.
        params: Configuration parameters such as local Mavlink port and telemetry refresh interval.
        debug_enabled: A flag that controls whether debug logs are printed.
    """
    
    def __init__(self, drone_config, params, debug_enabled=False):
        """
        Initialize the controller, set up the Mavlink connection, and start the telemetry monitoring thread.
        """
        self.latest_messages = {}
        self.debug_enabled = debug_enabled
        # Define which message types to listen for
        self.message_filter = [
            'GLOBAL_POSITION_INT', 'HOME_POSITION', 'BATTERY_STATUS', 'GPS_GLOBAL_ORIGIN',
            'ATTITUDE', 'HEARTBEAT', 'GPS_RAW_INT', 'SYS_STATUS', 'LOCAL_POSITION_NED',
            'STATUSTEXT'
        ]
        
        self.local_mavlink_port = int(getattr(params, 'local_mavlink_port', 12550))
        self.local_mavlink_timeout_sec = max(1, int(getattr(params, 'LOCAL_MAVLINK_TIMEOUT_SEC', 5)))
        self.local_mavlink_reconnect_after_timeouts = max(
            1,
            int(getattr(params, 'LOCAL_MAVLINK_RECONNECT_AFTER_TIMEOUTS', 3)),
        )
        self.mav = self._open_mavlink_connection()
        self.drone_config = drone_config
        self.local_mavlink_refresh_interval = params.local_mavlink_refresh_interval
        self.require_global_position = bool(getattr(params, 'REQUIRE_GLOBAL_POSITION', False))
        self.run_telemetry_thread = threading.Event()
        self.run_telemetry_thread.set()

        # Start the telemetry monitoring thread
        self.telemetry_thread = threading.Thread(target=self.mavlink_monitor)
        self.telemetry_thread.start()
        self.home_position_logged = False
        self._status_text_buffers: Dict[int, Dict[str, Any]] = {}
        self._status_messages: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    def _open_mavlink_connection(self):
        """Open a fresh UDP listener for the locally routed MAVLink stream."""
        connection_string = f"udpin:127.0.0.1:{self.local_mavlink_port}"
        self.log_debug(f"Opening LocalMavlinkController on {connection_string}")
        return mavutil.mavlink_connection(connection_string)

    def _reset_mavlink_connection(self, reason: str) -> None:
        """Close and reopen the local MAVLink listener after repeated silence/errors."""
        try:
            self.mav.close()
        except Exception:
            pass

        self.mav = self._open_mavlink_connection()
        logging.warning(
            "Reinitialized local MAVLink listener on port %s after %s.",
            self.local_mavlink_port,
            reason,
        )

    def log_debug(self, message):
        """Logs a debug message if debugging is enabled."""
        if self.debug_enabled:
            logging.debug(message)

    def log_info(self, message):
        """Logs an info message if debugging is enabled."""
        if self.debug_enabled:
            logging.info(message)

    def log_warning(self, message):
        """Logs a warning message if debugging is enabled."""
        if self.debug_enabled:
            logging.warning(message)

    def mavlink_monitor(self):
        """
        Continuously monitor for incoming Mavlink messages and process them.
        """
        consecutive_timeouts = 0

        while self.run_telemetry_thread.is_set():
            try:
                msg = self.mav.recv_match(
                    type=self.message_filter,
                    blocking=True,
                    timeout=self.local_mavlink_timeout_sec,
                )
            except Exception as exc:
                logging.warning("Local MAVLink receive error: %s", exc)
                consecutive_timeouts = 0
                self._reset_mavlink_connection(f"receive error ({type(exc).__name__})")
                continue

            if msg is not None:
                if consecutive_timeouts > 0:
                    logging.info(
                        "Local MAVLink telemetry restored after %s timeout(s).",
                        consecutive_timeouts,
                    )
                    consecutive_timeouts = 0
                self.process_message(msg)
                self.latest_messages[msg.get_type()] = msg
                continue

            consecutive_timeouts += 1
            if consecutive_timeouts == 1:
                logging.warning('No MAVLink message received within timeout period')

            if consecutive_timeouts >= self.local_mavlink_reconnect_after_timeouts:
                self._reset_mavlink_connection(
                    f"{consecutive_timeouts} consecutive timeouts",
                )
                consecutive_timeouts = 0

    def process_message(self, msg):
        """
        Process incoming Mavlink messages based on their type and update the drone_config object.
        """
        msg_type = msg.get_type()
        self.latest_messages[msg_type] = msg

        if msg_type == 'GLOBAL_POSITION_INT':
            self.process_global_position_int(msg)
        elif msg_type == 'HOME_POSITION':
            self.set_home_position(msg)
        elif msg_type == 'BATTERY_STATUS':
            self.process_battery_status(msg)
        elif msg_type == 'ATTITUDE':
            self.process_attitude(msg)
        elif msg_type == 'HEARTBEAT':
            self.process_heartbeat(msg)
        elif msg_type == 'GPS_RAW_INT':
            self.process_gps_raw_int(msg)
        elif msg_type == 'LOCAL_POSITION_NED':
            self.process_local_position_ned(msg)
        elif msg_type == 'GPS_GLOBAL_ORIGIN':
            self.process_gps_global_origin(msg)
        elif msg_type == 'SYS_STATUS':
            self.process_sys_status(msg)
        elif msg_type == 'STATUSTEXT':
            self.process_status_text(msg)
        else:
            self.log_debug(f"Received unhandled message type: {msg.get_type()}")

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def _mark_telemetry_update(self, now_ms: Optional[int] = None) -> None:
        timestamp_ms = int(now_ms if now_ms is not None else self._now_ms())
        self.drone_config.last_update_timestamp = max(1, timestamp_ms // 1000)
        self.drone_config.telemetry_timestamp_ms = timestamp_ms
        self.drone_config.telemetry_sequence = int(getattr(self.drone_config, 'telemetry_sequence', 0) or 0) + 1

    @staticmethod
    def _is_valid_global_position(lat_deg: float, lon_deg: float) -> bool:
        if not (-90.0 <= lat_deg <= 90.0 and -180.0 <= lon_deg <= 180.0):
            return False
        return abs(lat_deg) > 0.000001 or abs(lon_deg) > 0.000001

    @staticmethod
    def _severity_name(severity: Optional[int]) -> str:
        mapping = {
            0: 'emergency',
            1: 'alert',
            2: 'critical',
            3: 'error',
            4: 'warning',
            5: 'notice',
            6: 'info',
            7: 'debug',
        }
        try:
            return mapping.get(int(severity), 'info')
        except (TypeError, ValueError):
            return 'info'

    @staticmethod
    def _severity_rank(severity: str) -> int:
        order = {
            'emergency': 0,
            'alert': 1,
            'critical': 2,
            'error': 3,
            'warning': 4,
            'notice': 5,
            'info': 6,
            'debug': 7,
        }
        return order.get(severity, 6)

    @staticmethod
    def _trim_statustext(text: Any) -> str:
        if isinstance(text, bytes):
            decoded = text.decode('utf-8', errors='ignore')
        else:
            decoded = str(text or '')
        return decoded.split('\x00', 1)[0].strip()

    def _expire_status_text_buffers(self) -> None:
        cutoff = time.time() - STATUS_TEXT_BUFFER_RETENTION_S
        stale_ids = [
            message_id
            for message_id, buffer in self._status_text_buffers.items()
            if buffer.get('created_at', 0) < cutoff
        ]
        for message_id in stale_ids:
            self._status_text_buffers.pop(message_id, None)

    def _collect_status_text(self, msg) -> Optional[str]:
        text_chunk = self._trim_statustext(getattr(msg, 'text', ''))
        if not text_chunk:
            return None

        message_id = int(getattr(msg, 'id', 0) or 0)
        chunk_seq = int(getattr(msg, 'chunk_seq', 0) or 0)
        if message_id == 0 and chunk_seq == 0:
            return text_chunk

        self._expire_status_text_buffers()
        buffer = self._status_text_buffers.setdefault(
            message_id,
            {'created_at': time.time(), 'chunks': {}},
        )
        buffer['chunks'][chunk_seq] = text_chunk

        if len(text_chunk) >= 50:
            return None

        combined = ''.join(
            chunk
            for _, chunk in sorted(buffer['chunks'].items(), key=lambda item: item[0])
        ).strip()
        self._status_text_buffers.pop(message_id, None)
        return combined or None

    @staticmethod
    def _classify_status_text(message: str, severity: str) -> Dict[str, Any]:
        lowered = message.lower()
        is_preflight = any(
            token in lowered
            for token in ('preflight', 'prearm', 'arm denied', 'arming denied', 'takeoff denied')
        )
        blocks_readiness = any(
            token in lowered
            for token in ('preflight fail', 'prearm fail', 'arm denied', 'arming denied', 'takeoff denied')
        )
        category = 'preflight' if is_preflight else 'system'
        if is_preflight and not blocks_readiness and severity in {'emergency', 'alert', 'critical', 'error'}:
            blocks_readiness = True

        return {
            'category': category,
            'blocks_readiness': blocks_readiness,
        }

    def _store_status_message(self, message: Dict[str, Any]) -> None:
        key = f"{message['category']}::{message['severity']}::{message['message'].strip().lower()}"
        self._status_messages[key] = message
        self._status_messages.move_to_end(key)

        active_messages = self._get_recent_status_messages(self._now_ms())
        self.drone_config.status_messages = active_messages[-STATUS_TEXT_MAX_MESSAGES:]

    def _get_recent_status_messages(self, now_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        current_ms = now_ms if now_ms is not None else self._now_ms()
        cutoff = current_ms - STATUS_TEXT_RETENTION_MS
        stale_keys = [
            key for key, message in self._status_messages.items()
            if int(message.get('timestamp', 0)) < cutoff
        ]
        for key in stale_keys:
            self._status_messages.pop(key, None)
        return list(self._status_messages.values())

    @staticmethod
    def _dedupe_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for message in messages:
            key = (
                message.get('source'),
                message.get('message', '').strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(message)
        return deduped

    @staticmethod
    def _build_message(source: str, severity: str, message: str, timestamp: int) -> Dict[str, Any]:
        return {
            'source': source,
            'severity': severity,
            'message': message,
            'timestamp': timestamp,
        }

    @staticmethod
    def _get_system_status_name(system_status: int) -> str:
        names = {
            0: 'UNINIT',
            1: 'BOOT',
            2: 'CALIBRATING',
            3: 'STANDBY',
            4: 'ACTIVE',
            5: 'CRITICAL',
            6: 'EMERGENCY',
            7: 'POWEROFF',
            8: 'FLIGHT_TERMINATION',
        }
        return names.get(system_status, f'UNKNOWN({system_status})')

    def process_status_text(self, msg):
        """Capture recent PX4 warnings/errors so readiness issues are visible in telemetry and UI."""
        message = self._collect_status_text(msg)
        if not message:
            return

        severity = self._severity_name(getattr(msg, 'severity', None))
        if self._severity_rank(severity) > self._severity_rank('warning'):
            return

        classification = self._classify_status_text(message, severity)
        timestamp = self._now_ms()
        self._store_status_message({
            'source': 'px4',
            'severity': severity,
            'category': classification['category'],
            'message': message,
            'timestamp': timestamp,
            'blocks_readiness': classification['blocks_readiness'],
        })
        self._update_pre_arm_status()

    def process_heartbeat(self, msg):
        """
        Process the HEARTBEAT message and update flight mode and system status.
        Follows MAVLink/PX4 standards for proper flight mode handling.
        """
        # Store previous values for change detection
        prev_custom_mode = self.drone_config.custom_mode
        prev_armed = self.drone_config.is_armed

        # Store MAVLink HEARTBEAT fields according to specification
        self.drone_config.base_mode = msg.base_mode      # MAV_MODE flags (armed, custom mode enabled, etc.)
        self.drone_config.custom_mode = msg.custom_mode  # PX4-specific flight mode
        self.drone_config.system_status = msg.system_status  # MAV_STATE (STANDBY, ACTIVE, etc.)

        # Extract arming status from base_mode flags (raw MAVLink value)
        mavlink_armed_flag = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0

        # Enhanced arming detection for SITL and real operations
        # In SITL, the armed flag can be misleading, so we cross-reference with flight mode and system status
        if mavlink_armed_flag:
            # If MAVLink says armed, verify with flight mode and system status
            if (self.drone_config.custom_mode == 0 and
                self.drone_config.system_status == mavutil.mavlink.MAV_STATE_ACTIVE):
                # Special case: SITL shows armed flag but custom_mode=0 (Initializing)
                # This typically means the system is ready but not actually armed for flight
                self.drone_config.is_armed = False
                self.log_debug(f"⚠️ SITL Armed flag detected but flight mode is Initializing - treating as disarmed")
            else:
                # Normal case: armed flag set and flight mode is valid
                self.drone_config.is_armed = True
        else:
            # MAVLink says disarmed
            self.drone_config.is_armed = False

        # Update pre-arm readiness based on system status and sensor health
        self._update_pre_arm_status()

        # Get flight mode name for logging
        mode_name = self._get_flight_mode_name(self.drone_config.custom_mode)

        # Always log HEARTBEAT reception for debugging
        self.log_info(f"HEARTBEAT: custom_mode={self.drone_config.custom_mode} ({mode_name}), "
                     f"base_mode={self.drone_config.base_mode}, armed={self.drone_config.is_armed}")

        # Log flight mode changes
        if self.drone_config.custom_mode != prev_custom_mode:
            self.log_info(f"🔄 Flight mode changed: {prev_custom_mode} → {self.drone_config.custom_mode} ({mode_name})")

        # Log arming changes
        if self.drone_config.is_armed != prev_armed:
            self.log_info(f"🔄 Arming changed: {prev_armed} → {self.drone_config.is_armed}")

        # Special attention to custom modes and offboard
        if self.drone_config.custom_mode == 393216:
            self.log_info(f"🚁 OFFBOARD mode active: {self.drone_config.custom_mode}")
        elif self.drone_config.custom_mode in [33816576, 100925440]:
            self.log_info(f"🚁 Custom mode active: {mode_name} ({self.drone_config.custom_mode})")
        elif self.drone_config.custom_mode == 0:
            self.log_warning(f"⚠️ Flight mode is 0 - possible issue with HEARTBEAT or mode initialization")
        elif mode_name.startswith('Unknown'):
            main_mode = self.drone_config.custom_mode >> 16
            sub_mode = self.drone_config.custom_mode & 0xFFFF
            self.log_warning(f"⚠️ Unknown flight mode: {self.drone_config.custom_mode} (Main: {main_mode}, Sub: {sub_mode})")
                      
    def _update_pre_arm_status(self):
        """
        Update the readiness report from both live telemetry and recent PX4 status text.

        `is_ready_to_arm` stays as a simple boolean for compatibility, but the
        detailed readiness state is published through:
        - readiness_status / readiness_summary
        - readiness_checks
        - preflight_blockers / preflight_warnings
        - status_messages
        """
        now_ms = self._now_ms()
        recent_status_messages = self._get_recent_status_messages(now_ms)

        has_live_vehicle_state = any([
            self.drone_config.system_status > 0,
            self.drone_config.last_update_timestamp > 0,
            bool(recent_status_messages),
        ])

        if not has_live_vehicle_state:
            self.drone_config.is_ready_to_arm = False
            self.drone_config.readiness_status = "unknown"
            self.drone_config.readiness_summary = "Waiting for PX4 telemetry"
            self.drone_config.readiness_checks = []
            self.drone_config.preflight_blockers = []
            self.drone_config.preflight_warnings = []
            self.drone_config.status_messages = []
            self.drone_config.preflight_last_update = now_ms
            return

        px4_blockers = [
            self._build_message('px4', message['severity'], message['message'], message['timestamp'])
            for message in recent_status_messages
            if message.get('category') == 'preflight' and message.get('blocks_readiness')
        ]
        px4_warnings = [
            self._build_message('px4', message['severity'], message['message'], message['timestamp'])
            for message in recent_status_messages
            if message.get('category') == 'preflight' and not message.get('blocks_readiness')
        ]

        system_ready = self.drone_config.system_status >= mavutil.mavlink.MAV_STATE_STANDBY
        imu_sensors_ready = (
            self.drone_config.is_gyrometer_calibration_ok and
            self.drone_config.is_accelerometer_calibration_ok
        )
        mag_ready = self.drone_config.is_magnetometer_calibration_ok
        gps_fix_ok = getattr(self.drone_config, 'gps_fix_type', 0) >= 3

        gps_dependent_modes = [
            196608,
            262147,
            262148,
            262149,
            196609,
            262152,
        ]
        mode_requires_gps = self.drone_config.custom_mode in gps_dependent_modes
        takeoff_requires_gps = not bool(getattr(self.drone_config, 'is_armed', False))
        gps_required = bool(getattr(self, 'require_global_position', False)) or takeoff_requires_gps or mode_requires_gps
        home_ready = bool(getattr(self.drone_config, 'px4_home_position_set', False))

        if gps_required:
            gps_ready = gps_fix_ok and self.drone_config.hdop > 0 and self.drone_config.hdop < 2.0
        else:
            gps_ready = True

        sensors_ready = imu_sensors_ready and mag_ready

        has_strong_live_signal = any([
            bool(getattr(self.drone_config, 'base_mode', 0)),
            bool(getattr(self.drone_config, 'custom_mode', 0)),
            bool(getattr(self.drone_config, 'px4_home_position_set', False)),
            getattr(self.drone_config, 'gps_fix_type', 0) >= 3,
        ])
        system_state_name = self._get_system_status_name(self.drone_config.system_status)
        system_state_advisory = None
        system_ready_effective = system_ready
        if (
            not system_ready
            and self.drone_config.system_status == mavutil.mavlink.MAV_STATE_UNINIT
            and has_strong_live_signal
            and len(px4_blockers) == 0
        ):
            system_ready_effective = True
            system_state_advisory = self._build_message(
                'telemetry',
                'warning',
                (
                    f"Vehicle system state reports {system_state_name}, but PX4 preflight is healthy and "
                    "live telemetry is present. Treating the MAVLink system-state field as advisory."
                ),
                now_ms,
            )

        heuristic_blockers: List[Dict[str, Any]] = []
        if not system_ready and not system_state_advisory:
            heuristic_blockers.append(self._build_message(
                'telemetry',
                'error',
                f"Vehicle system state is {system_state_name}; not yet ready for arming.",
                now_ms,
            ))
        if not imu_sensors_ready:
            heuristic_blockers.append(self._build_message(
                'telemetry',
                'error',
                "IMU health is incomplete; gyro and accelerometer must both report healthy.",
                now_ms,
            ))
        if not mag_ready:
            heuristic_blockers.append(self._build_message(
                'telemetry',
                'error',
                "Magnetometer health is incomplete; heading is not yet trustworthy for arming.",
                now_ms,
            ))
        if gps_required and not gps_ready:
            requirement_context = "takeoff readiness" if takeoff_requires_gps and not mode_requires_gps else "the current flight mode"
            if not gps_fix_ok:
                gps_message = f"GPS fix is below 3D while {requirement_context} requires GPS."
            else:
                gps_message = f"GPS quality is insufficient for {requirement_context} (HDOP={self.drone_config.hdop:.2f})."
            heuristic_blockers.append(self._build_message('telemetry', 'error', gps_message, now_ms))
        if gps_required and not home_ready:
            requirement_context = "Takeoff readiness" if takeoff_requires_gps else "This mode"
            heuristic_blockers.append(self._build_message(
                'telemetry',
                'error',
                f"{requirement_context} is waiting for PX4 home position.",
                now_ms,
            ))

        heuristic_warnings: List[Dict[str, Any]] = []
        if system_state_advisory:
            heuristic_warnings.append(system_state_advisory)
        if not gps_required and getattr(self.drone_config, 'gps_fix_type', 0) < 3:
            heuristic_warnings.append(self._build_message(
                'telemetry',
                'warning',
                "GPS is not required for the current airborne mode, but fix quality is currently low.",
                now_ms,
            ))

        blockers = self._dedupe_messages(px4_blockers + heuristic_blockers)
        warnings = self._dedupe_messages(px4_warnings + heuristic_warnings)
        readiness_checks = [
            {
                'id': 'system',
                'label': 'Vehicle status',
                'ready': system_ready_effective,
                'detail': (
                    f"PX4 system state: {system_state_name} "
                    "(treated as advisory because live PX4 preflight is healthy)"
                    if system_state_advisory else
                    f"PX4 system state: {system_state_name}"
                ),
            },
            {
                'id': 'imu',
                'label': 'IMU health',
                'ready': imu_sensors_ready,
                'detail': "Gyro and accelerometer health",
            },
            {
                'id': 'mag',
                'label': 'Magnetometer',
                'ready': mag_ready,
                'detail': "Compass / heading health",
            },
            {
                'id': 'gps',
                'label': 'GPS requirement',
                'ready': gps_ready,
                'detail': (
                    f"GPS required now: {'yes' if gps_required else 'no'}; "
                    f"fix={getattr(self.drone_config, 'gps_fix_type', 0)}, hdop={self.drone_config.hdop:.2f}"
                ),
            },
            {
                'id': 'home',
                'label': 'Home position',
                'ready': (not gps_required) or home_ready,
                'detail': (
                    "PX4 home position is set"
                    if home_ready else
                    ("Awaiting PX4 home position before takeoff." if gps_required else "Home position is not required in the current mode.")
                ),
            },
            {
                'id': 'px4',
                'label': 'PX4 arming report',
                'ready': len(px4_blockers) == 0,
                'detail': (
                    "No active PX4 preflight blockers"
                    if not px4_blockers else
                    f"{len(px4_blockers)} active PX4 preflight blocker(s)"
                ),
            },
        ]

        self.drone_config.is_ready_to_arm = (
            system_ready_effective
            and sensors_ready
            and gps_ready
            and ((not gps_required) or home_ready)
            and not blockers
        )
        if blockers:
            readiness_status = "blocked"
            readiness_summary = blockers[0]['message']
        elif warnings and not system_state_advisory:
            readiness_status = "warning"
            readiness_summary = warnings[0]['message']
        else:
            readiness_status = "ready"
            readiness_summary = (
                "Ready to fly with telemetry advisory"
                if system_state_advisory else
                "Ready to fly"
            )

        self.drone_config.readiness_status = readiness_status
        self.drone_config.readiness_summary = readiness_summary
        self.drone_config.readiness_checks = readiness_checks
        self.drone_config.preflight_blockers = blockers
        self.drone_config.preflight_warnings = warnings
        self.drone_config.status_messages = recent_status_messages[-STATUS_TEXT_MAX_MESSAGES:]
        self.drone_config.preflight_last_update = now_ms

        self.log_debug(
            "Pre-arm checks: "
            f"system={system_ready_effective} (raw={system_state_name}), imu={imu_sensors_ready}, mag={mag_ready}, "
            f"gps_required={gps_required}, gps_ready={gps_ready}, home_ready={home_ready} "
            f"(fix={getattr(self.drone_config, 'gps_fix_type', 0)}, hdop={self.drone_config.hdop}) "
            f"px4_blockers={len(px4_blockers)} -> ready={self.drone_config.is_ready_to_arm}"
        )

    def _get_flight_mode_name(self, custom_mode):
        """
        Helper function to decode PX4 custom_mode to human-readable name for debugging.
        This matches the frontend mapping in px4FlightModes.js
        """
        flight_modes = {
            0: 'Unknown/Uninit',
            65536: 'Manual',
            131072: 'Altitude',
            196608: 'Position',
            327680: 'Acro',
            393216: 'Offboard',
            458752: 'Stabilized',
            524288: 'Rattitude',
            655360: 'Termination',
            262144: 'Auto',
            262145: 'Ready',
            262146: 'Takeoff',
            262147: 'Hold',
            262148: 'Mission',
            262149: 'Return',
            262150: 'Land',
            262152: 'Follow',
            262153: 'Precision Land',
            262154: 'VTOL Takeoff',
            196609: 'Orbit',
            196610: 'Position Slow',
            50593792: 'Hold (GPS-less)',  # Special Hold mode variant

            # Additional Offboard mode variations (PX4 sub-modes)
            393217: 'Offboard',  # OFFBOARD with sub-mode 1
            393218: 'Offboard',  # OFFBOARD with sub-mode 2
            393219: 'Offboard',  # OFFBOARD with sub-mode 3
            393220: 'Offboard',  # OFFBOARD with sub-mode 4

            # Custom/Extended flight modes (observed in field)
            33816576: 'Takeoff',   # Custom takeoff mode (516 << 16)
            100925440: 'Land'      # Custom land mode (1540 << 16)
        }
        # Simple fallback for unknown modes
        if custom_mode not in flight_modes:
            main_mode = (custom_mode >> 16) & 0xFFFF
            sub_mode = custom_mode & 0xFFFF

            # Try intelligent detection for common patterns
            if main_mode == 6:
                return 'Offboard'
            elif main_mode == 516:
                return 'Takeoff'
            elif main_mode == 1540:
                return 'Land'
            elif main_mode == 4:
                # Auto modes
                auto_sub_modes = {
                    1: 'Ready', 2: 'Takeoff', 3: 'Hold',
                    4: 'Mission', 5: 'Return', 6: 'Land'
                }
                return auto_sub_modes.get(sub_mode, f'Auto({sub_mode})')
            elif main_mode == 1:
                return 'Manual'
            elif main_mode == 2:
                return 'Altitude'
            elif main_mode == 3:
                return 'Position'
            elif main_mode == 5:
                return 'Acro'
            elif main_mode == 7:
                return 'Stabilized'

            # Log unknown modes for debugging
            self.log_warning(f"Unknown flight mode: {custom_mode} (Main: {main_mode}, Sub: {sub_mode})")
            return f'Unknown({custom_mode})'

        return flight_modes[custom_mode]

    def process_sys_status(self, msg):
        """
        Process the SYS_STATUS message and update sensor health statuses.
        """
        # Check if sensors are healthy and calibrated
        self.drone_config.is_gyrometer_calibration_ok = (msg.onboard_control_sensors_health & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_GYRO) != 0
        self.drone_config.is_accelerometer_calibration_ok = (msg.onboard_control_sensors_health & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_ACCEL) != 0
        self.drone_config.is_magnetometer_calibration_ok = (msg.onboard_control_sensors_health & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_MAG) != 0
        self.log_debug(f"Sensor health updated: Gyro: {self.drone_config.is_gyrometer_calibration_ok}, "
                       f"Accel: {self.drone_config.is_accelerometer_calibration_ok}, Mag: {self.drone_config.is_magnetometer_calibration_ok}")
        self._update_pre_arm_status()

    def process_gps_raw_int(self, msg):
        """
        Process the GPS_RAW_INT message and update GPS data including HDOP, VDOP, and fix status.
        """
        # Update GPS data including HDOP and VDOP (if available)
        self.drone_config.hdop = msg.eph / 1E2  # Horizontal dilution of precision
        self.drone_config.vdop = msg.epv / 1E2  # Vertical dilution of precision (if applicable)

        # Update GPS fix status
        # GPS fix type: 0=No GPS, 1=No Fix, 2=2D Fix, 3=3D Fix, 4=DGPS, 5=RTK Float, 6=RTK Fixed
        self.drone_config.gps_fix_type = getattr(msg, 'fix_type', 0)
        self.drone_config.satellites_visible = getattr(msg, 'satellites_visible', 0)
        self.drone_config.gps_raw_timestamp_ms = self._now_ms()

        self.log_debug(f"Updated GPS - HDOP: {self.drone_config.hdop}, VDOP: {self.drone_config.vdop}, Fix: {self.drone_config.gps_fix_type}, Sats: {self.drone_config.satellites_visible}")
        self._update_pre_arm_status()

    def process_attitude(self, msg):
        """
        Process the ATTITUDE message and update the yaw value.
        """
        if msg.yaw is not None:
            self.drone_config.yaw = self.drone_config.radian_to_degrees_heading(msg.yaw)
            self.drone_config.yaw_rate_deg_s = float(getattr(msg, 'yawspeed', 0.0) or 0.0) * (180.0 / 3.141592653589793)
            self.log_debug(f"Updated yaw to: {self.drone_config.yaw}")
        else:
            logging.error('Received ATTITUDE message with invalid data')

    def set_home_position(self, msg):
        """
        Process the HOME_POSITION message and set the home position.
        """
        if msg.latitude is not None and msg.longitude is not None and msg.altitude is not None:
            self.drone_config.home_position = {
                'lat': msg.latitude / 1E7,
                'long': msg.longitude / 1E7,
                'alt': msg.altitude / 1E3
            }
            self.drone_config.px4_home_position_set = True
            self.drone_config.home_position_source = 'px4'

            if not self.home_position_logged:
                logging.info(f"Home position for drone {self.drone_config.hw_id} is set: {self.drone_config.home_position}")
                self.home_position_logged = True
        else:
            logging.error('Received HOME_POSITION message with invalid data')
            
    def process_gps_global_origin(self, msg):
        """
        Process the GPS_GLOBAL_ORIGIN message and update the drone_config with the vehicle's GPS local origin.

        The message includes:
            - latitude (int32_t, degE7): Convert to degrees by dividing by 1e7.
            - longitude (int32_t, degE7): Convert to degrees by dividing by 1e7.
            - altitude (int32_t, mm): Convert to meters by dividing by 1e3.
            - time_usec (uint64_t, us): Timestamp indicating when the origin was set.

        The processed data is stored in drone_config.gps_global_origin.
        """
        # Validate that all required fields are present and not None
        if (hasattr(msg, 'latitude') and msg.latitude is not None and
            hasattr(msg, 'longitude') and msg.longitude is not None and
            hasattr(msg, 'altitude') and msg.altitude is not None and
            hasattr(msg, 'time_usec') and msg.time_usec is not None):
            
            self.drone_config.gps_global_origin = {
                'lat': msg.latitude / 1e7,
                'lon': msg.longitude / 1e7,
                'alt': msg.altitude / 1e3,
                'time_usec': msg.time_usec
            }
            self.log_debug(f"Updated GPS global origin: {self.drone_config.gps_global_origin}")
        else:
            logging.error('Received GPS_GLOBAL_ORIGIN message with invalid data')


    def process_global_position_int(self, msg):
        """
        Process the GLOBAL_POSITION_INT message and update the position and velocity.
        """
        if msg.lat is not None and msg.lon is not None and msg.alt is not None:
            now_ms = self._now_ms()
            lat_deg = msg.lat / 1E7
            lon_deg = msg.lon / 1E7
            alt_m = msg.alt / 1E3
            if not self._is_valid_global_position(lat_deg, lon_deg):
                self.drone_config.global_position_valid = False
                self.drone_config.position_source = 'invalid_global_position'
                logging.warning(
                    "Ignoring invalid GLOBAL_POSITION_INT for drone %s: lat=%s lon=%s alt=%s",
                    self.drone_config.hw_id,
                    lat_deg,
                    lon_deg,
                    alt_m,
                )
                return

            self.drone_config.position = {
                'lat': lat_deg,
                'long': lon_deg,
                'alt': alt_m
            }
            self.drone_config.velocity = {
                'north': msg.vx / 1E2,
                'east': msg.vy / 1E2,
                'down': msg.vz / 1E2
            }
            self.drone_config.global_position_valid = True
            self.drone_config.global_position_timestamp_ms = now_ms
            self.drone_config.position_source = 'global_position_int'
            self._mark_telemetry_update(now_ms)

            if self.drone_config.home_position is None:
                self.drone_config.home_position = self.drone_config.position.copy()
                self.drone_config.home_position_source = 'fallback_position'
                logging.info(
                    "Fallback home position cache for drone %s set from first global position sample: %s",
                    self.drone_config.hw_id,
                    self.drone_config.home_position,
                )
        else:
            logging.error('Received GLOBAL_POSITION_INT message with invalid data')

    def process_battery_status(self, msg):
        """
        Process the BATTERY_STATUS message and update the battery voltage.
        """
        if msg.voltages and len(msg.voltages) > 0:
            self.drone_config.battery = msg.voltages[0] / 1E3  # Convert from mV to V
            self.log_debug(f"Updated battery voltage to: {self.drone_config.battery}V")
        else:
            logging.error('Received BATTERY_STATUS message with invalid data')
            
    def process_local_position_ned(self, msg):
        """
        Process LOCAL_POSITION_NED (#32) message and update drone_config
        with MAVLink-native field names and values.
        """
        required_fields = ['time_boot_ms', 'x', 'y', 'z', 'vx', 'vy', 'vz']
        
        if not all(hasattr(msg, field) for field in required_fields):
            logging.error('LOCAL_POSITION_NED message missing required fields')
            return

        # Update all fields in one atomic operation
        self.drone_config.local_position_ned.update({
            'time_boot_ms': msg.time_boot_ms,
            'x': msg.x,
            'y': msg.y,
            'z': msg.z,
            'vx': msg.vx,
            'vy': msg.vy,
            'vz': msg.vz
        })
        self._mark_telemetry_update()
        
        self.log_debug(f"NED Update: X:{msg.x:.2f}m Y:{msg.y:.2f}m Z:{msg.z:.2f}m | "
                    f"VX:{msg.vx:.2f}m/s VY:{msg.vy:.2f}m/s VZ:{msg.vz:.2f}m/s")

    def __del__(self):
        """
        Ensure the telemetry thread is stopped when the object is deleted.
        """
        run_telemetry_thread = getattr(self, 'run_telemetry_thread', None)
        if run_telemetry_thread is not None:
            run_telemetry_thread.clear()

        # Wait for the telemetry thread to stop
        telemetry_thread = getattr(self, 'telemetry_thread', None)
        if telemetry_thread is not None and telemetry_thread.is_alive():
            telemetry_thread.join()
