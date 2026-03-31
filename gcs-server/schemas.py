# gcs-server/schemas.py
"""
GCS Server Pydantic Schemas
===========================
Comprehensive request/response models for all GCS API endpoints.
Ensures type safety and automatic validation for FastAPI migration.

Author: MAVSDK Drone Show Team
Last Updated: 2025-11-22
"""

import os
import sys

from pydantic import BaseModel, Field, validator, ConfigDict, field_validator
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum

# Import shared enums from src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from enums import CommandOutcome, CommandPhase, CommandStatus


# ============================================================================
# Enums for Type Safety
# ============================================================================

class DroneState(str, Enum):
    """Drone operational states"""
    IDLE = "idle"
    ARMED = "armed"
    TAKING_OFF = "taking_off"
    FLYING = "flying"
    LANDING = "landing"
    LANDED = "landed"
    ERROR = "error"
    UNKNOWN = "unknown"


class FlightMode(str, Enum):
    """MAVLink flight modes"""
    MANUAL = "MANUAL"
    STABILIZED = "STABILIZED"
    ACRO = "ACRO"
    ALTCTL = "ALTCTL"
    POSCTL = "POSCTL"
    OFFBOARD = "OFFBOARD"
    AUTO_MISSION = "AUTO.MISSION"
    AUTO_LOITER = "AUTO.LOITER"
    AUTO_RTL = "AUTO.RTL"
    AUTO_LAND = "AUTO.LAND"
    AUTO_TAKEOFF = "AUTO.TAKEOFF"


class GitStatus(str, Enum):
    """Git repository status"""
    SYNCED = "synced"
    AHEAD = "ahead"
    BEHIND = "behind"
    DIVERGED = "diverged"
    DIRTY = "dirty"
    UNKNOWN = "unknown"


# ============================================================================
# Configuration Schemas
# ============================================================================

