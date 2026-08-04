# src/drone_api_server.py
"""
Drone API Server - FastAPI Implementation
==========================================
Modern async API server for drone-side HTTP and WebSocket communication.
Uses canonical `/api/v1/...` HTTP routes plus a dedicated WebSocket stream.

HTTP REST Endpoints:
- GET  /api/v1/drone/state                    - Get current drone state (snapshot)
- GET  /api/v1/preflight/armability           - Probe live launch readiness
- POST /api/v1/preflight/launch-preparations  - Prepare one command-bound launch
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
import shutil
import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Tuple
from urllib.parse import quote

# FastAPI imports
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
import uvicorn
import requests
import asyncio
import json
from mavsdk.system import System

from mds_logging import get_logger
from mds_logging.api_schemas import (
    OnboardUlogCapability,
    OnboardUlogDownloadRequest,
    OnboardUlogJobDeleteResponse,
    OnboardUlogSummaryResponse,
)
from src.live_armability_contract import LiveArmabilityTrustEnvelope
from src.command_execution_contract import (
    DroneExecutionOutcome,
    format_pending_superseded_execution_error,
    is_legacy_schema_outcome_rejection,
    mission_requires_launch_armability_probe,
)
from src.launch_preparation_protocol import (
    LAUNCH_PREPARATION_TOKEN_HEADER,
    LaunchPreparationBinding,
    LaunchPreparationConsumeStatus,
    LaunchPreparationRequest,
    LaunchPreparationResponse,
    LaunchPreparationStore,
    calculate_launch_preparation_token_ttl_sec,
    immutable_command_payload_sha256,
)

logger = get_logger("drone_api")

SIDECAR_PROFILE_PROXY_ACTIONS = {"import", "apply", "promote-reference-draft"}
SIDECAR_PROFILE_PROXY_DEFAULTS = {
    "smart-wifi-manager": {
        "port": 9080,
        "listen_env": "MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN",
        "token_env": ("MDS_SIDECAR_PROFILE_TOKEN", "SMART_WIFI_MANAGER_API_TOKEN"),
        "reconcile_script": "tools/reconcile_connectivity.sh",
    },
    "mavlink-anywhere": {
        "port": 9070,
        "listen_env": "MDS_MAVLINK_ANYWHERE_DASHBOARD_LISTEN",
        "token_env": ("MDS_SIDECAR_PROFILE_TOKEN", "MAVLINK_ANYWHERE_API_TOKEN"),
        "reconcile_script": "tools/reconcile_mavlink_runtime.sh",
    },
}

# Project imports
from src.drone_config import DroneConfig
from src.constants import NetworkDefaults
from src.coordinate_utils import latlon_to_ne, get_expected_position_from_trajectory
from src.command_contract import DroneCommandRequest
from src.command_admission import (
    AirborneAdmissionStatus,
    evaluate_cached_airborne_admission,
)
from src.command_installation import (
    CommandInstallationRejected,
    CommandInstallationResult,
)
from src.drone_api_routes import (
    DRONE_COMMANDS_ROUTE,
    DRONE_GIT_STATUS_ROUTE,
    DRONE_LAUNCH_PREPARATION_ROUTE,
    DRONE_LIVE_ARMABILITY_ROUTE,
    DRONE_LOCAL_POSITION_ROUTE,
    DRONE_NAVIGATION_GLOBAL_ORIGIN_ROUTE,
    DRONE_NAVIGATION_HOME_ROUTE,
    DRONE_ENV_ROUTE,
    DRONE_NETWORK_STATUS_ROUTE,
    DRONE_PX4_PARAMS_PATCH_APPLY_ROUTE,
    DRONE_PX4_PARAMS_POLICY_ROUTE,
    DRONE_PX4_PARAMS_SNAPSHOT_CURRENT_ROUTE,
    DRONE_PX4_PARAMS_SNAPSHOT_REFRESH_ROUTE,
    DRONE_PX4_PARAM_VALUE_ROUTE_TEMPLATE,
    DRONE_POSITION_DEVIATION_ROUTE,
    DRONE_SIDECAR_PROFILE_PROXY_ROUTE_TEMPLATE,
    DRONE_STATE_ROUTE,
    DRONE_SWARM_CONFIG_ROUTE,
    DRONE_SWARM_STATE_ROUTE,
    DRONE_SYSTEM_HEALTH_ROUTE,
    DRONE_ULOG_DOWNLOAD_CONTENT_ROUTE_TEMPLATE,
    DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE,
    DRONE_ULOG_ERASE_ALL_ROUTE,
    DRONE_ULOG_FILES_ROUTE,
    DRONE_ULOG_FILE_SUMMARY_ROUTE_TEMPLATE,
    DRONE_ULOG_FILE_DOWNLOAD_ROUTE_TEMPLATE,
    DRONE_ULOG_JOB_TOKEN_HEADER,
    DRONE_ULOG_POLICY_ROUTE,
    DRONE_WS_STATE_ROUTE,
    DRONE_WS_SWARM_STATE_ROUTE,
)
from src.gcs_api_routes import (
    GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE,
    GCS_ORIGIN_BOOTSTRAP_ROUTE,
)
from src.gcs_auth_client import gcs_auth_headers, read_gcs_api_token
from src.managed_runtime_status import (
    build_connectivity_runtime_summary,
    build_mavlink_runtime_summary,
    read_git_sync_runtime_summary,
)
from src.network_status import build_network_info
from src.settings.env_files import persist_env_updates
from src.settings.env_registry import EnvRegistryError
from src.settings.env_status import (
    build_node_env_response,
    build_node_env_summary_safe,
    validate_node_env_updates,
)
from src.settings.runtime import get_local_env_path
from src.mission_startup import probe_offboard_armability
from src.security.auth import (
    MACHINE_CREDENTIAL_HEADER,
    ULOG_OP_DOWNLOAD_CONTENT,
    ULOG_OP_DOWNLOAD_CREATE,
    ULOG_OP_DOWNLOAD_DELETE,
    ULOG_OP_DOWNLOAD_STATUS,
    ULOG_OP_ERASE,
    ULOG_OP_FILES_READ,
    ULOG_OP_POLICY_READ,
    ULOG_OP_SUMMARY_READ,
    verify_machine_credential,
)
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
from src.ulog_service import OnboardUlogService, UlogServiceError
from functions.git_manager import get_local_git_report
from functions.data_utils import safe_float, safe_get, safe_int
from functions.file_utils import load_csv, load_json, get_trajectory_first_position
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
    battery_remaining_percent: Optional[float] = None
    battery_charge_state: Optional[int] = None
    battery_fault_bitmask: Optional[int] = None
    battery_timestamp_ms: int = 0
    battery_age_ms: Optional[int] = None
    follow_mode: Any = None
    update_time: Any = None
    timestamp: int
    server_time: int = 0
    flight_mode: Any
    base_mode: Any
    system_status: Any
    is_armed: bool
    heartbeat_timestamp_ms: int = 0
    heartbeat_age_ms: Optional[int] = None
    is_ready_to_arm: bool
    home_position_set: bool = False
    distance_to_home_m: Optional[float] = None
    global_position_valid: bool = False
    global_position_timestamp_ms: int = 0
    global_position_age_ms: Optional[int] = None
    gps_raw_valid: bool = False
    gps_raw_timestamp_ms: int = 0
    gps_raw_age_ms: Optional[int] = None
    gps_raw_altitude_m: Optional[float] = None
    # Keep the shared altitude-policy fields in the typed response model.
    # Pydantic otherwise drops the communicator's relative/local evidence,
    # leaving GCS with only the MSL ``position_alt`` fallback.
    altitude_report: Dict[str, Any] = Field(default_factory=dict)
    altitude_display_m: Optional[float] = None
    altitude_source: Optional[str] = None
    relative_altitude_m: Optional[float] = None
    baro_altitude_m: Optional[float] = None
    baro_timestamp_ms: int = 0
    baro_age_ms: Optional[int] = None
    local_position_ok: bool = False
    local_position_north: float = 0.0
    local_position_east: float = 0.0
    local_position_down: float = 0.0
    local_position_time_boot_ms: int = 0
    local_position_timestamp_ms: int = 0
    position_source: str = "unavailable"
    position_unavailable_reason: Optional[str] = None
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


class SwarmStateResponse(BaseModel):
    hw_id: int
    pos_id: int
    follow_mode: Optional[int] = None
    position_lat: float
    position_long: float
    position_alt: float
    velocity_north: float
    velocity_east: float
    velocity_down: float
    yaw: float
    yaw_deg: float
    yaw_rate_deg_s: float = 0.0
    telemetry_timestamp_ms: int = 0
    stream_seq: int = 0
    global_position_valid: bool = False
    global_position_timestamp_ms: int = 0
    position_source: str = "unavailable"
    source_frame: str = "global_lla_ned"
    source_time_boot_ms: int = 0
    local_position_north: float = 0.0
    local_position_east: float = 0.0
    local_position_down: float = 0.0
    local_velocity_north: float = 0.0
    local_velocity_east: float = 0.0
    local_velocity_down: float = 0.0
    emitted_at_ms: int


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
    replayed: bool = Field(False, description="Whether this is a replay of an earlier command delivery")
    command_phase: Optional[str] = Field(
        None,
        description="Known lifecycle phase of the original command delivery",
    )
    command_outcome: Optional[str] = Field(
        None,
        description="Known terminal outcome of the original command delivery",
    )
    timestamp: int = Field(..., description="Response timestamp in milliseconds")


@dataclass(frozen=True)
class _CommandSemanticIdentity:
    """Bounded canonical identity for one execution-affecting command payload."""

    fingerprint: str
    field_fingerprints: Dict[str, str]


@dataclass
class _NodeCommandRecord:
    """In-process idempotency record retained across the command lifecycle."""

    command_id: str
    semantic_identity: _CommandSemanticIdentity
    mission_type: int
    trigger_time: int
    phase: str
    outcome: Optional[str]
    response: Optional[Dict[str, Any]]
    created_at_monotonic: float
    last_seen_monotonic: float
    legacy_runtime_bound: bool = False


@dataclass(frozen=True)
class _CommandStateSnapshot:
    """Minimum scheduler-visible state captured before a command can mutate it."""

    command_id: Optional[str]
    mission_type: int
    trigger_time: int
    state: int


@dataclass(frozen=True)
class _LaunchCommitAdmission:
    """Pre-transaction result for one node command request.

    Live launch probing deliberately happens before the command/scheduler lock
    so a slow readiness path cannot block LAND/RTL/HOLD recovery admission.
    Exact idempotent replays skip token/probe work and are reconciled by the
    authoritative in-lock command record without executing again.
    """

    command: DroneCommandRequest
    launch_required: bool
    authorized: bool
    existing_record_seen: bool = False
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    readiness_valid_until_monotonic: Optional[float] = None


class LiveArmabilityResponse(LiveArmabilityTrustEnvelope):
    """Full node response extending the shared trust-bearing envelope."""

    blockers: List[str] = Field(default_factory=list)
    armable: bool = False
    global_position_ok: bool = False
    home_position_ok: bool = False
    local_position_ok: bool = False
    gyro_ok: bool = False
    accel_ok: bool = False
    mag_ok: bool = False
    health_ready: bool = False
    health_age_ms: Optional[int] = None
    battery: Dict[str, Any] = Field(default_factory=dict)
    timed_out: bool = False
    elapsed_sec: float = 0.0
    require_global_position: bool = True
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    probe_error: Optional[str] = None


class DroneHealthResponse(BaseModel):
    status: str
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    version: str
    ulog_capability: Dict[str, Any] = Field(default_factory=dict)


class DroneManagedMavlinkRuntimeResponse(BaseModel):
    tool: str = "mavlink-anywhere"
    status_source: str
    mode: Optional[str] = None
    management_mode: str
    service_state: Optional[str] = None
    repo_url: str
    ref: str
    installed_ref: Optional[str] = None
    repo_web_url: Optional[str] = None
    install_dir: str
    install_dir_present: bool
    runtime_present: bool
    runtime_head: Optional[str] = None
    router_binary_present: bool
    router_service_status: str
    dashboard_enabled: bool
    dashboard_listen: str
    dashboard_service_status: str
    desired_config_hash: Optional[str] = None
    applied_config_hash: Optional[str] = None
    config_hash_match: Optional[bool] = None
    profile_source: Optional[str] = None
    desired_hash: Optional[str] = None
    applied_hash: Optional[str] = None
    local_hash: Optional[str] = None
    drift_state: Optional[str] = None
    profile_summary: Dict[str, Any] = Field(default_factory=dict)
    last_apply_result: Optional[str] = None


class DroneManagedConnectivityRuntimeResponse(BaseModel):
    tool: str = "smart-wifi-manager"
    status_source: str
    backend: str
    service_state: Optional[str] = None
    repo_url: str
    ref: str
    installed_ref: Optional[str] = None
    repo_web_url: Optional[str] = None
    install_dir: str
    install_dir_present: bool
    mode: str
    import_mode: str
    profile_path: str
    profile_present: bool
    profile_hash: Optional[str] = None
    dashboard_listen: str
    service_status: str
    desired_config_hash: Optional[str] = None
    applied_config_hash: Optional[str] = None
    config_hash_match: Optional[bool] = None
    profile_source: Optional[str] = None
    desired_hash: Optional[str] = None
    applied_hash: Optional[str] = None
    local_hash: Optional[str] = None
    drift_state: Optional[str] = None
    profile_summary: Dict[str, Any] = Field(default_factory=dict)
    last_apply_result: Optional[str] = None


class DroneGitSyncRuntimeResponse(BaseModel):
    status: str
    summary: str
    phase: str = "unknown"
    phase_message: str = ""
    last_run_at_ms: Optional[int] = None
    updated_units: List[str] = Field(default_factory=list)
    service_reload_status: str = "unknown"
    service_reload_message: str = ""
    deferred_unit_actions: List[str] = Field(default_factory=list)
    coordinator_restart_scheduled: bool = False
    connectivity_reconcile_status: str = "unknown"
    mavlink_runtime_reconcile_status: str = "unknown"
    mavsdk_runtime_status: str = "unknown"
    requirements_update_status: str = "unknown"
    recovery_action: str = "none"
    recovery_backup_path: Optional[str] = None
    disk_available_status: str = "unknown"
    disk_free_kb: Optional[int] = None


class DroneEnvRuntimeResponse(BaseModel):
    status_source: str = "unknown"
    registry_version: int = 0
    registry_hash: str = ""
    local_env_path: str = ""
    local_env_present: bool = False
    node_identity_path: str = ""
    node_identity_present: bool = False
    runtime_mode: str = "unknown"
    runtime_mode_source: str = "unknown"
    hw_id: Optional[int] = None
    hw_id_source: str = "unknown"
    configured_key_count: int = 0
    configured_node_key_count: int = 0
    registered_node_key_count: int = 0
    unknown_keys: List[str] = Field(default_factory=list)
    deprecated_keys: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class DroneEnvEntryResponse(BaseModel):
    name: str
    title: str
    scope: str
    domain: str
    source_of_truth: str
    value_type: str
    value: Optional[Any] = None
    value_present: bool
    secret: bool
    secret_configured: bool = False
    default: Optional[Any] = None
    editable: bool
    ui_visibility: str
    restart_required: str
    apply_action: str
    allowed_values: List[Any] = Field(default_factory=list)
    docs: str
    deprecated: bool = False
    replacement: Optional[str] = None
    notes: str = ""


class DroneEnvResponse(BaseModel):
    config_path: str
    config_present: bool
    registry_version: int
    registry_hash: str
    values: List[DroneEnvEntryResponse] = Field(default_factory=list)
    unknown_keys: List[str] = Field(default_factory=list)
    deprecated_keys: List[str] = Field(default_factory=list)
    summary: DroneEnvRuntimeResponse
    warnings: List[str] = Field(default_factory=list)


class DroneEnvUpdateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    updates: Dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class DroneEnvUpdateResponse(BaseModel):
    success: bool
    dry_run: bool
    config_path: str
    updated_keys: List[str] = Field(default_factory=list)
    changed_keys: List[str] = Field(default_factory=list)
    restart_required: bool
    apply_actions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


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
    hw_id: str
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
    repo_access_mode: str = "custom_or_unknown"
    git_auth_health_status: str = "unknown"
    git_auth_health_summary: str = ""
    git_auth_health_issues: List[str] = Field(default_factory=list)
    mavlink_runtime: Optional[DroneManagedMavlinkRuntimeResponse] = None
    connectivity_runtime: Optional[DroneManagedConnectivityRuntimeResponse] = None
    git_sync_runtime: Optional[DroneGitSyncRuntimeResponse] = None
    env_runtime: Optional[DroneEnvRuntimeResponse] = None


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


class UsbModemStatusResponse(BaseModel):
    interface: str
    connection_name: str


class CellularStatusResponse(BaseModel):
    interface: str
    connection_name: str


class NetworkLinkResponse(BaseModel):
    type: str
    label: str
    interface: str
    connection_name: str = ""
    ssid: Optional[str] = None
    signal_strength_percent: Optional[Any] = None
    is_default_route: Optional[bool] = None
    internet_reachable: Optional[bool] = None


class InternetStatusResponse(BaseModel):
    enabled: bool
    reachable: Optional[bool] = None
    method: str
    target: str
    checked_at: int
    error: Optional[str] = None


class NetworkStatusResponse(BaseModel):
    wifi: Optional[WifiStatusResponse] = None
    ethernet: Optional[EthernetStatusResponse] = None
    usb_modem: Optional[UsbModemStatusResponse] = None
    cellular: Optional[CellularStatusResponse] = None
    primary_link: Optional[NetworkLinkResponse] = None
    active_links: List[NetworkLinkResponse] = Field(default_factory=list)
    default_route_interface: str = ""
    internet: Optional[InternetStatusResponse] = None
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


def _listen_port(value: Optional[str], default: int) -> int:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    if ":" in text:
        tail = text.rsplit(":", 1)[-1]
        if tail.isdigit():
            return int(tail)
    return default


def _sidecar_profile_proxy_url(sidecar: str, action: str) -> str:
    config = SIDECAR_PROFILE_PROXY_DEFAULTS.get(sidecar)
    if not config:
        raise HTTPException(status_code=404, detail="unsupported sidecar")
    if action not in SIDECAR_PROFILE_PROXY_ACTIONS:
        raise HTTPException(status_code=404, detail="unsupported sidecar profile action")
    port = _listen_port(os.environ.get(str(config["listen_env"])), int(config["port"]))
    return f"http://127.0.0.1:{port}/api/v1/profiles/{action}"


def _sidecar_profile_proxy_headers(sidecar: str) -> Dict[str, str]:
    config = SIDECAR_PROFILE_PROXY_DEFAULTS.get(sidecar) or {}
    for key in config.get("token_env", ()):
        token = os.environ.get(str(key), "").strip()
        if token:
            return {"Authorization": f"Bearer {token}"}
    return {}


def _sidecar_proxy_error_detail(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return (response.text or "sidecar request failed")[:500]


def _sidecar_proxy_error_text(response: requests.Response) -> str:
    detail = _sidecar_proxy_error_detail(response)
    try:
        return json.dumps(detail, sort_keys=True)
    except TypeError:
        return str(detail)


def _sidecar_proxy_requires_profile_token(sidecar: str, response: requests.Response) -> bool:
    if sidecar != "smart-wifi-manager":
        return False
    text = _sidecar_proxy_error_text(response)
    return (
        "SMART_WIFI_MANAGER_API_TOKEN is required" in text
        or "API_TOKEN is required for remote mutating requests" in text
    )


def _sidecar_proxy_has_smart_wifi_mode_error(sidecar: str, response: requests.Response) -> bool:
    if sidecar != "smart-wifi-manager":
        return False
    return "mode must be manage, observe, or disabled" in _sidecar_proxy_error_text(response)


def _should_repair_smart_wifi_config(sidecar: str, action: str, response: requests.Response) -> bool:
    if sidecar != "smart-wifi-manager" or action not in {"import", "apply"}:
        return False
    return _sidecar_proxy_has_smart_wifi_mode_error(sidecar, response)


def _repo_root() -> Path:
    return Path(os.environ.get("MDS_REPO_ROOT") or Path(__file__).resolve().parents[1]).resolve()


def _run_sidecar_reconcile_refresh(sidecar: str, action: str) -> Optional[Dict[str, Any]]:
    if action != "apply":
        return None
    config = SIDECAR_PROFILE_PROXY_DEFAULTS.get(sidecar) or {}
    script_relative = str(config.get("reconcile_script") or "").strip()
    if not script_relative:
        return None
    repo_root = _repo_root()
    script_path = repo_root / script_relative
    if not script_path.is_file():
        return {"ok": False, "status": "missing_helper"}

    command = [str(script_path), "apply", "--force", "--quiet"]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if not sudo:
            return {"ok": False, "status": "missing_privilege"}
        command = [sudo, "-n", *command]

    try:
        completed = subprocess.run(
            command,
            cwd=str(repo_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout"}
    except OSError:
        return {"ok": False, "status": "invoke_error"}
    if completed.returncode == 0:
        return {"ok": True, "status": "success"}
    return {"ok": False, "status": "failed", "exit_code": completed.returncode}


def _run_smart_wifi_service_mode_repair() -> Dict[str, Any]:
    install_dir = os.environ.get("MDS_SMART_WIFI_MANAGER_INSTALL_DIR", "/opt/smart-wifi-manager")
    configure_script = Path(install_dir) / "configure_smart_wifi_manager.sh"
    config_path = os.environ.get("MDS_SMART_WIFI_MANAGER_CONFIG_FILE", "/etc/smart-wifi-manager/config.json")
    if not configure_script.is_file():
        return {"ok": False, "status": "missing_helper"}

    command = [str(configure_script), "--headless", "--config", config_path, "--mode", "manage"]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if not sudo:
            return {"ok": False, "status": "missing_privilege"}
        command = [sudo, "-n", *command]

    try:
        completed = subprocess.run(
            command,
            cwd=str(_repo_root()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout"}
    except OSError:
        return {"ok": False, "status": "invoke_error"}
    if completed.returncode == 0:
        return {"ok": True, "status": "success"}
    return {"ok": False, "status": "failed", "exit_code": completed.returncode}


def _parse_reconcile_status_output(stdout: str) -> Dict[str, str]:
    status: Dict[str, str] = {}
    for raw_line in str(stdout or "").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        status[key.strip()] = value.strip()
    return status


def _run_sidecar_reconcile_status(sidecar: str) -> Dict[str, Any]:
    config = SIDECAR_PROFILE_PROXY_DEFAULTS.get(sidecar) or {}
    script_relative = str(config.get("reconcile_script") or "").strip()
    if not script_relative:
        return {"ok": False, "status": "missing_helper"}
    repo_root = _repo_root()
    script_path = repo_root / script_relative
    if not script_path.is_file():
        return {"ok": False, "status": "missing_helper"}

    try:
        completed = subprocess.run(
            [str(script_path), "status", "--quiet"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout"}
    except OSError:
        return {"ok": False, "status": "invoke_error"}
    if completed.returncode != 0:
        return {"ok": False, "status": "failed", "exit_code": completed.returncode}
    raw_status = _parse_reconcile_status_output(completed.stdout)
    public_status = {
        key: raw_status.get(key)
        for key in (
            "backend",
            "ref",
            "mode",
            "profile_hash",
            "desired_config_hash",
            "applied_config_hash",
            "config_hash_match",
            "service_status",
        )
        if raw_status.get(key)
    }
    return {"ok": True, "status": "success", "runtime": public_status}


def _smart_wifi_local_profile_fallback(action: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if action == "import":
        status = _run_sidecar_reconcile_status("smart-wifi-manager")
        if not status.get("ok"):
            return None
        runtime = status.get("runtime") if isinstance(status.get("runtime"), dict) else {}
        seed = json.dumps(
            {
                "sidecar": "smart-wifi-manager",
                "action": action,
                "mode": payload.get("mode"),
                "desired": runtime.get("desired_config_hash"),
                "applied": runtime.get("applied_config_hash"),
                "ts": int(time.time() * 1000),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        token = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return {
            "sidecar": "smart-wifi-manager",
            "dry_run": True,
            "dry_run_id": f"mds-local-reconcile-{token}",
            "confirmation_token": token,
            "mode": payload.get("mode") or runtime.get("mode") or "fleet-merge",
            "mutation_path": "mds-local-reconcile-helper",
            "runtime": runtime,
            "warnings": [
                "Smart Wi-Fi profile API token is not configured on this node; apply will use the node-local MDS reconcile helper."
            ],
        }
    if action == "apply":
        refresh = _run_sidecar_reconcile_refresh("smart-wifi-manager", "apply")
        if not refresh or not refresh.get("ok"):
            return None
        return {
            "sidecar": "smart-wifi-manager",
            "applied": True,
            "mutation_path": "mds-local-reconcile-helper",
            "mds_reconcile_refresh": refresh,
        }
    return None


# ============================================================================
# DroneAPIServer Class (FastAPI Version)
# ============================================================================

class DroneAPIServer:
    """
    Drone API Server using FastAPI.

    Provides:
    - Async/await for better performance
    - Automatic OpenAPI documentation
    - Type validation with Pydantic
    - Canonical typed drone routes
    - WebSocket support for real-time telemetry streaming
    """
    # Class-level flags to prevent log spam for expected SITL failures
    _network_info_error_logged = False
    _origin_fetch_error_logged = False
    _origin_fetch_last_issue = None

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
        # Uvicorn serves this node with one event loop. Keep the complete
        # command acceptance transaction serialized so an awaited cancel or
        # supersede cannot interleave with a second POST and clobber state.
        # Mission execution itself happens outside this request-scoped lock.
        self._command_transaction_lock = asyncio.Lock()
        shared_state_lock = getattr(drone_config, "command_state_transaction_lock", None)
        if not (
            callable(getattr(shared_state_lock, "acquire", None))
            and callable(getattr(shared_state_lock, "release", None))
        ):
            shared_state_lock = threading.Lock()
            setattr(drone_config, "command_state_transaction_lock", shared_state_lock)
        self._command_state_transaction_lock = shared_state_lock
        self._command_idempotency_lock = threading.RLock()
        self._command_idempotency_records: OrderedDict[str, _NodeCommandRecord] = OrderedDict()
        self._command_idempotency_ttl_sec = self._bounded_numeric_param(
            "COMMAND_IDEMPOTENCY_HISTORY_SEC",
            default=1800.0,
            minimum=60.0,
            integer=False,
        )
        self._command_idempotency_max_records = self._bounded_numeric_param(
            "COMMAND_IDEMPOTENCY_MAX_HISTORY",
            default=256,
            minimum=32,
            integer=True,
        )
        # Launch authority is deliberately process-local and short-lived. A
        # node restart invalidates every uncommitted preparation; the existing
        # command-history bound also caps token memory without a second knob.
        def typed_nonnegative_setting(name: str, default: float) -> float:
            raw = getattr(params, name, default)
            if type(raw) not in {int, float} or not math.isfinite(float(raw)):
                return default
            return max(0.0, float(raw))

        self._launch_preparation_store = LaunchPreparationStore(
            ttl_sec=calculate_launch_preparation_token_ttl_sec(params=params),
            max_records=int(self._command_idempotency_max_records),
            minimum_post_barrier_lead_sec=(
                typed_nonnegative_setting("trigger_sooner_seconds", 0.0)
                + typed_nonnegative_setting("COMMAND_SYNC_DISPATCH_GUARD_SEC", 1.0)
            ),
        )
        self._command_followup_tasks: Set[asyncio.Task] = set()
        self._command_followup_max_tasks = 32
        self._ulog_download_tasks: Set[asyncio.Task] = set()
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

        self.app.add_event_handler("shutdown", self._shutdown_ulog_download_tasks)
        self.app.add_event_handler("shutdown", self._shutdown_command_followup_tasks)
        self.setup_routes()

    def _bounded_numeric_param(
        self,
        name: str,
        *,
        default: float,
        minimum: float,
        integer: bool,
    ) -> float | int:
        """Read an optional numeric setting without treating Mock-like values as configuration."""
        raw_value = getattr(self.params, name, default)
        try:
            parsed = int(raw_value) if integer else float(raw_value)
        except (TypeError, ValueError):
            parsed = int(default) if integer else float(default)
        bounded = max(int(minimum), parsed) if integer else max(float(minimum), parsed)
        return bounded

    async def _command_transaction_guard(self):
        """Serialize HTTP commands with both other POSTs and scheduler claims."""
        async with self._command_transaction_lock:
            # The mission scheduler runs in another OS thread. Acquire its
            # lock in a worker so Uvicorn remains responsive. Cancellation is
            # handled explicitly: asyncio cannot stop a thread that is waiting
            # in Lock.acquire(), so we wait for that worker to finish and
            # release any lock it obtained before propagating cancellation.
            acquire_task = asyncio.create_task(
                asyncio.to_thread(self._command_state_transaction_lock.acquire)
            )
            try:
                acquired = await asyncio.shield(acquire_task)
            except BaseException:
                acquired = await acquire_task
                if acquired:
                    self._command_state_transaction_lock.release()
                raise
            try:
                yield
            finally:
                if acquired:
                    self._command_state_transaction_lock.release()

    def set_drone_communicator(self, drone_communicator):
        """Setter for injecting the DroneCommunicator dependency after initialization."""
        self.drone_communicator = drone_communicator

    def _register_command_report_capability(
        self,
        *,
        command_id: Optional[str],
        capability: Optional[str],
    ) -> None:
        """Bind callback authority before the scheduler can claim the command."""
        if capability is None:
            return
        drone_setup = getattr(self.drone_config, "drone_setup", None)
        register = getattr(drone_setup, "register_command_report_capability", None)
        if not callable(register):
            raise RuntimeError(
                "DroneSetup cannot register the command report capability"
            )
        register(command_id, capability)

    async def _shutdown_command_followup_tasks(self) -> None:
        """Cancel bounded best-effort callbacks during API shutdown."""
        tasks = tuple(self._command_followup_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._command_followup_tasks.clear()

    def _schedule_pending_command_superseded(
        self,
        *,
        command_id: Optional[str],
        override_mission_type: int,
    ) -> None:
        """Report prior-command retirement without delaying ACK or recovery.

        The mission transaction is already committed before this is called.
        GCS callback delivery is retryable bookkeeping, so a slow/unavailable
        GCS must not hold the node's scheduler lock or delay LAND/RTL/NONE.
        """
        if not command_id:
            return
        self._command_followup_tasks = {
            task for task in self._command_followup_tasks if not task.done()
        }
        if len(self._command_followup_tasks) >= self._command_followup_max_tasks:
            logger.error(
                "Supersede callback queue is full; GCS must reconcile command_id=%s by timeout/state evidence.",
                command_id,
            )
            return

        task = asyncio.create_task(
            self._report_pending_command_superseded(
                command_id=command_id,
                override_mission_type=override_mission_type,
            )
        )
        self._command_followup_tasks.add(task)

        def _retire_followup(completed_task: asyncio.Task) -> None:
            self._command_followup_tasks.discard(completed_task)
            if completed_task.cancelled():
                return
            try:
                exc = completed_task.exception()
            except asyncio.CancelledError:
                return
            if exc is not None:
                logger.error(
                    "Unhandled supersede callback failure for command_id=%s: %s",
                    command_id,
                    exc,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

        task.add_done_callback(_retire_followup)

    def _resolve_live_probe_connection(self) -> Tuple[int, str]:
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

    @staticmethod
    def _build_mavsdk_server_capability_payload() -> Dict[str, Any]:
        env_path = os.environ.get("MAVSDK_SERVER_PATH")
        candidates = [
            env_path,
            os.path.join(BASE_DIR, "mavsdk_server"),
            os.path.join(os.path.dirname(BASE_DIR), "mavsdk_server"),
        ]
        selected_path = next((candidate for candidate in candidates if candidate and os.path.isfile(candidate)), None)
        present = selected_path is not None
        executable = bool(selected_path and os.access(selected_path, os.X_OK))

        if executable:
            missing_dependency = None
            detail = "mavsdk_server is present and executable."
        elif present:
            missing_dependency = "mavsdk_server_not_executable"
            detail = "mavsdk_server exists but is not executable on this node."
        else:
            missing_dependency = "mavsdk_server_missing"
            detail = "mavsdk_server is missing on this node."

        return {
            "available": executable,
            "mavsdk_server_present": present,
            "mavsdk_server_executable": executable,
            "mavsdk_server_path": selected_path or os.path.join(BASE_DIR, "mavsdk_server"),
            "filesystem_fallback_configured": False,
            "filesystem_fallback_paths": [],
            "filesystem_fallback_existing_paths": [],
            "missing_dependency": missing_dependency,
            "detail": detail,
        }

    def _build_ulog_capability(self) -> OnboardUlogCapability:
        mavsdk_server_path: Optional[str] = None
        mavsdk_server_present = False
        mavsdk_server_executable = False
        missing_dependency: Optional[str] = None

        try:
            mavsdk_server_path = self._find_mavsdk_server_binary()
            mavsdk_server_present = True
            mavsdk_server_executable = os.access(mavsdk_server_path, os.X_OK)
            if not mavsdk_server_executable:
                missing_dependency = "mavsdk_server_not_executable"
        except FileNotFoundError:
            missing_dependency = "mavsdk_server_missing"

        fallback_paths = [
            str(path)
            for path in self._ulog_service.filesystem_fallback_dirs()
        ]
        existing_fallback_paths = []
        for path in fallback_paths:
            try:
                if Path(path).exists():
                    existing_fallback_paths.append(path)
            except OSError as exc:
                logger.debug("Skipping inaccessible ULog fallback path %s: %s", path, exc)
        filesystem_fallback_configured = bool(fallback_paths)
        available = mavsdk_server_executable or bool(existing_fallback_paths)

        if available:
            detail = "ULog access is available through MAVSDK or configured filesystem fallback."
            if mavsdk_server_present and not mavsdk_server_executable and existing_fallback_paths:
                detail = "MAVSDK server is not executable; filesystem fallback is available."
        elif missing_dependency == "mavsdk_server_missing":
            detail = "mavsdk_server is missing and no configured filesystem fallback path exists on this node."
        elif missing_dependency == "mavsdk_server_not_executable":
            detail = "mavsdk_server exists but is not executable and no configured filesystem fallback path exists on this node."
        else:
            detail = "ULog capability could not be established."

        return OnboardUlogCapability(
            available=available,
            mavsdk_server_present=mavsdk_server_present,
            mavsdk_server_executable=mavsdk_server_executable,
            mavsdk_server_path=mavsdk_server_path,
            filesystem_fallback_configured=filesystem_fallback_configured,
            filesystem_fallback_paths=fallback_paths,
            filesystem_fallback_existing_paths=existing_fallback_paths,
            missing_dependency=missing_dependency if not available else None,
            detail=detail,
        )

    def _build_ulog_capability_payload(self) -> Dict[str, Any]:
        try:
            return self._build_ulog_capability().model_dump()
        except Exception as exc:
            logger.warning("ULog capability probe failed during health check: %s", exc)
            return {
                "available": False,
                "mavsdk_server_present": False,
                "mavsdk_server_executable": False,
                "mavsdk_server_path": os.path.join(BASE_DIR, "mavsdk_server"),
                "filesystem_fallback_configured": False,
                "filesystem_fallback_paths": [],
                "filesystem_fallback_existing_paths": [],
                "missing_dependency": "ulog_capability_probe_failed",
                "detail": f"ULog capability probe failed: {exc.__class__.__name__}",
            }

    @staticmethod
    def _is_mavsdk_dependency_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            isinstance(exc, FileNotFoundError)
            and "mavsdk_server" in message
        ) or (
            isinstance(exc, PermissionError)
            and "mavsdk_server" in message
        )

    def _ulog_failure_http_exception(self, action: str, exc: Exception) -> HTTPException:
        capability = self._build_ulog_capability_payload()
        message = str(exc) or exc.__class__.__name__
        lowered = message.lower()

        typed_status = getattr(exc, "http_status", None)
        typed_code = getattr(exc, "code", None)
        if isinstance(typed_status, int) and isinstance(typed_code, str):
            return HTTPException(
                status_code=typed_status,
                detail={
                    "error": typed_code,
                    "message": message,
                    "action": action,
                    "ulog_capability": capability,
                },
            )

        if isinstance(exc, TimeoutError):
            return HTTPException(
                status_code=504,
                detail={
                    "error": "ulog_summary_timeout",
                    "message": message,
                    "action": action,
                    "ulog_capability": capability,
                },
            )

        if self._is_mavsdk_dependency_error(exc):
            error = capability.get("missing_dependency") or "mavsdk_server_unavailable"
            return HTTPException(
                status_code=424,
                detail={
                    "error": error,
                    "message": message,
                    "action": action,
                    "ulog_capability": capability,
                },
            )

        if isinstance(exc, (TimeoutError, ConnectionError, RuntimeError)) and (
            "mavsdk" in lowered
            or "connection" in lowered
            or "timed out" in lowered
            or "probe" in lowered
        ):
            return HTTPException(
                status_code=503,
                detail={
                    "error": "ulog_transport_unavailable",
                    "message": message,
                    "action": action,
                    "ulog_capability": capability,
                },
            )

        return HTTPException(
            status_code=500,
            detail={
                "error": "ulog_operation_failed",
                "message": message,
                "action": action,
                "ulog_capability": capability,
            },
        )

    def _px4_param_failure_http_exception(self, action: str, exc: Exception) -> HTTPException:
        capability = self._build_mavsdk_server_capability_payload()
        message = str(exc) or exc.__class__.__name__
        lowered = message.lower()

        if self._is_mavsdk_dependency_error(exc):
            error = capability.get("missing_dependency") or "mavsdk_server_unavailable"
            return HTTPException(
                status_code=424,
                detail={
                    "error": error,
                    "message": message,
                    "action": action,
                    "mavsdk_capability": capability,
                },
            )

        if isinstance(exc, (TimeoutError, ConnectionError, RuntimeError)) and (
            "mavsdk" in lowered
            or "connection" in lowered
            or "timed out" in lowered
            or "param" in lowered
        ):
            return HTTPException(
                status_code=503,
                detail={
                    "error": "px4_params_transport_unavailable",
                    "message": message,
                    "action": action,
                    "mavsdk_capability": capability,
                },
            )

        return HTTPException(
            status_code=500,
            detail={
                "error": "px4_params_operation_failed",
                "message": message,
                "action": action,
                "mavsdk_capability": capability,
            },
        )

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
        probe_started_monotonic = time.monotonic()
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
                        await asyncio.to_thread(
                            self._stop_live_probe_server,
                            mavsdk_server,
                        )
            response_generated_at_ms = int(time.time() * 1000)
            observation = result.get("observation") if isinstance(result.get("observation"), dict) else {}
            try:
                valid_until_ms = int(observation.get("valid_until_ms"))
            except (TypeError, ValueError):
                valid_until_ms = 0
            return {
                "hw_id": str(self.drone_config.hw_id),
                "success": True,
                **result,
                # Freshness crosses hosts as durations, never as comparable
                # wall-clock instants. The GCS subtracts transport time from
                # this node-computed remaining lease.
                "remaining_valid_ms": max(0, valid_until_ms - response_generated_at_ms),
                "server_processing_ms": max(
                    0,
                    int((time.monotonic() - probe_started_monotonic) * 1000),
                ),
                "timestamp": response_generated_at_ms,
                "probe_error": None,
            }
        except Exception as exc:
            timed_out = isinstance(exc, (TimeoutError, asyncio.TimeoutError))
            return {
                "hw_id": str(self.drone_config.hw_id),
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
                "remaining_valid_ms": 0,
                "server_processing_ms": max(
                    0,
                    int((time.monotonic() - probe_started_monotonic) * 1000),
                ),
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
                    await asyncio.to_thread(
                        self._stop_live_probe_server,
                        mavsdk_server,
                    )

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
                    await asyncio.to_thread(
                        self._stop_live_probe_server,
                        mavsdk_server,
                    )

    async def _run_ulog_download_job(self, job_id: str) -> None:
        """Complete a queued onboard ULog download in the background."""
        try:
            await self._with_local_ulog_system(
                lambda drone: self._ulog_service.perform_download(drone, job_id)
            )
        except asyncio.CancelledError:
            await self._ulog_service.mark_job_failed(job_id, "ULog download cancelled during shutdown")
            raise
        except Exception as exc:
            logger.error(f"Onboard ULog download job {job_id} failed before completion: {exc}")
            await self._ulog_service.mark_job_failed(job_id, str(exc))

    def _start_ulog_download_task(self, job_id: str) -> None:
        task = asyncio.create_task(self._run_ulog_download_job(job_id))
        self._ulog_download_tasks.add(task)
        task.add_done_callback(self._ulog_download_tasks.discard)

    async def _shutdown_ulog_download_tasks(self) -> None:
        tasks = tuple(self._ulog_download_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._ulog_download_tasks.clear()

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

    def _require_ulog_machine_credential(
        self,
        request: Request,
        *,
        operation: str,
    ) -> None:
        token_file = os.environ.get("MDS_GCS_API_TOKEN_FILE", "").strip()
        if not token_file:
            if not getattr(self, "_ulog_open_mode_warning_logged", False):
                logger.warning(
                    "Onboard ULog routes are using trusted-network demo mode "
                    "without GCS machine authentication. Configure "
                    "MDS_GCS_API_TOKEN_FILE for hardened deployments."
                )
                self._ulog_open_mode_warning_logged = True
            return

        bearer_token = read_gcs_api_token()
        if not bearer_token:
            raise HTTPException(
                status_code=503,
                detail="Node machine authentication is configured but unavailable.",
            )
        credential = request.headers.get(MACHINE_CREDENTIAL_HEADER)
        if not credential:
            raise HTTPException(
                status_code=401,
                detail="GCS machine credential is required.",
            )
        audience = f"mds-drone:{str(getattr(self.drone_config, 'hw_id', '')).strip()}"
        if verify_machine_credential(
            credential,
            bearer_token=bearer_token,
            audience=audience,
            operation=operation,
        ) is None:
            raise HTTPException(
                status_code=401,
                detail="GCS machine credential is invalid or expired.",
            )

    async def _assert_ulog_job_access(
        self,
        job_id: str,
        access_token: str | None,
    ) -> None:
        if not await self._ulog_service.authorize_job(job_id, access_token):
            raise HTTPException(status_code=404, detail=f"ULog download job {job_id} not found")

    async def _evaluate_launch_commit_admission(
        self,
        command: DroneCommandRequest,
        launch_preparation_token: Optional[str],
    ) -> _LaunchCommitAdmission:
        """Consume launch authority and revalidate readiness before locking.

        The command transaction remains short, so recovery commands retain a
        responsive path. The returned monotonic lease is checked again after
        the lock is acquired to prevent queued launch installation from using
        an observation that expired while another command committed.
        """
        mission_type = int(command.mission_type)
        launch_required = mission_requires_launch_armability_probe(mission_type)
        if not launch_required:
            if launch_preparation_token is not None:
                return _LaunchCommitAdmission(
                    command=command,
                    launch_required=False,
                    authorized=False,
                    error_code=CommandErrorCode.INVALID_FORMAT.value,
                    error_detail=(
                        "Launch preparation tokens are valid only for launch missions"
                    ),
                )
            return _LaunchCommitAdmission(
                command=command,
                launch_required=False,
                authorized=True,
            )

        command_data = command.model_dump(mode="json", exclude_none=True)
        command_id = command_data.get("command_id")
        if type(command_id) is str and command_id:
            semantic_identity = self._command_semantic_identity(command_data)
            with self._command_idempotency_lock:
                existing_record = self._command_idempotency_records.get(command_id)
                if existing_record is not None:
                    # The in-lock route path will return either the exact
                    # authoritative replay or a semantic conflict. Never
                    # consume a second token or re-run launch admission for a
                    # command whose execution decision already exists.
                    return _LaunchCommitAdmission(
                        command=command,
                        launch_required=True,
                        authorized=False,
                        existing_record_seen=True,
                        error_code=(
                            None
                            if existing_record.semantic_identity.fingerprint
                            == semantic_identity.fingerprint
                            else CommandErrorCode.INVALID_FORMAT.value
                        ),
                        error_detail=(
                            None
                            if existing_record.semantic_identity.fingerprint
                            == semantic_identity.fingerprint
                            else "Command ID already exists with a different canonical payload"
                        ),
                    )

        preparation_result = self._launch_preparation_store.consume(
            launch_preparation_token,
            command,
        )
        if not preparation_result.consumed:
            error_code = (
                CommandErrorCode.PREFLIGHT_FAILED.value
                if preparation_result.status
                in {
                    LaunchPreparationConsumeStatus.EXPIRED,
                    LaunchPreparationConsumeStatus.REPLAYED,
                }
                else CommandErrorCode.INVALID_FORMAT.value
            )
            return _LaunchCommitAdmission(
                command=command,
                launch_required=True,
                authorized=False,
                error_code=error_code,
                error_detail=preparation_result.detail,
            )

        try:
            probe = await self._probe_live_armability(require_global_position=True)
            envelope = LiveArmabilityResponse(**probe)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Commit-time launch readiness unavailable for command_id=%s: %s",
                command_id,
                exc,
            )
            return _LaunchCommitAdmission(
                command=command,
                launch_required=True,
                authorized=False,
                error_code=CommandErrorCode.PREFLIGHT_FAILED.value,
                error_detail="Commit-time live launch readiness could not be established",
            )

        local_hw_id = str(self.drone_config.hw_id)
        if envelope.hw_id != local_hw_id:
            return _LaunchCommitAdmission(
                command=command,
                launch_required=True,
                authorized=False,
                error_code=CommandErrorCode.TARGET_IDENTITY_MISMATCH.value,
                error_detail=(
                    "Commit-time readiness came from a different hardware identity"
                ),
            )
        if not envelope.ready:
            blockers = (
                envelope.observation.blockers
                if envelope.observation is not None
                else []
            )
            return _LaunchCommitAdmission(
                command=command,
                launch_required=True,
                authorized=False,
                error_code=CommandErrorCode.PREFLIGHT_FAILED.value,
                error_detail=(
                    "; ".join(blockers)
                    or envelope.summary
                    or "Commit-time launch readiness conditions were not met"
                ),
            )

        return _LaunchCommitAdmission(
            command=command,
            launch_required=True,
            authorized=True,
            readiness_valid_until_monotonic=(
                time.monotonic() + (envelope.remaining_valid_ms / 1_000.0)
            ),
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

    @staticmethod
    def _serialize_swarm_state_payload(swarm_state: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Smart Swarm leader-state payloads into the canonical route contract."""
        payload = dict(swarm_state)
        payload["emitted_at_ms"] = safe_int(payload.get("emitted_at_ms"), int(time.time() * 1000))
        return SwarmStateResponse.model_validate(payload).model_dump()

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

        @self.app.get(DRONE_SWARM_STATE_ROUTE, response_model=SwarmStateResponse)
        async def get_swarm_state():
            """Endpoint to retrieve the high-rate Smart Swarm state payload."""
            try:
                swarm_state = self.drone_communicator.get_swarm_state()
                if swarm_state:
                    return self._serialize_swarm_state_payload(swarm_state)
                raise HTTPException(status_code=404, detail="Swarm state not found")
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"error_in_get_swarm_state: {str(exc)}")

        @self.app.get(DRONE_LIVE_ARMABILITY_ROUTE, response_model=LiveArmabilityResponse)
        async def get_live_armability(require_global_position: bool = True):
            """Run an on-demand MAVSDK launch-readiness probe."""
            result = await self._probe_live_armability(require_global_position=require_global_position)
            return LiveArmabilityResponse(**result)

        @self.app.post(
            DRONE_LAUNCH_PREPARATION_ROUTE,
            response_model=LaunchPreparationResponse,
        )
        async def prepare_launch(
            request: LaunchPreparationRequest,
        ) -> LaunchPreparationResponse:
            """Issue one command-bound launch token after a live node probe."""
            started = time.monotonic()
            command = request.command
            command_id = command.command_id
            target_hw_id = command.target_hw_id
            local_hw_id = str(self.drone_config.hw_id)
            payload_digest = immutable_command_payload_sha256(command)

            if target_hw_id != local_hw_id:
                return LaunchPreparationResponse(
                    status="rejected",
                    command_id=command_id,
                    target_hw_id=local_hw_id,
                    mission_type=command.mission_type,
                    immutable_payload_sha256=payload_digest,
                    ready=False,
                    summary="Launch preparation reached a different drone than the selected target",
                    preparation_token=None,
                    token_ttl_ms=0,
                    server_processing_ms=max(
                        0,
                        int((time.monotonic() - started) * 1_000),
                    ),
                    error_code=CommandErrorCode.TARGET_IDENTITY_MISMATCH.value,
                    error_detail=(
                        f"Intended hardware ID={target_hw_id}; receiving hardware ID={local_hw_id}"
                    ),
                )

            try:
                probe = await self._probe_live_armability(
                    require_global_position=request.require_global_position,
                )
                envelope = LiveArmabilityResponse(**probe)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Command-bound launch preparation unavailable for command_id=%s: %s",
                    command_id,
                    exc,
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error_code": CommandErrorCode.PREFLIGHT_FAILED.value,
                        "message": "Live launch readiness could not be established",
                        "error_detail": "No launch token was issued",
                    },
                ) from exc

            if not envelope.ready:
                return LaunchPreparationResponse(
                    status="rejected",
                    command_id=command_id,
                    target_hw_id=local_hw_id,
                    mission_type=command.mission_type,
                    immutable_payload_sha256=payload_digest,
                    ready=False,
                    summary=envelope.summary,
                    observation=envelope.observation,
                    preparation_token=None,
                    token_ttl_ms=0,
                    server_processing_ms=max(
                        0,
                        int((time.monotonic() - started) * 1_000),
                    ),
                    error_code=CommandErrorCode.PREFLIGHT_FAILED.value,
                    error_detail=(
                        "; ".join(envelope.observation.blockers)
                        or "Current PX4 launch readiness conditions were not met"
                    ),
                )

            try:
                binding = LaunchPreparationBinding.from_command(command)
                token, token_ttl_ms = self._launch_preparation_store.issue(binding)
            except (RuntimeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Launch preparation token could not be issued for command_id=%s: %s",
                    command_id,
                    exc,
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error_code": CommandErrorCode.PREFLIGHT_FAILED.value,
                        "message": "Launch preparation authority is temporarily unavailable",
                        "error_detail": "No launch token was issued",
                    },
                ) from exc

            return LaunchPreparationResponse(
                status="prepared",
                command_id=command_id,
                target_hw_id=local_hw_id,
                mission_type=command.mission_type,
                immutable_payload_sha256=payload_digest,
                ready=True,
                summary=envelope.summary,
                observation=envelope.observation,
                preparation_token=token,
                token_ttl_ms=token_ttl_ms,
                server_processing_ms=max(
                    0,
                    int((time.monotonic() - started) * 1_000),
                ),
            )

        async def evaluate_command_admission(
            command: DroneCommandRequest,
            launch_preparation_token: Optional[str] = Header(
                None,
                alias=LAUNCH_PREPARATION_TOKEN_HEADER,
            ),
        ) -> _LaunchCommitAdmission:
            return await self._evaluate_launch_commit_admission(
                command,
                launch_preparation_token,
            )

        async def admitted_command_transaction(
            admission: _LaunchCommitAdmission = Depends(evaluate_command_admission),
        ):
            # The launch probe above never owns the scheduler transaction lock;
            # recovery admission therefore cannot queue behind network I/O.
            async for _ in self._command_transaction_guard():
                yield admission

        @self.app.post(DRONE_COMMANDS_ROUTE, response_model=CommandAckResponse)
        async def send_drone_command(
            admission: _LaunchCommitAdmission = Depends(admitted_command_transaction),
        ) -> CommandAckResponse:
            """
            Endpoint to send a command to the drone.

            Returns detailed acknowledgment with status and error codes.
            No longer returns generic HTTP 500 - all errors return structured response.
            """
            command = admission.command
            timestamp = int(time.time() * 1000)
            hw_id = str(self.drone_config.hw_id)
            pos_id = int(self.drone_config.pos_id)
            current_state = int(self.drone_config.state)
            command_data: Dict[str, Any] = {}
            command_id: Optional[str] = None
            mission_type: Optional[int] = None
            trigger_time: Optional[int] = None
            command_report_capability: Optional[str] = None
            idempotency_record: Optional[_NodeCommandRecord] = None
            mutation_started = False
            command_committed = False
            state_snapshot = _CommandStateSnapshot(
                command_id=getattr(self.drone_config, "current_command_id", None),
                mission_type=int(self.drone_config.mission),
                trigger_time=int(getattr(self.drone_config, "trigger_time", 0) or 0),
                state=current_state,
            )

            try:
                command_data = command.model_dump(mode="json", exclude_none=True)
                command_report_capability = command_data.get("command_report_capability")
                command_id = command_data.get('command_id')
                if command_id is not None:
                    command_id = str(command_id).strip()
                    if not command_id or len(command_id) > 200:
                        return CommandAckResponse(
                            status="rejected",
                            command_id=command_id or None,
                            hw_id=hw_id,
                            pos_id=pos_id,
                            current_state=current_state,
                            message="command_id must contain between 1 and 200 characters",
                            error_code=CommandErrorCode.INVALID_FORMAT.value,
                            command_phase="terminal",
                            command_outcome="rejected",
                            timestamp=timestamp,
                        )
                    command_data['command_id'] = command_id

                # Bind the selected fleet target to the node that received the
                # request. A stale IP mapping must not command the wrong drone.
                target_hw_id = command_data.get('target_hw_id')
                if target_hw_id is not None and str(target_hw_id).strip() != hw_id:
                    logger.error(
                        "Command target identity mismatch: intended hw_id=%s, receiving hw_id=%s, command_id=%s",
                        target_hw_id,
                        hw_id,
                        command_id,
                    )
                    return CommandAckResponse(
                        status="rejected",
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        message="Command reached a different drone than the selected target",
                        error_code=CommandErrorCode.TARGET_IDENTITY_MISMATCH.value,
                        error_detail=(
                            f"Intended hardware ID={str(target_hw_id).strip()}; "
                            f"receiving hardware ID={hw_id}"
                        ),
                        timestamp=timestamp,
                    )

                mission_type = int(command_data["mission_type"])
                trigger_time = int(command_data.get("trigger_time", 0))
                if mission_type == Mission.TEST.value:
                    try:
                        command.ground_test_safety.validate_for_runtime(
                            sim_mode=bool(getattr(self.params, "sim_mode", False))
                        )
                    except (AttributeError, ValueError) as exc:
                        logger.warning(
                            "Ground-test safety acknowledgement rejected before command installation: %s",
                            exc,
                        )
                        return CommandAckResponse(
                            status="rejected",
                            command_id=command_id,
                            hw_id=hw_id,
                            pos_id=pos_id,
                            current_state=current_state,
                            mission_type=mission_type,
                            trigger_time=trigger_time,
                            message="Arm/Disarm Ground Test safety acknowledgement does not match this runtime",
                            error_code=CommandErrorCode.INVALID_FORMAT.value,
                            error_detail=str(exc),
                            command_phase="terminal",
                            command_outcome="rejected",
                            timestamp=timestamp,
                        )
                semantic_identity = self._command_semantic_identity(command_data)
                known_command = self._find_active_command_by_id(command_id)
                idempotency_classification, idempotency_record, conflict_detail = (
                    self._begin_command_idempotency(
                        command_id=command_id,
                        semantic_identity=semantic_identity,
                        mission_type=mission_type,
                        trigger_time=trigger_time,
                        known_command=known_command,
                    )
                )
                if idempotency_classification == "conflict":
                    return self._command_idempotency_conflict_response(
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        mission_type=mission_type,
                        trigger_time=trigger_time,
                        detail=conflict_detail or "Canonical command payload differs.",
                        timestamp=timestamp,
                    )
                if idempotency_classification == "capacity":
                    logger.error(
                        "Command idempotency registry is at protected capacity; rejecting command_id=%s",
                        command_id,
                    )
                    return CommandAckResponse(
                        status="rejected",
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        mission_type=mission_type,
                        trigger_time=trigger_time,
                        message="Node command history is temporarily at protected capacity",
                        error_code=CommandErrorCode.INTERNAL_ERROR.value,
                        error_detail=(
                            "No terminal idempotency record can be evicted safely; retry this same "
                            "command ID after an active command reaches a terminal state."
                        ),
                        command_phase="terminal",
                        command_outcome="rejected",
                        timestamp=timestamp,
                    )
                if idempotency_classification == "replay" and idempotency_record is not None:
                    return self._build_idempotent_replay_response(
                        record=idempotency_record,
                        known_command=known_command,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        timestamp=timestamp,
                    )

                if not admission.authorized:
                    logger.warning(
                        "Command admission rejected before mutation: command_id=%s launch_required=%s detail=%s",
                        command_id,
                        admission.launch_required,
                        admission.error_detail,
                    )
                    response = CommandAckResponse(
                        status="rejected",
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        mission_type=mission_type,
                        trigger_time=trigger_time,
                        message=(
                            "Launch commit did not present current prepared authority"
                            if admission.launch_required
                            else "Command carried launch authority outside a launch mission"
                        ),
                        error_code=(
                            admission.error_code
                            or CommandErrorCode.PREFLIGHT_FAILED.value
                        ),
                        error_detail=(
                            admission.error_detail
                            or "No command was installed"
                        ),
                        timestamp=timestamp,
                    )
                    return self._finalize_command_idempotency(
                        idempotency_record,
                        response,
                        phase="rejected",
                        outcome="rejected",
                    )

                if (
                    admission.launch_required
                    and (
                        admission.readiness_valid_until_monotonic is None
                        or time.monotonic()
                        >= admission.readiness_valid_until_monotonic
                    )
                ):
                    response = CommandAckResponse(
                        status="rejected",
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        mission_type=mission_type,
                        trigger_time=trigger_time,
                        message="Commit-time launch readiness expired before command installation",
                        error_code=CommandErrorCode.PREFLIGHT_FAILED.value,
                        error_detail="Prepare and validate the launch again; no command was installed",
                        timestamp=timestamp,
                    )
                    return self._finalize_command_idempotency(
                        idempotency_record,
                        response,
                        phase="rejected",
                        outcome="rejected",
                    )

                # Validate command structure
                validation_result = self._validate_command(command_data)
                if not validation_result['valid']:
                    logger.warning(f"Command rejected: {validation_result['message']}")
                    response = CommandAckResponse(
                        status="rejected",
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        message=validation_result['message'],
                        error_code=validation_result['error_code'],
                        error_detail=validation_result.get('detail'),
                        timestamp=timestamp,
                    )
                    return self._finalize_command_idempotency(
                        idempotency_record,
                        response,
                        phase="rejected",
                        outcome="rejected",
                    )

                previous_command_id = state_snapshot.command_id
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
                    response = CommandAckResponse(
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
                        timestamp=timestamp,
                    )
                    return self._finalize_command_idempotency(
                        idempotency_record,
                        response,
                        phase="rejected",
                        outcome="rejected",
                    )

                if mission_type == Mission.NONE.value:
                    had_active_command = current_state in {
                        State.MISSION_READY.value,
                        State.MISSION_EXECUTING.value,
                    }
                    superseded_pending_cancel = (
                        current_state == State.MISSION_READY.value
                        and previous_command_id
                        and previous_command_id != command_id
                    )

                    mutation_started = True
                    self.drone_config.current_command_id = command_id
                    self._register_command_report_capability(
                        command_id=command_id,
                        capability=command_report_capability,
                    )
                    new_state, cancel_message = await self._cancel_active_or_pending_command(
                        had_active_command=had_active_command,
                    )
                    command_committed = True
                    if superseded_pending_cancel:
                        self._schedule_pending_command_superseded(
                            command_id=previous_command_id,
                            override_mission_type=mission_type,
                        )
                    logger.info(f"Command accepted: CANCEL (trigger: {trigger_time})")
                    response = CommandAckResponse(
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
                    return self._finalize_command_idempotency(
                        idempotency_record,
                        response,
                        phase="completed",
                        outcome="completed",
                    )

                # DroneCommunicator owns the one prepare -> artifact/config
                # commit-or-rollback contract. The API deliberately does not
                # duplicate mission-field writers or a legacy install path.
                installation_payload = {
                    key: value
                    for key, value in command_data.items()
                    if key != "command_report_capability"
                }
                mutation_started = True
                installation_result = self.drone_communicator.process_command(
                    installation_payload
                )
                if not (
                    isinstance(installation_result, CommandInstallationResult)
                    and installation_result.committed
                    and installation_result.command_id == command_id
                    and getattr(self.drone_config, "current_command_id", None) == command_id
                ):
                    raise RuntimeError(
                        "Communicator returned without verifiable command ownership commit"
                    )

                command_committed = True
                self._register_command_report_capability(
                    command_id=command_id,
                    capability=command_report_capability,
                )

                if superseded_pending_command:
                    self._schedule_pending_command_superseded(
                        command_id=previous_command_id,
                        override_mission_type=mission_type,
                    )

                # Get mission name for message
                try:
                    mission_name = Mission(mission_type).name
                except ValueError:
                    mission_name = f"MISSION_{mission_type}"

                logger.info(f"Command accepted: {mission_name} (trigger: {trigger_time})")
                response = CommandAckResponse(
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
                    timestamp=timestamp,
                )
                return self._finalize_command_idempotency(
                    idempotency_record,
                    response,
                    phase="pending",
                )

            except asyncio.CancelledError as exc:
                if mutation_started:
                    self._record_post_mutation_command_uncertainty(
                        record=idempotency_record,
                        command_id=command_id,
                        hw_id=hw_id,
                        pos_id=pos_id,
                        current_state=current_state,
                        mission_type=mission_type,
                        trigger_time=trigger_time,
                        state_snapshot=state_snapshot,
                        exc=exc,
                        timestamp=timestamp,
                    )
                raise
            except HTTPException:
                # Lifecycle replay deliberately uses HTTP 503 for an
                # unresolved post-mutation outcome. Preserve that transport
                # classification instead of flattening it into a fresh
                # pre-commit rejection in the generic exception handler.
                raise
            except CommandInstallationRejected as e:
                # The communicator raises this only after proving that every
                # published artifact/config field was restored.  It is a
                # definite rejection even when its reversible commit phase had
                # started, so do not mislabel it as delivery_unknown.
                logger.error(
                    "Command installation rejected during %s: %s",
                    e.phase,
                    e,
                )
                return self._handle_command_processing_exception(
                    record=idempotency_record,
                    command_id=command_id,
                    hw_id=hw_id,
                    pos_id=pos_id,
                    current_state=current_state,
                    mission_type=mission_type,
                    trigger_time=trigger_time,
                    mutation_started=False,
                    command_committed=False,
                    state_snapshot=state_snapshot,
                    exc=e,
                    precommit_message="Command was not installed",
                    precommit_error_code=CommandErrorCode.INTERNAL_ERROR.value,
                    precommit_error_detail=f"{e.phase}: {str(e)}",
                    timestamp=timestamp,
                )
            except KeyError as e:
                logger.error(f"Missing field in command: {e}")
                return self._handle_command_processing_exception(
                    record=idempotency_record,
                    command_id=command_id,
                    hw_id=hw_id,
                    pos_id=pos_id,
                    current_state=current_state,
                    mission_type=mission_type,
                    trigger_time=trigger_time,
                    mutation_started=mutation_started,
                    command_committed=command_committed,
                    state_snapshot=state_snapshot,
                    exc=e,
                    precommit_message=f"Missing required field: {str(e)}",
                    precommit_error_code=CommandErrorCode.MISSING_MISSION_TYPE.value,
                    precommit_error_detail=str(e),
                    timestamp=timestamp,
                )
            except ValueError as e:
                logger.error(f"Invalid value in command: {e}")
                return self._handle_command_processing_exception(
                    record=idempotency_record,
                    command_id=command_id,
                    hw_id=hw_id,
                    pos_id=pos_id,
                    current_state=current_state,
                    mission_type=mission_type,
                    trigger_time=trigger_time,
                    mutation_started=mutation_started,
                    command_committed=command_committed,
                    state_snapshot=state_snapshot,
                    exc=e,
                    precommit_message=f"Invalid value: {str(e)}",
                    precommit_error_code=CommandErrorCode.INVALID_FORMAT.value,
                    precommit_error_detail=str(e),
                    timestamp=timestamp,
                )
            except AttributeError as e:
                logger.error(f"Configuration attribute error: {e}")
                return self._handle_command_processing_exception(
                    record=idempotency_record,
                    command_id=command_id,
                    hw_id=hw_id,
                    pos_id=pos_id,
                    current_state=current_state,
                    mission_type=mission_type,
                    trigger_time=trigger_time,
                    mutation_started=mutation_started,
                    command_committed=command_committed,
                    state_snapshot=state_snapshot,
                    exc=e,
                    precommit_message=f"Configuration error: {str(e)}",
                    precommit_error_code=CommandErrorCode.INTERNAL_ERROR.value,
                    precommit_error_detail=f"AttributeError: {str(e)} - Check drone configuration",
                    timestamp=timestamp,
                )
            except Exception as e:
                logger.exception(f"Unexpected error processing command: {e}")
                return self._handle_command_processing_exception(
                    record=idempotency_record,
                    command_id=command_id,
                    hw_id=hw_id,
                    pos_id=pos_id,
                    current_state=current_state,
                    mission_type=mission_type,
                    trigger_time=trigger_time,
                    mutation_started=mutation_started,
                    command_committed=command_committed,
                    state_snapshot=state_snapshot,
                    exc=e,
                    precommit_message=f"Internal error: {str(e)}",
                    precommit_error_code=CommandErrorCode.INTERNAL_ERROR.value,
                    precommit_error_detail=str(e),
                    timestamp=timestamp,
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
            git_report = get_local_git_report(repo_path=BASE_DIR)
            if git_report.get("error"):
                raise HTTPException(status_code=500, detail=git_report["error"])

            return {
                'hw_id': str(self.drone_config.hw_id),
                'branch': git_report.get('branch', ''),
                'commit': git_report.get('commit', ''),
                'author_name': git_report.get('author_name', ''),
                'author_email': git_report.get('author_email', ''),
                'commit_date': git_report.get('commit_date', ''),
                'commit_message': git_report.get('commit_message', ''),
                'remote_url': git_report.get('remote_url') or '',
                'tracking_branch': git_report.get('tracking_branch') or '',
                'status': git_report.get('status', 'unknown'),
                'uncommitted_changes': git_report.get('uncommitted_changes', []),
                'commits_ahead': git_report.get('commits_ahead', 0),
                'commits_behind': git_report.get('commits_behind', 0),
                'repo_access_mode': git_report.get('repo_access_mode', 'custom_or_unknown'),
                'git_auth_health_status': git_report.get('git_auth_health_status', 'unknown'),
                'git_auth_health_summary': git_report.get('git_auth_health_summary', ''),
                'git_auth_health_issues': git_report.get('git_auth_health_issues', []),
                'mavlink_runtime': build_mavlink_runtime_summary(Path(BASE_DIR)),
                'connectivity_runtime': build_connectivity_runtime_summary(Path(BASE_DIR)),
                'git_sync_runtime': read_git_sync_runtime_summary(),
                'env_runtime': build_node_env_summary_safe(),
            }

        @self.app.get(DRONE_SYSTEM_HEALTH_ROUTE, response_model=DroneHealthResponse)
        async def ping_v1():
            """Canonical v1 health endpoint with timestamp and version metadata."""
            return DroneHealthResponse(
                status="ok",
                version=MDS_VERSION,
                ulog_capability=self._build_ulog_capability_payload(),
            )

        @self.app.get(DRONE_ENV_ROUTE, response_model=DroneEnvResponse)
        async def get_node_env(include_hidden: bool = False):
            """Return node-local env values with registry metadata and safe redaction."""
            try:
                return build_node_env_response(include_hidden=include_hidden)
            except EnvRegistryError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"error_in_get_node_env: {exc}") from exc

        @self.app.put(DRONE_ENV_ROUTE, response_model=DroneEnvUpdateResponse)
        async def update_node_env(payload: DroneEnvUpdateRequest):
            """Persist registry-approved node-local env keys without exposing secrets."""
            try:
                updates = payload.updates or {}
                validated, warnings, apply_actions, restart_required = validate_node_env_updates(updates)
                config_path = get_local_env_path()
                changed_keys: list[str] = []
                if not payload.dry_run and validated:
                    changed_keys = list(persist_env_updates(config_path, validated).changed_keys)

                return DroneEnvUpdateResponse(
                    success=True,
                    dry_run=bool(payload.dry_run),
                    config_path=str(config_path),
                    updated_keys=list(validated),
                    changed_keys=changed_keys,
                    restart_required=bool(restart_required and (payload.dry_run or changed_keys)),
                    apply_actions=apply_actions,
                    warnings=warnings,
                )
            except EnvRegistryError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"error_in_update_node_env: {exc}") from exc

        @self.app.post(DRONE_SIDECAR_PROFILE_PROXY_ROUTE_TEMPLATE)
        async def proxy_sidecar_profile_request(sidecar: str, action: str, payload: Dict[str, Any]):
            """Proxy profile-control requests to node-local sidecar loopback APIs."""
            url = _sidecar_profile_proxy_url(sidecar, action)
            headers = _sidecar_profile_proxy_headers(sidecar)
            try:
                response = requests.post(url, json=payload or {}, headers=headers, timeout=10)
            except requests.RequestException as exc:
                raise HTTPException(status_code=502, detail=f"sidecar loopback request failed: {exc}") from exc
            repair_refresh = None
            mode_repair = None
            if response.status_code >= 400 and _sidecar_proxy_has_smart_wifi_mode_error(sidecar, response):
                mode_repair = _run_smart_wifi_service_mode_repair()
                if mode_repair.get("ok"):
                    try:
                        response = requests.post(url, json=payload or {}, headers=headers, timeout=10)
                    except requests.RequestException as exc:
                        raise HTTPException(status_code=502, detail=f"sidecar loopback request failed: {exc}") from exc
            if response.status_code >= 400 and (
                _sidecar_proxy_requires_profile_token(sidecar, response)
                or _sidecar_proxy_has_smart_wifi_mode_error(sidecar, response)
            ):
                fallback = _smart_wifi_local_profile_fallback(action, payload or {})
                if fallback is not None:
                    if mode_repair is not None:
                        fallback["mds_mode_repair"] = mode_repair
                    return fallback
            if response.status_code >= 400 and _should_repair_smart_wifi_config(sidecar, action, response):
                repair_refresh = _run_sidecar_reconcile_refresh(sidecar, "apply")
                if repair_refresh and repair_refresh.get("ok"):
                    try:
                        response = requests.post(url, json=payload or {}, headers=headers, timeout=10)
                    except requests.RequestException as exc:
                        raise HTTPException(status_code=502, detail=f"sidecar loopback request failed: {exc}") from exc
            if response.status_code >= 400 and (
                _sidecar_proxy_requires_profile_token(sidecar, response)
                or _sidecar_proxy_has_smart_wifi_mode_error(sidecar, response)
            ):
                fallback = _smart_wifi_local_profile_fallback(action, payload or {})
                if fallback is not None:
                    if mode_repair is not None:
                        fallback["mds_mode_repair"] = mode_repair
                    return fallback
            if response.status_code >= 400:
                raise HTTPException(status_code=response.status_code, detail=_sidecar_proxy_error_detail(response))
            try:
                data = response.json()
            except ValueError as exc:
                raise HTTPException(status_code=502, detail="sidecar returned non-json response") from exc
            refresh = _run_sidecar_reconcile_refresh(sidecar, action)
            if repair_refresh is not None and refresh is None:
                refresh = repair_refresh
            if refresh is None:
                if mode_repair is not None and isinstance(data, dict):
                    data["mds_mode_repair"] = mode_repair
                return data
            if isinstance(data, dict):
                if mode_repair is not None:
                    data["mds_mode_repair"] = mode_repair
                data["mds_reconcile_refresh"] = refresh
                return data
            return {"sidecar_result": data, "mds_reconcile_refresh": refresh}

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

        @self.app.get(DRONE_SWARM_CONFIG_ROUTE, response_model=Dict[str, Any])
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
                raise self._px4_param_failure_http_exception("refresh_px4_param_snapshot", exc) from exc

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
                raise self._px4_param_failure_http_exception("read_px4_param_value", exc) from exc

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
                raise self._px4_param_failure_http_exception("write_px4_param_value", exc) from exc

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
                raise self._px4_param_failure_http_exception("apply_px4_param_patch", exc) from exc

        @self.app.get(DRONE_ULOG_POLICY_ROUTE)
        async def get_onboard_ulog_policy(request: Request):
            """Return the local onboard ULog subsystem policy envelope."""
            self._require_ulog_machine_credential(
                request,
                operation=ULOG_OP_POLICY_READ,
            )
            return self._ulog_service.build_policy(
                ulog_capability=self._build_ulog_capability()
            )

        @self.app.get(DRONE_ULOG_FILES_ROUTE)
        async def list_onboard_ulog_files(request: Request):
            """List onboard PX4 ULog files visible through MAVSDK."""
            self._require_ulog_machine_credential(
                request,
                operation=ULOG_OP_FILES_READ,
            )
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
                raise self._ulog_failure_http_exception("list_onboard_ulogs", exc) from exc

        @self.app.get(DRONE_ULOG_FILE_SUMMARY_ROUTE_TEMPLATE, response_model=OnboardUlogSummaryResponse)
        async def summarize_onboard_ulog_file(log_id: int, request: Request):
            """Return a safe derived summary for one onboard PX4 ULog."""
            from mds_logging.ulog_analysis import UlogSummaryError

            self._require_ulog_machine_credential(
                request,
                operation=ULOG_OP_SUMMARY_READ,
            )
            self._assert_ulog_download_allowed()
            try:
                return await self._with_local_ulog_system(
                    lambda drone: self._ulog_service.summarize_entry(
                        drone,
                        int(log_id),
                        OnboardUlogDownloadRequest(pos_id=safe_int(getattr(self.drone_config, "pos_id", None), None)),
                    )
                )
            except UlogServiceError as exc:
                raise self._ulog_failure_http_exception("summarize_ulog", exc) from exc
            except FileNotFoundError as exc:
                if self._is_mavsdk_dependency_error(exc):
                    raise self._ulog_failure_http_exception("summarize_ulog", exc) from exc
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=413, detail=str(exc)) from exc
            except UlogSummaryError as exc:
                raise self._ulog_failure_http_exception("summarize_ulog", exc) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(f"Error summarizing onboard ULog {log_id}: {exc}")
                raise self._ulog_failure_http_exception("summarize_ulog", exc) from exc

        @self.app.post(DRONE_ULOG_FILE_DOWNLOAD_ROUTE_TEMPLATE)
        async def create_onboard_ulog_download(
            log_id: int,
            http_request: Request,
            request: Optional[OnboardUlogDownloadRequest] = None,
            ulog_job_token: str | None = Header(
                default=None,
                alias=DRONE_ULOG_JOB_TOKEN_HEADER,
            ),
        ):
            """Create a short-lived staged onboard ULog download job."""
            self._require_ulog_machine_credential(
                http_request,
                operation=ULOG_OP_DOWNLOAD_CREATE,
            )
            self._assert_ulog_download_allowed()
            if not ulog_job_token:
                raise HTTPException(
                    status_code=401,
                    detail="ULog download job capability is required.",
                )
            download_request = request or OnboardUlogDownloadRequest()
            try:
                job_response = await self._with_local_ulog_system(
                    lambda drone: self._ulog_service.create_download_job(
                        drone,
                        int(log_id),
                        download_request,
                        access_token=ulog_job_token,
                    )
                )
                self._start_ulog_download_task(job_response.job.job_id)
                return job_response
            except UlogServiceError as exc:
                raise self._ulog_failure_http_exception(
                    "create_ulog_download",
                    exc,
                ) from exc
            except HTTPException:
                raise
            except Exception as exc:
                logger.error(f"Error creating onboard ULog download job for log {log_id}: {exc}")
                raise self._ulog_failure_http_exception("create_ulog_download", exc) from exc

        @self.app.get(DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE)
        async def get_onboard_ulog_download_job(
            job_id: str,
            request: Request,
            ulog_job_token: str | None = Header(
                default=None,
                alias=DRONE_ULOG_JOB_TOKEN_HEADER,
            ),
        ):
            """Return the current state of a staged onboard ULog download job."""
            self._require_ulog_machine_credential(
                request,
                operation=ULOG_OP_DOWNLOAD_STATUS,
            )
            await self._assert_ulog_job_access(job_id, ulog_job_token)
            try:
                job = await self._ulog_service.get_job(job_id)
            except UlogServiceError as exc:
                raise self._ulog_failure_http_exception(
                    "read_ulog_download_job",
                    exc,
                ) from exc
            if job is None:
                raise HTTPException(status_code=404, detail=f"ULog download job {job_id} not found")
            return job

        @self.app.delete(DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE)
        async def delete_onboard_ulog_download_job(
            job_id: str,
            request: Request,
            ulog_job_token: str | None = Header(
                default=None,
                alias=DRONE_ULOG_JOB_TOKEN_HEADER,
            ),
        ) -> OnboardUlogJobDeleteResponse:
            """Delete a staged onboard ULog download job and any staged file."""
            self._require_ulog_machine_credential(
                request,
                operation=ULOG_OP_DOWNLOAD_DELETE,
            )
            await self._assert_ulog_job_access(job_id, ulog_job_token)
            try:
                deleted = await self._ulog_service.delete_job(job_id)
            except UlogServiceError as exc:
                raise self._ulog_failure_http_exception(
                    "delete_ulog_download_job",
                    exc,
                ) from exc
            if not deleted:
                raise HTTPException(status_code=404, detail=f"ULog download job {job_id} not found")
            return OnboardUlogJobDeleteResponse(
                status="deleted",
                job_id=job_id,
                timestamp=int(time.time() * 1000),
            )

        @self.app.get(DRONE_ULOG_DOWNLOAD_CONTENT_ROUTE_TEMPLATE)
        async def download_onboard_ulog_content(
            job_id: str,
            request: Request,
            ulog_job_token: str | None = Header(
                default=None,
                alias=DRONE_ULOG_JOB_TOKEN_HEADER,
            ),
        ):
            """Stream the staged onboard ULog file once the node-local job is ready."""
            self._require_ulog_machine_credential(
                request,
                operation=ULOG_OP_DOWNLOAD_CONTENT,
            )
            await self._assert_ulog_job_access(job_id, ulog_job_token)
            lease = self._ulog_service.lease_ready_file(job_id)
            try:
                file_handle, _stage_path, job = await lease.__aenter__()
            except UlogServiceError as exc:
                raise self._ulog_failure_http_exception(
                    "stream_ulog_download",
                    exc,
                ) from exc

            async def stream_file():
                try:
                    while True:
                        chunk = await asyncio.to_thread(
                            file_handle.read,
                            1024 * 1024,
                        )
                        if not chunk:
                            break
                        yield chunk
                finally:
                    await lease.__aexit__(None, None, None)

            try:
                filename = Path(
                    job.download_filename
                    or f"mds-ulog_H{self.drone_config.hw_id}_L{job.log_id}.ulg"
                ).name
                encoded_filename = quote(filename, safe="._-")
                response = StreamingResponse(
                    stream_file(),
                    media_type="application/octet-stream",
                    headers={
                        "Content-Disposition": (
                            "attachment; "
                            f"filename*=UTF-8''{encoded_filename}"
                        ),
                        "Content-Length": str(
                            os.fstat(file_handle.fileno()).st_size
                        ),
                    },
                )
            except BaseException as exc:
                await lease.__aexit__(type(exc), exc, exc.__traceback__)
                raise
            return response

        @self.app.post(DRONE_ULOG_ERASE_ALL_ROUTE)
        async def erase_all_onboard_ulogs(request: Request):
            """Erase all onboard PX4 ULog files through MAVSDK."""
            self._require_ulog_machine_credential(
                request,
                operation=ULOG_OP_ERASE,
            )
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
                raise self._ulog_failure_http_exception("erase_onboard_ulogs", exc) from exc

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

        @self.app.websocket(DRONE_WS_SWARM_STATE_ROUTE)
        async def websocket_swarm_state(websocket: WebSocket):
            """Dedicated Smart Swarm leader-state stream for follower control."""
            await websocket.accept()
            rate_hz = max(1.0, safe_float(getattr(self.params, "SMART_SWARM_STATE_STREAM_RATE_HZ", 15), 15.0))
            interval = 1.0 / rate_hz

            try:
                while True:
                    swarm_state = self.drone_communicator.get_swarm_state()
                    if swarm_state:
                        await websocket.send_json(self._serialize_swarm_state_payload(swarm_state))
                    else:
                        await websocket.send_json({
                            "error": "Swarm state not available",
                            "emitted_at_ms": int(time.time() * 1000),
                        })
                    await asyncio.sleep(interval)
            except WebSocketDisconnect:
                logger.info("Smart Swarm WebSocket client disconnected")
            except Exception as exc:
                logger.error(f"Smart Swarm WebSocket error: {exc}")

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

    @staticmethod
    def _command_semantic_identity(command_data: Dict[str, Any]) -> _CommandSemanticIdentity:
        """Return a canonical digest of every execution-affecting request field.

        ``command_id`` is the idempotency key itself; ``target_hw_id`` and the
        callback capability are transport/security metadata already bound at
        their respective boundaries. All execution-affecting typed fields are
        conservatively included so future mission fields cannot silently
        weaken replay safety.
        """
        semantic_payload = {
            key: value
            for key, value in command_data.items()
            if key not in {
                "command_id",
                "target_hw_id",
                "command_report_capability",
            }
        }
        canonical = json.dumps(
            semantic_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        field_fingerprints = {
            key: hashlib.sha256(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            for key, value in semantic_payload.items()
        }
        return _CommandSemanticIdentity(
            fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            field_fingerprints=field_fingerprints,
        )

    def _protected_command_ids(self) -> Set[str]:
        """Return command IDs still represented by live node execution state."""
        protected: Set[str] = set()
        current_command_id = getattr(self.drone_config, "current_command_id", None)
        if current_command_id:
            protected.add(str(current_command_id))

        drone_setup = getattr(self.drone_config, "drone_setup", None)
        active_mission_command_id = (
            getattr(drone_setup, "_active_mission_command_id", None)
            if drone_setup
            else None
        )
        if active_mission_command_id:
            protected.add(str(active_mission_command_id))
        running_processes = getattr(drone_setup, "running_processes", None) if drone_setup else None
        if isinstance(running_processes, dict):
            try:
                process_records = tuple(running_processes.values())
            except RuntimeError:
                # A monitor may retire a process on the scheduler loop while
                # this API thread snapshots it. Protecting every current
                # registry key is conservative and prevents unsafe eviction.
                logger.warning(
                    "Running-process ownership changed during idempotency pruning; "
                    "deferring history eviction for this command transaction."
                )
                protected.update(self._command_idempotency_records.keys())
                return protected
            for process_record in process_records:
                command_id = getattr(process_record, "command_id", None)
                if command_id:
                    protected.add(str(command_id))
        return protected

    def _prune_command_idempotency_records_locked(self, now_monotonic: float) -> Set[str]:
        """Expire terminal history and return IDs that must never be evicted."""
        protected_ids = self._protected_command_ids()
        expired_ids = [
            command_id
            for command_id, record in self._command_idempotency_records.items()
            if command_id not in protected_ids
            and (now_monotonic - record.created_at_monotonic) > self._command_idempotency_ttl_sec
        ]
        for command_id in expired_ids:
            self._command_idempotency_records.pop(command_id, None)

        while len(self._command_idempotency_records) > self._command_idempotency_max_records:
            removable_id = next(
                (
                    command_id
                    for command_id in self._command_idempotency_records
                    if command_id not in protected_ids
                ),
                None,
            )
            if removable_id is None:
                break
            self._command_idempotency_records.pop(removable_id, None)
        return protected_ids

    def _make_command_idempotency_room_locked(self, protected_ids: Set[str]) -> bool:
        """Evict one terminal LRU record, never an active command record."""
        if len(self._command_idempotency_records) < self._command_idempotency_max_records:
            return True
        removable_id = next(
            (
                command_id
                for command_id in self._command_idempotency_records
                if command_id not in protected_ids
            ),
            None,
        )
        if removable_id is None:
            return False
        self._command_idempotency_records.pop(removable_id, None)
        return True

    @staticmethod
    def _semantic_conflict_detail(
        existing: _CommandSemanticIdentity,
        requested: _CommandSemanticIdentity,
    ) -> str:
        all_fields = set(existing.field_fingerprints) | set(requested.field_fingerprints)
        changed_fields = sorted(
            field
            for field in all_fields
            if existing.field_fingerprints.get(field) != requested.field_fingerprints.get(field)
        )
        changed_summary = ", ".join(changed_fields) if changed_fields else "canonical payload"
        return (
            f"Changed semantic field(s): {changed_summary}. "
            f"Existing fingerprint={existing.fingerprint[:16]}; "
            f"requested fingerprint={requested.fingerprint[:16]}."
        )

    def _begin_command_idempotency(
        self,
        *,
        command_id: Optional[str],
        semantic_identity: _CommandSemanticIdentity,
        mission_type: int,
        trigger_time: int,
        known_command: Optional[Dict[str, Any]],
    ) -> Tuple[str, Optional[_NodeCommandRecord], Optional[str]]:
        """Reserve a new command ID or classify an existing delivery.

        Returns ``(classification, record, detail)`` where classification is
        ``new``, ``replay``, ``conflict``, or ``capacity``. The reservation is
        created before any command-state mutation, closing the scheduler
        detach/running-record visibility gap for duplicate HTTP delivery.
        """
        if not command_id:
            return "new", None, None

        normalized_command_id = str(command_id).strip()
        now_monotonic = time.monotonic()
        with self._command_idempotency_lock:
            protected_ids = self._prune_command_idempotency_records_locked(now_monotonic)
            record = self._command_idempotency_records.get(normalized_command_id)
            if record is not None:
                record.last_seen_monotonic = now_monotonic
                self._command_idempotency_records.move_to_end(normalized_command_id)
                if record.semantic_identity.fingerprint != semantic_identity.fingerprint:
                    return (
                        "conflict",
                        record,
                        self._semantic_conflict_detail(record.semantic_identity, semantic_identity),
                    )
                return "replay", record, None

            # Rolling-upgrade compatibility: a command accepted before this
            # API registry existed may still be visible in current/running/
            # recent state. Bind the first matching delivery to its full
            # semantic fingerprint and never execute it again. The warning is
            # auditable because historical optional fields cannot be recovered.
            if known_command is not None:
                known_mission_type = int(known_command.get("mission_type", Mission.NONE.value))
                trigger_time_authoritative = bool(
                    known_command.get("trigger_time_authoritative", True)
                )
                known_trigger_time = int(known_command.get("trigger_time", 0) or 0)
                if (
                    known_mission_type != mission_type
                    or (
                        trigger_time_authoritative
                        and known_trigger_time != trigger_time
                    )
                ):
                    return (
                        "conflict",
                        None,
                        (
                            "Existing legacy command metadata differs: "
                            f"mission_type={known_mission_type}, trigger_time={known_trigger_time}; "
                            f"requested mission_type={mission_type}, trigger_time={trigger_time}."
                        ),
                    )
                record = _NodeCommandRecord(
                    command_id=normalized_command_id,
                    semantic_identity=semantic_identity,
                    mission_type=mission_type,
                    trigger_time=trigger_time,
                    phase=str(known_command.get("phase", "pending")),
                    outcome=None,
                    response=None,
                    created_at_monotonic=now_monotonic,
                    last_seen_monotonic=now_monotonic,
                    legacy_runtime_bound=True,
                )
                if self._make_command_idempotency_room_locked(protected_ids):
                    self._command_idempotency_records[normalized_command_id] = record
                logger.warning(
                    "Bound legacy in-process command_id=%s to its first full semantic replay fingerprint; "
                    "the command will not be re-executed.",
                    normalized_command_id,
                )
                return "replay", record, None

            if not self._make_command_idempotency_room_locked(protected_ids):
                return "capacity", None, None

            record = _NodeCommandRecord(
                command_id=normalized_command_id,
                semantic_identity=semantic_identity,
                mission_type=mission_type,
                trigger_time=trigger_time,
                phase="processing",
                outcome=None,
                response=None,
                created_at_monotonic=now_monotonic,
                last_seen_monotonic=now_monotonic,
            )
            self._command_idempotency_records[normalized_command_id] = record
            return "new", record, None

    @staticmethod
    def _public_command_lifecycle(phase: str, outcome: Optional[str] = None) -> Tuple[str, Optional[str]]:
        normalized_phase = str(phase or "pending").strip().lower()
        if normalized_phase == "processing":
            return "preparing", outcome
        if normalized_phase == "launching":
            return "preparing", outcome
        if normalized_phase == "pending":
            return "pending_execution", outcome
        if normalized_phase == "executing":
            return "in_progress", outcome
        if normalized_phase in {"completed", "failed", "superseded", "rejected"}:
            return "terminal", outcome or normalized_phase
        if normalized_phase == "outcome_unknown":
            return "outcome_unknown", outcome or "unknown"
        return normalized_phase, outcome

    def _finalize_command_idempotency(
        self,
        record: Optional[_NodeCommandRecord],
        response: CommandAckResponse,
        *,
        phase: str,
        outcome: Optional[str] = None,
    ) -> CommandAckResponse:
        public_phase, public_outcome = self._public_command_lifecycle(phase, outcome)
        response.command_phase = public_phase
        response.command_outcome = public_outcome
        if record is None:
            return response

        with self._command_idempotency_lock:
            record.phase = phase
            record.outcome = public_outcome
            record.response = response.model_dump(mode="json")
            record.last_seen_monotonic = time.monotonic()
            if record.command_id in self._command_idempotency_records:
                self._command_idempotency_records.move_to_end(record.command_id)
        return response

    def _build_idempotent_replay_response(
        self,
        *,
        record: _NodeCommandRecord,
        known_command: Optional[Dict[str, Any]],
        hw_id: str,
        pos_id: int,
        current_state: int,
        timestamp: int,
    ) -> CommandAckResponse:
        """Replay prior acceptance/rejection with explicit lifecycle evidence."""
        phase = record.phase
        outcome = record.outcome
        mission_type = record.mission_type
        trigger_time = record.trigger_time
        state = current_state
        uncertainty_resolved = False

        if known_command is not None:
            known_mission_type = int(known_command.get("mission_type", mission_type))
            trigger_time_authoritative = bool(
                known_command.get("trigger_time_authoritative", True)
            )
            known_trigger_time = (
                int(known_command.get("trigger_time", trigger_time) or 0)
                if trigger_time_authoritative
                else trigger_time
            )
            if (
                known_mission_type != mission_type
                or known_trigger_time != trigger_time
            ):
                logger.critical(
                    "Command lifecycle metadata conflicts with its idempotency record: "
                    "command_id=%s registry=(%s,%s) runtime=(%s,%s)",
                    record.command_id,
                    mission_type,
                    trigger_time,
                    known_mission_type,
                    known_trigger_time,
                )
                record.phase = "outcome_unknown"
                record.outcome = "unknown"
                detail = {
                    "status": "delivery_unknown",
                    "command_id": record.command_id,
                    "hw_id": hw_id,
                    "pos_id": pos_id,
                    "current_state": current_state,
                    "mission_type": mission_type,
                    "trigger_time": trigger_time,
                    "message": "Node command lifecycle metadata is inconsistent; delivery outcome is unknown",
                    "error_code": CommandErrorCode.INTERNAL_ERROR.value,
                    "error_detail": "Runtime mission/trigger metadata conflicts with the idempotency record.",
                    "replayed": True,
                    "command_phase": "outcome_unknown",
                    "command_outcome": "unknown",
                    "timestamp": timestamp,
                }
                record.response = detail
                raise HTTPException(status_code=503, detail=detail)

            if phase == "outcome_unknown":
                uncertainty_resolved = bool(
                    known_command.get("runtime_acceptance_authoritative", False)
                )
                if not uncertainty_resolved:
                    detail = dict(record.response or {})
                    detail.update(
                        {
                            "replayed": True,
                            "command_phase": "outcome_unknown",
                            "command_outcome": "unknown",
                            "timestamp": timestamp,
                        }
                    )
                    raise HTTPException(status_code=503, detail=detail)
                logger.warning(
                    "Resolved uncertain command delivery from authoritative scheduler lifecycle evidence: "
                    "command_id=%s phase=%s",
                    record.command_id,
                    known_command.get("phase"),
                )

            phase = str(known_command.get("phase", phase))
            outcome = phase if phase in {"completed", "failed", "superseded"} else None
            mission_type = known_mission_type
            trigger_time = known_trigger_time
            state = int(known_command.get("state", state))

        elif phase == "outcome_unknown":
            # Mutable config alone cannot prove acceptance after a fault. Keep
            # returning ambiguity until DroneSetup records launch/execution or
            # terminal lifecycle evidence for this exact command identity.
            detail = dict(record.response or {})
            detail.update(
                {
                    "replayed": True,
                    "command_phase": "outcome_unknown",
                    "command_outcome": "unknown",
                    "timestamp": timestamp,
                }
            )
            raise HTTPException(status_code=503, detail=detail)

        public_phase, public_outcome = self._public_command_lifecycle(phase, outcome)

        if record.response is not None and not uncertainty_resolved:
            response_data = dict(record.response)
            response_data.update(
                {
                    "hw_id": hw_id,
                    "pos_id": pos_id,
                    "current_state": current_state,
                    "mission_type": mission_type,
                    "trigger_time": trigger_time,
                    "replayed": True,
                    "command_phase": public_phase,
                    "command_outcome": public_outcome,
                    "timestamp": timestamp,
                }
            )
            if response_data.get("status") == "accepted":
                response_data["new_state"] = state
                try:
                    mission_name = Mission(mission_type).name
                except ValueError:
                    mission_name = f"MISSION_{mission_type}"
                response_data["message"] = self._build_idempotent_acceptance_message(
                    mission_name=mission_name,
                    phase=phase,
                )
            else:
                original_message = str(response_data.get("message") or "Command was rejected")
                response_data["message"] = f"Previous identical delivery was rejected: {original_message}"
            response = CommandAckResponse(**response_data)
        else:
            try:
                mission_name = Mission(mission_type).name
            except ValueError:
                mission_name = f"MISSION_{mission_type}"
            response = CommandAckResponse(
                status="accepted",
                command_id=record.command_id,
                hw_id=hw_id,
                pos_id=pos_id,
                current_state=current_state,
                new_state=state,
                mission_type=mission_type,
                trigger_time=trigger_time,
                message=self._build_idempotent_acceptance_message(
                    mission_name=mission_name,
                    phase=phase,
                ),
                replayed=True,
                command_phase=public_phase,
                command_outcome=public_outcome,
                timestamp=timestamp,
            )

        if record.legacy_runtime_bound:
            response.message = (
                f"{response.message}; exact optional payload fields are unavailable for this "
                "legacy in-process command, so the node will not execute the retry"
            )

        with self._command_idempotency_lock:
            record.phase = phase
            record.outcome = public_outcome
            record.response = response.model_dump(mode="json")
            record.last_seen_monotonic = time.monotonic()
        return response

    def _command_idempotency_conflict_response(
        self,
        *,
        command_id: Optional[str],
        hw_id: str,
        pos_id: int,
        current_state: int,
        mission_type: int,
        trigger_time: int,
        detail: str,
        timestamp: int,
    ) -> CommandAckResponse:
        logger.error("Rejected conflicting reuse of command_id=%s: %s", command_id, detail)
        return CommandAckResponse(
            status="rejected",
            command_id=command_id,
            hw_id=hw_id,
            pos_id=pos_id,
            current_state=current_state,
            mission_type=mission_type,
            trigger_time=trigger_time,
            message="Command ID is already bound to a different semantic payload",
            error_code=CommandErrorCode.IDEMPOTENCY_CONFLICT.value,
            error_detail=detail,
            replayed=True,
            command_phase="terminal",
            command_outcome="conflict",
            timestamp=timestamp,
        )

    def _reconcile_uncertain_command_ownership(
        self,
        *,
        command_id: Optional[str],
        state_snapshot: _CommandStateSnapshot,
    ) -> None:
        """Keep command ownership aligned with the scheduler-visible state.

        The canonical communicator returns a typed definite rejection only
        after verified rollback. An unexpected exception or an explicitly
        uncertain rollback can still cross the mutation boundary. A changed
        core state is then evidence that the new command may have installed;
        unchanged core state means the prior command still owns it. Neither
        proves the external outcome, so this helper only repairs local
        ownership while the idempotency record remains ``outcome_unknown``.
        """
        current_core = (
            int(self.drone_config.mission),
            int(getattr(self.drone_config, "trigger_time", 0) or 0),
            int(self.drone_config.state),
        )
        previous_core = (
            state_snapshot.mission_type,
            state_snapshot.trigger_time,
            state_snapshot.state,
        )
        reconciled_command_id = command_id if current_core != previous_core else state_snapshot.command_id
        self.drone_config.current_command_id = reconciled_command_id
        logger.warning(
            "Reconciled scheduler ownership after uncertain command mutation: "
            "core_state_changed=%s owner_command_id=%s",
            current_core != previous_core,
            reconciled_command_id,
        )

    def _record_post_mutation_command_uncertainty(
        self,
        *,
        record: Optional[_NodeCommandRecord],
        command_id: Optional[str],
        hw_id: str,
        pos_id: int,
        current_state: int,
        mission_type: Optional[int],
        trigger_time: Optional[int],
        state_snapshot: _CommandStateSnapshot,
        exc: Exception,
        timestamp: int,
    ) -> CommandAckResponse:
        """Persist an ambiguous outcome once command-state mutation may have begun."""
        self._reconcile_uncertain_command_ownership(
            command_id=command_id,
            state_snapshot=state_snapshot,
        )
        error_detail = str(exc).strip() or type(exc).__name__
        logger.critical(
            "Command processing failed after the mutation boundary; delivery outcome is unknown: "
            "command_id=%s mission_type=%s error=%s",
            command_id,
            mission_type,
            exc,
            exc_info=True,
        )
        response = CommandAckResponse(
            status="delivery_unknown",
            command_id=command_id,
            hw_id=hw_id,
            pos_id=pos_id,
            current_state=current_state,
            new_state=int(getattr(self.drone_config, "state", current_state)),
            mission_type=mission_type,
            trigger_time=trigger_time,
            message=(
                "Command processing crossed the node mutation boundary, but the final local "
                "acceptance outcome could not be confirmed; do not submit a new command ID."
            ),
            error_code=CommandErrorCode.INTERNAL_ERROR.value,
            error_detail=error_detail[:500],
            command_phase="outcome_unknown",
            command_outcome="unknown",
            timestamp=timestamp,
        )
        self._finalize_command_idempotency(
            record,
            response,
            phase="outcome_unknown",
            outcome="unknown",
        )
        return response

    def _raise_post_mutation_command_uncertainty(
        self,
        *,
        record: Optional[_NodeCommandRecord],
        command_id: Optional[str],
        hw_id: str,
        pos_id: int,
        current_state: int,
        mission_type: Optional[int],
        trigger_time: Optional[int],
        state_snapshot: _CommandStateSnapshot,
        exc: Exception,
        timestamp: int,
    ) -> None:
        """Return an ambiguous HTTP response once local mutation may have begun."""
        response = self._record_post_mutation_command_uncertainty(
            record=record,
            command_id=command_id,
            hw_id=hw_id,
            pos_id=pos_id,
            current_state=current_state,
            mission_type=mission_type,
            trigger_time=trigger_time,
            state_snapshot=state_snapshot,
            exc=exc,
            timestamp=timestamp,
        )
        raise HTTPException(status_code=503, detail=response.model_dump(mode="json"))

    def _handle_command_processing_exception(
        self,
        *,
        record: Optional[_NodeCommandRecord],
        command_id: Optional[str],
        hw_id: str,
        pos_id: int,
        current_state: int,
        mission_type: Optional[int],
        trigger_time: Optional[int],
        mutation_started: bool,
        command_committed: bool,
        state_snapshot: _CommandStateSnapshot,
        exc: Exception,
        precommit_message: str,
        precommit_error_code: str,
        precommit_error_detail: str,
        timestamp: int,
    ) -> CommandAckResponse:
        """Preserve the acceptance boundary when exception handling a command."""
        if mutation_started and not command_committed:
            self._raise_post_mutation_command_uncertainty(
                record=record,
                command_id=command_id,
                hw_id=hw_id,
                pos_id=pos_id,
                current_state=current_state,
                mission_type=mission_type,
                trigger_time=trigger_time,
                state_snapshot=state_snapshot,
                exc=exc,
                timestamp=timestamp,
            )

        if command_committed:
            logger.error(
                "Command was installed before response finalization failed; preserving accepted state: "
                "command_id=%s error=%s",
                command_id,
                exc,
                exc_info=True,
            )
            response = CommandAckResponse(
                status="accepted",
                command_id=command_id,
                hw_id=hw_id,
                pos_id=pos_id,
                current_state=current_state,
                new_state=int(getattr(self.drone_config, "state", State.MISSION_READY.value)),
                mission_type=mission_type,
                trigger_time=trigger_time,
                message=(
                    "Command was installed on this node, but post-commit response/reporting "
                    "encountered an error; execution tracking remains authoritative."
                ),
                error_detail=str(exc)[:500],
                timestamp=timestamp,
            )
            return self._finalize_command_idempotency(
                record,
                response,
                phase="pending",
            )

        response = CommandAckResponse(
            status="rejected",
            command_id=command_id,
            hw_id=hw_id,
            pos_id=pos_id,
            current_state=current_state,
            mission_type=mission_type,
            trigger_time=trigger_time,
            message=precommit_message,
            error_code=precommit_error_code,
            error_detail=precommit_error_detail,
            timestamp=timestamp,
        )
        return self._finalize_command_idempotency(
            record,
            response,
            phase="rejected",
            outcome="rejected",
        )

    def _validate_command(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate command structure and values.

        Returns dict with 'valid', 'message', 'error_code', and optionally 'detail'.
        """
        mission_key = 'mission_type'
        trigger_key = 'trigger_time'

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
            if (
                mission_type not in Mission._value2member_map_
                or mission_type == Mission.UNKNOWN.value
            ):
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

        if mission_type in {Mission.HOLD.value, Mission.PRECISION_MOVE.value}:
            mission_name = Mission(mission_type).name
            cached_admission = evaluate_cached_airborne_admission(
                self.drone_config,
                max_age_sec=getattr(self.params, "LOCAL_MAVLINK_STALE_TIMEOUT_SEC", 0),
            )
            if not cached_admission.accepted:
                error_code = (
                    CommandErrorCode.NOT_ARMED.value
                    if cached_admission.status
                    in {
                        AirborneAdmissionStatus.HEARTBEAT_UNAVAILABLE,
                        AirborneAdmissionStatus.HEARTBEAT_STALE,
                        AirborneAdmissionStatus.ARMED_UNAVAILABLE,
                        AirborneAdmissionStatus.DISARMED,
                    }
                    else CommandErrorCode.INVALID_STATE.value
                )
                return {
                    'valid': False,
                    'message': f'{mission_name} requires fresh evidence of an armed airborne drone',
                    'error_code': error_code,
                    'detail': cached_admission.detail,
                }

        return {'valid': True, 'message': 'State preconditions met'}

    @staticmethod
    def _allowed_override_missions() -> Set[int]:
        """Commands that are allowed to replace a queued or executing mission."""
        return {
            Mission.NONE.value,
            Mission.DRONE_SHOW_FROM_CSV.value,
            Mission.CUSTOM_CSV_DRONE_SHOW.value,
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
                'trigger_time_authoritative': True,
                # This mutable pending slot is the same state reconciled after
                # an uncertain fault, so it cannot independently prove ACK.
                'runtime_acceptance_authoritative': False,
            }

        drone_setup = getattr(self.drone_config, 'drone_setup', None)
        running_processes = getattr(drone_setup, 'running_processes', None) if drone_setup else None
        if not isinstance(running_processes, dict):
            running_processes = {}

        try:
            process_records = tuple(running_processes.values())
        except RuntimeError:
            logger.warning(
                "Running-process registry changed while resolving command_id=%s; "
                "using node idempotency history only for this request.",
                command_id,
            )
            process_records = ()

        for record in process_records:
            if getattr(record, 'command_id', None) == command_id:
                return {
                    'mission_type': int(
                        getattr(record, 'mission_type', self.drone_config.mission)
                    ),
                    'trigger_time': int(getattr(record, 'trigger_time', 0) or 0),
                    'state': int(self.drone_config.state),
                    'phase': 'executing',
                    'trigger_time_authoritative': True,
                    'runtime_acceptance_authoritative': True,
                }

        get_recent_command_record = getattr(drone_setup, 'get_recent_command_record', None) if drone_setup else None
        if callable(get_recent_command_record):
            recent_record = get_recent_command_record(command_id)
            if isinstance(recent_record, dict):
                recent_record.setdefault('trigger_time_authoritative', True)
                recent_record.setdefault('runtime_acceptance_authoritative', True)
                return recent_record

        return None

    async def _cancel_active_or_pending_command(self, *, had_active_command: bool) -> Tuple[int, str]:
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
        if phase == "launching":
            return f"Command {mission_name} launch preparation is already in progress; returning idempotent ACK"
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
        superseded_message = format_pending_superseded_execution_error(mission_name)

        drone_setup = getattr(self.drone_config, 'drone_setup', None)
        if drone_setup and hasattr(drone_setup, '_report_execution_to_gcs'):
            await drone_setup._report_execution_to_gcs(
                command_id=command_id,
                success=False,
                outcome=DroneExecutionOutcome.SUPERSEDED,
                error_message=superseded_message,
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
                'outcome': DroneExecutionOutcome.SUPERSEDED.value,
                'error_message': superseded_message,
                'duration_ms': 0,
            }
            url = f"http://{gcs_ip}:{self.params.gcs_api_port}{GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE}"
            response = await asyncio.to_thread(
                requests.post,
                url,
                json=payload,
                headers=gcs_auth_headers(),
                timeout=5,
            )
            try:
                response_payload = response.json() if response.status_code == 422 else None
            except (requests.RequestException, ValueError, TypeError):
                response_payload = None
            if is_legacy_schema_outcome_rejection(
                status_code=response.status_code,
                response_payload=response_payload,
            ):
                legacy_payload = dict(payload)
                legacy_payload.pop('outcome', None)
                response = await asyncio.to_thread(
                    requests.post,
                    url,
                    json=legacy_payload,
                    headers=gcs_auth_headers(),
                    timeout=5,
                )
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
        """Load swarm data using the canonical object envelope.

        Current MDS writes swarm.json as {"version": int, "assignments": [...]},
        while older drone-local paths may still have a legacy raw list or CSV.
        Keep the route envelope stable so GCS/UI/API consumers see one shape.
        """
        path = Path(file_path)
        if path.suffix.lower() == ".json":
            payload = load_json(str(path))
            if not payload:
                return {"version": 1, "assignments": []}
            if isinstance(payload, dict):
                assignments = payload.get("assignments")
                if isinstance(assignments, list):
                    return {
                        "version": int(payload.get("version") or 1),
                        "assignments": assignments,
                    }
                raise ValueError("Swarm JSON must contain an assignments array")
            if isinstance(payload, list):
                return {"version": 1, "assignments": payload}
            raise ValueError("Swarm JSON must be an object or list")

        return {"version": 1, "assignments": load_csv(file_path)}

    def _get_origin_from_gcs(self):
        """Fetches the origin coordinates from the GCS."""
        try:
            gcs_ip = self.params.GCS_IP
            if not gcs_ip:
                logger.error("GCS IP not configured in Params")
                return None

            gcs_port = self.params.gcs_api_port
            gcs_url = f"http://{gcs_ip}:{gcs_port}"

            response = requests.get(
                f"{gcs_url}{GCS_ORIGIN_BOOTSTRAP_ROUTE}",
                headers=gcs_auth_headers(),
                timeout=5,
            )
            if response.status_code == 200:
                data = response.json()
                if 'lat' in data and 'lon' in data:
                    # Reset error flag on success
                    DroneAPIServer._origin_fetch_error_logged = False
                    DroneAPIServer._origin_fetch_last_issue = None
                    return {'lat': float(data['lat']), 'lon': float(data['lon'])}
            else:
                detail = ""
                try:
                    payload = response.json()
                    detail = str(payload.get("detail") or payload.get("error") or "")
                except ValueError:
                    response_text = getattr(response, "text", "")
                    detail = response_text[:200] if response_text else ""

                issue_key = f"http_{response.status_code}:{detail}"
                if issue_key != DroneAPIServer._origin_fetch_last_issue:
                    DroneAPIServer._origin_fetch_last_issue = issue_key
                    DroneAPIServer._origin_fetch_error_logged = True
                    if response.status_code == 404 and "Origin not set" in detail:
                        logger.info(
                            "GCS origin is not set yet; pos_id auto-detection will wait for dashboard origin."
                        )
                    else:
                        suffix = f": {detail}" if detail else ""
                        logger.warning(f"Origin fetch from GCS returned HTTP {response.status_code}{suffix}")
            return None
        except requests.RequestException as e:
            # Log once to avoid spam - GCS might not be running yet
            issue_key = f"request_exception:{type(e).__name__}:{e}"
            if issue_key != DroneAPIServer._origin_fetch_last_issue:
                DroneAPIServer._origin_fetch_error_logged = True
                DroneAPIServer._origin_fetch_last_issue = issue_key
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
            return build_network_info()

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
