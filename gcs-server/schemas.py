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
from typing import Optional, List, Dict, Any, Union, Literal
from datetime import datetime
from enum import Enum

# Import shared enums from src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from enums import CommandOutcome, CommandPhase, CommandStatus
from command_contract import SubmitCommandRequest as SharedSubmitCommandRequest


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


class FleetConfigEntryPayload(BaseModel):
    """Permissive fleet-config entry payload for the live dashboard contract."""
    model_config = ConfigDict(extra='allow')

    hw_id: Optional[Union[int, str]] = Field(None, description="Hardware ID")
    pos_id: Optional[int] = Field(None, ge=1, description="Position ID")
    ip: Optional[str] = Field(None, description="IP address")
    mavlink_port: Optional[int] = Field(None, ge=1, description="MAVLink UDP port")
    connection_str: Optional[str] = Field(None, description="Legacy connection string")


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


class SwarmConfigSaveResponse(BaseModel):
    """Response for PUT /api/v1/config/swarm"""
    status: str = Field(..., description="Save status")
    message: str = Field(..., description="Operator-facing result summary")
    config: SwarmConfig = Field(..., description="Persisted swarm configuration resource")
    git_result: Optional[Dict[str, Any]] = Field(None, description="Git commit/push result if auto-push enabled")


class SwarmAssignmentPatchRequest(BaseModel):
    """Patch payload for one saved swarm assignment."""
    model_config = ConfigDict(extra='forbid')

    follow: Optional[int] = Field(None, ge=0, description="Leader hw_id to follow (0 = independent)")
    offset_x: Optional[float] = Field(None, description="Offset axis 1: North (ned) or Forward (body), meters")
    offset_y: Optional[float] = Field(None, description="Offset axis 2: East (ned) or Right (body), meters")
    offset_z: Optional[float] = Field(None, description="Offset axis 3: Up (positive = higher), meters")
    frame: Optional[str] = Field(None, pattern=r'^(ned|body)$', description="Coordinate frame override")


class SwarmAssignmentUpdateResponse(BaseModel):
    """Response for PATCH /api/v1/config/swarm/assignments/{hw_id}"""
    status: str = Field(..., description="Update status")
    message: str = Field(..., description="Operator-facing result summary")
    assignment: SwarmAssignment = Field(..., description="Updated saved assignment")


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
# Fleet Candidate / Enrollment Schemas
# ============================================================================

class FleetCandidateState(str, Enum):
    """Registration lifecycle state for a discovered or announced node."""
    PENDING_OPERATOR_REVIEW = "pending_operator_review"
    CONFLICT = "conflict"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IGNORED = "ignored"
    SUPERSEDED = "superseded"


class FleetCandidateRecord(BaseModel):
    """Durable GCS-side candidate record for onboarding, replacement, and recovery."""
    model_config = ConfigDict(extra='ignore')

    candidate_id: str = Field(..., description="Stable candidate identifier")
    node_uuid: Optional[str] = Field(None, description="Node-local bootstrap UUID if reported")
    hw_id: Optional[str] = Field(None, description="Candidate hardware ID")
    hostname: Optional[str] = Field(None, description="Candidate hostname")
    reported_pos_id: Optional[str] = Field(None, description="Explicit pos_id reported by the node heartbeat")
    detected_pos_id: Optional[str] = Field(None, description="Auto-detected position hint from the node heartbeat")
    first_seen: int = Field(..., ge=0, description="First time the candidate was observed (Unix ms)")
    last_seen: int = Field(..., ge=0, description="Last time the candidate was observed by GCS (Unix ms)")
    last_heartbeat: Optional[int] = Field(None, ge=0, description="Last heartbeat timestamp seen for this candidate (Unix ms)")
    last_announce: Optional[int] = Field(None, ge=0, description="Last explicit announce timestamp for this candidate (Unix ms)")
    heartbeat_age_sec: Optional[int] = Field(None, ge=0, description="Derived heartbeat age in seconds")
    heartbeat_status: Optional[str] = Field(None, description="Derived heartbeat presence status")
    ip_addresses: List[str] = Field(default_factory=list, description="Unique observed candidate IP addresses")
    primary_control_ip: Optional[str] = Field(None, description="Preferred control-plane IP for the candidate")
    network_mode: Optional[str] = Field(None, description="Provisioned network mode")
    netbird_ip: Optional[str] = Field(None, description="NetBird-assigned overlay IP if present")
    repo_url: Optional[str] = Field(None, description="Provisioned repository URL")
    branch: Optional[str] = Field(None, description="Provisioned git branch")
    commit: Optional[str] = Field(None, description="Provisioned git revision if reported")
    bootstrap_version: Optional[str] = Field(None, description="Bootstrap script version if reported")
    bootstrap_status: Optional[str] = Field(None, description="Bootstrap status string")
    role_hint: Optional[str] = Field(None, description="Optional node role hint")
    mavlink_routing_mode: Optional[str] = Field(None, description="MAVLink routing mode")
    mavlink_input_type: Optional[str] = Field(None, description="MAVLink input type")
    mavlink_input_device: Optional[str] = Field(None, description="MAVLink input device path or URI")
    autopilot_link_state: Optional[str] = Field(None, description="Best-effort autopilot link health summary")
    registration_state: FleetCandidateState = Field(..., description="Current registration lifecycle state")
    conflict_reasons: List[str] = Field(default_factory=list, description="Active conflict reasons, if any")
    resolution: Optional[str] = Field(None, description="Latest accepted resolution path such as accepted_as_new or replaced_existing")
    replacement_target_hw_id: Optional[str] = Field(None, description="Existing fleet hw_id targeted by a replacement action")
    replacement_target_pos_id: Optional[str] = Field(None, description="Existing fleet pos_id preserved by a replacement action")
    notes: Optional[str] = Field(None, description="Operator or automation notes")


class FleetCandidateListResponse(BaseModel):
    """Response for listing fleet enrollment candidates."""
    candidates: List[FleetCandidateRecord] = Field(..., description="Candidate records")
    total_candidates: int = Field(..., ge=0, description="Number of returned candidate records")
    state_counts: Dict[str, int] = Field(default_factory=dict, description="Counts grouped by registration_state")
    timestamp: int = Field(..., ge=0, description="Response timestamp (Unix ms)")


