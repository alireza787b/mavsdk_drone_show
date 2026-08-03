"""Typed API schemas for the logging subsystem."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LogSessionSummary(BaseModel):
    session_id: str
    size_bytes: int
    modified: float


class LogSourcesResponse(BaseModel):
    components: dict[str, dict[str, Any]]


class LogSessionsResponse(BaseModel):
    sessions: list[LogSessionSummary]


class LogSessionContentResponse(BaseModel):
    session_id: str
    count: int
    lines: list[dict[str, Any]]


class FrontendLogReportRequest(BaseModel):
    level: str = "ERROR"
    component: str = "frontend"
    msg: str
    extra: Any | None = None


class LogExportRequest(BaseModel):
    session_ids: list[str] = Field(default_factory=list)
    format: Literal["jsonl", "zip"] = "jsonl"


class LogConfigUpdateRequest(BaseModel):
    background_pull: bool | None = None


class LogStatusResponse(BaseModel):
    status: str


class OnboardUlogPolicy(BaseModel):
    supported: bool = True
    transport: Literal["mavsdk_log_files"] = "mavsdk_log_files"
    storage_mode: Literal["file_backed", "streaming_only", "unsupported", "unknown"] = "file_backed"
    list_supported: bool = True
    download_supported: bool = True
    erase_all_supported: bool = True
    single_delete_supported: bool = False
    download_requires_disarmed: bool = True
    erase_requires_disarmed: bool = True
    staged_download_ttl_sec: int = 900
    notes: list[str] = Field(default_factory=list)


class OnboardUlogCapability(BaseModel):
    available: bool = False
    mavsdk_server_present: bool = False
    mavsdk_server_executable: bool = False
    mavsdk_server_path: str | None = None
    filesystem_fallback_configured: bool = False
    filesystem_fallback_paths: list[str] = Field(default_factory=list)
    filesystem_fallback_existing_paths: list[str] = Field(default_factory=list)
    missing_dependency: str | None = None
    detail: str = ""


class OnboardUlogPolicyResponse(BaseModel):
    hw_id: str
    pos_id: int | None = None
    policy: OnboardUlogPolicy
    ulog_capability: OnboardUlogCapability | None = None
    timestamp: int


class OnboardUlogEntry(BaseModel):
    id: int
    date_utc: str | None = None
    size_bytes: int


class OnboardUlogListResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    hw_id: str
    pos_id: int | None = None
    count: int
    files: list[OnboardUlogEntry]
    policy: OnboardUlogPolicy
    ulog_capability: OnboardUlogCapability | None = None
    timestamp: int


BoundedUlogName = Annotated[str, Field(min_length=1, max_length=128)]
NonNegativeUlogInt = Annotated[int, Field(ge=0)]
UlogCountMap = dict[BoundedUlogName, NonNegativeUlogInt]


class _StrictUlogSummaryModel(BaseModel):
    """Closed, finite-value schema shared by all derived ULog evidence."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        str_max_length=512,
    )


class UlogSourceSummary(_StrictUlogSummaryModel):
    source_kind: str = Field(default="ulog_file", min_length=1, max_length=64)
    log_id: int | None = Field(default=None, ge=0)
    date_utc: str | None = Field(default=None, max_length=64)
    size_bytes: int = Field(default=0, ge=0)


class UlogParserSummary(_StrictUlogSummaryModel):
    name: str = Field(default="pyulog", min_length=1, max_length=64)
    available: bool = False
    status: Literal["not_started", "ok", "failed", "skipped", "unavailable"] = "not_started"
    error: str | None = Field(default=None, max_length=500)
    topics_requested: list[BoundedUlogName] = Field(default_factory=list, max_length=32)
    topics_present: list[BoundedUlogName] = Field(default_factory=list, max_length=32)
    topic_sample_counts: UlogCountMap = Field(default_factory=dict, max_length=32)
    logged_topics: list[BoundedUlogName] = Field(default_factory=list, max_length=32)
    logged_topic_count: int = Field(default=0, ge=0)
    logged_topics_truncated: bool = False
    observability_warnings: list[
        Annotated[str, Field(min_length=1, max_length=512)]
    ] = Field(default_factory=list, max_length=16)


