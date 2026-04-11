"""Typed API schemas for the logging subsystem."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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


class OnboardUlogPolicyResponse(BaseModel):
    hw_id: str
    pos_id: int | None = None
    policy: OnboardUlogPolicy
    timestamp: int


class OnboardUlogEntry(BaseModel):
    id: int
    date_utc: str | None = None
    size_bytes: int


class OnboardUlogListResponse(BaseModel):
    hw_id: str
    pos_id: int | None = None
    count: int
    files: list[OnboardUlogEntry]
    policy: OnboardUlogPolicy
    timestamp: int


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