class FleetCandidateAnnounceRequest(BaseModel):
    """Machine-friendly node bootstrap / identity announce payload."""
    model_config = ConfigDict(extra='forbid')

    node_uuid: Optional[str] = Field(None, description="Node-local bootstrap UUID")
    hw_id: Optional[Union[int, str]] = Field(None, description="Candidate hardware ID")
    hostname: Optional[str] = Field(None, description="Companion hostname")
    role_hint: Optional[str] = Field(None, description="Optional node role hint")
    repo_url: Optional[str] = Field(None, description="Provisioned repository URL")
    branch: Optional[str] = Field(None, description="Provisioned git branch")
    commit: Optional[str] = Field(None, description="Provisioned git revision if reported")
    bootstrap_version: Optional[str] = Field(None, description="Bootstrap script version")
    bootstrap_status: Optional[str] = Field(None, description="Bootstrap status")
    network_mode: Optional[str] = Field(None, description="Provisioned network mode")
    primary_control_ip: Optional[str] = Field(None, description="Preferred control-plane IP")
    mavlink_routing_mode: Optional[str] = Field(None, description="MAVLink routing mode")
    mavlink_input_type: Optional[str] = Field(None, description="MAVLink input type")
    mavlink_input_device: Optional[str] = Field(None, description="MAVLink input device path or URI")
    timestamp: Optional[int] = Field(None, ge=0, description="Announce timestamp (Unix ms)")

    @field_validator("hw_id", mode="before")
    @classmethod
    def normalize_candidate_hw_id(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
        return str(value) if value not in {"", None} else None


class FleetCandidateActionRequest(BaseModel):
    """Base request for simple candidate state mutations."""
    model_config = ConfigDict(extra='forbid')

    reason: Optional[str] = Field(None, description="Optional operator or automation note")


class FleetCandidateAcceptRequest(BaseModel):
    """Accept a pending candidate as a new fleet member."""
    model_config = ConfigDict(extra='forbid')

    pos_id: int = Field(..., ge=1, description="Assigned fleet position ID for the accepted candidate")
    ip: Optional[str] = Field(None, description="Override control-plane IP to save into config")
    mavlink_port: int = Field(..., ge=1, description="MAVLink UDP port to save into config")
    serial_port: str = Field('', description="Serial device path, empty for non-serial routing")
    baudrate: int = Field(0, ge=0, description="Serial baudrate")
    color: Optional[str] = Field(None, pattern=r'^#[0-9a-fA-F]{6}$', description="Optional UI color")
    notes: Optional[str] = Field(None, description="Operator notes to save into config")


class FleetCandidateReplaceRequest(BaseModel):
    """Replace an existing configured fleet member with a pending candidate."""
    model_config = ConfigDict(extra='forbid')

    target_hw_id: int = Field(..., ge=1, description="Existing fleet hardware ID to replace")
    ip: Optional[str] = Field(None, description="Override control-plane IP to save into config")
    mavlink_port: Optional[int] = Field(None, ge=1, description="Override MAVLink UDP port to save into config")
    serial_port: Optional[str] = Field(None, description="Override serial device path")
    baudrate: Optional[int] = Field(None, ge=0, description="Override serial baudrate")
    notes: Optional[str] = Field(None, description="Operator note describing the replacement")


class FleetCandidateRecoverRequest(BaseModel):
    """Recover an existing configured fleet member using the same hardware ID."""
    model_config = ConfigDict(extra='forbid')

    ip: Optional[str] = Field(None, description="Override control-plane IP to save into config")
    mavlink_port: Optional[int] = Field(None, ge=1, description="Override MAVLink UDP port to save into config")
    serial_port: Optional[str] = Field(None, description="Override serial device path")
    baudrate: Optional[int] = Field(None, ge=0, description="Override serial baudrate")
    notes: Optional[str] = Field(None, description="Operator note describing the recovery")


class FleetCandidatePostSyncPlan(BaseModel):
    """Operator/MCP-facing follow-up required after enrollment updates GCS-side state."""
    required: bool = Field(..., description="Whether the node still needs a follow-up sync/apply step")
    mode: str = Field(..., description="Sync doctrine such as git_sync_required or manual_repo_sync_required")
    target_hw_id: Optional[str] = Field(None, description="Hardware ID the operator should sync or verify")
    target_pos_id: Optional[str] = Field(None, description="Slot identity affected by the enrollment action")
    summary: str = Field(..., description="Short operator-facing summary of the required next step")
    action_hint: str = Field(..., description="Concrete next action to take")


class FleetCandidateMutationResponse(BaseModel):
    """Response for candidate enrollment/replacement state changes."""
    status: str = Field(..., description="Mutation status")
    message: str = Field(..., description="Operator-facing summary")
    candidate: FleetCandidateRecord = Field(..., description="Updated candidate record")
    warnings: List[str] = Field(default_factory=list, description="Non-blocking warnings")
    git_result: Optional[Dict[str, Any]] = Field(None, description="Git commit/push result if auto-push was requested")
    post_sync: Optional[FleetCandidatePostSyncPlan] = Field(
        None,
        description="Required node follow-up after GCS-side enrollment changes",
    )


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
    runtime_mode: Optional[str] = Field(None, description="Declared node runtime mode if reported")
    last_heartbeat: Optional[int] = Field(None, description="Last heartbeat timestamp (Unix ms)")
    online: bool = Field(..., description="Online status")
    latency_ms: Optional[float] = Field(None, ge=0, description="Network latency (ms)")


class HeartbeatResponse(BaseModel):
    """Response for GET /api/v1/fleet/heartbeats"""
    heartbeats: List[HeartbeatData] = Field(..., description="Heartbeat data for all drones")
    total_drones: int = Field(..., ge=0, description="Total drones")
    online_count: int = Field(..., ge=0, description="Online drones")
    timestamp: int = Field(..., description="Server timestamp (Unix ms)")


class HeartbeatRequest(BaseModel):
    """Request for POST /api/v1/fleet/heartbeats"""
    pos_id: int = Field(..., ge=0, description="Position ID")
    hw_id: str = Field(..., description="Hardware ID")
    detected_pos_id: Optional[int] = Field(None, ge=0, description="Auto-detected position ID")
    ip: Optional[str] = Field(None, description="Drone IP address")
    timestamp: Optional[int] = Field(None, description="Client timestamp (Unix ms)")
    network_info: Optional[Dict[str, Any]] = Field(None, description="Optional network details")
    runtime_mode: Optional[str] = Field(None, description="Canonical node runtime mode: real or sitl")

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

    @field_validator("runtime_mode", mode="before")
    @classmethod
    def normalize_runtime_mode(cls, value):
        if value is None:
            return None
        value = str(value).strip().lower()
        if not value:
            return None
        if value in {"real", "hardware", "production"}:
            return "real"
        if value in {"sitl", "sim", "simulation", "simulated"}:
            return "sitl"
        raise ValueError("runtime_mode must be either 'real' or 'sitl'")


class HeartbeatPostResponse(BaseModel):
    """Response for POST /api/v1/fleet/heartbeats"""
    success: bool = Field(..., description="Heartbeat received status")
    message: str = Field(..., description="Status message")
    server_time: int = Field(..., description="Server timestamp (Unix ms)")


# ============================================================================
# Git Status Schemas
# ============================================================================

class DroneGitStatus(BaseModel):
    """Git status for individual drone.

    Field names match the canonical drone API response (`GET /api/v1/git/status`)
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
    repo_access_mode: str = Field("custom_or_unknown", description="Resolved node repository access posture")
    git_auth_health_status: str = Field("unknown", description="Resolved node git auth health status")
    git_auth_health_summary: Optional[str] = Field(None, description="Operator-facing node git auth health summary")
    git_auth_health_issues: List[str] = Field(default_factory=list, description="Operator-facing node git auth issues")

    # Timestamps
    last_check: int = Field(..., description="Last status check timestamp (Unix ms)")
    last_sync: Optional[int] = Field(None, description="Last successful sync timestamp (Unix ms)")


class GitStatusResponse(BaseModel):
    """Response for the unified GCS git-status resource."""
    git_status: Dict[str, DroneGitStatus] = Field(..., description="Git status by pos_id")
    total_drones: int = Field(..., ge=0, description="Total drones")
    synced_count: int = Field(..., ge=0, description="Drones fully synced")
    needs_sync_count: int = Field(..., ge=0, description="Drones needing sync")
    gcs_status: Optional[Dict[str, Any]] = Field(None, description="GCS repository git status")
    sync_in_progress: bool = Field(False, description="Whether a sync operation is currently running")
    timestamp: int = Field(..., description="Server timestamp (Unix ms)")


class SyncReposRequest(BaseModel):
    """Request for triggering a GCS-managed git sync operation."""
    pos_ids: Optional[List[int]] = Field(None, description="Specific drone IDs to sync (all if empty)")
    force_pull: bool = Field(False, description="Force pull from origin")


class SyncReposResponse(BaseModel):
    """Response for a GCS-managed git sync operation."""
    success: bool = Field(..., description="Sync operation status")
    message: str = Field(..., description="Status message")
    synced_drones: List[int] = Field(..., description="Successfully synced drone IDs")
    failed_drones: List[int] = Field(..., description="Failed drone IDs")
    total_attempted: int = Field(..., ge=0, description="Total sync attempts")
    target_branch: Optional[str] = Field(None, description="Branch the drones were asked to match")
    target_commit: Optional[str] = Field(None, description="Commit the drones were verified against")


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


class SwarmTrajectoryLeaderListResponse(BaseModel):
    """Response for GET /api/v1/swarm-trajectories/leaders."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    leaders: List[int] = Field(default_factory=list, description="Current top-level leader drone IDs")
    hierarchies: Dict[str, int] = Field(
        default_factory=dict,
        description="Follower counts keyed by leader drone ID",
    )
    follower_details: Dict[str, List[int]] = Field(
        default_factory=dict,
        description="Follower drone IDs keyed by leader drone ID",
    )
    uploaded_leaders: List[int] = Field(default_factory=list, description="Leader IDs with uploaded CSV inputs")
    simulation_mode: bool = Field(False, description="Whether the system is running in SITL mode")

    @field_validator("hierarchies", "follower_details", mode="before")
    @classmethod
    def _normalize_swarm_mapping_keys(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): payload for key, payload in value.items()}
        return value


