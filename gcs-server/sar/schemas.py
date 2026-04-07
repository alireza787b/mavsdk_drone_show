"""
QuickScout SAR Module - Pydantic Schemas
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict
from enum import Enum


class ReturnBehavior(str, Enum):
    RETURN_HOME = "return_home"
    LAND_CURRENT = "land_current"
    HOLD_POSITION = "hold_position"


class SurveyState(str, Enum):
    PLANNING = "planning"
    READY = "ready"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"


class POIType(str, Enum):
    PERSON = "person"
    VEHICLE = "vehicle"
    STRUCTURE = "structure"
    ANOMALY = "anomaly"
    OTHER = "other"


class POIPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# --- Request Models ---

class SearchAreaPoint(BaseModel):
    """Vertex coordinate of search area polygon"""
    lat: float = Field(..., ge=-90, le=90, description="Latitude (degrees)")
    lng: float = Field(..., ge=-180, le=180, description="Longitude (degrees)")


class SearchArea(BaseModel):
    """Polygon definition for search area"""
    type: str = Field(default="polygon", description="Area type (polygon)")
    points: List[SearchAreaPoint] = Field(..., min_length=3, description="Polygon vertices (min 3)")
    area_sq_m: Optional[float] = Field(None, ge=0, description="Computed area in square meters")


class SurveyConfig(BaseModel):
    """Survey configuration parameters"""
    algorithm: str = Field(default="boustrophedon", description="Coverage algorithm")
    sweep_width_m: float = Field(default=30.0, gt=0, le=500, description="Sweep width in meters")
    overlap_percent: float = Field(default=10.0, ge=0, le=50, description="Overlap between sweeps (%)")
    cruise_altitude_msl: float = Field(default=50.0, gt=0, le=500, description="Cruise altitude MSL (m)")
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
    return_behavior: ReturnBehavior = Field(default=ReturnBehavior.RETURN_HOME, description="End-of-mission behavior")


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


class CoveragePlanResponse(BaseModel):
    """Response from coverage planning endpoint"""
    model_config = ConfigDict(extra='ignore')

    mission_id: str = Field(..., description="Unique mission identifier")
    plans: List[DroneCoveragePlan] = Field(..., description="Per-drone coverage plans")
    total_area_sq_m: float = Field(..., ge=0, description="Total search area (sq m)")
    estimated_coverage_time_s: float = Field(..., ge=0, description="Estimated total coverage time (s)")
    algorithm_used: str = Field(..., description="Algorithm used for planning")


class POI(BaseModel):
    """Point of Interest"""
    id: Optional[str] = Field(None, description="POI unique identifier")
    type: POIType = Field(default=POIType.OTHER, description="POI type")
    priority: POIPriority = Field(default=POIPriority.MEDIUM, description="Priority level")
    lat: float = Field(..., ge=-90, le=90, description="Latitude (degrees)")
    lng: float = Field(..., ge=-180, le=180, description="Longitude (degrees)")
    alt_msl: Optional[float] = Field(None, description="Altitude MSL (m)")
    timestamp: Optional[float] = Field(None, description="Detection timestamp (Unix epoch)")
    reported_by_drone: Optional[str] = Field(None, description="Reporting drone hw_id")
    drone_position: Optional[Dict] = Field(None, description="Drone position at detection time")
    notes: Optional[str] = Field(None, max_length=500, description="Operator notes")
    status: str = Field(default="new", description="POI status (new/confirmed/dismissed)")
    mission_id: Optional[str] = Field(None, description="Associated mission ID")


class DroneSurveyState(BaseModel):
    """Per-drone survey progress"""
    hw_id: str = Field(..., description="Hardware ID")
    state: SurveyState = Field(default=SurveyState.READY, description="Drone survey state")
    current_waypoint_index: int = Field(default=0, ge=0, description="Current waypoint index")
    total_waypoints: int = Field(default=0, ge=0, description="Total waypoints")
    coverage_percent: float = Field(default=0.0, ge=0, le=100, description="Coverage completion (%)")
    distance_covered_m: float = Field(default=0.0, ge=0, description="Distance covered (m)")
    estimated_remaining_s: Optional[float] = Field(None, ge=0, description="Estimated time remaining (s)")


class MissionStatus(BaseModel):
    """Full mission status"""
    model_config = ConfigDict(extra='ignore')

    mission_id: str = Field(..., description="Mission unique identifier")
    state: SurveyState = Field(default=SurveyState.PLANNING, description="Overall mission state")
    drone_states: Dict[str, DroneSurveyState] = Field(default_factory=dict, description="Per-drone states keyed by hw_id")
    pois: List[POI] = Field(default_factory=list, description="Points of interest")
    total_coverage_percent: float = Field(default=0.0, ge=0, le=100, description="Total coverage (%)")
    elapsed_time_s: float = Field(default=0.0, ge=0, description="Elapsed time (s)")
    started_at: Optional[float] = Field(None, description="Mission start timestamp (Unix epoch)")


class QuickScoutOperationRecord(BaseModel):
    """Durable QuickScout operation record stored on the GCS."""
    model_config = ConfigDict(extra='ignore')

    mission_id: str = Field(..., description="Mission unique identifier")
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
    created_at: float = Field(..., description="Creation timestamp (Unix epoch)")
    updated_at: float = Field(..., description="Last-update timestamp (Unix epoch)")
    started_at: Optional[float] = Field(None, description="Mission launch timestamp (Unix epoch)")
    launch_summary: Optional[Dict] = Field(
        None,
        description="Latest launch/control summary for operator recovery",
    )


class DroneProgressReport(BaseModel):
    """Progress report from drone"""
    hw_id: str = Field(..., description="Reporting drone hw_id")
    current_waypoint_index: int = Field(..., ge=0, description="Current waypoint index")
    total_waypoints: int = Field(..., ge=0, description="Total waypoints")
    distance_covered_m: float = Field(default=0.0, ge=0, description="Distance covered (m)")
    state: Optional[SurveyState] = Field(None, description="Drone survey state")
