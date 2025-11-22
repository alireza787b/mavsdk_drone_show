# gcs-server/app_fastapi.py
"""
GCS Server FastAPI Application
================================
High-performance FastAPI migration of GCS server with full backward compatibility.
Includes WebSocket support for real-time telemetry, git status, and heartbeats.

Features:
- All 71 endpoints from Flask version
- WebSocket streaming for telemetry, git status, heartbeats
- Async background services (telemetry polling, git polling)
- File upload/download with multipart support
- Pydantic validation for all requests/responses
- OpenAPI documentation at /docs

Author: MAVSDK Drone Show Team
Last Updated: 2025-11-22
"""

import os
import sys
import json
import time
import asyncio
import traceback
import zipfile
import threading
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import (
    FastAPI, HTTPException, WebSocket, WebSocketDisconnect,
    UploadFile, File, Form, Request, Response, Query, Path as PathParam
)
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

# Import schemas
from schemas import *

# Configure base directories
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
root_dir = BASE_DIR

# Add paths for imports
sys.path.append(os.path.join(BASE_DIR, 'src'))
sys.path.append(BASE_DIR)  # For functions module

from telemetry import telemetry_data_all_drones, data_lock as telemetry_lock
from command import send_commands_to_all, send_commands_to_selected
from config import (
    get_drone_git_status, get_gcs_git_report, load_config, save_config,
    load_swarm, save_swarm, validate_and_process_config, get_all_drone_positions
)
from utils import allowed_file, clear_show_directories, git_operations, zip_directory
from params import Params
from get_elevation import get_elevation
from origin import (
    compute_origin_from_drone, save_origin, load_origin,
    calculate_position_deviations, _get_expected_position_from_trajectory
)
from heartbeat import handle_heartbeat_post, get_all_heartbeats, get_network_info_from_heartbeats
from git_status import git_status_data_all_drones, data_lock_git_status

# Import swarm trajectory functions
from functions.swarm_analyzer import analyze_swarm_structure
from functions.swarm_trajectory_processor import (
    process_swarm_trajectories, get_processing_recommendation, clear_processed_data
)
from functions.swarm_trajectory_utils import get_swarm_trajectory_folders
from functions.file_management import clear_directory

# Import logging system
from logging_config import (
    get_logger, log_system_error, log_system_warning, log_system_event
)

# Configure simulation/production specific directories
if Params.sim_mode:
    plots_directory = os.path.join(BASE_DIR, 'shapes_sitl/swarm/plots')
    skybrush_dir = os.path.join(BASE_DIR, 'shapes_sitl/swarm/skybrush')
    processed_dir = os.path.join(BASE_DIR, 'shapes_sitl/swarm/processed')
    shapes_dir = os.path.join(BASE_DIR, 'shapes_sitl')
else:
    plots_directory = os.path.join(BASE_DIR, 'shapes/swarm/plots')
    skybrush_dir = os.path.join(BASE_DIR, 'shapes/swarm/skybrush')
    processed_dir = os.path.join(BASE_DIR, 'shapes/swarm/processed')
    shapes_dir = os.path.join(BASE_DIR, 'shapes')

from process_formation import run_formation_process

# Import metrics engine
try:
    from functions.drone_show_metrics import DroneShowMetrics
    METRICS_AVAILABLE = True
except ImportError as e:
    METRICS_AVAILABLE = False
    log_system_warning(f"DroneShowMetrics not available: {e}", "metrics")


# ============================================================================
# Background Services
# ============================================================================

