#!/usr/bin/env python3
"""
===============================================================
Drone Action Executor with MAVSDK
---------------------------------------------------------------
Usage Examples:
---------------
1) Take off to 15 metres:
   python3 actions.py --action takeoff --altitude 15

2) Land without setting any parameters:
   python3 actions.py --action land

3) Update code from a specific branch (e.g., "new_feature_branch"):
   python3 actions.py --action update_code --branch new_feature_branch

4) Execute a typed precision move request:
   python3 actions.py --action precision_move --request-file /path/to/request.json

Description:
------------
This script executes various drone actions using MAVSDK:
 - takeoff, land, hold, test, reboot, kill_terminate, update_code,
   return_rtl and precision_move.
 - Safely manages MAVSDK server launch/teardown.
 - Provides logging, exit codes, LED status feedback, and robust error handling.
 - PX4 parameter changes are intentionally excluded. Use the typed PX4
   Parameters API/dashboard workflow for mutation, diff, readback, and audit.

---------------------------------------------------------------
"""

import argparse
import asyncio
import os
import requests
import signal
import socket
import subprocess
import sys
import time

import psutil
from mavsdk import System, telemetry
from mavsdk.action import ActionError
from src.action_runners import (
    ActionExecutionContext,
    ActionInvocation,
    ActionSpec,
    load_request_payload,
)
from src.action_runners.precision_move import precision_move
from src.action_result_protocol import (
    TerminalActionResult,
    emit_terminal_result,
    make_terminal_result,
)
from src.async_stream_utils import (
    managed_async_stream,
    monotonic_deadline,
    next_stream_sample,
)
from src.action_safety import (
    ACTION_SAFETY_CLEANUP_TIMEOUT_SEC,
    AIRBORNE_MIN_RELATIVE_ALTITUDE_M,
    GROUND_MAX_RELATIVE_ALTITUDE_M,
    ActionSafetyError,
    VehicleStateObservation,
    observe_authoritative_vehicle_state,
)
from src.command_contract import GroundTestSafetyAcknowledgement
from src.drone_config import ConfigLoader
from src.flight_timeout_utils import calculate_land_disarm_timeout, calculate_rtl_completion_timeout
from src.drone_api_routes import DRONE_NAVIGATION_HOME_ROUTE, DRONE_STATE_ROUTE
from src.led_controller import LEDController
from src.mission_startup import arm_with_preflight_gate
from src.params import Params

# Unified logging system
from mds_logging.drone import init_drone_logging
from mds_logging import get_logger, register_component

register_component("actions", "drone", "Drone action execution")
init_drone_logging()
logger = get_logger("actions")

# Return codes: 0 = success, 1 = failure
RETURN_CODE = 0
_LAST_ACTION_FAILURE: TerminalActionResult | None = None
_CURRENT_ACTION_NAME: str | None = None
_LAST_FINAL_VEHICLE_STATE: dict | None = None
_LAST_ACTION_CLEANUP_EVIDENCE: dict | None = None
_REQUESTED_PROCESS_SIGNAL: str | None = None
_LED_FEEDBACK_DISABLED = False

GRPC_PORT = Params.DEFAULT_GRPC_PORT
UDP_PORT = Params.mavsdk_port
HW_ID = None

# -----------------------
# Helper / Setup Functions
# -----------------------

def fail(
    *,
    code: str | None = None,
    phase: str = "execution",
    operator_message: str | None = None,
    retryable: bool = False,
    evidence: dict | None = None,
    final_vehicle_state: dict | None = None,
):
    """
    Set the process return code and, when supplied, preserve the first
    structured root cause for the terminal action result.

    The first structured failure wins: later cleanup/LED diagnostics must not
    replace the vehicle-command failure that caused the action to stop.
    """
    global RETURN_CODE, _LAST_ACTION_FAILURE, _LAST_FINAL_VEHICLE_STATE
    RETURN_CODE = 1
    if final_vehicle_state is not None:
        _LAST_FINAL_VEHICLE_STATE = dict(final_vehicle_state)
    if code and operator_message and _LAST_ACTION_FAILURE is None:
        _LAST_ACTION_FAILURE = make_terminal_result(
            success=False,
            code=code,
            phase=phase,
            operator_message=operator_message,
            retryable=retryable,
            evidence=evidence or {},
            final_vehicle_state=_LAST_FINAL_VEHICLE_STATE,
        )


def _set_final_vehicle_state(final_vehicle_state: dict | None) -> None:
    """Retain the latest action-local terminal state for the result protocol."""
    global _LAST_FINAL_VEHICLE_STATE
    _LAST_FINAL_VEHICLE_STATE = (
        dict(final_vehicle_state) if final_vehicle_state is not None else None
    )


def _set_action_cleanup_evidence(evidence: dict | None) -> None:
    """Retain bounded cleanup facts for cooperative process interruption."""
    global _LAST_ACTION_CLEANUP_EVIDENCE
    _LAST_ACTION_CLEANUP_EVIDENCE = dict(evidence) if evidence is not None else None


def _exception_detail(exc: BaseException) -> tuple[str, dict]:
    """Extract bounded MAVSDK result detail without depending on one SDK version."""
    evidence = {
        "action": _CURRENT_ACTION_NAME or "unknown",
        "exception_type": type(exc).__name__,
    }
    result = getattr(exc, "_result", None) or getattr(exc, "result", None)
    result_value = getattr(result, "result", None)
    result_name = getattr(result_value, "name", None)
    result_text = getattr(result, "result_str", None)
    if result_name:
        evidence["mavsdk_result"] = result_name
    elif result_value is not None:
        evidence["mavsdk_result"] = str(result_value)
    if result_text:
        evidence["mavsdk_result_str"] = str(result_text)

    detail = str(result_text or exc or type(exc).__name__)
    return detail, evidence


def _record_action_exception(action_name: str, exc: BaseException) -> None:
    primary_error = getattr(exc, "primary_error", exc)
    final_vehicle_state = getattr(exc, "final_vehicle_state", None)
    if final_vehicle_state is None:
        final_vehicle_state = _LAST_FINAL_VEHICLE_STATE
    transaction_evidence = getattr(exc, "evidence", None)
    cleanup_unconfirmed = bool(
        isinstance(transaction_evidence, dict)
        and transaction_evidence.get("cleanup_confirmed") is False
    )
    cleanup_warning = (
        " Safety cleanup could not be confirmed; keep clear of the vehicle and use the "
        "primary recovery controls."
        if cleanup_unconfirmed
        else ""
    )

    typed_code = getattr(primary_error, "code", None)
    typed_phase = getattr(primary_error, "phase", None)
    if isinstance(typed_code, str) and isinstance(typed_phase, str):
        typed_evidence = {
            "action": action_name,
            "exception_type": type(primary_error).__name__,
        }
        for attribute in ("observation", "battery", "blockers", "evidence", "timed_out"):
            value = getattr(primary_error, attribute, None)
            if value not in (None, [], {}):
                typed_evidence[attribute] = value
        if isinstance(transaction_evidence, dict):
            typed_evidence["transaction"] = transaction_evidence
        fail(
            code=typed_code,
            phase=typed_phase,
            operator_message=(
                (str(primary_error) or f"Action '{action_name}' was blocked.")
                + cleanup_warning
            ),
            retryable=bool(getattr(primary_error, "retryable", False)),
            evidence=typed_evidence,
            final_vehicle_state=final_vehicle_state,
        )
        return

    detail, evidence = _exception_detail(primary_error)
    evidence["action"] = action_name
    if isinstance(transaction_evidence, dict):
        evidence["transaction"] = transaction_evidence
    normalized_detail = detail.upper()
    if "COMMAND_DENIED" in normalized_detail or "DENIED" in normalized_detail:
        fail(
            code="PX4_COMMAND_DENIED",
            phase="vehicle_command",
            operator_message=(
                f"PX4 rejected the '{action_name}' vehicle command: {detail}. "
                "Resolve the reported vehicle health or flight-state condition before retrying."
                f"{cleanup_warning}"
            ),
            retryable=False,
            evidence=evidence,
            final_vehicle_state=final_vehicle_state,
        )
    else:
        fail(
            code=("MAVSDK_ACTION_ERROR" if isinstance(primary_error, ActionError) else "ACTION_EXECUTION_FAILED"),
            phase=("vehicle_command" if isinstance(primary_error, ActionError) else "execution"),
            operator_message=(
                f"The '{action_name}' vehicle command failed: {detail}."
                if isinstance(primary_error, ActionError)
                else f"Action '{action_name}' failed before terminal vehicle-state confirmation: {detail}."
            ) + cleanup_warning,
            retryable=isinstance(primary_error, (TimeoutError, asyncio.TimeoutError)),
            evidence=evidence,
            final_vehicle_state=final_vehicle_state,
        )


