"""
Mission-aware tracker timeout policy for command lifecycle monitoring.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from src.enums import Mission
from src.flight_timeout_utils import calculate_land_disarm_timeout, calculate_rtl_completion_timeout
from src.params import Params


def _coerce_mission(value: Any) -> Mission | None:
    if isinstance(value, Mission):
        return value

    enum_value = getattr(value, "value", None)
    if enum_value is not None and enum_value is not value:
        coerced = _coerce_mission(enum_value)
        if coerced is not None:
            return coerced

    enum_name = getattr(value, "name", None)
    if isinstance(enum_name, str):
        normalized_name = enum_name.strip().upper().replace("-", "_").replace(" ", "_")
        if normalized_name:
            mission = Mission.__members__.get(normalized_name)
            if mission is not None:
                return mission

    try:
        return Mission(int(value))
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _target_drone_file_names(target_drone_ids: Optional[Iterable[Any]]) -> set[str] | None:
    if not target_drone_ids:
        return None

    names: set[str] = set()
    for drone_id in target_drone_ids:
        try:
            names.add(f"Drone {int(str(drone_id).strip())}.csv")
        except (TypeError, ValueError):
            continue

    return names or None


def _extract_future_trigger_delay_ms(command_data: Optional[Dict[str, Any]]) -> int:
    if not command_data:
        return 0

    trigger_time = command_data.get("trigger_time", command_data.get("triggerTime"))
    if trigger_time in (None, "", 0, "0"):
        return 0

    try:
        numeric = int(str(trigger_time).strip())
    except (TypeError, ValueError):
        return 0

    if numeric <= 0:
        return 0

    trigger_ms = numeric if numeric >= 10_000_000_000 else numeric * 1000
    now_ms = int(time.time() * 1000)
    return max(0, trigger_ms - now_ms)


def _read_show_duration_ms(
    skybrush_dir: Path,
    *,
    target_drone_ids: Optional[Iterable[Any]] = None,
) -> Optional[int]:
    if not skybrush_dir.exists():
        return None

    allowed_names = _target_drone_file_names(target_drone_ids)
    max_duration_ms = 0.0
    for csv_path in sorted(skybrush_dir.glob("Drone *.csv")):
        if allowed_names is not None and csv_path.name not in allowed_names:
            continue
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                next(handle, None)
                rows = [line.strip() for line in handle if line.strip()]
        except OSError:
            continue

        if not rows:
            continue

        parts = rows[-1].split(",")
        if not parts:
            continue

        try:
            duration_ms = float(parts[0])
        except (TypeError, ValueError):
            continue

        max_duration_ms = max(max_duration_ms, duration_ms)

    return int(max_duration_ms) if max_duration_ms > 0 else None


def _read_custom_show_duration_ms(shapes_dir: Path) -> Optional[int]:
    csv_path = shapes_dir / "active.csv"
    if not csv_path.exists():
        return None

    max_duration_s = 0.0
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not any((value or "").strip() for value in row.values()):
                    continue
                try:
                    max_duration_s = max(max_duration_s, float(row.get("t", 0.0)))
                except (TypeError, ValueError):
                    continue
    except OSError:
        return None

    return int(max_duration_s * 1000) if max_duration_s > 0 else None


def _read_swarm_processed_duration_s(
    processed_dir: Path,
    *,
    target_drone_ids: Optional[Iterable[Any]] = None,
) -> Optional[float]:
    if not processed_dir.exists():
        return None

    allowed_names = _target_drone_file_names(target_drone_ids)
    max_duration_s = 0.0
    for csv_path in sorted(processed_dir.glob("Drone *.csv")):
        if allowed_names is not None and csv_path.name not in allowed_names:
            continue
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    try:
                        max_duration_s = max(max_duration_s, float(row.get("t", 0.0)))
                    except (TypeError, ValueError):
                        continue
        except OSError:
            continue

    return max_duration_s if max_duration_s > 0 else None


def estimate_command_tracking_timeout_ms(
    mission: Any,
    *,
    command_data: Optional[Dict[str, Any]] = None,
    target_drone_ids: Optional[Iterable[Any]] = None,
    max_relative_altitude_m: Optional[float] = None,
    skybrush_dir: Optional[str | Path] = None,
    processed_dir: Optional[str | Path] = None,
    shapes_dir: Optional[str | Path] = None,
    params=Params,
) -> int:
    """
    Estimate a realistic command tracking timeout for the given mission.

    The tracker should stay alive for the whole real operator-visible lifecycle,
    not just for ACK collection or for the first mode transition.
    """
    mission_enum = _coerce_mission(mission)
    default_ms = _safe_int(getattr(params, "COMMAND_TRACKING_DEFAULT_TIMEOUT_MS", 60000), 60000)
    action_buffer_sec = max(0, _safe_int(getattr(params, "COMMAND_TRACKING_ACTION_BUFFER_SEC", 30), 30))
    mission_buffer_sec = max(0, _safe_int(getattr(params, "COMMAND_TRACKING_MISSION_BUFFER_SEC", 120), 120))
    trigger_delay_ms = _extract_future_trigger_delay_ms(command_data)

    if mission_enum == Mission.TAKE_OFF:
        preflight_sec = _safe_int(getattr(params, "TAKEOFF_PREFLIGHT_TIMEOUT_SEC", 30), 30)
        climb_sec = _safe_int(getattr(params, "TAKEOFF_ALTITUDE_CONFIRM_TIMEOUT_SEC", 60), 60)
        return max(default_ms, trigger_delay_ms + ((preflight_sec + climb_sec + action_buffer_sec) * 1000))

    if mission_enum == Mission.LAND:
        return max(
            default_ms,
            trigger_delay_ms
            + ((calculate_land_disarm_timeout(max_relative_altitude_m, params=params) + action_buffer_sec) * 1000),
        )

    if mission_enum == Mission.RETURN_RTL:
        return max(
            default_ms,
            trigger_delay_ms + (calculate_rtl_completion_timeout(max_relative_altitude_m, params=params) * 1000),
        )

    if mission_enum == Mission.HOVER_TEST:
        hover_timeout_sec = _safe_int(getattr(params, "COMMAND_TRACKING_HOVER_TEST_TIMEOUT_SEC", 180), 180)
        return max(default_ms, trigger_delay_ms + (hover_timeout_sec * 1000))

    if mission_enum == Mission.DRONE_SHOW_FROM_CSV:
        show_duration_ms = (
            _read_show_duration_ms(Path(skybrush_dir), target_drone_ids=target_drone_ids)
            if skybrush_dir
            else None
        )
        if show_duration_ms is not None:
            return max(default_ms, trigger_delay_ms + show_duration_ms + (mission_buffer_sec * 1000))

    if mission_enum == Mission.CUSTOM_CSV_DRONE_SHOW:
        custom_duration_ms = _read_custom_show_duration_ms(Path(shapes_dir)) if shapes_dir else None
        if custom_duration_ms is not None:
            return max(default_ms, trigger_delay_ms + custom_duration_ms + (mission_buffer_sec * 1000))

    if mission_enum == Mission.SWARM_TRAJECTORY:
        processed_duration_s = (
            _read_swarm_processed_duration_s(Path(processed_dir), target_drone_ids=target_drone_ids)
            if processed_dir
            else None
        )
        if processed_duration_s is not None:
            multiplier = max(1.0, float(getattr(params, "SWARM_TRAJECTORY_TIMEOUT_MULTIPLIER", 1.2)))
            total_duration_s = (processed_duration_s * multiplier) + mission_buffer_sec
            end_behavior = str(
                (command_data or {}).get("return_behavior")
                or getattr(params, "SWARM_TRAJECTORY_END_BEHAVIOR", "return_home")
            ).lower()
            if end_behavior == "return_home":
                total_duration_s += calculate_rtl_completion_timeout(None, params=params)
            elif end_behavior == "land_current":
                total_duration_s += calculate_land_disarm_timeout(None, params=params)
            return max(default_ms, trigger_delay_ms + int(total_duration_s * 1000))

    if mission_enum == Mission.QUICKSCOUT:
        quickscout_timeout_sec = _safe_int(
            getattr(params, "COMMAND_TRACKING_QUICKSCOUT_TIMEOUT_SEC", 900),
            900,
        )
        return max(default_ms, trigger_delay_ms + (quickscout_timeout_sec * 1000))

    return max(default_ms, trigger_delay_ms + default_ms)