class SwarmTrajectoryUploadResponse(BaseModel):
    """Response for POST /api/v1/swarm-trajectories/upload/{leader_id}."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    message: str = Field(..., description="Operator-facing upload summary")
    filepath: str = Field(..., description="Saved raw CSV path relative to the active runtime filesystem")


class SwarmTrajectoryProcessRequest(BaseModel):
    """Optional processing controls for POST /api/v1/swarm-trajectories/process."""

    model_config = ConfigDict(extra='forbid')

    force_clear: bool = Field(False, description="Clear processed outputs before generating a fresh package")
    auto_reload: bool = Field(True, description="Auto-include unchanged leader uploads from the active workspace")


class SwarmTrajectoryCommitRequest(BaseModel):
    """Optional git commit metadata for POST /api/v1/swarm-trajectories/commit."""

    model_config = ConfigDict(extra='forbid')

    message: Optional[str] = Field(None, min_length=1, description="Optional git commit message override")

    @field_validator("message", mode="before")
    @classmethod
    def _normalize_commit_message(cls, value: Any) -> Any:
        if value in (None, ""):
            return None
        normalized = str(value).strip()
        return normalized or None


class SwarmTrajectoryProcessingChanges(BaseModel):
    """Change-detection details from the current workspace session."""

    has_previous_session: bool = Field(..., description="Whether the workspace has a prior processed session record")
    swarm_structure_changed: bool = Field(..., description="Whether swarm relationships changed since last process")
    parameters_changed: bool = Field(..., description="Whether trajectory processing parameters changed")
    trajectory_files_changed: bool = Field(..., description="Whether uploaded leader CSV contents changed")
    new_uploads: List[int] = Field(default_factory=list, description="Leader IDs newly uploaded since last process")
    missing_uploads: List[int] = Field(default_factory=list, description="Leader IDs removed since last process")
    leader_structure_changed: bool = Field(..., description="Whether leader coverage changed in a way that invalidates outputs")
    requires_full_reprocess: bool = Field(..., description="Whether the workspace requires a full reprocess")
    safe_to_incremental: bool = Field(..., description="Whether incremental processing is considered safe")


class SwarmTrajectoryProcessingRecommendation(BaseModel):
    """Operator-facing processing recommendation for the active workspace."""

    action: str = Field(..., description="Recommended processing action identifier")
    message: str = Field(..., description="Short operator-facing recommendation summary")
    details: List[str] = Field(default_factory=list, description="Detailed recommendation bullets")
    requires_confirmation: bool = Field(False, description="Whether the operator should explicitly confirm before proceeding")
    uploaded_count: int = Field(0, ge=0, description="Count of currently uploaded leader CSV files")
    changes: SwarmTrajectoryProcessingChanges = Field(..., description="Detected workspace changes behind this recommendation")
    expected_top_leaders: List[int] = Field(default_factory=list, description="Leader IDs required by the current swarm configuration")
    uploaded_leaders: List[int] = Field(default_factory=list, description="Leader IDs currently uploaded in the workspace")
    missing_uploaded_leaders: List[int] = Field(default_factory=list, description="Expected leaders still missing uploads")
    orphan_uploaded_leaders: List[int] = Field(default_factory=list, description="Uploaded leaders no longer present in the swarm configuration")


class SwarmTrajectoryRecommendationResponse(BaseModel):
    """Response for GET /api/v1/swarm-trajectories/recommendation."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    recommendation: SwarmTrajectoryProcessingRecommendation = Field(..., description="Current processing recommendation")


class SwarmTrajectoryDronePackageStats(BaseModel):
    """Per-drone processed package timing and altitude stats."""

    drone_id: int = Field(..., ge=1, description="Drone ID")
    route_entry_time_s: Optional[float] = Field(None, ge=0, description="First route-entry timestamp in seconds")
    mission_clock_s: Optional[float] = Field(None, ge=0, description="Mission completion timestamp in seconds")
    route_motion_time_s: Optional[float] = Field(None, ge=0, description="Time between route entry and completion")
    max_altitude_msl_m: Optional[float] = Field(None, description="Maximum altitude above MSL in meters")
    min_altitude_msl_m: Optional[float] = Field(None, description="Minimum altitude above MSL in meters")
    altitude_window_m: Optional[float] = Field(None, ge=0, description="Altitude envelope across the package")


