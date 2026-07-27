"""
Async helpers to proxy log requests from GCS to individual drones.

GCS is the single gateway — the UI never connects directly to drones.
Drone IPs are resolved from the fleet config (same as command.py).
Reference: docs/guides/logging-system.md
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from pydantic import ValidationError

from config import load_config
from mds_logging import get_logger
from mds_logging.api_schemas import OnboardUlogSummaryResponse
from mds_logging.schema import build_log_entry
from mds_logging.ulog_analysis import (
    DEFAULT_ULOG_SUMMARY_MAX_BYTES,
    UlogSummaryError,
    summarize_ulog_file_with_timeout,
)
from src.drone_api_routes import (
    DRONE_ULOG_DOWNLOAD_CONTENT_ROUTE_TEMPLATE,
    DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE,
    DRONE_ULOG_ERASE_ALL_ROUTE,
    DRONE_ULOG_FILES_ROUTE,
    DRONE_ULOG_FILE_SUMMARY_ROUTE_TEMPLATE,
    DRONE_ULOG_FILE_DOWNLOAD_ROUTE_TEMPLATE,
    DRONE_ULOG_JOB_TOKEN_HEADER,
    DRONE_ULOG_POLICY_ROUTE,
)
from src.security.auth import (
    MACHINE_CREDENTIAL_HEADER,
    MachineCredentialUnavailable,
    ULOG_OP_DOWNLOAD_CONTENT,
    ULOG_OP_DOWNLOAD_CREATE,
    ULOG_OP_DOWNLOAD_DELETE,
    ULOG_OP_DOWNLOAD_STATUS,
    ULOG_OP_ERASE,
    ULOG_OP_FILES_READ,
    ULOG_OP_POLICY_READ,
    ULOG_OP_SUMMARY_READ,
    build_auth_service,
)
from src.ulog_proxy_policy import (
    DEFAULT_DRONE_ULOG_PROXY_TIMEOUT_SECONDS,
    DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS,
    drone_ulog_proxy_timeout_seconds,
    drone_ulog_summary_timeout_seconds,
)

__all__ = [
    "DEFAULT_DRONE_ULOG_PROXY_TIMEOUT_SECONDS",
    "DEFAULT_DRONE_ULOG_SUMMARY_TIMEOUT_SECONDS",
]

logger = get_logger("log_proxy")

def _drone_api_port() -> int:
    raw_value = os.getenv("MDS_DRONE_API_PORT", os.getenv("MDS_DEFAULT_DRONE_API_PORT", "7070"))
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        logger.warning("Invalid MDS_DRONE_API_PORT=%r; using 7070", raw_value)
        return 7070


_TIMEOUT = 5.0  # seconds
_ULOG_DOWNLOAD_POLL_INTERVAL_SECONDS = 0.25
_ULOG_STREAM_CHUNK_BYTES = 1024 * 1024
_ULOG_CLEANUP_TIMEOUT_SECONDS = 5.0


class DroneProxyRequestError(Exception):
    """Base error for proxied drone HTTP requests."""


class DroneProxyUnavailableError(DroneProxyRequestError):
    """Raised when the drone cannot be reached from GCS."""


class DroneProxyResponseError(DroneProxyRequestError):
    """Raised when the drone responds with a non-success HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = int(status_code)
        self.detail = detail


def _validate_ulog_summary_payload(payload: Any) -> dict[str, Any]:
    """Fail closed when a node or fallback parser violates the public schema."""

    try:
        validated = OnboardUlogSummaryResponse.model_validate(payload)
    except ValidationError as exc:
        raise DroneProxyResponseError(
            502,
            "Drone returned an invalid ULog summary response.",
        ) from exc
    return validated.model_dump(mode="json")


def _ulog_summary_max_bytes() -> int:
    raw_value = os.getenv("MDS_ULOG_SUMMARY_MAX_BYTES")
    try:
        value = int(raw_value) if raw_value is not None else DEFAULT_ULOG_SUMMARY_MAX_BYTES
    except (TypeError, ValueError):
        value = DEFAULT_ULOG_SUMMARY_MAX_BYTES
    return max(1, value)


def _summary_deadline(timeout: float | None = None) -> float:
    raw_timeout = drone_ulog_summary_timeout_seconds() if timeout is None else timeout
    try:
        timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError):
        timeout_seconds = drone_ulog_summary_timeout_seconds()
    if timeout_seconds <= 0:
        timeout_seconds = drone_ulog_summary_timeout_seconds()
    return time.monotonic() + timeout_seconds


