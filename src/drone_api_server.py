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

import csv
import math
import os
import time
import subprocess
import logging
from typing import Dict, Any, Optional, List
from pyproj import Proj, Transformer

# FastAPI imports
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import requests
import asyncio
import json

# Project imports
from src.drone_config import DroneConfig
from functions.data_utils import safe_float, safe_get
from src.params import Params

# Base directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, Params.config_csv_name)
SWARM_FILE_PATH = os.path.join(BASE_DIR, Params.swarm_csv_name)

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
    missionType: str = Field(..., description="Mission type")
    triggerTime: Optional[str] = Field("0", description="Trigger time")
    # Add other command fields as needed
    class Config:
        extra = "allow"  # Allow additional fields for flexibility


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
    flight_mode: Any
    base_mode: Any
    system_status: Any
    is_armed: bool
    is_ready_to_arm: bool
    hdop: float
    vdop: float
    gps_fix_type: int
    satellites_visible: int
    ip: str


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
            version="2.0.0",  # FastAPI version
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
                    # Add timestamp
                    drone_state['timestamp'] = int(time.time() * 1000)
                    return drone_state
                else:
                    raise HTTPException(status_code=404, detail="Drone State not found")
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"error_in_get_drone_state: {str(e)}")

        @self.app.post(f"/{Params.send_drone_command_URI}")
        async def send_drone_command(command: CommandRequest):
            """Endpoint to send a command to the drone."""
            try:
                command_data = command.dict()
                self.drone_communicator.process_command(command_data)
                return {"status": "success", "message": "Command received"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

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
                    logging.debug(f"Retrieved home position: {home_pos_with_timestamp}")
                    return home_pos_with_timestamp
                else:
                    logging.warning("Home position requested but not set.")
                    raise HTTPException(status_code=404, detail="Home position not set")
            except HTTPException:
                raise
            except Exception as e:
                logging.error(f"Error retrieving home position: {e}")
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
                    logging.debug(f"Retrieved GPS global origin: {gps_origin_with_timestamp}")
                    return gps_origin_with_timestamp
                else:
                    logging.warning("GPS global origin requested but not set.")
                    raise HTTPException(status_code=404, detail="GPS global origin not set")
            except HTTPException:
                raise
            except Exception as e:
                logging.error(f"Error retrieving GPS global origin: {e}")
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
                    'uncommitted_changes': status.splitlines() if status else []
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

                initial_north, initial_east = self._get_expected_position_from_trajectory(pos_id)

                if initial_north is None or initial_east is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Could not read trajectory file for pos_id={pos_id}"
                    )

                # Step 4: Convert current position to NE coordinates
                current_north, current_east = self._latlon_to_ne(current_lat, current_lon, origin['lat'], origin['lon'])

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
                logging.error(f"Error in get_position_deviation: {e}")
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
                logging.error(f"Error in network-info endpoint: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get('/get-swarm-data')
        async def get_swarm():
            """Get swarm configuration data"""
            logging.info("Swarm data requested")
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
                    logging.warning("LOCAL_POSITION_NED data not yet received")
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

                logging.debug(f"Returning LOCAL_POSITION_NED: {response}")
                return response

            except HTTPException:
                raise
            except Exception as e:
                logging.error(f"Error retrieving LOCAL_POSITION_NED: {e}")
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

            logging.info(f"WebSocket client connected from {websocket.client.host}")
            logging.info(f"Active WebSocket connections: {len(self.active_websockets)}")

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
                logging.info(f"WebSocket client disconnected from {websocket.client.host}")
            except Exception as e:
                logging.error(f"WebSocket error: {e}")
            finally:
                # Clean up
                if websocket in self.active_websockets:
                    self.active_websockets.remove(websocket)
                logging.info(f"Active WebSocket connections: {len(self.active_websockets)}")

    # ========================================================================
    # Helper Methods (preserved from Flask version)
    # ========================================================================

    def load_swarm(self, file_path):
        """Load swarm data from CSV file"""
        return self.load_csv(file_path)

    def load_csv(self, file_path):
        """General function to load data from a CSV file."""
        data = []
        if not os.path.exists(file_path):
            logging.error(f"File not found: {file_path}")
            return data

        try:
            with open(file_path, mode='r') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    data.append(row)

            if not data:
                logging.warning(f"File is empty: {file_path}")
        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
        except csv.Error as e:
            logging.error(f"Error reading CSV file {file_path}: {e}")
        except Exception as e:
            logging.error(f"Unexpected error loading file {file_path}: {e}")
        return data

    def _get_origin_from_gcs(self):
        """Fetches the origin coordinates from the GCS."""
        try:
            gcs_ip = self.params.GCS_IP
            if not gcs_ip:
                logging.error("GCS IP not configured in Params")
                return None

            gcs_port = self.params.GCS_FLASK_PORT
            gcs_url = f"http://{gcs_ip}:{gcs_port}"

            response = requests.get(f"{gcs_url}/get-origin", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'lat' in data and 'lon' in data:
                    return {'lat': float(data['lat']), 'lon': float(data['lon'])}
            else:
                logging.error(f"GCS responded with status code {response.status_code}")
            return None
        except requests.RequestException as e:
            logging.error(f"Error fetching origin from GCS: {e}")
            return None

    def _latlon_to_ne(self, lat, lon, origin_lat, origin_lon):
        """Converts lat/lon to north-east coordinates relative to the origin."""
        proj_string = f"+proj=tmerc +lat_0={origin_lat} +lon_0={origin_lon} +k=1 +units=m +ellps=WGS84"
        transformer = Transformer.from_proj(
            Proj('epsg:4326'),  # Source coordinate system (WGS84)
            Proj(proj_string)   # Local tangent plane projection
        )
        east, north = transformer.transform(lat, lon)
        return north, east

    def _get_expected_position_from_trajectory(self, pos_id):
        """
        Get the expected position (starting point) from a trajectory CSV file.

        Returns:
            tuple: (north, east) coordinates from first waypoint, or (None, None) on error
        """
        try:
            base_dir = 'shapes_sitl' if self.params.sim_mode else 'shapes'
            trajectory_file = os.path.join(
                BASE_DIR,
                base_dir,
                'swarm',
                'processed',
                f"Drone {pos_id}.csv"
            )

            if not os.path.exists(trajectory_file):
                logging.error(f"Trajectory file not found: {trajectory_file}")
                return None, None

            with open(trajectory_file, 'r') as f:
                reader = csv.DictReader(f)
                first_waypoint = next(reader, None)

                if first_waypoint is None:
                    logging.error(f"Trajectory file is empty: {trajectory_file}")
                    return None, None

                expected_north = float(first_waypoint.get('px', 0))
                expected_east = float(first_waypoint.get('py', 0))

                logging.debug(
                    f"Expected position for pos_id={pos_id}: "
                    f"North={expected_north:.2f}m, East={expected_east:.2f}m "
                    f"(from {trajectory_file})"
                )

                return expected_north, expected_east

        except Exception as e:
            logging.error(f"Unexpected error reading trajectory file for pos_id={pos_id}: {e}")
            return None, None

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

        except subprocess.CalledProcessError as e:
            network_info = {
                "wifi": None,
                "ethernet": None,
                "timestamp": int(time.time() * 1000),
                "error": f"Command failed: {e}"
            }
            return network_info
        except Exception as e:
            network_info = {
                "wifi": None,
                "ethernet": None,
                "timestamp": int(time.time() * 1000),
                "error": f"Unexpected error: {e}"
            }
            return network_info

    def run(self):
        """
        Run the FastAPI application using uvicorn.
        Equivalent to Flask's app.run()
        """
        host = '0.0.0.0'
        port = self.params.drones_flask_port

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