class SwarmTrajectoryPackageStats(BaseModel):
    """Aggregate timing and altitude stats for a processed package."""

    available: bool = Field(..., description="Whether processed package stats are currently available")
    drone_count: int = Field(..., ge=0, description="Number of drones contributing to this package summary")
    drone_ids: List[int] = Field(default_factory=list, description="Drone IDs included in the package summary")
    route_entry_time_s: Optional[float] = Field(None, ge=0, description="Earliest route-entry timestamp in seconds")
    mission_clock_s: Optional[float] = Field(None, ge=0, description="Latest mission completion timestamp in seconds")
    route_motion_time_s: Optional[float] = Field(None, ge=0, description="Envelope duration between entry and completion")
    max_altitude_msl_m: Optional[float] = Field(None, description="Maximum altitude above MSL in meters")
    min_altitude_msl_m: Optional[float] = Field(None, description="Minimum altitude above MSL in meters")
    altitude_window_m: Optional[float] = Field(None, ge=0, description="Altitude envelope across the package")


class SwarmTrajectoryClusterSummary(BaseModel):
    """Readiness summary for all swarm clusters in the active workspace."""

    cluster_count: int = Field(..., ge=0, description="Number of top-level leader clusters in the swarm")
    ready_cluster_count: int = Field(..., ge=0, description="Clusters fully ready for launch packaging")
    needs_processing_cluster_count: int = Field(..., ge=0, description="Clusters waiting for processed outputs")
    missing_upload_cluster_count: int = Field(..., ge=0, description="Clusters missing required leader uploads")
    partial_output_cluster_count: int = Field(..., ge=0, description="Clusters with incomplete processed outputs")
    processed_cluster_count: int = Field(..., ge=0, description="Clusters with a processed leader output")
    all_clusters_ready: bool = Field(..., description="Whether every cluster is fully ready")
    overall_state: str = Field(..., description="High-level readiness state for the full workspace")


class SwarmTrajectoryClusterStatus(BaseModel):
    """Per-cluster readiness and artifact state for the active workspace."""

    leader_id: int = Field(..., ge=1, description="Top-level leader drone ID")
    follower_ids: List[int] = Field(default_factory=list, description="Follower drone IDs in this cluster")
    follower_count: int = Field(..., ge=0, description="Number of followers in this cluster")
    expected_drone_count: int = Field(..., ge=1, description="Expected total drones for the cluster")
    processed_drone_count: int = Field(..., ge=0, description="Processed drones currently available for the cluster")
    leader_uploaded: bool = Field(..., description="Whether the leader CSV upload is present")
    leader_processed: bool = Field(..., description="Whether the leader output was successfully processed")
    processed_follower_ids: List[int] = Field(default_factory=list, description="Follower drone IDs with processed outputs")
    missing_follower_ids: List[int] = Field(default_factory=list, description="Follower drone IDs still missing outputs")
    leader_plot_available: bool = Field(..., description="Whether the individual leader plot exists")
    cluster_plot_available: bool = Field(..., description="Whether the aggregate cluster plot exists")
    package_stats: SwarmTrajectoryPackageStats = Field(..., description="Processed package statistics scoped to this cluster")
    ready: bool = Field(..., description="Whether this cluster is fully ready")
    state: str = Field(..., description="Cluster readiness state identifier")
    issues: List[str] = Field(default_factory=list, description="Blocking issues for the cluster")
    advisories: List[str] = Field(default_factory=list, description="Non-blocking operator advisories for the cluster")


class SwarmTrajectorySessionStatus(BaseModel):
    """Saved processing-session metadata for the active workspace."""

    exists: bool = Field(..., description="Whether a processing session exists")
    session_id: Optional[str] = Field(None, description="Current processing session identifier")
    timestamp: Optional[str] = Field(None, description="ISO-8601 timestamp when the current session was created")
    processed_leaders: List[int] = Field(default_factory=list, description="Leader IDs included in the current session")
    total_drones: int = Field(0, ge=0, description="Total drones processed in the current session")


class SwarmTrajectoryStatusPayload(BaseModel):
    """Current Swarm Trajectory workspace state and readiness envelope."""

    raw_trajectories: int = Field(..., ge=0, description="Raw leader CSV file count")
    processed_trajectories: int = Field(..., ge=0, description="Processed per-drone CSV file count")
    generated_plots: int = Field(..., ge=0, description="Generated plot image count")
    raw_leaders: List[int] = Field(default_factory=list, description="Leader IDs with uploaded raw CSV files")
    processed_drones: List[int] = Field(default_factory=list, description="Drone IDs with processed outputs")
    processed_leaders: List[int] = Field(default_factory=list, description="Leader IDs with processed outputs")
    processed_followers: List[int] = Field(default_factory=list, description="Follower IDs with processed outputs")
    follow_map: Dict[str, int] = Field(default_factory=dict, description="Current follow assignments keyed by drone ID")
    leader_count: int = Field(..., ge=0, description="Processed leader count")
    follower_count: int = Field(..., ge=0, description="Processed follower count")
    package_stats: SwarmTrajectoryPackageStats = Field(..., description="Aggregate package timing and altitude stats")
    package_drone_stats: Dict[str, SwarmTrajectoryDronePackageStats] = Field(
        default_factory=dict,
        description="Per-drone processed package stats keyed by drone ID",
    )
    has_results: bool = Field(..., description="Whether processed outputs are currently available")
    plots_available: bool = Field(..., description="Whether any processed plots are currently available")
    expected_top_leaders: List[int] = Field(default_factory=list, description="Leader IDs expected by the current swarm configuration")
    uploaded_leaders: List[int] = Field(default_factory=list, description="Leader IDs currently uploaded")
    missing_uploaded_leaders: List[int] = Field(default_factory=list, description="Expected leaders still missing uploads")
    orphan_uploaded_leaders: List[int] = Field(default_factory=list, description="Uploaded leaders no longer present in the swarm configuration")
    clusters: List[SwarmTrajectoryClusterStatus] = Field(default_factory=list, description="Per-cluster readiness state")
    cluster_summary: SwarmTrajectoryClusterSummary = Field(..., description="Workspace-wide cluster readiness summary")
    session: SwarmTrajectorySessionStatus = Field(..., description="Saved processing session metadata")
    session_changes: SwarmTrajectoryProcessingChanges = Field(..., description="Detected workspace changes relative to the saved session")
    processing_recommendation: SwarmTrajectoryProcessingRecommendation = Field(..., description="Operator-facing processing recommendation")

    @field_validator("follow_map", "package_drone_stats", mode="before")
    @classmethod
    def _normalize_status_mapping_keys(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): payload for key, payload in value.items()}
        return value