class UlogDurationEvidence(_StrictUlogSummaryModel):
    source: Literal[
        "overall_data_timestamps",
        "requested_topic_timestamps",
        "logged_event_timestamps",
        "unavailable",
    ] = "unavailable"
    lower_bound: bool = True
    data_messages_scanned: int = Field(default=0, ge=0)
    timestamp_scan_complete: bool = False


class UlogMetricRange(_StrictUlogSummaryModel):
    min: float | None = None
    max: float | None = None
    final: float | None = None


class UlogVector3(_StrictUlogSummaryModel):
    north: float | None = None
    east: float | None = None
    up: float | None = None


class UlogDropoutSummary(_StrictUlogSummaryModel):
    count: int = Field(default=0, ge=0)
    total_duration_sec: float = Field(default=0.0, ge=0)
    max_duration_ms: float = Field(default=0.0, ge=0)


class UlogLoggedMessagesSummary(_StrictUlogSummaryModel):
    count: int = Field(default=0, ge=0)
    levels: UlogCountMap = Field(default_factory=dict, max_length=32)
    raw_text_included: Literal[False] = False


class UlogSystemSummary(_StrictUlogSummaryModel):
    sys_name: str | None = Field(default=None, max_length=128)
    ver_hw: str | None = Field(default=None, max_length=128)


class UlogLocalPositionSummary(_StrictUlogSummaryModel):
    samples: int = Field(default=0, ge=0)
    x_range_m: UlogMetricRange | None = None
    y_range_m: UlogMetricRange | None = None
    relative_altitude_range_m: UlogMetricRange | None = None
    max_horizontal_distance_from_start_m: float | None = Field(default=None, ge=0)
    final_relative_position_m: UlogVector3 | None = None


class UlogTrajectorySetpointSummary(_StrictUlogSummaryModel):
    samples: int = Field(default=0, ge=0)
    north_m_range: UlogMetricRange | None = None
    east_m_range: UlogMetricRange | None = None
    down_m_range: UlogMetricRange | None = None


class UlogBatterySummary(_StrictUlogSummaryModel):
    samples: int = Field(default=0, ge=0)
    voltage_v: UlogMetricRange | None = None
    remaining: UlogMetricRange | None = None


class UlogVehicleStatusSummary(_StrictUlogSummaryModel):
    samples: int = Field(default=0, ge=0)
    arming_state: UlogCountMap = Field(default_factory=dict, max_length=32)
    nav_state: UlogCountMap = Field(default_factory=dict, max_length=64)
    failsafe: UlogCountMap = Field(default_factory=dict, max_length=8)
    hil_state: UlogCountMap = Field(default_factory=dict, max_length=8)


class UlogLandDetectedSummary(_StrictUlogSummaryModel):
    samples: int = Field(default=0, ge=0)
    landed: UlogCountMap = Field(default_factory=dict, max_length=8)
    maybe_landed: UlogCountMap = Field(default_factory=dict, max_length=8)
    ground_contact: UlogCountMap = Field(default_factory=dict, max_length=8)
    freefall: UlogCountMap = Field(default_factory=dict, max_length=8)


class UlogVehicleCommandSummary(_StrictUlogSummaryModel):
    samples: int = Field(default=0, ge=0)
    command_counts: UlogCountMap = Field(default_factory=dict, max_length=128)


class UlogVehicleCommandAckSummary(UlogVehicleCommandSummary):
    result_counts: UlogCountMap = Field(default_factory=dict, max_length=32)


class UlogCommandsSummary(_StrictUlogSummaryModel):
    vehicle_command: UlogVehicleCommandSummary | None = None
    vehicle_command_ack: UlogVehicleCommandAckSummary | None = None


