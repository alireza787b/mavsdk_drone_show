# src/drone_api_server.py
"""
Drone API Server - FastAPI Implementation
==========================================
Modern async API server for drone-side HTTP and WebSocket communication.
Uses canonical `/api/v1/...` HTTP routes plus a dedicated WebSocket stream.

HTTP REST Endpoints:
- GET  /api/v1/drone/state                    - Get current drone state (snapshot)
- GET  /api/v1/preflight/armability           - Probe live launch readiness
- POST /api/v1/drone/commands                 - Receive command from GCS
- GET  /api/v1/navigation/home                - Get home position
- GET  /api/v1/navigation/global-origin       - Get GPS global origin
- GET  /api/v1/git/status                     - Get drone git status
- GET  /api/v1/system/health                  - Versioned health probe
- GET  /ping                                  - Stable operational health probe
- GET  /api/v1/navigation/position-deviation  - Calculate position deviation
- GET  /api/v1/network/status                 - Get network information
- GET  /api/v1/swarm/config                   - Get swarm configuration
- GET  /api/v1/telemetry/local-position       - Get LOCAL_POSITION_NED data

WebSocket Endpoints:
- WS   /ws/drone-state                          - Real-time drone state streaming

API Documentation:
- Interactive Docs: http://drone-ip:7070/docs
- OpenAPI Schema:   http://drone-ip:7070/openapi.json
"""

import math
import os
import time
import subprocess
import socket
from typing import Dict, Any, Optional, List

# FastAPI imports
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
import uvicorn
import requests
import asyncio
import json
from mavsdk.system import System

from mds_logging import get_logger
from mds_logging.api_schemas import OnboardUlogDownloadRequest, OnboardUlogJobDeleteResponse

logger = get_logger("drone_api")

# Project imports
from src.drone_config import DroneConfig
from src.constants import NetworkDefaults
from src.coordinate_utils import latlon_to_ne, get_expected_position_from_trajectory
from src.command_contract import DroneCommandRequest
from src.drone_api_routes import (
    DRONE_COMMANDS_ROUTE,
    DRONE_GIT_STATUS_ROUTE,
    DRONE_LIVE_ARMABILITY_ROUTE,
    DRONE_LOCAL_POSITION_ROUTE,
    DRONE_NAVIGATION_GLOBAL_ORIGIN_ROUTE,
    DRONE_NAVIGATION_HOME_ROUTE,
    DRONE_NETWORK_STATUS_ROUTE,
    DRONE_PX4_PARAMS_PATCH_APPLY_ROUTE,
    DRONE_PX4_PARAMS_POLICY_ROUTE,
    DRONE_PX4_PARAMS_SNAPSHOT_CURRENT_ROUTE,
    DRONE_PX4_PARAMS_SNAPSHOT_REFRESH_ROUTE,
    DRONE_PX4_PARAM_VALUE_ROUTE_TEMPLATE,
    DRONE_POSITION_DEVIATION_ROUTE,
    DRONE_STATE_ROUTE,
    DRONE_SWARM_CONFIG_ROUTE,
    DRONE_SYSTEM_HEALTH_ROUTE,
    DRONE_ULOG_DOWNLOAD_CONTENT_ROUTE_TEMPLATE,
    DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE,
    DRONE_ULOG_ERASE_ALL_ROUTE,
    DRONE_ULOG_FILES_ROUTE,
    DRONE_ULOG_FILE_DOWNLOAD_ROUTE_TEMPLATE,
    DRONE_ULOG_POLICY_ROUTE,
    DRONE_WS_STATE_ROUTE,
)
from src.gcs_api_routes import (
    GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE,
    GCS_ORIGIN_BOOTSTRAP_ROUTE,
)
from src.mission_startup import probe_offboard_armability
from src.px4_param_models import (
    Px4ParamPatchApplyRequest,
    Px4ParamPatchApplyResponse,
    Px4ParamPolicyResponse,
    Px4ParamSetRequest,
    Px4ParamSetResponse,
    Px4ParamSnapshotRequest,
    Px4ParamSnapshotResponse,
    Px4ParamValueResponse,
)
from src.px4_params.service import Px4ParamService
from src.ulog_service import OnboardUlogService
from functions.git_manager import resolve_current_git_branch
from functions.data_utils import safe_float, safe_get, safe_int
from functions.file_utils import load_csv, get_trajectory_first_position
from src import __version__ as MDS_VERSION
from src.params import Params
from src.enums import Mission, State, CommandErrorCode

# Base directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, Params.config_file_name)
SWARM_FILE_PATH = os.path.join(BASE_DIR, Params.swarm_file_name)

# Color codes for logging (preserved from Flask version)
RESET = "\x1b[0m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
INFO_SYMBOL = BLUE + "ℹ️" + RESET
ERROR_SYMBOL = RED + "❌" + RESET


# ============================================================================
# Pydantic Models for Request/Response Validation
# ============================================================================

class ReadinessCheckResponse(BaseModel):
    id: str
    label: str
    ready: bool
    detail: str


class ReadinessMessageResponse(BaseModel):
    source: str
    severity: str
    message: str
    timestamp: int


class DroneStateResponse(BaseModel):
    """Drone state response"""
    pos_id: Any
    detected_pos_id: Any
    state: int
    mission: Any
    last_mission: Any
    position_lat: float
    position_long: float
    position_alt: float
    velocity_north: float
    velocity_east: float
    velocity_down: float
    yaw: float
    battery_voltage: float
    follow_mode: Any = None
    update_time: Any = None
    timestamp: int
    server_time: int = 0
    flight_mode: Any
    base_mode: Any
    system_status: Any
    is_armed: bool
    is_ready_to_arm: bool
    home_position_set: bool = False
    readiness_status: str = "unknown"
    readiness_summary: str = "Readiness unavailable"
    readiness_checks: List[ReadinessCheckResponse] = Field(default_factory=list)
    preflight_blockers: List[ReadinessMessageResponse] = Field(default_factory=list)
    preflight_warnings: List[ReadinessMessageResponse] = Field(default_factory=list)
    status_messages: List[ReadinessMessageResponse] = Field(default_factory=list)
    preflight_last_update: int = 0
    hdop: float
    vdop: float
    gps_fix_type: int
    satellites_visible: int
    ip: str


class CommandAckResponse(BaseModel):
    """
    Detailed command acknowledgment response.

    Returns acceptance/rejection status with error codes for debugging.
    This replaces the simple {"status": "success"} response.
    """
    status: str = Field(..., description="'accepted' or 'rejected'")
    command_id: Optional[str] = Field(None, description="Command tracking ID from GCS")
    hw_id: str = Field(..., description="Hardware ID of this drone")
    pos_id: int = Field(..., description="Position ID of this drone")
    current_state: int = Field(..., description="Current drone state before command")
    new_state: Optional[int] = Field(None, description="New state after command accepted")
    mission_type: Optional[int] = Field(None, description="Parsed mission type")
    trigger_time: Optional[int] = Field(None, description="Trigger time from command")
    message: str = Field(..., description="Human-readable status message")
    error_code: Optional[str] = Field(None, description="Error code (e.g., E100, E201)")
    error_detail: Optional[str] = Field(None, description="Detailed error information")
    timestamp: int = Field(..., description="Response timestamp in milliseconds")


class LiveArmabilityResponse(BaseModel):
    success: bool = True
    ready: bool
    summary: str
    blockers: List[str] = Field(default_factory=list)
    armable: bool = False
    global_position_ok: bool = False
    home_position_ok: bool = False
    local_position_ok: bool = False
    gyro_ok: bool = False
    accel_ok: bool = False
    mag_ok: bool = False
    timed_out: bool = False
    elapsed_sec: float = 0.0
    require_global_position: bool = True
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    probe_error: Optional[str] = None


class DroneHealthResponse(BaseModel):
    status: str
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    version: str


class HomePositionResponse(BaseModel):
    latitude: float
    longitude: float
    altitude: float
    timestamp: int


