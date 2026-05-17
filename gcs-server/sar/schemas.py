"""
QuickScout SAR Module - Pydantic Schemas
"""

from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Any, Optional, List, Dict, Literal
from enum import Enum

from schemas import SubmitCommandResponse


class ReturnBehavior(str, Enum):
    RETURN_HOME = "return_home"
    LAND_CURRENT = "land_current"
    HOLD_POSITION = "hold_position"


class QuickScoutMissionTemplate(str, Enum):
    POINT_DISPATCH = "point_dispatch"
    AREA_SWEEP = "area_sweep"
    LAST_KNOWN_POINT = "last_known_point"
    CORRIDOR_SEARCH = "corridor_search"


class QuickScoutPlanningPositionMode(str, Enum):
    LIVE_DRONE_POSITIONS = "live_drone_positions"
    CONFIGURED_ORIGIN = "configured_origin"


class SurveyState(str, Enum):
    PLANNING = "planning"
    READY = "ready"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"


class QuickScoutMissionPhase(str, Enum):
    PLANNING = "planning"
    READY_TO_LAUNCH = "ready_to_launch"
    LAUNCH_PARTIAL = "launch_partial"
    SEARCHING = "searching"
    HOLDING = "holding"
    RETURN_COMMANDED = "return_commanded"
    COMPLETED = "completed"
    ABORTED = "aborted"


class QuickScoutControlEffect(str, Enum):
    COMMAND_ACCEPTED = "command_accepted"
    COMMAND_REJECTED = "command_rejected"
    REPLAN_REQUIRED = "replan_required"


class QuickScoutPlanningJobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    EXPIRED = "expired"


class QuickScoutControlAvailability(BaseModel):
    """Resolved operator control availability for the active mission."""

    pause_enabled: bool = Field(default=False, description="Whether HOLD/pause is currently available")
    pause_reason: Optional[str] = Field(None, description="Why pause is unavailable")
    replan_enabled: bool = Field(default=False, description="Whether follow-up planning is currently recommended")
    replan_reason: Optional[str] = Field(None, description="Why follow-up planning is recommended or unavailable")
    abort_enabled: bool = Field(default=False, description="Whether abort/end-mission control is currently available")
    abort_reason: Optional[str] = Field(None, description="Why abort is unavailable")


class FindingType(str, Enum):
    PERSON = "person"
    VESSEL = "vessel"
    VEHICLE = "vehicle"
    CLUE = "clue"
    HAZARD = "hazard"
    INFRASTRUCTURE = "infrastructure"
    ANOMALY = "anomaly"
    OTHER = "other"


class FindingPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(str, Enum):
    NEW = "new"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    HANDED_OFF = "handed_off"


class FindingConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingSource(str, Enum):
    OPERATOR_MARK = "operator_mark"
    DRONE_REPORT = "drone_report"
    SYSTEM_DETECTION = "system_detection"
    EXTERNAL_REPORT = "external_report"


# --- Request Models ---

class SearchAreaPoint(BaseModel):
    """Vertex coordinate of search area polygon"""
    lat: float = Field(..., ge=-90, le=90, description="Latitude (degrees)")
    lng: float = Field(..., ge=-180, le=180, description="Longitude (degrees)")


class SearchArea(BaseModel):
    """Template-aware search geometry definition."""
    type: str = Field(default="polygon", description="Search geometry type")
    points: List[SearchAreaPoint] = Field(default_factory=list, description="Polygon vertices when using area search")
    center: Optional[SearchAreaPoint] = Field(None, description="Center point for point-centered search templates")
    radius_m: Optional[float] = Field(None, gt=0, description="Point-search radius in meters")
    path: List[SearchAreaPoint] = Field(default_factory=list, description="Ordered route points for corridor search")
    corridor_width_m: Optional[float] = Field(None, gt=0, description="Total corridor width in meters")
    area_sq_m: Optional[float] = Field(None, ge=0, description="Computed area in square meters")

    @model_validator(mode="after")
    def validate_shape_requirements(self):
        if self.type == "polygon":
            if len(self.points) < 3:
                raise ValueError("Polygon search areas require at least 3 points")
            return self

        if self.type == "point":
            if self.center is None:
                raise ValueError("Point search areas require a center")
            return self

        if self.type == "line":
            if len(self.path) < 2:
                raise ValueError("Line search areas require at least 2 path points")
            if self.corridor_width_m is None or self.corridor_width_m <= 0:
                raise ValueError("Line search areas require a positive corridor width")
            return self

        raise ValueError(f"Unsupported search area type: {self.type}")


