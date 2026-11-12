"""Shared PX4 parameter models for drone, GCS, automation, and future MCP use."""

from __future__ import annotations

from enum import Enum
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, field_validator, model_validator
from src.px4_param_values import validate_parameter_value


Px4ParamValue = StrictInt | StrictFloat | StrictStr


def _validate_unique_entries(entries):
    keys = [(entry.component_id, entry.name) for entry in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate component/parameter entries are not allowed")
    return entries


class Px4ParamValueType(str, Enum):
    INT = "int"
    FLOAT = "float"
    CUSTOM = "custom"


class Px4ParamMetadataSource(str, Enum):
    VEHICLE = "vehicle"
    COMPONENT_INFORMATION = "component_information"
    PX4_BUILD_CATALOG = "px4_build_catalog"
    PX4_DOCS_CACHE = "px4_docs_cache"
    PX4_DOCS = "px4_docs"
    UNKNOWN = "unknown"


class Px4ParamPatchSource(str, Enum):
    MANUAL = "manual"
    QGC_IMPORT = "qgc_import"
    MDS_PROFILE = "mds_profile"
    API = "api"


class Px4ParamProfileScope(str, Enum):
    SINGLE = "single"
    SELECTED = "selected"
    CLUSTER = "cluster"
    FLEET = "fleet"


class Px4ParamProfileSource(str, Enum):
    REPO = "repo"


class Px4ParamPolicyDocs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    version: str
    base_url: str
    param_anchor_supported: bool = True


class Px4ParamPolicyMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_values: str
    float_metadata: str
    docs_links: str
    reboot_required: str


class Px4ParamPolicyMutations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_disarmed: bool = True
    supports_batch_apply: bool = True
    supports_qgc_import: bool = True
    supports_mds_profiles: bool = True
    supported_component_ids: List[int] = Field(default_factory=lambda: [1])


class Px4ParamPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subsystem: str = "px4_params"
    docs: Px4ParamPolicyDocs
    metadata: Px4ParamPolicyMetadata
    mutations: Px4ParamPolicyMutations


class Px4ParamRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: int = Field(1, ge=1)
    name: str = Field(..., min_length=1, max_length=16)
    value_type: Px4ParamValueType
    value: Px4ParamValue
    writable: bool = True
    docs_url: Optional[str] = None
    short_description: Optional[str] = None
    long_description: Optional[str] = None
    unit: Optional[str] = None
    group: Optional[str] = None
    category: Optional[str] = None
    decimal_places: Optional[int] = None
    increment: Optional[int | float] = None
    default_value: Optional[int | float | str] = None
    min_value: Optional[int | float] = None
    max_value: Optional[int | float] = None
    reboot_required: Optional[bool] = None
    enum_values: List[Dict[str, Any]] = Field(default_factory=list)
    metadata_sources: List[Px4ParamMetadataSource] = Field(default_factory=list)
    metadata_authority: str = "unavailable"
    authoritative_fields: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _finite_runtime_value(self):
        self.value = validate_parameter_value(self.value_type, self.value)
        return self

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: Any) -> str:
        if value is None:
            raise ValueError("parameter name is required")
        normalized = str(value).strip().upper()
        if not normalized:
            raise ValueError("parameter name must not be blank")
        return normalized


class Px4ParamProfileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    source: Px4ParamProfileSource = Px4ParamProfileSource.REPO
    recommended_scope: Px4ParamProfileScope = Px4ParamProfileScope.FLEET
    tags: List[str] = Field(default_factory=list)
    entry_count: int = Field(0, ge=0)
    updated_at: int

    @field_validator("profile_id", mode="before")
    @classmethod
    def _normalize_profile_id(cls, value: Any) -> str:
        normalized = str(value or "").strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("profile_id must not be blank")
        return normalized


