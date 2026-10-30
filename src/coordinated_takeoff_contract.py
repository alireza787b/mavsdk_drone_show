"""Versioned, capability-authenticated messages for one Takeoff operation.

Readiness reports are not independent flight commands. The issuing node keeps
its own bounded armed-wait lease and repeats native state checks before release.
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator


class TakeoffStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    command_id: StrictStr = Field(min_length=1, max_length=200)
    hw_id: StrictStr = Field(min_length=1, max_length=64)
    sequence: StrictInt = Field(ge=0)
    state: Literal["armed_ready", "failed", "airborne"]
    armed: StrictBool
    landed_state: Literal["ON_GROUND", "TAKING_OFF", "IN_AIR", "UNKNOWN"]
    lease_remaining_ms: StrictInt = Field(ge=0)
    challenge: Optional[StrictStr] = Field(default=None, min_length=16, max_length=200)
    reason: Optional[StrictStr] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_state(self):
        if any(value != value.strip() for value in (self.command_id, self.hw_id)):
            raise ValueError("command and aircraft identities must be canonical")
        if self.state == "armed_ready" and (
            not self.armed or self.landed_state != "ON_GROUND" or self.lease_remaining_ms <= 0
        ):
            raise ValueError("armed_ready requires armed, on-ground evidence and a positive local lease")
        if self.state == "airborne" and (not self.armed or self.landed_state != "IN_AIR"):
            raise ValueError("airborne requires armed IN_AIR evidence")
        return self


class TakeoffStageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    decision: Literal["wait", "release", "abort"]
    release_at_unix_ms: Optional[StrictInt] = Field(default=None, ge=0)
    server_time_unix_ms: Optional[StrictInt] = Field(default=None, ge=0)
    challenge: Optional[StrictStr] = Field(default=None, min_length=16, max_length=200)
    reason: Optional[StrictStr] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_release(self):
        if self.decision == "release" and (
            self.release_at_unix_ms is None or self.server_time_unix_ms is None
        ):
            raise ValueError("release requires its shared time and current server clock")
        if self.decision != "release" and self.release_at_unix_ms is not None:
            raise ValueError("only release may carry takeoff timing authority")
        return self