def _build_terminal_result(action_name: str | None) -> TerminalActionResult:
    """Build the process' single authoritative terminal result."""
    if RETURN_CODE == 0:
        return make_terminal_result(
            success=True,
            code="ACTION_COMPLETED",
            phase="completed",
            operator_message=f"Action '{action_name or 'unknown'}' completed successfully.",
            retryable=False,
            evidence={"action": action_name or "unknown"},
            final_vehicle_state=_LAST_FINAL_VEHICLE_STATE,
        )
    if _LAST_ACTION_FAILURE is not None:
        if (
            _LAST_FINAL_VEHICLE_STATE is not None
            and _LAST_ACTION_FAILURE.final_vehicle_state != _LAST_FINAL_VEHICLE_STATE
        ):
            return make_terminal_result(
                success=False,
                code=_LAST_ACTION_FAILURE.code,
                phase=_LAST_ACTION_FAILURE.phase,
                operator_message=_LAST_ACTION_FAILURE.operator_message,
                retryable=_LAST_ACTION_FAILURE.retryable,
                evidence=_LAST_ACTION_FAILURE.evidence,
                final_vehicle_state=_LAST_FINAL_VEHICLE_STATE,
            )
        return _LAST_ACTION_FAILURE
    return make_terminal_result(
        success=False,
        code="ACTION_FAILED",
        phase="execution",
        operator_message=(
            f"Action '{action_name or 'unknown'}' stopped before completion. "
            "Review the node unified log for supporting diagnostics."
        ),
        retryable=False,
        evidence={"action": action_name or "unknown"},
        final_vehicle_state=_LAST_FINAL_VEHICLE_STATE,
    )

def check_mavsdk_server_running(port):
    """
    Checks if a mavsdk_server process is already running on the specified port.
    Returns (bool, pid).
    """
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    return True, proc.info['pid']
        except Exception:
            pass
    return False, None

