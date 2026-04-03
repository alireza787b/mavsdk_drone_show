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