class SurveyConfig(BaseModel):
    """Survey configuration parameters"""
    algorithm: Literal["boustrophedon"] = Field(default="boustrophedon", description="Coverage algorithm")
    sweep_width_m: float = Field(default=30.0, gt=0, le=500, description="Sweep width in meters")
    overlap_percent: float = Field(default=10.0, ge=0, le=50, description="Overlap between sweeps (%)")
    cruise_altitude_msl: float = Field(
        default=50.0,
        gt=0,
        le=10000,
        description="Cruise altitude above mean sea level (MSL) in metres",
    )
    survey_altitude_agl: float = Field(default=40.0, gt=0, le=300, description="Survey altitude AGL (m)")
    cruise_speed_ms: float = Field(default=10.0, gt=0, le=25, description="Cruise speed (m/s)")
    survey_speed_ms: float = Field(default=5.0, gt=0, le=15, description="Survey speed (m/s)")
    use_terrain_following: bool = Field(default=True, description="Adjust altitude for terrain")
    camera_interval_s: float = Field(default=2.0, gt=0, le=30, description="Camera capture interval (s)")


class QuickScoutMissionRequest(BaseModel):
    """Request to plan or launch a QuickScout mission"""
    model_config = ConfigDict(extra='ignore')

    search_area: SearchArea = Field(..., description="Search area polygon")
    survey_config: SurveyConfig = Field(default_factory=SurveyConfig, description="Survey parameters")
    pos_ids: Optional[List[int]] = Field(None, description="Target drone position IDs (None = all)")
    position_source_mode: QuickScoutPlanningPositionMode = Field(
        default=QuickScoutPlanningPositionMode.LIVE_DRONE_POSITIONS,
        description="Source used for per-drone planning origins",
    )
    mission_template: QuickScoutMissionTemplate = Field(
        default=QuickScoutMissionTemplate.AREA_SWEEP,
        description="QuickScout mission template identifier",
    )
    mission_label: Optional[str] = Field(None, max_length=80, description="Optional operator-visible mission label")
    mission_profile: Optional[str] = Field(None, max_length=64, description="Selected planning profile identifier")
    mission_brief: Optional[str] = Field(None, max_length=500, description="Optional operator mission brief")
    return_behavior: ReturnBehavior = Field(default=ReturnBehavior.RETURN_HOME, description="End-of-mission behavior")


class QuickScoutElevationPoint(BaseModel):
    """Coordinate requested for QuickScout terrain context."""

    id: Optional[str] = Field(None, max_length=80, description="Caller-supplied point ID")
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")


class QuickScoutElevationResult(BaseModel):
    """Per-point terrain/elevation lookup result."""

    id: Optional[str] = Field(None, description="Caller-supplied point ID")
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    elevation_m: Optional[float] = Field(None, description="Resolved ground elevation MSL")
    status: Literal["ok", "unavailable"] = Field(..., description="Lookup status")
    source: str = Field(..., description="Elevation provider/source")
    provider: Optional[str] = Field(None, description="Normalized backend terrain provider")
    confidence: Optional[str] = Field(None, description="Provider confidence or quality hint")
    message: Optional[str] = Field(None, description="Operator-facing provider status")
    sample_time: Optional[Any] = Field(None, description="Provider sample timestamp when available")


class QuickScoutElevationBatchResponse(BaseModel):
    """Batch terrain/elevation lookup response with explicit unavailable state."""

    success: Literal[True] = Field(True, description="Always true for successful batch responses")
    elevations: List[Optional[float]] = Field(default_factory=list, description="Backward-compatible elevation list")
    results: List[QuickScoutElevationResult] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict, description="Lookup summary")
    count: int = Field(..., ge=0, description="Number of points processed")


# --- Internal/Response Models ---

class CoverageWaypoint(BaseModel):
    """Individual waypoint in a coverage plan"""
    lat: float = Field(..., ge=-90, le=90, description="Latitude (degrees)")
    lng: float = Field(..., ge=-180, le=180, description="Longitude (degrees)")
    alt_msl: float = Field(..., description="Altitude MSL (m)")
    alt_agl: Optional[float] = Field(None, description="Altitude AGL (m)")
    ground_elevation: Optional[float] = Field(None, description="Ground elevation MSL (m)")
    is_survey_leg: bool = Field(default=True, description="True if survey leg, False if transit")
    speed_ms: float = Field(..., gt=0, description="Target speed (m/s)")
    yaw_deg: Optional[float] = Field(None, description="Target yaw (degrees)")
    camera_interval_s: Optional[float] = Field(None, gt=0, description="Camera trigger interval (s)")
    sequence: int = Field(..., ge=0, description="Waypoint sequence number")