class GPSGlobalOriginResponse(BaseModel):
    latitude: float
    longitude: float
    altitude: float
    origin_time_usec: Optional[int] = None
    timestamp: int


class DroneGitStatusResponse(BaseModel):
    branch: str
    commit: str
    author_name: str
    author_email: str
    commit_date: str
    commit_message: str
    remote_url: Optional[str] = None
    tracking_branch: Optional[str] = None
    status: str
    uncommitted_changes: List[str] = Field(default_factory=list)
    commits_ahead: int = 0
    commits_behind: int = 0


class PositionDeviationResponse(BaseModel):
    deviation_north: float
    deviation_east: float
    total_deviation: float
    within_acceptable_range: bool


class WifiStatusResponse(BaseModel):
    ssid: str
    signal_strength_percent: Any


class EthernetStatusResponse(BaseModel):
    interface: str
    connection_name: str


class NetworkStatusResponse(BaseModel):
    wifi: Optional[WifiStatusResponse] = None
    ethernet: Optional[EthernetStatusResponse] = None
    timestamp: int


class LocalPositionNEDResponse(BaseModel):
    time_boot_ms: int
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    timestamp: int


# ============================================================================
# DroneAPIServer Class (FastAPI Version)
# ============================================================================

class DroneAPIServer:
    """
    Drone API Server using FastAPI.

    Drop-in replacement for the Flask-based FlaskHandler with:
    - Async/await for better performance
    - Automatic OpenAPI documentation
    - Type validation with Pydantic
    - Same routes and behavior as Flask version
    - WebSocket support for real-time telemetry streaming
    """
    # Class-level flags to prevent log spam for expected SITL failures
    _network_info_error_logged = False
    _origin_fetch_error_logged = False

    def __init__(self, params: Params, drone_config: DroneConfig):
        """
        Initialize the DroneAPIServer with params and drone_config.
        DroneCommunicator will be injected later using the set_drone_communicator() method.

        Args:
            params (Params): Global parameters
            drone_config (DroneConfig): Drone configuration object
        """
        self.app = FastAPI(
            title="Drone API Server",
            description="High-performance API server for drone-side communication with HTTP REST and WebSocket support",
            version=MDS_VERSION,
            docs_url="/docs",  # Interactive API docs
            redoc_url="/redoc",  # Alternative docs
            openapi_url="/openapi.json"  # OpenAPI schema
        )

        # Add CORS middleware (same as Flask-CORS)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self.params = params
        self.drone_communicator = None  # Will be set later
        self.drone_config = drone_config

        # WebSocket connection management
        self.active_websockets: List[WebSocket] = []
        self.last_state_hash = None  # Track state changes
        self._live_probe_lock = asyncio.Lock()
        self._px4_param_lock = asyncio.Lock()
        self._ulog_lock = asyncio.Lock()
        self._px4_param_snapshot_cache: Optional[Px4ParamSnapshotResponse] = None
        self._px4_param_service = Px4ParamService(
            params,
            hw_id=str(getattr(drone_config, "hw_id", "unknown")),
        )
        self._ulog_service = OnboardUlogService(
            params,
            hw_id=str(getattr(drone_config, "hw_id", "unknown")),
            pos_id=safe_int(getattr(drone_config, "pos_id", None), None),
        )

        self.setup_routes()

    def set_drone_communicator(self, drone_communicator):
        """Setter for injecting the DroneCommunicator dependency after initialization."""
        self.drone_communicator = drone_communicator

    def _resolve_live_probe_connection(self) -> tuple[int, str]:
        """Mirror the runtime MAVSDK wiring used by mission/action execution."""
        grpc_port = getattr(
            self.params,
            "DEFAULT_GRPC_PORT",
            NetworkDefaults.GRPC_BASE_PORT,
        )
        mavlink_port = safe_int(getattr(self.params, "mavsdk_port", 14540), 14540)
        return grpc_port, f"udp://:{mavlink_port}"

    @staticmethod
    def _port_is_open(port: int, host: str = "127.0.0.1", timeout: float = 0.2) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, int(port))) == 0

    @staticmethod
    def _find_mavsdk_server_binary() -> str:
        env_path = os.environ.get("MAVSDK_SERVER_PATH")
        candidates = [
            env_path,
            os.path.join(BASE_DIR, "mavsdk_server"),
            os.path.join(os.path.dirname(BASE_DIR), "mavsdk_server"),
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        raise FileNotFoundError("mavsdk_server binary not found")

    async def _ensure_live_probe_server(self, grpc_port: int, udp_port: int):
        """Start a short-lived mavsdk_server only when the local port is idle."""
        if self._port_is_open(grpc_port):
            return None, False

        mavsdk_server_path = self._find_mavsdk_server_binary()
        process = subprocess.Popen(
            [mavsdk_server_path, "-p", str(grpc_port), f"udp://:{udp_port}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + safe_float(
            getattr(self.params, "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC", 5.0),
            5.0,
        )
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("mavsdk_server exited before the probe connection was ready.")
            if self._port_is_open(grpc_port):
                return process, True
            await asyncio.sleep(0.1)

        process.terminate()
        raise TimeoutError("Timed out waiting for temporary mavsdk_server to start.")

    @staticmethod
    def _stop_live_probe_server(process: Optional[subprocess.Popen]) -> None:
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    async def _wait_for_mavsdk_connection(self, drone: System) -> None:
        connect_timeout = safe_float(
            getattr(self.params, "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC", 5.0),
            5.0,
        )
        deadline = time.monotonic() + connect_timeout
        connection_iter = drone.core.connection_state().__aiter__()

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for local MAVSDK connection.")

            try:
                state = await asyncio.wait_for(connection_iter.__anext__(), timeout=min(1.0, remaining))
            except asyncio.TimeoutError:
                continue
            except StopAsyncIteration as exc:
                raise RuntimeError("MAVSDK connection stream ended before connection was confirmed.") from exc

            if state.is_connected:
                return

    async def _probe_live_armability(self, require_global_position: bool = True) -> Dict[str, Any]:
        probe_timeout = safe_float(
            getattr(self.params, "LIVE_ARMABILITY_PROBE_TIMEOUT_SEC", 6.0),
            6.0,
        )
        connect_timeout = safe_float(
            getattr(self.params, "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC", 5.0),
            5.0,
        )

        try:
            async with self._live_probe_lock:
                grpc_port, system_address = self._resolve_live_probe_connection()
                udp_port = safe_int(getattr(self.params, "mavsdk_port", 14540), 14540)
                mavsdk_server, started_server = await self._ensure_live_probe_server(grpc_port, udp_port)
                try:
                    drone = System(
                        mavsdk_server_address="127.0.0.1",
                        port=grpc_port,
                    )
                    await asyncio.wait_for(
                        drone.connect(system_address=system_address),
                        timeout=connect_timeout,
                    )
                    await self._wait_for_mavsdk_connection(drone)
                    result = await probe_offboard_armability(
                        drone,
                        require_global_position=require_global_position,
                        timeout=probe_timeout,
                        logger=logger,
                    )
                finally:
                    if started_server:
                        self._stop_live_probe_server(mavsdk_server)
            return {
                "success": True,
                **result,
                "timestamp": int(time.time() * 1000),
                "probe_error": None,
            }
        except Exception as exc:
            timed_out = isinstance(exc, (TimeoutError, asyncio.TimeoutError))
            return {
                "success": False,
                "ready": False,
                "summary": (
                    f"Timed out waiting for live armability probe: {exc}"
                    if timed_out
                    else f"Live armability probe unavailable: {exc}"
                ),
                "blockers": (
                    ["live armability probe timed out"]
                    if timed_out
                    else ["live armability probe unavailable"]
                ),
                "armable": False,
                "global_position_ok": False,
                "home_position_ok": False,
                "local_position_ok": False,
                "gyro_ok": False,
                "accel_ok": False,
                "mag_ok": False,
                "timed_out": timed_out,
                "elapsed_sec": 0.0,
                "require_global_position": require_global_position,
                "timestamp": int(time.time() * 1000),
                "probe_error": str(exc),
            }

    async def _with_local_mavsdk_system(self, operation):
        """Run an async operation against the local PX4 instance over MAVSDK."""
        async with self._px4_param_lock:
            grpc_port, system_address = self._resolve_live_probe_connection()
            udp_port = safe_int(getattr(self.params, "mavsdk_port", 14540), 14540)
            mavsdk_server, started_server = await self._ensure_live_probe_server(grpc_port, udp_port)

            try:
                drone = System(
                    mavsdk_server_address="127.0.0.1",
                    port=grpc_port,
                )
                await asyncio.wait_for(
                    drone.connect(system_address=system_address),
                    timeout=safe_float(
                        getattr(self.params, "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC", 5.0),
                        5.0,
                    ),
                )
                await self._wait_for_mavsdk_connection(drone)
                return await operation(drone)
            finally:
                if started_server:
                    self._stop_live_probe_server(mavsdk_server)

    async def _with_local_ulog_system(self, operation):
        """Run a ULog operation against the local PX4 instance over MAVSDK."""
        async with self._ulog_lock:
            grpc_port, system_address = self._resolve_live_probe_connection()
            udp_port = safe_int(getattr(self.params, "mavsdk_port", 14540), 14540)
            mavsdk_server, started_server = await self._ensure_live_probe_server(grpc_port, udp_port)

            try:
                drone = System(
                    mavsdk_server_address="127.0.0.1",
                    port=grpc_port,
                )
                await asyncio.wait_for(
                    drone.connect(system_address=system_address),
                    timeout=safe_float(
                        getattr(self.params, "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC", 5.0),
                        5.0,
                    ),
                )
                await self._wait_for_mavsdk_connection(drone)
                return await operation(drone)
            finally:
                if started_server:
                    self._stop_live_probe_server(mavsdk_server)

    async def _run_ulog_download_job(self, job_id: str) -> None:
        """Complete a queued onboard ULog download in the background."""
        try:
            await self._with_local_ulog_system(
                lambda drone: self._ulog_service.perform_download(drone, job_id)
            )
        except Exception as exc:
            logger.error(f"Onboard ULog download job {job_id} failed before completion: {exc}")
            await self._ulog_service.mark_job_failed(job_id, str(exc))

    def _assert_px4_param_mutation_allowed(self) -> None:
        require_disarmed = bool(
            getattr(self.params, "PX4_PARAMETER_MUTATION_REQUIRE_DISARMED", True)
        )
        if require_disarmed and bool(getattr(self.drone_config, "is_armed", False)):
            raise HTTPException(
                status_code=409,
                detail="PX4 parameter writes are blocked while the vehicle is armed.",
            )

    def _assert_ulog_download_allowed(self) -> None:
        require_disarmed = bool(getattr(self.params, "ULOG_DOWNLOAD_REQUIRE_DISARMED", True))
        if require_disarmed and bool(getattr(self.drone_config, "is_armed", False)):
            raise HTTPException(
                status_code=409,
                detail="Onboard ULog download is blocked while the vehicle is armed.",
            )

    def _assert_ulog_erase_allowed(self) -> None:
        require_disarmed = bool(getattr(self.params, "ULOG_ERASE_REQUIRE_DISARMED", True))
        if require_disarmed and bool(getattr(self.drone_config, "is_armed", False)):
            raise HTTPException(
                status_code=409,
                detail="Onboard ULog erase-all is blocked while the vehicle is armed.",
            )

    @staticmethod
    def _serialize_drone_state_payload(drone_state: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize raw communicator state into the canonical HTTP/WebSocket payload shape."""
        payload = dict(drone_state)
        server_time_ms = int(time.time() * 1000)
        raw_update_time = payload.get('update_time')
        try:
            numeric_update_time = float(raw_update_time)
        except (TypeError, ValueError):
            numeric_update_time = 0.0

        if numeric_update_time > 0:
            if numeric_update_time < 1_000_000_000_000:
                payload['timestamp'] = int(numeric_update_time * 1000)
            else:
                payload['timestamp'] = int(numeric_update_time)
        else:
            payload['timestamp'] = server_time_ms

        payload['server_time'] = server_time_ms
        return DroneStateResponse.model_validate(payload).model_dump()

    def setup_routes(self):
        """Define all API routes (same as Flask version)"""

        @self.app.get(DRONE_STATE_ROUTE, response_model=DroneStateResponse)
        async def get_drone_state():
            """Endpoint to retrieve the current state of the drone."""
            try:
                drone_state = self.drone_communicator.get_drone_state()
                if drone_state:
                    return self._serialize_drone_state_payload(drone_state)
                else:
                    raise HTTPException(status_code=404, detail="Drone State not found")
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"error_in_get_drone_state: {str(e)}")

        @self.app.get(DRONE_LIVE_ARMABILITY_ROUTE, response_model=LiveArmabilityResponse)
        async def get_live_armability(require_global_position: bool = True):
            """Run an on-demand MAVSDK launch-readiness probe."""
            result = await self._probe_live_armability(require_global_position=require_global_position)
            return LiveArmabilityResponse(**result)

        @self.app.post(DRONE_COMMANDS_ROUTE, response_model=CommandAckResponse)
        async def send_drone_command(command: DroneCommandRequest) -> CommandAckResponse:
            """
            Endpoint to send a command to the drone.

            Returns detailed acknowledgment with status and error codes.
            No longer returns generic HTTP 500 - all errors return structured response.
            """
            timestamp = int(time.time() * 1000)
            hw_id = str(self.drone_config.hw_id)
            pos_id = int(self.drone_config.pos_id)
            current_state = int(self.drone_config.state)

            try:
                command_data = command.model_dump(exclude_none=True)
                command_id = command_data.get('command_id')

                # Validate command structure
                validation_result = self._validate_command(command_data)
                if not validation_result['valid']:
                    logger.warning(f"Command rejected: {validation_result['message']}")
                    return CommandAckResponse(
                        status="rejected",
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        message=validation_result['message'],
                        error_code=validation_result['error_code'],
                        error_detail=validation_result.get('detail'),
                        timestamp=timestamp
                    )

                # Parse mission type for response
                mission_type = int(command_data["mission_type"])
                trigger_time = int(command_data.get("trigger_time", 0))
                known_command = self._find_active_command_by_id(command_id)
                if known_command is not None:
                    known_mission_type = int(known_command['mission_type'])
                    if known_mission_type == mission_type:
                        try:
                            mission_name = Mission(mission_type).name
                        except ValueError:
                            mission_name = f"MISSION_{mission_type}"

                        return CommandAckResponse(
                            status="accepted",
                            command_id=command_id,
                            hw_id=hw_id,
                            pos_id=pos_id,
                            current_state=current_state,
                            new_state=int(known_command['state']),
                            mission_type=mission_type,
                            trigger_time=int(known_command.get('trigger_time', trigger_time)),
                            message=self._build_idempotent_acceptance_message(
                                mission_name=mission_name,
                                phase=str(known_command.get('phase', 'active')),
                            ),
                            timestamp=timestamp,
                        )

                    return CommandAckResponse(
                        status="rejected",
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        mission_type=mission_type,
                        trigger_time=trigger_time,
                        message="Command ID is already active for a different mission on this drone",
                        error_code=CommandErrorCode.INVALID_FORMAT.value,
                        error_detail=(
                            f"Existing mission type={known_mission_type}, requested mission type={mission_type}"
                        ),
                        timestamp=timestamp,
                    )

                previous_command_id = getattr(self.drone_config, 'current_command_id', None)
                superseded_pending_command = (
                    current_state == State.MISSION_READY.value
                    and previous_command_id
                    and previous_command_id != command_id
                    and mission_type in self._allowed_override_missions()
                )

                # Check state preconditions
                state_check = self._check_state_preconditions(mission_type)
                if not state_check['valid']:
                    logger.warning(f"Command rejected due to state: {state_check['message']}")
                    return CommandAckResponse(
                        status="rejected",
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        mission_type=mission_type,
                        trigger_time=trigger_time,
                        message=state_check['message'],
                        error_code=state_check['error_code'],
                        error_detail=state_check.get('detail'),
                        timestamp=timestamp
                    )

                if mission_type == Mission.NONE.value:
                    had_active_command = current_state in {
                        State.MISSION_READY.value,
                        State.MISSION_EXECUTING.value,
                    }
                    if current_state == State.MISSION_READY.value and previous_command_id and previous_command_id != command_id:
                        await self._report_pending_command_superseded(
                            command_id=previous_command_id,
                            override_mission_type=mission_type,
                        )

                    self.drone_config.current_command_id = command_id
                    new_state, cancel_message = await self._cancel_active_or_pending_command(
                        had_active_command=had_active_command,
                    )
                    logger.info(f"Command accepted: CANCEL (trigger: {trigger_time})")
                    return CommandAckResponse(
                        status="accepted",
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        new_state=new_state,
                        mission_type=mission_type,
                        trigger_time=trigger_time,
                        message=cancel_message,
                        timestamp=timestamp,
                    )

                # Stage the command id before the mission becomes visible to the
                # scheduler. Otherwise a fast scheduler tick can launch the
                # mission script before current_command_id is stored, which
                # drops execution tracking callbacks for that run.
                self.drone_config.current_command_id = command_id

                try:
                    self.drone_communicator.process_command(command_data)
                except Exception:
                    # Restore the previous pending command on install failure so
                    # an override attempt does not orphan the older staged
                    # mission's tracking identity.
                    self.drone_config.current_command_id = previous_command_id
                    raise

                if superseded_pending_command:
                    await self._report_pending_command_superseded(
                        command_id=previous_command_id,
                        override_mission_type=mission_type,
                    )

                # Get mission name for message
                try:
                    mission_name = Mission(mission_type).name
                except ValueError:
                    mission_name = f"MISSION_{mission_type}"

                logger.info(f"Command accepted: {mission_name} (trigger: {trigger_time})")
                return CommandAckResponse(
                    status="accepted",
                    command_id=command_id,
                    hw_id=hw_id,
                    pos_id=pos_id,
                    current_state=current_state,
                    new_state=State.MISSION_READY.value,
                    mission_type=mission_type,
                    trigger_time=trigger_time,
                    message=self._build_acceptance_message(
                        mission_name=mission_name,
                        trigger_time=trigger_time,
                        superseded_pending_command=superseded_pending_command,
                    ),
                    timestamp=timestamp
                )

            except KeyError as e:
                logger.error(f"Missing field in command: {e}")
                return CommandAckResponse(
                    status="rejected",
                    command_id=command_data.get('command_id') if command_data else None,
                    hw_id=hw_id,
                    pos_id=pos_id,
                    current_state=current_state,
                    message=f"Missing required field: {str(e)}",
                    error_code=CommandErrorCode.MISSING_MISSION_TYPE.value,
                    error_detail=str(e),
                    timestamp=timestamp
                )
            except ValueError as e:
                logger.error(f"Invalid value in command: {e}")
                return CommandAckResponse(
                    status="rejected",
                    command_id=command_data.get('command_id') if command_data else None,
                    hw_id=hw_id,
                    pos_id=pos_id,
                    current_state=current_state,
                    message=f"Invalid value: {str(e)}",
                    error_code=CommandErrorCode.INVALID_FORMAT.value,
                    error_detail=str(e),
                    timestamp=timestamp
                )
            except AttributeError as e:
                logger.error(f"Configuration attribute error: {e}")
                return CommandAckResponse(
                    status="rejected",
                    command_id=command_data.get('command_id') if command_data else None,
                    hw_id=hw_id,
                    pos_id=pos_id,
                    current_state=current_state,
                    message=f"Configuration error: {str(e)}",
                    error_code=CommandErrorCode.INTERNAL_ERROR.value,
                    error_detail=f"AttributeError: {str(e)} - Check drone configuration",
                    timestamp=timestamp
                )
            except Exception as e:
                logger.exception(f"Unexpected error processing command: {e}")
                return CommandAckResponse(
                    status="rejected",
                    command_id=command_data.get('command_id') if command_data else None,
                    hw_id=hw_id,
                    pos_id=pos_id,
                    current_state=current_state,
                    message=f"Internal error: {str(e)}",
                    error_code=CommandErrorCode.INTERNAL_ERROR.value,
                    error_detail=str(e),
                    timestamp=timestamp
                )

        @self.app.get(DRONE_NAVIGATION_HOME_ROUTE, response_model=HomePositionResponse)
        async def get_home_pos():
            """
            Endpoint to retrieve the home position of the drone.
            Returns JSON response containing the home position coordinates and a timestamp.
            """
            try:
                home_pos = self.drone_config.home_position
                if home_pos:
                    home_pos_with_timestamp = {
                        'latitude': home_pos.get('lat'),
                        'longitude': home_pos.get('long'),
                        'altitude': home_pos.get('alt'),
                        'timestamp': int(time.time() * 1000)
                    }
                    logger.debug(f"Retrieved home position: {home_pos_with_timestamp}")
                    return home_pos_with_timestamp
                else:
                    logger.warning("Home position requested but not set.")
                    raise HTTPException(status_code=404, detail="Home position not set")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error retrieving home position: {e}")
                raise HTTPException(status_code=500, detail="Failed to retrieve home position")

        @self.app.get(DRONE_NAVIGATION_GLOBAL_ORIGIN_ROUTE, response_model=GPSGlobalOriginResponse)
        async def get_gps_global_origin():
            """
            Endpoint to retrieve the GPS global origin from the drone configuration.
            Returns JSON response containing latitude, longitude, altitude, timestamps.
            """
            try:
                gps_origin = self.drone_config.gps_global_origin
                if gps_origin:
                    gps_origin_with_timestamp = {
                        'latitude': gps_origin.get('lat'),
                        'longitude': gps_origin.get('lon'),
                        'altitude': gps_origin.get('alt'),
                        'origin_time_usec': gps_origin.get('time_usec'),
                        'timestamp': int(time.time() * 1000)
                    }
                    logger.debug(f"Retrieved GPS global origin: {gps_origin_with_timestamp}")
                    return gps_origin_with_timestamp
                else:
                    logger.warning("GPS global origin requested but not set.")
                    raise HTTPException(status_code=404, detail="GPS global origin not set")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error retrieving GPS global origin: {e}")
                raise HTTPException(status_code=500, detail="Failed to retrieve GPS global origin")

        @self.app.get(DRONE_GIT_STATUS_ROUTE, response_model=DroneGitStatusResponse)
        async def get_git_status():
            """
            Endpoint to retrieve the current Git status of the drone.
            Returns branch, commit, author, date, message, remote URL, tracking branch, and status.
            """
            try:
                # Retrieve git information
                branch = resolve_current_git_branch(
                    lambda cmd, cwd=None: self._execute_git_command(cmd)
                )
                commit = self._execute_git_command(['git', 'rev-parse', 'HEAD'])
                author_name = self._execute_git_command(['git', 'show', '-s', '--format=%an', commit])
                author_email = self._execute_git_command(['git', 'show', '-s', '--format=%ae', commit])
                commit_date = self._execute_git_command(['git', 'show', '-s', '--format=%cd', '--date=iso-strict', commit])
                commit_message = self._execute_git_command(['git', 'show', '-s', '--format=%B', commit])
                remote_url = self._execute_git_command(['git', 'config', '--get', 'remote.origin.url'])
                tracking_branch = self._execute_git_command(['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'])
                status = self._execute_git_command(['git', 'status', '--porcelain'])

                # Count commits ahead/behind origin
                commits_ahead = 0
                commits_behind = 0
                try:
                    ahead_behind = self._execute_git_command(
                        ['git', 'rev-list', '--left-right', '--count', f'{tracking_branch}...HEAD']
                    )
                    if ahead_behind:
                        parts = ahead_behind.split()
                        if len(parts) == 2:
                            commits_behind = int(parts[0])
                            commits_ahead = int(parts[1])
                except Exception:
                    pass

                response = {
                    'branch': branch,
                    'commit': commit,
                    'author_name': author_name,
                    'author_email': author_email,
                    'commit_date': commit_date,
                    'commit_message': commit_message,
                    'remote_url': remote_url,
                    'tracking_branch': tracking_branch,
                    'status': 'clean' if not status else 'dirty',
                    'uncommitted_changes': status.splitlines() if status else [],
                    'commits_ahead': commits_ahead,
                    'commits_behind': commits_behind,
                }

                return response
            except subprocess.CalledProcessError as e:
                raise HTTPException(status_code=500, detail=f"Git command failed: {str(e)}")

        @self.app.get(DRONE_SYSTEM_HEALTH_ROUTE, response_model=DroneHealthResponse)
        async def ping_v1():
            """Canonical v1 health endpoint with timestamp and version metadata."""
            return DroneHealthResponse(status="ok", version=MDS_VERSION)

        @self.app.get('/ping')
        async def ping():
            """Simple endpoint to confirm connectivity."""
            return {"status": "ok"}

        @self.app.get(DRONE_POSITION_DEVIATION_ROUTE, response_model=PositionDeviationResponse)
        async def get_position_deviation():
            """Endpoint to calculate the drone's position deviation from its intended initial position."""
            try:
                # Step 1: Get the origin coordinates from GCS
                origin = self._get_origin_from_gcs()
                if not origin:
                    raise HTTPException(status_code=400, detail="Origin coordinates not set on GCS")

                # Step 2: Get the drone's current position
                current_lat = safe_float(safe_get(self.drone_config.position, 'lat'))
                current_lon = safe_float(safe_get(self.drone_config.position, 'long'))
                if current_lat is None or current_lon is None:
                    raise HTTPException(status_code=400, detail="Drone's current position not available")

                # Step 3: Get expected position from trajectory CSV
                pos_id = safe_get(self.drone_config.config, 'pos_id', self.drone_config.hw_id)
                if not pos_id:
                    pos_id = self.drone_config.hw_id

                initial_north, initial_east = get_expected_position_from_trajectory(
                    pos_id, self.params.sim_mode, base_dir=BASE_DIR
                )

                if initial_north is None or initial_east is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Could not read trajectory file for pos_id={pos_id}"
                    )

                # Step 4: Convert current position to NE coordinates
                current_north, current_east = latlon_to_ne(current_lat, current_lon, origin['lat'], origin['lon'])

                # Step 5: Calculate deviations
                deviation_north = current_north - initial_north
                deviation_east = current_east - initial_east
                total_deviation = math.sqrt(deviation_north**2 + deviation_east**2)

                # Step 6: Check if within acceptable range
                acceptable_range = self.params.acceptable_deviation
                within_range = total_deviation <= acceptable_range

                # Step 7: Return response
                response = {
                    "deviation_north": deviation_north,
                    "deviation_east": deviation_east,
                    "total_deviation": total_deviation,
                    "within_acceptable_range": within_range
                }
                return response

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error in get_position_deviation: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get(DRONE_NETWORK_STATUS_ROUTE, response_model=NetworkStatusResponse)
        async def get_network_info():
            """
            Endpoint to retrieve current network information.
            This includes both Wi-Fi and wired network (if connected).
            """
            try:
                network_info = self._get_network_info()
                if network_info:
                    return network_info
                else:
                    raise HTTPException(status_code=404, detail="No network information available")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error in network-info endpoint: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get(DRONE_SWARM_CONFIG_ROUTE, response_model=List[Dict[str, Any]])
        async def get_swarm():
            """Get swarm configuration data"""
            logger.info("Swarm data requested")
            try:
                swarm = self.load_swarm(SWARM_FILE_PATH)
                return swarm
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error loading swarm data: {e}")

        @self.app.get(DRONE_LOCAL_POSITION_ROUTE, response_model=LocalPositionNEDResponse)
        async def get_local_position_ned():
            """
            Endpoint to retrieve the LOCAL_POSITION_NED data from MAVLink.

            Returns:
                JSON response containing:
                - time_boot_ms: Timestamp from autopilot (ms since boot)
                - x, y, z: Position in meters (NED frame)
                - vx, vy, vz: Velocity in m/s (NED frame)
                - timestamp: Current server timestamp (ms)
            """
            try:
                ned_data = self.drone_config.local_position_ned

                if ned_data['time_boot_ms'] == 0:  # Initial zero value indicates no data yet
                    logger.warning("LOCAL_POSITION_NED data not yet received")
                    raise HTTPException(status_code=404, detail="NED data not available")

                response = {
                    'time_boot_ms': ned_data['time_boot_ms'],
                    'x': ned_data['x'],
                    'y': ned_data['y'],
                    'z': ned_data['z'],
                    'vx': ned_data['vx'],
                    'vy': ned_data['vy'],
                    'vz': ned_data['vz'],
                    'timestamp': int(time.time() * 1000)
                }

                logger.debug(f"Returning LOCAL_POSITION_NED: {response}")
                return response

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error retrieving LOCAL_POSITION_NED: {e}")
                raise HTTPException(status_code=500, detail="Failed to retrieve NED position")

        @self.app.get(DRONE_PX4_PARAMS_POLICY_ROUTE, response_model=Px4ParamPolicyResponse)
        async def get_px4_param_policy():
            """Return the local PX4 parameter subsystem policy envelope."""
            return self._px4_param_service.build_policy()

        @self.app.post(DRONE_PX4_PARAMS_SNAPSHOT_REFRESH_ROUTE, response_model=Px4ParamSnapshotResponse)
        async def refresh_px4_param_snapshot(request: Px4ParamSnapshotRequest):
            """Fetch a fresh PX4 parameter snapshot from the local vehicle."""
            try:
                snapshot = await self._with_local_mavsdk_system(
                    lambda drone: self._px4_param_service.build_snapshot(
                        drone,
                        component_id=request.component_id,
                    )
                )
                self._px4_param_snapshot_cache = snapshot
                return snapshot
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(f"Error refreshing PX4 parameter snapshot: {exc}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to refresh PX4 parameter snapshot: {exc}",
                ) from exc

        @self.app.get(DRONE_PX4_PARAMS_SNAPSHOT_CURRENT_ROUTE, response_model=Px4ParamSnapshotResponse)
        async def get_current_px4_param_snapshot():
            """Return the latest locally cached PX4 parameter snapshot."""
            if self._px4_param_snapshot_cache is None:
                raise HTTPException(status_code=404, detail="No PX4 parameter snapshot cached yet")
            return self._px4_param_snapshot_cache

        @self.app.get(DRONE_PX4_PARAM_VALUE_ROUTE_TEMPLATE, response_model=Px4ParamValueResponse)
        async def get_px4_param_value(name: str):
            """Read one PX4 parameter directly from the local vehicle."""
            try:
                return await self._with_local_mavsdk_system(
                    lambda drone: self._px4_param_service.get_param_value(drone, name)
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(f"Error reading PX4 parameter {name}: {exc}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to read PX4 parameter {name}: {exc}",
                ) from exc

        @self.app.patch(DRONE_PX4_PARAM_VALUE_ROUTE_TEMPLATE, response_model=Px4ParamSetResponse)
        async def set_px4_param_value(name: str, request: Px4ParamSetRequest):
            """Write one PX4 parameter and optionally verify readback."""
            self._assert_px4_param_mutation_allowed()
            try:
                response = await self._with_local_mavsdk_system(
                    lambda drone: self._px4_param_service.set_param_value(drone, name, request)
                )
                self._px4_param_snapshot_cache = None
                return response
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(f"Error writing PX4 parameter {name}: {exc}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to write PX4 parameter {name}: {exc}",
                ) from exc

        @self.app.post(DRONE_PX4_PARAMS_PATCH_APPLY_ROUTE, response_model=Px4ParamPatchApplyResponse)
        async def apply_px4_param_patch(request: Px4ParamPatchApplyRequest):
            """Apply a batch parameter patch to the local PX4 vehicle."""
            self._assert_px4_param_mutation_allowed()
            try:
                response = await self._with_local_mavsdk_system(
                    lambda drone: self._px4_param_service.apply_patch(drone, request)
                )
                self._px4_param_snapshot_cache = None
                return response
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(f"Error applying PX4 parameter patch: {exc}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to apply PX4 parameter patch: {exc}",
                ) from exc

        @self.app.get(DRONE_ULOG_POLICY_ROUTE)
        async def get_onboard_ulog_policy():
            """Return the local onboard ULog subsystem policy envelope."""
            return self._ulog_service.build_policy()

        @self.app.get(DRONE_ULOG_FILES_ROUTE)
        async def list_onboard_ulog_files():
            """List onboard PX4 ULog files visible through MAVSDK."""
            try:
                return await self._with_local_ulog_system(
                    lambda drone: self._ulog_service.list_entries(
                        drone,
                        pos_id=safe_int(getattr(self.drone_config, "pos_id", None), None),
                    )
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(f"Error listing onboard ULogs: {exc}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to list onboard ULogs: {exc}",
                ) from exc

        @self.app.post(DRONE_ULOG_FILE_DOWNLOAD_ROUTE_TEMPLATE)
        async def create_onboard_ulog_download(
            log_id: int,
            request: OnboardUlogDownloadRequest | None = None,
        ):
            """Create a short-lived staged onboard ULog download job."""
            self._assert_ulog_download_allowed()
            download_request = request or OnboardUlogDownloadRequest()
            try:
                job_response = await self._with_local_ulog_system(
                    lambda drone: self._ulog_service.create_download_job(
                        drone,
                        int(log_id),
                        download_request,
                    )
                )
                asyncio.create_task(self._run_ulog_download_job(job_response.job.job_id))
                return job_response
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(f"Error creating onboard ULog download job for log {log_id}: {exc}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create onboard ULog download job: {exc}",
                ) from exc

        @self.app.get(DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE)
        async def get_onboard_ulog_download_job(job_id: str):
            """Return the current state of a staged onboard ULog download job."""
            job = await self._ulog_service.get_job(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail=f"ULog download job {job_id} not found")
            return job

        @self.app.delete(DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE)
        async def delete_onboard_ulog_download_job(job_id: str) -> OnboardUlogJobDeleteResponse:
            """Delete a staged onboard ULog download job and any staged file."""
            deleted = await self._ulog_service.delete_job(job_id)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"ULog download job {job_id} not found")
            return OnboardUlogJobDeleteResponse(
                status="deleted",
                job_id=job_id,
                timestamp=int(time.time() * 1000),
            )

        @self.app.get(DRONE_ULOG_DOWNLOAD_CONTENT_ROUTE_TEMPLATE)
        async def download_onboard_ulog_content(job_id: str):
            """Stream the staged onboard ULog file once the node-local job is ready."""
            try:
                stage_path, job = await self._ulog_service.get_ready_file(job_id)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

            return FileResponse(
                path=stage_path,
                media_type="application/octet-stream",
                filename=job.download_filename or stage_path.name,
            )

        @self.app.post(DRONE_ULOG_ERASE_ALL_ROUTE)
        async def erase_all_onboard_ulogs():
            """Erase all onboard PX4 ULog files through MAVSDK."""
            self._assert_ulog_erase_allowed()
            try:
                return await self._with_local_ulog_system(
                    lambda drone: self._ulog_service.erase_all(
                        drone,
                        pos_id=safe_int(getattr(self.drone_config, "pos_id", None), None),
                    )
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(f"Error erasing onboard ULogs: {exc}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to erase onboard ULogs: {exc}",
                ) from exc

        # ====================================================================
        # WebSocket Endpoint for Real-Time Telemetry Streaming
        # ====================================================================

        @self.app.websocket(DRONE_WS_STATE_ROUTE)
        async def websocket_drone_state(websocket: WebSocket):
            """
            WebSocket endpoint for real-time drone state streaming.

            Advantages over HTTP polling:
            - 95% less network overhead (no HTTP headers)
            - Real-time push (no polling delay)
            - Bi-directional communication
            - More efficient for GCS monitoring multiple drones

            Usage:
                ws://drone-ip:7070/ws/drone-state

            Example (JavaScript):
                const ws = new WebSocket('ws://192.168.1.100:7070/ws/drone-state');
                ws.onmessage = (event) => {
                    const droneState = JSON.parse(event.data);
                    console.log('Drone state:', droneState);
                };

            Example (Python):
                import asyncio
                import websockets
                async with websockets.connect('ws://192.168.1.100:7070/ws/drone-state') as ws:
                    while True:
                        state = json.loads(await ws.recv())
                        print(f"Drone state: {state}")

            The endpoint sends state updates at 1 Hz (configurable).
            """
            await websocket.accept()
            self.active_websockets.append(websocket)

            logger.info(f"WebSocket client connected from {websocket.client.host}")
            logger.info(f"Active WebSocket connections: {len(self.active_websockets)}")

            try:
                while True:
                    # Get current drone state
                    drone_state = self.drone_communicator.get_drone_state()

                    if drone_state:
                        # Send state to client
                        await websocket.send_json(self._serialize_drone_state_payload(drone_state))
                    else:
                        # Send error message if state not available
                        await websocket.send_json({
                            "error": "Drone state not available",
                            "timestamp": int(time.time() * 1000)
                        })

                    # Update interval: 1 Hz (can be adjusted based on requirements)
                    # For higher frequency: 0.1 (10 Hz) or 0.05 (20 Hz)
                    # For lower frequency: 2 (0.5 Hz) or 5 (0.2 Hz)
                    await asyncio.sleep(1.0)

            except WebSocketDisconnect:
                logger.info(f"WebSocket client disconnected from {websocket.client.host}")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            finally:
                # Clean up
                if websocket in self.active_websockets:
                    self.active_websockets.remove(websocket)
                logger.info(f"Active WebSocket connections: {len(self.active_websockets)}")

        # ====================================================================
        # Log API Endpoints (Phase 2 — log aggregation)
        # ====================================================================

        @self.app.get("/api/logs/sessions")
        async def get_log_sessions():
            """List available log sessions on this drone."""
            from mds_logging.session import list_sessions
            from mds_logging.constants import get_log_dir
            sessions = list_sessions(get_log_dir())
            return {"sessions": sessions}

        @self.app.get("/api/logs/sessions/{session_id}")
        async def get_log_session(
            session_id: str,
            level: Optional[str] = None,
            component: Optional[str] = None,
            limit: Optional[int] = None,
            offset: int = 0,
            since: Optional[str] = None,
        ):
            """Retrieve filtered JSONL content from a log session."""
            from mds_logging.session import read_session_lines
            from mds_logging.constants import get_log_dir
            lines = read_session_lines(
                get_log_dir(), session_id,
                level=level, component=component, limit=limit, offset=offset,
                since=since,
            )
            if lines is None:
                raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
            return {"session_id": session_id, "count": len(lines), "lines": lines}

        @self.app.get("/api/logs/stream")
        async def stream_logs(
            level: Optional[str] = None,
            component: Optional[str] = None,
            source: Optional[str] = None,
        ):
            """Stream current session logs in real-time via SSE."""
            import json as _json
            from mds_logging.watcher import get_watcher

            async def event_generator():
                async for entry in get_watcher().subscribe(
                    level=level, component=component, source=source,
                ):
                    yield f"data: {_json.dumps(entry)}\n\n"

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    # ========================================================================
    # Command Validation Methods
    # ========================================================================

    def _validate_command(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate command structure and values.

        Returns dict with 'valid', 'message', 'error_code', and optionally 'detail'.
        """
        mission_key = 'mission_type' if 'mission_type' in command_data else 'missionType'
        trigger_key = 'trigger_time' if 'trigger_time' in command_data else 'triggerTime'

        # Check required field: mission_type
        if mission_key not in command_data:
            return {
                'valid': False,
                'message': 'Missing required field: mission_type',
                'error_code': CommandErrorCode.MISSING_MISSION_TYPE.value
            }

        # Check required field: trigger_time
        if trigger_key not in command_data:
            return {
                'valid': False,
                'message': 'Missing required field: trigger_time',
                'error_code': CommandErrorCode.MISSING_TRIGGER_TIME.value
            }

        # Validate mission_type format and value
        try:
            mission_type = int(command_data[mission_key])
            if mission_type not in Mission._value2member_map_:
                return {
                    'valid': False,
                    'message': f'Unknown mission type: {mission_type}',
                    'error_code': CommandErrorCode.INVALID_MISSION_TYPE.value,
                    'detail': f'Valid mission types: {list(Mission._value2member_map_.keys())}'
                }
        except (ValueError, TypeError) as e:
            return {
                'valid': False,
                'message': f'Invalid mission_type format: {command_data[mission_key]}',
                'error_code': CommandErrorCode.INVALID_FORMAT.value,
                'detail': str(e)
            }

        # Validate trigger_time format
        try:
            trigger_time = int(command_data[trigger_key])
            if trigger_time < 0:
                return {
                    'valid': False,
                    'message': 'trigger_time must be non-negative',
                    'error_code': CommandErrorCode.INVALID_TRIGGER_TIME.value
                }
        except (ValueError, TypeError) as e:
            return {
                'valid': False,
                'message': f'Invalid trigger_time format: {command_data[trigger_key]}',
                'error_code': CommandErrorCode.INVALID_TRIGGER_TIME.value,
                'detail': str(e)
            }

        # Validate takeoff_altitude if present (for TAKE_OFF command)
        if 'takeoff_altitude' in command_data:
            try:
                altitude = float(command_data['takeoff_altitude'])
                if altitude <= 0:
                    return {
                        'valid': False,
                        'message': 'takeoff_altitude must be positive',
                        'error_code': CommandErrorCode.INVALID_ALTITUDE.value
                    }
                if altitude > self.params.max_takeoff_alt:
                    return {
                        'valid': False,
                        'message': f'takeoff_altitude exceeds maximum ({self.params.max_takeoff_alt}m)',
                        'error_code': CommandErrorCode.INVALID_ALTITUDE.value,
                        'detail': f'Requested: {altitude}m, Max: {self.params.max_takeoff_alt}m'
                    }
            except (ValueError, TypeError) as e:
                return {
                    'valid': False,
                    'message': f'Invalid takeoff_altitude format: {command_data["takeoff_altitude"]}',
                    'error_code': CommandErrorCode.INVALID_ALTITUDE.value,
                    'detail': str(e)
                }

        if mission_type == Mission.PRECISION_MOVE.value:
            if trigger_time != 0:
                return {
                    'valid': False,
                    'message': 'PRECISION_MOVE requires trigger_time=0',
                    'error_code': CommandErrorCode.INVALID_TRIGGER_TIME.value,
                }
            if not isinstance(command_data.get('precision_move'), dict):
                return {
                    'valid': False,
                    'message': 'Missing required field: precision_move',
                    'error_code': CommandErrorCode.INVALID_FORMAT.value,
                }

        return {'valid': True, 'message': 'Validation passed'}

    def _check_state_preconditions(self, mission_type: int) -> Dict[str, Any]:
        """
        Check if drone state allows this command.

        Returns dict with 'valid', 'message', 'error_code', and optionally 'detail'.
        """
        current_state = self.drone_config.state

        # Emergency commands always allowed
        if mission_type == Mission.KILL_TERMINATE.value:
            return {'valid': True, 'message': 'Emergency command always allowed'}

        if current_state in {State.MISSION_READY.value, State.MISSION_EXECUTING.value}:
            allowed_during_active_mission = self._allowed_override_missions()
            if mission_type not in allowed_during_active_mission:
                state_name = "MISSION_EXECUTING" if current_state == State.MISSION_EXECUTING.value else "MISSION_READY"
                detail_suffix = "pending trigger" if current_state == State.MISSION_READY.value else "currently executing"
                return {
                    'valid': False,
                    'message': 'Cannot accept a new command while another command is active',
                    'error_code': CommandErrorCode.ALREADY_EXECUTING.value,
                    'detail': f'Current state: {state_name}, mission: {self.drone_config.mission} ({detail_suffix})'
                }

        # For takeoff, check if ready to arm
        if mission_type == Mission.TAKE_OFF.value:
            if not self.drone_config.is_ready_to_arm:
                raw_summary = getattr(self.drone_config, 'readiness_summary', '')
                readiness_summary = raw_summary.strip() if isinstance(raw_summary, str) else ''
                raw_blockers = getattr(self.drone_config, 'preflight_blockers', [])
                blockers = raw_blockers if isinstance(raw_blockers, list) else []
                if blockers:
                    detail = " | ".join(
                        str(blocker.get('message', '')).strip()
                        for blocker in blockers[:3]
                        if str(blocker.get('message', '')).strip()
                    )
                else:
                    detail = readiness_summary
                if not detail:
                    detail = 'Check live readiness report for current PX4 preflight blockers.'
                return {
                    'valid': False,
                    'message': 'Drone is not ready to arm (pre-flight checks not passed)',
                    'error_code': CommandErrorCode.NOT_READY_TO_ARM.value,
                    'detail': detail
                }

        if mission_type == Mission.PRECISION_MOVE.value and not self.drone_config.is_armed:
            return {
                'valid': False,
                'message': 'PRECISION_MOVE requires an armed airborne drone',
                'error_code': CommandErrorCode.NOT_ARMED.value,
            }

        return {'valid': True, 'message': 'State preconditions met'}

    @staticmethod
    def _allowed_override_missions() -> set[int]:
        """Commands that are allowed to replace a queued or executing mission."""
        return {
            Mission.NONE.value,
            Mission.KILL_TERMINATE.value,
            Mission.LAND.value,
            Mission.HOLD.value,
            Mission.RETURN_RTL.value,
            Mission.PRECISION_MOVE.value,
            Mission.SWARM_TRAJECTORY.value,
        }

    def _find_active_command_by_id(self, command_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Return known active command metadata for duplicate-delivery idempotency."""
        if not command_id:
            return None

        current_command_id = getattr(self.drone_config, 'current_command_id', None)
        if current_command_id == command_id:
            return {
                'mission_type': int(self.drone_config.mission),
                'trigger_time': int(getattr(self.drone_config, 'trigger_time', 0) or 0),
                'state': int(self.drone_config.state),
                'phase': 'pending',
            }

        drone_setup = getattr(self.drone_config, 'drone_setup', None)
        running_processes = getattr(drone_setup, 'running_processes', None) if drone_setup else None
        if not isinstance(running_processes, dict):
            running_processes = {}

        for record in running_processes.values():
            if getattr(record, 'command_id', None) == command_id:
                return {
                    'mission_type': int(self.drone_config.mission),
                    'trigger_time': 0,
                    'state': int(self.drone_config.state),
                    'phase': 'executing',
                }

        get_recent_command_record = getattr(drone_setup, 'get_recent_command_record', None) if drone_setup else None
        if callable(get_recent_command_record):
            recent_record = get_recent_command_record(command_id)
            if isinstance(recent_record, dict):
                return recent_record

        return None

    async def _cancel_active_or_pending_command(self, *, had_active_command: bool) -> tuple[int, str]:
        """Clear the current mission state and report a successful cancel command."""
        message = (
            "Cancel command accepted; active mission cleared."
            if had_active_command
            else "Cancel command accepted; there was no active mission to clear."
        )
        drone_setup = getattr(self.drone_config, 'drone_setup', None)

        if drone_setup and hasattr(drone_setup, 'cancel_active_command'):
            await drone_setup.cancel_active_command(message)
        else:
            self.drone_config.mission = Mission.NONE.value
            self.drone_config.state = State.IDLE.value
            self.drone_config.trigger_time = 0
            self.drone_config.current_command_id = None

        return State.IDLE.value, message

    def _build_acceptance_message(
        self,
        mission_name: str,
        trigger_time: int,
        superseded_pending_command: bool = False,
    ) -> str:
        """Build a precise operator-facing ACK message."""
        now_s = int(time.time())
        if trigger_time > now_s:
            message = f"Command {mission_name} accepted and queued for trigger at {trigger_time}"
        else:
            message = f"Command {mission_name} accepted for immediate execution"

        if superseded_pending_command:
            return f"{message}; previous pending command was superseded"

        return message

    @staticmethod
    def _build_idempotent_acceptance_message(mission_name: str, phase: str) -> str:
        if phase == "executing":
            return f"Command {mission_name} was already active on this drone; returning idempotent ACK while execution continues"
        if phase == "completed":
            return f"Command {mission_name} already completed on this drone; returning idempotent ACK without re-executing it"
        if phase == "failed":
            return f"Command {mission_name} already reached a terminal failure on this drone; returning idempotent ACK without re-executing it"
        if phase == "superseded":
            return f"Command {mission_name} was already superseded on this drone; returning idempotent ACK without re-executing it"
        return f"Command {mission_name} was already queued on this drone; returning idempotent ACK"

    async def _report_pending_command_superseded(
        self,
        command_id: str,
        override_mission_type: int,
    ) -> None:
        """Report that a queued command was replaced before execution started."""
        if not command_id:
            return

        try:
            mission_name = Mission(override_mission_type).name
        except ValueError:
            mission_name = f"MISSION_{override_mission_type}"

        drone_setup = getattr(self.drone_config, 'drone_setup', None)
        if drone_setup and hasattr(drone_setup, '_report_execution_to_gcs'):
            await drone_setup._report_execution_to_gcs(
                command_id=command_id,
                success=False,
                error_message=f"Superseded by a newer command ({mission_name}) before execution started",
                duration_ms=0,
            )
            return

        gcs_ip = self.params.GCS_IP
        if not isinstance(gcs_ip, str) or not gcs_ip:
            logger.warning("GCS_IP not configured, cannot report superseded pending command")
            return

        try:
            payload = {
                'command_id': command_id,
                'hw_id': str(self.drone_config.hw_id),
                'success': False,
                'error_message': f"Superseded by a newer command ({mission_name}) before execution started",
                'duration_ms': 0,
            }
            url = f"http://{gcs_ip}:{self.params.gcs_api_port}{GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE}"
            response = await asyncio.to_thread(requests.post, url, json=payload, timeout=5)
            if response.status_code == 200:
                logger.info(f"Reported superseded pending command {command_id[:8]}...")
            else:
                logger.warning(f"Failed to report superseded pending command: HTTP {response.status_code}")
        except requests.RequestException as e:
            logger.warning(f"Failed to report superseded pending command: {e}")

    # ========================================================================
    # Helper Methods (preserved from Flask version)
    # ========================================================================

    def load_swarm(self, file_path):
        """Load swarm data from CSV file"""
        return load_csv(file_path)

    def _get_origin_from_gcs(self):
        """Fetches the origin coordinates from the GCS."""
        try:
            gcs_ip = self.params.GCS_IP
            if not gcs_ip:
                logger.error("GCS IP not configured in Params")
                return None

            gcs_port = self.params.gcs_api_port
            gcs_url = f"http://{gcs_ip}:{gcs_port}"

            response = requests.get(f"{gcs_url}{GCS_ORIGIN_BOOTSTRAP_ROUTE}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'lat' in data and 'lon' in data:
                    # Reset error flag on success
                    DroneAPIServer._origin_fetch_error_logged = False
                    return {'lat': float(data['lat']), 'lon': float(data['lon'])}
            else:
                logger.warning(f"GCS responded with status code {response.status_code}")
            return None
        except requests.RequestException as e:
            # Log once to avoid spam - GCS might not be running yet
            if not DroneAPIServer._origin_fetch_error_logged:
                DroneAPIServer._origin_fetch_error_logged = True
                logger.warning(f"Origin fetch from GCS failed (will retry): {e}")
            return None

    def _execute_git_command(self, command):
        """
        Helper method to execute a Git command and return the output.
        """
        return subprocess.check_output(command).strip().decode('utf-8')

    def _get_network_info(self):
        """
        Fetch the current network information (Wi-Fi and Wired LAN).
        Returns a dictionary containing Wi-Fi and Ethernet information if available.
        """
        try:
            wifi_info = subprocess.check_output(
                ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"],
                universal_newlines=True
            )

            eth_connection = subprocess.check_output(
                ["nmcli", "-t", "-f", "device,state,connection", "device", "status"],
                universal_newlines=True
            )

            network_info = {
                "wifi": None,
                "ethernet": None,
                "timestamp": int(time.time() * 1000)
            }

            # Extract Wi-Fi details
            active_wifi_ssid = None
            active_wifi_signal = None
            for line in wifi_info.splitlines():
                parts = line.split(':')
                if len(parts) >= 3 and parts[0].lower() == 'yes':
                    active_wifi_ssid = parts[1]
                    active_wifi_signal = parts[2]
                    break

            if active_wifi_ssid:
                if active_wifi_signal.isdigit():
                    signal_strength = int(active_wifi_signal)
                else:
                    signal_strength = "Unknown"

                network_info["wifi"] = {
                    "ssid": active_wifi_ssid,
                    "signal_strength_percent": signal_strength
                }

            # Extract Ethernet details
            active_eth_connection = None
            active_eth_device = None
            for line in eth_connection.splitlines():
                parts = line.split(':')
                if len(parts) >= 3 and parts[1].lower() == 'connected' and 'eth' in parts[0].lower():
                    active_eth_device = parts[0]
                    active_eth_connection = parts[2]
                    break

            if active_eth_device and active_eth_connection:
                network_info["ethernet"] = {
                    "interface": active_eth_device,
                    "connection_name": active_eth_connection
                }

            return network_info

        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            # nmcli not available - expected in SITL/Docker environments
            # Log once to avoid spam
            if not DroneAPIServer._network_info_error_logged:
                DroneAPIServer._network_info_error_logged = True
                if Params.sim_mode:
                    logger.debug(f"nmcli not available (expected in SITL): {e}")
                else:
                    logger.warning(f"Network info unavailable: {e}")
            return {
                "wifi": None,
                "ethernet": None,
                "timestamp": int(time.time() * 1000)
            }
        except Exception as e:
            # Unexpected errors still logged, but only once
            if not DroneAPIServer._network_info_error_logged:
                DroneAPIServer._network_info_error_logged = True
                logger.warning(f"Unexpected error getting network info: {e}")
            return {
                "wifi": None,
                "ethernet": None,
                "timestamp": int(time.time() * 1000)
            }

    def run(self):
        """
        Run the FastAPI application using uvicorn.
        Equivalent to Flask's app.run()
        """
        host = '0.0.0.0'
        port = self.params.drone_api_port

        # Uvicorn configuration
        config = uvicorn.Config(
            app=self.app,
            host=host,
            port=port,
            log_level="info" if self.params.env_mode == 'development' else "warning",
            access_log=self.params.env_mode == 'development',
            reload=False  # No auto-reload for embedded systems
        )

        server = uvicorn.Server(config)
        server.run()


# Backward compatibility: alias for old name
FlaskHandler = DroneAPIServer