class Px4ParamProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    source: Px4ParamProfileSource = Px4ParamProfileSource.REPO
    recommended_scope: Px4ParamProfileScope = Px4ParamProfileScope.FLEET
    tags: List[str] = Field(default_factory=list)
    entries: List["Px4ParamPatchEntry"] = Field(..., min_length=1, max_length=4096)
    updated_at: int

    @field_validator("entries")
    @classmethod
    def _unique_entries(cls, entries):
        return _validate_unique_entries(entries)

    @field_validator("profile_id", mode="before")
    @classmethod
    def _normalize_profile_response_id(cls, value: Any) -> str:
        normalized = str(value or "").strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("profile_id must not be blank")
        return normalized


class Px4ParamProfileListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: List[Px4ParamProfileSummary]
    total_profiles: int
    timestamp: int


class Px4ParamSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: int = Field(1, ge=1, le=255, strict=True)


class Px4ParamSnapshotSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    hw_id: str
    component_id: int = Field(1, ge=1)
    px4_docs_version: str
    total_params: int
    created_at: int
    stale_after_ms: int
    metadata_quality: str = Field(
        "raw_values_only",
        description="Operator-facing metadata quality: rich, catalog, component_information, or raw_values_only",
    )
    metadata_sources: List[Px4ParamMetadataSource] = Field(default_factory=list)
    metadata_warning: Optional[str] = None
    metadata_catalog_available: bool = False
    component_information_available: bool = False


class Px4ParamSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: Px4ParamSnapshotSummary
    rows: List[Px4ParamRow]


class Px4ParamFleetSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hw_ids: List[str] = Field(..., min_length=1)
    component_id: int = Field(1, ge=1, le=255, strict=True)

    @field_validator("hw_ids", mode="before")
    @classmethod
    def _normalize_hw_ids(cls, value: Any) -> List[str]:
        if not isinstance(value, list) or not value:
            raise ValueError("hw_ids must be a non-empty list")
        normalized = []
        for raw_value in value:
            normalized_value = str(raw_value).strip()
            if not normalized_value:
                raise ValueError("hw_ids must not contain blank entries")
            normalized.append(normalized_value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("hw_ids must not contain duplicate entries")
        return normalized


class Px4ParamFleetSnapshotError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hw_id: str
    error: str


class Px4ParamFleetSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshots: List[Px4ParamSnapshotResponse]
    errors: List[Px4ParamFleetSnapshotError] = Field(default_factory=list)
    total_targets: int
    timestamp: int


class Px4ParamSnapshotRowsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    rows: List[Px4ParamRow]
    total_rows: int
    timestamp: int


class Px4ParamValueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: Optional[str] = None
    row: Px4ParamRow
    timestamp: int


class Px4ParamSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: int = Field(1, ge=1, le=255, strict=True)
    value_type: Px4ParamValueType
    value: Px4ParamValue
    verify_readback: bool = True
    expected_current_value: Optional[Px4ParamValue] = None
    expected_hw_id: Optional[str] = Field(None, min_length=1, max_length=128)
    operation_id: Optional[str] = Field(None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _validate_type_and_value(self) -> "Px4ParamSetRequest":
        self.value = validate_parameter_value(self.value_type, self.value)
        if self.expected_current_value is not None:
            self.expected_current_value = validate_parameter_value(self.value_type, self.expected_current_value)
        return self


class Px4ParamSetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: bool
    verified: bool
    component_id: int = Field(1, ge=1)
    name: str
    value_type: Px4ParamValueType
    requested_value: int | float | str
    actual_value: Optional[int | float | str] = None
    timestamp: int
    outcome: str = "unknown"
    write_acknowledged: bool = False
    readback_status: str = "not_attempted"
    error_phase: Optional[str] = None
    error: Optional[str] = None
    operation_id: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: Any) -> str:
        if value is None:
            raise ValueError("parameter name is required")
        normalized = str(value).strip().upper()
        if not normalized:
            raise ValueError("parameter name must not be blank")
        return normalized


class Px4ParamPatchEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: int = Field(1, ge=1, le=255, strict=True)
    name: str = Field(..., min_length=1, max_length=16)
    value_type: Px4ParamValueType
    value: Px4ParamValue
    expected_current_value: Optional[Px4ParamValue] = None

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: Any) -> str:
        if value is None:
            raise ValueError("parameter name is required")
        if not isinstance(value, str):
            raise ValueError("parameter name must be text")
        normalized = value.strip().upper()
        if not value.isascii() or not re.fullmatch(r"[A-Z0-9_]{1,16}", normalized):
            raise ValueError("parameter name must contain 1–16 ASCII letters, digits or underscores")
        return normalized

    @model_validator(mode="after")
    def _validate_type_and_value(self) -> "Px4ParamPatchEntry":
        self.value = validate_parameter_value(self.value_type, self.value)
        if self.expected_current_value is not None:
            self.expected_current_value = validate_parameter_value(self.value_type, self.expected_current_value)
        return self