class SwarmTrajectoryStatusResponse(BaseModel):
    """Response for GET /api/v1/swarm-trajectories/status."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    status: SwarmTrajectoryStatusPayload = Field(..., description="Current workspace state")
    folders: Dict[str, str] = Field(default_factory=dict, description="Active raw/processed/plot workspace paths")


class SwarmTrajectoryProcessingStatistics(BaseModel):
    """Processing totals from a successful reprocess run."""

    leaders: int = Field(..., ge=0, description="Number of leaders processed")
    followers: int = Field(..., ge=0, description="Number of followers processed")
    errors: int = Field(..., ge=0, description="Number of drones skipped due to processing errors")


class SwarmTrajectoryProcessResponse(BaseModel):
    """Response for POST /api/v1/swarm-trajectories/process."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    outcome: Literal["success", "partial"] = Field(..., description="Overall processing outcome")
    message: str = Field(..., description="Operator-facing processing summary")
    processed_drones: int = Field(..., ge=0, description="Number of drones processed into the output package")
    processed_drone_list: List[int] = Field(default_factory=list, description="Drone IDs included in the processed package")
    expected_drone_list: List[int] = Field(default_factory=list, description="Drone IDs expected by the current swarm configuration")
    skipped_drone_ids: List[int] = Field(default_factory=list, description="Drone IDs still missing outputs after processing")
    statistics: SwarmTrajectoryProcessingStatistics = Field(..., description="Processing totals")
    session_id: Optional[str] = Field(None, description="Saved processing session identifier")
    recommendation: SwarmTrajectoryProcessingRecommendation = Field(..., description="Recommendation snapshot captured at processing time")
    processed_leaders: List[int] = Field(default_factory=list, description="Leader IDs included in the processed package")
    missing_leaders: List[int] = Field(default_factory=list, description="Expected leaders still missing raw uploads")
    auto_reloaded: List[int] = Field(default_factory=list, description="Leader IDs auto-reloaded from the current workspace")
    ignored_leaders: List[int] = Field(default_factory=list, description="Uploaded leader IDs ignored because they are no longer valid top leaders")


class SwarmTrajectoryPolicyAltitude(BaseModel):
    """Altitude policy envelope for Swarm Trajectory planning."""

    default_msl: float = Field(..., description="Default altitude above mean sea level")
    default_target_agl: float = Field(..., description="Default target altitude above ground level")
    min_msl: float = Field(..., description="Minimum allowed altitude above mean sea level")
    max_msl: float = Field(..., description="Maximum allowed altitude above mean sea level")


class SwarmTrajectoryPolicySpeed(BaseModel):
    """Speed policy envelope for Swarm Trajectory planning."""

    default_preferred: float = Field(..., description="Default preferred route speed")
    min_preferred: float = Field(..., description="Minimum preferred route speed")
    optimal_max: float = Field(..., description="Preferred upper bound for routine authoring")
    absolute_max: float = Field(..., description="Hard speed ceiling")


class SwarmTrajectoryPolicyTiming(BaseModel):
    """Timing policy envelope for Swarm Trajectory planning."""

    default_route_entry_delay_s: float = Field(..., description="Default delay before route entry")
    default_fallback_leg_duration_s: float = Field(..., description="Fallback leg duration used when explicit timing is unavailable")
    derived_time_step_s: float = Field(..., description="Derived waypoint interpolation time step")


class SwarmTrajectoryPolicyTerrain(BaseModel):
    """Terrain clearance policy envelope for Swarm Trajectory planning."""

    min_safe_clearance_m: float = Field(..., description="Minimum allowed terrain clearance")
    default_safe_clearance_m: float = Field(..., description="Default terrain clearance target")


class SwarmTrajectoryPolicyPayload(BaseModel):
    """Operator-facing planning envelope sourced from Params."""

    altitude: SwarmTrajectoryPolicyAltitude = Field(..., description="Altitude planning policy")
    speed: SwarmTrajectoryPolicySpeed = Field(..., description="Speed planning policy")
    timing: SwarmTrajectoryPolicyTiming = Field(..., description="Timing planning policy")
    terrain: SwarmTrajectoryPolicyTerrain = Field(..., description="Terrain planning policy")


class SwarmTrajectoryPolicyResponse(BaseModel):
    """Response for GET /api/v1/swarm-trajectories/policy."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    policy: SwarmTrajectoryPolicyPayload = Field(..., description="Current planning envelope")


class SwarmTrajectoryClearProcessedResponse(BaseModel):
    """Response for POST /api/v1/swarm-trajectories/clear-processed."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    cleared_items: List[str] = Field(default_factory=list, description="Processed outputs and plots removed by the clear operation")
    message: str = Field(..., description="Operator-facing clear summary")


class SwarmTrajectoryClearAllResponse(BaseModel):
    """Response for POST /api/v1/swarm-trajectories/clear."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    message: str = Field(..., description="Operator-facing clear summary")
    cleared_directories: List[str] = Field(default_factory=list, description="Workspace artifacts removed by the clear operation")


class SwarmTrajectoryRemoveLeaderResponse(BaseModel):
    """Response for DELETE /api/v1/swarm-trajectories/remove/{leader_id}."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    message: str = Field(..., description="Operator-facing removal summary")
    removed_files: List[str] = Field(default_factory=list, description="Raw and derived files removed for the leader cluster")
    files_removed: int = Field(..., ge=0, description="Count of removed files")


class SwarmTrajectoryClearLeaderResponse(BaseModel):
    """Response for POST /api/v1/swarm-trajectories/clear-leader/{leader_id}."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    message: str = Field(..., description="Operator-facing clear summary")
    removed_files: List[str] = Field(default_factory=list, description="Files removed for the cleared leader cluster")


class SwarmTrajectoryClearDroneResponse(BaseModel):
    """Response for POST /api/v1/swarm-trajectories/clear-drone/{drone_id}."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    message: str = Field(..., description="Operator-facing clear summary")
    removed_files: List[str] = Field(default_factory=list, description="Follower files removed by the clear operation")


class SwarmTrajectoryCommitResponse(BaseModel):
    """Response for POST /api/v1/swarm-trajectories/commit."""

    success: Literal[True] = Field(True, description="Always true for successful responses")
    message: str = Field(..., description="Operator-facing git commit summary")
    git_info: Optional[Dict[str, Any]] = Field(None, description="Git commit and push result details")


# ============================================================================
# Show Control Schemas
# ============================================================================

class ShowImportRequest(BaseModel):
    """Request metadata for POST /api/v1/shows/skybrush/import"""
    show_name: str = Field(..., min_length=1, description="Show name")
    overwrite: bool = Field(False, description="Overwrite existing show")