def _remaining_summary_seconds(deadline: float, *, operation: str = "downloading ULog") -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DroneProxyResponseError(504, f"Timed out while {operation}")
    return remaining


def _bounded_proxy_timeout(deadline: float) -> float:
    return min(
        drone_ulog_proxy_timeout_seconds(),
        _remaining_summary_seconds(deadline),
    )


def _summary_log_id_from_path(path: str) -> int | None:
    prefix, suffix = DRONE_ULOG_FILE_SUMMARY_ROUTE_TEMPLATE.split("{log_id}", 1)
    normalized = str(path or "")
    if not normalized.startswith(prefix) or not normalized.endswith(suffix):
        return None
    raw_log_id = normalized[len(prefix):len(normalized) - len(suffix) if suffix else None]
    try:
        log_id = int(raw_log_id)
    except (TypeError, ValueError):
        return None
    return log_id if log_id >= 0 else None


def resolve_drone_ip(drone_id: int) -> Optional[str]:
    """Resolve a drone_id (hw_id as int) to its IP address from fleet config."""
    drones = load_config()
    for d in drones:
        hw = d.get("hw_id", "")
        try:
            if int(hw) == drone_id:
                return d.get("ip")
        except (ValueError, TypeError):
            continue
    return None


def _build_drone_url(drone_ip: str, path: str) -> str:
    return f"http://{drone_ip}:{_drone_api_port()}{path}"


def _path_matches_template(path: str, template: str) -> bool:
    if "{" not in template:
        return path == template
    prefix, remainder = template.split("{", 1)
    _, suffix = remainder.split("}", 1)
    if not path.startswith(prefix) or not path.endswith(suffix):
        return False
    end = len(path) - len(suffix) if suffix else len(path)
    value = path[len(prefix):end]
    return bool(value and "/" not in value)


def _ulog_operation(method: str, path: str) -> str | None:
    normalized_method = str(method or "").upper()
    if normalized_method == "GET" and path == DRONE_ULOG_POLICY_ROUTE:
        return ULOG_OP_POLICY_READ
    if normalized_method == "GET" and path == DRONE_ULOG_FILES_ROUTE:
        return ULOG_OP_FILES_READ
    if normalized_method == "GET" and _path_matches_template(
        path,
        DRONE_ULOG_FILE_SUMMARY_ROUTE_TEMPLATE,
    ):
        return ULOG_OP_SUMMARY_READ
    if normalized_method == "POST" and _path_matches_template(
        path,
        DRONE_ULOG_FILE_DOWNLOAD_ROUTE_TEMPLATE,
    ):
        return ULOG_OP_DOWNLOAD_CREATE
    if _path_matches_template(path, DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE):
        if normalized_method == "GET":
            return ULOG_OP_DOWNLOAD_STATUS
        if normalized_method == "DELETE":
            return ULOG_OP_DOWNLOAD_DELETE
    if normalized_method == "GET" and _path_matches_template(
        path,
        DRONE_ULOG_DOWNLOAD_CONTENT_ROUTE_TEMPLATE,
    ):
        return ULOG_OP_DOWNLOAD_CONTENT
    if normalized_method == "POST" and path == DRONE_ULOG_ERASE_ALL_ROUTE:
        return ULOG_OP_ERASE
    return None


def _drone_machine_audience(drone_ip: str) -> str:
    normalized_ip = str(drone_ip or "").strip()
    matches = [
        str(drone.get("hw_id") or "").strip()
        for drone in load_config()
        if str(drone.get("ip") or "").strip() == normalized_ip
        and str(drone.get("hw_id") or "").strip()
    ]
    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) != 1:
        raise DroneProxyResponseError(
            503,
            "Target node identity is not uniquely configured for ULog authentication.",
        )
    return f"mds-drone:{unique_matches[0]}"