class DroneCoveragePlan(BaseModel):
    """Per-drone coverage plan"""
    model_config = ConfigDict(extra='ignore')

    hw_id: str = Field(..., description="Hardware ID")
    pos_id: int = Field(..., ge=0, description="Position ID")
    waypoints: List[CoverageWaypoint] = Field(..., min_length=1, description="Ordered waypoints")
    assigned_area_sq_m: float = Field(..., ge=0, description="Assigned coverage area (sq m)")
    estimated_duration_s: float = Field(..., ge=0, description="Estimated mission duration (s)")
    total_distance_m: float = Field(..., ge=0, description="Total path distance (m)")


class QuickScoutPlanningWarning(BaseModel):
    """Machine-readable planning warning for UI review and future automation."""

    code: str = Field(..., description="Stable warning code")
    message: str = Field(..., description="Operator-facing warning")
    details: Optional[Dict[str, Any]] = Field(None, description="Optional warning details")


class QuickScoutPlanningPositionSource(BaseModel):
    """Telemetry position source accepted for planning."""

    pos_id: int = Field(..., ge=0, description="Drone position ID")
    hw_id: Optional[str] = Field(None, description="Hardware ID when available")
    lat: float = Field(..., ge=-90, le=90, description="Accepted latitude")
    lng: float = Field(..., ge=-180, le=180, description="Accepted longitude")
    timestamp_ms: Optional[int] = Field(None, ge=0, description="Position sample timestamp (Unix ms)")
    age_s: Optional[float] = Field(None, ge=0, description="Position sample age in seconds")
    source: str = Field(default="global_position", description="Telemetry source used for planning")
    approximate: bool = Field(default=False, description="Whether this source is a planned/approximate position")
    details: Optional[Dict[str, Any]] = Field(None, description="Source-specific provenance details")


class QuickScoutPlanningOrigin(BaseModel):
    """Configured-origin provenance for staged QuickScout planning."""

    lat: float = Field(..., ge=-90, le=90, description="Configured origin latitude")
    lng: float = Field(..., ge=-180, le=180, description="Configured origin longitude")
    alt_msl: float = Field(default=0.0, description="Configured origin MSL altitude")
    heading_deg: float = Field(default=0.0, ge=0, lt=360, description="Launch-slot heading used for planning")
    timestamp_ms: Optional[int] = Field(None, ge=0, description="Origin timestamp when available")
    source: str = Field(default="configured_origin", description="Origin source label")


class QuickScoutTerrainSummary(BaseModel):
    """Terrain lookup summary for explicit altitude-source review."""

    requested: bool = Field(..., description="Whether terrain following was requested")
    status: str = Field(..., description="ok, unavailable, partial, or skipped")
    queried_waypoints: int = Field(default=0, ge=0, description="Number of terrain points queried")
    resolved_waypoints: int = Field(default=0, ge=0, description="Number of terrain points resolved")
    missing_waypoints: int = Field(default=0, ge=0, description="Number of terrain points without elevation")
    message: Optional[str] = Field(None, description="Operator-facing terrain status")


class CoveragePlanResponse(BaseModel):
    """Response from coverage planning endpoint"""
    model_config = ConfigDict(extra='ignore')

    mission_id: str = Field(..., description="Unique mission identifier")
    plans: List[DroneCoveragePlan] = Field(..., description="Per-drone coverage plans")
    total_area_sq_m: float = Field(..., ge=0, description="Total search area (sq m)")
    estimated_coverage_time_s: float = Field(..., ge=0, description="Estimated total coverage time (s)")
    algorithm_used: str = Field(..., description="Algorithm used for planning")
    warnings: List[QuickScoutPlanningWarning] = Field(default_factory=list, description="Planning warnings")
    position_sources: List[QuickScoutPlanningPositionSource] = Field(
        default_factory=list,
        description="Accepted live positions or configured launch slots used as planner origins",
    )
    position_source_mode: QuickScoutPlanningPositionMode = Field(
        default=QuickScoutPlanningPositionMode.LIVE_DRONE_POSITIONS,
        description="Source mode used for per-drone planning origins",
    )
    planning_origin: Optional[QuickScoutPlanningOrigin] = Field(
        None,
        description="Configured origin used when position_source_mode is configured_origin",
    )
    launchable: bool = Field(default=True, description="Whether the package can be launched without extra revalidation")
    requires_revalidation: bool = Field(
        default=False,
        description="Whether live GPS/slot revalidation is required before launch",
    )
    terrain_summary: Optional[QuickScoutTerrainSummary] = Field(
        None,
        description="Terrain lookup status when altitude behavior affected planning",
    )


