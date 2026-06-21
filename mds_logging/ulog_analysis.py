"""Bounded local PX4 ULog summary helpers.

This module converts a local ``.ulg`` file into derived operator metrics. It
never returns raw topic arrays, raw log message text, or file bytes.
"""

from __future__ import annotations

import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ULOG_SUMMARY_TOPIC_FILTER: tuple[str, ...] = (
    "battery_status",
    "estimator_status",
    "sensor_gps",
    "trajectory_setpoint",
    "vehicle_command",
    "vehicle_command_ack",
    "vehicle_gps_position",
    "vehicle_land_detected",
    "vehicle_local_position",
    "vehicle_status",
)
DEFAULT_ULOG_SUMMARY_MAX_BYTES = 64 * 1024 * 1024


def summarize_ulog_file(
    path: str | Path,
    *,
    source_metadata: Mapping[str, Any] | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Return a safe, bounded ULog summary for operator evidence.

    The summary is suitable for GCS-local API/Simurgh evidence. It deliberately
    excludes raw coordinates, raw logged message text, raw topic arrays, and the
    binary ULog content.
    """

    log_path = Path(path)
    metadata = dict(source_metadata or {})
    max_allowed = _safe_int(max_bytes, _env_int("MDS_ULOG_SUMMARY_MAX_BYTES", DEFAULT_ULOG_SUMMARY_MAX_BYTES))
    file_size = log_path.stat().st_size if log_path.exists() else 0
    base = {
        "source": {
            "source_kind": metadata.get("source_kind") or "ulog_file",
            "log_id": metadata.get("log_id"),
            "date_utc": metadata.get("date_utc"),
            "size_bytes": int(metadata.get("size_bytes") or file_size or 0),
        },
        "parser": {
            "name": "pyulog",
            "available": False,
            "status": "not_started",
            "error": None,
            "topics_requested": list(ULOG_SUMMARY_TOPIC_FILTER),
        },
        "parsed": False,
    }

    if not log_path.exists():
        base["parser"].update({"status": "failed", "error": "ULog file not found"})
        return base
    if file_size > max_allowed:
        base["parser"].update(
            {
                "status": "skipped",
                "error": f"ULog file is larger than MDS_ULOG_SUMMARY_MAX_BYTES ({max_allowed} bytes)",
            }
        )
        return base

    try:
        from pyulog import ULog  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on runtime packaging
        base["parser"].update({"status": "unavailable", "error": f"pyulog unavailable: {exc}"})
        return base

    try:
        ulog = ULog(str(log_path), list(ULOG_SUMMARY_TOPIC_FILTER))
    except Exception as exc:
        base["parser"].update({"available": True, "status": "failed", "error": _safe_error(exc)})
        return base

    datasets = {dataset.name: dataset for dataset in getattr(ulog, "data_list", [])}
    topic_sample_counts = {
        name: _dataset_sample_count(dataset)
        for name, dataset in sorted(datasets.items())
    }
    summary: dict[str, Any] = {
        **base,
        "parsed": True,
        "parser": {
            **base["parser"],
            "available": True,
            "status": "ok",
            "error": None,
            "topics_present": sorted(topic_sample_counts),
            "topic_sample_counts": topic_sample_counts,
        },
        "duration_sec": _duration_seconds(ulog),
        "dropouts": _summarize_dropouts(getattr(ulog, "dropouts", []) or []),
        "logged_messages": _summarize_logged_messages(getattr(ulog, "logged_messages", []) or []),
        "system": _summarize_system_info(getattr(ulog, "msg_info_dict", {}) or {}),
    }

    local_position = _summarize_local_position(datasets.get("vehicle_local_position"))
    if local_position:
        summary["local_position"] = local_position

    setpoint = _summarize_setpoint(datasets.get("trajectory_setpoint"))
    if setpoint:
        summary["trajectory_setpoint"] = setpoint

    battery = _summarize_battery(datasets.get("battery_status"))
    if battery:
        summary["battery"] = battery

    vehicle_status = _summarize_vehicle_status(datasets.get("vehicle_status"))
    if vehicle_status:
        summary["vehicle_status"] = vehicle_status

    land_detected = _summarize_land_detected(datasets.get("vehicle_land_detected"))
    if land_detected:
        summary["land_detected"] = land_detected

    commands = _summarize_commands(datasets.get("vehicle_command"), datasets.get("vehicle_command_ack"))
    if commands:
        summary["commands"] = commands

    return summary


def _dataset_sample_count(dataset: Any) -> int:
    data = getattr(dataset, "data", {}) if dataset is not None else {}
    if not isinstance(data, Mapping) or not data:
        return 0
    first = next(iter(data.values()))
    try:
        return int(len(first))
    except TypeError:
        return 0


def _duration_seconds(ulog: Any) -> float | None:
    start = _safe_float(getattr(ulog, "start_timestamp", None), None)
    end = _safe_float(getattr(ulog, "last_timestamp", None), None)
    if start is None or end is None or end < start:
        return None
    return _round((end - start) / 1_000_000.0, 3)


def _summarize_dropouts(dropouts: Sequence[Any]) -> dict[str, Any]:
    durations_ms: list[float] = []
    for dropout in dropouts:
        duration = _safe_float(getattr(dropout, "duration", None), None)
        if duration is None and isinstance(dropout, Mapping):
            duration = _safe_float(dropout.get("duration"), None)
        if duration is not None:
            durations_ms.append(duration)
    return {
        "count": len(dropouts),
        "total_duration_sec": _round(sum(durations_ms) / 1000.0, 3) if durations_ms else 0.0,
        "max_duration_ms": _round(max(durations_ms), 3) if durations_ms else 0.0,
    }


def _summarize_logged_messages(messages: Sequence[Any]) -> dict[str, Any]:
    levels: Counter[str] = Counter()
    for message in messages:
        level = getattr(message, "log_level", None)
        if level is None and isinstance(message, Mapping):
            level = message.get("log_level")
        levels[str(level if level is not None else "unknown")] += 1
    return {
        "count": len(messages),
        "levels": dict(sorted(levels.items())),
        "raw_text_included": False,
    }


def _summarize_system_info(info: Mapping[str, Any]) -> dict[str, Any]:
    allowed = ("sys_name", "ver_hw")
    return {key: str(info.get(key)) for key in allowed if info.get(key) is not None}


def _summarize_local_position(dataset: Any) -> dict[str, Any]:
    if dataset is None:
        return {}
    data = getattr(dataset, "data", {}) or {}
    x = _finite_array(data.get("x"))
    y = _finite_array(data.get("y"))
    z = _finite_array(data.get("z"))
    if x.size == 0 or y.size == 0 or z.size == 0:
        return {}
    size = min(x.size, y.size, z.size)
    x = x[:size]
    y = y[:size]
    z = z[:size]
    horizontal_from_start = np.sqrt((x - x[0]) ** 2 + (y - y[0]) ** 2)
    relative_up = -z
    return {
        "samples": int(size),
        "x_range_m": _range(x),
        "y_range_m": _range(y),
        "relative_altitude_range_m": _range(relative_up),
        "max_horizontal_distance_from_start_m": _round(float(np.max(horizontal_from_start)), 3),
        "final_relative_position_m": {
            "north": _round(float(x[-1] - x[0]), 3),
            "east": _round(float(y[-1] - y[0]), 3),
            "up": _round(float(relative_up[-1] - relative_up[0]), 3),
        },
    }


def _summarize_setpoint(dataset: Any) -> dict[str, Any]:
    if dataset is None:
        return {}
    data = getattr(dataset, "data", {}) or {}
    result: dict[str, Any] = {"samples": _dataset_sample_count(dataset)}
    for key, label in (("position[0]", "north_m"), ("position[1]", "east_m"), ("position[2]", "down_m")):
        values = _finite_array(data.get(key))
        if values.size:
            result[f"{label}_range"] = _range(values)
    return result


def _summarize_battery(dataset: Any) -> dict[str, Any]:
    if dataset is None:
        return {}
    data = getattr(dataset, "data", {}) or {}
    result: dict[str, Any] = {"samples": _dataset_sample_count(dataset)}
    voltage = _finite_array(data.get("voltage_v"))
    if voltage.size:
        result["voltage_v"] = _range(voltage)
    remaining = _finite_array(data.get("remaining"))
    if remaining.size:
        result["remaining"] = _range(remaining)
    return result


def _summarize_vehicle_status(dataset: Any) -> dict[str, Any]:
    if dataset is None:
        return {}
    data = getattr(dataset, "data", {}) or {}
    result: dict[str, Any] = {"samples": _dataset_sample_count(dataset)}
    for key in ("arming_state", "nav_state", "failsafe", "hil_state"):
        counts = _value_counts(data.get(key))
        if counts:
            result[key] = counts
    return result


def _summarize_land_detected(dataset: Any) -> dict[str, Any]:
    if dataset is None:
        return {}
    data = getattr(dataset, "data", {}) or {}
    result: dict[str, Any] = {"samples": _dataset_sample_count(dataset)}
    for key in ("landed", "maybe_landed", "ground_contact", "freefall"):
        counts = _value_counts(data.get(key))
        if counts:
            result[key] = counts
    return result


def _summarize_commands(command_dataset: Any, ack_dataset: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if command_dataset is not None:
        command_data = getattr(command_dataset, "data", {}) or {}
        result["vehicle_command"] = {
            "samples": _dataset_sample_count(command_dataset),
            "command_counts": _value_counts(command_data.get("command")),
        }
    if ack_dataset is not None:
        ack_data = getattr(ack_dataset, "data", {}) or {}
        result["vehicle_command_ack"] = {
            "samples": _dataset_sample_count(ack_dataset),
            "command_counts": _value_counts(ack_data.get("command")),
            "result_counts": _value_counts(ack_data.get("result")),
        }
    return result


def _finite_array(values: Any) -> np.ndarray:
    if values is None:
        return np.asarray([], dtype=float)
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0:
        return array
    return array[np.isfinite(array)]


def _range(values: np.ndarray) -> dict[str, float]:
    return {
        "min": _round(float(np.min(values)), 3),
        "max": _round(float(np.max(values)), 3),
        "final": _round(float(values[-1]), 3),
    }


def _value_counts(values: Any, *, limit: int = 12) -> dict[str, int]:
    if values is None:
        return {}
    try:
        array = np.asarray(values).reshape(-1)
    except Exception:
        return {}
    counts: Counter[str] = Counter()
    for raw in array:
        if isinstance(raw, np.generic):
            raw = raw.item()
        if isinstance(raw, float) and not math.isfinite(raw):
            continue
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        counts[str(raw)] += 1
    return dict(counts.most_common(limit))


def _round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return _safe_int(raw, default)


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:240]
