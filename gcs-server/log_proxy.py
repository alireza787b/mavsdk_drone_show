"""
Async helpers to proxy log requests from GCS to individual drones.

GCS is the single gateway — the UI never connects directly to drones.
Drone IPs are resolved from the fleet config (same as command.py).
Reference: docs/guides/logging-system.md
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx

from config import load_config
from mds_logging import get_logger
from mds_logging.schema import build_log_entry
from src.drone_api_routes import (
    DRONE_ULOG_DOWNLOAD_CONTENT_ROUTE_TEMPLATE,
    DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE,
    DRONE_ULOG_ERASE_ALL_ROUTE,
    DRONE_ULOG_FILES_ROUTE,
    DRONE_ULOG_FILE_SUMMARY_ROUTE_TEMPLATE,
    DRONE_ULOG_FILE_DOWNLOAD_ROUTE_TEMPLATE,
    DRONE_ULOG_POLICY_ROUTE,
)

logger = get_logger("log_proxy")

def _drone_api_port() -> int:
    raw_value = os.getenv("MDS_DRONE_API_PORT", os.getenv("MDS_DEFAULT_DRONE_API_PORT", "7070"))
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        logger.warning("Invalid MDS_DRONE_API_PORT=%r; using 7070", raw_value)
        return 7070


_TIMEOUT = 5.0  # seconds
_ULOG_TIMEOUT = 30.0  # seconds


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
    timeout: float | None = _TIMEOUT,
) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method,
                _build_drone_url(drone_ip, path),
                params=params,
                json=json_body,
            )
    except Exception as exc:
        raise DroneProxyUnavailableError(str(exc)) from exc

    if resp.status_code >= 400:
        raise DroneProxyResponseError(resp.status_code, _extract_error_detail(resp))
    return resp.json()


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

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(
                _build_drone_url(drone_ip, path),
                params=dict(params or {}),
            )
    except Exception as exc:
        raise DroneProxyUnavailableError(str(exc)) from exc

    if resp.status_code >= 400:
        raise DroneProxyResponseError(resp.status_code, _extract_error_detail(resp))
    payload = resp.json()
    if not isinstance(payload, dict):
        raise DroneProxyResponseError(502, "Drone proxy returned non-object JSON")
    return payload


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
    return await _request_json("GET", drone_ip, DRONE_ULOG_POLICY_ROUTE, timeout=_ULOG_TIMEOUT)


async def fetch_drone_ulog_files(drone_ip: str) -> dict:
    return await _request_json("GET", drone_ip, DRONE_ULOG_FILES_ROUTE, timeout=_ULOG_TIMEOUT)


async def fetch_drone_ulog_summary(drone_ip: str, log_id: int) -> dict:
    return await _request_json(
        "GET",
        drone_ip,
        DRONE_ULOG_FILE_SUMMARY_ROUTE_TEMPLATE.format(log_id=int(log_id)),
        timeout=float(os.getenv("MDS_ULOG_SUMMARY_TIMEOUT_SEC", "90")),
    )


async def create_drone_ulog_download_job(
    drone_ip: str,
    log_id: int,
    *,
    pos_id: int | None = None,
) -> dict:
    payload: dict[str, Any] = {}
    if pos_id is not None:
        payload["pos_id"] = int(pos_id)
    return await _request_json(
        "POST",
        drone_ip,
        DRONE_ULOG_FILE_DOWNLOAD_ROUTE_TEMPLATE.format(log_id=int(log_id)),
        json_body=payload,
        timeout=_ULOG_TIMEOUT,
    )


async def fetch_drone_ulog_download_job(drone_ip: str, job_id: str) -> dict:
    return await _request_json(
        "GET",
        drone_ip,
        DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE.format(job_id=job_id),
        timeout=_ULOG_TIMEOUT,
    )


async def delete_drone_ulog_download_job(drone_ip: str, job_id: str) -> dict:
    return await _request_json(
        "DELETE",
        drone_ip,
        DRONE_ULOG_DOWNLOAD_JOB_ROUTE_TEMPLATE.format(job_id=job_id),
        timeout=_ULOG_TIMEOUT,
    )


async def erase_all_drone_ulogs(drone_ip: str) -> dict:
    return await _request_json("POST", drone_ip, DRONE_ULOG_ERASE_ALL_ROUTE, timeout=_ULOG_TIMEOUT)


async def open_drone_ulog_download_stream(drone_ip: str, job_id: str) -> tuple[httpx.AsyncClient, httpx.Response]:
    client = httpx.AsyncClient(timeout=None)
    request = client.build_request(
        "GET",
        _build_drone_url(
            drone_ip,
            DRONE_ULOG_DOWNLOAD_CONTENT_ROUTE_TEMPLATE.format(job_id=job_id),
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