def wait_for_port(port, host='localhost', timeout=10.0):
    """
    Waits until a port on the specified host is open, or until timeout is reached.
    Returns True if open, False otherwise.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.2)
    return False

async def log_mavsdk_output(mavsdk_server):
    """
    Asynchronously reads MAVSDK server's stdout/stderr for logging.
    Filters known cleanup messages that appear during normal server shutdown.
    """
    # Known non-error messages that appear during normal MAVSDK cleanup
    CLEANUP_PATTERNS = [
        "Socket closed",
        "connection reset",
        "Broken pipe",
        "Connection refused",
        "EOF",
    ]

    loop = asyncio.get_event_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, mavsdk_server.stdout.readline)
            if not line:
                break
            logger.debug(f"MAVSDK Server: {line.decode().strip()}")
    except Exception:
        logger.exception("Error reading MAVSDK server stdout")

    try:
        while True:
            line = await loop.run_in_executor(None, mavsdk_server.stderr.readline)
            if not line:
                break
            msg = line.decode().strip()
            # Check if this is a known cleanup message (not a real error)
            if any(pattern.lower() in msg.lower() for pattern in CLEANUP_PATTERNS):
                logger.debug(f"MAVSDK cleanup: {msg}")
            else:
                logger.error(f"MAVSDK Server Error: {msg}")
    except Exception:
        logger.exception("Error reading MAVSDK server stderr")

def stop_mavsdk_server(mavsdk_server):
    """
    Gracefully stops the MAVSDK server if it's still running.
    """
    if mavsdk_server and mavsdk_server.poll() is None:
        logger.info("Stopping MAVSDK server...")
        mavsdk_server.terminate()
        try:
            mavsdk_server.wait(timeout=5)
            logger.info("MAVSDK server terminated gracefully.")
        except subprocess.TimeoutExpired:
            logger.warning("MAVSDK server did not terminate. Killing it.")
            mavsdk_server.kill()
            mavsdk_server.wait()
            logger.info("MAVSDK server killed.")
    else:
        logger.debug("MAVSDK server already stopped or never started.")

def find_mavsdk_server():
    """
    Finds the path to the mavsdk_server binary.
    Priority:
    1. MAVSDK_SERVER_PATH environment variable.
    2. Current script directory (relative to __file__).
    3. Default fallback directory: project root.
    """
    # 1. Check environment variable
    mavsdk_server_path = os.environ.get("MAVSDK_SERVER_PATH")
    if mavsdk_server_path and os.path.isfile(mavsdk_server_path):
        return mavsdk_server_path

    # 2. Check script directory (relative to __file__)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mavsdk_server_path = os.path.join(script_dir, "mavsdk_server")
    if os.path.isfile(mavsdk_server_path):
        return mavsdk_server_path

    # 3. Check fallback directory (project root)
    fallback_path = os.path.join(script_dir, "..", "mavsdk_server")
    if os.path.isfile(fallback_path):
        return fallback_path

    return None

def start_mavsdk_server(grpc_port, udp_port):
    """
    Starts or restarts the MAVSDK server, ensuring any previously running server
    on the same gRPC port is stopped first. Returns the subprocess.Popen instance.
    """
    is_running, pid = check_mavsdk_server_running(grpc_port)
    if is_running:
        logger.info(f"MAVSDK server already running on port {grpc_port}, terminating it.")
        try:
            psutil.Process(pid).terminate()
            psutil.Process(pid).wait(timeout=5)
            logger.info(f"Terminated existing MAVSDK server (PID: {pid}).")
        except psutil.NoSuchProcess:
            logger.warning(f"No process found with PID {pid}.")
        except psutil.TimeoutExpired:
            logger.warning(f"Process {pid} did not terminate, killing it.")
            psutil.Process(pid).kill()
            psutil.Process(pid).wait()
            logger.info(f"Killed MAVSDK server (PID: {pid}).")

    mavsdk_server_path = find_mavsdk_server()
    if not mavsdk_server_path:
        logger.error("mavsdk_server executable not found.")
        fail(
            code="MAVSDK_SERVER_UNAVAILABLE",
            phase="mavsdk_startup",
            operator_message="The local MAVSDK server executable is unavailable; no vehicle command was sent.",
            retryable=False,
        )
        sys.exit(1)

    logger.info(f"Starting MAVSDK server: {mavsdk_server_path} on gRPC:{grpc_port}, UDP:{udp_port}")
    try:
        mavsdk_server = subprocess.Popen(
            [mavsdk_server_path, "-p", str(grpc_port), f"udp://:{udp_port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        asyncio.create_task(log_mavsdk_output(mavsdk_server))

        if not wait_for_port(grpc_port, timeout=10):
            logger.error("MAVSDK server did not start listening in time.")
            mavsdk_server.terminate()
            fail(
                code="MAVSDK_SERVER_START_TIMEOUT",
                phase="mavsdk_startup",
                operator_message="The local MAVSDK server did not become ready before the startup timeout; no vehicle command was sent.",
                retryable=True,
            )
            sys.exit(1)

        logger.info("MAVSDK server ready.")
        return mavsdk_server
    except Exception:
        logger.exception("Failed to start MAVSDK server")
        fail(
            code="MAVSDK_SERVER_START_FAILED",
            phase="mavsdk_startup",
            operator_message="The local MAVSDK server failed to start; no vehicle command was sent.",
            retryable=True,
        )
        sys.exit(1)


# -----------------------
# Core Action Execution
# -----------------------

def _normalize_action_name(action_name: str | None) -> str | None:
    if action_name is None:
        return None
    normalized = str(action_name).strip().lower()
    return normalized or None


async def perform_action(action, altitude=None, branch=None, request_payload=None):
    """
    Main entry to perform the requested action with optional altitude, branch,
    and a typed request payload.
    """
    global _CURRENT_ACTION_NAME, _LAST_ACTION_FAILURE, _LAST_FINAL_VEHICLE_STATE
    global _LAST_ACTION_CLEANUP_EVIDENCE
    global _LED_FEEDBACK_DISABLED, RETURN_CODE
    action_name = _normalize_action_name(action)
    RETURN_CODE = 0
    _LAST_ACTION_FAILURE = None
    _LAST_FINAL_VEHICLE_STATE = None
    _LAST_ACTION_CLEANUP_EVIDENCE = None
    _LED_FEEDBACK_DISABLED = False
    _CURRENT_ACTION_NAME = action_name
    logger.info(
        f"Requested action: {action_name}, altitude: {altitude}, branch: {branch}"
    )
    global HW_ID
    invocation = ActionInvocation(
        action=action_name or "",
        altitude=altitude,
        branch=branch,
        request_payload=request_payload,
    )
    action_spec = get_action_spec(action_name)
    if action_spec is None:
        logger.error(f"Invalid action specified: {action_name}")
        fail(
            code="INVALID_ACTION",
            phase="validation",
            operator_message=f"Action '{action_name or 'missing'}' is not supported; no vehicle command was sent.",
            retryable=False,
            evidence={"action": action_name or "missing"},
        )
        return

    if not action_spec.requires_connection:
        if not await action_spec.runner(
            ActionExecutionContext(drone=None, hw_id=str(HW_ID) if HW_ID is not None else None, logger=logger),
            invocation,
        ):
            fail(
                code="ACTION_RUNNER_FAILED",
                phase="execution",
                operator_message=f"Action '{action_name}' stopped before completion.",
                retryable=False,
                evidence={"action": action_name},
            )
        return

    HW_ID = ConfigLoader.get_hw_id()

    if action != "update_code":
        # Vehicle actions require a canonical companion identity and config.
        if HW_ID is None:
            logger.error("No valid HW_ID found, cannot proceed.")
            fail(
                code="DRONE_IDENTITY_UNAVAILABLE",
                phase="configuration",
                operator_message="The companion computer has no valid hardware identity; no vehicle command was sent.",
                retryable=False,
                evidence={"action": action_name},
            )
            return

        drone_config = ConfigLoader.read_config(HW_ID)  # Returns raw CSV row dict (keys: hw_id, pos_id, ip, mavlink_port, serial_port, baudrate)
        if not drone_config:
            logger.error("Drone config not found, cannot proceed.")
            fail(
                code="DRONE_CONFIGURATION_UNAVAILABLE",
                phase="configuration",
                operator_message="No configuration was found for this drone identity; no vehicle command was sent.",
                retryable=False,
                evidence={"action": action_name, "hw_id": HW_ID},
            )
            return

    # Start MAVSDK if not just "update_code" (that doesn't need flight connect).
    grpc_port = GRPC_PORT
    udp_port = UDP_PORT
    logger.info(f"MAVSDK: gRPC Port: {grpc_port}, UDP Port: {udp_port}")

    mavsdk_server = start_mavsdk_server(grpc_port, udp_port)
    if not mavsdk_server:
        logger.error("Failed to start MAVSDK server.")
        fail(
            code="MAVSDK_SERVER_UNAVAILABLE",
            phase="mavsdk_startup",
            operator_message="The local MAVSDK server is unavailable; no vehicle command was sent.",
            retryable=True,
            evidence={"action": action_name},
        )
        return

    drone = System(mavsdk_server_address="localhost", port=grpc_port)
    logger.info("Connecting to drone...")
    try:
        await drone.connect(system_address=f"udp://:{udp_port}")
    except Exception:
        logger.exception("Failed to connect to MAVSDK server")
        fail(
            code="MAVSDK_CONNECTION_FAILED",
            phase="vehicle_connection",
            operator_message="The action process could not connect to the local MAVSDK service; no vehicle command was confirmed.",
            retryable=True,
            evidence={"action": action_name},
        )
        stop_mavsdk_server(mavsdk_server)
        return

    # Wait for connection
    if not await wait_for_drone_connection(drone):
        logger.error("Drone not connected in time.")
        fail(
            code="VEHICLE_CONNECTION_TIMEOUT",
            phase="vehicle_connection",
            operator_message="No PX4 connection was observed before the action timeout; no vehicle command was sent.",
            retryable=True,
            evidence={"action": action_name},
        )
        stop_mavsdk_server(mavsdk_server)
        return

    # Execute the requested action safely
    try:
        context = ActionExecutionContext(
            drone=drone,
            hw_id=str(HW_ID) if HW_ID is not None else None,
            logger=logger,
            grpc_port=grpc_port,
            udp_port=udp_port,
            mavsdk_server=mavsdk_server,
        )
        if not await action_spec.runner(context, invocation):
            fail(
                code="ACTION_RUNNER_FAILED",
                phase="execution",
                operator_message=f"Action '{action_name}' stopped before terminal vehicle-state confirmation.",
                retryable=False,
                evidence={"action": action_name},
            )
    except Exception as exc:
        logger.exception(f"Error performing action '{action_name}'")
        fail(
            code="ACTION_EXECUTION_FAILED",
            phase="execution",
            operator_message=f"Action '{action_name}' failed unexpectedly: {exc}.",
            retryable=False,
            evidence={"action": action_name, "exception_type": type(exc).__name__},
        )
    finally:
        stop_mavsdk_server(mavsdk_server)
        logger.info("Action completed.")

async def wait_for_drone_connection(drone, timeout=10):
    """
    Waits up to 'timeout' seconds for drone connection.
    Returns True if connected, else False.
    """
    logger.info("Waiting for drone connection state...")
    deadline = monotonic_deadline(timeout)
    try:
        async with managed_async_stream(drone.core.connection_state) as stream:
            while True:
                state = await next_stream_sample(
                    stream,
                    deadline=deadline,
                    description="drone connection",
                )
                if state.is_connected:
                    logger.info("Drone connected successfully.")
                    return True
    except TimeoutError:
        return False


async def wait_for_telemetry_condition(stream_factory, predicate, description, timeout=20):
    """
    Wait until a MAVSDK telemetry stream satisfies a predicate.

    This keeps action completion aligned with actual vehicle state changes
    instead of treating MAVSDK RPC acceptance as the terminal success signal.
    """
    deadline = monotonic_deadline(timeout)
    async with managed_async_stream(stream_factory) as stream:
        while True:
            sample = await next_stream_sample(
                stream,
                deadline=deadline,
                description=description,
            )
            if predicate(sample):
                logger.info(f"{description} confirmed.")
                return sample


def _get_local_drone_state_snapshot(timeout: float = 1.0):
    """Read the local drone API state as a fallback readiness signal for this container."""
    try:
        response = requests.get(
            f"http://127.0.0.1:{Params.drone_api_port}{DRONE_STATE_ROUTE}",
            timeout=timeout,
        )
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        return None
    return None


def _get_local_home_position_snapshot(timeout: float = 1.0):
    """Read the local drone API home position as a fallback altitude reference."""
    try:
        response = requests.get(
            f"http://127.0.0.1:{Params.drone_api_port}{DRONE_NAVIGATION_HOME_ROUTE}",
            timeout=timeout,
        )
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        return None
    return None


def _get_local_relative_altitude_snapshot(timeout: float = 1.0):
    """Derive relative altitude from the local drone API when MAVSDK telemetry lags."""
    drone_state = _get_local_drone_state_snapshot(timeout=timeout)
    home_position = _get_local_home_position_snapshot(timeout=timeout)
    if not drone_state or not home_position:
        return None

    try:
        current_altitude = float(drone_state.get("position_alt"))
        home_altitude = float(home_position.get("altitude"))
    except (TypeError, ValueError):
        return None

    return current_altitude - home_altitude


async def _get_current_relative_altitude(drone, timeout: float = 3.0):
    """Capture the current relative altitude, preferring the local API snapshot."""
    local_relative_altitude = await asyncio.to_thread(
        _get_local_relative_altitude_snapshot,
        timeout=1.0,
    )
    if local_relative_altitude is not None:
        return local_relative_altitude

    deadline = monotonic_deadline(timeout)
    try:
        async with managed_async_stream(drone.telemetry.position) as stream:
            position = await next_stream_sample(
                stream,
                deadline=deadline,
                description="current relative altitude",
            )
            return getattr(position, "relative_altitude_m", None)
    except TimeoutError:
        pass
    return None


async def _get_current_landed_state(drone, timeout: float = 3.0):
    """Read the current landed state without treating the read as a logged milestone."""
    deadline = monotonic_deadline(timeout)
    try:
        async with managed_async_stream(drone.telemetry.landed_state) as stream:
            return await next_stream_sample(
                stream,
                deadline=deadline,
                description="current landed state",
            )
    except TimeoutError:
        pass
    return None


class _ActionTransactionError(RuntimeError):
    """Preserve the primary failure while attaching cleanup/final-state facts."""

    def __init__(
        self,
        primary_error: Exception,
        *,
        evidence: dict,
        final_vehicle_state: dict | None,
    ) -> None:
        self.primary_error = primary_error
        self.evidence = dict(evidence)
        self.final_vehicle_state = (
            dict(final_vehicle_state) if final_vehicle_state is not None else None
        )
        super().__init__(str(primary_error) or type(primary_error).__name__)


def _safe_led_call(led_controller, method_name: str, *args) -> None:
    """Keep optional companion LED/SPI failures out of vehicle action results."""
    global _LED_FEEDBACK_DISABLED
    if led_controller is None or _LED_FEEDBACK_DISABLED:
        return
    try:
        getattr(led_controller, method_name)(*args)
    except Exception as exc:
        _LED_FEEDBACK_DISABLED = True
        logger.warning(
            "Optional LED feedback failed during %s: %s",
            _CURRENT_ACTION_NAME or "action",
            exc,
        )


def _optional_led_controller():
    global _LED_FEEDBACK_DISABLED
    try:
        return LEDController.get_instance()
    except Exception as exc:
        _LED_FEEDBACK_DISABLED = True
        logger.warning("Optional LED controller is unavailable: %s", exc)
        return None


def _landed_state_name(value) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if name:
        return str(name).upper()
    text = str(value).strip()
    return text.rsplit(".", 1)[-1].upper() if text else None


def _relative_altitude_value(sample) -> float | None:
    raw_value = (
        getattr(sample, "relative_altitude_m", None)
        if sample is not None and not isinstance(sample, (int, float))
        else sample
    )
    try:
        converted = float(raw_value)
    except (TypeError, ValueError):
        return None
    return converted if converted == converted and abs(converted) != float("inf") else None


def _takeoff_confirmation_altitude_m(target_altitude_m: float) -> float:
    """Return an attainable confirmation threshold for every positive target.

    The historical 1.5 m floor made a valid 1 m takeoff impossible to confirm.
    Keep the normal 80%/0.5 m margin posture while never requiring telemetry to
    exceed the requested target.
    """
    threshold = max(
        0.5,
        min(target_altitude_m - 0.5, target_altitude_m * 0.8),
    )
    return min(target_altitude_m, threshold)


async def _best_effort_state_observation(drone) -> VehicleStateObservation | None:
    try:
        return await observe_authoritative_vehicle_state(drone)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Final vehicle-state observation failed: %s", exc)
        return None


def _final_state_from_observation(
    observation: VehicleStateObservation | None,
    *,
    recovery_action: str | None,
    recovery_status: str,
    armed_override: bool | None = None,
    landed_state_override: str | None = None,
) -> dict:
    state = observation.as_dict() if observation is not None else {
        "source": "mavsdk.telemetry",
        "fresh": False,
        "complete": False,
        "armed": None,
        "landed_state": None,
        "relative_altitude_m": None,
        "field_errors": {"observation": "final vehicle-state observation unavailable"},
    }
    if armed_override is not None:
        state["armed"] = armed_override
    if landed_state_override is not None:
        state["landed_state"] = landed_state_override
    state["recovery_action"] = recovery_action
    state["recovery_status"] = recovery_status
    return state


async def _verified_disarm_cleanup(
    drone,
    *,
    initial_observation: VehicleStateObservation | None = None,
) -> tuple[bool, dict, dict]:
    """Best-effort normal disarm with authoritative confirmation and evidence."""
    evidence: dict = {"cleanup": "disarm", "disarm_command_attempted": False}
    observation = initial_observation or await _best_effort_state_observation(drone)
    if observation is not None:
        evidence["initial_state"] = observation.as_dict()
        if observation.armed is False:
            final_state = _final_state_from_observation(
                observation,
                recovery_action=None,
                recovery_status="safe_disarmed_confirmed",
            )
            return True, final_state, evidence
        if observation.armed is True and not observation.on_ground:
            evidence["disarm_blocked"] = "fresh telemetry did not confirm ON_GROUND"
            final_state = _final_state_from_observation(
                observation,
                recovery_action=None,
                recovery_status="disarm_blocked_airborne",
            )
            return False, final_state, evidence

    command_error = None
    try:
        evidence["disarm_command_attempted"] = True
        await drone.action.disarm()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        command_error = exc
        evidence["disarm_command_error"] = _exception_detail(exc)[0]

    disarm_confirmed = False
    try:
        await wait_until_armed_state(drone, False, timeout=10)
        disarm_confirmed = True
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        evidence["disarm_confirmation_error"] = _exception_detail(exc)[0]

    final_observation = await _best_effort_state_observation(drone)
    if final_observation is not None:
        evidence["final_state"] = final_observation.as_dict()
        if final_observation.armed is False:
            disarm_confirmed = True
        elif final_observation.armed is True:
            disarm_confirmed = False

    recovery_status = (
        "safe_disarmed_confirmed" if disarm_confirmed else "disarm_unconfirmed"
    )
    final_state = _final_state_from_observation(
        final_observation or observation,
        recovery_action="disarm" if evidence["disarm_command_attempted"] else None,
        recovery_status=recovery_status,
        armed_override=False if disarm_confirmed else None,
    )
    if command_error is not None and disarm_confirmed:
        evidence["note"] = "Disarm RPC failed, but fresh telemetry confirmed the vehicle disarmed."
    return disarm_confirmed, final_state, evidence


async def _recover_failed_takeoff(
    drone,
    *,
    takeoff_command_may_have_started: bool,
) -> tuple[bool, dict, dict]:
    """Reach verified disarm or confirm that primary LAND recovery has started."""
    initial = await _best_effort_state_observation(drone)
    evidence: dict = {
        "cleanup": "failed_takeoff",
        "takeoff_command_may_have_started": takeoff_command_may_have_started,
    }
    if initial is not None:
        evidence["initial_state"] = initial.as_dict()

    if initial is not None and initial.armed is False:
        final_state = _final_state_from_observation(
            initial,
            recovery_action=None,
            recovery_status="safe_disarmed_confirmed",
        )
        return True, final_state, evidence

    if initial is not None and initial.on_ground:
        confirmed, final_state, disarm_evidence = await _verified_disarm_cleanup(
            drone,
            initial_observation=initial,
        )
        evidence["disarm"] = disarm_evidence
        return confirmed, final_state, evidence

    should_land = bool(
        takeoff_command_may_have_started
        or (initial is not None and initial.landed_state in {"TAKING_OFF", "IN_AIR", "LANDING"})
    )
    if not should_land:
        confirmed, final_state, disarm_evidence = await _verified_disarm_cleanup(
            drone,
            initial_observation=initial,
        )
        evidence["disarm"] = disarm_evidence
        return confirmed, final_state, evidence

    evidence["land_command_attempted"] = True
    try:
        # LAND is the primary recovery action.  Never gate it on HOLD.
        await drone.action.land()
        transition = await wait_until_landed_state(
            drone,
            {telemetry.LandedState.LANDING, telemetry.LandedState.ON_GROUND},
            "failed-takeoff landing state transition",
            timeout=15,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        evidence["land_recovery_error"] = _exception_detail(exc)[0]
        final_observation = await _best_effort_state_observation(drone)
        final_state = _final_state_from_observation(
            final_observation or initial,
            recovery_action="land",
            recovery_status="land_recovery_unconfirmed",
        )
        return False, final_state, evidence

    transition_name = _landed_state_name(transition)
    final_observation = await _best_effort_state_observation(drone)
    if final_observation is not None:
        evidence["final_state"] = final_observation.as_dict()
        if final_observation.armed is False:
            final_state = _final_state_from_observation(
                final_observation,
                recovery_action="land",
                recovery_status="safe_disarmed_confirmed",
            )
            return True, final_state, evidence

    if transition_name == "ON_GROUND":
        confirmed, final_state, disarm_evidence = await _verified_disarm_cleanup(
            drone,
            initial_observation=final_observation,
        )
        evidence["post_land_disarm"] = disarm_evidence
        return confirmed, final_state, evidence

    recovery_confirmed = transition_name in {"LANDING", "ON_GROUND"}
    final_state = _final_state_from_observation(
        final_observation or initial,
        recovery_action="land",
        recovery_status=(
            "land_recovery_started" if recovery_confirmed else "land_recovery_unconfirmed"
        ),
        landed_state_override=transition_name,
    )
    return recovery_confirmed, final_state, evidence


async def _shielded_takeoff_cleanup(
    drone,
    *,
    takeoff_command_may_have_started: bool,
) -> tuple[bool, dict, dict]:
    return await _run_bounded_shielded_cleanup(
        _recover_failed_takeoff(
            drone,
            takeoff_command_may_have_started=takeoff_command_may_have_started,
        ),
        cleanup_name="failed_takeoff",
    )


async def _shielded_verified_disarm_cleanup(
    drone,
    *,
    initial_observation: VehicleStateObservation | None,
) -> tuple[bool, dict, dict]:
    return await _run_bounded_shielded_cleanup(
        _verified_disarm_cleanup(
            drone,
            initial_observation=initial_observation,
        ),
        cleanup_name="verified_disarm",
    )


async def _run_bounded_shielded_cleanup(
    cleanup_coro,
    *,
    cleanup_name: str,
) -> tuple[bool, dict, dict]:
    """Let one cooperative signal reach bounded cleanup exactly once.

    The cleanup task is shielded from the cancellation that initiated it.  A
    fixed wall-clock deadline prevents a stuck SDK call from keeping the action
    process alive forever; the process manager grants a slightly longer grace
    window before force-kill.
    """

    cleanup_task = asyncio.create_task(cleanup_coro)

    async def wait_for_cleanup():
        return await asyncio.wait_for(
            asyncio.shield(cleanup_task),
            timeout=ACTION_SAFETY_CLEANUP_TIMEOUT_SEC,
        )

    wait_task = asyncio.create_task(wait_for_cleanup())
    try:
        return await asyncio.shield(wait_task)
    except asyncio.CancelledError:
        # Consume the initiating cancellation, but keep the safety task alive.
        try:
            return await wait_task
        except asyncio.TimeoutError:
            pass
    except asyncio.TimeoutError:
        pass

    cleanup_task.cancel()
    cleanup_task.add_done_callback(
        lambda task: task.exception() if not task.cancelled() else None
    )
    logger.critical(
        "%s safety cleanup exceeded the fixed %.1fs deadline.",
        cleanup_name,
        ACTION_SAFETY_CLEANUP_TIMEOUT_SEC,
    )
    final_state = {
        "source": "mavsdk.telemetry",
        "fresh": False,
        "complete": False,
        "connection_live": None,
        "armed": None,
        "landed_state": None,
        "relative_altitude_m": None,
        "field_errors": {"cleanup": "bounded safety cleanup timed out"},
        "recovery_action": cleanup_name,
        "recovery_status": "cleanup_unconfirmed_timeout",
    }
    evidence = {
        "cleanup": cleanup_name,
        "cleanup_confirmed": False,
        "cleanup_timeout_sec": ACTION_SAFETY_CLEANUP_TIMEOUT_SEC,
    }
    return False, final_state, evidence


async def wait_until_armed_state(drone, expected: bool, timeout=15):
    state_label = "armed" if expected else "disarmed"
    return await wait_for_telemetry_condition(
        drone.telemetry.armed,
        lambda armed: armed is expected,
        f"vehicle to become {state_label}",
        timeout=timeout,
    )


async def wait_until_landed_state(drone, expected_states, description, timeout=20):
    expected_states = set(expected_states)
    return await wait_for_telemetry_condition(
        drone.telemetry.landed_state,
        lambda state: state in expected_states,
        description,
        timeout=timeout,
    )


async def wait_until_flight_mode(drone, expected_mode, timeout=15):
    return await wait_for_telemetry_condition(
        drone.telemetry.flight_mode,
        lambda mode: mode == expected_mode,
        f"flight mode {expected_mode.name}",
        timeout=timeout,
    )


async def wait_until_relative_altitude(drone, minimum_relative_altitude_m: float, timeout=30):
    try:
        return await wait_for_telemetry_condition(
            drone.telemetry.position,
            lambda position: position.relative_altitude_m >= minimum_relative_altitude_m,
            f"relative altitude >= {minimum_relative_altitude_m:.1f}m",
            timeout=timeout,
        )
    except TimeoutError:
        local_relative_altitude = await asyncio.to_thread(
            _get_local_relative_altitude_snapshot,
            timeout=1.0,
        )
        if (
            local_relative_altitude is not None
            and local_relative_altitude >= minimum_relative_altitude_m
        ):
            logger.warning(
                "Relative altitude confirmed via local drone API fallback: %.2fm >= %.2fm",
                local_relative_altitude,
                minimum_relative_altitude_m,
            )
            return local_relative_altitude
        raise

async def safe_action(func, *args, **kwargs):
    """
    Wraps an action function with exception handling.
    Logs start/end, returns True if success, False if failure.
    """
    action_name = func.__name__
    logger.info(f"Starting action: {action_name}")
    try:
        await func(*args, **kwargs)
        logger.info(f"Action {action_name} completed successfully.")
        return True
    except ActionError as ae:
        logger.error(f"Action {action_name} failed with ActionError: {ae}")
        _record_action_exception(action_name, ae)
        return False
    except Exception as exc:
        if isinstance(getattr(exc, "code", None), str):
            logger.warning(
                "Action %s was blocked (%s): %s",
                action_name,
                exc.code,
                exc,
            )
        else:
            logger.exception(f"Action {action_name} failed with an unexpected error.")
        _record_action_exception(action_name, exc)
        return False


async def _run_takeoff(context: ActionExecutionContext, invocation: ActionInvocation) -> bool:
    return await safe_action(takeoff, context.drone, invocation.altitude)


async def _run_land(context: ActionExecutionContext, invocation: ActionInvocation) -> bool:
    return await safe_action(land, context.drone)


async def _run_return_rtl(context: ActionExecutionContext, invocation: ActionInvocation) -> bool:
    return await safe_action(return_rtl, context.drone)


async def _run_hold(context: ActionExecutionContext, invocation: ActionInvocation) -> bool:
    return await safe_action(hold, context.drone)


async def _run_kill_terminate(context: ActionExecutionContext, invocation: ActionInvocation) -> bool:
    return await safe_action(kill_terminate, context.drone)


async def _run_test(context: ActionExecutionContext, invocation: ActionInvocation) -> bool:
    return await safe_action(
        test,
        context.drone,
        request_payload=invocation.request_payload,
    )


async def _run_reboot_fc(context: ActionExecutionContext, invocation: ActionInvocation) -> bool:
    return await safe_action(reboot, context.drone, fc_flag=True, sys_flag=False)


async def _run_reboot_sys(context: ActionExecutionContext, invocation: ActionInvocation) -> bool:
    return await safe_action(reboot, context.drone, fc_flag=False, sys_flag=True)


async def _run_update_code(context: ActionExecutionContext, invocation: ActionInvocation) -> bool:
    return await safe_action(update_code, invocation.branch)


async def _run_precision_move(context: ActionExecutionContext, invocation: ActionInvocation) -> bool:
    return await safe_action(precision_move, context, invocation)


def get_action_spec(action_name: str | None) -> ActionSpec | None:
    normalized = _normalize_action_name(action_name)
    if normalized is None:
        return None

    action_specs = {
        "takeoff": ActionSpec(
            name="takeoff",
            runner=_run_takeoff,
            requires_connection=True,
            description="Arm and take off to the requested altitude.",
        ),
        "land": ActionSpec(
            name="land",
            runner=_run_land,
            requires_connection=True,
            description="Land safely and wait for disarm confirmation.",
        ),
        "return_rtl": ActionSpec(
            name="return_rtl",
            runner=_run_return_rtl,
            requires_connection=True,
            description="Return to launch and wait for landing/disarm completion.",
        ),
        "hold": ActionSpec(
            name="hold",
            runner=_run_hold,
            requires_connection=True,
            description="Enter PX4 Hold mode.",
        ),
        "kill_terminate": ActionSpec(
            name="kill_terminate",
            runner=_run_kill_terminate,
            requires_connection=True,
            description="Emergency kill/terminate.",
        ),
        "test": ActionSpec(
            name="test",
            runner=_run_test,
            requires_connection=True,
            description="Arm motors briefly, then disarm under the required ground-test safety acknowledgement.",
        ),
        "reboot_fc": ActionSpec(
            name="reboot_fc",
            runner=_run_reboot_fc,
            requires_connection=True,
            description="Reboot PX4/flight controller services.",
        ),
        "reboot_sys": ActionSpec(
            name="reboot_sys",
            runner=_run_reboot_sys,
            requires_connection=True,
            description="Reboot the companion computer/system.",
        ),
        "update_code": ActionSpec(
            name="update_code",
            runner=_run_update_code,
            requires_connection=False,
            description="Sync the repo via the configured update workflow.",
        ),
        "precision_move": ActionSpec(
            name="precision_move",
            runner=_run_precision_move,
            requires_connection=True,
            description="Move relative to the current local state and finish in PX4 Hold.",
        ),
    }
    return action_specs.get(normalized)

# -----------------------
# Action Implementations
# -----------------------

async def ensure_ready_for_flight(drone, timeout: float | None = None):
    """
    Before takeoff, ensure the drone is healthy, global position is good,
    and home position is set.
    """
    preflight_timeout = float(timeout or getattr(Params, "TAKEOFF_PREFLIGHT_TIMEOUT_SEC", 30))
    logger.info("Checking preflight conditions...")
    start = time.monotonic()
    deadline = monotonic_deadline(preflight_timeout)
    gps_ok = False
    home_ok = False
    last_reported_state = None
    try:
        async with managed_async_stream(drone.telemetry.health) as stream:
            while True:
                health = await next_stream_sample(
                    stream,
                    deadline=deadline,
                    description="takeoff preflight health",
                )
                if health.is_global_position_ok:
                    gps_ok = True
                if health.is_home_position_ok:
                    home_ok = True

                local_state = await asyncio.to_thread(
                    _get_local_drone_state_snapshot,
                    timeout=min(1.0, max(0.1, deadline - time.monotonic())),
                )
                local_home_ok = bool(local_state and local_state.get("home_position_set"))
                if local_home_ok:
                    home_ok = True

                home_source = (
                    "mavsdk"
                    if health.is_home_position_ok
                    else ("drone_api" if local_home_ok else "pending")
                )
                current_state = (gps_ok, home_ok, home_source)
                if current_state != last_reported_state:
                    logger.info(
                        "Preflight health update: gps_ok=%s, home_ok=%s, home_source=%s, elapsed=%.1fs/%.1fs",
                        gps_ok,
                        home_ok,
                        home_source,
                        time.monotonic() - start,
                        preflight_timeout,
                    )
                    last_reported_state = current_state
                if gps_ok and home_ok:
                    logger.info("Preflight checks passed: GPS and Home position are good.")
                    return True
    except TimeoutError:
        logger.error(
            "Preflight checks timed out. GPS or Home not ready (gps_ok=%s, home_ok=%s, timeout=%.1fs).",
            gps_ok,
            home_ok,
            preflight_timeout,
        )
        return False

async def takeoff(drone, altitude):
    """
    Arms and takes off to the specified altitude (in meters).
    """
    led_controller = _optional_led_controller()
    try:
        target_altitude = float(altitude)
    except (TypeError, ValueError) as exc:
        raise ActionSafetyError(
            code="TAKEOFF_ALTITUDE_INVALID",
            phase="validation",
            message="Takeoff altitude must be a positive finite number; no vehicle command was sent.",
            evidence={"requested_altitude": altitude},
        ) from exc
    if (
        target_altitude <= 0.0
        or target_altitude != target_altitude
        or abs(target_altitude) == float("inf")
    ):
        raise ActionSafetyError(
            code="TAKEOFF_ALTITUDE_INVALID",
            phase="validation",
            message="Takeoff altitude must be a positive finite number; no vehicle command was sent.",
            evidence={"requested_altitude": altitude},
        )

    arm_phase_started = False
    takeoff_command_may_have_started = False
    try:
        if not await ensure_ready_for_flight(drone):
            raise ActionSafetyError(
                code="TAKEOFF_PREFLIGHT_NOT_READY",
                phase="preflight",
                message="Takeoff was blocked because fresh GPS/home readiness was not confirmed.",
                retryable=True,
            )

        _safe_led_call(led_controller, "set_color", 255, 255, 0)
        await asyncio.sleep(0.5)
        await drone.action.set_takeoff_altitude(target_altitude)

        try:
            start_state = await observe_authoritative_vehicle_state(drone)
        except Exception as exc:
            raise ActionSafetyError(
                code="TAKEOFF_START_STATE_UNAVAILABLE",
                phase="precondition",
                message=(
                    "Takeoff was blocked because fresh armed, landed, and relative-altitude "
                    "state could not be sampled immediately before arming."
                ),
                retryable=True,
                evidence={"observation_error": _exception_detail(exc)[0]},
            ) from exc
        if not start_state.complete:
            raise ActionSafetyError(
                code="TAKEOFF_START_STATE_UNAVAILABLE",
                phase="precondition",
                message=(
                    "Takeoff was blocked because fresh armed, landed, and relative-altitude "
                    "state was incomplete immediately before arming."
                ),
                retryable=True,
                evidence={"observation": start_state.as_dict()},
                final_vehicle_state=start_state.as_dict(),
            )
        if not start_state.safe_ground_disarmed:
            raise ActionSafetyError(
                code="TAKEOFF_REQUIRES_SAFE_GROUND_STATE",
                phase="precondition",
                message=(
                    "Takeoff requires a freshly confirmed on-ground, disarmed vehicle near "
                    f"zero relative altitude (within {GROUND_MAX_RELATIVE_ALTITUDE_M:.1f} m)."
                ),
                evidence={"observation": start_state.as_dict()},
                final_vehicle_state=start_state.as_dict(),
            )

        # Keep standalone takeoff on the same bounded armability posture as
        # synchronized launchers without changing its separate GPS/home preflight.
        arm_phase_started = True
        await arm_with_preflight_gate(
            drone,
            require_global_position=False,
            logger=logger,
        )
        await wait_until_armed_state(drone, True, timeout=10)
        _safe_led_call(led_controller, "set_color", 255, 255, 255)
        await asyncio.sleep(0.5)
        takeoff_command_may_have_started = True
        await drone.action.takeoff()
        landed_transition = await wait_until_landed_state(
            drone,
            {telemetry.LandedState.TAKING_OFF, telemetry.LandedState.IN_AIR},
            "takeoff state transition",
            timeout=15,
        )
        minimum_altitude = _takeoff_confirmation_altitude_m(target_altitude)
        altitude_sample = await wait_until_relative_altitude(
            drone,
            minimum_altitude,
            timeout=Params.TAKEOFF_ALTITUDE_CONFIRM_TIMEOUT_SEC,
        )
        confirmed_altitude = _relative_altitude_value(altitude_sample)
        if confirmed_altitude is None or confirmed_altitude < minimum_altitude:
            raise ActionSafetyError(
                code="TAKEOFF_ALTITUDE_UNCONFIRMED",
                phase="state_verification",
                message=(
                    "Takeoff started, but the required relative-altitude threshold was not "
                    "confirmed from telemetry. LAND recovery was initiated."
                ),
                retryable=False,
                evidence={
                    "target_altitude_m": target_altitude,
                    "minimum_confirmed_altitude_m": minimum_altitude,
                    "observed_relative_altitude_m": confirmed_altitude,
                },
            )
        completion_state = await observe_authoritative_vehicle_state(drone)
        if (
            not completion_state.complete
            or not completion_state.airborne
            or completion_state.relative_altitude_m is None
            or completion_state.relative_altitude_m < minimum_altitude
        ):
            raise ActionSafetyError(
                code="TAKEOFF_FINAL_STATE_UNAVAILABLE",
                phase="state_verification",
                message=(
                    "Takeoff reached the altitude threshold, but a connected, fresh and "
                    "internally consistent final airborne snapshot was not confirmed. "
                    "LAND recovery was initiated."
                ),
                evidence={"observation": completion_state.as_dict()},
                final_vehicle_state=completion_state.as_dict(),
            )
        final_vehicle_state = completion_state.as_dict()
        final_vehicle_state.update(
            {
                "target_altitude_m": target_altitude,
                "minimum_confirmed_altitude_m": minimum_altitude,
                "recovery_action": None,
                "recovery_status": "not_required",
            }
        )
        _set_final_vehicle_state(final_vehicle_state)
    except BaseException as primary_error:
        _safe_led_call(led_controller, "turn_off")
        if not arm_phase_started:
            raise

        cleanup_confirmed, final_vehicle_state, cleanup_evidence = (
            await _shielded_takeoff_cleanup(
                drone,
                takeoff_command_may_have_started=takeoff_command_may_have_started,
            )
        )
        cleanup_evidence["cleanup_confirmed"] = cleanup_confirmed
        _set_action_cleanup_evidence(cleanup_evidence)
        _set_final_vehicle_state(final_vehicle_state)
        if isinstance(primary_error, asyncio.CancelledError):
            raise
        if not isinstance(primary_error, Exception):
            raise
        raise _ActionTransactionError(
            primary_error,
            evidence=cleanup_evidence,
            final_vehicle_state=final_vehicle_state,
        ) from primary_error

    # Indicate success with green blinks
    for _ in range(3):
        _safe_led_call(led_controller, "set_color", 0, 255, 0)
        await asyncio.sleep(0.2)
        _safe_led_call(led_controller, "turn_off")
        await asyncio.sleep(0.2)
    _safe_led_call(led_controller, "turn_off")
    logger.info("Takeoff successful.")

async def land(drone):
    """
    Commands the drone to land safely.
    """
    led_controller = None
    try:
        # LAND is itself the recovery command.  A preliminary HOLD can be
        # rejected while LAND remains available, so it must never gate or
        # delay the primary recovery action.
        await drone.action.land()
        led_controller = _optional_led_controller()
        _safe_led_call(led_controller, "set_color", 255, 255, 0)
        await wait_until_landed_state(
            drone,
            {telemetry.LandedState.LANDING, telemetry.LandedState.ON_GROUND},
            "landing state transition",
            timeout=15,
        )

        # A steady best-effort indicator must not add sleeps to the recovery
        # state machine or delay disarm confirmation.
        _safe_led_call(led_controller, "set_color", 0, 0, 255)

        relative_altitude = await _get_current_relative_altitude(drone)
        disarm_timeout = calculate_land_disarm_timeout(relative_altitude)
        altitude_message = (
            f"{relative_altitude:.1f}m"
            if isinstance(relative_altitude, (int, float))
            else "unknown"
        )
        logger.info(
            "Waiting up to %.0fs for landing disarm confirmation (relative altitude: %s).",
            disarm_timeout,
            altitude_message,
        )

        try:
            await wait_until_armed_state(drone, False, timeout=disarm_timeout)
        except TimeoutError:
            landed_state = await _get_current_landed_state(drone)
            if landed_state == telemetry.LandedState.ON_GROUND:
                touchdown_grace = int(getattr(Params, "LAND_ACTION_TOUCHDOWN_DISARM_GRACE_SEC", 20))
                logger.warning(
                    "Drone is on ground but still armed after %.0fs; issuing explicit disarm and waiting %.0fs more.",
                    disarm_timeout,
                    touchdown_grace,
                )
                await drone.action.disarm()
                await wait_until_armed_state(drone, False, timeout=touchdown_grace)
            else:
                raise

        logger.info("Landing successful.")
    except ActionError as e:
        logger.error(f"Landing failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during landing")
        raise
    finally:
        _safe_led_call(led_controller, "turn_off")

async def return_rtl(drone):
    """
    Commands the drone to return to launch (home) position.
    """
    led_controller = None
    try:
        # RTL is the primary recovery action and must be attempted directly.
        # Requiring HOLD first suppresses RTL on vehicles that reject HOLD but
        # can still accept return-to-launch.
        await drone.action.return_to_launch()
        led_controller = _optional_led_controller()
        _safe_led_call(led_controller, "set_color", 255, 0, 255)
        await wait_until_flight_mode(drone, telemetry.FlightMode.RETURN_TO_LAUNCH, timeout=15)

        _safe_led_call(led_controller, "set_color", 0, 0, 255)

        relative_altitude = await _get_current_relative_altitude(drone)
        completion_timeout = calculate_rtl_completion_timeout(relative_altitude)
        altitude_message = (
            f"{relative_altitude:.1f}m"
            if isinstance(relative_altitude, (int, float))
            else "unknown"
        )
        logger.info(
            "Waiting up to %.0fs for RTL landing/disarm completion (relative altitude: %s).",
            completion_timeout,
            altitude_message,
        )

        try:
            await wait_until_armed_state(drone, False, timeout=completion_timeout)
        except TimeoutError:
            landed_state = await _get_current_landed_state(drone)
            if landed_state == telemetry.LandedState.ON_GROUND:
                touchdown_grace = int(getattr(Params, "LAND_ACTION_TOUCHDOWN_DISARM_GRACE_SEC", 20))
                logger.warning(
                    "Drone reached the ground during RTL but stayed armed after %.0fs; issuing explicit disarm and waiting %.0fs more.",
                    completion_timeout,
                    touchdown_grace,
                )
                await drone.action.disarm()
                await wait_until_armed_state(drone, False, timeout=touchdown_grace)
            else:
                raise

        logger.info("RTL successful.")
    except ActionError as e:
        logger.error(f"RTL failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during RTL")
        raise
    finally:
        _safe_led_call(led_controller, "turn_off")

async def kill_terminate(drone):
    """
    Immediately terminates the drone (emergency kill).
    """
    led_controller = None
    try:
        # Termination is the emergency effect. Optional companion cosmetics
        # must never run, fail, or sleep ahead of this RPC.
        await drone.action.terminate()
        led_controller = _optional_led_controller()
        _safe_led_call(led_controller, "set_color", 255, 0, 0)
        await wait_until_armed_state(drone, False, timeout=10)
        logger.info("Kill and Terminate successful.")
    except ActionError as e:
        logger.error(f"Kill terminate failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during kill terminate")
        raise

async def hold(drone):
    """
    Commands an authoritatively-confirmed airborne drone to hold position.
    """
    led_controller = None
    try:
        try:
            admission_state = await observe_authoritative_vehicle_state(drone)
        except Exception as exc:
            raise ActionSafetyError(
                code="HOLD_STATE_UNAVAILABLE",
                phase="precondition",
                message=(
                    "Hold was blocked because fresh armed, landed, and relative-altitude "
                    "telemetry could not be sampled immediately before the mode change."
                ),
                retryable=True,
                evidence={"observation_error": _exception_detail(exc)[0]},
            ) from exc
        if not admission_state.complete:
            raise ActionSafetyError(
                code="HOLD_STATE_UNAVAILABLE",
                phase="precondition",
                message=(
                    "Hold was blocked because fresh armed, landed, and relative-altitude "
                    "telemetry was incomplete immediately before the mode change."
                ),
                retryable=True,
                evidence={"observation": admission_state.as_dict()},
                final_vehicle_state=admission_state.as_dict(),
            )
        if not admission_state.airborne:
            raise ActionSafetyError(
                code="HOLD_REQUIRES_AIRBORNE_STATE",
                phase="precondition",
                message=(
                    "Hold Position requires a freshly confirmed armed, IN_AIR vehicle at "
                    f"or above {AIRBORNE_MIN_RELATIVE_ALTITUDE_M:.1f} m relative altitude. "
                    "It never arms or launches a grounded drone."
                ),
                evidence={"observation": admission_state.as_dict()},
                final_vehicle_state=admission_state.as_dict(),
            )

        await drone.action.hold()
        led_controller = _optional_led_controller()
        _safe_led_call(led_controller, "set_color", 0, 0, 255)
        await wait_until_flight_mode(drone, telemetry.FlightMode.HOLD, timeout=10)
        final_observation = await _best_effort_state_observation(drone)
        final_state = _final_state_from_observation(
            final_observation or admission_state,
            recovery_action=None,
            recovery_status="not_required",
        )
        final_state["flight_mode"] = "HOLD"
        _set_final_vehicle_state(final_state)
        _safe_led_call(led_controller, "set_color", 0, 0, 255)
        await asyncio.sleep(1)
        _safe_led_call(led_controller, "turn_off")
        logger.info("Hold successful.")
    except ActionError as e:
        logger.error(f"Hold failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during hold")
        raise
    finally:
        _safe_led_call(led_controller, "turn_off")

async def test(drone, *, request_payload=None):
    """
    Ground arm/disarm test with state confirmation.

    A successful result proves command transport and observed arm/disarm state
    transitions only.  It is not evidence that takeoff preflight requirements
    are currently satisfied.
    """
    try:
        safety_acknowledgement = GroundTestSafetyAcknowledgement.from_action_payload(
            request_payload
        )
        safety_acknowledgement.validate_for_runtime(
            sim_mode=bool(getattr(Params, "sim_mode", False))
        )
    except Exception as exc:
        acknowledgement = (
            request_payload.get("ground_test_safety")
            if isinstance(request_payload, dict)
            else None
        )
        acknowledgement_mode = (
            acknowledgement.get("mode")
            if isinstance(acknowledgement, dict)
            else None
        )
        raise ActionSafetyError(
            code="GROUND_TEST_SAFETY_ACK_REQUIRED",
            phase="precondition",
            message=(
                f"Arm/Disarm Ground Test safety acknowledgement was rejected: {exc}. "
                "No arm command was sent."
            ),
            evidence={
                "runtime_mode": "sitl" if bool(getattr(Params, "sim_mode", False)) else "real",
                "acknowledgement_mode": acknowledgement_mode,
            },
        ) from exc

    led_controller = _optional_led_controller()
    arm_command_may_have_started = False
    disarm_confirmed = False
    primary_error: BaseException | None = None
    cleanup_confirmed = True
    cleanup_evidence: dict = {"cleanup": "not_required"}
    final_vehicle_state: dict | None = None

    try:
        try:
            start_state = await observe_authoritative_vehicle_state(drone)
        except Exception as exc:
            raise ActionSafetyError(
                code="GROUND_TEST_STATE_UNAVAILABLE",
                phase="precondition",
                message=(
                    "Arm/Disarm Ground Test was blocked because fresh armed, landed, and "
                    "relative-altitude telemetry could not be sampled."
                ),
                retryable=True,
                evidence={"observation_error": _exception_detail(exc)[0]},
            ) from exc
        if not start_state.complete:
            raise ActionSafetyError(
                code="GROUND_TEST_STATE_UNAVAILABLE",
                phase="precondition",
                message=(
                    "Arm/Disarm Ground Test was blocked because fresh armed, landed, and "
                    "relative-altitude telemetry was incomplete."
                ),
                retryable=True,
                evidence={"observation": start_state.as_dict()},
                final_vehicle_state=start_state.as_dict(),
            )
        if not start_state.safe_ground_disarmed:
            raise ActionSafetyError(
                code="GROUND_TEST_REQUIRES_SAFE_GROUND_STATE",
                phase="precondition",
                message=(
                    "Arm/Disarm Ground Test requires a freshly confirmed on-ground, "
                    f"disarmed vehicle within {GROUND_MAX_RELATIVE_ALTITUDE_M:.1f} m of "
                    "zero relative altitude. It is not allowed on an airborne vehicle."
                ),
                evidence={"observation": start_state.as_dict()},
                final_vehicle_state=start_state.as_dict(),
            )

        _safe_led_call(led_controller, "set_color", 255, 0, 0)
        arm_command_may_have_started = True
        await drone.action.arm()
        await wait_until_armed_state(drone, True, timeout=10)
        _safe_led_call(led_controller, "set_color", 255, 255, 255)
        await asyncio.sleep(1)
        _safe_led_call(led_controller, "set_color", 0, 0, 255)
        await asyncio.sleep(1)
        _safe_led_call(led_controller, "set_color", 0, 255, 0)
        await asyncio.sleep(1)
        await drone.action.disarm()
        await wait_until_armed_state(drone, False, timeout=10)
        disarm_confirmed = True
    except BaseException as exc:
        primary_error = exc
    finally:
        if arm_command_may_have_started:
            final_observation = await _best_effort_state_observation(drone)
            if final_observation is not None and final_observation.armed is False:
                disarm_confirmed = True
            elif final_observation is not None and final_observation.armed is True:
                disarm_confirmed = False

            if not disarm_confirmed:
                if final_observation is not None and not final_observation.on_ground:
                    cleanup_confirmed, final_vehicle_state, cleanup_evidence = (
                        await _shielded_takeoff_cleanup(
                            drone,
                            takeoff_command_may_have_started=False,
                        )
                    )
                else:
                    cleanup_confirmed, final_vehicle_state, cleanup_evidence = (
                        await _shielded_verified_disarm_cleanup(
                            drone,
                            initial_observation=final_observation,
                        )
                    )
            else:
                final_vehicle_state = _final_state_from_observation(
                    final_observation,
                    recovery_action="disarm",
                    recovery_status="safe_disarmed_confirmed",
                    armed_override=(
                        False
                        if final_observation is None or final_observation.armed is None
                        else None
                    ),
                )
                cleanup_evidence = {
                    "cleanup": "disarm",
                    "cleanup_confirmed": True,
                    "disarm_confirmation": "mavsdk.telemetry.armed",
                }
            _set_action_cleanup_evidence(cleanup_evidence)
        _safe_led_call(led_controller, "turn_off")

    if final_vehicle_state is not None:
        _set_final_vehicle_state(final_vehicle_state)

    if primary_error is not None:
        if not arm_command_may_have_started:
            raise primary_error
        cleanup_evidence["cleanup_confirmed"] = cleanup_confirmed
        _set_action_cleanup_evidence(cleanup_evidence)
        if isinstance(primary_error, asyncio.CancelledError):
            raise primary_error
        if not isinstance(primary_error, Exception):
            raise primary_error
        raise _ActionTransactionError(
            primary_error,
            evidence=cleanup_evidence,
            final_vehicle_state=final_vehicle_state,
        ) from primary_error

    if not cleanup_confirmed:
        raise ActionSafetyError(
            code="GROUND_TEST_DISARM_UNCONFIRMED",
            phase="safety_cleanup",
            message=(
                "Arm/Disarm Ground Test ended, but a safe disarmed state could not be "
                "confirmed. Keep clear of the vehicle and use the primary recovery controls."
            ),
            evidence=cleanup_evidence,
            final_vehicle_state=final_vehicle_state,
        )

    logger.info("Arm/Disarm Ground Test successful; final disarmed state confirmed.")

async def reboot(drone, fc_flag, sys_flag, force_reboot=True):
    """
    Reboots flight controller or entire system (Linux-based), or both.
    """
    led_controller = _optional_led_controller()
    _safe_led_call(led_controller, "set_color", 255, 255, 0)
    await asyncio.sleep(0.5)

    try:
        if fc_flag:
            await drone.action.reboot()
            for _ in range(3):
                _safe_led_call(led_controller, "set_color", 0, 255, 0)
                await asyncio.sleep(0.2)
                _safe_led_call(led_controller, "turn_off")
                await asyncio.sleep(0.2)
            logger.info("FC reboot successful.")

        if sys_flag:
            logger.info("Initiating system reboot...")
            _safe_led_call(led_controller, "turn_off")
            await reboot_system()

        _safe_led_call(led_controller, "turn_off")
    except ActionError as e:
        logger.error(f"Reboot failed: {e}")
        raise
    except Exception:
        logger.exception("Unexpected error during reboot")
        raise
    finally:
        _safe_led_call(led_controller, "turn_off")

async def reboot_system():
    """
    Reboots the entire system via D-Bus (for Linux-based OS).
    """
    process = await asyncio.create_subprocess_exec(
        'dbus-send', '--system', '--print-reply', '--dest=org.freedesktop.login1',
        '/org/freedesktop/login1', 'org.freedesktop.login1.Manager.Reboot', 'boolean:true',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        logger.error(f"System reboot via D-Bus failed: {stderr.decode().strip()}")
    else:
        logger.info("System reboot command executed successfully.")

async def update_code(branch=None):
    """
    Pulls latest code from a git repository (via tools/update_repo_ssh.sh).
    Optionally checks out a specific branch.
    """
    global RETURN_CODE
    led_controller = _optional_led_controller()
    _safe_led_call(led_controller, "set_color", 255, 255, 0)
    await asyncio.sleep(0.5)

    try:
        script_path = os.path.join('tools', 'update_repo_ssh.sh')
        command = [script_path]
        if branch:
            command.extend(['--branch', branch])
        logger.info(f"Executing update script: {' '.join(command)}")

        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            stderr_text = stderr.decode().strip()
            stdout_text = stdout.decode().strip()
            logger.error(f"Update script failed (exit={process.returncode}): {stderr_text}")
            # Parse structured failure result if available
            for line in stdout_text.splitlines():
                if line.startswith("GIT_SYNC_RESULT="):
                    try:
                        import json
                        result = json.loads(line[len("GIT_SYNC_RESULT="):])
                        logger.error(f"Sync failure detail: error={result.get('error')}, "
                                     f"message={result.get('message')}")
                    except Exception:
                        pass
                    break
            fail()
            for _ in range(3):
                _safe_led_call(led_controller, "set_color", 255, 0, 0)
                await asyncio.sleep(0.2)
                _safe_led_call(led_controller, "turn_off")
                await asyncio.sleep(0.2)
            raise ActionError(f"Update script failed with exit code {process.returncode}")
        else:
            stdout_text = stdout.decode().strip()
            logger.info(f"Update script successful: {stdout_text}")
            # Parse structured result if available
            for line in stdout_text.splitlines():
                if line.startswith("GIT_SYNC_RESULT="):
                    try:
                        import json
                        result = json.loads(line[len("GIT_SYNC_RESULT="):])
                        logger.info(f"Sync result: branch={result.get('branch')}, "
                                    f"commit={result.get('commit')}, "
                                    f"duration={result.get('duration')}s")
                    except (json.JSONDecodeError, Exception) as parse_err:
                        logger.warning(f"Could not parse GIT_SYNC_RESULT: {parse_err}")
                    break
            for _ in range(3):
                _safe_led_call(led_controller, "set_color", 0, 255, 0)
                await asyncio.sleep(0.2)
    except Exception:
        logger.exception("Update code action failed")
        fail()
        for _ in range(3):
            _safe_led_call(led_controller, "set_color", 255, 0, 0)
            await asyncio.sleep(0.2)
            _safe_led_call(led_controller, "turn_off")
            await asyncio.sleep(0.2)
    finally:
        _safe_led_call(led_controller, "turn_off")


async def run_action_process(
    *,
    action: str | None,
    altitude: float | None,
    branch: str | None,
    request_payload: dict | None,
) -> None:
    """Run one action with cooperative SIGTERM/SIGINT cancellation.

    Only the first signal cancels the action task.  Subsequent signals are
    deliberately ignored inside this process so TAKE_OFF/TEST cleanup cannot
    be cancelled repeatedly; the owning process manager retains the bounded
    force-kill deadline.
    """

    global _REQUESTED_PROCESS_SIGNAL, RETURN_CODE
    _REQUESTED_PROCESS_SIGNAL = None
    loop = asyncio.get_running_loop()
    action_task = asyncio.current_task()
    installed_signals: list[signal.Signals] = []

    def request_shutdown(received_signal: signal.Signals) -> None:
        global _REQUESTED_PROCESS_SIGNAL, RETURN_CODE
        if _REQUESTED_PROCESS_SIGNAL is not None:
            logger.warning(
                "Ignoring repeated %s while bounded action cleanup is in progress.",
                received_signal.name,
            )
            return
        _REQUESTED_PROCESS_SIGNAL = received_signal.name
        RETURN_CODE = 1
        logger.warning(
            "Received %s; cancelling the action cooperatively so bounded safety cleanup can run.",
            received_signal.name,
        )
        if action_task is not None:
            action_task.cancel()

    for handled_signal in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                handled_signal,
                request_shutdown,
                handled_signal,
            )
            installed_signals.append(handled_signal)
        except (NotImplementedError, RuntimeError, ValueError):
            # Non-POSIX/test loops may not expose signal handlers. The process
            # manager uses this path only on Linux, where installation succeeds.
            logger.debug("Event loop signal handlers are unavailable for %s.", handled_signal.name)

    try:
        await perform_action(
            action=action,
            altitude=altitude,
            branch=branch,
            request_payload=request_payload,
        )
    except asyncio.CancelledError:
        signal_name = _REQUESTED_PROCESS_SIGNAL or "task cancellation"
        cleanup = dict(_LAST_ACTION_CLEANUP_EVIDENCE or {})
        cleanup_confirmed = cleanup.get("cleanup_confirmed")
        if cleanup_confirmed is True:
            cleanup_message = "Bounded safety cleanup completed and was confirmed."
        elif cleanup_confirmed is False:
            cleanup_message = (
                "Safety cleanup could not be confirmed; keep clear of the vehicle and use "
                "the primary recovery controls."
            )
        else:
            cleanup_message = "No post-arm cleanup was required before the action stopped."
        fail(
            code="ACTION_INTERRUPTED",
            phase="safety_cleanup",
            operator_message=(
                f"Action '{_normalize_action_name(action) or 'unknown'}' was interrupted by "
                f"{signal_name}. {cleanup_message}"
            ),
            retryable=False,
            evidence={
                "action": _normalize_action_name(action) or "unknown",
                "signal": signal_name,
                "cleanup": cleanup,
            },
            final_vehicle_state=_LAST_FINAL_VEHICLE_STATE,
        )
    finally:
        for handled_signal in installed_signals:
            loop.remove_signal_handler(handled_signal)

# -----------------------
# Main Entry Point
# -----------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Perform actions with drones.")
    parser.add_argument('--action',
                        help='Actions: takeoff, land, hold, test, reboot_fc, reboot_sys, update_code, '
                             'return_rtl, kill_terminate, precision_move')
    parser.add_argument('--altitude', type=float, default=10.0, help='Altitude (meters) for takeoff')
    parser.add_argument('--branch', type=str, help='Branch name for code update')
    parser.add_argument('--request-json', dest='request_json', type=str,
                        help='Optional structured JSON request payload for typed action runners')
    parser.add_argument('--request-file', dest='request_file', type=str,
                        help='Optional path to a JSON file containing a structured action request payload')

    args = parser.parse_args()

    request_payload_valid = True
    try:
        request_payload = load_request_payload(args.request_json, args.request_file)
    except Exception as exc:
        logger.error(f"Invalid structured action request payload: {exc}")
        fail(
            code="INVALID_ACTION_REQUEST",
            phase="validation",
            operator_message=f"The structured action request is invalid: {exc}. No vehicle command was sent.",
            retryable=False,
            evidence={"action": _normalize_action_name(args.action) or "missing"},
        )
        request_payload = None
        request_payload_valid = False

    try:
        if request_payload_valid:
            asyncio.run(
                run_action_process(
                    action=args.action,
                    altitude=args.altitude,
                    branch=args.branch,
                    request_payload=request_payload,
                )
            )
    except Exception as exc:
        logger.exception("An unexpected error occurred in the main block.")
        fail(
            code="ACTION_PROCESS_FAILED",
            phase="process",
            operator_message=f"The action process stopped unexpectedly: {exc}.",
            retryable=False,
            evidence={
                "action": _normalize_action_name(args.action) or "missing",
                "exception_type": type(exc).__name__,
            },
        )
    finally:
        logger.info("Operation completed.")
        emit_terminal_result(_build_terminal_result(_normalize_action_name(args.action)))
        sys.exit(RETURN_CODE)
