"""Bounded typed execution diagnostics shared by callbacks and stored status.

These facts explain a terminal outcome; they never grant flight authority.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from src.action_result_protocol import decode_terminal_result
from src.control_release_protocol import ControlReleaseResult


class ActionResultEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    success: StrictBool
    code: str
    phase: str
    operator_message: str
    retryable: StrictBool
    evidence: dict[str, Any]
    final_vehicle_state: dict[str, Any] | None

    @model_validator(mode="after")
    def validate_terminal_contract(self):
        # Reuse the child-result decoder rather than inventing a looser copy
        # of its field, nesting and size policy at the HTTP boundary.
        decode_terminal_result(json.dumps(
            self.model_dump(), ensure_ascii=False, allow_nan=False, separators=(",", ":"),
        ).encode("utf-8"))
        return self


def normalize_execution_evidence(*, command_id, hw_id, action_result=None,
                                 control_release=None, teardown_forced=None):
    action = ActionResultEvidence.model_validate(action_result) if action_result is not None else None
    release = ControlReleaseResult.model_validate(control_release) if control_release is not None else None
    if release is not None and (release.command_id != command_id or release.hw_id != str(hw_id)):
        raise ValueError("Control release does not match the reporting command and aircraft")
    if teardown_forced is not None and type(teardown_forced) is not bool:
        raise ValueError("teardown_forced must be a boolean")
    return {
        "action_result": action.model_dump(mode="json") if action is not None else None,
        "control_release": release.model_dump(mode="json") if release is not None else None,
        "teardown_forced": teardown_forced,
    }
