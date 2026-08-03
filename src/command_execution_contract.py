"""Shared mission execution classes used at both GCS and node boundaries.

These sets classify wire-level mission semantics.  Operator authorization and
timing calculations remain GCS policy, while transport and node admission use
the same mission classes instead of maintaining parallel lists.
"""

from __future__ import annotations

from typing import Any

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


__all__ = [
    "LAUNCH_ARMABILITY_MISSIONS",
    "RECOVERY_MISSIONS",
    "STRICT_SYNC_MISSIONS",
    "mission_is_recovery",
    "mission_requires_launch_armability_probe",
    "mission_requires_strict_sync_dispatch",
    "resolve_mission_type",
]