class QuickScoutPlanningJobResponse(BaseModel):
    """Long-running QuickScout planning job state."""

    job_id: str = Field(..., description="Planning job identifier")
    status: QuickScoutPlanningJobState = Field(..., description="Planning job state")
    phase: str = Field(..., description="Current planning phase")
    progress_percent: int = Field(default=0, ge=0, le=100, description="Best-effort progress percentage")
    message: Optional[str] = Field(None, description="Operator-facing job message")
    mission_id: Optional[str] = Field(None, description="Generated mission ID when planning succeeds")
    result: Optional[CoveragePlanResponse] = Field(None, description="Coverage plan result when complete")
    error_code: Optional[str] = Field(None, description="Stable error code when failed")
    error_message: Optional[str] = Field(None, description="Operator-facing failure detail")
    warnings: List[QuickScoutPlanningWarning] = Field(default_factory=list, description="Planning warnings")
    cancel_requested: bool = Field(default=False, description="Whether cancellation was requested")
    created_at: float = Field(..., description="Job creation timestamp (Unix epoch)")
    updated_at: float = Field(..., description="Last job update timestamp (Unix epoch)")
    started_at: Optional[float] = Field(None, description="Job start timestamp (Unix epoch)")
    completed_at: Optional[float] = Field(None, description="Terminal timestamp (Unix epoch)")


class QuickScoutFinding(BaseModel):
    """Operator-visible QuickScout finding."""

    id: Optional[str] = Field(None, description="Finding unique identifier")
    type: FindingType = Field(default=FindingType.OTHER, description="Finding classification")
    priority: FindingPriority = Field(default=FindingPriority.MEDIUM, description="Priority level")
    summary: Optional[str] = Field(None, max_length=120, description="Short operator-facing finding summary")
    confidence: FindingConfidence = Field(default=FindingConfidence.MEDIUM, description="Operator confidence level")
    source: FindingSource = Field(default=FindingSource.OPERATOR_MARK, description="Finding source")
    lat: float = Field(..., ge=-90, le=90, description="Latitude (degrees)")
    lng: float = Field(..., ge=-180, le=180, description="Longitude (degrees)")
    alt_msl: Optional[float] = Field(None, description="Altitude MSL (m)")
    timestamp: Optional[float] = Field(None, description="Detection timestamp (Unix epoch)")
    updated_at: Optional[float] = Field(None, description="Last update timestamp (Unix epoch)")
    reported_by_drone: Optional[str] = Field(None, description="Reporting drone hw_id")
    drone_position: Optional[Dict] = Field(None, description="Drone position at detection time")
    notes: Optional[str] = Field(None, max_length=500, description="Operator notes")
    status: FindingStatus = Field(default=FindingStatus.NEW, description="Finding lifecycle status")
    mission_id: Optional[str] = Field(None, description="Associated mission ID")
    evidence_refs: List[str] = Field(default_factory=list, description="Optional evidence or artifact references")


class QuickScoutFindingCreate(BaseModel):
    """Typed payload for creating a new QuickScout finding."""
    model_config = ConfigDict(extra='forbid')

    type: FindingType = Field(default=FindingType.OTHER, description="Finding classification")
    priority: FindingPriority = Field(default=FindingPriority.MEDIUM, description="Priority level")
    summary: Optional[str] = Field(None, max_length=120, description="Short operator-facing finding summary")
    confidence: FindingConfidence = Field(default=FindingConfidence.MEDIUM, description="Operator confidence level")
    source: FindingSource = Field(default=FindingSource.OPERATOR_MARK, description="Finding source")
    lat: float = Field(..., ge=-90, le=90, description="Latitude (degrees)")
    lng: float = Field(..., ge=-180, le=180, description="Longitude (degrees)")
    alt_msl: Optional[float] = Field(None, description="Altitude MSL (m)")
    timestamp: Optional[float] = Field(None, description="Detection timestamp (Unix epoch)")
    reported_by_drone: Optional[str] = Field(None, description="Reporting drone hw_id")
    drone_position: Optional[Dict] = Field(None, description="Drone position at detection time")
    notes: Optional[str] = Field(None, max_length=500, description="Operator notes")
    status: FindingStatus = Field(default=FindingStatus.NEW, description="Finding lifecycle status")
    evidence_refs: List[str] = Field(default_factory=list, description="Optional evidence or artifact references")


