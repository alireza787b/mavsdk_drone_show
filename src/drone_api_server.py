# src/drone_api_server.py
"""
Drone API Server - FastAPI Implementation
==========================================
Modern async API server for drone-side HTTP and WebSocket communication.
Migrated from Flask with 100% backward compatibility + WebSocket streaming.

HTTP REST Endpoints:
- GET  /get_drone_state          - Get current drone state (snapshot)
- POST /api/send-command          - Receive command from GCS
- GET  /get-home-pos              - Get home position
- GET  /get-gps-global-origin     - Get GPS global origin
- GET  /get-git-status            - Get drone git status
- GET  /ping                      - Health check
- GET  /get-position-deviation    - Calculate position deviation
- GET  /get-network-status        - Get network information
- GET  /get-swarm-data            - Get swarm configuration
- GET  /get-local-position-ned    - Get LOCAL_POSITION_NED data

WebSocket Endpoints:
- WS   /ws/drone-state            - Real-time drone state streaming (efficient)

API Documentation:
- Interactive Docs: http://drone-ip:7070/docs
- OpenAPI Schema:   http://drone-ip:7070/openapi.json
"""

import math
import os
import time
import subprocess
from typing import Dict, Any, Optional, List

# FastAPI imports
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
import uvicorn
import requests
import asyncio
import json

from mds_logging import get_logger

logger = get_logger("drone_api")

# Project imports
from src.drone_config import DroneConfig
from src.coordinate_utils import latlon_to_ne, get_expected_position_from_trajectory
from functions.data_utils import safe_float, safe_get
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

class CommandRequest(BaseModel):
    """Command request from GCS"""
    model_config = ConfigDict(extra='allow')  # Allow additional fields for flexibility

    missionType: str = Field(..., description="Mission type")
    triggerTime: Optional[str] = Field("0", description="Trigger time")


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
    follow_mode: Any
    update_time: Any
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

        self.setup_routes()

    def set_drone_communicator(self, drone_communicator):
        """Setter for injecting the DroneCommunicator dependency after initialization."""
        self.drone_communicator = drone_communicator

    def setup_routes(self):
        """Define all API routes (same as Flask version)"""

        @self.app.get(f"/{Params.get_drone_state_URI}")
        async def get_drone_state():
            """Endpoint to retrieve the current state of the drone."""
            try:
                drone_state = self.drone_communicator.get_drone_state()
                if drone_state:
                    raw_update_time = drone_state.get('update_time')
                    try:
                        numeric_update_time = float(raw_update_time)
                    except (TypeError, ValueError):
                        numeric_update_time = 0.0

                    if numeric_update_time > 0:
                        if numeric_update_time < 1_000_000_000_000:
                            drone_state['timestamp'] = int(numeric_update_time * 1000)
                        else:
                            drone_state['timestamp'] = int(numeric_update_time)
                    else:
                        drone_state['timestamp'] = 0

                    drone_state['server_time'] = int(time.time() * 1000)
                    return drone_state
                else:
                    raise HTTPException(status_code=404, detail="Drone State not found")
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"error_in_get_drone_state: {str(e)}")

        @self.app.post(f"/{Params.send_drone_command_URI}", response_model=CommandAckResponse)
        async def send_drone_command(command: CommandRequest) -> CommandAckResponse:
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
                command_data = command.dict()
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
                mission_type = int(command_data['missionType'])
                trigger_time = int(command_data.get('triggerTime', 0))
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

                if superseded_pending_command:
                    await self._report_pending_command_superseded(
                        command_id=previous_command_id,
                        override_mission_type=mission_type,
                    )

                # Store command_id for execution tracking
                self.drone_config.current_command_id = command_id

                # Process command
                self.drone_communicator.process_command(command_data)

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

        @self.app.get('/get-home-pos')
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

        @self.app.get('/get-gps-global-origin')
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

        @self.app.get('/get-git-status')
        async def get_git_status():
            """
            Endpoint to retrieve the current Git status of the drone.
            Returns branch, commit, author, date, message, remote URL, tracking branch, and status.
            """
            try:
                # Retrieve git information
                branch = self._execute_git_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
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

        @self.app.get('/ping')
        async def ping():
            """Simple endpoint to confirm connectivity."""
            return {"status": "ok"}

        @self.app.get(f"/{Params.get_position_deviation_URI}")
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

        @self.app.get("/get-network-status")
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

        @self.app.get('/get-swarm-data')
        async def get_swarm():
            """Get swarm configuration data"""
            logger.info("Swarm data requested")
            try:
                swarm = self.load_swarm(SWARM_FILE_PATH)
                return swarm
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error loading swarm data: {e}")

        @self.app.get('/get-local-position-ned')
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

        # ====================================================================
        # WebSocket Endpoint for Real-Time Telemetry Streaming
        # ====================================================================

        @self.app.websocket("/ws/drone-state")
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
                        # Add timestamp
                        drone_state['timestamp'] = int(time.time() * 1000)

                        # Send state to client
                        await websocket.send_json(drone_state)
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
        # Check required field: missionType
        if 'missionType' not in command_data:
            return {
                'valid': False,
                'message': 'Missing required field: missionType',
                'error_code': CommandErrorCode.MISSING_MISSION_TYPE.value
            }

        # Check required field: triggerTime
        if 'triggerTime' not in command_data:
            return {
                'valid': False,
                'message': 'Missing required field: triggerTime',
                'error_code': CommandErrorCode.MISSING_TRIGGER_TIME.value
            }

        # Validate missionType format and value
        try:
            mission_type = int(command_data['missionType'])
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
                'message': f'Invalid missionType format: {command_data["missionType"]}',
                'error_code': CommandErrorCode.INVALID_FORMAT.value,
                'detail': str(e)
            }

        # Validate triggerTime format
        try:
            trigger_time = int(command_data['triggerTime'])
            if trigger_time < 0:
                return {
                    'valid': False,
                    'message': 'triggerTime must be non-negative',
                    'error_code': CommandErrorCode.INVALID_TRIGGER_TIME.value
                }
        except (ValueError, TypeError) as e:
            return {
                'valid': False,
                'message': f'Invalid triggerTime format: {command_data["triggerTime"]}',
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

        return {'valid': True, 'message': 'State preconditions met'}

    @staticmethod
    def _allowed_override_missions() -> set[int]:
        """Commands that are allowed to replace a queued or executing mission."""
        return {
            Mission.KILL_TERMINATE.value,
            Mission.LAND.value,
            Mission.HOLD.value,
            Mission.RETURN_RTL.value,
        }

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

    async def _report_pending_command_superseded(
        self,
        command_id: str,
        override_mission_type: int,
    ) -> None:
        """Report that a queued command was replaced before execution started."""
        if not command_id:
            return

        gcs_ip = self.params.GCS_IP
        if not isinstance(gcs_ip, str) or not gcs_ip:
            logger.warning("GCS_IP not configured, cannot report superseded pending command")
            return

        try:
            try:
                mission_name = Mission(override_mission_type).name
            except ValueError:
                mission_name = f"MISSION_{override_mission_type}"

            payload = {
                'command_id': command_id,
                'hw_id': str(self.drone_config.hw_id),
                'success': False,
                'error_message': f"Superseded by override command {mission_name} before execution started",
                'duration_ms': 0,
            }
            url = f"http://{gcs_ip}:{self.params.gcs_api_port}/command/execution-result"
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

            response = requests.get(f"{gcs_url}/get-origin", timeout=5)
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
