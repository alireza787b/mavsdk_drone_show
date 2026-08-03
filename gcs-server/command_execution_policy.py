"""Canonical GCS policy for typed mission identity, admission, and timing."""

from __future__ import annotations

from enum import Enum
import math
import time
from typing import Any, Mapping

from src.enums import Mission
from src.command_execution_contract import (
    LAUNCH_ARMABILITY_MISSIONS,
    RECOVERY_MISSIONS,
    STRICT_SYNC_MISSIONS,
    mission_is_recovery,
    mission_requires_launch_armability_probe,
    mission_requires_strict_sync_dispatch,
    resolve_mission_type,
)


class CommandSubmissionAuthority(str, Enum):
    """Typed caller authority for admission rules that routes cannot bypass."""

    OPERATOR_COMMAND = "operator_command"
    FLEET_OPS_GIT_SYNC = "fleet_ops_git_sync"


class CommandSubmissionPolicyError(ValueError):
    """A canonical submission policy rejected a request before tracking."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class StrictSyncTimingError(ValueError):
    """A synchronized mission cannot reach every target before its trigger."""


def enforce_command_submission_policy(
    mission: Mission,
    command: Any,
    *,
    params: Any,
    authority: CommandSubmissionAuthority,
) -> None:
    """Apply intrinsic mission admission independent of the calling route."""

    if not isinstance(authority, CommandSubmissionAuthority):
        raise TypeError("command submission authority must be typed")

    if mission is Mission.UPDATE_CODE and authority is not CommandSubmissionAuthority.FLEET_OPS_GIT_SYNC:
        raise CommandSubmissionPolicyError(
            "UPDATE_CODE is restricted to Fleet Ops Git Sync dry-run and explicit apply.",
            status_code=400,
        )

    if mission is Mission.TEST:
        if command.trigger_time != 0:
            raise CommandSubmissionPolicyError(
                "Arm/Disarm Ground Test is immediate-only because its physical "
                "safety acknowledgement is valid only for the current conditions.",
                status_code=400,
            )
        try:
            command.ground_test_safety.validate_for_runtime(
                sim_mode=bool(getattr(params, "sim_mode", False))
            )
        except (AttributeError, ValueError) as exc:
            raise CommandSubmissionPolicyError(
                f"Arm/Disarm Ground Test safety check failed: {exc}. No command was dispatched.",
                status_code=409,
            ) from exc

    if mission_requires_strict_sync_dispatch(mission) and command.trigger_time > 0:
        try:
            resolve_strict_sync_trigger_time(
                mission,
                requested_trigger_time=command.trigger_time,
                params=params,
            )
        except StrictSyncTimingError as exc:
            raise CommandSubmissionPolicyError(str(exc), status_code=409) from exc


def extract_trigger_time_seconds(command_payload: Mapping[str, Any]) -> float | None:
    raw_trigger_time = command_payload.get("trigger_time")
    if raw_trigger_time in (None, 0):
        return None
    if type(raw_trigger_time) not in {int, float}:
        return None
    trigger_time = float(raw_trigger_time)
    return trigger_time if trigger_time > 0 else None


def get_sync_dispatch_deadline(
    mission: Mission | None,
    command_payload: Mapping[str, Any],
    *,
    params: Any,
) -> float | None:
    """Return the last wall-clock second at which strict fan-out may begin."""

    if not mission_requires_strict_sync_dispatch(mission):
        return None
    trigger_time = extract_trigger_time_seconds(command_payload)
    if trigger_time is None:
        return None
    trigger_sooner = max(0.0, float(getattr(params, "trigger_sooner_seconds", 0)))
    dispatch_guard = max(0.0, float(getattr(params, "COMMAND_SYNC_DISPATCH_GUARD_SEC", 1.0)))
    return trigger_time - trigger_sooner - dispatch_guard


def choose_post_preparation_trigger_time(*, params: Any, now: float | None = None) -> int:
    """Choose one safe fleet trigger after an all-required readiness barrier.

    The lead includes the bounded dispatch deadline, node warm-up offset, and
    sync guard. A small whole-second margin prevents rounding from consuming
    the guard before fan-out begins.
    """

    dispatch_budget = max(0.0, float(getattr(params, "GCS_FLEET_DISPATCH_DEADLINE_SEC", 15.0)))
    trigger_sooner = max(0.0, float(getattr(params, "trigger_sooner_seconds", 0.0)))
    dispatch_guard = max(0.0, float(getattr(params, "COMMAND_SYNC_DISPATCH_GUARD_SEC", 1.0)))
    return int(math.ceil(float(now if now is not None else time.time()) + dispatch_budget + trigger_sooner + dispatch_guard + 2.0))


def resolve_strict_sync_trigger_time(
    mission: Mission | None,
    *,
    requested_trigger_time: int,
    params: Any,
    now: float | None = None,
) -> int:
    """Resolve the one safe trigger used by every strict-sync target.

    ``0`` means "as soon as safely synchronized", not literal immediate
    execution. An explicit operator timestamp is preserved only while the
    complete bounded fan-out can still finish before the node warm-up window.
    """

    if not mission_requires_strict_sync_dispatch(mission):
        return requested_trigger_time
    if type(requested_trigger_time) is not int or requested_trigger_time < 0:
        raise StrictSyncTimingError(
            "Strict-sync trigger_time must be a non-negative Unix-second integer"
        )

    earliest_safe = choose_post_preparation_trigger_time(params=params, now=now)
    if requested_trigger_time == 0:
        return earliest_safe
    if requested_trigger_time < earliest_safe:
        raise StrictSyncTimingError(
            "The synchronized trigger is too soon for bounded fleet dispatch. "
            f"Earliest safe trigger_time is {earliest_safe}; no drone was commanded."
        )
    return requested_trigger_time