class QuickScoutFindingUpdate(BaseModel):
    """Typed patch payload for updating an existing QuickScout finding."""
    model_config = ConfigDict(extra='forbid')

    type: Optional[FindingType] = Field(None, description="Finding classification")
    priority: Optional[FindingPriority] = Field(None, description="Priority level")
    summary: Optional[str] = Field(None, max_length=120, description="Short operator-facing finding summary")
    confidence: Optional[FindingConfidence] = Field(None, description="Operator confidence level")
    source: Optional[FindingSource] = Field(None, description="Finding source")
    lat: Optional[float] = Field(None, ge=-90, le=90, description="Latitude (degrees)")
    lng: Optional[float] = Field(None, ge=-180, le=180, description="Longitude (degrees)")
    alt_msl: Optional[float] = Field(None, description="Altitude MSL (m)")
    reported_by_drone: Optional[str] = Field(None, description="Reporting drone hw_id")
    drone_position: Optional[Dict] = Field(None, description="Drone position at detection time")
    notes: Optional[str] = Field(None, max_length=500, description="Operator notes")
    status: Optional[FindingStatus] = Field(None, description="Finding lifecycle status")
    evidence_refs: Optional[List[str]] = Field(None, description="Optional evidence or artifact references")

class DroneSurveyState(BaseModel):
    """Per-drone survey progress"""
    hw_id: str = Field(..., description="Hardware ID")
    pos_id: Optional[int] = Field(None, ge=0, description="Assigned mission slot / position ID")
    state: SurveyState = Field(default=SurveyState.READY, description="Drone survey state")
    current_waypoint_index: int = Field(default=0, ge=0, description="Current waypoint index")
    total_waypoints: int = Field(default=0, ge=0, description="Total waypoints")
    coverage_percent: float = Field(default=0.0, ge=0, le=100, description="Coverage completion (%)")
    distance_covered_m: float = Field(default=0.0, ge=0, description="Distance covered (m)")
    estimated_remaining_s: Optional[float] = Field(None, ge=0, description="Estimated time remaining (s)")
    status_note: Optional[str] = Field(None, description="Compact operator-facing status detail")
    last_update_at: Optional[float] = Field(None, ge=0, description="Last progress/control update timestamp (Unix epoch)")


class MissionStatus(BaseModel):
    """Full mission status"""
    model_config = ConfigDict(extra='ignore')

    mission_id: str = Field(..., description="Mission unique identifier")
    state: SurveyState = Field(default=SurveyState.PLANNING, description="Overall mission state")
    operation_phase: QuickScoutMissionPhase = Field(
        default=QuickScoutMissionPhase.PLANNING,
        description="Derived operator-facing mission phase",
    )
    drone_states: Dict[str, DroneSurveyState] = Field(default_factory=dict, description="Per-drone states keyed by hw_id")
    findings: List[QuickScoutFinding] = Field(default_factory=list, description="Operator findings linked to this mission")
    total_coverage_percent: float = Field(default=0.0, ge=0, le=100, description="Total coverage (%)")
    elapsed_time_s: float = Field(default=0.0, ge=0, description="Elapsed time (s)")
    started_at: Optional[float] = Field(None, description="Mission start timestamp (Unix epoch)")
    status_summary: str = Field(default="", description="Compact operator-facing mission status summary")
    recommended_operator_action: Optional[str] = Field(
        None,
        description="Suggested next operator action for degraded or transitional states",
    )
    control_availability: QuickScoutControlAvailability = Field(
        default_factory=QuickScoutControlAvailability,
        description="Resolved monitor/control affordances for the current mission state",
    )
    launch_summary: Optional[Dict[str, Any]] = Field(None, description="Latest launch batch summary for operator recovery")
    last_command_summary: Optional[Dict[str, Any]] = Field(
        None,
        description="Latest launch or control command summary for operator recovery",
    )


