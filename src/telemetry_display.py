"""Operator-facing telemetry presentation helpers.

Raw MAVLink streams expose altitude in several frames.  This module keeps the
selection policy explicit so API and dashboard consumers do not infer altitude
source from map readiness or from one legacy altitude field.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Optional

from functions.data_utils import safe_int

ALTITUDE_STALE_AFTER_MS = 3000


def _finite_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def build_altitude_report(
    *,
    position: Optional[Dict[str, Any]],
    local_position_ned: Optional[Dict[str, Any]],
    gps_fix_type: Any = 0,
    global_position_timestamp_ms: Any = 0,
    relative_altitude_m: Any = None,
    baro_altitude_m: Any = None,
    baro_timestamp_ms: Any = 0,
    now_ms: Any = None,
) -> Dict[str, Any]:
    """Build a compact source-aware altitude report.

    Selection order:
    1. ``relative_home`` from GLOBAL_POSITION_INT.relative_alt.
    2. ``local_ned`` from LOCAL_POSITION_NED.z converted to up-positive metres.
    3. ``baro`` from SCALED_PRESSURE.press_abs when available.
    4. ``absolute_msl`` from GLOBAL_POSITION_INT.alt.

    The legacy ``position_alt`` field remains GLOBAL_POSITION_INT.alt in metres.
    """

    position = position or {}
    local_position_ned = local_position_ned or {}

    global_position_timestamp_ms = safe_int(global_position_timestamp_ms)
    baro_timestamp_ms = safe_int(baro_timestamp_ms)
    now_ms = safe_int(now_ms) or int(time.time() * 1000)
    local_time_boot_ms = safe_int(local_position_ned.get("time_boot_ms"))
    local_timestamp_ms = safe_int(local_position_ned.get("timestamp_ms"))
    msl_m = _finite_float(position.get("alt"))
    relative_home_m = _finite_float(relative_altitude_m)
    local_down_m = _finite_float(local_position_ned.get("z"))
    local_up_m = -local_down_m if local_time_boot_ms > 0 and local_down_m is not None else None
    baro_m = _finite_float(baro_altitude_m)

    has_global_position = global_position_timestamp_ms > 0
    sources = {
        "relative_home": _altitude_source_entry(
            value_m=relative_home_m,
            label="REL",
            frame="relative_home",
            timestamp_ms=global_position_timestamp_ms,
            now_ms=now_ms,
            requires_global_position=True,
            valid=has_global_position and relative_home_m is not None,
        ),
        "local_ned": _altitude_source_entry(
            value_m=local_up_m,
            label="LCL",
            frame="local_ned",
            timestamp_ms=local_timestamp_ms,
            time_boot_ms=local_time_boot_ms,
            now_ms=now_ms,
            requires_global_position=False,
            valid=local_up_m is not None,
        ),
        "baro": _altitude_source_entry(
            value_m=baro_m,
            label="BARO",
            frame="baro",
            timestamp_ms=baro_timestamp_ms,
            now_ms=now_ms,
            requires_global_position=False,
            valid=baro_m is not None,
        ),
        "absolute_msl": _altitude_source_entry(
            value_m=msl_m,
            label="MSL",
            frame="absolute_msl",
            timestamp_ms=global_position_timestamp_ms,
            now_ms=now_ms,
            requires_global_position=True,
            valid=has_global_position and msl_m is not None,
        ),
    }

    selected_source = "unavailable"
    selected = None
    for candidate in ("relative_home", "local_ned", "baro", "absolute_msl"):
        source_entry = sources[candidate]
        if source_entry["valid"] and not source_entry["stale"]:
            selected_source = candidate
            selected = source_entry
            break
    if selected is None:
        for candidate in ("relative_home", "local_ned", "baro", "absolute_msl"):
            source_entry = sources[candidate]
            if source_entry["valid"]:
                selected_source = candidate
                selected = source_entry
                break

    display_m = selected["value_m"] if selected else None
    frame = selected["frame"] if selected else "unavailable"
    label = selected["label"] if selected else "ALT"
    requires_global_position = bool(selected["requires_global_position"]) if selected else False

    return {
        "available": display_m is not None,
        "display_m": display_m,
        "source": selected_source,
        "frame": frame,
        "label": label,
        "requires_global_position": requires_global_position,
        "valid": bool(selected and selected["valid"]),
        "stale": bool(selected and selected["stale"]),
        "freshness_ms": selected["age_ms"] if selected else None,
        "sources": sources,
        "msl_m": sources["absolute_msl"]["value_m"] if sources["absolute_msl"]["valid"] else None,
        "relative_home_m": sources["relative_home"]["value_m"] if sources["relative_home"]["valid"] else None,
        "local_up_m": sources["local_ned"]["value_m"] if sources["local_ned"]["valid"] else None,
        "baro_m": sources["baro"]["value_m"] if sources["baro"]["valid"] else None,
        "global_position_available": has_global_position,
        "local_position_available": sources["local_ned"]["valid"],
        "gps_fix_type": safe_int(gps_fix_type),
    }


def _altitude_source_entry(
    *,
    value_m: Optional[float],
    label: str,
    frame: str,
    timestamp_ms: int = 0,
    time_boot_ms: int = 0,
    now_ms: int,
    requires_global_position: bool,
    valid: bool,
) -> Dict[str, Any]:
    age_ms = None
    fresh = None
    stale = False
    if valid and timestamp_ms > 0:
        age_ms = max(0, now_ms - timestamp_ms)
        fresh = age_ms <= ALTITUDE_STALE_AFTER_MS
        stale = not fresh
    elif valid:
        fresh = False
        stale = True
    return {
        "valid": bool(valid),
        "value_m": value_m if valid else None,
        "label": label,
        "frame": frame,
        "requires_global_position": requires_global_position,
        "timestamp_ms": timestamp_ms or None,
        "time_boot_ms": time_boot_ms or None,
        "age_ms": age_ms,
        "fresh": fresh,
        "stale": stale,
    }


def build_gps_report(
    *,
    fix_type: Any = 0,
    satellites_visible: Any = 0,
    hdop: Any = None,
    vdop: Any = None,
) -> Dict[str, Any]:
    """Normalize GPS quality values while hiding MAVLink sentinel values."""

    fix_type_int = safe_int(fix_type)
    sats_raw = safe_int(satellites_visible)
    hdop_float = _finite_float(hdop)
    vdop_float = _finite_float(vdop)

    sats = None if sats_raw >= 255 else max(0, sats_raw)
    hdop_value = None if hdop_float is None or hdop_float <= 0 or hdop_float >= 655.35 else hdop_float
    vdop_value = None if vdop_float is None or vdop_float <= 0 or vdop_float >= 655.35 else vdop_float

    has_fix = fix_type_int >= 2
    has_3d_fix = fix_type_int >= 3
    quality_known = hdop_value is not None or vdop_value is not None or sats is not None

    if fix_type_int <= 0:
        label = "No GPS"
    elif fix_type_int == 1:
        label = "No Fix"
    elif fix_type_int == 2:
        label = "2D Fix"
    elif fix_type_int == 3:
        label = "3D Fix"
    elif fix_type_int == 4:
        label = "DGPS"
    elif fix_type_int == 5:
        label = "RTK Float"
    elif fix_type_int >= 6:
        label = "RTK Fixed"
    else:
        label = "Unknown"

    return {
        "available": has_fix,
        "has_3d_fix": has_3d_fix,
        "fix_type": fix_type_int,
        "fix_label": label,
        "satellites_visible": sats,
        "hdop": hdop_value,
        "vdop": vdop_value,
        "quality_known": quality_known,
    }
