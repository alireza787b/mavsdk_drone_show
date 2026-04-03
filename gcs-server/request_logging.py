"""Helpers for classifying API request log noise by operational value."""
from __future__ import annotations


_ROUTINE_SUCCESS_PATHS = {
    "/api/logs/sources",
    "/api/telemetry",
    "/api/v1/commands/active",
    "/api/v1/commands/recent",
    "/api/v1/command-reports/execution-result",
    "/api/v1/command-reports/execution-start",
    "/commands/recent",
    "/drone-heartbeat",
    "/get-config-data",
    "/get-heartbeats",
    "/get-origin",
    "/git-status",
    "/health",
    "/ping",
    "/telemetry",
}


def is_routine_success_path(path: str) -> bool:
    """Return True when a successful request is expected polling noise."""
    if path in _ROUTINE_SUCCESS_PATHS:
        return True

    if path == "/command/execution-result":
        return True

    if path.startswith("/api/v1/commands/") and not path.endswith("/cancel") and path != "/api/v1/commands/statistics":
        return True

    if path.startswith("/command/"):
        return True

    if path == "/api/logs/stream":
        return True

    if path.startswith("/api/logs/drone/") and path.endswith("/stream"):
        return True

    return False


def get_request_log_level(path: str, status_code: int) -> str:
    """Map an API response to the right operational log level."""
    if status_code >= 500:
        return "ERROR"

    if status_code >= 400:
        return "WARNING"

    if is_routine_success_path(path):
        return "DEBUG"

    return "INFO"
