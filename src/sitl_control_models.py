"""Shared SITL control models for the GCS API, dashboard, and future MCP tools."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SitlControlDockerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    socket_path: str
    socket_exists: bool
    daemon_reachable: bool
    server_version: Optional[str] = None
    api_version: Optional[str] = None
    error: Optional[str] = None


class SitlControlFeatureFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_summary: bool = True
    image_inventory: bool = True
    instance_inventory: bool = True
    instance_logs: bool = True
    lifecycle_mutations: bool = True
    operations: bool = True
    browser_terminal: bool = False


class SitlControlPolicyDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_image: str
    default_network_name: str
    default_git_sync: bool = True
    default_requirements_sync: bool = True
    default_log_tail_lines: int = Field(200, ge=1)


class SitlControlPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subsystem: str = "sitl_control"
    sim_mode: bool
    read_only: bool = False
    docs_path: str
    features: SitlControlFeatureFlags
    defaults: SitlControlPolicyDefaults
    docker: SitlControlDockerState
    timestamp: int


class SitlControlHostSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hostname: str
    platform: str
    platform_release: str
    architecture: str
    python_version: str
    cpu_count_logical: int = Field(..., ge=0)
    memory_total_bytes: int = Field(..., ge=0)
    memory_available_bytes: int = Field(..., ge=0)
    disk_path: str
    disk_total_bytes: int = Field(..., ge=0)
    disk_free_bytes: int = Field(..., ge=0)
    load_avg_1m: Optional[float] = None
    load_avg_5m: Optional[float] = None
    load_avg_15m: Optional[float] = None
    docker: SitlControlDockerState


class SitlControlHostResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: SitlControlHostSummary
    timestamp: int


class SitlControlImageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: str
    primary_tag: Optional[str] = None
    repo_tags: List[str] = Field(default_factory=list)
    size_bytes: int = Field(..., ge=0)
    created_at: Optional[str] = None
    repo: Optional[str] = None
    version_tag: Optional[str] = None
    branch: Optional[str] = None
    commit: Optional[str] = None
    prepared_from: Optional[str] = None
    in_use_by_instances: int = Field(0, ge=0)
    labels: Dict[str, str] = Field(default_factory=dict)


class SitlControlImageListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    images: List[SitlControlImageSummary]
    total_images: int = Field(..., ge=0)
    docker: SitlControlDockerState
    timestamp: int


class SitlControlInstanceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_id: str
    name: str
    image_ref: Optional[str] = None
    image_id: Optional[str] = None
    status: str
    state: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    restart_policy: Optional[str] = None
    health_status: Optional[str] = None
    hw_id: Optional[str] = None
    pos_id_hint: Optional[int] = None
    git_repo_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_sync_enabled: Optional[bool] = None
    requirements_sync_enabled: Optional[bool] = None
    ip_addresses: Dict[str, str] = Field(default_factory=dict)


class SitlControlInstanceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instances: List[SitlControlInstanceSummary]
    total_instances: int = Field(..., ge=0)
    docker: SitlControlDockerState
    timestamp: int


class SitlControlInstanceLogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_name: str
    tail_lines: int = Field(..., ge=1)
    lines: List[str] = Field(default_factory=list)
    source: Optional[str] = Field(None, description="Resolved log source such as docker or startup_sitl.log")
    docker: SitlControlDockerState
    timestamp: int


class SitlControlReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_count: int = Field(..., ge=1, le=50)
    image_ref: Optional[str] = None
    subnet: Optional[str] = None
    docker_network_name: Optional[str] = None
    start_id: int = Field(1, ge=1, le=999)
    start_ip: int = Field(2, ge=2, le=254)
    git_sync_enabled: bool = True
    requirements_sync_enabled: bool = True

    @field_validator("image_ref", "subnet", "docker_network_name", mode="before")
    @classmethod
    def _normalize_optional_strings(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class SitlControlOperationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    operation_type: str
    status: str
    summary: str
    detail: Optional[str] = None
    affected_instances: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    log_lines: List[str] = Field(default_factory=list)
    created_at: int
    updated_at: int
    completed_at: Optional[int] = None


class SitlControlOperationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: List[SitlControlOperationResponse] = Field(default_factory=list)
    total_operations: int = Field(..., ge=0)
    active_operations: int = Field(..., ge=0)
    timestamp: int