class ShowImportResponse(BaseModel):
    """Response for POST /api/v1/shows/skybrush/import"""
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


class ShowDeploymentRequest(BaseModel):
    """Optional deployment metadata for POST /api/v1/shows/skybrush/deployments."""
    model_config = ConfigDict(extra='forbid')

    message: Optional[str] = Field(None, min_length=1, description="Optional git commit message override")

    @field_validator("message", mode="before")
    @classmethod
    def _normalize_show_deployment_message(cls, value):
        if value in (None, ""):
            return None
        normalized = str(value).strip()
        return normalized or None


class ShowDeploymentResponse(BaseModel):
    """Response for POST /api/v1/shows/skybrush/deployments."""
    success: bool = Field(..., description="Deployment success status")
    message: str = Field(..., description="Operator-facing deployment result")
    git_info: Optional[Dict[str, Any]] = Field(None, description="Git commit/push result")


class CustomShowInfoResponse(BaseModel):
    """Response for GET /api/v1/shows/custom"""
    exists: bool = Field(..., description="Whether an active custom CSV exists")
    filename: str = Field(..., description="Active custom CSV filename")
    row_count: int = Field(..., ge=0, description="Number of trajectory rows")
    duration_sec: float = Field(..., ge=0, description="Total trajectory duration in seconds")
    max_altitude: float = Field(..., ge=0, description="Maximum altitude above launch frame in meters")
    preview_exists: bool = Field(..., description="Whether a preview image has been generated")
    execution_mode: str = Field(..., description="Execution mode summary")
    required_columns: List[str] = Field(default_factory=list, description="Required CSV protocol columns")


class CustomShowImportResponse(BaseModel):
    """Response for POST /api/v1/shows/custom/import"""
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
    """Response for POST /api/v1/commands (GCS endpoint for command submission)"""
    success: bool = Field(..., description="Command sent status")
    message: str = Field(..., description="Status message")
    command: str = Field(..., description="Command that was sent")
    target_drones: List[int] = Field(..., description="Targeted drone IDs")
    sent_count: int = Field(..., ge=0, description="Successfully sent count")


# ============================================================================
# Origin & GPS Schemas
# ============================================================================

class OriginRequest(BaseModel):
    """Request for manual origin persistence."""
    lat: float = Field(..., ge=-90, le=90, description="Origin latitude")
    lon: float = Field(..., ge=-180, le=180, description="Origin longitude")
    alt: float = Field(0.0, description="Origin altitude (m MSL)")
    alt_source: Optional[str] = Field('manual', description="Altitude source (manual/drone)")


class OriginComputeRequest(BaseModel):
    """Request for computing origin from a live drone position plus assigned slot."""
    current_lat: float = Field(..., ge=-90, le=90, description="Current drone latitude")
    current_lon: float = Field(..., ge=-180, le=180, description="Current drone longitude")
    pos_id: int = Field(..., ge=1, description="Assigned launch-slot position ID")


class OriginComputeResponse(BaseModel):
    """Response for POST /api/v1/origin/compute."""
    status: str = Field(..., description="Computation status")
    lat: float = Field(..., description="Computed origin latitude")
    lon: float = Field(..., description="Computed origin longitude")


class OriginResponse(BaseModel):
    """Response for canonical origin read/write endpoints"""
    lat: float = Field(..., description="Origin latitude")
    lon: float = Field(..., description="Origin longitude")
    alt: float = Field(..., description="Origin altitude (m MSL)")
    timestamp: Optional[int] = Field(None, description="Last update timestamp (Unix ms)")
    source: Optional[str] = Field(None, description="Origin source")


class GPSGlobalOriginResponse(BaseModel):
    """Response for GET /api/v1/navigation/global-origin"""
    latitude: float = Field(..., description="GPS global origin latitude")
    longitude: float = Field(..., description="GPS global origin longitude")
    altitude: float = Field(..., description="GPS global origin altitude (m MSL)")
    has_origin: bool = Field(..., description="Origin has been set")


class GCSConfigResponse(BaseModel):
    """Response for GET /get-gcs-config."""
    sim_mode: bool = Field(..., description="Whether the GCS is running in simulation mode")
    mode: str = Field(..., description="Canonical running runtime mode")
    mode_source: str = Field(..., description="How the running runtime mode was resolved")
    configured_mode: str = Field(..., description="Configured host runtime mode from the system config")
    configured_sim_mode: bool = Field(..., description="Whether the configured host runtime mode is simulation mode")
    gcs_port: int = Field(..., ge=1, description="Configured GCS API port")
    git_auto_push: bool = Field(..., description="Whether git auto-push is enabled")
    configured_git_auto_push: bool = Field(..., description="Configured git auto-push state from the system config")
    acceptable_deviation: float = Field(..., ge=0, description="Allowed launch-position deviation in meters")
    gcs_config_path: str = Field(..., description="Path to the system GCS config file")
    gcs_config_present: bool = Field(..., description="Whether the system GCS config file exists")
    sitl_instance_count: Optional[int] = Field(None, ge=0, description="Detected local SITL instance count on this GCS host")
    restart_required: bool = Field(..., description="Whether the running process differs from the persisted host config")


class GCSConfigUpdateRequest(BaseModel):
    """Request payload for safe host-local GCS config persistence."""
    model_config = ConfigDict(extra='allow')

    mode: Optional[str] = Field(None, description="Requested canonical runtime mode: real or sitl")
    sim_mode: Optional[bool] = Field(None, description="Requested simulation mode flag")
    gcs_port: Optional[int] = Field(None, ge=1, description="Requested GCS API port")
    git_auto_push: Optional[bool] = Field(None, description="Requested git auto-push flag")
    acceptable_deviation: Optional[float] = Field(None, ge=0, description="Requested acceptable launch deviation")


class GCSConfigSaveResponse(BaseModel):
    """Response for safe host-local GCS config persistence."""
    success: bool = Field(..., description="Whether the request was accepted")
    status: str = Field(..., description="Compatibility status string")
    message: str = Field(..., description="Operator-facing result summary")
    persisted: bool = Field(..., description="Whether the config was actually written to disk/runtime state")
    config_path: Optional[str] = Field(None, description="Path to the persisted system config file")
    updated_keys: List[str] = Field(default_factory=list, description="System-config keys that were updated")
    configured_mode: Optional[str] = Field(None, description="Configured host runtime mode after persistence")
    configured_git_auto_push: Optional[bool] = Field(None, description="Configured git auto-push state after persistence")
    restart_required: bool = Field(..., description="Whether the running process must restart to apply the persisted config")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings for the operator")