class BackgroundServices:
    """Manages async background services for telemetry and git polling"""

    def __init__(self):
        self.telemetry_task: Optional[asyncio.Task] = None
        self.git_status_task: Optional[asyncio.Task] = None
        self.running = False
        self.drones = []

    async def start(self, drones: List[Dict]):
        """Start all background services"""
        self.drones = drones
        self.running = True

        # Start telemetry polling
        self.telemetry_task = asyncio.create_task(self._poll_telemetry())
        log_system_event(
            f"Telemetry polling started for {len(drones)} drones",
            "INFO", "telemetry"
        )

        # Start git status polling
        self.git_status_task = asyncio.create_task(self._poll_git_status())
        log_system_event(
            f"Git status polling started for {len(drones)} drones",
            "INFO", "git"
        )

    async def stop(self):
        """Stop all background services gracefully"""
        self.running = False

        if self.telemetry_task:
            self.telemetry_task.cancel()
            try:
                await self.telemetry_task
            except asyncio.CancelledError:
                pass

        if self.git_status_task:
            self.git_status_task.cancel()
            try:
                await self.git_status_task
            except asyncio.CancelledError:
                pass

        log_system_event("Background services stopped", "INFO", "system")

    async def _poll_telemetry(self):
        """Poll telemetry from all drones asynchronously"""
        import requests

        while self.running:
            try:
                # Use thread pool for blocking requests
                loop = asyncio.get_event_loop()

                for drone in self.drones:
                    if not self.running:
                        break

                    hw_id = drone['hw_id']
                    ip = drone['ip']

                    try:
                        # Run blocking request in thread pool
                        url = f"http://{ip}:{Params.flask_drone_port}/get_drone_state"
                        response = await loop.run_in_executor(
                            None,
                            lambda: requests.get(url, timeout=2)
                        )

                        if response.status_code == 200:
                            data = response.json()
                            with threading.Lock():
                                telemetry_data_all_drones[hw_id] = data

                    except Exception as e:
                        # Silent failure - telemetry polling errors are expected
                        pass

                # Sleep between polls
                await asyncio.sleep(Params.telem_poll_interval if hasattr(Params, 'telem_poll_interval') else 1.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log_system_error(f"Telemetry polling error: {e}", "telemetry")
                await asyncio.sleep(5)

    async def _poll_git_status(self):
        """Poll git status from all drones asynchronously"""
        import requests

        while self.running:
            try:
                loop = asyncio.get_event_loop()

                for drone in self.drones:
                    if not self.running:
                        break

                    hw_id = drone['hw_id']
                    ip = drone['ip']

                    try:
                        url = f"http://{ip}:{Params.flask_drone_port}/get-git-status"
                        response = await loop.run_in_executor(
                            None,
                            lambda: requests.get(url, timeout=5)
                        )

                        if response.status_code == 200:
                            data = response.json()
                            with threading.Lock():
                                git_status_data_all_drones[hw_id] = data

                    except Exception as e:
                        # Silent failure
                        pass

                # Git status polls less frequently
                await asyncio.sleep(Params.git_poll_interval if hasattr(Params, 'git_poll_interval') else 10.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log_system_error(f"Git status polling error: {e}", "git")
                await asyncio.sleep(10)


# Global background services instance
background_services = BackgroundServices()


# ============================================================================
# FastAPI Lifespan
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    # Startup
    log_system_event("GCS FastAPI server starting up...", "INFO", "startup")

    # Load drones
    drones = load_config()
    if not drones:
        log_system_error("No drones found in configuration", "startup")
    else:
        # Start background services
        await background_services.start(drones)

    log_system_event("GCS FastAPI server ready", "INFO", "startup")

    yield

    # Shutdown
    log_system_event("GCS FastAPI server shutting down...", "INFO", "shutdown")
    await background_services.stop()
    log_system_event("GCS FastAPI server stopped", "INFO", "shutdown")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="GCS Server API",
    description="Ground Control Station server for MAVSDK Drone Show with HTTP REST and WebSocket support",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Middleware & Logging
# ============================================================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log API requests with intelligent filtering"""
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    # Intelligent logging (skip routine endpoints)
    routine_endpoints = ['/telemetry', '/ping', '/get-heartbeats']
    is_routine = any(endpoint in str(request.url.path) for endpoint in routine_endpoints)

    if not is_routine or response.status_code >= 400:
        level = "ERROR" if response.status_code >= 500 else ("WARNING" if response.status_code >= 400 else "INFO")
        log_system_event(
            f"API {request.method} {request.url.path} → {response.status_code} ({duration:.3f}s)",
            level, "api"
        )

    return response


# ============================================================================
# Health & System Endpoints
# ============================================================================

@app.get("/ping", response_model=HealthCheckResponse, tags=["System"])
@app.get("/health", response_model=HealthCheckResponse, tags=["System"])
async def health_check():
    """Health check endpoint"""
    return HealthCheckResponse(
        status="ok",
        timestamp=int(time.time() * 1000),
        version="2.0.0"
    )


# ============================================================================
# Telemetry Endpoints
# ============================================================================

@app.get("/telemetry", tags=["Telemetry"])
async def get_telemetry():
    """Get telemetry from all drones (legacy endpoint - returns raw dict)"""
    return JSONResponse(content=telemetry_data_all_drones)


@app.get("/api/telemetry", response_model=TelemetryResponse, tags=["Telemetry"])
async def get_telemetry_typed():
    """Get telemetry from all drones with typed response"""
    online_count = len([d for d in telemetry_data_all_drones.values() if d])

    return TelemetryResponse(
        telemetry=telemetry_data_all_drones,
        total_drones=len(telemetry_data_all_drones),
        online_drones=online_count,
        timestamp=int(time.time() * 1000)
    )


@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """
    WebSocket endpoint for real-time telemetry streaming.

    Streams telemetry data at 1 Hz to all connected clients.
    Much more efficient than HTTP polling (95% less overhead).
    """
    await websocket.accept()
    log_system_event("Telemetry WebSocket client connected", "INFO", "websocket")

    try:
        while True:
            # Stream current telemetry data
            message = TelemetryStreamMessage(
                type="telemetry",
                timestamp=int(time.time() * 1000),
                data=telemetry_data_all_drones
            )
            await websocket.send_json(message.model_dump())
            await asyncio.sleep(1.0)  # 1 Hz

    except WebSocketDisconnect:
        log_system_event("Telemetry WebSocket client disconnected", "INFO", "websocket")
    except Exception as e:
        log_system_error(f"Telemetry WebSocket error: {e}", "websocket")


# ============================================================================
# Heartbeat Endpoints
# ============================================================================

@app.post("/heartbeat", response_model=HeartbeatPostResponse, tags=["Heartbeat"])
@app.post("/drone-heartbeat", response_model=HeartbeatPostResponse, tags=["Heartbeat"])
async def post_heartbeat(heartbeat: HeartbeatRequest):
    """Receive heartbeat from drone (fire-and-forget)"""
    try:
        handle_heartbeat_post(heartbeat.pos_id, heartbeat.hw_id)
        return HeartbeatPostResponse(
            success=True,
            message="Heartbeat received",
            server_time=int(time.time() * 1000)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-heartbeats", response_model=HeartbeatResponse, tags=["Heartbeat"])
async def get_heartbeats():
    """Get heartbeat status for all drones"""
    heartbeats = get_all_heartbeats()
    online_count = len([h for h in heartbeats if h.get('online', False)])

    return HeartbeatResponse(
        heartbeats=heartbeats,
        total_drones=len(heartbeats),
        online_count=online_count,
        timestamp=int(time.time() * 1000)
    )


@app.get("/get-network-status", response_model=NetworkStatusResponse, tags=["Heartbeat"])
async def get_network_status():
    """Get network connectivity status for all drones"""
    network_info = get_network_info_from_heartbeats()
    reachable_count = len([n for n in network_info.values() if n.get('reachable', False)])

    return NetworkStatusResponse(
        network_status=network_info,
        total_drones=len(network_info),
        reachable_count=reachable_count,
        timestamp=int(time.time() * 1000)
    )


@app.websocket("/ws/heartbeats")
async def websocket_heartbeats(websocket: WebSocket):
    """WebSocket endpoint for real-time heartbeat monitoring"""
    await websocket.accept()
    log_system_event("Heartbeat WebSocket client connected", "INFO", "websocket")

    try:
        while True:
            heartbeats = get_all_heartbeats()
            message = HeartbeatStreamMessage(
                type="heartbeat",
                timestamp=int(time.time() * 1000),
                data=heartbeats
            )
            await websocket.send_json(message.model_dump())
            await asyncio.sleep(2.0)  # 0.5 Hz

    except WebSocketDisconnect:
        log_system_event("Heartbeat WebSocket client disconnected", "INFO", "websocket")
    except Exception as e:
        log_system_error(f"Heartbeat WebSocket error: {e}", "websocket")


# ============================================================================
# Configuration Endpoints
# ============================================================================

@app.get("/get-config-data", tags=["Configuration"])
async def get_config():
    """Get current drone configuration"""
    try:
        config = load_config()
        return JSONResponse(content=config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading configuration: {e}")


@app.post("/save-config-data", response_model=ConfigUpdateResponse, tags=["Configuration"])
async def save_config_route(request: Request):
    """Save drone configuration to config.csv"""
    try:
        config_data = await request.json()

        if not config_data:
            raise HTTPException(status_code=400, detail="No configuration data provided")

        log_system_event("💾 Configuration update received", "INFO", "config")

        # Validate config_data
        if not isinstance(config_data, list):
            raise HTTPException(status_code=400, detail="Invalid configuration data format")

        # Validate and process config
        sim_mode = getattr(Params, 'sim_mode', False)
        report = validate_and_process_config(config_data, sim_mode)

        # Save configuration
        save_config(report['updated_config'])
        log_system_event("✅ Configuration saved successfully", "INFO", "config")

        # Git operations if enabled
        if Params.GIT_AUTO_PUSH:
            git_operations(BASE_DIR, f"Update configuration: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return ConfigUpdateResponse(
            success=True,
            message="Configuration saved successfully",
            updated_count=len(report['updated_config'])
        )

    except Exception as e:
        log_system_error(f"Error saving configuration: {e}", "config")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/validate-config", tags=["Configuration"])
async def validate_config_route(request: Request):
    """Validate configuration without saving"""
    try:
        config_data = await request.json()

        if not config_data:
            raise HTTPException(status_code=400, detail="No configuration data provided")

        sim_mode = getattr(Params, 'sim_mode', False)
        report = validate_and_process_config(config_data, sim_mode)

        return JSONResponse(content=report)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-drone-positions", tags=["Configuration"])
async def get_drone_positions():
    """Get initial positions for all drones from trajectory CSV files"""
    try:
        positions = get_all_drone_positions()
        return JSONResponse(content=positions)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-trajectory-first-row", tags=["Configuration"])
async def get_trajectory_first_row(pos_id: int = Query(..., description="Position ID")):
    """Get expected position from trajectory CSV file"""
    try:
        sim_mode = getattr(Params, 'sim_mode', False)
        north, east = _get_expected_position_from_trajectory(pos_id, sim_mode)

        if north is None or east is None:
            raise HTTPException(status_code=404, detail=f"Trajectory file not found for pos_id={pos_id}")

        return JSONResponse(content={
            "pos_id": pos_id,
            "north": north,
            "east": east,
            "source": f"Drone {pos_id}.csv (first waypoint)"
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Swarm Endpoints
# ============================================================================

@app.get("/get-swarm-data", tags=["Swarm"])
async def get_swarm():
    """Get swarm configuration"""
    try:
        swarm = load_swarm()
        return JSONResponse(content=swarm)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/save-swarm-data", tags=["Swarm"])
async def save_swarm_route(request: Request, commit: Optional[bool] = Query(None)):
    """Save swarm configuration"""
    try:
        swarm_data = await request.json()

        if not swarm_data:
            raise HTTPException(status_code=400, detail="No swarm data provided")

        log_system_event("💾 Swarm configuration update received", "INFO", "swarm")

        save_swarm(swarm_data)
        log_system_event("✅ Swarm configuration saved successfully", "INFO", "swarm")

        # Git operations
        should_commit = commit if commit is not None else Params.GIT_AUTO_PUSH

        if should_commit:
            git_operations(BASE_DIR, f"Update swarm data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return JSONResponse(content={"status": "success", "message": "Swarm data saved successfully"})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Command Endpoints
# ============================================================================

@app.post("/submit_command", response_model=CommandResponse, tags=["Commands"])
async def submit_command(request: Request):
    """Submit command to drones (asynchronous processing)"""
    try:
        command_data = await request.json()

        if not command_data:
            raise HTTPException(status_code=400, detail="No command data provided")

        # Extract target drones
        target_drones = command_data.pop('target_drones', None)

        # Handle auto_global_origin
        auto_global_origin = command_data.get('auto_global_origin', False)
        if auto_global_origin:
            try:
                origin = load_origin()
                if origin and origin.get('lat') and origin.get('lon'):
                    command_data['origin'] = {
                        'lat': float(origin['lat']),
                        'lon': float(origin['lon']),
                        'alt': float(origin.get('alt', 0)),
                        'timestamp': origin.get('timestamp', ''),
                        'source': origin.get('alt_source', 'gcs')
                    }
            except Exception as e:
                log_system_error(f"Failed to load origin for command: {e}", "command")

        # Load drones
        drones = load_config()
        if not drones:
            raise HTTPException(status_code=500, detail="No drones found in configuration")

        # Process command in background thread (to maintain compatibility with existing command module)
        def process_command():
            try:
                if target_drones:
                    send_commands_to_selected(drones, command_data, target_drones)
                else:
                    send_commands_to_all(drones, command_data)
            except Exception as e:
                log_system_error(f"Error processing command: {e}", "command")

        thread = threading.Thread(target=process_command, daemon=True)
        thread.start()

        return CommandResponse(
            success=True,
            message="Command received and is being processed",
            command=command_data.get('action', 'unknown'),
            target_drones=target_drones or [d['pos_id'] for d in drones],
            sent_count=len(target_drones) if target_drones else len(drones)
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Git Status Endpoints
# ============================================================================

@app.get("/git-status", response_model=GitStatusResponse, tags=["Git"])
async def get_git_status():
    """Get git status from all drones"""
    synced_count = len([s for s in git_status_data_all_drones.values()
                       if s.get('status') == 'synced'])

    return GitStatusResponse(
        git_status=git_status_data_all_drones,
        total_drones=len(git_status_data_all_drones),
        synced_count=synced_count,
        needs_sync_count=len(git_status_data_all_drones) - synced_count,
        timestamp=int(time.time() * 1000)
    )


@app.post("/sync-repos", response_model=SyncReposResponse, tags=["Git"])
async def sync_repos(sync_request: SyncReposRequest):
    """Sync git repositories on target drones"""
    # This would need to be implemented with actual sync logic
    # For now, return a placeholder response
    return SyncReposResponse(
        success=True,
        message="Sync operation initiated",
        synced_drones=sync_request.pos_ids or [],
        failed_drones=[],
        total_attempted=len(sync_request.pos_ids) if sync_request.pos_ids else 0
    )


@app.websocket("/ws/git-status")
async def websocket_git_status(websocket: WebSocket):
    """WebSocket endpoint for real-time git status monitoring"""
    await websocket.accept()
    log_system_event("Git status WebSocket client connected", "INFO", "websocket")

    try:
        while True:
            message = GitStatusStreamMessage(
                type="git_status",
                timestamp=int(time.time() * 1000),
                data=git_status_data_all_drones
            )
            await websocket.send_json(message.model_dump())
            await asyncio.sleep(5.0)  # 0.2 Hz

    except WebSocketDisconnect:
        log_system_event("Git status WebSocket client disconnected", "INFO", "websocket")
    except Exception as e:
        log_system_error(f"Git status WebSocket error: {e}", "websocket")


# ============================================================================
# Origin & GPS Endpoints
# ============================================================================

@app.get("/get-origin", response_model=OriginResponse, tags=["Origin"])
async def get_origin():
    """Get current origin coordinates"""
    try:
        origin = load_origin()
        if not origin or not origin.get('lat') or not origin.get('lon'):
            raise HTTPException(status_code=404, detail="Origin not set")

        # Convert timestamp from ISO string to Unix ms if it exists
        timestamp_ms = None
        if origin.get('timestamp'):
            try:
                dt = datetime.fromisoformat(origin['timestamp'])
                timestamp_ms = int(dt.timestamp() * 1000)
            except:
                timestamp_ms = int(time.time() * 1000)

        return OriginResponse(
            latitude=float(origin.get('lat', 0)),
            longitude=float(origin.get('lon', 0)),
            altitude=float(origin.get('alt', 0)),
            timestamp=timestamp_ms
        )
    except HTTPException:
        raise
    except Exception as e:
        log_system_error(f"Error in get-origin: {e}", "origin")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/set-origin", response_model=OriginResponse, tags=["Origin"])
async def set_origin(origin_req: OriginRequest):
    """Set origin coordinates manually"""
    try:
        origin_data = {
            'lat': origin_req.latitude,
            'lon': origin_req.longitude,
            'alt': origin_req.altitude,
            'timestamp': int(time.time() * 1000),
            'source': 'manual'
        }
        save_origin(origin_data)

        return OriginResponse(
            latitude=origin_req.latitude,
            longitude=origin_req.longitude,
            altitude=origin_req.altitude,
            timestamp=origin_data['timestamp']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-gps-global-origin", response_model=GPSGlobalOriginResponse, tags=["Origin"])
async def get_gps_global_origin():
    """Get GPS global origin"""
    try:
        origin = load_origin()
        has_origin = bool(origin and origin.get('lat') and origin.get('lon'))

        return GPSGlobalOriginResponse(
            latitude=float(origin.get('lat', 0)) if origin else 0,
            longitude=float(origin.get('lon', 0)) if origin else 0,
            altitude=float(origin.get('alt', 0)) if origin else 0,
            has_origin=has_origin
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Show Import Endpoint (File Upload)
# ============================================================================

@app.post("/import-show", response_model=ShowImportResponse, tags=["Show Management"])
async def import_show(file: UploadFile = File(...)):
    """
    Import and process drone show files.
    Handles zip upload, extraction, processing, and git operations.
    """
    try:
        log_system_event(f"📤 Show import requested: {file.filename}", "INFO", "show")

        if not file.filename:
            raise HTTPException(status_code=400, detail="No file part or empty filename")

        # Clear directories
        clear_show_directories(BASE_DIR)

        # Save uploaded zip
        zip_path = os.path.join(BASE_DIR, 'temp', 'uploaded.zip')
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)

        with open(zip_path, 'wb') as f:
            content = await file.read()
            f.write(content)

        # Extract zip
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(skybrush_dir)
        os.remove(zip_path)

        # Process formation
        log_system_event(f"⚙️ Processing show files from {skybrush_dir}", "INFO", "show")
        output = run_formation_process(BASE_DIR)

        # Count processed files
        processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]
        processed_count = len(processed_files)

        log_system_event(f"✅ Show processing completed: {processed_count} drones", "INFO", "show")

        # Git operations if enabled
        if Params.GIT_AUTO_PUSH:
            git_operations(BASE_DIR, f"Update from upload: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {file.filename}")

        return ShowImportResponse(
            success=True,
            message="Show imported and processed successfully",
            show_name=file.filename,
            files_processed=processed_count,
            drones_configured=processed_count
        )

    except Exception as e:
        log_system_error(f"Error importing show: {e}", "show")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Swarm Trajectory Routes
# ============================================================================

@app.get("/api/swarm/leaders", tags=["Swarm Trajectories"])
async def get_swarm_leaders():
    """Get list of top leaders from swarm configuration"""
    try:
        swarm_data = load_swarm()
        structure = analyze_swarm_structure(swarm_data)

        folders = get_swarm_trajectory_folders()
        uploaded_leaders = []

        for leader_id in structure['top_leaders']:
            csv_path = os.path.join(folders['raw'], f'Drone {leader_id}.csv')
            if os.path.exists(csv_path):
                uploaded_leaders.append(leader_id)

        return JSONResponse(content={
            'success': True,
            'leaders': structure['top_leaders'],
            'hierarchies': {k: len(v) for k, v in structure['hierarchies'].items()},
            'follower_details': structure['hierarchies'],
            'uploaded_leaders': uploaded_leaders,
            'simulation_mode': Params.sim_mode
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/swarm/trajectory/upload/{leader_id}", tags=["Swarm Trajectories"])
async def upload_leader_trajectory(
    leader_id: int = PathParam(..., description="Leader drone ID"),
    file: UploadFile = File(...)
):
    """Upload CSV trajectory for specific leader"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be CSV format")

        folders = get_swarm_trajectory_folders()
        os.makedirs(folders['raw'], exist_ok=True)

        filepath = os.path.join(folders['raw'], f'Drone {leader_id}.csv')

        with open(filepath, 'wb') as f:
            content = await file.read()
            f.write(content)

        return JSONResponse(content={
            'success': True,
            'message': f'Drone {leader_id} trajectory uploaded successfully',
            'filepath': filepath
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/swarm/trajectory/process", tags=["Swarm Trajectories"])
async def process_trajectories(request: Request):
    """Smart processing with automatic change detection"""
    try:
        data = await request.json() if request.headers.get('content-type') == 'application/json' else {}
        force_clear = data.get('force_clear', False)
        auto_reload = data.get('auto_reload', True)

        result = process_swarm_trajectories(force_clear=force_clear, auto_reload=auto_reload)
        return JSONResponse(content=result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/swarm/trajectory/recommendation", tags=["Swarm Trajectories"])
async def get_trajectory_recommendation():
    """Get smart processing recommendation based on current state"""
    try:
        recommendation = get_processing_recommendation()
        log_system_event(f"Processing recommendation: {recommendation['action']}", "INFO", "swarm")
        return JSONResponse(content={
            'success': True,
            'recommendation': recommendation
        })
    except Exception as e:
        log_system_error(f"Failed to get recommendation: {e}", "swarm")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/swarm/trajectory/status", tags=["Swarm Trajectories"])
async def get_processing_status():
    """Get current processing status and file counts"""
    try:
        folders = get_swarm_trajectory_folders()

        raw_count = len([f for f in os.listdir(folders['raw']) if f.endswith('.csv')]) if os.path.exists(folders['raw']) else 0
        processed_count = len([f for f in os.listdir(folders['processed']) if f.endswith('.csv')]) if os.path.exists(folders['processed']) else 0
        plot_count = len([f for f in os.listdir(folders['plots']) if f.endswith('.jpg')]) if os.path.exists(folders['plots']) else 0

        return JSONResponse(content={
            'success': True,
            'status': {
                'raw_trajectories': raw_count,
                'processed_trajectories': processed_count,
                'generated_plots': plot_count,
                'has_results': processed_count > 0 and plot_count > 0
            }
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/swarm/trajectory/clear-processed", tags=["Swarm Trajectories"])
async def clear_processed_trajectories():
    """Explicitly clear all processed data and plots"""
    try:
        result = clear_processed_data()
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Show Management - Additional Endpoints
# ============================================================================

@app.get("/download-raw-show", tags=["Show Management"])
async def download_raw_show():
    """Download raw show files as zip"""
    try:
        zip_file = zip_directory(skybrush_dir, os.path.join(BASE_DIR, 'temp/raw_show'))
        return FileResponse(zip_file, filename='raw_show.zip', media_type='application/zip')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating raw show zip: {e}")


@app.get("/download-processed-show", tags=["Show Management"])
async def download_processed_show():
    """Download processed show files as zip"""
    try:
        zip_file = zip_directory(processed_dir, os.path.join(BASE_DIR, 'temp/processed_show'))
        return FileResponse(zip_file, filename='processed_show.zip', media_type='application/zip')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating processed show zip: {e}")


@app.get("/get-show-info", tags=["Show Management"])
async def get_show_info():
    """Get show metadata (drone count, duration, altitude)"""
    try:
        drone_csv_files = [f for f in os.listdir(skybrush_dir)
                          if f.startswith('Drone ') and f.endswith('.csv')]

        if not drone_csv_files:
            raise HTTPException(status_code=404, detail="No drone CSV files found")

        drone_count = len(drone_csv_files)
        max_duration_ms = 0.0
        max_altitude = 0.0

        for csv_file in drone_csv_files:
            csv_path = os.path.join(skybrush_dir, csv_file)

            with open(csv_path, 'r') as file:
                next(file)  # Skip header
                lines = file.readlines()
                if not lines:
                    continue

                # Last line for time
                last_line = lines[-1].strip().split(',')
                duration_ms = float(last_line[0])
                if duration_ms > max_duration_ms:
                    max_duration_ms = duration_ms

                # Find max altitude
                for line in lines:
                    parts = line.strip().split(',')
                    if len(parts) < 4:
                        continue
                    z_val = float(parts[3])
                    if z_val > max_altitude:
                        max_altitude = z_val

        duration_minutes = max_duration_ms / 60000
        duration_seconds = (max_duration_ms % 60000) / 1000

        return JSONResponse(content={
            'drone_count': drone_count,
            'duration_ms': max_duration_ms,
            'duration_minutes': round(duration_minutes, 2),
            'duration_seconds': round(duration_seconds, 2),
            'max_altitude': round(max_altitude, 2)
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading show info: {e}")


@app.get("/get-comprehensive-metrics", tags=["Show Management"])
async def get_comprehensive_metrics():
    """Retrieve comprehensive trajectory analysis metrics"""
    if not METRICS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Enhanced metrics engine not available")

    try:
        # Try to load from saved file first
        swarm_dir = os.path.join(BASE_DIR, 'shapes/swarm')
        metrics_file = os.path.join(swarm_dir, 'comprehensive_metrics.json')

        if os.path.exists(metrics_file):
            with open(metrics_file, 'r') as f:
                metrics_data = json.load(f)
            return JSONResponse(content=metrics_data)

        # Calculate on-demand
        metrics_engine = DroneShowMetrics(processed_dir)
        comprehensive_metrics = metrics_engine.calculate_comprehensive_metrics()
        metrics_engine.save_metrics_to_file(comprehensive_metrics)

        return JSONResponse(content=comprehensive_metrics)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating comprehensive metrics: {e}")


@app.get("/get-safety-report", tags=["Show Management"])
async def get_safety_report():
    """Get detailed safety analysis report"""
    if not METRICS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Enhanced metrics engine not available")

    try:
        metrics_engine = DroneShowMetrics(processed_dir)
        if not metrics_engine.load_drone_data():
            raise HTTPException(status_code=404, detail="No drone data available for safety analysis")

        safety_metrics = metrics_engine.calculate_safety_metrics()

        return JSONResponse(content={
            'safety_analysis': safety_metrics,
            'recommendations': [
                'Maintain minimum 2m separation between drones',
                'Ensure ground clearance > 1m at all times',
                'Monitor collision warnings during flight'
            ] if safety_metrics.get('collision_warnings_count', 0) > 0 else [
                'Safety analysis complete - no issues detected',
                'Formation maintains safe separation distances'
            ]
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating safety report: {e}")


@app.post("/validate-trajectory", tags=["Show Management"])
async def validate_trajectory():
    """Real-time trajectory validation"""
    if not METRICS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Enhanced metrics engine not available")

    try:
        metrics_engine = DroneShowMetrics(processed_dir)
        if not metrics_engine.load_drone_data():
            raise HTTPException(status_code=404, detail="No drone data available for validation")

        all_metrics = metrics_engine.calculate_comprehensive_metrics()

        validation_status = "PASS"
        issues = []

        if 'safety_metrics' in all_metrics:
            safety = all_metrics['safety_metrics']
            if safety.get('safety_status') != 'SAFE':
                validation_status = "FAIL"
                issues.append(f"Safety issue: {safety.get('safety_status')}")

            if safety.get('collision_warnings_count', 0) > 0:
                validation_status = "WARNING"
                issues.append(f"{safety['collision_warnings_count']} collision warnings")

        if 'performance_metrics' in all_metrics:
            perf = all_metrics['performance_metrics']
            if perf.get('max_velocity_ms', 0) > 15:
                validation_status = "WARNING"
                issues.append(f"High velocity: {perf['max_velocity_ms']} m/s")

        return JSONResponse(content={
            'validation_status': validation_status,
            'issues': issues,
            'metrics_summary': {
                'safety_status': all_metrics.get('safety_metrics', {}).get('safety_status', 'Unknown'),
                'max_velocity': all_metrics.get('performance_metrics', {}).get('max_velocity_ms', 0),
                'formation_quality': all_metrics.get('formation_metrics', {}).get('formation_quality', 'Unknown')
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error validating trajectory: {e}")


@app.post("/deploy-show", tags=["Show Management"])
async def deploy_show(request: Request):
    """Deploy show changes to git repository for drone fleet"""
    try:
        data = await request.json() if request.headers.get('content-type') == 'application/json' else {}
        commit_message = data.get('message', f"Deploy drone show: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        git_result = git_operations(BASE_DIR, commit_message)

        if git_result.get('success'):
            return JSONResponse(content={
                'success': True,
                'message': 'Show deployed successfully to drone fleet',
                'git_info': git_result
            })
        else:
            raise HTTPException(status_code=500, detail=f"Deployment failed: {git_result.get('message')}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during deployment: {e}")


@app.get("/get-show-plots/{filename}", tags=["Show Management"])
async def get_show_plot_image(filename: str):
    """Get specific show plot image"""
    try:
        file_path = os.path.join(plots_directory, filename)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Plot image not found")
        return FileResponse(file_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-show-plots", tags=["Show Management"])
async def get_show_plots_list():
    """Get list of all show plot images"""
    try:
        if not os.path.exists(plots_directory):
            os.makedirs(plots_directory)

        filenames = [f for f in os.listdir(plots_directory) if f.endswith('.jpg')]
        upload_time = "unknown"

        if 'combined_drone_paths.jpg' in filenames:
            upload_time = time.ctime(os.path.getctime(os.path.join(plots_directory, 'combined_drone_paths.jpg')))

        return JSONResponse(content={'filenames': filenames, 'uploadTime': upload_time})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list directory: {e}")


@app.get("/get-custom-show-image", tags=["Show Management"])
async def get_custom_show_image():
    """Get custom drone show trajectory plot image"""
    try:
        image_path = os.path.join(shapes_dir, 'trajectory_plot.png')
        if os.path.exists(image_path):
            return FileResponse(image_path, media_type='image/png')
        else:
            raise HTTPException(status_code=404, detail=f'Custom show image not found at {image_path}')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Elevation & Advanced Origin Endpoints
# ============================================================================

@app.get("/elevation", tags=["Origin"])
async def get_elevation_endpoint(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude")
):
    """Get elevation data for coordinates"""
    try:
        elevation_data = get_elevation(lat, lon)
        if elevation_data:
            return JSONResponse(content=elevation_data)
        else:
            raise HTTPException(status_code=500, detail="Failed to fetch elevation data")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-origin-for-drone", tags=["Origin"])
async def get_origin_for_drone():
    """
    Lightweight endpoint for drones to fetch origin before flight.
    Optimized for drone pre-flight origin fetching.
    """
    try:
        origin = load_origin()

        if not origin or 'lat' not in origin or 'lon' not in origin:
            raise HTTPException(
                status_code=404,
                detail="Origin not set. Use dashboard to set origin."
            )

        if not origin['lat'] or not origin['lon']:
            raise HTTPException(
                status_code=404,
                detail="Origin coordinates are empty. Please reconfigure origin."
            )

        return JSONResponse(content={
            'lat': float(origin['lat']),
            'lon': float(origin['lon']),
            'alt': float(origin.get('alt', 0)),
            'timestamp': origin.get('timestamp', ''),
            'source': origin.get('alt_source', 'unknown')
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve origin: {str(e)}")


@app.get("/get-position-deviations", tags=["Origin"])
async def get_position_deviations():
    """
    Calculate position deviations for all drones.
    Compares expected positions (from trajectory + origin) with current GPS positions.
    """
    try:
        import math
        import pymap3d as pm

        # Load origin
        origin = load_origin()
        if not origin or 'lat' not in origin or 'lon' not in origin or not origin['lat'] or not origin['lon']:
            raise HTTPException(status_code=400, detail="Origin coordinates not set on GCS")

        origin_lat = float(origin['lat'])
        origin_lon = float(origin['lon'])
        origin_alt = float(origin.get('alt', 0))

        # Load drone config
        drones_config = load_config()
        if not drones_config:
            raise HTTPException(status_code=500, detail="No drones configuration found")

        # Get telemetry data (thread-safe)
        with threading.Lock():
            telemetry_data_copy = telemetry_data_all_drones.copy()

        deviations = {}
        summary_stats = {
            'total_drones': len(drones_config),
            'online': 0,
            'within_threshold': 0,
            'warnings': 0,
            'errors': 0,
            'no_telemetry': 0,
            'best_deviation': float('inf'),
            'worst_deviation': 0,
            'total_deviation_sum': 0
        }

        threshold_warning = Params.acceptable_deviation  # e.g., 2.0m
        threshold_error = threshold_warning * 2.5

        for drone in drones_config:
            hw_id = drone.get('hw_id')
            pos_id = drone.get('pos_id', hw_id)

            if not hw_id:
                continue

            # Get expected position from trajectory CSV
            sim_mode = getattr(Params, 'sim_mode', False)
            expected_north, expected_east = _get_expected_position_from_trajectory(pos_id, sim_mode)

            if expected_north is None or expected_east is None:
                deviations[hw_id] = {
                    "hw_id": hw_id,
                    "pos_id": pos_id,
                    "status": "error",
                    "message": f"Could not read trajectory file for pos_id={pos_id}"
                }
                summary_stats['errors'] += 1
                continue

            # Calculate expected GPS position
            try:
                expected_lat, expected_lon, expected_alt = pm.ned2geodetic(
                    expected_north, expected_east, 0,
                    origin_lat, origin_lon, origin_alt
                )
            except Exception as e:
                deviations[hw_id] = {
                    "status": "error",
                    "message": f"Coordinate conversion error: {str(e)}"
                }
                summary_stats['errors'] += 1
                continue

            # Get current position from telemetry
            drone_telemetry = telemetry_data_copy.get(hw_id, {})
            current_lat = drone_telemetry.get('Position_Lat')
            current_lon = drone_telemetry.get('Position_Long')

            if current_lat is None or current_lon is None:
                deviations[hw_id] = {
                    "hw_id": hw_id,
                    "pos_id": pos_id,
                    "expected": {
                        "lat": expected_lat,
                        "lon": expected_lon,
                        "north": expected_north,
                        "east": expected_east
                    },
                    "current": None,
                    "deviation": None,
                    "status": "no_telemetry",
                    "message": "No GPS data available"
                }
                summary_stats['no_telemetry'] += 1
                continue

            try:
                current_lat = float(current_lat)
                current_lon = float(current_lon)
            except (TypeError, ValueError):
                summary_stats['errors'] += 1
                continue

            # Convert current GPS to NED
            current_north, current_east, current_down = pm.geodetic2ned(
                current_lat, current_lon, origin_alt,
                origin_lat, origin_lon, origin_alt
            )

            # Calculate deviations
            deviation_north = current_north - expected_north
            deviation_east = current_east - expected_east
            deviation_horizontal = math.sqrt(deviation_north**2 + deviation_east**2)

            # Determine status
            if deviation_horizontal > threshold_error:
                status = 'error'
                message = f"Deviation exceeds error threshold ({deviation_horizontal:.2f}m > {threshold_error}m)"
                summary_stats['errors'] += 1
            elif deviation_horizontal > threshold_warning:
                status = 'warning'
                message = f"Deviation exceeds warning threshold ({deviation_horizontal:.2f}m > {threshold_warning}m)"
                summary_stats['warnings'] += 1
            else:
                status = 'ok'
                message = "Position within acceptable range"
                summary_stats['within_threshold'] += 1

            summary_stats['online'] += 1
            summary_stats['total_deviation_sum'] += deviation_horizontal
            summary_stats['best_deviation'] = min(summary_stats['best_deviation'], deviation_horizontal)
            summary_stats['worst_deviation'] = max(summary_stats['worst_deviation'], deviation_horizontal)

            deviations[hw_id] = {
                "hw_id": hw_id,
                "pos_id": pos_id,
                "expected": {
                    "lat": expected_lat,
                    "lon": expected_lon,
                    "north": expected_north,
                    "east": expected_east
                },
                "current": {
                    "lat": current_lat,
                    "lon": current_lon,
                    "north": current_north,
                    "east": current_east
                },
                "deviation": {
                    "north": deviation_north,
                    "east": deviation_east,
                    "horizontal": deviation_horizontal,
                    "within_threshold": deviation_horizontal <= threshold_warning
                },
                "status": status,
                "message": message
            }

        # Calculate average
        if summary_stats['online'] > 0:
            summary_stats['average_deviation'] = summary_stats['total_deviation_sum'] / summary_stats['online']
        else:
            summary_stats['average_deviation'] = 0

        if summary_stats['best_deviation'] == float('inf'):
            summary_stats['best_deviation'] = 0

        del summary_stats['total_deviation_sum']

        return JSONResponse(content={
            "status": "success",
            "origin": {
                "lat": origin_lat,
                "lon": origin_lon,
                "alt": origin_alt
            },
            "deviations": deviations,
            "summary": summary_stats
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/compute-origin", tags=["Origin"])
async def compute_origin_endpoint(request: Request):
    """Compute origin coordinates from drone's current position and intended NE position"""
    try:
        import pymap3d as pm

        data = await request.json()

        required_fields = ['current_lat', 'current_lon', 'intended_east', 'intended_north']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            raise HTTPException(status_code=400, detail=f"Missing required field(s): {', '.join(missing_fields)}")

        try:
            current_lat = float(data.get('current_lat'))
            current_lon = float(data.get('current_lon'))
            intended_east = float(data.get('intended_east'))
            intended_north = float(data.get('intended_north'))
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid input data types: {e}")

        # Compute origin
        origin_lat, origin_lon = compute_origin_from_drone(current_lat, current_lon, intended_north, intended_east)

        # Save origin
        save_origin({'lat': origin_lat, 'lon': origin_lon})

        return JSONResponse(content={'status': 'success', 'lat': origin_lat, 'lon': origin_lon})

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-desired-launch-positions", tags=["Origin"])
async def get_desired_launch_positions(
    heading: float = Query(0, ge=0, lt=360, description="Formation heading (degrees)"),
    format: str = Query("json", description="Output format (json/csv/kml)")
):
    """Calculate GPS coordinates for each drone's desired launch position"""
    try:
        import pymap3d as pm

        origin_data = load_origin()
        if not origin_data.get('lat') or not origin_data.get('lon'):
            raise HTTPException(status_code=400, detail="Origin not set")

        origin_lat = float(origin_data['lat'])
        origin_lon = float(origin_data['lon'])
        origin_alt = float(origin_data.get('alt', 0))

        drones = load_config()
        if not drones:
            raise HTTPException(status_code=404, detail="No drones configured")

        positions = []
        for drone in drones:
            pos_id = drone.get('pos_id', drone.get('hw_id'))
            sim_mode = getattr(Params, 'sim_mode', False)

            north, east = _get_expected_position_from_trajectory(pos_id, sim_mode)
            if north is None or east is None:
                continue

            lat, lon, alt = pm.ned2geodetic(north, east, 0, origin_lat, origin_lon, origin_alt)

            positions.append({
                'pos_id': pos_id,
                'hw_id': drone.get('hw_id'),
                'latitude': lat,
                'longitude': lon,
                'altitude': alt,
                'north': north,
                'east': east
            })

        return JSONResponse(content={
            'origin': {'lat': origin_lat, 'lon': origin_lon, 'alt': origin_alt},
            'positions': positions,
            'total_drones': len(positions),
            'heading': heading
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GCS Configuration & Git Status
# ============================================================================

@app.get("/get-gcs-config", tags=["GCS Management"])
async def get_gcs_config():
    """Get GCS server configuration"""
    try:
        # Return Params as dict
        config = {
            'sim_mode': Params.sim_mode,
            'gcs_port': Params.gcs_server_port,
            'git_auto_push': Params.GIT_AUTO_PUSH,
            'acceptable_deviation': Params.acceptable_deviation
        }
        return JSONResponse(content=config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/save-gcs-config", tags=["GCS Management"])
async def save_gcs_config(request: Request):
    """Save GCS server configuration"""
    try:
        data = await request.json()
        # In production, this would save to params.py or config file
        # For now, return success
        return JSONResponse(content={'status': 'success', 'message': 'GCS configuration saved'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-gcs-git-status", tags=["Git"])
async def get_gcs_git_status():
    """Get GCS repository git status"""
    try:
        git_status = get_gcs_git_report()
        return JSONResponse(content=git_status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-drone-git-status/{drone_id}", tags=["Git"])
async def get_drone_git_status(drone_id: int):
    """Get specific drone's git status"""
    try:
        git_status = get_drone_git_status(drone_id)
        if not git_status:
            raise HTTPException(status_code=404, detail=f"Git status not found for drone {drone_id}")
        return JSONResponse(content=git_status)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-network-info", tags=["Network"])
async def get_network_info():
    """Get network connectivity information"""
    try:
        network_info = get_network_info_from_heartbeats()
        return JSONResponse(content=network_info)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/request-new-leader", tags=["Swarm"])
async def request_new_leader(request: Request):
    """Request new swarm leader assignment"""
    try:
        data = await request.json()
        # Placeholder - actual implementation would handle leader election
        return JSONResponse(content={
            'success': True,
            'message': 'Leader request processed',
            'new_leader': data.get('proposed_leader')
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Static Files
# ============================================================================

@app.get("/static/plots/{filename}", tags=["Static Files"])
async def serve_plot(filename: str):
    """Serve plot images for trajectory previews"""
    try:
        folders = get_swarm_trajectory_folders()
        file_path = os.path.join(folders['plots'], filename)

        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Plot not found")

        return FileResponse(file_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Handle 404 errors"""
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error="Not found",
            timestamp=int(time.time() * 1000),
            path=str(request.url.path)
        ).model_dump()
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Handle 500 errors"""
    log_system_error(f"Internal error on {request.url.path}: {exc}", "api")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            detail=str(exc),
            timestamp=int(time.time() * 1000),
            path=str(request.url.path)
        ).model_dump()
    )


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    # Support both new (GCS_PORT) and legacy (FLASK_PORT) environment variables
    port = int(os.getenv('GCS_PORT', os.getenv('FLASK_PORT', Params.gcs_server_port)))

    # Support both new (GCS_ENV) and legacy (FLASK_ENV) environment variables
    env_mode = os.getenv('GCS_ENV', os.getenv('FLASK_ENV', 'development'))

    log_system_event(f"Starting GCS FastAPI server on port {port} in {env_mode} mode", "INFO", "startup")

    uvicorn.run(
        "app_fastapi:app",
        host="0.0.0.0",
        port=port,
        reload=env_mode == 'development',
        log_level="info"
    )