class QuickScoutMissionSummary(BaseModel):
    """Compact persisted mission summary for list/reopen flows."""

    mission_id: str = Field(..., description="Mission identifier")
    mission_template: QuickScoutMissionTemplate = Field(..., description="QuickScout mission template identifier")
    mission_label: Optional[str] = Field(None, description="Optional operator mission label")
    mission_profile: Optional[str] = Field(None, description="Selected planning profile identifier")
    state: SurveyState = Field(..., description="Overall mission state")
    created_at: float = Field(..., description="Mission creation timestamp (Unix epoch)")
    updated_at: float = Field(..., description="Last mission update timestamp (Unix epoch)")
    started_at: Optional[float] = Field(None, description="Mission launch timestamp (Unix epoch)")
    drone_count: int = Field(..., ge=0, description="Number of drones/plans in the mission")
    pos_ids: Optional[List[int]] = Field(None, description="Requested target position IDs")
    total_area_sq_m: float = Field(..., ge=0, description="Total search area (sq m)")
    estimated_coverage_time_s: float = Field(..., ge=0, description="Estimated coverage time (s)")
    algorithm_used: str = Field(..., description="Planner algorithm used")
    return_behavior: ReturnBehavior = Field(..., description="Configured mission end behavior")
    total_coverage_percent: float = Field(default=0.0, ge=0, le=100, description="Derived mission coverage (%)")
    finding_count: int = Field(default=0, ge=0, description="Persisted finding count")
    position_source_mode: QuickScoutPlanningPositionMode = Field(
        default=QuickScoutPlanningPositionMode.LIVE_DRONE_POSITIONS,
        description="Planner origin source mode used for this package",
    )
    launchable: bool = Field(default=True, description="Whether the package is launchable without extra revalidation")
    requires_revalidation: bool = Field(default=False, description="Whether launch requires live revalidation")
    last_command_summary: Optional[Dict] = Field(
        None,
        description="Most recent compact tracked-command recovery summary",
    )


class QuickScoutMissionCatalogResponse(BaseModel):
    """List response for persisted QuickScout missions."""

    missions: List[QuickScoutMissionSummary] = Field(default_factory=list, description="Persisted mission summaries")
    count: int = Field(..., ge=0, description="Number of missions in this response")


class QuickScoutLaunchSubmission(BaseModel):
    """Single tracked command submission used to launch one drone's QuickScout plan."""

    hw_id: str = Field(..., description="Target hardware ID")
    pos_id: int = Field(..., ge=0, description="Target position ID")
    accepted: bool = Field(..., description="Whether at least one target drone accepted the launch command")
    command: Optional[SubmitCommandResponse] = Field(
        None,
        description="Tracked command submission response when dispatch reached the command layer",
    )
    error: Optional[str] = Field(None, description="Error when launch submission failed before dispatch")


class QuickScoutMissionLaunchResponse(BaseModel):
    """Response returned when launching a planned QuickScout mission."""

    success: bool = Field(..., description="Whether at least one drone accepted the launch")
    mission_id: str = Field(..., description="Mission identifier")
    trigger_time: int = Field(..., ge=0, description="Shared mission trigger time (Unix epoch seconds)")
    drones_requested: int = Field(..., ge=0, description="Number of per-drone plans requested for launch")
    drones_launched: int = Field(..., ge=0, description="Number of drones that accepted launch")
    drones_failed: int = Field(..., ge=0, description="Number of drones that failed launch submission")
    launched_hw_ids: List[str] = Field(default_factory=list, description="Hardware IDs that accepted launch")
    failed_hw_ids: List[str] = Field(default_factory=list, description="Hardware IDs that failed launch")
    submissions: List[QuickScoutLaunchSubmission] = Field(
        default_factory=list,
        description="Per-drone tracked command submissions for the launch batch",
    )
    message: str = Field(..., description="Operator-facing summary")


class QuickScoutMissionLaunchRequest(BaseModel):
    """Optional launch payload for staged QuickScout package confirmation."""

    revalidation_token: Optional[str] = Field(
        None,
        description="Short-lived token returned by launch revalidation for staged packages",
    )


