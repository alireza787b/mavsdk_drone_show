"""Bounded local PX4 ULog summary helpers.

This module converts a local ``.ulg`` file into derived operator metrics. It
never returns raw topic arrays, raw log message text, or file bytes.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from functools import partial
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any, Callable, Mapping, Sequence

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
DEFAULT_ULOG_SUMMARY_MAX_WORKERS = 2
DEFAULT_ULOG_SUMMARY_MAX_QUEUE = 4
DEFAULT_ULOG_SUMMARY_MAX_MEMORY_MB = 1024
DEFAULT_ULOG_SUMMARY_MAX_CPU_SECONDS = 60
DEFAULT_ULOG_SUMMARY_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
DEFAULT_ULOG_SUMMARY_MAX_OPEN_FILES = 64
ULOG_SUMMARY_WORKER_RESULT_PREFIX = "MDS_ULOG_SUMMARY_RESULT:"
_ULOG_SUMMARY_WORKER_GRACE_SECONDS = 2.0
_ULOG_SUMMARY_EXECUTOR: ThreadPoolExecutor | None = None
_ULOG_SUMMARY_SLOTS: BoundedSemaphore | None = None
_ULOG_SUMMARY_EXECUTOR_LOCK = Lock()


class UlogSummaryError(RuntimeError):
    """Typed parser execution or result failure."""

    def __init__(self, message: str, *, code: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = int(http_status)


class UlogSummaryTimeoutError(TimeoutError):
    """Raised when a parser worker exceeds its wall-clock deadline."""

    code = "ulog_summary_timeout"
    http_status = 504


def _summary_executor() -> ThreadPoolExecutor:
    global _ULOG_SUMMARY_EXECUTOR, _ULOG_SUMMARY_SLOTS
    with _ULOG_SUMMARY_EXECUTOR_LOCK:
        if _ULOG_SUMMARY_EXECUTOR is None:
            max_workers = _env_int(
                "MDS_ULOG_SUMMARY_MAX_WORKERS",
                DEFAULT_ULOG_SUMMARY_MAX_WORKERS,
            )
            max_workers = max(1, min(max_workers, 8))
            max_queue = _env_int(
                "MDS_ULOG_SUMMARY_MAX_QUEUE",
                DEFAULT_ULOG_SUMMARY_MAX_QUEUE,
            )
            max_queue = max(0, min(max_queue, 32))
            _ULOG_SUMMARY_EXECUTOR = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="mds-ulog-summary",
            )
            _ULOG_SUMMARY_SLOTS = BoundedSemaphore(max_workers + max_queue)
        return _ULOG_SUMMARY_EXECUTOR


def _submit_summary_operation(
    operation: Callable[[], dict[str, Any]],
) -> Future[dict[str, Any]]:
    executor = _summary_executor()
    slots = _ULOG_SUMMARY_SLOTS
    if slots is None or not slots.acquire(blocking=False):
        raise UlogSummaryError(
            "ULog parser capacity is busy; retry after an active summary completes",
            code="ulog_summary_busy",
            http_status=429,
        )
    try:
        future = executor.submit(operation)
    except Exception:
        slots.release()
        raise
    future.add_done_callback(lambda _future: slots.release())
    return future


def _validated_timeout_seconds(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("ULog summary timeout must be a positive number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("ULog summary timeout must be a positive number")
    return timeout


def _summary_memory_limit_mb() -> int:
    configured = _env_int(
        "MDS_ULOG_SUMMARY_MAX_MEMORY_MB",
        DEFAULT_ULOG_SUMMARY_MAX_MEMORY_MB,
    )
    return max(128, min(configured, 4096))


def _summary_cpu_limit_seconds() -> int:
    configured = _env_int(
        "MDS_ULOG_SUMMARY_MAX_CPU_SEC",
        DEFAULT_ULOG_SUMMARY_MAX_CPU_SECONDS,
    )
    return max(1, min(configured, 300))


def _summary_output_limit_bytes() -> int:
    configured = _env_int(
        "MDS_ULOG_SUMMARY_MAX_OUTPUT_BYTES",
        DEFAULT_ULOG_SUMMARY_MAX_OUTPUT_BYTES,
    )
    return max(1024 * 1024, min(configured, 64 * 1024 * 1024))


def _summary_open_file_limit() -> int:
    configured = _env_int(
        "MDS_ULOG_SUMMARY_MAX_OPEN_FILES",
        DEFAULT_ULOG_SUMMARY_MAX_OPEN_FILES,
    )
    return max(16, min(configured, 256))


def _worker_environment(repo_root: str) -> dict[str, str]:
    """Return the minimal non-secret environment inherited by parser workers."""

    return {
        "PATH": os.defpath,
        "PYTHONPATH": repo_root,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "MDS_ULOG_SUMMARY_MAX_MEMORY_MB": str(_summary_memory_limit_mb()),
        "MDS_ULOG_SUMMARY_MAX_CPU_SEC": str(_summary_cpu_limit_seconds()),
        "MDS_ULOG_SUMMARY_MAX_OUTPUT_BYTES": str(_summary_output_limit_bytes()),
        "MDS_ULOG_SUMMARY_MAX_OPEN_FILES": str(_summary_open_file_limit()),
    }


def _terminate_worker(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=0.5)


def _worker_result(stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    result_line = next(
        (
            line[len(ULOG_SUMMARY_WORKER_RESULT_PREFIX):]
            for line in reversed(stdout.splitlines())
            if line.startswith(ULOG_SUMMARY_WORKER_RESULT_PREFIX)
        ),
        None,
    )
    if result_line is None:
        detail = (stderr or stdout).strip()[:500]
        raise UlogSummaryError(
            detail or f"ULog parser worker exited with status {returncode}",
            code="ulog_summary_worker_failed",
            http_status=500,
        )
    try:
        payload = json.loads(result_line)
    except json.JSONDecodeError as exc:
        raise UlogSummaryError(
            "ULog parser worker returned invalid output",
            code="ulog_summary_worker_invalid_output",
            http_status=500,
        ) from exc
    if not isinstance(payload, dict):
        raise UlogSummaryError(
            "ULog parser worker returned an invalid result",
            code="ulog_summary_worker_invalid_output",
            http_status=500,
        )
    if not payload.get("ok"):
        raise UlogSummaryError(
            str(payload.get("error") or "ULog parser worker failed")[:500],
            code=str(payload.get("code") or "ulog_summary_worker_failed"),
            http_status=int(payload.get("http_status") or 500),
        )
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise UlogSummaryError(
            "ULog parser worker returned an invalid summary",
            code="ulog_summary_worker_invalid_output",
            http_status=500,
        )
    try:
        from mds_logging.api_schemas import UlogDerivedSummary

        return UlogDerivedSummary.model_validate(summary).model_dump(mode="json")
    except Exception as exc:
        raise UlogSummaryError(
            "ULog parser worker returned an out-of-contract summary",
            code="ulog_summary_worker_invalid_output",
            http_status=500,
        ) from exc


def _raise_for_unparsed_summary(summary: Mapping[str, Any]) -> None:
    if bool(summary.get("parsed")):
        return
    parser = summary.get("parser")
    parser_payload = parser if isinstance(parser, Mapping) else {}
    status = str(parser_payload.get("status") or "failed").strip().lower()
    detail = str(parser_payload.get("error") or "ULog could not be parsed").strip()
    if status == "skipped":
        code, http_status = "ulog_summary_limit_exceeded", 413
    elif status == "unavailable":
        code, http_status = "ulog_summary_parser_unavailable", 503
    elif detail == "ULog file not found":
        code, http_status = "ulog_summary_not_found", 404
    else:
        code, http_status = "ulog_summary_parse_failed", 422
    raise UlogSummaryError(detail[:500], code=code, http_status=http_status)


def _run_summary_subprocess(
    path: str | Path,
    *,
    source_metadata: Mapping[str, Any] | None,
    max_bytes: int | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    timeout = _validated_timeout_seconds(timeout_seconds)
    repo_root = str(Path(__file__).resolve().parents[1])
    environment = _worker_environment(repo_root)
    request_payload = json.dumps(
        {
            "path": str(Path(path)),
            "source_metadata": dict(source_metadata or {}),
            "max_bytes": max_bytes,
        },
        default=str,
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "mds_logging.ulog_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        close_fds=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(request_payload, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_worker(process)
        raise UlogSummaryTimeoutError(
            f"ULog summary timed out after {timeout:g} second(s)"
        ) from exc
    if process.returncode != 0:
        return _worker_result(stdout, stderr, process.returncode)
    summary = _worker_result(stdout, stderr, process.returncode)
    _raise_for_unparsed_summary(summary)
    return summary


def summarize_ulog_file_with_timeout(
    path: str | Path,
    *,
    source_metadata: Mapping[str, Any] | None = None,
    max_bytes: int | None = None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Run one isolated parser process with bounded concurrency and resources."""

    timeout = _validated_timeout_seconds(timeout_seconds)
    future = _submit_summary_operation(
        partial(
            _run_summary_subprocess,
            path,
            source_metadata=source_metadata,
            max_bytes=max_bytes,
            timeout_seconds=timeout,
        )
    )
    try:
        return future.result(timeout=timeout + _ULOG_SUMMARY_WORKER_GRACE_SECONDS)
    except FutureTimeoutError as exc:
        future.cancel()
        raise UlogSummaryTimeoutError(
            f"ULog summary timed out after {timeout:g} second(s)"
        ) from exc


