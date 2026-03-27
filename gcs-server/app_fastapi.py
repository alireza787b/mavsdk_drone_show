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
import shutil
import sys
import json
import time
import asyncio
import traceback
import tempfile
import zipfile
import threading
import csv
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime
from functools import partial

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
    get_drone_git_status as _config_get_drone_git_status,
    get_gcs_git_report, load_config, save_config,
    load_swarm, save_swarm, validate_and_process_config, get_all_drone_positions
)
from utils import allowed_file, clear_show_directories, git_operations, zip_directory
from params import Params
from get_elevation import get_elevation
from origin import (
    compute_origin_from_drone, save_origin, load_origin,
    calculate_position_deviations
)
from coordinate_utils import get_expected_position_from_trajectory
from heartbeat import (
    handle_heartbeat_post,
    get_all_heartbeats,
    get_network_info_from_heartbeats,
    last_heartbeats,
    last_heartbeats_lock,
)
from git_status import git_status_data_all_drones, data_lock_git_status
from command_tracker import get_command_tracker, init_command_tracker
from src import __version__ as MDS_VERSION

# Import SAR router
from sar.routes import router as sar_router

# Import swarm trajectory functions
from functions import swarm_trajectory_service
from functions.swarm_trajectory_utils import get_swarm_trajectory_folders