class QuickScoutLaunchRevalidationResponse(BaseModel):
    """Live GPS revalidation result for configured-origin QuickScout packages."""

    mission_id: str = Field(..., description="Mission identifier")
    launchable: bool = Field(..., description="Whether launch may proceed now")
    token: Optional[str] = Field(None, description="Short-lived launch token when launchable")
    expires_at: Optional[float] = Field(None, description="Token expiry timestamp (Unix epoch)")
    max_slot_error_m: float = Field(..., ge=0, description="Maximum allowed distance from planned slot")
    slot_errors_m: Dict[str, float] = Field(default_factory=dict, description="Live slot error by pos_id")
    blockers: List[QuickScoutPlanningWarning] = Field(default_factory=list, description="Blocking revalidation issues")
    warnings: List[QuickScoutPlanningWarning] = Field(default_factory=list, description="Non-blocking revalidation warnings")
    position_sources: List[QuickScoutPlanningPositionSource] = Field(
        default_factory=list,
        description="Live positions accepted during revalidation",
    )
    message: str = Field(..., description="Operator-facing result summary")


class QuickScoutMissionControlResponse(BaseModel):
    """Response returned when sending a tracked QuickScout control command."""

    success: bool = Field(..., description="Whether at least one targeted drone accepted the control command")
    mission_id: str = Field(..., description="Mission identifier")
    action: str = Field(..., description="Control action key such as 'pause' or 'abort'")
    effect: QuickScoutControlEffect = Field(..., description="Resolved control outcome")
    state_changed: bool = Field(..., description="Whether QuickScout mission state changed on the GCS")
    target_hw_ids: List[str] = Field(default_factory=list, description="Hardware IDs targeted by the control command")
    accepted_hw_ids: List[str] = Field(default_factory=list, description="Hardware IDs that accepted the command")
    failed_hw_ids: List[str] = Field(default_factory=list, description="Hardware IDs that did not accept the command")
    command: Optional[SubmitCommandResponse] = Field(
        None,
        description="Tracked command submission response when dispatch reached the command layer",
    )
    message: str = Field(..., description="Operator-facing summary")
    operator_guidance: Optional[str] = Field(None, description="Suggested operator next step")
    return_behavior: Optional[str] = Field(None, description="Resolved abort return behavior when applicable")


class QuickScoutOperationRecord(BaseModel):
    """Durable QuickScout operation record stored on the GCS."""
    model_config = ConfigDict(extra='ignore')

    mission_id: str = Field(..., description="Mission unique identifier")
    mission_template: QuickScoutMissionTemplate = Field(
        default=QuickScoutMissionTemplate.AREA_SWEEP,
        description="QuickScout mission template identifier",
    )
    mission_label: Optional[str] = Field(None, description="Optional operator-visible mission label")
    mission_profile: Optional[str] = Field(None, description="Selected planning profile identifier")
    mission_brief: Optional[str] = Field(None, description="Optional operator mission brief")
    state: SurveyState = Field(default=SurveyState.PLANNING, description="Overall mission state")
    search_area: SearchArea = Field(..., description="Search area definition")
    survey_config: SurveyConfig = Field(default_factory=SurveyConfig, description="Survey parameters")
    pos_ids: Optional[List[int]] = Field(None, description="Requested target drone position IDs")
    return_behavior: ReturnBehavior = Field(
        default=ReturnBehavior.RETURN_HOME,
        description="Configured end-of-mission behavior",
    )
    plans: List[DroneCoveragePlan] = Field(default_factory=list, description="Per-drone coverage plans")
    drone_states: Dict[str, DroneSurveyState] = Field(
        default_factory=dict,
        description="Per-drone states keyed by hw_id",
    )
    total_area_sq_m: float = Field(default=0.0, ge=0, description="Total search area (sq m)")
    estimated_coverage_time_s: float = Field(default=0.0, ge=0, description="Estimated coverage time (s)")
    algorithm_used: str = Field(default="boustrophedon", description="Planner algorithm used")
    planning_warnings: List[QuickScoutPlanningWarning] = Field(
        default_factory=list,
        description="Warnings produced while computing the mission package",
    )
    position_sources: List[QuickScoutPlanningPositionSource] = Field(
        default_factory=list,
        description="Accepted live positions or configured launch slots used while computing the mission package",
    )
    position_source_mode: QuickScoutPlanningPositionMode = Field(
        default=QuickScoutPlanningPositionMode.LIVE_DRONE_POSITIONS,
        description="Planner origin source mode used for this package",
    )
    planning_origin: Optional[QuickScoutPlanningOrigin] = Field(
        None,
        description="Configured origin used for staged planning",
    )
    launchable: bool = Field(default=True, description="Whether the package can be launched without extra revalidation")
    requires_revalidation: bool = Field(
        default=False,
        description="Whether live GPS/slot revalidation is required before launch",
    )
    terrain_summary: Optional[QuickScoutTerrainSummary] = Field(
        None,
        description="Terrain lookup status for the computed mission package",
    )
    created_at: float = Field(..., description="Creation timestamp (Unix epoch)")
    updated_at: float = Field(..., description="Last-update timestamp (Unix epoch)")
    started_at: Optional[float] = Field(None, description="Mission launch timestamp (Unix epoch)")
    launch_summary: Optional[Dict] = Field(
        None,
        description="Latest launch batch summary for operator recovery",
    )
    last_command_summary: Optional[Dict] = Field(
        None,
        description="Latest launch or control command summary for operator recovery",
    )