def _authenticated_ulog_headers(
    method: str,
    drone_ip: str,
    path: str,
    headers: dict[str, str] | None = None,
) -> dict[str, str] | None:
    operation = _ulog_operation(method, path)
    if operation is None:
        return dict(headers) if headers else None
    service = build_auth_service()
    try:
        credential = service.issue_machine_credential(
            audience=_drone_machine_audience(drone_ip),
            operation=operation,
            target_ip=drone_ip,
        )
    except (MachineCredentialUnavailable, OSError, ValueError) as exc:
        hardened_sitl = bool(
            os.environ.get("MDS_SITL_GCS_API_TOKEN_FILE", "").strip()
        )
        if not service.settings.api_auth_enabled and not hardened_sitl:
            return dict(headers) if headers else None
        raise DroneProxyResponseError(
            503,
            "GCS-to-node ULog machine authentication is not configured for this target.",
        ) from exc
    protected_headers = dict(headers or {})
    protected_headers[MACHINE_CREDENTIAL_HEADER] = credential
    return protected_headers


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail
    except Exception:
        pass
    text = (response.text or "").strip()
    return text or f"Drone proxy request failed with HTTP {response.status_code}"


async def _request_json(
    method: str,
    drone_ip: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = _TIMEOUT,
) -> dict:
    request_headers = _authenticated_ulog_headers(
        method,
        drone_ip,
        path,
        headers,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method,
                _build_drone_url(drone_ip, path),
                params=params,
                json=json_body,
                headers=request_headers,
            )
    except Exception as exc:
        raise DroneProxyUnavailableError(str(exc)) from exc

    if resp.status_code >= 400:
        raise DroneProxyResponseError(resp.status_code, _extract_error_detail(resp))
    return resp.json()


def _request_json_sync(
    method: str,
    drone_ip: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = _TIMEOUT,
) -> dict:
    request_headers = _authenticated_ulog_headers(
        method,
        drone_ip,
        path,
        headers,
    )
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(
                method,
                _build_drone_url(drone_ip, path),
                params=params,
                json=json_body,
                headers=request_headers,
            )
    except Exception as exc:
        raise DroneProxyUnavailableError(str(exc)) from exc

    if resp.status_code >= 400:
        raise DroneProxyResponseError(resp.status_code, _extract_error_detail(resp))
    payload = resp.json()
    if not isinstance(payload, dict):
        raise DroneProxyResponseError(502, "Drone proxy returned non-object JSON")
    return payload


def fetch_drone_json_sync(
    drone_ip: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float | None = _TIMEOUT,
) -> dict:
    """Fetch a drone JSON endpoint through the GCS log-proxy boundary.

    This synchronous helper exists for Simurgh's local read-tool path, which is
    intentionally synchronous. Keep direct drone URL construction here so
    dashboard routes, MCP tools, and assistant reads share one proxy boundary.
    """

    log_id = _summary_log_id_from_path(path)
    if log_id is not None and not params:
        return fetch_drone_ulog_summary_sync(
            drone_ip,
            log_id,
            timeout=timeout,
        )
    return _request_json_sync(
        "GET",
        drone_ip,
        path,
        params=params,
        timeout=timeout,
    )