# Unified logging system
from mds_logging.server import (
    get_logger, log_system_error, log_system_warning, log_system_event,
    init_server_logging, log_system_startup,
)
from mds_logging import register_component

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
from request_logging import get_request_log_level

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

                    hw_id = str(drone['hw_id'])
                    ip = drone['ip']

                    try:
                        # Run blocking request in thread pool
                        url = f"http://{ip}:{Params.drone_api_port}/get_drone_state"
                        response = await loop.run_in_executor(
                            None,
                            lambda u=url: requests.get(u, timeout=Params.GCS_TELEMETRY_REQUEST_TIMEOUT_SEC)
                        )

                        if response.status_code == 200:
                            data = response.json()
                            with telemetry_lock:
                                telemetry_data_all_drones[hw_id] = _build_background_telemetry_record(hw_id, ip, data)

                    except Exception as e:
                        # Silent failure - telemetry polling errors are expected
                        pass

                # Sleep between polls
                await asyncio.sleep(Params.telem_poll_interval)

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
                        url = f"http://{ip}:{Params.drone_api_port}/get-git-status"
                        response = await loop.run_in_executor(
                            None,
                            lambda u=url: requests.get(u, timeout=Params.GCS_GIT_STATUS_REQUEST_TIMEOUT_SEC)
                        )

                        if response.status_code == 200:
                            data = response.json()
                            with data_lock_git_status:
                                git_status_data_all_drones[hw_id] = data

                    except Exception as e:
                        # Silent failure
                        pass

                # Git status polls less frequently
                await asyncio.sleep(Params.git_poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log_system_error(f"Git status polling error: {e}", "git")
                await asyncio.sleep(10)


# Global background services instance
background_services = BackgroundServices()


def _normalize_heartbeat_first_seen(value: Any) -> Optional[int]:
    """Normalize legacy heartbeat first_seen values into Unix milliseconds."""
    if value in (None, ""):
        return None

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None

    if numeric_value <= 0:
        return None

    if numeric_value < 1_000_000_000_000:
        numeric_value *= 1000.0

    return int(numeric_value)


def _build_background_telemetry_record(hw_id: Any, ip: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Keep FastAPI background telemetry aligned with the typed telemetry API contract."""
    normalized_hw_id = str(hw_id)

    with last_heartbeats_lock:
        heartbeat_data = (last_heartbeats.get(normalized_hw_id) or {}).copy()

    return {
        **data,
        "hw_id": str(data.get("hw_id", normalized_hw_id)),
        "ip": data.get("ip", ip),
        "heartbeat_last_seen": heartbeat_data.get("timestamp"),
        "heartbeat_network_info": heartbeat_data.get("network_info") or {},
        "heartbeat_first_seen": _normalize_heartbeat_first_seen(heartbeat_data.get("first_seen")),
    }


def _get_telemetry_record_for_hw_id(
    telemetry_snapshot: Dict[Any, Dict[str, Any]],
    hw_id: Any,
) -> Dict[str, Any]:
    """Return telemetry for a drone regardless of whether storage keys are ints or strings."""
    if hw_id in telemetry_snapshot:
        return telemetry_snapshot.get(hw_id) or {}

    normalized_hw_id = str(hw_id)
    if normalized_hw_id in telemetry_snapshot:
        return telemetry_snapshot.get(normalized_hw_id) or {}

    try:
        numeric_hw_id = int(normalized_hw_id)
    except (TypeError, ValueError):
        numeric_hw_id = None

    if numeric_hw_id is not None and numeric_hw_id in telemetry_snapshot:
        return telemetry_snapshot.get(numeric_hw_id) or {}

    return {}


# ============================================================================
# FastAPI Lifespan
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    # Initialize unified logging (session file, console, SSE watcher handlers)
    init_server_logging()
    register_component("gcs", "gcs", "GCS FastAPI server")

    # Startup - only runs in worker process
    mode = "Simulation" if Params.sim_mode else "Production"
    log_system_event(f"Starting GCS FastAPI server ({mode} mode)...", "INFO", "startup")
    log_system_event(f"Configuration: {Params.config_file_name}, Swarm: {Params.swarm_file_name}", "INFO", "startup")

    # Load drones
    drones = load_config()
    if not drones:
        log_system_warning("No drones found in configuration", "startup")
    else:
        log_system_event(f"Loaded {len(drones)} drone(s) from configuration", "INFO", "startup")
        # Start background services
        await background_services.start(drones)

    log_system_event("GCS FastAPI server ready - all services started", "INFO", "startup")

    # Start background log puller (no-op loop if disabled via env)
    await background_puller.start()

    yield

    # Shutdown - only runs in worker process
    log_system_event("GCS FastAPI server shutting down...", "INFO", "shutdown")
    await background_puller.stop()
    await background_services.stop()
    log_system_event("GCS FastAPI server stopped", "INFO", "shutdown")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="GCS Server API",
    description="Ground Control Station server for MAVSDK Drone Show with HTTP REST and WebSocket support",
    version=MDS_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# CORS middleware - completely permissive for development/production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,  # Allow credentials
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
    expose_headers=["*"],  # Expose all headers to the client
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Register SAR router
app.include_router(sar_router)

# Background log puller (disabled by default, enable via MDS_LOG_BACKGROUND_PULL=true)
from log_background import BackgroundLogPuller
background_puller = BackgroundLogPuller()

# Register Log API router (puller injected to avoid circular import)
from log_routes import create_log_router
app.include_router(create_log_router(puller=background_puller))


# ============================================================================
# Middleware & Logging
# ============================================================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log API requests with intelligent filtering"""
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    path = str(request.url.path)
    level = get_request_log_level(path, response.status_code)
    log_system_event(
        f"API {request.method} {path} → {response.status_code} ({duration:.3f}s)",
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
        version=MDS_VERSION
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
async def post_heartbeat(heartbeat: HeartbeatRequest, request: Request):
    """Receive heartbeat from drone (fire-and-forget)"""
    try:
        client_ip = request.client.host if request.client else None
        heartbeat_ip = heartbeat.ip.strip() if heartbeat.ip else None
        if heartbeat_ip in {"", "unknown", "n/a", "none"}:
            heartbeat_ip = None

        handle_heartbeat_post(
            pos_id=heartbeat.pos_id,
            hw_id=heartbeat.hw_id,
            detected_pos_id=heartbeat.detected_pos_id,
            ip=heartbeat_ip or client_ip,
            timestamp=heartbeat.timestamp,
            network_info=heartbeat.network_info,
        )
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
    heartbeats_dict = get_all_heartbeats()  # Returns dict {hw_id: {...}}

    # Load drone config to get IP addresses
    drones_config = load_config()
    config_lookup = {str(d['hw_id']): d for d in drones_config}

    current_time = time.time()
    heartbeat_timeout = Params.TELEMETRY_POLLING_TIMEOUT  # Default 10 seconds

    # Transform dict to list of HeartbeatData objects
    heartbeats_list = []
    for hw_id, hb_data in heartbeats_dict.items():
        # Calculate online status based on timestamp
        last_timestamp = hb_data.get('timestamp', 0)
        if last_timestamp:
            # Timestamp is in milliseconds, convert to seconds
            time_diff = current_time - (last_timestamp / 1000.0)
            is_online = time_diff < heartbeat_timeout
        else:
            is_online = False

        # Calculate latency from network_info if available
        network_info = hb_data.get('network_info', {})
        latency_ms = network_info.get('latency_ms') if network_info else None

        # Get IP from heartbeat data, fallback to config, then 'unknown'
        ip_value = hb_data.get('ip')
        if ip_value is not None:
            ip_value = str(ip_value).strip()
        if ip_value in {"", "unknown", "n/a", "none", None}:
            # Try to get from config
            ip_value = config_lookup.get(hw_id, {}).get('ip', 'unknown')

        # Ensure ip is always a string (Pydantic validation requirement)
        ip_str = str(ip_value) if ip_value else 'unknown'

        # Create HeartbeatData object
        heartbeat_obj = HeartbeatData(
            hw_id=str(hw_id),
            pos_id=int(hb_data.get('pos_id', 0)),
            ip=ip_str,
            detected_pos_id=hb_data.get('detected_pos_id'),
            last_heartbeat=last_timestamp,
            online=is_online,
            latency_ms=latency_ms
        )
        heartbeats_list.append(heartbeat_obj)

    online_count = len([h for h in heartbeats_list if h.online])

    return HeartbeatResponse(
        heartbeats=heartbeats_list,
        total_drones=len(heartbeats_list),
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
    """Save drone configuration to config.json"""
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

        # Git operations if enabled (run in executor to avoid blocking event loop)
        git_result = None
        if Params.GIT_AUTO_PUSH:
            drone_count = len(report['updated_config'])
            loop = asyncio.get_event_loop()
            git_result = await loop.run_in_executor(
                None, git_operations, BASE_DIR,
                f"config: update config.json via dashboard ({drone_count} drones updated)"
            )

        return ConfigUpdateResponse(
            success=True,
            message="Configuration saved successfully",
            updated_count=len(report['updated_config']),
            git_result=git_result
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
        north, east = get_expected_position_from_trajectory(pos_id, sim_mode)

        if north is None or east is None:
            raise HTTPException(status_code=404, detail=f"Trajectory file not found for pos_id={pos_id}")

        return JSONResponse(content={
            "pos_id": pos_id,
            "north": north,
            "east": east,
            "source": f"Drone {pos_id}.csv (first waypoint)"
        })

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Swarm Endpoints
# ============================================================================

def _normalize_swarm_hw_id(value):
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _extract_swarm_assignments(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("assignments"), list):
        return payload["assignments"]
    return None


def _would_create_swarm_cycle(assignments, hw_id, follow):
    normalized_hw_id = _normalize_swarm_hw_id(hw_id)
    normalized_follow = _normalize_swarm_hw_id(follow)
    if normalized_hw_id is None or normalized_follow is None:
        return False

    follow_map = {}
    for entry in assignments:
        entry_hw_id = _normalize_swarm_hw_id(entry.get("hw_id"))
        if entry_hw_id is None:
            continue
        try:
            follow_map[entry_hw_id] = int(entry.get("follow", 0))
        except (TypeError, ValueError):
            follow_map[entry_hw_id] = 0

    follow_map[normalized_hw_id] = normalized_follow

    visited = {normalized_hw_id}
    current = normalized_follow
    while current > 0:
        if current in visited:
            return True
        visited.add(current)
        current = int(follow_map.get(current, 0) or 0)

    return False


def _validate_swarm_cycle_constraints(payload):
    assignments = _extract_swarm_assignments(payload)
    if assignments is None:
        return

    known_hw_ids = {
        _normalize_swarm_hw_id(entry.get("hw_id"))
        for entry in assignments
    }
    known_hw_ids.discard(None)

    for entry in assignments:
        hw_id = _normalize_swarm_hw_id(entry.get("hw_id"))
        try:
            follow = int(entry.get("follow", 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="follow must be zero or a valid leader hw_id")

        if hw_id is None:
            raise HTTPException(status_code=400, detail="Each swarm assignment requires a valid positive hw_id")
        if follow < 0:
            raise HTTPException(status_code=400, detail="follow must be zero or a valid leader hw_id")
        if follow == hw_id:
            raise HTTPException(status_code=400, detail=f"A drone cannot follow itself (hw_id={hw_id})")
        if follow > 0 and follow not in known_hw_ids:
            raise HTTPException(status_code=400, detail=f"Leader hw_id={follow} is not present in swarm config")
        if _would_create_swarm_cycle(assignments, hw_id, follow):
            raise HTTPException(status_code=400, detail=f"Follow update would create a cycle for hw_id={hw_id}")

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

        _validate_swarm_cycle_constraints(swarm_data)

        log_system_event("💾 Swarm configuration update received", "INFO", "swarm")

        save_swarm(swarm_data)
        log_system_event("✅ Swarm configuration saved successfully", "INFO", "swarm")

        # Git operations
        should_commit = commit if commit is not None else Params.GIT_AUTO_PUSH
        git_result = None

        if should_commit:
            loop = asyncio.get_event_loop()
            git_result = await loop.run_in_executor(
                None, git_operations, BASE_DIR, "config: update swarm.json via dashboard"
            )

        return JSONResponse(content={
            "status": "success",
            "message": "Swarm data saved successfully",
            "git_result": git_result
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Command Endpoints
# ============================================================================

@app.post("/submit_command", response_model=SubmitCommandResponse, tags=["Commands"])
async def submit_command(request: Request):
    """
    Submit command to drones with tracking.

    Returns a command_id that can be used to track the command's progress via
    GET /command/{command_id} endpoint.
    """
    try:
        command_data = await request.json()

        if not command_data:
            raise HTTPException(status_code=400, detail="No command data provided")

        # Log command reception
        mission_type = command_data.get('missionType', 'unknown')
        trigger_time = command_data.get('triggerTime', '0')
        operator_label = command_data.get('operatorLabel')
        log_suffix = f", operatorLabel={operator_label}" if operator_label else ""
        log_system_event(
            f"Command received: missionType={mission_type}, triggerTime={trigger_time}{log_suffix}",
            "INFO",
            "command",
        )

        # Extract target drones
        target_drones = command_data.pop('target_drones', None)
        normalized_target_ids = {str(target_id) for target_id in target_drones} if target_drones else None

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

        # Determine actual target drone list
        if normalized_target_ids:
            actual_targets = [
                d for d in drones
                if str(d.get('hw_id')) in normalized_target_ids or str(d.get('pos_id')) in normalized_target_ids
            ]
        else:
            actual_targets = drones

        target_hw_ids = [str(d['hw_id']) for d in actual_targets]

        # Create tracked command
        tracker = get_command_tracker()
        try:
            mission_type_int = int(mission_type) if mission_type != 'unknown' else 0
        except (ValueError, TypeError):
            mission_type_int = 0

        command_id = await tracker.create_command(
            mission_type=mission_type_int,
            target_drones=target_hw_ids,
            params={
                'triggerTime': trigger_time,
                **{k: v for k, v in command_data.items() if k not in ['missionType', 'triggerTime']}
            }
        )

        # Add command_id to the data sent to drones so they can report back
        command_data['command_id'] = command_id

        # Execute command synchronously - send_commands_to_all already uses ThreadPoolExecutor
        # This ensures ACKs are recorded before response is returned (no race condition)
        if normalized_target_ids:
            results = send_commands_to_selected(drones, command_data, target_hw_ids)
        else:
            results = send_commands_to_all(drones, command_data)

        # Mark as submitted and record ACKs synchronously
        await tracker.mark_submitted(command_id)

        for drone_id, result in results.get('results', {}).items():
            category = result.get('category', 'error')
            if result.get('success'):
                await tracker.record_ack(
                    command_id, drone_id,
                    category='accepted',
                    message='HTTP 200 received'
                )
            elif category == 'offline':
                # Drone unreachable - neutral, not an error
                await tracker.record_ack(
                    command_id, drone_id,
                    category='offline',
                    message=result.get('error', 'Drone unreachable'),
                    error_code='E304'  # DRONE_OFFLINE
                )
            elif category == 'rejected':
                # Drone actively rejected
                await tracker.record_ack(
                    command_id, drone_id,
                    category='rejected',
                    message=result.get('error', 'Drone rejected command'),
                    error_code='E303'  # HTTP_ERROR
                )
            else:
                # Unexpected error
                await tracker.record_ack(
                    command_id, drone_id,
                    category='error',
                    message=result.get('error', 'Unexpected error'),
                    error_code='E500'  # INTERNAL_ERROR
                )

        tracked_status = await tracker.get_status(command_id)

        # Build results summary for response (simple dict for immediate feedback)
        results_summary = {
            'accepted': results.get('success', 0),
            'offline': results.get('offline', 0),
            'rejected': results.get('rejected', 0),
            'errors': results.get('errors', 0)
        }

        # Get mission name for response
        from src.enums import Mission
        try:
            mission_name = Mission(mission_type_int).name
        except ValueError:
            mission_name = f"MISSION_{mission_type}"

        # Determine success based on results
        has_success = results.get('success', 0) > 0
        rejected = results.get('rejected', 0)
        errors = results.get('errors', 0)
        offline = results.get('offline', 0)
        if has_success and rejected == 0 and errors == 0 and offline == 0:
            submission_status = "submitted"
        elif has_success:
            submission_status = "partial"
        elif offline > 0 and rejected == 0 and errors == 0:
            submission_status = "offline"
        else:
            submission_status = "failed"

        return SubmitCommandResponse(
            success=has_success,  # True if at least one drone accepted
            command_id=command_id,
            status=submission_status,
            mission_type=mission_type_int,
            mission_name=mission_name,
            target_drones=target_hw_ids,
            submitted_count=results.get('success', 0),
            message=results.get('result_summary', f"Command {mission_name} sent"),
            timestamp=int(time.time() * 1000),
            results_summary=results_summary,
            ack_summary=tracked_status.get('acks') if tracked_status else None,
            tracking_status=CommandStatus(tracked_status['status']) if tracked_status else None,
            tracking_phase=CommandPhase(tracked_status['phase']) if tracked_status else None,
            tracking_outcome=CommandOutcome(tracked_status['outcome']) if tracked_status and tracked_status.get('outcome') else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        log_system_error(f"submit_command failed: {e}\n{traceback.format_exc()}", "command")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Command Tracking Endpoints
# ============================================================================

@app.get("/command/{command_id}", response_model=CommandStatusResponse, tags=["Commands"])
async def get_command_status(command_id: str = PathParam(..., description="Command UUID")):
    """
    Get detailed status of a specific command.

    Returns the command's current status including:
    - ACK summary (accepted/rejected by each drone)
    - Execution summary (success/failure by each drone)
    - Timing information (created, submitted, completed)
    - Error details if any
    """
    tracker = get_command_tracker()
    status = await tracker.get_status(command_id)

    if not status:
        raise HTTPException(
            status_code=404,
            detail=f"Command {command_id} not found"
        )

    return status


@app.get("/commands/recent", response_model=CommandListResponse, tags=["Commands"])
async def get_recent_commands(
    limit: int = Query(50, ge=1, le=200, description="Maximum commands to return"),
    status: Optional[str] = Query(None, description="Filter by status (e.g., 'completed', 'failed')"),
    mission_type: Optional[int] = Query(None, description="Filter by mission type")
):
    """
    Get recent commands with optional filtering.

    Commands are returned newest first.
    """
    tracker = get_command_tracker()

    # Parse status filter
    status_filter = None
    if status:
        try:
            status_filter = [CommandStatus(status)]
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    # Parse mission filter
    mission_filter = [mission_type] if mission_type is not None else None

    commands = await tracker.get_recent(
        limit=limit,
        status_filter=status_filter,
        mission_filter=mission_filter
    )

    return CommandListResponse(
        commands=commands,
        total=len(commands),
        timestamp=int(time.time() * 1000)
    )


@app.get("/commands/active", response_model=CommandListResponse, tags=["Commands"])
async def get_active_commands():
    """
    Get all currently active (non-terminal) commands.

    Returns commands in CREATED, SUBMITTED, or EXECUTING status.
    """
    tracker = get_command_tracker()
    commands = await tracker.get_active_commands()

    return CommandListResponse(
        commands=commands,
        total=len(commands),
        timestamp=int(time.time() * 1000)
    )


@app.get("/commands/statistics", response_model=CommandStatisticsResponse, tags=["Commands"])
async def get_command_statistics():
    """
    Get command execution statistics.

    Returns overall success rates, counts by status, and active command count.
    """
    tracker = get_command_tracker()
    stats = await tracker.get_statistics()

    return CommandStatisticsResponse(
        **stats,
        timestamp=int(time.time() * 1000)
    )


@app.post("/command/{command_id}/cancel", tags=["Commands"])
async def cancel_command(
    command_id: str = PathParam(..., description="Command UUID"),
    reason: str = Query("User cancelled", description="Cancellation reason")
):
    """
    Cancel an active command.

    Only commands in CREATED, SUBMITTED, or EXECUTING status can be cancelled.
    """
    tracker = get_command_tracker()
    success = await tracker.cancel_command(command_id, reason)

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel command {command_id} (not found or already completed)"
        )

    return {
        "success": True,
        "command_id": command_id,
        "message": f"Command cancelled: {reason}",
        "timestamp": int(time.time() * 1000)
    }


@app.post("/command/execution-result", response_model=ExecutionReportResponse, tags=["Commands"])
async def report_execution_result(report: ExecutionReportRequest):
    """
    Endpoint for drones to report command execution results.

    This is called by drones after completing (or failing) command execution.
    """
    tracker = get_command_tracker()

    success = await tracker.record_execution(
        command_id=report.command_id,
        hw_id=report.hw_id,
        success=report.success,
        error_message=report.error_message,
        exit_code=report.exit_code,
        script_output=report.script_output,
        duration_ms=report.duration_ms
    )

    if not success:
        log_system_warning(
            f"Execution report for unknown command {report.command_id} from {report.hw_id}",
            "command"
        )

    # Get updated command status
    status = await tracker.get_status(report.command_id)
    command_status = CommandStatus(status['status']) if status else CommandStatus.FAILED

    return ExecutionReportResponse(
        received=success,
        command_id=report.command_id,
        command_status=command_status,
        message="Execution result recorded" if success else "Command not found in tracker",
        timestamp=int(time.time() * 1000)
    )


@app.post("/command/execution-start", response_model=ExecutionStartResponse, tags=["Commands"])
async def report_execution_start(report: ExecutionStartRequest):
    """
    Endpoint for drones to report that command execution has actually started.

    This separates successful ACK/submission from the moment the drone begins
    acting on the command.
    """
    tracker = get_command_tracker()

    success = await tracker.record_execution_start(
        command_id=report.command_id,
        hw_id=report.hw_id,
    )

    if not success:
        log_system_warning(
            f"Execution-start report for unknown command {report.command_id} from {report.hw_id}",
            "command"
        )

    status = await tracker.get_status(report.command_id)
    command_status = CommandStatus(status['status']) if status else CommandStatus.FAILED
    command_phase = CommandPhase(status['phase']) if status else CommandPhase.TERMINAL

    return ExecutionStartResponse(
        received=success,
        command_id=report.command_id,
        command_status=command_status,
        command_phase=command_phase,
        message="Execution start recorded" if success else "Command not found in tracker",
        timestamp=int(time.time() * 1000)
    )


# ============================================================================
# Git Status Endpoints
# ============================================================================

@app.get("/git-status", response_model=GitStatusResponse, tags=["Git"])
async def get_git_status():
    """Get git status from all drones"""
    # Load drone config to get pos_id, hw_id, ip mapping
    drones_config = load_config()
    drone_map = {d['hw_id']: d for d in drones_config}

    # Transform raw git status to match DroneGitStatus schema
    transformed_git_status = {}

    with data_lock_git_status:
        for hw_id, raw_data in git_status_data_all_drones.items():
            if not raw_data:
                continue

            drone_info = drone_map.get(hw_id, {})

            # Map raw status to enum values
            raw_status = raw_data.get('status', 'unknown')
            drone_commit = raw_data.get('commit', '')
            commits_behind = raw_data.get('commits_behind', 0)
            commits_ahead = raw_data.get('commits_ahead', 0)

            if raw_status == 'clean' and commits_behind == 0 and commits_ahead == 0:
                mapped_status = GitStatus.SYNCED
            elif commits_behind > 0 and commits_ahead > 0:
                mapped_status = GitStatus.DIVERGED
            elif commits_behind > 0:
                mapped_status = GitStatus.BEHIND
            elif commits_ahead > 0:
                mapped_status = GitStatus.AHEAD
            elif raw_status == 'dirty':
                # Uncommitted local changes — not diverged, but not clean
                mapped_status = GitStatus.DIRTY
            elif raw_status == 'clean':
                mapped_status = GitStatus.SYNCED
            else:
                try:
                    mapped_status = GitStatus(raw_status)
                except ValueError:
                    mapped_status = GitStatus.UNKNOWN

            commit_hash = raw_data.get('commit', 'unknown')

            transformed_git_status[str(hw_id)] = DroneGitStatus(
                pos_id=int(drone_info.get('pos_id', hw_id)),
                hw_id=str(hw_id),
                ip=drone_info.get('ip', 'unknown'),
                branch=raw_data.get('branch', 'unknown'),
                commit=commit_hash,
                commit_message=raw_data.get('commit_message'),
                commit_date=raw_data.get('commit_date'),
                author_name=raw_data.get('author_name'),
                author_email=raw_data.get('author_email'),
                status=mapped_status,
                commits_ahead=raw_data.get('commits_ahead', 0),
                commits_behind=raw_data.get('commits_behind', 0),
                uncommitted_changes=raw_data.get('uncommitted_changes', []),
                last_check=int(time.time() * 1000),
                last_sync=None
            )

    synced_count = len([s for s in transformed_git_status.values()
                       if s.status == GitStatus.SYNCED])

    # Include GCS git status in the response
    try:
        gcs_status = get_gcs_git_report()
    except Exception:
        gcs_status = None

    return GitStatusResponse(
        git_status=transformed_git_status,
        total_drones=len(transformed_git_status),
        synced_count=synced_count,
        needs_sync_count=len(transformed_git_status) - synced_count,
        gcs_status=gcs_status,
        sync_in_progress=_sync_state["active"],
        timestamp=int(time.time() * 1000)
    )


# Module-level sync operation state (protected by _sync_lock)
_sync_state = {"active": False, "started_at": None, "results": None}
_sync_lock = asyncio.Lock()


@app.post("/sync-repos", response_model=SyncReposResponse, tags=["Git"])
async def sync_repos(sync_request: SyncReposRequest):
    """Sync git repositories on target drones by sending UPDATE_CODE command.

    Sends the UPDATE_CODE mission (103) to target drones, which triggers
    tools/update_repo_ssh.sh on each drone to pull the latest code.
    """
    async with _sync_lock:
        if _sync_state["active"]:
            return SyncReposResponse(
                success=False,
                message="A sync operation is already in progress",
                synced_drones=[],
                failed_drones=[],
                total_attempted=0
            )

    try:
        _sync_state["active"] = True
        _sync_state["started_at"] = time.time()
        _sync_state["results"] = None

        # Build UPDATE_CODE command
        branch = getattr(Params, 'GIT_BRANCH', 'main-candidate')
        command_data = {
            "missionType": 103,  # Mission.UPDATE_CODE
            "triggerTime": 0,
            "update_branch": branch,
        }

        # Load drone config
        drones_config = load_config()

        if sync_request.pos_ids:
            # Sync specific drones
            target_drones = [d for d in drones_config if int(d.get('pos_id', 0)) in sync_request.pos_ids]
            command_data["pos_ids"] = sync_request.pos_ids
        else:
            target_drones = drones_config

        if not target_drones:
            return SyncReposResponse(
                success=False,
                message="No target drones found",
                synced_drones=[],
                failed_drones=[],
                total_attempted=0
            )

        # Send UPDATE_CODE command to drones
        if sync_request.pos_ids:
            # Map pos_ids to hw_ids for send_commands_to_selected
            target_hw_ids = [str(d['hw_id']) for d in target_drones]
            results = send_commands_to_selected(drones_config, command_data, target_hw_ids)
        else:
            results = send_commands_to_all(drones_config, command_data)

        # Parse results - send_commands_to_all returns dict with 'results' dict keyed by hw_id
        synced = []
        failed = []
        hw_to_pos = {str(d['hw_id']): int(d.get('pos_id', d['hw_id'])) for d in drones_config}
        per_drone_results = results.get('results', {})
        for hw_id, drone_result in per_drone_results.items():
            pos_id = hw_to_pos.get(str(hw_id), 0)
            category = drone_result.get('category', 'error') if isinstance(drone_result, dict) else 'error'
            if category == 'accepted':
                synced.append(pos_id)
            else:
                failed.append(pos_id)

        # If no per-drone results, fall back to summary counts
        if not per_drone_results:
            success_count = results.get('success', 0)
            total_count = results.get('total', 0)
            # Can't map to specific pos_ids without per-drone results
            if success_count > 0:
                synced = [d.get('pos_id', 0) for d in target_drones[:success_count]]
            if total_count > success_count:
                failed = [d.get('pos_id', 0) for d in target_drones[success_count:]]

        _sync_state["results"] = {"synced": synced, "failed": failed}

        return SyncReposResponse(
            success=len(synced) > 0,
            message=f"Sync completed: {len(synced)} succeeded, {len(failed)} failed",
            synced_drones=synced,
            failed_drones=failed,
            total_attempted=len(target_drones)
        )

    except Exception as e:
        log_system_error(f"Sync repos failed: {e}", "git")
        return SyncReposResponse(
            success=False,
            message=f"Sync operation failed: {str(e)}",
            synced_drones=[],
            failed_drones=[],
            total_attempted=0
        )
    finally:
        _sync_state["active"] = False


@app.websocket("/ws/git-status")
async def websocket_git_status(websocket: WebSocket):
    """WebSocket endpoint for real-time git status monitoring.

    Sends the same transformed structure as the REST /git-status endpoint
    so the frontend can use either interchangeably.
    """
    await websocket.accept()
    log_system_event("Git status WebSocket client connected", "INFO", "websocket")

    try:
        while True:
            # Use the REST endpoint logic for consistent data format
            try:
                rest_response = await get_git_status()
                data = rest_response.model_dump()
            except Exception:
                data = {"git_status": {}, "total_drones": 0, "synced_count": 0,
                        "needs_sync_count": 0, "gcs_status": None, "sync_in_progress": False}

            message = GitStatusStreamMessage(
                type="git_status",
                timestamp=int(time.time() * 1000),
                data=data,
                sync_in_progress=data.get("sync_in_progress", False)
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
            except (ValueError, TypeError):
                timestamp_ms = int(time.time() * 1000)

        return OriginResponse(
            lat=float(origin.get('lat', 0)),
            lon=float(origin.get('lon', 0)),
            alt=float(origin.get('alt', 0)),
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
            'lat': origin_req.lat,
            'lon': origin_req.lon,
            'alt': origin_req.alt,
            'alt_source': origin_req.alt_source,
            'timestamp': datetime.now().isoformat(),
            'version': 2
        }
        save_origin(origin_data)

        return OriginResponse(
            lat=origin_req.lat,
            lon=origin_req.lon,
            alt=origin_req.alt,
            timestamp=int(time.time() * 1000)
        )
    except Exception as e:
        log_system_error(f"Error setting origin: {e}", "origin")
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

def _copy_directory_contents(src_dir: str, dst_dir: str) -> None:
    os.makedirs(dst_dir, exist_ok=True)
    for entry in os.listdir(src_dir):
        src_path = os.path.join(src_dir, entry)
        dst_path = os.path.join(dst_dir, entry)
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
        else:
            shutil.copy2(src_path, dst_path)


def _swarm_directory() -> str:
    return os.path.join(shapes_dir, 'swarm')


def _saved_metrics_path() -> str:
    return os.path.join(_swarm_directory(), 'comprehensive_metrics.json')


def _count_processed_drone_files(directory: str) -> int:
    if not os.path.exists(directory):
        return 0
    return len(
        [
            filename for filename in os.listdir(directory)
            if filename.startswith('Drone ') and filename.endswith('.csv')
        ]
    )


CUSTOM_SHOW_REQUIRED_COLUMNS = (
    't', 'px', 'py', 'pz',
    'vx', 'vy', 'vz',
    'ax', 'ay', 'az',
    'yaw', 'mode',
)


def _custom_show_csv_path() -> str:
    return os.path.join(shapes_dir, 'active.csv')


def _custom_show_preview_path() -> str:
    return os.path.join(shapes_dir, 'trajectory_plot.png')


def _inspect_custom_show_csv(csv_path: str) -> Dict[str, Any]:
    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        missing_columns = [column for column in CUSTOM_SHOW_REQUIRED_COLUMNS if column not in fieldnames]
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Custom CSV is missing required protocol columns: "
                    f"{', '.join(missing_columns)}"
                ),
            )

        row_count = 0
        duration_sec = 0.0
        max_altitude = 0.0
        previous_t = None
        points: List[Dict[str, float]] = []

        for line_no, row in enumerate(reader, start=2):
            if not any((value or '').strip() for value in row.values()):
                continue

            try:
                t_val = float(row['t'])
                px_val = float(row['px'])
                py_val = float(row['py'])
                pz_val = float(row['pz'])
                vx_val = float(row['vx'])
                vy_val = float(row['vy'])
                vz_val = float(row['vz'])
                ax_val = float(row['ax'])
                ay_val = float(row['ay'])
                az_val = float(row['az'])
                yaw_val = float(row['yaw'])
                mode_val = int(row['mode'])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid custom CSV row {line_no}: {exc}",
                ) from exc

            if t_val < 0:
                raise HTTPException(status_code=400, detail=f"Invalid custom CSV row {line_no}: time must be non-negative")

            if previous_t is not None and t_val < previous_t:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid custom CSV row {line_no}: time values must be non-decreasing",
                )

            previous_t = t_val
            row_count += 1
            duration_sec = max(duration_sec, t_val)
            max_altitude = max(max_altitude, -pz_val)
            points.append({
                't': t_val,
                'px': px_val,
                'py': py_val,
                'pz': pz_val,
                'vx': vx_val,
                'vy': vy_val,
                'vz': vz_val,
                'ax': ax_val,
                'ay': ay_val,
                'az': az_val,
                'yaw': yaw_val,
                'mode': mode_val,
            })

        if row_count == 0:
            raise HTTPException(status_code=400, detail="Custom CSV contains no executable trajectory rows")

        return {
            'row_count': row_count,
            'duration_sec': round(duration_sec, 2),
            'max_altitude': round(max_altitude, 2),
            'points': points,
        }


def _generate_custom_show_preview(points: List[Dict[str, float]], preview_path: str) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    times = [point['t'] for point in points]
    north_values = [point['px'] for point in points]
    east_values = [point['py'] for point in points]
    altitude_values = [-point['pz'] for point in points]

    fig, (path_ax, altitude_ax) = plt.subplots(1, 2, figsize=(13, 5.5), constrained_layout=True)

    path_ax.plot(east_values, north_values, color='#2563eb', linewidth=2.4)
    path_ax.scatter(east_values[0], north_values[0], color='#16a34a', s=60, label='Start', zorder=3)
    path_ax.scatter(east_values[-1], north_values[-1], color='#dc2626', s=60, label='End', zorder=3)
    path_ax.set_title('Launch-Frame XY Path')
    path_ax.set_xlabel('East (m)')
    path_ax.set_ylabel('North (m)')
    path_ax.grid(alpha=0.25)
    path_ax.legend(loc='best')
    path_ax.set_aspect('equal', adjustable='datalim')

    altitude_ax.plot(times, altitude_values, color='#7c3aed', linewidth=2.2)
    altitude_ax.fill_between(times, altitude_values, color='#c4b5fd', alpha=0.25)
    altitude_ax.set_title('Altitude Profile')
    altitude_ax.set_xlabel('Time (s)')
    altitude_ax.set_ylabel('Altitude above launch (m)')
    altitude_ax.grid(alpha=0.25)

    fig.suptitle('Custom CSV Preview', fontsize=14, fontweight='bold')
    fig.savefig(preview_path, dpi=150, bbox_inches='tight')
    plt.close(fig)


def _load_saved_metrics_if_current() -> Optional[Dict[str, Any]]:
    metrics_file = _saved_metrics_path()
    if not os.path.exists(metrics_file):
        return None

    try:
        with open(metrics_file, 'r', encoding='utf-8') as f:
            metrics_data = json.load(f)
    except Exception as e:
        log_system_warning(f"Failed to read saved show metrics, recalculating: {e}", "show")
        return None

    cached_count = metrics_data.get('basic_metrics', {}).get('drone_count')
    current_count = _count_processed_drone_files(processed_dir)
    try:
        cached_count = int(cached_count)
    except (TypeError, ValueError):
        cached_count = None

    if cached_count != current_count:
        log_system_warning(
            f"Saved show metrics are stale (cached drones={cached_count}, current drones={current_count}); recalculating.",
            "show",
        )
        return None

    return metrics_data


def _refresh_saved_show_metrics(show_filename: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not METRICS_AVAILABLE:
        return None

    metrics_engine = DroneShowMetrics(processed_dir)
    comprehensive_metrics = metrics_engine.calculate_comprehensive_metrics()
    metrics_engine.save_metrics_to_file(
        comprehensive_metrics,
        show_filename=show_filename,
        upload_datetime=datetime.now().isoformat(),
    )
    return comprehensive_metrics


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
        if not allowed_file(file.filename):
            raise HTTPException(status_code=400, detail="Only ZIP archives are supported")

        warnings: List[str] = []
        git_result: Optional[Dict[str, Any]] = None

        temp_root = os.path.join(BASE_DIR, 'temp')
        os.makedirs(temp_root, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="show-import-", dir=temp_root) as staging_root:
            zip_path = os.path.join(staging_root, 'uploaded.zip')
            extract_dir = os.path.join(staging_root, 'extracted')
            staging_skybrush_dir = os.path.join(staging_root, 'skybrush')
            staging_processed_dir = os.path.join(staging_root, 'processed')
            staging_plots_dir = os.path.join(staging_root, 'plots')

            os.makedirs(extract_dir, exist_ok=True)
            os.makedirs(staging_skybrush_dir, exist_ok=True)
            os.makedirs(staging_processed_dir, exist_ok=True)
            os.makedirs(staging_plots_dir, exist_ok=True)

            with open(zip_path, 'wb') as f:
                content = await file.read()
                f.write(content)

            if not zipfile.is_zipfile(zip_path):
                raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP archive")

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            extracted_csvs = sorted(path for path in Path(extract_dir).rglob('*.csv') if path.is_file())
            if not extracted_csvs:
                raise HTTPException(status_code=400, detail="ZIP archive does not contain any SkyBrush CSV files")

            basename_map: Dict[str, List[Path]] = {}
            for csv_path in extracted_csvs:
                basename_map.setdefault(csv_path.name, []).append(csv_path)

            duplicate_names = sorted(name for name, paths in basename_map.items() if len(paths) > 1)
            if duplicate_names:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "ZIP archive contains duplicate CSV filenames. "
                        f"Each drone CSV must be uniquely named. Duplicates: {duplicate_names}"
                    ),
                )

            nested_csv_count = sum(1 for csv_path in extracted_csvs if csv_path.parent != Path(extract_dir))
            if nested_csv_count:
                warnings.append(
                    f"Detected {nested_csv_count} CSV file(s) in nested archive folders; "
                    "they were flattened during import."
                )

            for csv_path in extracted_csvs:
                shutil.copy2(csv_path, os.path.join(staging_skybrush_dir, csv_path.name))

            log_system_event(f"⚙️ Processing show files from staged import ({len(extracted_csvs)} CSVs)", "INFO", "show")
            process_result = run_formation_process(
                BASE_DIR,
                skybrush_dir=staging_skybrush_dir,
                processed_dir=staging_processed_dir,
                plots_dir=staging_plots_dir,
            )
            if not process_result.get('success'):
                raise HTTPException(status_code=400, detail=process_result.get('message', 'Show processing failed'))

            clear_show_directories(BASE_DIR)
            _copy_directory_contents(staging_skybrush_dir, skybrush_dir)
            _copy_directory_contents(staging_processed_dir, processed_dir)
            _copy_directory_contents(staging_plots_dir, plots_directory)

            processed_count = len([f for f in os.listdir(processed_dir) if f.endswith('.csv')])
            plots_generated = len([f for f in os.listdir(plots_directory) if f.endswith('.jpg')])

            if METRICS_AVAILABLE:
                try:
                    _refresh_saved_show_metrics(file.filename)
                except Exception as metrics_error:
                    warnings.append(f"Metrics refresh failed: {metrics_error}")
                    log_system_warning(f"Failed to refresh show metrics after import: {metrics_error}", "show")

            log_system_event(f"✅ Show processing completed: {processed_count} drones", "INFO", "show")

            if Params.GIT_AUTO_PUSH:
                loop = asyncio.get_event_loop()
                git_result = await loop.run_in_executor(
                    None,
                    git_operations,
                    BASE_DIR,
                    f"show: import {file.filename} ({processed_count} drones)"
                )
                if not git_result.get('success'):
                    warnings.append(f"Git auto-push failed: {git_result.get('message', 'unknown error')}")

        return ShowImportResponse(
            success=True,
            message="Show imported and processed successfully",
            show_name=file.filename,
            files_processed=processed_count,
            drones_configured=processed_count,
            raw_files_found=len(extracted_csvs),
            plots_generated=plots_generated,
            warnings=warnings,
            next_steps=[
                "Review launch positions and origin in Mission Config.",
                "Confirm telemetry and readiness in Overview before launch.",
            ],
            git_info=git_result,
        )

    except Exception as e:
        log_system_error(f"Error importing show: {e}", "show")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Swarm Trajectory Routes
# ============================================================================

def _swarm_error_response(exc: swarm_trajectory_service.SwarmTrajectoryError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.message},
    )


@app.get("/api/swarm/leaders", tags=["Swarm Trajectories"])
async def get_swarm_leaders():
    """Get list of top leaders from swarm configuration"""
    try:
        return JSONResponse(content=swarm_trajectory_service.get_swarm_leaders_payload())
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to get swarm leaders: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/swarm/trajectory/upload/{leader_id}", tags=["Swarm Trajectories"])
async def upload_leader_trajectory(
    leader_id: int = PathParam(..., description="Leader drone ID"),
    file: UploadFile = File(...)
):
    """Upload CSV trajectory for specific leader"""
    try:
        payload = swarm_trajectory_service.save_uploaded_trajectory(
            leader_id=leader_id,
            filename=file.filename or "",
            content=await file.read(),
        )
        return JSONResponse(content=payload)
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to upload swarm trajectory for leader {leader_id}: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/swarm/trajectory/process", tags=["Swarm Trajectories"])
async def process_trajectories(request: Request):
    """Smart processing with automatic change detection"""
    try:
        content_type = request.headers.get("content-type", "")
        data = await request.json() if content_type.startswith("application/json") else {}
        force_clear = data.get("force_clear", False)
        auto_reload = data.get("auto_reload", True)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                swarm_trajectory_service.process_trajectories_payload,
                force_clear=force_clear,
                auto_reload=auto_reload,
            ),
        )
        return JSONResponse(content=result)
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to process swarm trajectories: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/swarm/trajectory/recommendation", tags=["Swarm Trajectories"])
async def get_trajectory_recommendation():
    """Get smart processing recommendation based on current state"""
    try:
        loop = asyncio.get_running_loop()
        payload = await loop.run_in_executor(None, swarm_trajectory_service.get_processing_recommendation_payload)
        log_system_event(f"Processing recommendation: {payload['recommendation']['action']}", "INFO", "swarm")
        return JSONResponse(content=payload)
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to get recommendation: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/swarm/trajectory/status", tags=["Swarm Trajectories"])
async def get_processing_status():
    """Get current processing status and file counts"""
    try:
        return JSONResponse(content=swarm_trajectory_service.get_processing_status_payload())
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to get swarm trajectory status: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/swarm/trajectory/clear-processed", tags=["Swarm Trajectories"])
async def clear_processed_trajectories():
    """Explicitly clear all processed data and plots"""
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, swarm_trajectory_service.clear_processed_payload)
        return JSONResponse(content=result)
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to clear processed swarm trajectories: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/swarm/trajectory/clear", tags=["Swarm Trajectories"])
async def clear_all_trajectories():
    """Clear all raw, processed, and generated swarm trajectory artifacts."""
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, swarm_trajectory_service.clear_all_payload)
        return JSONResponse(content=result)
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to clear all swarm trajectories: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/swarm/trajectory/clear-leader/{leader_id}", tags=["Swarm Trajectories"])
async def clear_leader_trajectory(
    leader_id: int = PathParam(..., description="Leader drone ID"),
):
    """Clear a leader upload together with all cluster outputs."""
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            partial(swarm_trajectory_service.clear_leader_trajectory_payload, leader_id),
        )
        return JSONResponse(content=result)
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to clear leader trajectory for drone {leader_id}: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.delete("/api/swarm/trajectory/remove/{leader_id}", tags=["Swarm Trajectories"])
async def remove_leader_trajectory(
    leader_id: int = PathParam(..., description="Leader drone ID"),
):
    """Remove a leader upload together with all cluster outputs."""
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            partial(swarm_trajectory_service.remove_leader_trajectory_payload, leader_id),
        )
        return JSONResponse(content=result)
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to remove leader trajectory for drone {leader_id}: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/swarm/trajectory/download/{drone_id}", tags=["Swarm Trajectories"])
async def download_drone_trajectory(
    drone_id: int = PathParam(..., description="Drone ID"),
):
    """Download a processed drone trajectory CSV."""
    try:
        file_path, filename = swarm_trajectory_service.get_processed_trajectory_download(drone_id)
        return FileResponse(file_path, filename=filename, media_type="text/csv")
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to download trajectory for drone {drone_id}: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/swarm/trajectory/download-kml/{drone_id}", tags=["Swarm Trajectories"])
async def download_drone_kml(
    drone_id: int = PathParam(..., description="Drone ID"),
):
    """Generate and download a KML file for a single drone trajectory."""
    try:
        loop = asyncio.get_running_loop()
        content, filename = await loop.run_in_executor(
            None,
            partial(swarm_trajectory_service.get_drone_kml_download, drone_id),
        )
        return Response(
            content=content,
            media_type="application/vnd.google-earth.kml+xml",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to generate KML for drone {drone_id}: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/swarm/trajectory/download-cluster-kml/{leader_id}", tags=["Swarm Trajectories"])
async def download_cluster_kml(
    leader_id: int = PathParam(..., description="Leader drone ID"),
):
    """Generate and download a KML file for a full cluster."""
    try:
        loop = asyncio.get_running_loop()
        content, filename = await loop.run_in_executor(
            None,
            partial(swarm_trajectory_service.get_cluster_kml_download, leader_id),
        )
        return Response(
            content=content,
            media_type="application/vnd.google-earth.kml+xml",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to generate cluster KML for leader {leader_id}: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/swarm/trajectory/clear-drone/{drone_id}", tags=["Swarm Trajectories"])
async def clear_individual_drone(
    drone_id: int = PathParam(..., description="Drone ID"),
):
    """Clear a single follower trajectory and invalidate stale plots."""
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            partial(swarm_trajectory_service.clear_individual_drone_payload, drone_id),
        )
        return JSONResponse(content=result)
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to clear trajectory for drone {drone_id}: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/swarm/trajectory/commit", tags=["Swarm Trajectories"])
async def commit_trajectory_changes(request: Request):
    """Commit and push swarm trajectory changes to git."""
    try:
        content_type = request.headers.get("content-type", "")
        data = await request.json() if content_type.startswith("application/json") else {}
        commit_message = data.get("message")

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            partial(swarm_trajectory_service.commit_trajectory_changes_payload, commit_message),
        )
        status_code = 200 if result.get("success") else 500
        return JSONResponse(status_code=status_code, content=result)
    except swarm_trajectory_service.SwarmTrajectoryError as exc:
        return _swarm_error_response(exc)
    except Exception as e:
        log_system_error(f"Failed to commit swarm trajectory changes: {e}", "swarm")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


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