class UlogCorrelationEvidence(_StrictUlogSummaryModel):
    """Bounded evidence used to associate one ULog with one guarded action."""

    target_drone_id: str | None = Field(default=None, max_length=128)
    ulog_log_id: int | None = Field(default=None, ge=0)
    ulog_started_at: str | None = Field(default=None, max_length=64)
    ulog_ended_at: str | None = Field(default=None, max_length=64)
    action_reference: str | None = Field(default=None, max_length=256)
    command_ids: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list,
        max_length=128,
    )
    command_window_started_at: str | None = Field(default=None, max_length=64)
    command_window_ended_at: str | None = Field(default=None, max_length=64)
    matched_dimensions: list[
        Literal["target", "time", "action_reference", "command_id"]
    ] = Field(default_factory=list, max_length=4)


class UlogActionCorrelation(_StrictUlogSummaryModel):
    """Typed, extensible mission-to-ULog association result."""

    status: Literal["unverified", "candidate", "verified", "ambiguous"] = "unverified"
    verified: bool = False
    method: Literal[
        "none",
        "source_metadata_only",
        "gcs_target_time_command_overlap",
        "gcs_target_time_action_command_overlap",
    ] = "none"
    evidence: UlogCorrelationEvidence = Field(default_factory=UlogCorrelationEvidence)
    limitations: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(
        default_factory=list,
        max_length=16,
    )


class UlogDerivedSummary(_StrictUlogSummaryModel):
    """Bounded derived metrics emitted by the isolated parser worker."""

    source: UlogSourceSummary = Field(default_factory=UlogSourceSummary)
    parser: UlogParserSummary = Field(default_factory=UlogParserSummary)
    parsed: bool = False
    duration_sec: float | None = Field(default=None, ge=0)
    duration_evidence: UlogDurationEvidence = Field(
        default_factory=UlogDurationEvidence
    )
    dropouts: UlogDropoutSummary = Field(default_factory=UlogDropoutSummary)
    logged_messages: UlogLoggedMessagesSummary = Field(
        default_factory=UlogLoggedMessagesSummary
    )
    system: UlogSystemSummary = Field(default_factory=UlogSystemSummary)
    local_position: UlogLocalPositionSummary | None = None
    trajectory_setpoint: UlogTrajectorySetpointSummary | None = None
    battery: UlogBatterySummary | None = None
    vehicle_status: UlogVehicleStatusSummary | None = None
    land_detected: UlogLandDetectedSummary | None = None
    commands: UlogCommandsSummary | None = None
    correlation: UlogActionCorrelation = Field(default_factory=UlogActionCorrelation)
    raw_content_included: Literal[False] = False


class OnboardUlogSummaryResponse(UlogDerivedSummary):
    schema_version: Literal["1.0"] = "1.0"
    hw_id: str = Field(min_length=1, max_length=128)
    pos_id: int | None = Field(default=None, ge=0)
    log_id: int = Field(ge=0)
    staged_job_deleted: bool | None = None
    timestamp: int = Field(ge=0)


class OnboardUlogDownloadRequest(BaseModel):
    pos_id: int | None = None


class OnboardUlogDownloadJob(BaseModel):
    job_id: str
    hw_id: str
    pos_id: int | None = None
    log_id: int
    date_utc: str | None = None
    size_bytes: int
    status: Literal["queued", "downloading", "ready", "failed", "expired"]
    progress: float = 0.0
    staged_filename: str | None = None
    download_filename: str | None = None
    created_at: int
    updated_at: int
    expires_at: int | None = None
    error: str | None = None


class OnboardUlogDownloadJobResponse(BaseModel):
    job: OnboardUlogDownloadJob
    timestamp: int


class OnboardUlogJobDeleteResponse(BaseModel):
    status: Literal["deleted"]
    job_id: str
    timestamp: int


class OnboardUlogEraseAllResponse(BaseModel):
    status: Literal["accepted"]
    hw_id: str
    pos_id: int | None = None
    timestamp: int
