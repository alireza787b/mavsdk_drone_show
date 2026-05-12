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
import math
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
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

# Import schemas
from schemas import *
from api_errors import DEFAULT_ERROR_RESPONSES, build_error_payload, normalize_validation_errors

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
from link_presence import get_recent_link_presence
from params import Params
from drone_api_routes import DRONE_GIT_STATUS_ROUTE, DRONE_STATE_ROUTE
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
from fleet_candidates import get_fleet_candidate_registry
from git_status import git_status_data_all_drones, data_lock_git_status
from command_tracker import get_command_tracker, init_command_tracker
from src import __version__ as MDS_VERSION

# Import SAR router
from api_routes.fleet_candidates import create_fleet_candidates_router
from api_routes.fleet_sidecars import create_fleet_sidecars_router
from sar.routes import create_sar_router
from api_routes.auth import create_auth_router
from api_routes.commands import create_command_router
from api_routes.configuration import create_configuration_router
from api_routes.core import create_core_router
from api_routes.git_status import create_git_router
from api_routes.management import create_management_router
from api_routes.origin import create_origin_router
from api_routes.px4_params import create_px4_params_router
from api_routes.show_management import create_show_management_router
from api_routes.sitl_control import create_sitl_control_router
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
from auth_runtime import MDSAuthMiddleware
from src.security.auth import AuthSettings

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

    def _normalize_drones(self, drones: List[Dict]) -> List[Dict[str, Any]]:
        """Normalize managed drone targets into a stable internal representation."""
        normalized: List[Dict[str, Any]] = []
        for drone in drones or []:
            try:
                hw_id = str(drone.get("hw_id")).strip()
            except Exception:
                hw_id = ""
            ip = str(drone.get("ip", "")).strip()
            if not hw_id or not ip:
                continue

            try:
                pos_id = int(drone.get("pos_id", 0) or 0)
            except Exception:
                pos_id = 0

            normalized.append(
                {
                    "hw_id": hw_id,
                    "pos_id": pos_id,
                    "ip": ip,
                }
            )
        return normalized

    def apply_drone_targets(self, drones: List[Dict]) -> dict[str, int]:
        """
        Reconcile in-memory polling targets with the current fleet manifest.

        This keeps the FastAPI runtime aligned with config.json / Fleet Enrollment
        changes without requiring a backend restart.
        """
        normalized = self._normalize_drones(drones)
        previous_ids = {str(drone.get("hw_id")) for drone in self.drones}
        next_ids = {str(drone.get("hw_id")) for drone in normalized}
        added_ids = next_ids - previous_ids
        removed_ids = previous_ids - next_ids

        self.drones = normalized

        with telemetry_lock:
            for drone in normalized:
                hw_id = str(drone["hw_id"])
                telemetry_data_all_drones[hw_id] = _build_background_unavailable_record(
                    hw_id=hw_id,
                    pos_id=drone.get("pos_id", 0),
                    ip=drone["ip"],
                    error_message="Waiting for drone telemetry.",
                    existing=telemetry_data_all_drones.get(hw_id),
                )

            for hw_id in list(telemetry_data_all_drones.keys()):
                if str(hw_id) not in next_ids:
                    telemetry_data_all_drones.pop(hw_id, None)

        with data_lock_git_status:
            for hw_id in list(git_status_data_all_drones.keys()):
                if str(hw_id) not in next_ids:
                    git_status_data_all_drones.pop(hw_id, None)

        return {
            "managed": len(normalized),
            "added": len(added_ids),
            "removed": len(removed_ids),
        }

    async def start(self, drones: List[Dict]):
        """Start all background services"""
        target_summary = self.apply_drone_targets(drones)
        if self.running:
            log_system_event(
                (
                    "Background services target set refreshed "
                    f"({target_summary['managed']} managed, "
                    f"+{target_summary['added']}, -{target_summary['removed']})"
                ),
                "INFO",
                "system",
            )
            return

        self.running = True

        # Start telemetry polling
        self.telemetry_task = asyncio.create_task(self._poll_telemetry())
        log_system_event(
            f"Telemetry polling started for {len(self.drones)} drones",
            "INFO", "telemetry"
        )

        # Start git status polling
        self.git_status_task = asyncio.create_task(self._poll_git_status())
        log_system_event(
            f"Git status polling started for {len(self.drones)} drones",
            "INFO", "git"
        )

        self.command_timeout_task = asyncio.create_task(self._poll_command_timeouts())
        log_system_event("Command timeout monitoring started", "INFO", "command")

    async def reconcile(self, drones: List[Dict]):
        """Apply a fresh fleet manifest to the live background pollers."""
        if not self.running:
            await self.start(drones)
            return

        target_summary = self.apply_drone_targets(drones)
        log_system_event(
            (
                "Background services reconciled with current fleet manifest "
                f"({target_summary['managed']} managed, "
                f"+{target_summary['added']}, -{target_summary['removed']})"
            ),
            "INFO",
            "system",
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

        if self.command_timeout_task:
            self.command_timeout_task.cancel()
            try:
                await self.command_timeout_task
            except asyncio.CancelledError:
                pass

        self.telemetry_task = None
        self.git_status_task = None
        self.command_timeout_task = None

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
                        url = f"http://{ip}:{Params.drone_api_port}{DRONE_STATE_ROUTE}"
                        response = await loop.run_in_executor(
                            None,
                            lambda u=url: requests.get(u, timeout=Params.GCS_TELEMETRY_REQUEST_TIMEOUT_SEC)
                        )

                        if response.status_code == 200:
                            data = response.json()
                            with telemetry_lock:
                                telemetry_data_all_drones[hw_id] = _build_background_telemetry_record(hw_id, ip, data)
                        else:
                            with telemetry_lock:
                                telemetry_data_all_drones[hw_id] = _build_background_unavailable_record(
                                    hw_id=hw_id,
                                    pos_id=drone.get("pos_id", 0),
                                    ip=ip,
                                    error_message=f"Drone telemetry endpoint returned HTTP {response.status_code}.",
                                    existing=telemetry_data_all_drones.get(hw_id),
                                )

                    except Exception:
                        with telemetry_lock:
                            telemetry_data_all_drones[hw_id] = _build_background_unavailable_record(
                                hw_id=hw_id,
                                pos_id=drone.get("pos_id", 0),
                                ip=ip,
                                error_message="Unable to reach the drone telemetry endpoint.",
                                existing=telemetry_data_all_drones.get(hw_id),
                            )

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
                        url = f"http://{ip}:{Params.drone_api_port}{DRONE_GIT_STATUS_ROUTE}"
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
fleet_candidate_registry = get_fleet_candidate_registry()


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


def observe_fleet_candidate_heartbeat(heartbeat: dict[str, Any]):
    """Update the durable fleet-candidate registry from a live heartbeat."""
    return fleet_candidate_registry.observe_heartbeat(heartbeat, load_config=load_config)


def list_fleet_candidates(*, include_inactive: bool = False, runtime_mode: str | None = None):
    """List durable fleet-candidate records."""
    return fleet_candidate_registry.list_candidates(
        load_config=load_config,
        include_inactive=include_inactive,
        runtime_mode=runtime_mode,
    )


def get_fleet_candidate(candidate_id: str):
    """Fetch one durable fleet-candidate record."""
    return fleet_candidate_registry.get_candidate(candidate_id, load_config=load_config)


def announce_fleet_candidate(payload: FleetCandidateAnnounceRequest):
    """Merge an explicit bootstrap/node announce payload into the candidate registry."""
    return fleet_candidate_registry.announce_candidate(payload, load_config=load_config)


def accept_fleet_candidate(candidate_id: str, payload: FleetCandidateAcceptRequest):
    """Accept a candidate as a new fleet member."""
    return fleet_candidate_registry.accept_candidate(
        candidate_id,
        payload,
        load_config=load_config,
        save_config=save_config,
        validate_and_process_config=validate_and_process_config,
    )


def replace_fleet_candidate(candidate_id: str, payload: FleetCandidateReplaceRequest):
    """Replace an existing configured fleet member with a pending candidate."""
    return fleet_candidate_registry.replace_candidate(
        candidate_id,
        payload,
        load_config=load_config,
        save_config=save_config,
        load_swarm=load_swarm,
        save_swarm=save_swarm,
        validate_and_process_config=validate_and_process_config,
    )


def recover_fleet_candidate(candidate_id: str, payload: FleetCandidateRecoverRequest):
    """Recover an existing configured fleet member using the same hardware ID."""
    return fleet_candidate_registry.recover_candidate(
        candidate_id,
        payload,
        load_config=load_config,
        save_config=save_config,
        validate_and_process_config=validate_and_process_config,
    )


def set_fleet_candidate_state(
    candidate_id: str,
    new_state: FleetCandidateState,
    *,
    reason: Optional[str] = None,
):
    """Mutate one candidate's resolved state without changing fleet config."""
    return fleet_candidate_registry.update_candidate_state(
        candidate_id,
        new_state=new_state,
        load_config=load_config,
        reason=reason,
    )


async def reconcile_background_services() -> list[dict[str, Any]]:
    """Refresh live pollers after fleet-manifest mutations without restarting GCS."""
    drones = load_config()
    await background_services.reconcile(drones)
    return drones


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


def _has_valid_global_position(record: Dict[str, Any]) -> bool:
    try:
        lat = float(record.get("position_lat"))
        lon = float(record.get("position_long"))
    except (TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in [lat, lon]):
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    return abs(lat) > 0.000001 or abs(lon) > 0.000001


def _position_unavailable_reason(record: Dict[str, Any]) -> Optional[str]:
    try:
        gps_fix_type = int(record.get("gps_fix_type", 0) or 0)
    except (TypeError, ValueError):
        gps_fix_type = 0
    if gps_fix_type >= 3:
        return "GPS fix present, waiting for valid PX4 global position."
    if gps_fix_type > 0:
        return "GPS fix is not 3D yet."
    return "No GPS fix reported."


def _ensure_position_quality_fields(record: Dict[str, Any], now_ms: int) -> Dict[str, Any]:
    explicit_global_flag = record.get("global_position_valid")
    valid_global = bool(explicit_global_flag) and _has_valid_global_position(record)
    if not isinstance(explicit_global_flag, bool):
        valid_global = _has_valid_global_position(record)

    record["global_position_valid"] = valid_global
    record.setdefault("global_position_timestamp_ms", record.get("telemetry_timestamp_ms") or 0)
    global_ts = _normalize_update_time_ms(record.get("global_position_timestamp_ms"))
    record["global_position_age_ms"] = max(0, now_ms - global_ts) if global_ts is not None else None

    try:
        gps_fix_type = int(record.get("gps_fix_type", 0) or 0)
    except (TypeError, ValueError):
        gps_fix_type = 0
    record.setdefault("gps_raw_valid", gps_fix_type >= 3)
    record.setdefault("gps_raw_timestamp_ms", record.get("telemetry_timestamp_ms") or 0)
    gps_ts = _normalize_update_time_ms(record.get("gps_raw_timestamp_ms"))
    record["gps_raw_age_ms"] = max(0, now_ms - gps_ts) if gps_ts is not None else None
    record.setdefault("position_source", "global_position_int" if valid_global else "unavailable")
    record["position_unavailable_reason"] = None if valid_global else (
        record.get("position_unavailable_reason") or _position_unavailable_reason(record)
    )
    if not valid_global:
        record["distance_to_home_m"] = None
    return record


def _build_background_unavailable_record(
    hw_id: Any,
    pos_id: Any,
    ip: str,
    error_message: str,
    *,
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a stable typed telemetry row even when live telemetry is unavailable."""
    normalized_hw_id = str(hw_id)
    now_ms = int(time.time() * 1000)
    stale_threshold_ms = _local_mavlink_stale_threshold_ms()
    existing = dict(existing or {})

    with last_heartbeats_lock:
        heartbeat_data = (last_heartbeats.get(normalized_hw_id) or {}).copy()

    record = {
        "hw_id": str(existing.get("hw_id", normalized_hw_id)),
        "pos_id": int(existing.get("pos_id", pos_id or 0) or 0),
        "detected_pos_id": existing.get("detected_pos_id", 0),
        "state": existing.get("state", 999),
        "mission": existing.get("mission", 0),
        "last_mission": existing.get("last_mission", 0),
        "position_lat": existing.get("position_lat", 0.0),
        "position_long": existing.get("position_long", 0.0),
        "position_alt": existing.get("position_alt", 0.0),
        "velocity_north": existing.get("velocity_north", 0.0),
        "velocity_east": existing.get("velocity_east", 0.0),
        "velocity_down": existing.get("velocity_down", 0.0),
        "yaw": existing.get("yaw", 0.0),
        "battery_voltage": existing.get("battery_voltage", 0.0),
        "follow_mode": existing.get("follow_mode", 0),
        "update_time": existing.get("update_time"),
        "timestamp": existing.get("timestamp", now_ms),
        "server_time": existing.get("server_time"),
        "trigger_time": existing.get("trigger_time", 0),
        "flight_mode": existing.get("flight_mode", "UNKNOWN"),
        "base_mode": existing.get("base_mode", "UNKNOWN"),
        "system_status": existing.get("system_status", "UNKNOWN"),
        "is_armed": bool(existing.get("is_armed", False)),
        "is_ready_to_arm": False,
        "home_position_set": bool(existing.get("home_position_set", False)),
        "distance_to_home_m": existing.get("distance_to_home_m"),
        "global_position_valid": existing.get("global_position_valid"),
        "global_position_timestamp_ms": existing.get("global_position_timestamp_ms", 0),
        "global_position_age_ms": existing.get("global_position_age_ms"),
        "gps_raw_valid": bool(existing.get("gps_raw_valid", False)),
        "gps_raw_timestamp_ms": existing.get("gps_raw_timestamp_ms", 0),
        "gps_raw_age_ms": existing.get("gps_raw_age_ms"),
        "local_position_ok": bool(existing.get("local_position_ok", False)),
        "local_position_north": existing.get("local_position_north"),
        "local_position_east": existing.get("local_position_east"),
        "local_position_down": existing.get("local_position_down"),
        "local_position_time_boot_ms": existing.get("local_position_time_boot_ms", 0),
        "position_source": existing.get("position_source", "unavailable"),
        "position_unavailable_reason": existing.get("position_unavailable_reason"),
        "readiness_status": "unknown",
        "readiness_summary": error_message,
        "readiness_checks": existing.get("readiness_checks", []),
        "preflight_blockers": [_build_stale_background_blocker(error_message, now_ms)],
        "preflight_warnings": [],
        "status_messages": existing.get("status_messages", []),
        "preflight_last_update": now_ms,
        "hdop": existing.get("hdop", 99.99),
        "vdop": existing.get("vdop", 99.99),
        "gps_fix_type": existing.get("gps_fix_type", 0),
        "satellites_visible": existing.get("satellites_visible", 0),
        "ip": existing.get("ip", ip),
        "telemetry_available": False,
        "telemetry_error": error_message,
        "heartbeat_last_seen": heartbeat_data.get("timestamp"),
        "heartbeat_network_info": heartbeat_data.get("network_info") or {},
        "heartbeat_first_seen": _normalize_heartbeat_first_seen(heartbeat_data.get("first_seen")),
        "telemetry_last_update_age_ms": None,
        "telemetry_stale_threshold_ms": stale_threshold_ms,
    }

    update_time_ms = _normalize_update_time_ms(record.get("update_time"))
    if update_time_ms is not None:
        record["telemetry_last_update_age_ms"] = max(0, now_ms - update_time_ms)

    return _ensure_position_quality_fields(record, now_ms)


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
    _ensure_position_quality_fields(record, now_ms)

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

    # Start background services even with an empty manifest so runtime fleet
    # changes can reconcile in-process without requiring a backend restart.
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

_auth_settings = AuthSettings.from_env()
_cors_origin_regex = os.environ.get(
    "MDS_CORS_ALLOW_ORIGIN_REGEX",
    r"https?://[^/]+(:3030|:5030)?",
)

app = FastAPI(
    title="GCS Server API",
    description="Ground Control Station server for MAVSDK Drone Show with HTTP REST and WebSocket support",
    version=MDS_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# Auth middleware must be registered before CORS so CORS remains the outer
# wrapper and auth errors still include browser CORS headers.
app.add_middleware(MDSAuthMiddleware)

# CORS middleware.
#
# When auth is enabled we cannot use wildcard origins with credentials. The
# default regex keeps browser operation portable across localhost/VPS/NetBird
# hosts while allowing the browser to send the HttpOnly auth cookie.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[] if _auth_settings.any_auth_enabled else ["*"],
    allow_origin_regex=_cors_origin_regex if _auth_settings.any_auth_enabled else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# Register SAR router
app.include_router(create_sar_router(sys.modules[__name__]))
app.include_router(create_auth_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_command_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_core_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_configuration_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_fleet_candidates_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_fleet_sidecars_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_git_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_management_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_origin_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_px4_params_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_show_management_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_sitl_control_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_static_assets_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_swarm_router(sys.modules[__name__]), responses=DEFAULT_ERROR_RESPONSES)
app.include_router(create_swarm_trajectory_router(sys.modules[__name__]))

# Background log puller (disabled by default, enable via MDS_LOG_BACKGROUND_PULL=true)
from log_background import BackgroundLogPuller
background_puller = BackgroundLogPuller()

# Register Log API router (puller injected to avoid circular import)
from log_routes import create_log_router
app.include_router(create_log_router(puller=background_puller), responses=DEFAULT_ERROR_RESPONSES)


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

    When no explicit target list is given, prefer drones with recent link presence
    so the operator sees results for the actively running fleet instead of stale
    config entries that are not part of the current SITL session.
    """
    if pos_ids:
        requested = {int(pos_id) for pos_id in pos_ids}
        targets = [d for d in drones_config if int(d.get('pos_id', 0)) in requested]
        return targets, []

    link_presence = get_recent_link_presence(d.get('hw_id') for d in drones_config)
    if not link_presence:
        return drones_config, []

    active_hw_ids = {
        str(hw_id)
        for hw_id, snapshot in link_presence.items()
        if snapshot.get('online_recent')
    }

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

@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    """Return one consistent validation-error envelope for typed request parsing."""
    return JSONResponse(
        status_code=422,
        content=build_error_payload(
            request,
            status_code=422,
            detail=normalize_validation_errors(exc),
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    """Return one consistent HTTP-error envelope for FastAPI and Starlette errors."""
    if exc.status_code >= 500:
        log_system_error(f"HTTP {exc.status_code} on {request.url.path}: {exc.detail}", "api")
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_payload(
            request,
            status_code=exc.status_code,
            detail=None if exc.status_code >= 500 else exc.detail,
        ),
    )


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception):
    """Handle uncaught server errors without exposing raw internals to clients."""
    log_system_error(f"Internal error on {request.url.path}: {exc}", "api")
    return JSONResponse(
        status_code=500,
        content=build_error_payload(
            request,
            status_code=500,
        ),
    )


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    # Read environment configuration
    port = int(os.getenv('MDS_GCS_API_PORT', Params.gcs_api_port))
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
