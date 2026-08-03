"""Shared command execution classes used at GCS and node boundaries.

Mission sets classify dispatch and admission semantics.  ``DroneExecutionOutcome``
classifies one node's terminal execution report without making operator-facing
error text part of lifecycle authority.
"""

from __future__ import annotations

from enum import Enum
from collections.abc import Mapping
from typing import Any, Optional

from src.enums import Mission, resolve_executable_mission


STRICT_SYNC_MISSIONS = frozenset(
    {
        Mission.DRONE_SHOW_FROM_CSV,
        Mission.CUSTOM_CSV_DRONE_SHOW,
        Mission.SWARM_TRAJECTORY,
        Mission.HOVER_TEST,
        Mission.QUICKSCOUT,
    }
)

RECOVERY_MISSIONS = frozenset(
    {
        Mission.NONE,
        Mission.LAND,
        Mission.RETURN_RTL,
        Mission.HOLD,
        Mission.KILL_TERMINATE,
    }
)

LAUNCH_ARMABILITY_MISSIONS = frozenset(
    {
        Mission.TAKE_OFF,
        Mission.DRONE_SHOW_FROM_CSV,
        Mission.CUSTOM_CSV_DRONE_SHOW,
        Mission.SWARM_TRAJECTORY,
        Mission.QUICKSCOUT,
        Mission.HOVER_TEST,
    }
)


class DroneExecutionOutcome(str, Enum):
    """Terminal outcome reported by one drone for one tracked command."""

    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


_LEGACY_SUPERSEDED_COMPLETION_PREFIX = "superseded by a newer command before completion"
_LEGACY_SUPERSEDED_PENDING_PREFIX = "superseded by a newer command ("
_LEGACY_SUPERSEDED_PENDING_SUFFIX = ") before execution started"
_SUPERSEDED_OPERATOR_PREFIX = "Superseded by a newer command before completion"


def resolve_mission_type(value: Any) -> Mission | None:
    """Resolve only an executable numeric value or canonical mission name."""

    return resolve_executable_mission(value)


def mission_requires_launch_armability_probe(mission: Mission | None) -> bool:
    """Return whether command admission requires command-bound preparation."""

    return resolve_mission_type(mission) in LAUNCH_ARMABILITY_MISSIONS


def mission_requires_strict_sync_dispatch(mission: Mission | None) -> bool:
    """Return whether every target must receive one shared future trigger."""

    return resolve_mission_type(mission) in STRICT_SYNC_MISSIONS


def mission_is_recovery(mission: Mission | None) -> bool:
    """Return whether transport must use capacity reserved for recovery."""

    return resolve_mission_type(mission) in RECOVERY_MISSIONS


def normalize_execution_outcome(
    outcome: DroneExecutionOutcome | str | None,
) -> Optional[DroneExecutionOutcome]:
    """Return the canonical typed outcome, preserving omitted legacy reports."""

    if outcome is None:
        return None
    return DroneExecutionOutcome(outcome)


def validate_execution_outcome(
    *,
    success: bool,
    outcome: DroneExecutionOutcome | str | None,
) -> Optional[DroneExecutionOutcome]:
    """Reject contradictory success and typed-outcome combinations."""

    normalized = normalize_execution_outcome(outcome)
    if normalized is None:
        return None
    if success != (normalized == DroneExecutionOutcome.COMPLETED):
        raise ValueError("success must be true exactly when outcome is completed")
    return normalized


def format_superseded_execution_error(
    detail: str | None = None,
    *,
    max_length: int = 500,
) -> str:
    """Build an operator message that old GCS releases can classify safely."""

    normalized_detail = " ".join(str(detail or "").split())
    if is_legacy_superseded_execution_error(normalized_detail):
        message = normalized_detail
    elif normalized_detail:
        message = f"{_SUPERSEDED_OPERATOR_PREFIX}. {normalized_detail}"
    else:
        message = _SUPERSEDED_OPERATOR_PREFIX
    return message[:max_length]


def format_pending_superseded_execution_error(
    replacement_mission: str,
    *,
    max_length: int = 500,
) -> str:
    """Build the legacy-compatible message for work replaced before start."""

    mission = " ".join(str(replacement_mission).split()).replace(")", "")
    return (
        f"Superseded by a newer command ({mission}) before execution started"
    )[:max_length]


def is_legacy_superseded_execution_error(message: str | None) -> bool:
    """Recognize reports from nodes that predate the typed outcome field."""

    normalized = " ".join(str(message or "").split()).lower()
    if normalized == _LEGACY_SUPERSEDED_COMPLETION_PREFIX or normalized.startswith(
        f"{_LEGACY_SUPERSEDED_COMPLETION_PREFIX}. "
    ):
        return True
    if not normalized.startswith(_LEGACY_SUPERSEDED_PENDING_PREFIX):
        return False
    pending_tail = normalized[len(_LEGACY_SUPERSEDED_PENDING_PREFIX) :]
    suffix_index = pending_tail.find(_LEGACY_SUPERSEDED_PENDING_SUFFIX)
    if suffix_index <= 0:
        return False
    remainder = pending_tail[suffix_index + len(_LEGACY_SUPERSEDED_PENDING_SUFFIX) :]
    return remainder == "" or remainder.startswith(". ")


def is_legacy_schema_outcome_rejection(
    *,
    status_code: int,
    response_payload: Any,
) -> bool:
    """Identify only an old strict schema rejecting the optional outcome field."""

    if status_code != 422 or not isinstance(response_payload, Mapping):
        return False
    details = response_payload.get("detail")
    if not isinstance(details, list):
        return False
    for detail in details:
        if not isinstance(detail, Mapping):
            continue
        location = detail.get("loc")
        if not isinstance(location, (list, tuple)):
            continue
        if list(location) != ["body", "outcome"]:
            continue
        if detail.get("type") in {"extra_forbidden", "value_error.extra"}:
            return True
    return False


__all__ = [
    "DroneExecutionOutcome",
    "LAUNCH_ARMABILITY_MISSIONS",
    "RECOVERY_MISSIONS",
    "STRICT_SYNC_MISSIONS",
    "format_pending_superseded_execution_error",
    "format_superseded_execution_error",
    "is_legacy_superseded_execution_error",
    "is_legacy_schema_outcome_rejection",
    "mission_is_recovery",
    "mission_requires_launch_armability_probe",
    "mission_requires_strict_sync_dispatch",
    "normalize_execution_outcome",
    "resolve_mission_type",
    "validate_execution_outcome",
]