class GCSConfigApplyResponse(BaseModel):
    """Response for applying persisted host-local GCS runtime settings."""
    success: bool = Field(..., description="Whether the apply request was accepted")
    status: str = Field(..., description="Apply status such as scheduled or no_restart_required")
    message: str = Field(..., description="Operator-facing result summary")
    configured_mode: str = Field(..., description="Configured host runtime mode that will be applied")
    configured_git_auto_push: bool = Field(..., description="Configured git auto-push state that will be applied")
    restart_required: bool = Field(..., description="Whether a restart was required at call time")
    scheduled: bool = Field(..., description="Whether a restart was scheduled")
    restart_delay_ms: int = Field(0, ge=0, description="Delay before the scheduled restart starts")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings for the operator")


class GCSRuntimeUpdateResponse(BaseModel):
    """Response for the constrained GCS fast-forward update flow."""

    success: bool = Field(..., description="Whether the update request was accepted")
    status: str = Field(..., description="Update status such as scheduled, no_update_available, or manual_update_required")
    message: str = Field(..., description="Operator-facing update result summary")
    update_readiness: str = Field(..., description="Resolved repo update posture at decision time")
    current_commit: str = Field(..., description="Current local commit when the decision was made")
    target_commit: Optional[str] = Field(None, description="Fetched upstream commit that would be applied")
    tracking_branch: Optional[str] = Field(None, description="Tracking branch used for the update decision")
    pending_paths_count: int = Field(0, ge=0, description="Number of pending changed paths between HEAD and tracking branch")
    blocked_paths: List[str] = Field(default_factory=list, description="Changed paths that require manual update handling")
    scheduled: bool = Field(..., description="Whether a fast-forward update and restart were scheduled")
    restart_delay_ms: int = Field(0, ge=0, description="Delay before the scheduled update launcher starts")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings for the operator")


class RuntimeDocsResponse(BaseModel):
    """Doc links surfaced in the runtime admin view."""

    mds_init_setup: Optional[str] = Field(None, description="Bootstrap/setup guide URL")
    fleet_sync_and_secrets: Optional[str] = Field(None, description="Fleet sync and secrets guide URL")
    mavlink_routing_setup: Optional[str] = Field(None, description="MAVLink routing guide URL")
    git_sync_feature: Optional[str] = Field(None, description="Git sync feature guide URL")


class RuntimeFleetDefaultsResponse(BaseModel):
    """Git-tracked fleet defaults exposed to the operator."""

    profile_id: str = Field(..., description="Deployment profile identifier")
    profile_source: str = Field(..., description="Deployment profile source")
    connectivity_backend: str = Field(..., description="Default connectivity backend for new nodes")
    smart_wifi_manager_repo_url_https: str = Field(..., description="Default Smart Wi-Fi Manager repo URL")
    smart_wifi_manager_ref: str = Field(..., description="Default Smart Wi-Fi Manager ref")
    smart_wifi_manager_mode: str = Field(..., description="Default Smart Wi-Fi Manager mode")
    smart_wifi_manager_import_mode: str = Field(..., description="Default Smart Wi-Fi Manager import mode")
    smart_wifi_manager_install_dir: str = Field(..., description="Default Smart Wi-Fi Manager install dir")
    smart_wifi_manager_dashboard_listen: str = Field(..., description="Default Smart Wi-Fi Manager dashboard listen address")
    smart_wifi_manager_profile_path: str = Field(..., description="Default Smart Wi-Fi Manager profile path")
    mavlink_management_mode: str = Field(..., description="Default mavlink-anywhere management mode")
    mavlink_anywhere_repo_url_https: str = Field(..., description="Default mavlink-anywhere repo URL")
    mavlink_anywhere_ref: str = Field(..., description="Default mavlink-anywhere ref")
    mavlink_anywhere_install_dir: str = Field(..., description="Default mavlink-anywhere install dir")
    mavlink_anywhere_dashboard_listen: str = Field(..., description="Default mavlink-anywhere dashboard listen address")
    mavlink_anywhere_skip_dashboard: bool = Field(..., description="Whether mavlink-anywhere dashboard is disabled by default")


class RuntimeGitAuthHealthResponse(BaseModel):
    """Resolved git auth/runtime health posture for the current host."""

    status: str = Field(..., description="Resolved auth health status")
    summary: str = Field(..., description="Operator-facing auth health summary")
    issues: List[str] = Field(default_factory=list, description="Actionable auth/runtime issues")


class RuntimeRepoSyncStatusResponse(BaseModel):
    """Resolved GCS repo sync/update posture for Runtime Admin."""

    branch: str = Field(..., description="Current branch")
    commit: str = Field(..., description="Current commit hash")
    remote_url: Optional[str] = Field(None, description="Current remote URL")
    tracking_branch: Optional[str] = Field(None, description="Current tracking branch")
    status: str = Field(..., description="Current working tree status")
    commits_ahead: int = Field(0, ge=0, description="Commits ahead of tracking branch")
    commits_behind: int = Field(0, ge=0, description="Commits behind tracking branch")
    update_readiness: str = Field(..., description="Resolved update posture such as up_to_date or ready_to_fast_forward")
    update_summary: str = Field(..., description="Operator-facing repo sync/update summary")
    fast_forward_update_available: bool = Field(..., description="Whether a safe fast-forward update is available")


class RuntimeMavlinkRuntimeResponse(BaseModel):
    """Managed mavlink-anywhere runtime status surfaced to Runtime Admin."""

    status_source: str = Field(..., description="How the runtime status was resolved")
    management_mode: str = Field(..., description="Managed/manual posture for mavlink-anywhere")
    repo_url: str = Field(..., description="Resolved mavlink-anywhere repo URL")
    ref: str = Field(..., description="Resolved mavlink-anywhere git ref")
    repo_web_url: Optional[str] = Field(None, description="Browsable repository URL")
    install_dir: str = Field(..., description="Resolved mavlink-anywhere install dir")
    install_dir_present: bool = Field(..., description="Whether the install dir exists")
    runtime_present: bool = Field(..., description="Whether a managed runtime checkout is present")
    runtime_head: Optional[str] = Field(None, description="Current managed runtime checkout commit")
    router_binary_present: bool = Field(..., description="Whether mavlink-router binary is present")
    router_service_status: str = Field(..., description="Current mavlink-router service status")
    dashboard_enabled: bool = Field(..., description="Whether the dashboard should be enabled")
    dashboard_listen: str = Field(..., description="Configured dashboard listen address")
    dashboard_service_status: str = Field(..., description="Current mavlink-anywhere dashboard service status")