class Px4ParamPatchApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Px4ParamPatchSource = Px4ParamPatchSource.API
    verify_readback: bool = True
    entries: List[Px4ParamPatchEntry] = Field(..., min_length=1, max_length=4096)
    operation_id: Optional[str] = Field(None, min_length=1, max_length=128)
    expected_hw_id: Optional[str] = Field(None, min_length=1, max_length=128)

    @field_validator("entries")
    @classmethod
    def _unique_entries(cls, entries):
        return _validate_unique_entries(entries)


class Px4ParamPatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value_type: Px4ParamValueType
    requested_value: int | float | str
    applied: bool
    verified: bool
    actual_value: Optional[int | float | str] = None
    error: Optional[str] = None
    component_id: int = 1
    outcome: str = "unknown"
    write_acknowledged: bool = False
    readback_status: str = "not_attempted"
    error_phase: Optional[str] = None


class Px4ParamPatchApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Px4ParamPatchSource
    applied_count: int
    failed_count: int
    verified_count: int
    results: List[Px4ParamPatchResult]
    timestamp: int
    operation_id: Optional[str] = None


class Px4ParamDiffEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    component_id: int = Field(1, ge=1)
    value_type: Px4ParamValueType
    current_value: Optional[int | float | str] = None
    desired_value: Optional[int | float | str] = None
    changed: bool = False


class Px4ParamDiffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    desired_entries: List[Px4ParamPatchEntry] = Field(..., min_length=1, max_length=4096)
    include_unchanged: bool = False

    @field_validator("desired_entries")
    @classmethod
    def _unique_entries(cls, entries):
        return _validate_unique_entries(entries)


class Px4ParamDiffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    differences: List[Px4ParamDiffEntry]
    total_changed: int
    timestamp: int


class Px4ParamImportWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: Optional[int] = None
    message: str


class Px4ParamImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., min_length=1)


class Px4ParamImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    entries: List[Px4ParamPatchEntry]
    warnings: List[Px4ParamImportWarning] = Field(default_factory=list)
    skipped_count: int = 0
    total_entries: int = 0
    timestamp: int


class Px4ParamPatchJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hw_ids: List[str] = Field(..., min_length=1)
    source: Px4ParamPatchSource = Px4ParamPatchSource.API
    verify_readback: bool = True
    entries: List[Px4ParamPatchEntry] = Field(..., min_length=1, max_length=4096)

    @field_validator("entries")
    @classmethod
    def _unique_entries(cls, entries):
        return _validate_unique_entries(entries)

    @field_validator("hw_ids", mode="before")
    @classmethod
    def _normalize_hw_ids(cls, value: Any) -> List[str]:
        if not isinstance(value, list) or not value:
            raise ValueError("hw_ids must be a non-empty list")
        normalized = []
        for raw_value in value:
            normalized_value = str(raw_value).strip()
            if not normalized_value:
                raise ValueError("hw_ids must not contain blank entries")
            normalized.append(normalized_value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("hw_ids must not contain duplicate entries")
        return normalized


class Px4ParamPatchJobDroneResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hw_id: str
    applied: bool
    verified: bool
    result: Optional[Px4ParamPatchApplyResponse] = None
    error: Optional[str] = None


class Px4ParamPatchJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    source: Px4ParamPatchSource
    status: str
    verify_readback: bool
    total_targets: int
    completed_targets: int
    failed_targets: int
    results: List[Px4ParamPatchJobDroneResult]
    created_at: int
    completed_at: int
