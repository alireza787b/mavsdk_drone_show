"""Helpers for classifying API request log noise by operational value."""
from __future__ import annotations


_ROUTINE_SUCCESS_PATHS = {
    "/api/logs/sources",
    "/api/v1/git/status",
    "/api/v1/fleet/telemetry",
    "/api/v1/origin",
    "/api/v1/commands/active",
    "/api/v1/commands/recent",
    "/api/v1/command-reports/execution-result",
    "/api/v1/command-reports/execution-start",
    "/api/v1/fleet/heartbeats",
    "/api/v1/config/fleet",
    "/api/v1/system/runtime-status",
    "/api/v1/simurgh/policy",
    "/api/v1/simurgh/status",
    "/health",
    "/ping",
}

_ROUTINE_AUTH_NOISE_METHODS = {"GET", "HEAD", "OPTIONS"}


def is_routine_success_path(path: str) -> bool:
    """Return True when a successful request is expected polling noise."""
    if path in _ROUTINE_SUCCESS_PATHS:
        return True

    if path.startswith("/api/v1/commands/") and path != "/api/v1/commands/statistics":
        return True

    if path == "/api/logs/stream":
        return True

    if path.startswith("/api/logs/drone/") and path.endswith("/stream"):
        return True

    return False


def is_routine_auth_noise_path(path: str, method: str | None = None) -> bool:
    """Return True for expected unauthenticated dashboard polling noise.

    This never changes the HTTP response or auth decision. It only prevents
    stale tabs and pre-login polling from being presented as operator warnings.
    Mutating methods remain warnings even when the path is familiar.
    """

    if method is not None and method.upper() not in _ROUTINE_AUTH_NOISE_METHODS:
        return False

    return is_routine_success_path(path)


def get_request_log_level(path: str, status_code: int, method: str | None = None) -> str:
    """Map an API response to the right operational log level."""
    if status_code >= 500:
        return "ERROR"

    if status_code in {401, 403} and is_routine_auth_noise_path(path, method):
        return "DEBUG"

    if status_code >= 400:
        return "WARNING"

    if is_routine_success_path(path):
        return "DEBUG"

    return "INFO"