class RuntimeConnectivityRuntimeResponse(BaseModel):
    """Connectivity backend runtime status surfaced to Runtime Admin."""

    status_source: str = Field(..., description="How the connectivity status was resolved")
    backend: str = Field(..., description="Resolved connectivity backend")
    repo_url: str = Field(..., description="Resolved Smart Wi-Fi Manager repo URL")
    ref: str = Field(..., description="Resolved Smart Wi-Fi Manager git ref")
    repo_web_url: Optional[str] = Field(None, description="Browsable repository URL")
    install_dir: str = Field(..., description="Resolved Smart Wi-Fi Manager install dir")
    install_dir_present: bool = Field(..., description="Whether the install dir exists")
    mode: str = Field(..., description="Resolved Smart Wi-Fi Manager mode")
    import_mode: str = Field(..., description="Resolved Smart Wi-Fi Manager import mode")
    profile_path: str = Field(..., description="Resolved Smart Wi-Fi Manager profile path")
    profile_present: bool = Field(..., description="Whether the resolved profile path exists")
    dashboard_listen: str = Field(..., description="Configured Smart Wi-Fi Manager dashboard listen address")
    service_status: str = Field(..., description="Current Smart Wi-Fi Manager service status")


class RuntimeStatusResponse(BaseModel):
    """Expanded runtime/admin status surface for the GCS."""

    version: str = Field(..., description="Running MDS version")
    timestamp: int = Field(..., description="Server timestamp (Unix ms)")
    uptime_seconds: float = Field(..., ge=0, description="GCS process uptime in seconds")
    mode: str = Field(..., description="Canonical runtime mode")
    mode_source: str = Field(..., description="How the runtime mode was resolved")
    sim_mode: bool = Field(..., description="Whether the current runtime is simulation mode")
    configured_mode: str = Field(..., description="Configured host runtime mode from the system config")
    configured_sim_mode: bool = Field(..., description="Whether the configured host runtime mode is simulation mode")
    gcs_port: int = Field(..., ge=1, description="Configured GCS API port")
    acceptable_deviation: float = Field(..., ge=0, description="Allowed launch-position deviation in meters")
    repo_url: str = Field(..., description="Configured repository URL")
    repo_branch: str = Field(..., description="Configured repository branch")
    repo_access_mode: str = Field(..., description="Resolved repository access posture")
    git_auto_push: bool = Field(..., description="Whether git auto-push is enabled")
    configured_git_auto_push: bool = Field(..., description="Configured git auto-push state from the system config")
    restart_required: bool = Field(..., description="Whether the running process differs from the persisted host config")
    sitl_instance_count: Optional[int] = Field(None, ge=0, description="Detected local SITL instance count on this GCS host")
    install_dir: Optional[str] = Field(None, description="Configured install directory for the GCS checkout")
    gcs_config_path: str = Field(..., description="Path to the system GCS config file")
    gcs_config_present: bool = Field(..., description="Whether the system GCS config file exists")
    git_auth_token_file: Optional[str] = Field(None, description="Configured HTTPS token-file path")
    git_auth_token_file_readable: bool = Field(..., description="Whether the configured HTTPS token-file path is readable")
    git_ssh_key_file: Optional[str] = Field(None, description="Configured SSH private key path")
    git_ssh_key_file_readable: bool = Field(..., description="Whether the configured SSH private key path is readable")
    git_auth_health: RuntimeGitAuthHealthResponse = Field(..., description="Resolved runtime git auth health posture")
    repo_sync_status: RuntimeRepoSyncStatusResponse = Field(..., description="Resolved GCS repo sync/update posture")
    fleet_defaults: RuntimeFleetDefaultsResponse = Field(..., description="Git-tracked defaults for future node bootstraps")
    mavlink_runtime: RuntimeMavlinkRuntimeResponse = Field(..., description="Resolved local managed mavlink-anywhere runtime status")
    connectivity_runtime: RuntimeConnectivityRuntimeResponse = Field(..., description="Resolved local connectivity backend runtime status")
    docs: RuntimeDocsResponse = Field(..., description="Relevant operator and agent guide links")


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
    """Response for GET /api/v1/fleet/network-status"""
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
    loc: Optional[List[Union[str, int]]] = Field(None, description="Error location path")
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
    idempotency_key: Optional[str] = Field(None, description="Client-supplied idempotency key when the command was created via replay-safe submission")
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


class PrecisionMovePolicyDefaults(BaseModel):
    """Runtime defaults for the Precision Move action."""
    speed_m_s: float = Field(..., gt=0, description="Default translation speed in m/s")
    position_tolerance_m: float = Field(..., gt=0, description="Default convergence position tolerance in metres")
    yaw_tolerance_deg: float = Field(..., gt=0, description="Default convergence yaw tolerance in degrees")
    settle_time_sec: float = Field(..., gt=0, description="Default settle duration after entering tolerance")
    timeout_sec: float = Field(..., gt=0, description="Default maximum execution timeout in seconds")


class PrecisionMovePolicyLimits(BaseModel):
    """Runtime safety and control limits for the Precision Move action."""
    max_translation_m: float = Field(..., gt=0, description="Maximum total translation magnitude in metres")
    max_speed_m_s: float = Field(..., gt=0, description="Maximum allowed translation speed in m/s")
    min_position_tolerance_m: float = Field(..., gt=0, description="Minimum allowed position tolerance in metres")
    max_timeout_sec: float = Field(..., gt=0, description="Maximum allowed action timeout in seconds")
    min_airborne_altitude_m: float = Field(..., gt=0, description="Minimum relative altitude required before the move is allowed")
    control_rate_hz: float = Field(..., gt=0, description="Offboard control-loop update rate in Hz")


class PrecisionMovePolicyExecution(BaseModel):
    """Operator-facing execution constraints for the Precision Move action."""
    supported_frames: List[str] = Field(..., description="Supported input frames")
    supported_yaw_modes: List[str] = Field(..., description="Supported yaw command modes")
    hold_mode: str = Field(..., description="Post-move hold handoff strategy")
    immediate_only: bool = Field(..., description="Whether the action must dispatch immediately")
    requires_airborne: bool = Field(..., description="Whether the drone must already be airborne")
    requires_local_position: bool = Field(..., description="Whether local position telemetry is required")


class PrecisionMovePolicyResponse(BaseModel):
    """Response for GET /api/v1/commands/policy/precision-move."""
    action: str = Field(..., description="Canonical action key")
    defaults: PrecisionMovePolicyDefaults = Field(..., description="Runtime defaults used when fields are omitted")
    limits: PrecisionMovePolicyLimits = Field(..., description="Runtime safety and control limits")
    execution: PrecisionMovePolicyExecution = Field(..., description="Execution constraints for operators and clients")


class SubmitCommandRequest(SharedSubmitCommandRequest):
    """Request body for POST /api/v1/commands."""


class SubmitCommandResponse(BaseModel):
    """Response for command submission"""
    success: bool = Field(..., description="Whether command was successfully sent to at least one drone")
    command_id: str = Field(..., description="Command tracking UUID")
    idempotency_key: Optional[str] = Field(None, description="Client-supplied idempotency key when present on submission")
    replayed: bool = Field(False, description="Whether this response replayed an existing command submission instead of creating a new command")
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

    ack_summary: Optional[AckSummary] = Field(
        None,
        description="Immediate ACK summary recorded during synchronous dispatch/tracker submission",
    )
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
