# gcs-server/schemas.py
"""
GCS Server Pydantic Schemas
===========================
Comprehensive request/response models for all GCS API endpoints.
Ensures type safety and automatic validation for FastAPI migration.

Author: MAVSDK Drone Show Team
Last Updated: 2025-11-22
"""

from pydantic import BaseModel, Field, validator, ConfigDict
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum


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
    UNKNOWN = "unknown"


# ============================================================================
# Configuration Schemas
# ============================================================================

class DroneConfig(BaseModel):
    """Individual drone configuration"""
    model_config = ConfigDict(extra='allow')

    pos_id: int = Field(..., ge=0, description="Position ID (0-based)")
    hw_id: str = Field(..., min_length=1, description="Hardware ID")
    ip: str = Field(..., pattern=r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', description="IP address")
    connection_str: str = Field(..., description="MAVLink connection string")
    x: Optional[float] = Field(None, description="X coordinate (meters)")
    y: Optional[float] = Field(None, description="Y coordinate (meters)")
    z: Optional[float] = Field(None, description="Z coordinate (meters)")

    @validator('ip')
    def validate_ip(cls, v):
        """Validate IP address format"""
        octets = v.split('.')
        if len(octets) != 4:
            raise ValueError('Invalid IP address format')
        for octet in octets:
            if not 0 <= int(octet) <= 255:
                raise ValueError('IP octets must be 0-255')
        return v


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


class DroneTelemetry(BaseModel):
    """Complete drone telemetry snapshot"""
    model_config = ConfigDict(extra='allow')

    # Identity
    pos_id: int = Field(..., ge=0, description="Position ID")
    hw_id: str = Field(..., description="Hardware ID")

    # State
    state: DroneState = Field(..., description="Current drone state")
    flight_mode: FlightMode = Field(..., description="Current flight mode")
    armed: bool = Field(..., description="Armed status")
    in_air: bool = Field(..., description="In air status")

    # Position
    position_gps: Optional[PositionGPS] = Field(None, description="GPS position")
    position_ned: Optional[PositionNED] = Field(None, description="NED position")

    # Velocity & Attitude
    velocity_ned: Optional[VelocityNED] = Field(None, description="NED velocity")
    attitude: Optional[AttitudeEuler] = Field(None, description="Attitude (Euler angles)")

    # Battery
    battery: Optional[BatteryStatus] = Field(None, description="Battery status")

    # Health
    health_ok: bool = Field(..., description="Overall health status")
    gps_fix: Optional[int] = Field(None, ge=0, le=6, description="GPS fix type (0-6)")
    num_satellites: Optional[int] = Field(None, ge=0, description="Number of satellites")

    # Timestamps
    timestamp: int = Field(..., description="Telemetry timestamp (Unix ms)")
    last_heartbeat: Optional[int] = Field(None, description="Last heartbeat timestamp (Unix ms)")


class TelemetryResponse(BaseModel):
    """Response for GET /telemetry"""
    telemetry: Dict[str, DroneTelemetry] = Field(..., description="Telemetry by pos_id")
    total_drones: int = Field(..., ge=0, description="Total drones")
    online_drones: int = Field(..., ge=0, description="Online drones")
    timestamp: int = Field(..., description="Server timestamp (Unix ms)")


# ============================================================================
# Heartbeat Schemas
# ============================================================================

class HeartbeatData(BaseModel):
    """Individual drone heartbeat data"""
    pos_id: int = Field(..., ge=0, description="Position ID")
    hw_id: str = Field(..., description="Hardware ID")
    ip: str = Field(..., description="Drone IP address")
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
    timestamp: Optional[int] = Field(None, description="Client timestamp (Unix ms)")


class HeartbeatPostResponse(BaseModel):
    """Response for POST /heartbeat"""
    success: bool = Field(..., description="Heartbeat received status")
    message: str = Field(..., description="Status message")
    server_time: int = Field(..., description="Server timestamp (Unix ms)")


# ============================================================================
# Git Status Schemas
# ============================================================================

class DroneGitStatus(BaseModel):
    """Git status for individual drone"""
    pos_id: int = Field(..., ge=0, description="Position ID")
    hw_id: str = Field(..., description="Hardware ID")
    ip: str = Field(..., description="Drone IP")

    # Git information
    current_branch: str = Field(..., description="Current git branch")
    latest_commit: str = Field(..., description="Latest commit hash (short)")
    commit_message: Optional[str] = Field(None, description="Latest commit message")
    status: GitStatus = Field(..., description="Git sync status")

    # Synchronization
    commits_ahead: int = Field(..., ge=0, description="Commits ahead of origin")
    commits_behind: int = Field(..., ge=0, description="Commits behind origin")
    has_uncommitted: bool = Field(..., description="Has uncommitted changes")

    # Timestamps
    last_check: int = Field(..., description="Last status check timestamp (Unix ms)")
    last_sync: Optional[int] = Field(None, description="Last successful sync timestamp (Unix ms)")


class GitStatusResponse(BaseModel):
    """Response for GET /git-status"""
    git_status: Dict[str, DroneGitStatus] = Field(..., description="Git status by pos_id")
    total_drones: int = Field(..., ge=0, description="Total drones")
    synced_count: int = Field(..., ge=0, description="Drones fully synced")
    needs_sync_count: int = Field(..., ge=0, description="Drones needing sync")
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
    pos_id: int = Field(..., ge=0, description="Position ID")
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


class CommandRequest(BaseModel):
    """Request for POST /api/send-command"""
    command: str = Field(..., min_length=1, description="Command to send")
    drone_ids: Optional[List[int]] = Field(None, description="Target drone IDs (all if empty)")
    params: Optional[Dict[str, Any]] = Field(None, description="Command parameters")


class CommandResponse(BaseModel):
    """Response for POST /api/send-command"""
    success: bool = Field(..., description="Command sent status")
    message: str = Field(..., description="Status message")
    command: str = Field(..., description="Command that was sent")
    target_drones: List[int] = Field(..., description="Targeted drone IDs")
    sent_count: int = Field(..., ge=0, description="Successfully sent count")


# ============================================================================
# Origin & GPS Schemas
# ============================================================================

class OriginRequest(BaseModel):
    """Request for POST /set-origin"""
    latitude: float = Field(..., ge=-90, le=90, description="Origin latitude")
    longitude: float = Field(..., ge=-180, le=180, description="Origin longitude")
    altitude: float = Field(..., description="Origin altitude (m MSL)")


class OriginResponse(BaseModel):
    """Response for GET/POST origin endpoints"""
    latitude: float = Field(..., description="Origin latitude")
    longitude: float = Field(..., description="Origin longitude")
    altitude: float = Field(..., description="Origin altitude (m MSL)")
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
    pos_id: int = Field(..., ge=0, description="Position ID")
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


class GitStatusStreamMessage(WebSocketMessage):
    """WebSocket git status stream message"""
    type: str = Field(default="git_status", description="Message type")
    data: Dict[str, DroneGitStatus] = Field(..., description="Git status by pos_id")


class HeartbeatStreamMessage(WebSocketMessage):
    """WebSocket heartbeat stream message"""
    type: str = Field(default="heartbeat", description="Message type")
    data: List[HeartbeatData] = Field(..., description="Heartbeat data for all drones")