async def summarize_ulog_file_async(
    path: str | Path,
    *,
    source_metadata: Mapping[str, Any] | None = None,
    max_bytes: int | None = None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Parse one ULog outside the event loop in a killable worker process."""

    timeout = _validated_timeout_seconds(timeout_seconds)
    operation = partial(
        _run_summary_subprocess,
        path,
        source_metadata=source_metadata,
        max_bytes=max_bytes,
        timeout_seconds=timeout,
    )
    concurrent_future = _submit_summary_operation(operation)
    future = asyncio.wrap_future(concurrent_future)
    try:
        return await asyncio.wait_for(
            future,
            timeout=timeout + _ULOG_SUMMARY_WORKER_GRACE_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        concurrent_future.cancel()
        raise UlogSummaryTimeoutError(
            f"ULog summary timed out after {timeout:g} second(s)"
        ) from exc


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
        "correlation": {
            "status": "unverified",
            "verified": False,
            "method": "source_metadata_only" if metadata.get("date_utc") else "none",
            "evidence": {
                "ulog_log_id": metadata.get("log_id"),
                "ulog_started_at": metadata.get("date_utc"),
                "matched_dimensions": [],
            },
            "limitations": [
                "No GCS target, guarded-action reference, or command record was supplied to the ULog parser."
            ],
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
    samples = _joint_finite_sample_arrays(data, ("x", "y", "z"))
    if not samples:
        return {}
    x = samples["x"]
    y = samples["y"]
    z = samples["z"]
    size = x.size
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
    coordinates = (
        ("position[0]", "north_m"),
        ("position[1]", "east_m"),
        ("position[2]", "down_m"),
    )
    samples = _joint_finite_sample_arrays(data, tuple(key for key, _label in coordinates))
    result: dict[str, Any] = {
        "samples": int(samples["position[0]"].size) if samples else 0,
    }
    for key, label in coordinates:
        if samples:
            result[f"{label}_range"] = _range(samples[key])
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


def _joint_finite_sample_arrays(
    data: Mapping[str, Any],
    value_keys: Sequence[str],
) -> dict[str, np.ndarray]:
    """Return row-aligned finite values and their correlated PX4 timestamps."""

    timestamp_keys = tuple(
        key
        for key in ("timestamp", "timestamp_sample")
        if data.get(key) is not None
    )
    keys = (*value_keys, *timestamp_keys)
    arrays: dict[str, np.ndarray] = {}
    for key in keys:
        values = data.get(key)
        if values is None:
            return {}
        try:
            arrays[key] = np.asarray(values, dtype=float).reshape(-1)
        except (TypeError, ValueError):
            return {}

    if not arrays:
        return {}
    size = min(array.size for array in arrays.values())
    if size == 0:
        return {}

    valid = np.ones(size, dtype=bool)
    for array in arrays.values():
        valid &= np.isfinite(array[:size])
    if not np.any(valid):
        return {}

    return {
        key: array[:size][valid]
        for key, array in arrays.items()
    }


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
