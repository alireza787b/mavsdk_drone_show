"""Canonical resource limits for raw ULog staging and transfer."""

from __future__ import annotations

import os


DEFAULT_ULOG_DOWNLOAD_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_ULOG_DOWNLOAD_AGGREGATE_MAX_BYTES = 1024 * 1024 * 1024
DEFAULT_ULOG_DOWNLOAD_MIN_FREE_BYTES = 512 * 1024 * 1024
DEFAULT_ULOG_DOWNLOAD_TIMEOUT_SECONDS = 900.0
DEFAULT_ULOG_DOWNLOAD_IDLE_TIMEOUT_SECONDS = 60.0


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)
    return value if value > 0 else int(default)


def _env_positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)
    return value if value > 0 else float(default)


def ulog_download_max_bytes() -> int:
    return _env_positive_int(
        "MDS_ULOG_DOWNLOAD_MAX_BYTES",
        DEFAULT_ULOG_DOWNLOAD_MAX_BYTES,
    )


def ulog_download_aggregate_max_bytes() -> int:
    return _env_positive_int(
        "MDS_ULOG_DOWNLOAD_AGGREGATE_MAX_BYTES",
        DEFAULT_ULOG_DOWNLOAD_AGGREGATE_MAX_BYTES,
    )


def ulog_download_min_free_bytes() -> int:
    return _env_positive_int(
        "MDS_ULOG_DOWNLOAD_MIN_FREE_BYTES",
        DEFAULT_ULOG_DOWNLOAD_MIN_FREE_BYTES,
    )


def ulog_download_timeout_seconds() -> float:
    return _env_positive_float(
        "MDS_ULOG_DOWNLOAD_TIMEOUT_SEC",
        DEFAULT_ULOG_DOWNLOAD_TIMEOUT_SECONDS,
    )


def ulog_download_idle_timeout_seconds() -> float:
    return min(
        ulog_download_timeout_seconds(),
        _env_positive_float(
            "MDS_ULOG_DOWNLOAD_IDLE_TIMEOUT_SEC",
            DEFAULT_ULOG_DOWNLOAD_IDLE_TIMEOUT_SECONDS,
        ),
    )