class DroneConfig(BaseModel):
    """Individual drone configuration for config.json"""
    model_config = ConfigDict(extra='allow')  # Preserve user custom fields

    hw_id: int = Field(..., ge=1, description="Hardware ID (unique physical drone identifier)")
    pos_id: int = Field(..., ge=1, description="Position ID (1-based, maps to trajectory 'Drone {pos_id}.csv')")
    ip: str = Field(..., pattern=r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', description="IP address")
    mavlink_port: int = Field(..., ge=1, description="MAVLink UDP port")
    serial_port: str = Field('', description="Serial port device path (empty for SITL)")
    baudrate: int = Field(0, ge=0, description="Serial baudrate (0 for SITL)")
    color: Optional[str] = Field(None, pattern=r'^#[0-9a-fA-F]{6}$', description="UI color (hex)")
    notes: Optional[str] = Field(None, description="Operator notes")


class FleetConfig(BaseModel):
    """Top-level config.json schema"""
    version: int = Field(1, ge=1, description="Schema version for future migration")
    drones: List[DroneConfig]


class SwarmAssignment(BaseModel):
    """Individual swarm assignment for swarm.json"""
    model_config = ConfigDict(extra='allow')

    hw_id: int = Field(..., ge=1, description="Hardware ID")
    follow: int = Field(0, ge=0, description="Leader hw_id to follow (0 = independent)")
    offset_x: float = Field(0.0, description="Offset axis 1: North (ned) or Forward (body), meters")
    offset_y: float = Field(0.0, description="Offset axis 2: East (ned) or Right (body), meters")
    offset_z: float = Field(0.0, description="Offset axis 3: Up (positive = higher), meters")
    frame: str = Field("ned", pattern=r'^(ned|body)$', description="Coordinate frame: 'ned' (North-East-Up) or 'body' (Forward-Right-Up)")


class SwarmConfig(BaseModel):
    """Top-level swarm.json schema"""
    version: int = Field(1, ge=1, description="Schema version")
    assignments: List[SwarmAssignment]


class ConfigListResponse(BaseModel):
    """Response for GET /config"""
    drones: List[DroneConfig] = Field(..., description="List of drone configurations")
    total_drones: int = Field(..., ge=0, description="Total number of drones")
    timestamp: int = Field(..., description="Unix timestamp (ms)")


class ConfigUpdateRequest(BaseModel):
    """Request for POST /config"""
    drones: List[DroneConfig] = Field(..., min_length=1, description="Updated drone configurations")


class ConfigUpdateResponse(BaseModel):
    """Response for POST /config"""
    success: bool = Field(..., description="Update success status")
    message: str = Field(..., description="Status message")
    updated_count: int = Field(..., ge=0, description="Number of drones updated")
    git_result: Optional[Dict[str, Any]] = Field(None, description="Git commit/push result if auto-push enabled")


# ============================================================================
# Telemetry Schemas
# ============================================================================

class PositionNED(BaseModel):
    """NED (North-East-Down) position"""
    north: float = Field(..., description="North position (m)")
    east: float = Field(..., description="East position (m)")
    down: float = Field(..., description="Down position (m)")


class PositionGPS(BaseModel):
    """GPS coordinates"""
    latitude: float = Field(..., ge=-90, le=90, description="Latitude (degrees)")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude (degrees)")
    altitude: float = Field(..., description="Altitude above MSL (m)")


class VelocityNED(BaseModel):
    """NED velocity components"""
    vn: float = Field(..., description="North velocity (m/s)")
    ve: float = Field(..., description="East velocity (m/s)")
    vd: float = Field(..., description="Down velocity (m/s)")


class AttitudeEuler(BaseModel):
    """Euler angles for attitude"""
    roll: float = Field(..., description="Roll angle (degrees)")
    pitch: float = Field(..., description="Pitch angle (degrees)")
    yaw: float = Field(..., description="Yaw angle (degrees)")


class BatteryStatus(BaseModel):
    """Battery telemetry"""
    voltage: float = Field(..., ge=0, description="Battery voltage (V)")
    current: Optional[float] = Field(None, description="Battery current (A)")
    remaining: Optional[float] = Field(None, ge=0, le=100, description="Battery remaining (%)")


class TelemetryReadinessCheck(BaseModel):
    """Per-check readiness detail surfaced from drone telemetry."""
    id: str = Field(..., description="Stable readiness check identifier")
    label: str = Field(..., description="Human-readable check label")
    ready: bool = Field(..., description="Whether this readiness check is currently passing")
    detail: str = Field(..., description="Operator-facing detail for this readiness check")


class TelemetryReadinessMessage(BaseModel):
    """Structured readiness/preflight message from telemetry or PX4 STATUSTEXT."""
    source: str = Field(..., description="Message source such as 'px4', 'telemetry', or 'link'")
    severity: str = Field(..., description="Normalized severity level")
    message: str = Field(..., description="Operator-facing status text")
    timestamp: int = Field(..., ge=0, description="Message timestamp (Unix ms)")


class DroneTelemetry(BaseModel):
    """Typed snapshot for the unified telemetry payload exposed by the GCS."""
    model_config = ConfigDict(extra='ignore')

    pos_id: Any = Field(..., description="Configured position ID")
    hw_id: str = Field(..., description="Hardware ID")
    detected_pos_id: Any = Field(None, description="Auto-detected position ID, if available")

    state: Any = Field(..., description="Current drone state code")
    mission: Any = Field(..., description="Current mission code")
    last_mission: Any = Field(..., description="Last mission code")
    trigger_time: int = Field(0, description="Mission trigger time (Unix epoch seconds)")

    position_lat: float = Field(..., description="Latitude in degrees")
    position_long: float = Field(..., description="Longitude in degrees")
    position_alt: float = Field(..., description="Altitude in meters MSL")
    velocity_north: float = Field(..., description="North velocity (m/s)")
    velocity_east: float = Field(..., description="East velocity (m/s)")
    velocity_down: float = Field(..., description="Down velocity (m/s)")
    yaw: float = Field(..., description="Heading in degrees")

    battery_voltage: float = Field(..., ge=0, description="Battery voltage (V)")
    follow_mode: Any = Field(..., description="Current follow mode value")

    update_time: Any = Field(..., description="Legacy update time field from the drone API")
    timestamp: int = Field(..., description="Telemetry timestamp (Unix ms)")
    server_time: Optional[int] = Field(None, description="Drone API response time (Unix ms)")
    telemetry_available: bool = Field(True, description="Whether the latest telemetry poll succeeded")
    telemetry_error: Optional[str] = Field(None, description="Latest telemetry fetch issue, if any")

    flight_mode: Any = Field(..., description="PX4 custom_mode / derived flight mode value")
    base_mode: Any = Field(..., description="MAVLink base_mode flags")
    system_status: Any = Field(..., description="PX4 / MAVLink system status")
    is_armed: bool = Field(..., description="Whether the drone is currently armed")
    is_ready_to_arm: bool = Field(..., description="Compatibility readiness boolean")
    home_position_set: bool = Field(False, description="Whether PX4 home position has been established")
    home_position_source: Optional[str] = Field(None, description="Source of the cached home position record (px4 or fallback_position)")

    readiness_status: str = Field("unknown", description="Operator-facing readiness state")
    readiness_summary: str = Field("Readiness unavailable", description="High-level readiness summary")
    readiness_checks: List[TelemetryReadinessCheck] = Field(default_factory=list, description="Structured readiness check results")
    preflight_blockers: List[TelemetryReadinessMessage] = Field(default_factory=list, description="Active readiness blockers")
    preflight_warnings: List[TelemetryReadinessMessage] = Field(default_factory=list, description="Active readiness warnings")
    status_messages: List[TelemetryReadinessMessage] = Field(default_factory=list, description="Recent PX4 or telemetry status messages")
    preflight_last_update: int = Field(0, description="Last readiness update timestamp (Unix ms)")

    hdop: float = Field(..., description="Horizontal dilution of precision")
    vdop: float = Field(..., description="Vertical dilution of precision")
    gps_fix_type: int = Field(..., ge=0, le=6, description="GPS fix type (0-6)")
    satellites_visible: int = Field(..., ge=0, description="Visible satellites")

    ip: str = Field(..., description="Drone IP address")
    heartbeat_last_seen: Optional[int] = Field(None, description="Last heartbeat timestamp (Unix ms)")
    heartbeat_network_info: Dict[str, Any] = Field(default_factory=dict, description="Recent heartbeat network metadata")
    heartbeat_first_seen: Optional[int] = Field(None, description="First heartbeat timestamp (Unix ms)")

    @field_validator('hw_id', mode='before')
    @classmethod
    def normalize_hw_id(cls, value: Any) -> str:
        """Normalize numeric hw_id values into the string form used by the GCS API."""
        return str(value)


class TelemetryResponse(BaseModel):
    """Response for GET /telemetry"""
    telemetry: Dict[str, DroneTelemetry] = Field(..., description="Telemetry by pos_id")
    total_drones: int = Field(..., ge=0, description="Total drones")
    online_drones: int = Field(..., ge=0, description="Online drones")
    timestamp: int = Field(..., description="Server timestamp (Unix ms)")

    @field_validator('telemetry', mode='before')
    @classmethod
    def normalize_telemetry_keys(cls, value: Any) -> Any:
        """Ensure telemetry maps always expose string keys on the API boundary."""
        if isinstance(value, dict):
            return {str(key): payload for key, payload in value.items()}
        return value


# ============================================================================
# Heartbeat Schemas
# ============================================================================

class HeartbeatData(BaseModel):
    """Individual drone heartbeat data"""
    pos_id: int = Field(..., ge=0, description="Position ID")
    hw_id: str = Field(..., description="Hardware ID")
    ip: str = Field(..., description="Drone IP address")
    detected_pos_id: Optional[int] = Field(None, ge=0, description="Auto-detected position ID")
    last_heartbeat: Optional[int] = Field(None, description="Last heartbeat timestamp (Unix ms)")
    online: bool = Field(..., description="Online status")
    latency_ms: Optional[float] = Field(None, ge=0, description="Network latency (ms)")


class HeartbeatResponse(BaseModel):
    """Response for GET /get-heartbeats"""
    heartbeats: List[HeartbeatData] = Field(..., description="Heartbeat data for all drones")
    total_drones: int = Field(..., ge=0, description="Total drones")
    online_count: int = Field(..., ge=0, description="Online drones")
    timestamp: int = Field(..., description="Server timestamp (Unix ms)")


class HeartbeatRequest(BaseModel):
    """Request for POST /heartbeat"""
    pos_id: int = Field(..., ge=0, description="Position ID")
    hw_id: str = Field(..., description="Hardware ID")
    detected_pos_id: Optional[int] = Field(None, ge=0, description="Auto-detected position ID")
    ip: Optional[str] = Field(None, description="Drone IP address")
    timestamp: Optional[int] = Field(None, description="Client timestamp (Unix ms)")
    network_info: Optional[Dict[str, Any]] = Field(None, description="Optional network details")

    @field_validator("hw_id", mode="before")
    @classmethod
    def normalize_hw_id(cls, value):
        """Accept legacy int IDs and normalize to string at the API boundary."""
        if value is None:
            raise ValueError("hw_id is required")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("hw_id must not be empty")
            return value
        if isinstance(value, int):
            return str(value)
        raise ValueError("hw_id must be a string or integer")

    @field_validator("ip", mode="before")
    @classmethod
    def normalize_ip(cls, value):
        """Normalize empty heartbeat IP values to None."""
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        if value.lower() in {"unknown", "n/a", "none", "null"}:
            return None
        return value


class HeartbeatPostResponse(BaseModel):
    """Response for POST /heartbeat"""
    success: bool = Field(..., description="Heartbeat received status")
    message: str = Field(..., description="Status message")
    server_time: int = Field(..., description="Server timestamp (Unix ms)")


# ============================================================================
# Git Status Schemas
# ============================================================================

class DroneGitStatus(BaseModel):
    """Git status for individual drone.

    Field names match the raw drone API response (/get-git-status on each drone)
    so the frontend can read them directly without remapping.
    """
    pos_id: int = Field(..., ge=1, description="Position ID")
    hw_id: str = Field(..., description="Hardware ID")
    ip: str = Field(..., description="Drone IP")

    # Git information (field names match drone API + frontend expectations)
    branch: str = Field(..., description="Current git branch")
    commit: str = Field(..., description="Latest commit hash")
    commit_message: Optional[str] = Field(None, description="Latest commit message")
    commit_date: Optional[str] = Field(None, description="Commit date (ISO format)")
    author_name: Optional[str] = Field(None, description="Commit author name")
    author_email: Optional[str] = Field(None, description="Commit author email")
    status: GitStatus = Field(..., description="Git sync status")

    # Synchronization
    in_sync_with_gcs: bool = Field(False, description="Whether the drone matches the current GCS branch/commit")
    commits_ahead: int = Field(0, ge=0, description="Commits ahead of origin")
    commits_behind: int = Field(0, ge=0, description="Commits behind origin")
    uncommitted_changes: List[str] = Field(default_factory=list, description="List of uncommitted file changes")

    # Timestamps
    last_check: int = Field(..., description="Last status check timestamp (Unix ms)")
    last_sync: Optional[int] = Field(None, description="Last successful sync timestamp (Unix ms)")


class GitStatusResponse(BaseModel):
    """Response for GET /git-status"""
    git_status: Dict[str, DroneGitStatus] = Field(..., description="Git status by pos_id")
    total_drones: int = Field(..., ge=0, description="Total drones")
    synced_count: int = Field(..., ge=0, description="Drones fully synced")
    needs_sync_count: int = Field(..., ge=0, description="Drones needing sync")
    gcs_status: Optional[Dict[str, Any]] = Field(None, description="GCS repository git status")
    sync_in_progress: bool = Field(False, description="Whether a sync operation is currently running")
    timestamp: int = Field(..., description="Server timestamp (Unix ms)")


class SyncReposRequest(BaseModel):
    """Request for POST /sync-repos"""
    pos_ids: Optional[List[int]] = Field(None, description="Specific drone IDs to sync (all if empty)")
    force_pull: bool = Field(False, description="Force pull from origin")


class SyncReposResponse(BaseModel):
    """Response for POST /sync-repos"""
    success: bool = Field(..., description="Sync operation status")
    message: str = Field(..., description="Status message")
    synced_drones: List[int] = Field(..., description="Successfully synced drone IDs")
    failed_drones: List[int] = Field(..., description="Failed drone IDs")
    total_attempted: int = Field(..., ge=0, description="Total sync attempts")


# ============================================================================
# Swarm Trajectory Schemas
# ============================================================================

class TrajectoryPoint(BaseModel):
    """Single trajectory waypoint"""
    t: float = Field(..., ge=0, description="Time (seconds)")
    x: float = Field(..., description="X coordinate (meters)")
    y: float = Field(..., description="Y coordinate (meters)")
    z: float = Field(..., ge=0, description="Z coordinate (meters)")
    yaw: Optional[float] = Field(0.0, description="Yaw angle (degrees)")


class DroneTrajectory(BaseModel):
    """Complete trajectory for one drone"""
    pos_id: int = Field(..., ge=1, description="Position ID")
    hw_id: Optional[str] = Field(None, description="Hardware ID")
    waypoints: List[TrajectoryPoint] = Field(..., min_length=1, description="Trajectory waypoints")
    total_duration: float = Field(..., ge=0, description="Total trajectory duration (s)")


class SwarmTrajectory(BaseModel):
    """Complete swarm trajectory"""
    show_name: str = Field(..., min_length=1, description="Show/trajectory name")
    drones: List[DroneTrajectory] = Field(..., min_length=1, description="Trajectories for all drones")
    total_drones: int = Field(..., ge=1, description="Total number of drones")
    max_duration: float = Field(..., ge=0, description="Maximum trajectory duration (s)")
    created_at: Optional[int] = Field(None, description="Creation timestamp (Unix ms)")


class TrajectoryListItem(BaseModel):
    """Trajectory summary for list view"""
    name: str = Field(..., description="Trajectory name")
    drone_count: int = Field(..., ge=0, description="Number of drones")
    duration: float = Field(..., ge=0, description="Duration (seconds)")
    file_size: int = Field(..., ge=0, description="File size (bytes)")
    created: Optional[str] = Field(None, description="Creation date (ISO format)")
    has_preview: bool = Field(..., description="Has plot preview available")


class TrajectoryListResponse(BaseModel):
    """Response for GET /api/swarm/trajectories"""
    trajectories: List[TrajectoryListItem] = Field(..., description="Available trajectories")
    total_count: int = Field(..., ge=0, description="Total trajectory count")
    current_trajectory: Optional[str] = Field(None, description="Currently active trajectory")


class TrajectoryUploadResponse(BaseModel):
    """Response for POST /api/swarm/trajectory/upload"""
    success: bool = Field(..., description="Upload success status")
    message: str = Field(..., description="Status message")
    trajectory_name: str = Field(..., description="Uploaded trajectory name")
    drone_count: int = Field(..., ge=0, description="Number of drones in trajectory")
    duration: float = Field(..., ge=0, description="Trajectory duration (s)")
    preview_url: Optional[str] = Field(None, description="Preview plot URL")


class SetActiveTrajectoryRequest(BaseModel):
    """Request for POST /api/swarm/trajectory/set-active"""
    trajectory_name: str = Field(..., min_length=1, description="Trajectory name to activate")


class SetActiveTrajectoryResponse(BaseModel):
    """Response for POST /api/swarm/trajectory/set-active"""
    success: bool = Field(..., description="Activation success status")
    message: str = Field(..., description="Status message")
    active_trajectory: str = Field(..., description="Now active trajectory")


class TrajectoryDeleteRequest(BaseModel):
    """Request for DELETE /api/swarm/trajectory/{name}"""
    confirm: bool = Field(False, description="Confirm deletion")


class TrajectoryDeleteResponse(BaseModel):
    """Response for DELETE /api/swarm/trajectory/{name}"""
    success: bool = Field(..., description="Deletion success status")
    message: str = Field(..., description="Status message")
    deleted_files: List[str] = Field(..., description="Deleted file paths")


# ============================================================================
# Show Control Schemas
# ============================================================================

class ShowImportRequest(BaseModel):
    """Request metadata for POST /import-show"""
    show_name: str = Field(..., min_length=1, description="Show name")
    overwrite: bool = Field(False, description="Overwrite existing show")


class ShowImportResponse(BaseModel):
    """Response for POST /import-show"""
    success: bool = Field(..., description="Import success status")
    message: str = Field(..., description="Status message")
    show_name: str = Field(..., description="Imported show name")
    files_processed: int = Field(..., ge=0, description="Number of files processed")
    drones_configured: int = Field(..., ge=0, description="Number of drones configured")
    raw_files_found: int = Field(0, ge=0, description="Number of raw CSV files found in the uploaded archive")
    plots_generated: int = Field(0, ge=0, description="Number of generated plot images")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings raised during import")
    next_steps: List[str] = Field(default_factory=list, description="Operator follow-up actions after import")
    git_info: Optional[Dict[str, Any]] = Field(None, description="Git auto-push result when enabled")


class CustomShowInfoResponse(BaseModel):
    """Response for GET /get-custom-show-info"""
    exists: bool = Field(..., description="Whether an active custom CSV exists")
    filename: str = Field(..., description="Active custom CSV filename")
    row_count: int = Field(..., ge=0, description="Number of trajectory rows")
    duration_sec: float = Field(..., ge=0, description="Total trajectory duration in seconds")
    max_altitude: float = Field(..., ge=0, description="Maximum altitude above launch frame in meters")
    preview_exists: bool = Field(..., description="Whether a preview image has been generated")
    execution_mode: str = Field(..., description="Execution mode summary")
    required_columns: List[str] = Field(default_factory=list, description="Required CSV protocol columns")


class CustomShowImportResponse(BaseModel):
    """Response for POST /import-custom-show"""
    success: bool = Field(..., description="Import success status")
    message: str = Field(..., description="Status message")
    filename: str = Field(..., description="Uploaded source filename")
    stored_as: str = Field(..., description="Stored active filename on disk")
    row_count: int = Field(..., ge=0, description="Number of validated trajectory rows")
    duration_sec: float = Field(..., ge=0, description="Total trajectory duration in seconds")
    max_altitude: float = Field(..., ge=0, description="Maximum altitude above launch frame in meters")
    preview_generated: bool = Field(..., description="Whether the preview image was regenerated")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings raised during import")
    next_steps: List[str] = Field(default_factory=list, description="Operator follow-up actions after import")
    git_info: Optional[Dict[str, Any]] = Field(None, description="Git auto-push result when enabled")


class CommandRequest(BaseModel):
    """Request schema for commands (used internally, not directly exposed)"""
    command: str = Field(..., min_length=1, description="Command to send")
    drone_ids: Optional[List[int]] = Field(None, description="Target drone IDs (all if empty)")
    params: Optional[Dict[str, Any]] = Field(None, description="Command parameters")


class CommandResponse(BaseModel):
    """Response for POST /submit_command (GCS endpoint for command submission)"""
    success: bool = Field(..., description="Command sent status")
    message: str = Field(..., description="Status message")
    command: str = Field(..., description="Command that was sent")
    target_drones: List[int] = Field(..., description="Targeted drone IDs")
    sent_count: int = Field(..., ge=0, description="Successfully sent count")


# ============================================================================
# Origin & GPS Schemas
# ============================================================================

class OriginRequest(BaseModel):
    """Request for POST /set-origin - Flask-compatible format"""
    lat: float = Field(..., ge=-90, le=90, description="Origin latitude")
    lon: float = Field(..., ge=-180, le=180, description="Origin longitude")
    alt: float = Field(..., description="Origin altitude (m MSL)")
    alt_source: Optional[str] = Field('manual', description="Altitude source (manual/drone)")


class OriginResponse(BaseModel):
    """Response for GET/POST origin endpoints - Flask-compatible format"""
    lat: float = Field(..., description="Origin latitude")
    lon: float = Field(..., description="Origin longitude")
    alt: float = Field(..., description="Origin altitude (m MSL)")
    timestamp: Optional[int] = Field(None, description="Last update timestamp (Unix ms)")


class GPSGlobalOriginResponse(BaseModel):
    """Response for GET /get-gps-global-origin"""
    latitude: float = Field(..., description="GPS global origin latitude")
    longitude: float = Field(..., description="GPS global origin longitude")
    altitude: float = Field(..., description="GPS global origin altitude (m MSL)")
    has_origin: bool = Field(..., description="Origin has been set")


# ============================================================================
# Network & System Schemas
# ============================================================================

class NetworkStatus(BaseModel):
    """Network connectivity status"""
    pos_id: int = Field(..., ge=1, description="Position ID")
    ip: str = Field(..., description="IP address")
    reachable: bool = Field(..., description="Network reachable")
    latency_ms: Optional[float] = Field(None, ge=0, description="Ping latency (ms)")
    packet_loss: Optional[float] = Field(None, ge=0, le=100, description="Packet loss (%)")
    last_check: int = Field(..., description="Last check timestamp (Unix ms)")


class NetworkStatusResponse(BaseModel):
    """Response for GET /get-network-status"""
    network_status: Dict[str, NetworkStatus] = Field(..., description="Network status by pos_id")
    total_drones: int = Field(..., ge=0, description="Total drones")
    reachable_count: int = Field(..., ge=0, description="Reachable drones")
    timestamp: int = Field(..., description="Server timestamp (Unix ms)")


class HealthCheckResponse(BaseModel):
    """Response for GET /ping or /health"""
    status: str = Field(..., description="Health status")
    timestamp: int = Field(..., description="Server timestamp (Unix ms)")
    uptime_seconds: Optional[float] = Field(None, ge=0, description="Server uptime")
    version: Optional[str] = Field(None, description="Server version")


# ============================================================================
# Error Schemas
# ============================================================================

class ErrorDetail(BaseModel):
    """Detailed error information"""
    loc: Optional[List[str]] = Field(None, description="Error location path")
    msg: str = Field(..., description="Error message")
    type: str = Field(..., description="Error type")


class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str = Field(..., description="Error message")
    detail: Optional[Union[str, List[ErrorDetail]]] = Field(None, description="Detailed error info")
    timestamp: int = Field(..., description="Error timestamp (Unix ms)")
    path: Optional[str] = Field(None, description="Request path that caused error")


# ============================================================================
# WebSocket Message Schemas
# ============================================================================

class WebSocketMessage(BaseModel):
    """Base WebSocket message structure"""
    type: str = Field(..., description="Message type")
    timestamp: int = Field(..., description="Message timestamp (Unix ms)")
    data: Dict[str, Any] = Field(..., description="Message payload")


class TelemetryStreamMessage(WebSocketMessage):
    """WebSocket telemetry stream message"""
    type: str = Field(default="telemetry", description="Message type")
    data: Dict[str, DroneTelemetry] = Field(..., description="Telemetry data by pos_id")

    @field_validator('data', mode='before')
    @classmethod
    def normalize_data_keys(cls, value: Any) -> Any:
        """Keep WebSocket telemetry keying consistent with the HTTP telemetry API."""
        if isinstance(value, dict):
            return {str(key): payload for key, payload in value.items()}
        return value


class GitStatusStreamMessage(WebSocketMessage):
    """WebSocket git status stream message"""
    type: str = Field(default="git_status", description="Message type")
    data: Dict[str, Any] = Field(..., description="Git status data")
    sync_in_progress: bool = Field(False, description="Whether a sync operation is currently running")


class HeartbeatStreamMessage(WebSocketMessage):
    """WebSocket heartbeat stream message"""
    type: str = Field(default="heartbeat", description="Message type")
    data: List[HeartbeatData] = Field(..., description="Heartbeat data for all drones")


# ============================================================================
# Command Tracking Schemas
# ============================================================================
# Note: CommandStatus enum is imported from src/enums.py to avoid duplication

class DroneAckDetail(BaseModel):
    """Acknowledgment detail from a single drone"""
    status: str = Field(
        ...,
        pattern="^(accepted|offline|rejected|error)$",
        description="'accepted', 'offline', 'rejected', or 'error'"
    )
    category: str = Field(
        "accepted",
        pattern="^(accepted|offline|rejected|error)$",
        description="Result category: 'accepted' (success), 'offline' (unreachable - neutral), 'rejected' (drone refused), 'error' (unexpected)"
    )
    message: Optional[str] = Field(None, max_length=500, description="Status message")
    error_code: Optional[str] = Field(None, pattern="^E[0-9]{3}$", description="Error code if rejected/error (e.g., E202)")
    error_detail: Optional[str] = Field(None, max_length=500, description="Detailed error information")
    timestamp: int = Field(..., ge=0, description="ACK timestamp (Unix ms)")


class DroneExecutionDetail(BaseModel):
    """Execution detail from a single drone"""
    success: bool = Field(..., description="Whether execution succeeded")
    error: Optional[str] = Field(None, description="Error message if failed")
    exit_code: Optional[int] = Field(None, description="Script exit code")
    duration_ms: Optional[int] = Field(None, description="Execution duration (ms)")
    timestamp: int = Field(..., description="Execution timestamp (Unix ms)")


class AckSummary(BaseModel):
    """Summary of acknowledgments for a command"""
    expected: int = Field(..., ge=0, description="Number of ACKs expected")
    received: int = Field(..., ge=0, description="Number of ACKs received")
    accepted: int = Field(..., ge=0, description="Number accepted")
    offline: int = Field(0, ge=0, description="Number offline (unreachable - neutral, not an error)")
    rejected: int = Field(0, ge=0, description="Number rejected (drone refused command)")
    errors: int = Field(0, ge=0, description="Number with unexpected errors")
    result_summary: Optional[str] = Field(None, description="Human-readable result summary (e.g., '1 accepted, 4 offline')")
    details: Dict[str, DroneAckDetail] = Field(default_factory=dict, description="Per-drone ACK details")


class ExecutionSummary(BaseModel):
    """Summary of executions for a command"""
    expected: int = Field(..., ge=0, description="Number of executions expected")
    started: int = Field(0, ge=0, description="Number of drones that reported execution start")
    active: int = Field(0, ge=0, description="Number of drones currently executing without a terminal result yet")
    received: int = Field(..., ge=0, description="Number of executions received")
    succeeded: int = Field(..., ge=0, description="Number succeeded")
    failed: int = Field(..., ge=0, description="Number failed")
    details: Dict[str, DroneExecutionDetail] = Field(default_factory=dict, description="Per-drone execution details")


class LateAckSummary(BaseModel):
    """Late acknowledgments recorded after the command already reached a terminal state."""
    received: int = Field(0, ge=0, description="Number of late ACKs received after terminal state")
    accepted: int = Field(0, ge=0, description="Late ACKs categorized as accepted")
    offline: int = Field(0, ge=0, description="Late ACKs categorized as offline")
    rejected: int = Field(0, ge=0, description="Late ACKs categorized as rejected")
    errors: int = Field(0, ge=0, description="Late ACKs categorized as errors")
    details: Dict[str, DroneAckDetail] = Field(default_factory=dict, description="Per-drone late ACK details")


class LateExecutionStartSummary(BaseModel):
    """Late execution-start reports recorded after the command already reached a terminal state."""
    received: int = Field(0, ge=0, description="Number of late execution-start reports")
    details: Dict[str, int] = Field(default_factory=dict, description="Per-drone late execution-start timestamps (Unix ms)")


class LateExecutionSummary(BaseModel):
    """Late execution results recorded after the command already reached a terminal state."""
    received: int = Field(0, ge=0, description="Number of late execution results received")
    succeeded: int = Field(0, ge=0, description="Late execution results marked successful")
    failed: int = Field(0, ge=0, description="Late execution results marked failed")
    details: Dict[str, DroneExecutionDetail] = Field(default_factory=dict, description="Per-drone late execution details")


class LateReportSummary(BaseModel):
    """Post-terminal evidence captured without mutating the original terminal outcome."""
    acks: LateAckSummary = Field(default_factory=LateAckSummary, description="Late acknowledgments captured after terminal state")
    execution_starts: LateExecutionStartSummary = Field(default_factory=LateExecutionStartSummary, description="Late execution-start reports captured after terminal state")
    executions: LateExecutionSummary = Field(default_factory=LateExecutionSummary, description="Late execution results captured after terminal state")


class CommandProgressSummary(BaseModel):
    """Operator-facing progress snapshot for a tracked command."""
    stage: str = Field(..., description="Normalized progress stage (awaiting_ack, scheduled, pending_execution, executing, finishing, completed, partial, failed, cancelled, timeout, superseded)")
    label: str = Field(..., description="Short operator-facing progress label")
    message: str = Field(..., description="Human-readable progress detail for dashboards and notifications")
    ack_pending: int = Field(0, ge=0, description="Number of target drones still missing ACKs")
    accepted: int = Field(0, ge=0, description="Number of drones that accepted the command")
    execution_pending: int = Field(0, ge=0, description="Accepted drones that have not yet reported execution start")
    active: int = Field(0, ge=0, description="Drones currently executing without a terminal result")
    completed: int = Field(0, ge=0, description="Accepted drones that have reported a terminal execution result")
    remaining: int = Field(0, ge=0, description="Accepted drones still missing a terminal execution result")
    scheduled_trigger_time: Optional[int] = Field(None, description="Scheduled trigger time in Unix ms when the command is waiting for a future trigger")


class CommandStatusResponse(BaseModel):
    """Detailed command status response"""
    command_id: str = Field(..., description="Command UUID")
    mission_type: int = Field(..., description="Mission type code")
    mission_name: str = Field(..., description="Human-readable mission name")
    target_drones: List[str] = Field(..., description="Target drone hardware IDs")
    params: Dict[str, Any] = Field(default_factory=dict, description="Command parameters")
    status: CommandStatus = Field(..., description="Current command status")
    phase: CommandPhase = Field(..., description="Operational phase separating ACK collection from actual execution")
    outcome: Optional[CommandOutcome] = Field(None, description="Terminal outcome when the command has finished")

    # Timing
    created_at: int = Field(..., description="Creation timestamp (Unix ms)")
    submitted_at: Optional[int] = Field(None, description="Submission timestamp (Unix ms)")
    execution_started_at: Optional[int] = Field(None, description="Timestamp when execution was first confirmed (Unix ms)")
    completed_at: Optional[int] = Field(None, description="Completion timestamp (Unix ms)")
    updated_at: int = Field(..., description="Last update timestamp (Unix ms)")

    # Summaries
    acks: AckSummary = Field(..., description="Acknowledgment summary")
    executions: ExecutionSummary = Field(..., description="Execution summary")
    late_reports: LateReportSummary = Field(default_factory=LateReportSummary, description="Late post-terminal ACK/execution evidence that did not change the final outcome")
    progress: CommandProgressSummary = Field(..., description="Operator-facing lifecycle progress snapshot")

    error_summary: Optional[str] = Field(None, description="Error summary if failed/partial")


class CommandListResponse(BaseModel):
    """Response for command list endpoint"""
    commands: List[CommandStatusResponse] = Field(..., description="List of commands")
    total: int = Field(..., ge=0, description="Total commands returned")
    timestamp: int = Field(..., description="Response timestamp (Unix ms)")


class CommandStatisticsResponse(BaseModel):
    """Response for command statistics endpoint"""
    total_commands: int = Field(..., ge=0, description="Total commands ever tracked")
    successful_commands: int = Field(..., ge=0, description="Number of successful commands")
    failed_commands: int = Field(..., ge=0, description="Number of failed commands")
    partial_commands: int = Field(..., ge=0, description="Number of partial success commands")
    timeout_commands: int = Field(..., ge=0, description="Number of timed out commands")
    cancelled_commands: int = Field(..., ge=0, description="Number of cancelled commands")
    active_commands: int = Field(..., ge=0, description="Currently active commands")
    tracked_commands: int = Field(..., ge=0, description="Commands in tracking history")
    success_rate: float = Field(..., ge=0, le=100, description="Success rate percentage")
    timestamp: int = Field(..., description="Response timestamp (Unix ms)")


class SubmitCommandRequest(BaseModel):
    """Request to submit a command to drones"""
    model_config = ConfigDict(extra='allow')  # Allow additional fields

    missionType: int = Field(..., description="Mission type code")
    triggerTime: Optional[int] = Field(0, ge=0, description="Trigger time (Unix epoch seconds)")
    pos_ids: Optional[List[int]] = Field(None, description="Target position IDs (None = all drones)")

    # Optional fields depending on mission type
    takeoff_altitude: Optional[float] = Field(None, gt=0, description="Takeoff altitude (m)")
    origin_lat: Optional[float] = Field(None, ge=-90, le=90, description="Origin latitude")
    origin_lon: Optional[float] = Field(None, ge=-180, le=180, description="Origin longitude")
    trajectory_id: Optional[str] = Field(None, description="Trajectory file identifier")

    # Control options
    wait_for_ack: bool = Field(False, description="Wait for all drone ACKs before returning")
    ack_timeout_ms: int = Field(5000, gt=0, description="ACK wait timeout (ms)")


class SubmitCommandResponse(BaseModel):
    """Response for command submission"""
    success: bool = Field(..., description="Whether command was successfully sent to at least one drone")
    command_id: str = Field(..., description="Command tracking UUID")
    status: str = Field(..., description="Submission status ('submitted', 'partial', 'offline', or 'failed')")
    mission_type: int = Field(..., description="Mission type code")
    mission_name: str = Field(..., description="Human-readable mission name")
    target_drones: List[str] = Field(..., description="Target drone hardware IDs")
    submitted_count: int = Field(..., ge=0, description="Number of drones command was sent to")

    # Immediate categorized results (always populated)
    results_summary: Optional[Dict[str, int]] = Field(
        None,
        description="Categorized results: {'accepted': N, 'offline': N, 'rejected': N, 'errors': N}"
    )

    # If wait_for_ack=true, these will be populated
    ack_summary: Optional[AckSummary] = Field(None, description="ACK summary if wait_for_ack=true")
    tracking_status: Optional[CommandStatus] = Field(None, description="Legacy tracker status for this command")
    tracking_phase: Optional[CommandPhase] = Field(None, description="Operational phase of command tracking")
    tracking_outcome: Optional[CommandOutcome] = Field(None, description="Terminal tracking outcome once known")
    tracking_timeout_ms: Optional[int] = Field(
        None,
        gt=0,
        description="Mission-aware lifecycle tracking timeout the frontend should reuse for status polling",
    )

    message: str = Field(..., description="Human-readable status message")
    timestamp: int = Field(..., description="Response timestamp (Unix ms)")


class ExecutionReportRequest(BaseModel):
    """Request from drone reporting execution result"""
    command_id: str = Field(..., description="Command UUID from GCS")
    hw_id: str = Field(..., description="Reporting drone's hardware ID")
    success: bool = Field(..., description="Whether execution succeeded")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    exit_code: Optional[int] = Field(None, description="Script exit code")
    script_output: Optional[str] = Field(None, description="Script output/logs (truncated)")
    duration_ms: Optional[int] = Field(None, ge=0, description="Execution duration (ms)")


class ExecutionStartRequest(BaseModel):
    """Request from drone reporting that command execution has actually started."""
    command_id: str = Field(..., description="Command UUID from GCS")
    hw_id: str = Field(..., description="Reporting drone's hardware ID")
    script_name: Optional[str] = Field(None, description="Mission/action script responsible for execution")


class ExecutionStartResponse(BaseModel):
    """Response for execution-start report."""
    received: bool = Field(..., description="Whether report was recorded")
    command_id: str = Field(..., description="Command UUID")
    command_status: CommandStatus = Field(..., description="Updated legacy command status")
    command_phase: CommandPhase = Field(..., description="Updated command phase")
    message: str = Field(..., description="Status message")
    timestamp: int = Field(..., description="Response timestamp (Unix ms)")


class ExecutionReportResponse(BaseModel):
    """Response for execution report"""
    received: bool = Field(..., description="Whether report was recorded")
    command_id: str = Field(..., description="Command UUID")
    command_status: CommandStatus = Field(..., description="Updated command status")
    message: str = Field(..., description="Status message")
    timestamp: int = Field(..., description="Response timestamp (Unix ms)")