@app.get("/get-custom-show-info", response_model=CustomShowInfoResponse, tags=["Show Management"])
async def get_custom_show_info():
    """Get metadata for the advanced custom CSV workflow."""
    try:
        custom_csv_path = _custom_show_csv_path()
        preview_path = _custom_show_preview_path()

        if not os.path.exists(custom_csv_path):
            raise HTTPException(status_code=404, detail="Custom CSV not found")

        inspected = _inspect_custom_show_csv(custom_csv_path)
        return JSONResponse(content={
            'exists': True,
            'filename': 'active.csv',
            'row_count': inspected['row_count'],
            'duration_sec': inspected['duration_sec'],
            'max_altitude': inspected['max_altitude'],
            'preview_exists': os.path.exists(preview_path),
            'execution_mode': 'local per-drone replay',
            'required_columns': list(CUSTOM_SHOW_REQUIRED_COLUMNS),
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading custom show info: {e}")


@app.post("/import-custom-show", response_model=CustomShowImportResponse, tags=["Show Management"])
async def import_custom_show(file: UploadFile = File(...)):
    """Upload a ready-to-execute custom CSV, validate it, and regenerate the preview."""
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file part or empty filename")
        if not file.filename.lower().endswith('.csv'):
            raise HTTPException(status_code=400, detail="Only CSV files are supported for Custom CSV mode")

        warnings: List[str] = []
        git_result: Optional[Dict[str, Any]] = None
        temp_root = os.path.join(BASE_DIR, 'temp')
        os.makedirs(temp_root, exist_ok=True)
        os.makedirs(shapes_dir, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="custom-show-import-", dir=temp_root) as staging_root:
            staged_csv_path = os.path.join(staging_root, 'active.csv')
            staged_preview_path = os.path.join(staging_root, 'trajectory_plot.png')

            with open(staged_csv_path, 'wb') as staged_csv:
                content = await file.read()
                staged_csv.write(content)

            inspected = _inspect_custom_show_csv(staged_csv_path)
            _generate_custom_show_preview(inspected['points'], staged_preview_path)

            active_csv_path = _custom_show_csv_path()
            preview_path = _custom_show_preview_path()
            if os.path.exists(active_csv_path):
                warnings.append('Existing active custom CSV was replaced.')

            shutil.copy2(staged_csv_path, active_csv_path)
            shutil.copy2(staged_preview_path, preview_path)

            if Params.GIT_AUTO_PUSH:
                loop = asyncio.get_event_loop()
                git_result = await loop.run_in_executor(
                    None,
                    git_operations,
                    BASE_DIR,
                    f"custom-show: import {file.filename} ({inspected['row_count']} samples)",
                )
                if not git_result.get('success'):
                    warnings.append(f"Git auto-push failed: {git_result.get('message', 'unknown error')}")

            return CustomShowImportResponse(
                success=True,
                message='Custom CSV validated and activated successfully',
                filename=file.filename,
                stored_as='active.csv',
                row_count=inspected['row_count'],
                duration_sec=inspected['duration_sec'],
                max_altitude=inspected['max_altitude'],
                preview_generated=True,
                warnings=warnings,
                next_steps=[
                    'Review the generated preview and confirm the path is correct.',
                    'Remember: every drone will execute the same CSV in its own local launch frame.',
                    'Use Mission Config and Overview to confirm spacing and readiness before launch.',
                ],
                git_info=git_result,
            )

    except HTTPException:
        raise
    except Exception as e:
        log_system_error(f"Error importing custom show: {e}", "show")
        raise HTTPException(status_code=500, detail=f"Error importing custom CSV: {e}")


@app.get("/get-comprehensive-metrics", tags=["Show Management"])
async def get_comprehensive_metrics():
    """Retrieve comprehensive trajectory analysis metrics"""
    if not METRICS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Enhanced metrics engine not available")

    try:
        metrics_data = _load_saved_metrics_if_current()
        if metrics_data is not None:
            return JSONResponse(content=metrics_data)

        # Calculate on-demand
        comprehensive_metrics = _refresh_saved_show_metrics()

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

        loop = asyncio.get_event_loop()
        git_result = await loop.run_in_executor(None, git_operations, BASE_DIR, commit_message)

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
        with telemetry_lock:
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
            expected_north, expected_east = get_expected_position_from_trajectory(pos_id, sim_mode)

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
            drone_telemetry = _get_telemetry_record_for_hw_id(telemetry_data_copy, hw_id)
            current_lat = drone_telemetry.get('position_lat')
            current_lon = drone_telemetry.get('position_long')

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
    """Compute origin coordinates from drone's current position and pos_id (trajectory CSV)"""
    try:
        import pymap3d as pm

        data = await request.json()

        required_fields = ['current_lat', 'current_lon', 'pos_id']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            raise HTTPException(status_code=400, detail=f"Missing required field(s): {', '.join(missing_fields)}")

        try:
            current_lat = float(data.get('current_lat'))
            current_lon = float(data.get('current_lon'))
            pos_id = data.get('pos_id')
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid input data types: {e}")

        # Get intended position from trajectory CSV (single source of truth)
        sim_mode = getattr(Params, 'sim_mode', False)
        intended_north, intended_east = get_expected_position_from_trajectory(pos_id, sim_mode)

        if intended_north is None or intended_east is None:
            raise HTTPException(
                status_code=404,
                detail=f"Could not read trajectory file for pos_id={pos_id}. Ensure trajectory CSV exists."
            )

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

            north, east = get_expected_position_from_trajectory(pos_id, sim_mode)
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
            'gcs_port': Params.gcs_api_port,
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


@app.get("/get-gcs-git-status", tags=["Git"], deprecated=True)
async def get_gcs_git_status():
    """Get GCS repository git status.

    DEPRECATED: Use GET /git-status instead, which includes gcs_status field.
    """
    try:
        git_status = get_gcs_git_report()
        return JSONResponse(content=git_status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-drone-git-status/{drone_id}", tags=["Git"], deprecated=True)
async def get_drone_git_status(drone_id: int):
    """Get specific drone's git status.

    DEPRECATED: Use GET /git-status instead, which includes all drone statuses.
    """
    try:
        git_status = _config_get_drone_git_status(drone_id)
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
    """Persist a live Smart Swarm leader reassignment for a single drone."""
    try:
        data = await request.json()

        if not data:
            raise HTTPException(status_code=400, detail="No leader update data provided")

        try:
            hw_id = int(data.get('hw_id'))
            follow = int(data.get('follow', 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="hw_id and follow must be integers")

        if hw_id <= 0:
            raise HTTPException(status_code=400, detail="hw_id must be a positive integer")
        if follow < 0:
            raise HTTPException(status_code=400, detail="follow must be zero or a valid leader hw_id")
        if follow == hw_id:
            raise HTTPException(status_code=400, detail="A drone cannot follow itself")

        swarm_data = load_swarm()
        if not swarm_data:
            raise HTTPException(status_code=404, detail="Swarm configuration is empty")

        assignment_index = next(
            (idx for idx, entry in enumerate(swarm_data) if int(entry.get('hw_id', 0)) == hw_id),
            None,
        )
        if assignment_index is None:
            raise HTTPException(status_code=404, detail=f"Swarm assignment for hw_id={hw_id} not found")

        if follow != 0 and not any(int(entry.get('hw_id', 0)) == follow for entry in swarm_data):
            raise HTTPException(status_code=400, detail=f"Leader hw_id={follow} is not present in swarm config")

        updated_assignment = dict(swarm_data[assignment_index])
        updated_assignment['follow'] = follow

        projected_swarm = list(swarm_data)
        projected_swarm[assignment_index] = updated_assignment
        _validate_swarm_cycle_constraints(projected_swarm)

        try:
            if 'offset_x' in data:
                updated_assignment['offset_x'] = float(data['offset_x'])
            if 'offset_y' in data:
                updated_assignment['offset_y'] = float(data['offset_y'])
            if 'offset_z' in data:
                updated_assignment['offset_z'] = float(data['offset_z'])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="offset_x, offset_y, and offset_z must be numeric")
        if 'frame' in data:
            frame = str(data['frame']).strip().lower()
            if frame not in {'ned', 'body'}:
                raise HTTPException(status_code=400, detail="frame must be 'ned' or 'body'")
            updated_assignment['frame'] = frame

        swarm_data[assignment_index] = updated_assignment
        save_swarm(swarm_data)
        log_system_event(
            f"Smart Swarm leader update saved for hw_id={hw_id}: follow={follow}",
            "INFO",
            "swarm",
        )

        return JSONResponse(content={
            'status': 'success',
            'message': 'Leader request processed',
            'assignment': updated_assignment
        })
    except HTTPException:
        raise
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

    # Read environment configuration
    port = int(os.getenv('GCS_PORT', Params.gcs_api_port))
    env_mode = os.getenv('GCS_ENV', 'development')
    is_dev = env_mode == 'development'

    print(f"\n{'='*60}")
    print(f"  GCS FastAPI Server")
    print(f"{'='*60}")
    print(f"  Mode:    {env_mode.upper()}")
    print(f"  Host:    0.0.0.0")
    print(f"  Port:    {port}")
    print(f"  Reload:  {'Enabled (auto-reload on file changes)' if is_dev else 'Disabled'}")
    print(f"  Config:  {Params.config_file_name}")
    print(f"  Swarm:   {Params.swarm_file_name}")
    print(f"{'='*60}\n")

    uvicorn.run(
        "app_fastapi:app",
        host="0.0.0.0",
        port=port,
        reload=is_dev,  # Only use auto-reload in development
        log_level="info" if is_dev else "warning",  # Less verbose in production
        access_log=is_dev  # Disable access logs in production (reduces noise)
    )
