"""Canonical GCS-only review and durable receipt contracts for PX4 parameters."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.px4_param_models import (
    Px4ParamDiffEntry,
    Px4ParamPatchEntry,
    Px4ParamPatchApplyResponse,
    Px4ParamPatchSource,
)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hw_ids: list[str] = Field(..., min_length=1, max_length=100)
    excluded_hw_ids: list[str] = Field(default_factory=list, max_length=100)
    entries: list[Px4ParamPatchEntry] = Field(..., min_length=1, max_length=4096)
    source: Px4ParamPatchSource = Px4ParamPatchSource.MANUAL
    verify_readback: bool = True
    profile_id: str | None = Field(None, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    profile_hash: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def validate_review(self) -> "ReviewRequest":
        for field in ("hw_ids", "excluded_hw_ids"):
            values = [str(value).strip() for value in getattr(self, field)]
            if any(not value for value in values) or len(values) != len(set(values)):
                raise ValueError(f"{field} must contain unique, nonblank aircraft identities")
            setattr(self, field, values)
        if set(self.hw_ids) & set(self.excluded_hw_ids):
            raise ValueError("Included and excluded aircraft must not overlap")
        keys = [(entry.component_id, entry.name) for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("A review cannot contain duplicate parameter keys")
        if not self.verify_readback:
            raise ValueError("Reviewed GCS parameter jobs require readback verification")
        return self


class ReviewChange(Px4ParamDiffEntry):
    reboot_required: bool | None = None
    metadata_sources: list[str] = Field(default_factory=list)


class ReviewTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hw_id: str
    component_id: int = Field(..., ge=1)
    snapshot_id: str | None = None
    changes: list[ReviewChange] = Field(default_factory=list)
    unchanged_count: int = 0
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str
    review_hash: str
    runtime_binding: str
    hw_ids: list[str]
    excluded_hw_ids: list[str]
    source: Px4ParamPatchSource
    verify_readback: bool
    profile_id: str | None = None
    profile_hash: str | None = None
    targets: list[ReviewTarget]
    warnings: list[str] = Field(default_factory=list)
    blocked: bool
    created_at: int
    expires_at: int


class JobRequest(BaseModel):
    """A reviewed request, or the old body prepared by this same engine."""

    model_config = ConfigDict(extra="forbid")

    review_id: str | None = Field(None, max_length=160)
    review_hash: str | None = Field(None, max_length=64)
    idempotency_key: str | None = Field(None, min_length=8, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    hw_ids: list[str] | None = Field(None, min_length=1, max_length=100)
    entries: list[Px4ParamPatchEntry] | None = Field(None, min_length=1, max_length=4096)
    source: Px4ParamPatchSource = Px4ParamPatchSource.API
    verify_readback: bool = True

    @model_validator(mode="after")
    def validate_request(self) -> "JobRequest":
        if self.review_id is not None:
            if not self.review_hash or not self.idempotency_key:
                raise ValueError("Reviewed apply requires review_hash and idempotency_key")
            if self.hw_ids is not None or self.entries is not None:
                raise ValueError("Reviewed apply cannot replace its immutable targets or entries")
            if not self.verify_readback:
                raise ValueError("Reviewed apply cannot disable readback verification")
        elif self.hw_ids is None or self.entries is None:
            raise ValueError("Apply requires a review identity or the legacy targets and entries")
        return self


class JobTargetResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hw_id: str
    applied: bool = False
    verified: bool = False
    outcome: str = "pending"
    result: Px4ParamPatchApplyResponse | None = None
    error: str | None = None
    snapshot_refresh_error: str | None = None


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    review_id: str
    review_hash: str
    idempotency_key: str
    runtime_binding: str
    source: Px4ParamPatchSource
    status: str
    terminal: bool = False
    verify_readback: bool = True
    total_targets: int
    completed_targets: int = 0
    failed_targets: int = 0
    unknown_targets: int = 0
    results: list[JobTargetResult]
    created_at: int
    updated_at: int
    completed_at: int | None = None
