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
import threading
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
from command import (
    mission_requires_launch_armability_probe,
    probe_live_armability_for_drones,
    resolve_mission_type,
    send_commands_to_all,
    send_commands_to_selected,
)
from command_timeout_policy import estimate_command_tracking_timeout_ms
from config import (
    get_drone_git_status as _config_get_drone_git_status,
    get_gcs_git_report, load_config, save_config,
    load_swarm, save_swarm, validate_and_process_config, get_all_drone_positions
)
from utils import allowed_file, clear_show_directories, git_operations, zip_directory
from params import Params
from enums import Mission
from get_elevation import get_elevation
from origin import (
    build_desired_launch_positions_report,
    build_position_deviation_report,
    compute_origin_from_drone,
    load_origin,
    save_origin,
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
from api_routes.configuration import create_configuration_router
from api_routes.core import create_core_router
from api_routes.git_status import create_git_router
from api_routes.management import create_management_router
from api_routes.origin import create_origin_router
from api_routes.show_management import create_show_management_router
from api_routes.static_assets import create_static_assets_router
from api_routes.swarm import create_swarm_router
from api_routes.swarm_trajectory import create_swarm_trajectory_router
from show_management import (
    CUSTOM_SHOW_REQUIRED_COLUMNS,
    custom_show_csv_path,
    custom_show_preview_path,
    generate_custom_show_preview,
    inspect_custom_show_csv,
    load_saved_metrics_if_current,
    refresh_saved_show_metrics,
)

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


def _custom_show_csv_path() -> str:
    return custom_show_csv_path(shapes_dir)


def _custom_show_preview_path() -> str:
    return custom_show_preview_path(shapes_dir)


_inspect_custom_show_csv = inspect_custom_show_csv
_generate_custom_show_preview = generate_custom_show_preview


def _load_saved_metrics_if_current() -> Optional[Dict[str, Any]]:
    return load_saved_metrics_if_current(
        shapes_dir=shapes_dir,
        processed_dir=processed_dir,
        log_warning=log_system_warning,
    )


def _refresh_saved_show_metrics(show_filename: Optional[str] = None) -> Optional[Dict[str, Any]]:
    return refresh_saved_show_metrics(
        processed_dir=processed_dir,
        metrics_available=METRICS_AVAILABLE,
        metrics_engine_cls=DroneShowMetrics if METRICS_AVAILABLE else None,
        show_filename=show_filename,
    )


# ============================================================================
# Background Services
# ============================================================================

class BackgroundServices:
    """Manages async background services for telemetry and git polling"""

    def __init__(self):
        self.telemetry_task: Optional[asyncio.Task] = None
        self.git_status_task: Optional[asyncio.Task] = None
        self.command_timeout_task: Optional[asyncio.Task] = None
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

        self.command_timeout_task = asyncio.create_task(self._poll_command_timeouts())
        log_system_event("Command timeout monitoring started", "INFO", "command")

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

        if self.command_timeout_task:
            self.command_timeout_task.cancel()
            try:
                await self.command_timeout_task
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

    async def _poll_command_timeouts(self):
        """Promote stale tracked commands to terminal timeout states."""
        tracker = get_command_tracker()
        interval_sec = max(
            0.5,
            float(getattr(Params, "COMMAND_TRACKING_CHECK_INTERVAL_SEC", 1.0)),
        )

        while self.running:
            try:
                await tracker.check_timeouts()
                await asyncio.sleep(interval_sec)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log_system_error(f"Command timeout polling error: {exc}", "command")
                await asyncio.sleep(interval_sec)


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


def _normalize_update_time_ms(value: Any) -> Optional[int]:
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


def _local_mavlink_stale_threshold_ms() -> int:
    configured_timeout = getattr(Params, "LOCAL_MAVLINK_STALE_TIMEOUT_SEC", None)
    if configured_timeout is None:
        configured_timeout = (
            max(1, int(getattr(Params, "LOCAL_MAVLINK_TIMEOUT_SEC", 5)))
            * max(1, int(getattr(Params, "LOCAL_MAVLINK_RECONNECT_AFTER_TIMEOUTS", 3)))
        )

    return max(1000, int(float(configured_timeout) * 1000))


def _build_stale_background_blocker(message: str, timestamp_ms: int) -> Dict[str, Any]:
    return {
        "source": "telemetry",
        "severity": "warning",
        "message": message,
        "timestamp": timestamp_ms,
    }


def _build_background_telemetry_record(hw_id: Any, ip: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Keep FastAPI background telemetry aligned with the typed telemetry API contract."""
    normalized_hw_id = str(hw_id)
    now_ms = int(time.time() * 1000)
    stale_threshold_ms = _local_mavlink_stale_threshold_ms()

    with last_heartbeats_lock:
        heartbeat_data = (last_heartbeats.get(normalized_hw_id) or {}).copy()

    record = {
        **data,
        "hw_id": str(data.get("hw_id", normalized_hw_id)),
        "ip": data.get("ip", ip),
        "telemetry_available": data.get("telemetry_available", True),
        "telemetry_error": data.get("telemetry_error"),
        "heartbeat_last_seen": heartbeat_data.get("timestamp"),
        "heartbeat_network_info": heartbeat_data.get("network_info") or {},
        "heartbeat_first_seen": _normalize_heartbeat_first_seen(heartbeat_data.get("first_seen")),
    }

    update_time_ms = _normalize_update_time_ms(record.get("update_time"))
    telemetry_age_ms = (now_ms - update_time_ms) if update_time_ms is not None else None
    record["telemetry_last_update_age_ms"] = telemetry_age_ms
    record["telemetry_stale_threshold_ms"] = stale_threshold_ms

    if update_time_ms is None:
        record["telemetry_available"] = False
        record["telemetry_error"] = record.get("telemetry_error") or "Waiting for PX4 telemetry."
        return record

    if telemetry_age_ms is not None and telemetry_age_ms > stale_threshold_ms:
        stale_message = (
            f"Local MAVLink telemetry is stale ({telemetry_age_ms / 1000.0:.1f}s since last update). "
            "Readiness is currently unavailable."
        )
        record.update({
            "telemetry_available": False,
            "telemetry_error": stale_message,
            "is_ready_to_arm": False,
            "readiness_status": "unknown",
            "readiness_summary": stale_message,
            "preflight_blockers": [_build_stale_background_blocker(stale_message, now_ms)],
            "preflight_warnings": [],
            "preflight_last_update": now_ms,
        })

    return record


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


def _estimate_max_target_relative_altitude_m(
    drones: List[Dict[str, Any]],
    target_hw_ids: List[int],
) -> Optional[float]:
    """Best-effort relative altitude hint for LAND / RTL tracker timeout sizing."""
    if not target_hw_ids:
        return None

    import requests

    drone_by_hw_id: Dict[int, Dict[str, Any]] = {}
    for drone in drones:
        try:
            drone_by_hw_id[int(drone.get("hw_id"))] = drone
        except (TypeError, ValueError):
            continue

    with telemetry_lock:
        telemetry_snapshot = {
            key: (dict(value) if isinstance(value, dict) else value)
            for key, value in telemetry_data_all_drones.items()
        }

    request_timeout = max(
        0.2,
        min(
            float(getattr(Params, "GCS_TELEMETRY_REQUEST_TIMEOUT_SEC", 2.0)),
            1.0,
        ),
    )
    max_relative_altitude_m: Optional[float] = None

    for target_hw_id in target_hw_ids:
        telemetry = _get_telemetry_record_for_hw_id(telemetry_snapshot, target_hw_id)
        try:
            current_altitude_m = float(telemetry.get("position_alt"))
        except (TypeError, ValueError):
            continue

        try:
            telemetry_relative_altitude_m = float(telemetry.get("relative_altitude_m"))
        except (TypeError, ValueError):
            telemetry_relative_altitude_m = None

        if telemetry_relative_altitude_m is not None:
            relative_altitude_m = max(0.0, telemetry_relative_altitude_m)
        else:
            drone = drone_by_hw_id.get(int(target_hw_id))
            if not drone:
                continue

            ip = drone.get("ip")
            if not ip:
                continue

            try:
                response = requests.get(
                    f"http://{ip}:{Params.drone_api_port}/{Params.get_drone_home_URI}",
                    timeout=request_timeout,
                )
                response.raise_for_status()
                home_payload = response.json()
                home_altitude_m = float(home_payload.get("altitude"))
            except (requests.RequestException, TypeError, ValueError):
                continue

            relative_altitude_m = max(0.0, current_altitude_m - home_altitude_m)

        if max_relative_altitude_m is None:
            max_relative_altitude_m = relative_altitude_m
        else:
            max_relative_altitude_m = max(max_relative_altitude_m, relative_altitude_m)

    return max_relative_altitude_m


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
app.include_router(create_core_router(sys.modules[__name__]))
app.include_router(create_configuration_router(sys.modules[__name__]))
app.include_router(create_git_router(sys.modules[__name__]))
app.include_router(create_management_router(sys.modules[__name__]))
app.include_router(create_origin_router(sys.modules[__name__]))
app.include_router(create_show_management_router(sys.modules[__name__]))
app.include_router(create_static_assets_router(sys.modules[__name__]))
app.include_router(create_swarm_router(sys.modules[__name__]))
app.include_router(create_swarm_trajectory_router(sys.modules[__name__]))

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
                if (
                    origin
                    and origin.get('lat') not in ('', None)
                    and origin.get('lon') not in ('', None)
                ):
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
        resolved_mission = resolve_mission_type(mission_type)

        if resolved_mission == Mission.SWARM_TRAJECTORY and normalized_target_ids:
            try:
                status_payload = swarm_trajectory_service.get_processing_status_payload()["status"]
                structure = {
                    "swarm_config": {
                        int(drone_id): {"follow": follow_id}
                        for drone_id, follow_id in (status_payload.get("follow_map") or {}).items()
                    },
                }
                scope_issues = swarm_trajectory_service.validate_target_scope_for_swarm_trajectory(
                    structure=structure,
                    processed_drones=status_payload.get("processed_drones") or [],
                    target_drone_ids=[int(drone_id) for drone_id in target_hw_ids],
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Swarm Trajectory target scope could not be verified: {exc}",
                ) from exc

            if scope_issues:
                formatted_issues = []
                for issue in scope_issues:
                    drone_id = issue.get("drone_id")
                    leader_id = issue.get("leader_id")
                    issue_code = issue.get("issue")
                    if issue_code == "missing_processed_trajectory":
                        formatted_issues.append(f"Drone {drone_id} has no processed trajectory in the active package")
                    elif issue_code == "leader_not_in_active_mission_set":
                        formatted_issues.append(f"Drone {drone_id} requires leader {leader_id} in the same target set")
                    elif issue_code == "missing_swarm_assignment":
                        formatted_issues.append(f"Drone {drone_id} is not present in the current swarm configuration")
                    elif issue_code == "circular_leader_chain":
                        formatted_issues.append(f"Drone {drone_id} has an invalid circular leader chain")

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Unsafe Swarm Trajectory target set. "
                        + "; ".join(formatted_issues[:4])
                    ),
                )

        if mission_requires_launch_armability_probe(resolved_mission):
            launch_probe = probe_live_armability_for_drones(
                actual_targets,
                require_global_position=True,
            )
            if not launch_probe["all_ready"]:
                formatted = []
                for drone_id in launch_probe["blocked_ids"][:4]:
                    summary = launch_probe["results"][drone_id]["summary"]
                    formatted.append(f"Drone {drone_id}: {summary}")
                for drone_id in launch_probe["unavailable_ids"][:4]:
                    summary = launch_probe["results"][drone_id]["summary"]
                    formatted.append(f"Drone {drone_id}: {summary}")

                raise HTTPException(
                    status_code=400,
                    detail="Live launch readiness probe failed. " + "; ".join(formatted),
                )

        # Create tracked command
        tracker = get_command_tracker()
        mission_type_int = resolved_mission.value if resolved_mission else 0
        tracking_skybrush_dir = skybrush_dir
        tracking_processed_dir = processed_dir
        tracking_shapes_dir = shapes_dir

        if resolved_mission == Mission.SWARM_TRAJECTORY:
            trajectory_folders = get_swarm_trajectory_folders()
            tracking_processed_dir = trajectory_folders.get("processed", processed_dir)

        tracking_max_relative_altitude_m = None
        if resolved_mission in {Mission.LAND, Mission.RETURN_RTL}:
            tracking_max_relative_altitude_m = _estimate_max_target_relative_altitude_m(
                drones,
                target_hw_ids,
            )

        tracking_timeout_ms = estimate_command_tracking_timeout_ms(
            resolved_mission,
            command_data=command_data,
            target_drone_ids=target_hw_ids,
            max_relative_altitude_m=tracking_max_relative_altitude_m,
            skybrush_dir=tracking_skybrush_dir,
            processed_dir=tracking_processed_dir,
            shapes_dir=tracking_shapes_dir,
        )

        command_id = await tracker.create_command(
            mission_type=mission_type_int,
            target_drones=target_hw_ids,
            params={
                'triggerTime': trigger_time,
                **{k: v for k, v in command_data.items() if k not in ['missionType', 'triggerTime']}
            },
            timeout_ms=tracking_timeout_ms,
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
            tracking_timeout_ms=tracking_timeout_ms,
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
    Cancel endpoint is intentionally fail-closed until it is wired to drone dispatch.

    Live mission/action cancellation must go through `/submit_command` with
    `missionType=0` so the cancel command is actually delivered to the drones
    instead of only mutating tracker state in memory.
    """
    raise HTTPException(
        status_code=409,
        detail=(
            f"/command/{command_id}/cancel is disabled because it does not dispatch to drones. "
            "Use POST /submit_command with missionType=0 to cancel live mission execution safely."
        ),
    )


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

# Module-level sync operation state (protected by _sync_lock)
_sync_state = {"active": False, "started_at": None, "results": None}
_sync_lock = asyncio.Lock()
_SYNC_VERIFY_TIMEOUT_SEC = 45.0
_SYNC_VERIFY_POLL_SEC = 2.0


def _select_sync_target_drones(
    drones_config: List[Dict[str, Any]],
    pos_ids: Optional[List[int]],
) -> tuple[List[Dict[str, Any]], List[int]]:
    """Choose which drones a sync operation should target.

    When no explicit target list is given, prefer drones with recent heartbeats so
    the operator sees results for the actively running fleet instead of stale config
    entries that are not part of the current SITL session.
    """
    if pos_ids:
        requested = {int(pos_id) for pos_id in pos_ids}
        targets = [d for d in drones_config if int(d.get('pos_id', 0)) in requested]
        return targets, []

    recent_heartbeats = get_all_heartbeats()
    if not recent_heartbeats:
        return drones_config, []

    now = time.time()
    grace_seconds = max(Params.TELEMETRY_POLLING_TIMEOUT, Params.heartbeat_interval * 2)
    active_hw_ids = set()

    for hw_id, heartbeat in recent_heartbeats.items():
        timestamp_ms = heartbeat.get('timestamp') if isinstance(heartbeat, dict) else None
        if not timestamp_ms:
            continue

        try:
            age_seconds = now - (float(timestamp_ms) / 1000.0)
        except (TypeError, ValueError):
            continue

        if age_seconds <= grace_seconds:
            active_hw_ids.add(str(hw_id))

    if not active_hw_ids:
        return drones_config, []

    targets = [d for d in drones_config if str(d.get('hw_id')) in active_hw_ids]
    skipped = [int(d.get('pos_id', d.get('hw_id', 0))) for d in drones_config if str(d.get('hw_id')) not in active_hw_ids]
    return targets, skipped


def _is_git_sync_verified(
    git_status: Dict[str, Any],
    expected_branch: str,
    expected_commit: str,
) -> bool:
    """Check whether a drone repo actually converged to the expected revision."""
    if not git_status or git_status.get('error'):
        return False

    if git_status.get('branch') != expected_branch:
        return False

    if git_status.get('commit') != expected_commit:
        return False

    if git_status.get('status') != 'clean':
        return False

    if git_status.get('uncommitted_changes'):
        return False

    return int(git_status.get('commits_ahead', 0) or 0) == 0 and int(git_status.get('commits_behind', 0) or 0) == 0


async def _verify_sync_targets(
    target_drones: List[Dict[str, Any]],
    expected_branch: str,
    expected_commit: str,
    timeout_sec: float = _SYNC_VERIFY_TIMEOUT_SEC,
    poll_interval_sec: float = _SYNC_VERIFY_POLL_SEC,
) -> tuple[List[int], List[int]]:
    """Poll targeted drones until their repos actually match the expected revision."""
    if not target_drones:
        return [], []

    pending: Dict[str, Dict[str, Any]] = {str(d['hw_id']): d for d in target_drones}
    verified_hw_ids: set[str] = set()
    deadline = time.monotonic() + timeout_sec

    while pending and time.monotonic() < deadline:
        tasks = [
            asyncio.to_thread(
                _config_get_drone_git_status,
                f"http://{drone['ip']}:{Params.drone_api_port}",
            )
            for drone in pending.values()
        ]
        statuses = await asyncio.gather(*tasks, return_exceptions=True)

        for drone, git_status in zip(list(pending.values()), statuses):
            hw_id = str(drone['hw_id'])

            if isinstance(git_status, Exception):
                continue

            if isinstance(git_status, dict) and not git_status.get('error'):
                with data_lock_git_status:
                    git_status_data_all_drones[hw_id] = git_status

            if _is_git_sync_verified(git_status, expected_branch, expected_commit):
                verified_hw_ids.add(hw_id)
                pending.pop(hw_id, None)

        if pending:
            await asyncio.sleep(poll_interval_sec)

    verified_pos_ids = sorted(int(d['pos_id']) for d in target_drones if str(d['hw_id']) in verified_hw_ids)
    failed_pos_ids = sorted(int(d['pos_id']) for d in target_drones if str(d['hw_id']) not in verified_hw_ids)
    return verified_pos_ids, failed_pos_ids


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
