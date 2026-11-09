"""Preparation lead for executors that retain a separate synchronized start gate.

Only the three missions launched through drone_show.py may start their Python /
MAVSDK preparation earlier. Other handlers do not all pass a future timestamp
to their children; increasing their lead could execute an action early.
"""

from __future__ import annotations

import math
from typing import Any

from src.command_execution_contract import resolve_mission_type
from src.enums import Mission


DEFAULT_SYNCHRONIZED_SHOW_PREPARATION_SEC = 10.0
SYNCHRONIZED_SHOW_EXECUTOR_MISSIONS = frozenset({
    Mission.DRONE_SHOW_FROM_CSV, Mission.CUSTOM_CSV_DRONE_SHOW, Mission.HOVER_TEST,
})


def resolve_show_preparation_seconds(value: Any = None) -> float:
    """Normalize the configured preparation budget without accepting NaN/Mock/bool."""
    if type(value) not in {int, float, str}:
        return DEFAULT_SYNCHRONIZED_SHOW_PREPARATION_SEC
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SYNCHRONIZED_SHOW_PREPARATION_SEC
    return parsed if math.isfinite(parsed) and parsed > 0 else DEFAULT_SYNCHRONIZED_SHOW_PREPARATION_SEC


def mission_uses_synchronized_show_executor(mission: Any) -> bool:
    return resolve_mission_type(mission) in SYNCHRONIZED_SHOW_EXECUTOR_MISSIONS


def _nonnegative_setting(params: Any, name: str, default: float) -> float:
    value = getattr(params, name, default)
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        return default
    return max(0.0, float(value))


def mission_preparation_lead_seconds(mission: Any, *, params: Any) -> float:
    """One GCS/node preparation budget; never reduce the legacy lead."""
    legacy = _nonnegative_setting(params, 'trigger_sooner_seconds', 0.0)
    if not mission_uses_synchronized_show_executor(mission):
        return legacy
    configured = resolve_show_preparation_seconds(
        getattr(params, 'SYNCHRONIZED_SHOW_PREPARATION_SEC', None)
    )
    return max(legacy, configured)


def mission_commit_lead_seconds(mission: Any, *, params: Any) -> float:
    """Minimum remaining node preparation plus the existing dispatch guard."""
    return mission_preparation_lead_seconds(mission, params=params) + _nonnegative_setting(
        params, 'COMMAND_SYNC_DISPATCH_GUARD_SEC', 1.0,
    )
