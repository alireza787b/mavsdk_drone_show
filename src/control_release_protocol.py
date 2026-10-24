"""Bounded, process-owner-bound control release; never a mission success result.

Unlike the terminal action protocol this channel has no stdout fallback. Receipt
time and the stop deadline are supervisor-local, not trusted child assertions.
"""
from __future__ import annotations

import json
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.bounded_fd_transport import write_bounded_payload

CONTROL_RELEASE_FD_ENV = "MDS_CONTROL_RELEASE_FD"
CONTROL_RELEASE_OWNER_ENV = "MDS_CONTROL_RELEASE_OWNER"
CONTROL_RELEASE_COMMAND_ENV = "MDS_CONTROL_RELEASE_COMMAND_ID"
MAX_CONTROL_RELEASE_BYTES = 4096


class ControlReleaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    kind: Literal["control_release"] = "control_release"
    command_id: str | None = Field(max_length=256)
    ownership_token: str = Field(min_length=1, max_length=64)
    hw_id: str = Field(min_length=1, max_length=64)
    producers_stopped: bool
    offboard_stop_completed: bool
    hold_accepted: bool
    observed_mode: str | None = Field(default=None, max_length=64)
    external_control_preserved: bool

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    @property
    def released(self) -> bool:
        # Acceptance releases this producer's ownership; it is NOT evidence
        # that telemetry observed Hold, nor that the replacement completed.
        return self.producers_stopped and (
            self.hold_accepted or self.external_control_preserved
        )


def decode_control_release(payload: bytes) -> ControlReleaseResult:
    if not payload or len(payload) > MAX_CONTROL_RELEASE_BYTES:
        raise ValueError("control release is empty or oversized")
    lines = payload.decode("utf-8", errors="strict").splitlines()
    if len(lines) != 1 or not payload.endswith(b"\n"):
        raise ValueError("control release requires exactly one complete line")
    document = json.loads(lines[0])
    if not isinstance(document, dict) or set(document) != set(ControlReleaseResult.model_fields):
        raise ValueError("control release fields do not match schema")
    return ControlReleaseResult.model_validate(document)


def emit_control_release(*, hw_id: str, producers_stopped: bool,
                         offboard_stop_completed: bool, hold_accepted: bool,
                         observed_mode: str | None,
                         external_control_preserved: bool) -> bool:
    """One nonblocking atomic pipe write, before network/helper teardown.

    An unavailable/full pipe fails closed without delaying aircraft recovery.
    Direct/manual execution has no process supervisor and emits no ack.
    """
    fd_text = os.environ.pop(CONTROL_RELEASE_FD_ENV, "")
    if not fd_text:
        return False
    release_fd = None
    try:
        release_fd = int(fd_text)
        if release_fd < 3:
            raise ValueError("reserved descriptor")
        result = ControlReleaseResult(
            command_id=os.environ.get(CONTROL_RELEASE_COMMAND_ENV) or None,
            ownership_token=os.environ.get(CONTROL_RELEASE_OWNER_ENV, ""),
            hw_id=str(hw_id), producers_stopped=producers_stopped,
            offboard_stop_completed=offboard_stop_completed,
            hold_accepted=hold_accepted, observed_mode=observed_mode,
            external_control_preserved=external_control_preserved,
        )
        payload = result.model_dump_json().encode("utf-8") + b"\n"
        if len(payload) > MAX_CONTROL_RELEASE_BYTES:
            raise ValueError("oversized control release")
        write_bounded_payload(release_fd, payload, limit=MAX_CONTROL_RELEASE_BYTES,
                              nonblocking_atomic=True)
        return True
    except (ValueError, OSError):
        return False
    finally:
        if release_fd is not None and release_fd >= 3:
            try:
                os.close(release_fd)
            except OSError:
                pass