async def fetch_drone_sessions(drone_ip: str) -> Optional[dict]:
    """Fetch session list from a drone. Returns None if unreachable."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_build_drone_url(drone_ip, "/api/logs/sessions"))
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"Drone at {drone_ip} unreachable: {e}")
        return None


async def fetch_drone_session_content(
    drone_ip: str,
    session_id: str,
    level: str | None = None,
    component: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    since: str | None = None,
) -> Optional[dict]:
    """Fetch session content from a drone. Returns None if unreachable."""
    params: dict = {}
    if level:
        params["level"] = level
    if component:
        params["component"] = component
    if limit is not None:
        params["limit"] = limit
    if offset:
        params["offset"] = offset
    if since:
        params["since"] = since
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                _build_drone_url(drone_ip, f"/api/logs/sessions/{session_id}"),
                params=params,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"Drone at {drone_ip} unreachable for session {session_id}: {e}")
        return None


async def fetch_drone_ulog_policy(drone_ip: str) -> dict:
    return await _request_json("GET", drone_ip, DRONE_ULOG_POLICY_ROUTE, timeout=drone_ulog_proxy_timeout_seconds())


async def fetch_drone_ulog_files(drone_ip: str) -> dict:
    return await _request_json("GET", drone_ip, DRONE_ULOG_FILES_ROUTE, timeout=drone_ulog_proxy_timeout_seconds())


async def fetch_drone_ulog_summary(drone_ip: str, log_id: int) -> dict:
    timeout_seconds = drone_ulog_summary_timeout_seconds()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                fetch_drone_ulog_summary_sync,
                drone_ip,
                int(log_id),
                timeout=timeout_seconds,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise DroneProxyResponseError(
            504,
            f"Timed out after {timeout_seconds:g} second(s) while summarizing ULog"
        ) from exc


def fetch_drone_ulog_summary_sync(
    drone_ip: str,
    log_id: int,
    *,
    timeout: float | None = None,
) -> dict:
    """Return a direct or backward-compatible derived ULog summary."""

    deadline = _summary_deadline(timeout)
    try:
        return _validate_ulog_summary_payload(
            _request_json_sync(
                "GET",
                drone_ip,
                DRONE_ULOG_FILE_SUMMARY_ROUTE_TEMPLATE.format(log_id=int(log_id)),
                timeout=_remaining_summary_seconds(deadline),
            )
        )
    except DroneProxyResponseError as exc:
        if exc.status_code != 404:
            raise
    return _fetch_drone_ulog_summary_fallback(
        drone_ip,
        int(log_id),
        deadline=deadline,
    )


async def create_drone_ulog_download_job(
    drone_ip: str,
    log_id: int,
    *,
    pos_id: int | None = None,
    access_token: str,
) -> dict:
    payload: dict[str, Any] = {}
    if pos_id is not None:
        payload["pos_id"] = int(pos_id)
    return await _request_json(
        "POST",
        drone_ip,
        DRONE_ULOG_FILE_DOWNLOAD_ROUTE_TEMPLATE.format(log_id=int(log_id)),
        json_body=payload,
        headers={DRONE_ULOG_JOB_TOKEN_HEADER: access_token},
        timeout=drone_ulog_proxy_timeout_seconds(),
    )


async def fetch_drone_ulog_download_job(
    drone_ip: str,
    job_id: str,
    *,
    access_token: str,
) -> dict:
    return await _request_json(
        "GET",
        drone_ip,
        DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE.format(job_id=job_id),
        headers={DRONE_ULOG_JOB_TOKEN_HEADER: access_token},
        timeout=drone_ulog_proxy_timeout_seconds(),
    )


async def delete_drone_ulog_download_job(
    drone_ip: str,
    job_id: str,
    *,
    access_token: str,
) -> dict:
    return await _request_json(
        "DELETE",
        drone_ip,
        DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE.format(job_id=job_id),
        headers={DRONE_ULOG_JOB_TOKEN_HEADER: access_token},
        timeout=drone_ulog_proxy_timeout_seconds(),
    )


async def erase_all_drone_ulogs(drone_ip: str) -> dict:
    return await _request_json(
        "POST",
        drone_ip,
        DRONE_ULOG_ERASE_ALL_ROUTE,
        timeout=drone_ulog_proxy_timeout_seconds(),
    )


async def open_drone_ulog_download_stream(
    drone_ip: str,
    job_id: str,
    *,
    access_token: str,
) -> tuple[httpx.AsyncClient, httpx.Response]:
    client = httpx.AsyncClient(timeout=drone_ulog_proxy_timeout_seconds())
    path = DRONE_ULOG_DOWNLOAD_CONTENT_ROUTE_TEMPLATE.format(job_id=job_id)
    request = client.build_request(
        "GET",
        _build_drone_url(drone_ip, path),
        headers=_authenticated_ulog_headers(
            "GET",
            drone_ip,
            path,
            {DRONE_ULOG_JOB_TOKEN_HEADER: access_token},
        ),
    )
    try:
        response = await client.send(request, stream=True)
    except Exception as exc:
        await client.aclose()
        raise DroneProxyUnavailableError(str(exc)) from exc

    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        await response.aclose()
        await client.aclose()
        raise DroneProxyResponseError(response.status_code, detail)

    return client, response


def _download_job(payload: dict, *, expected_job_id: str | None = None) -> dict[str, Any]:
    raw_job = payload.get("job")
    if not isinstance(raw_job, dict):
        raise DroneProxyResponseError(502, "Drone returned an invalid ULog download job")
    job = dict(raw_job)
    job_id = str(job.get("job_id") or "").strip()
    if not job_id or not str(job.get("status") or "").strip():
        raise DroneProxyResponseError(502, "Drone returned an incomplete ULog download job")
    if expected_job_id is not None and job_id != expected_job_id:
        raise DroneProxyResponseError(502, "Drone returned a mismatched ULog download job")
    return job


def _enforce_ulog_size(size_value: Any, max_bytes: int) -> int:
    try:
        size_bytes = int(size_value or 0)
    except (TypeError, ValueError) as exc:
        raise DroneProxyResponseError(502, "Drone returned an invalid ULog size") from exc
    if size_bytes < 0:
        raise DroneProxyResponseError(502, "Drone returned an invalid ULog size")
    if size_bytes > max_bytes:
        raise DroneProxyResponseError(
            413,
            f"ULog exceeds MDS_ULOG_SUMMARY_MAX_BYTES ({max_bytes} bytes)",
        )
    return size_bytes


def _wait_for_download_job(
    drone_ip: str,
    job: dict[str, Any],
    *,
    deadline: float,
    max_bytes: int,
    access_token: str,
) -> dict[str, Any]:
    current = dict(job)
    job_id = str(current["job_id"])
    while True:
        _enforce_ulog_size(current.get("size_bytes"), max_bytes)
        status = str(current.get("status") or "").strip().lower()
        if status == "ready":
            return current
        if status not in {"queued", "downloading"}:
            detail = str(
                current.get("error")
                or f"ULog download job ended with status {status or 'unknown'}"
            )
            raise DroneProxyResponseError(502, detail)
        time.sleep(
            min(
                _ULOG_DOWNLOAD_POLL_INTERVAL_SECONDS,
                _remaining_summary_seconds(deadline),
            )
        )
        current = _download_job(
            _request_json_sync(
                "GET",
                drone_ip,
                DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE.format(job_id=job_id),
                headers={DRONE_ULOG_JOB_TOKEN_HEADER: access_token},
                timeout=_bounded_proxy_timeout(deadline),
            ),
            expected_job_id=job_id,
        )


def _stream_download_to_temp(
    drone_ip: str,
    job_id: str,
    *,
    deadline: float,
    max_bytes: int,
    access_token: str,
) -> tuple[Path, int]:
    temp_path: Path | None = None
    total_bytes = 0
    try:
        with tempfile.NamedTemporaryFile(
            prefix="mds-proxied-ulog-summary-",
            suffix=".ulg",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            with httpx.Client(timeout=_bounded_proxy_timeout(deadline)) as client:
                path = DRONE_ULOG_DOWNLOAD_CONTENT_ROUTE_TEMPLATE.format(
                    job_id=job_id
                )
                with client.stream(
                    "GET",
                    _build_drone_url(drone_ip, path),
                    headers=_authenticated_ulog_headers(
                        "GET",
                        drone_ip,
                        path,
                        {DRONE_ULOG_JOB_TOKEN_HEADER: access_token},
                    ),
                ) as response:
                    if response.status_code >= 400:
                        raise DroneProxyResponseError(
                            response.status_code,
                            f"ULog content download failed with HTTP {response.status_code}",
                        )
                    content_length = response.headers.get("content-length")
                    if content_length:
                        _enforce_ulog_size(content_length, max_bytes)
                    for chunk in response.iter_bytes(chunk_size=_ULOG_STREAM_CHUNK_BYTES):
                        _remaining_summary_seconds(deadline)
                        total_bytes += len(chunk)
                        _enforce_ulog_size(total_bytes, max_bytes)
                        handle.write(chunk)
        if total_bytes <= 0:
            raise DroneProxyResponseError(502, "Drone returned an empty ULog download")
        return temp_path, total_bytes
    except DroneProxyRequestError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise DroneProxyUnavailableError(str(exc)) from exc


def _delete_download_job_after_fallback(
    drone_ip: str,
    job_id: str,
    *,
    access_token: str,
) -> bool:
    try:
        _request_json_sync(
            "DELETE",
            drone_ip,
            DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE.format(job_id=job_id),
            headers={DRONE_ULOG_JOB_TOKEN_HEADER: access_token},
            timeout=min(drone_ulog_proxy_timeout_seconds(), _ULOG_CLEANUP_TIMEOUT_SECONDS),
        )
        return True
    except DroneProxyResponseError as exc:
        if exc.status_code == 404:
            return True
        logger.warning("Failed to delete staged ULog job %s on %s: %s", job_id, drone_ip, exc)
    except DroneProxyRequestError as exc:
        logger.warning("Failed to delete staged ULog job %s on %s: %s", job_id, drone_ip, exc)
    return False


def _build_fallback_summary(
    parsed: dict[str, Any],
    *,
    job: dict[str, Any],
    log_id: int,
    staged_job_deleted: bool,
) -> dict[str, Any]:
    summary = dict(parsed)
    source = dict(summary.get("source") or {})
    source.update(
        source_kind="drone_staged_download_fallback",
        log_id=int(log_id),
        date_utc=job.get("date_utc"),
        size_bytes=int(job.get("size_bytes") or 0),
    )
    correlation = dict(summary.get("correlation") or {})
    evidence = dict(correlation.get("evidence") or {})
    evidence["target_drone_id"] = str(job.get("hw_id") or "") or None
    correlation["evidence"] = evidence
    summary.update(
        source=source,
        correlation=correlation,
        hw_id=str(job.get("hw_id") or ""),
        pos_id=job.get("pos_id"),
        log_id=int(log_id),
        staged_job_deleted=bool(staged_job_deleted),
        raw_content_included=False,
        timestamp=int(time.time() * 1000),
    )
    return summary


def _fetch_drone_ulog_summary_fallback(
    drone_ip: str,
    log_id: int,
    *,
    deadline: float,
) -> dict:
    max_bytes = _ulog_summary_max_bytes()
    job_id: str | None = None
    temp_path: Path | None = None
    summary: dict[str, Any] | None = None
    ready_job: dict[str, Any] | None = None
    deleted = False
    access_token = secrets.token_urlsafe(32)
    try:
        queued_job = _download_job(
            _request_json_sync(
                "POST",
                drone_ip,
                DRONE_ULOG_FILE_DOWNLOAD_ROUTE_TEMPLATE.format(log_id=int(log_id)),
                json_body={},
                headers={DRONE_ULOG_JOB_TOKEN_HEADER: access_token},
                timeout=_bounded_proxy_timeout(deadline),
            )
        )
        job_id = str(queued_job["job_id"])
        ready_job = _wait_for_download_job(
            drone_ip,
            queued_job,
            deadline=deadline,
            max_bytes=max_bytes,
            access_token=access_token,
        )
        temp_path, downloaded_bytes = _stream_download_to_temp(
            drone_ip,
            job_id,
            deadline=deadline,
            max_bytes=max_bytes,
            access_token=access_token,
        )
        ready_job["size_bytes"] = downloaded_bytes
        _remaining_summary_seconds(deadline, operation="starting ULog parser")
        try:
            summary = summarize_ulog_file_with_timeout(
                temp_path,
                source_metadata={
                    "source_kind": "drone_staged_download_fallback",
                    "log_id": int(log_id),
                    "date_utc": ready_job.get("date_utc"),
                    "size_bytes": downloaded_bytes,
                },
                max_bytes=max_bytes,
                timeout_seconds=_remaining_summary_seconds(
                    deadline,
                    operation="starting ULog parser",
                ),
            )
        except TimeoutError as exc:
            raise DroneProxyResponseError(504, str(exc)) from exc
        except UlogSummaryError as exc:
            raise DroneProxyResponseError(exc.http_status, str(exc)) from exc
        _remaining_summary_seconds(deadline, operation="parsing ULog")
        if not isinstance(summary, dict):
            raise DroneProxyResponseError(502, "ULog parser returned an invalid summary")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        if job_id is not None:
            deleted = _delete_download_job_after_fallback(
                drone_ip,
                job_id,
                access_token=access_token,
            )

    if summary is None or ready_job is None:
        raise DroneProxyResponseError(502, "ULog fallback did not produce a summary")
    return _validate_ulog_summary_payload(
        _build_fallback_summary(
            summary,
            job=ready_job,
            log_id=int(log_id),
            staged_job_deleted=deleted,
        )
    )


def stream_drone_logs(
    drone_ip: str,
    drone_id: int,
    level: str | None = None,
    component: str | None = None,
    source: str | None = None,
):
    """Proxy SSE from a drone as a synchronous iterator for StreamingResponse."""
    params: dict = {}
    if level:
        params["level"] = level
    if component:
        params["component"] = component
    if source:
        params["source"] = source
    try:
        with httpx.Client(timeout=None) as client:
            with client.stream(
                "GET",
                _build_drone_url(drone_ip, "/api/logs/stream"),
                params=params,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")
                    if line.startswith("data: "):
                        yield line + "\n\n"
    except GeneratorExit:
        return
    except Exception as e:
        error = build_log_entry(
            level="WARNING",
            component="log_proxy",
            source="gcs",
            msg=f"Drone #{drone_id} log stream unavailable: {e}",
            session_id="",
            drone_id=drone_id,
            extra={
                "kind": "proxy_stream_error",
                "drone_ip": drone_ip,
                "error": str(e),
            },
        )
        yield f"data: {json.dumps(error)}\n\n"
