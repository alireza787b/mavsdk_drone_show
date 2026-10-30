"""Shared trust-bearing contract for current-operation launch readiness."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator


class TakeoffAdmissionEvidence(BaseModel):
    predicate: Literal["takeoff_ground_disarmed"]
    ready: StrictBool
    checks: Dict[str, StrictBool]

    @model_validator(mode="after")
    def _validate_checks(self) -> "TakeoffAdmissionEvidence":
        required = {"connection_live", "connection_continuous", "armed_fresh", "landed_state_fresh", "disarmed", "on_ground"}
        if set(self.checks) != required or self.ready != all(self.checks.values()):
            raise ValueError("takeoff admission must preserve all native ground checks")
        return self


class LaunchReadinessObservation(BaseModel):
    """Identity and freshness evidence sampled by the node.

    Health/check details remain extensible, while every field used to trust or
    expire the observation is strict and shared by both sides of the RPC.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: Literal[1]
    observation_id: StrictStr = Field(..., min_length=1, max_length=160)
    source: StrictStr = Field(..., min_length=1, max_length=120)
    observed_at_ms: StrictInt = Field(..., ge=0)
    valid_until_ms: StrictInt = Field(..., ge=0)
    require_global_position: StrictBool
    ready: StrictBool
    blockers: List[StrictStr] = Field(default_factory=list)
    checks: Dict[str, Any] = Field(default_factory=dict)
    battery: Dict[str, Any] = Field(default_factory=dict)
    mission_type: Optional[StrictInt] = None
    admission: Optional[TakeoffAdmissionEvidence] = None

    @field_validator("observation_id", "source")
    @classmethod
    def _require_canonical_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("trust-bearing text fields must not contain surrounding whitespace")
        return value

    @model_validator(mode="after")
    def _validate_ready_lease(self) -> "LaunchReadinessObservation":
        if self.ready and self.valid_until_ms <= self.observed_at_ms:
            raise ValueError("a ready observation requires a positive freshness interval")
        return self


class LiveArmabilityTrustEnvelope(BaseModel):
    """Fields the GCS must validate before using node readiness evidence."""

    model_config = ConfigDict(extra="allow")

    hw_id: StrictStr = Field(..., min_length=1, max_length=64)
    success: StrictBool
    ready: StrictBool
    summary: StrictStr = Field(..., min_length=1, max_length=500)
    observation: Optional[LaunchReadinessObservation] = None
    remaining_valid_ms: StrictInt = Field(..., ge=0)
    server_processing_ms: StrictInt = Field(..., ge=0)
    coordinated_takeoff_supported: StrictBool = False

    @field_validator("hw_id", "summary")
    @classmethod
    def _require_canonical_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("trust-bearing text fields must not contain surrounding whitespace")
        return value

    @model_validator(mode="after")
    def _validate_ready_evidence(self) -> "LiveArmabilityTrustEnvelope":
        if self.ready:
            if not self.success:
                raise ValueError("an unsuccessful probe cannot report ready")
            if self.observation is None or not self.observation.ready:
                raise ValueError("a ready response requires a ready typed observation")
            if self.remaining_valid_ms <= 0:
                raise ValueError("a ready response requires a positive remaining freshness lease")
        return self


__all__ = ["LaunchReadinessObservation", "LiveArmabilityTrustEnvelope"]