class QuickScoutMissionWorkspaceResponse(BaseModel):
    """Combined persisted mission package and live-derived status for workspace recovery."""

    operation: QuickScoutOperationRecord = Field(..., description="Persisted mission package and recovery data")
    status: MissionStatus = Field(..., description="Current derived mission status for the same mission")


class QuickScoutMissionHandoffFinding(BaseModel):
    """Compact finding payload included in operator handoff/export bundles."""

    id: str = Field(..., description="Finding identifier")
    summary: Optional[str] = Field(None, description="Short operator-facing finding summary")
    type: FindingType = Field(..., description="Finding classification")
    priority: FindingPriority = Field(..., description="Priority level")
    confidence: FindingConfidence = Field(..., description="Operator confidence level")
    status: FindingStatus = Field(..., description="Finding lifecycle status")
    lat: float = Field(..., ge=-90, le=90, description="Latitude (degrees)")
    lng: float = Field(..., ge=-180, le=180, description="Longitude (degrees)")
    reported_by_drone: Optional[str] = Field(None, description="Reporting drone hw_id")
    notes: Optional[str] = Field(None, description="Operator notes")
    evidence_refs: List[str] = Field(default_factory=list, description="Evidence or artifact references")


class QuickScoutMissionHandoff(BaseModel):
    """Canonical mission handoff/export bundle for operators and future automation layers."""

    mission_id: str = Field(..., description="Mission identifier")
    mission_label: Optional[str] = Field(None, description="Operator-visible mission label")
    mission_template: QuickScoutMissionTemplate = Field(..., description="QuickScout mission template")
    mission_state: SurveyState = Field(..., description="Current overall mission state")
    operation_phase: QuickScoutMissionPhase = Field(..., description="Derived operator-facing mission phase")
    mission_brief: Optional[str] = Field(None, description="Operator-entered mission brief")
    generated_at: float = Field(..., ge=0, description="Handoff generation timestamp (Unix epoch)")
    drone_count: int = Field(..., ge=0, description="Number of drones assigned to the mission package")
    total_area_sq_m: float = Field(..., ge=0, description="Total search area (sq m)")
    estimated_coverage_time_s: float = Field(..., ge=0, description="Estimated package coverage time (s)")
    total_coverage_percent: float = Field(..., ge=0, le=100, description="Derived mission coverage percent")
    status_summary: str = Field(default="", description="Compact mission status summary")
    recommended_operator_action: Optional[str] = Field(None, description="Suggested operator next step")
    finding_count: int = Field(default=0, ge=0, description="Total finding count")
    reviewed_finding_count: int = Field(default=0, ge=0, description="Findings that are no longer in the 'new' state")
    unresolved_finding_count: int = Field(default=0, ge=0, description="Findings still under review or awaiting disposition")
    confirmed_finding_count: int = Field(default=0, ge=0, description="Confirmed findings")
    handed_off_finding_count: int = Field(default=0, ge=0, description="Findings explicitly marked handed off")
    evidence_ref_count: int = Field(default=0, ge=0, description="Total evidence references across all findings")
    last_command_summary: Optional[Dict[str, Any]] = Field(
        None,
        description="Most recent launch/control recovery summary for the mission",
    )
    brief_text: str = Field(..., description="Operator-facing handoff summary text")
    findings: List[QuickScoutMissionHandoffFinding] = Field(
        default_factory=list,
        description="Findings included in the handoff bundle",
    )


class DroneProgressReport(BaseModel):
    """Progress report from drone"""
    hw_id: str = Field(..., description="Reporting drone hw_id")
    current_waypoint_index: int = Field(..., ge=0, description="Current waypoint index")
    total_waypoints: int = Field(..., ge=0, description="Total waypoints")
    distance_covered_m: float = Field(default=0.0, ge=0, description="Distance covered (m)")
    state: Optional[SurveyState] = Field(None, description="Drone survey state")
