"""
GCS Log API Router — REST + SSE endpoints for log access.

Endpoints:
  GET  /api/logs/sources                  — registered components
  GET  /api/logs/sessions                 — list GCS sessions
  GET  /api/logs/sessions/{session_id}    — retrieve session content
  GET  /api/logs/stream                   — real-time SSE stream
  POST /api/logs/frontend                 — receive frontend error reports

Reference: docs/guides/logging-system.md
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from mds_logging.api_schemas import (
    FrontendLogReportRequest,
    LogConfigUpdateRequest,
    LogExportRequest,
    LogSessionContentResponse,
    LogSessionsResponse,
    LogSourcesResponse,
    LogStatusResponse,
    OnboardUlogDownloadJobResponse,
    OnboardUlogEraseAllResponse,
    OnboardUlogJobDeleteResponse,
    OnboardUlogListResponse,
    OnboardUlogPolicyResponse,
)
from mds_logging.registry import get_registry
from mds_logging.session import get_session_filepath, list_sessions, read_session_lines
from mds_logging.watcher import get_watcher, LogWatcher
from mds_logging.constants import get_log_dir
from mds_logging import get_logger

logger = get_logger("log_api")


def create_log_router(
    log_dir: str | None = None,
    watcher: LogWatcher | None = None,
    puller=None,
) -> APIRouter:
    """Create the log API router. Accepts overrides for testing."""

    _log_dir = log_dir or get_log_dir()
    _watcher = watcher or get_watcher()
    _puller = puller  # BackgroundLogPuller instance (injected from app_fastapi)

    router = APIRouter(prefix="/api/logs", tags=["Logs"])

    def _resolve_existing_session_file(session_id: str) -> str:
        try:
            filepath = get_session_filepath(_log_dir, session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found") from exc
        if not os.path.isfile(filepath):
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return filepath

    @router.get("/sources", response_model=LogSourcesResponse)
    async def get_sources():
        """List all registered log source components."""
        return {"components": get_registry()}

    @router.get("/sessions", response_model=LogSessionsResponse)
    async def get_sessions():
        """List GCS log sessions, newest first."""
        sessions = list_sessions(_log_dir)
        return {"sessions": sessions}

    @router.get("/sessions/{session_id}", response_model=LogSessionContentResponse)
    async def get_session(
        session_id: str,
        level: Optional[str] = None,
        component: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        since: Optional[str] = None,
    ):
        """Retrieve filtered JSONL content from a GCS log session."""
        lines = read_session_lines(
            _log_dir, session_id,
            level=level, component=component, limit=limit, offset=offset,
            since=since,
        )
        if lines is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return {"session_id": session_id, "count": len(lines), "lines": lines}

    @router.get("/stream")
    async def stream_logs(
        level: Optional[str] = None,
        component: Optional[str] = None,
        source: Optional[str] = None,
        drone_id: Optional[int] = None,
    ):
        """Stream GCS logs in real-time via SSE."""
        async def event_generator():
            async for entry in _watcher.subscribe(
                level=level, component=component, source=source, drone_id=drone_id,
            ):
                yield f"data: {json.dumps(entry)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/frontend", response_model=LogStatusResponse)
    async def receive_frontend_report(report: FrontendLogReportRequest):
        """Receive error/log reports from the React frontend."""
        level = report.level.upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise HTTPException(status_code=400, detail=f"Invalid log level: '{level}'")
        component = report.component or "frontend"
        msg = report.msg
        extra = report.extra
        fe_logger = get_logger(component)
        log_level = getattr(logging, level)
        fe_logger.log(log_level, msg, extra={"mds_extra": extra})
        return {"status": "received"}

    # --- Export endpoint ---

    @router.post("/export")
    async def export_sessions(request: LogExportRequest):
        """Export one or more sessions as JSONL or ZIP."""
        import io
        import zipfile
        from fastapi.responses import Response

        session_ids = request.session_ids
        fmt = request.format

        if not session_ids:
            raise HTTPException(status_code=400, detail="session_ids required")

        # Verify all sessions exist
        for sid in session_ids:
            _resolve_existing_session_file(sid)

        if fmt == "zip" or len(session_ids) > 1:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for sid in session_ids:
                    filepath = _resolve_existing_session_file(sid)
                    zf.write(filepath, f"{sid}.jsonl")
            buf.seek(0)
            return Response(
                content=buf.getvalue(),
                media_type="application/zip",
                headers={"Content-Disposition": "attachment; filename=mds_logs_export.zip"},
            )
        else:
            filepath = _resolve_existing_session_file(session_ids[0])
            with open(filepath, "r") as f:
                content = f.read()
            return Response(
                content=content,
                media_type="application/x-ndjson",
                headers={"Content-Disposition": f"attachment; filename={session_ids[0]}.jsonl"},
            )

    # --- Drone proxy endpoints ---

    @router.post("/drone/{drone_id}/export")
    async def export_drone_sessions(drone_id: int, request: LogExportRequest):
        """Export one or more sessions from a specific drone as JSONL or ZIP."""
        import io
        import zipfile
        from fastapi.responses import Response

        from log_proxy import resolve_drone_ip, fetch_drone_session_content

        session_ids = request.session_ids
        fmt = request.format

        if not session_ids:
            raise HTTPException(status_code=400, detail="session_ids required")

        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")

        session_payloads: list[tuple[str, list[dict]]] = []
        for sid in session_ids:
            result = await fetch_drone_session_content(ip, sid)
            if result is None:
                raise HTTPException(status_code=502, detail=f"Drone {drone_id} unreachable")
            session_payloads.append((sid, result.get("lines", [])))

        def _to_jsonl(lines: list[dict]) -> str:
            if not lines:
                return ""
            return "".join(f"{json.dumps(line)}\n" for line in lines)

        if fmt == "zip" or len(session_ids) > 1:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for sid, lines in session_payloads:
                    zf.writestr(f"{sid}.jsonl", _to_jsonl(lines))
            buf.seek(0)
            return Response(
                content=buf.getvalue(),
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename=drone_{drone_id}_logs_export.zip"},
            )

        sid, lines = session_payloads[0]
        return Response(
            content=_to_jsonl(lines),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f"attachment; filename={sid}.jsonl"},
        )

    @router.get("/drone/{drone_id}/sessions", response_model=LogSessionsResponse)
    async def get_drone_sessions(drone_id: int):
        """List log sessions on a specific drone (proxied)."""
        from log_proxy import resolve_drone_ip, fetch_drone_sessions
        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")
        result = await fetch_drone_sessions(ip)
        if result is None:
            raise HTTPException(status_code=502, detail=f"Drone {drone_id} unreachable")
        return result

    @router.get("/drone/{drone_id}/sessions/{session_id}", response_model=LogSessionContentResponse)
    async def get_drone_session(
        drone_id: int,
        session_id: str,
        level: Optional[str] = None,
        component: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        since: Optional[str] = None,
    ):
        """Retrieve session content from a specific drone (proxied)."""
        from log_proxy import resolve_drone_ip, fetch_drone_session_content
        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")
        result = await fetch_drone_session_content(
            ip, session_id, level=level, component=component, limit=limit, offset=offset,
            since=since,
        )
        if result is None:
            raise HTTPException(status_code=502, detail=f"Drone {drone_id} unreachable")
        return result

    @router.get("/drone/{drone_id}/stream")
    async def stream_drone(
        drone_id: int,
        level: Optional[str] = None,
        component: Optional[str] = None,
        source: Optional[str] = None,
    ):
        """Proxy real-time log stream from a specific drone via SSE."""
        from log_proxy import resolve_drone_ip, stream_drone_logs
        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")
        return StreamingResponse(
            stream_drone_logs(ip, drone_id=drone_id, level=level, component=component, source=source),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/drone/{drone_id}/ulog/policy", response_model=OnboardUlogPolicyResponse)
    async def get_drone_ulog_policy(drone_id: int):
        """Return the onboard ULog maintenance policy for a specific drone."""
        from log_proxy import (
            DroneProxyResponseError,
            DroneProxyUnavailableError,
            fetch_drone_ulog_policy,
            resolve_drone_ip,
        )

        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")
        try:
            return await fetch_drone_ulog_policy(ip)
        except DroneProxyUnavailableError as exc:
            raise HTTPException(status_code=502, detail=f"Drone {drone_id} unreachable: {exc}") from exc
        except DroneProxyResponseError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @router.get("/drone/{drone_id}/ulog/files", response_model=OnboardUlogListResponse)
    async def list_drone_ulog_files(drone_id: int):
        """List onboard PX4 ULog files for a specific drone."""
        from log_proxy import (
            DroneProxyResponseError,
            DroneProxyUnavailableError,
            fetch_drone_ulog_files,
            resolve_drone_ip,
        )

        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")
        try:
            return await fetch_drone_ulog_files(ip)
        except DroneProxyUnavailableError as exc:
            raise HTTPException(status_code=502, detail=f"Drone {drone_id} unreachable: {exc}") from exc
        except DroneProxyResponseError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @router.post(
        "/drone/{drone_id}/ulog/files/{log_id}/download",
        response_model=OnboardUlogDownloadJobResponse,
    )
    async def create_drone_ulog_download_job_route(drone_id: int, log_id: int):
        """Start a staged onboard ULog download job on a specific drone."""
        from log_proxy import (
            DroneProxyResponseError,
            DroneProxyUnavailableError,
            create_drone_ulog_download_job as create_job,
            resolve_drone_ip,
        )

        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")
        try:
            return await create_job(ip, log_id)
        except DroneProxyUnavailableError as exc:
            raise HTTPException(status_code=502, detail=f"Drone {drone_id} unreachable: {exc}") from exc
        except DroneProxyResponseError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @router.get(
        "/drone/{drone_id}/ulog/downloads/{job_id}",
        response_model=OnboardUlogDownloadJobResponse,
    )
    async def get_drone_ulog_download_job(drone_id: int, job_id: str):
        """Fetch status for a staged onboard ULog download job."""
        from log_proxy import (
            DroneProxyResponseError,
            DroneProxyUnavailableError,
            fetch_drone_ulog_download_job,
            resolve_drone_ip,
        )

        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")
        try:
            return await fetch_drone_ulog_download_job(ip, job_id)
        except DroneProxyUnavailableError as exc:
            raise HTTPException(status_code=502, detail=f"Drone {drone_id} unreachable: {exc}") from exc
        except DroneProxyResponseError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @router.delete(
        "/drone/{drone_id}/ulog/downloads/{job_id}",
        response_model=OnboardUlogJobDeleteResponse,
    )
    async def delete_drone_ulog_download_job_route(drone_id: int, job_id: str):
        """Delete a staged onboard ULog download job and staged file."""
        from log_proxy import (
            DroneProxyResponseError,
            DroneProxyUnavailableError,
            delete_drone_ulog_download_job as delete_job,
            resolve_drone_ip,
        )

        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")
        try:
            return await delete_job(ip, job_id)
        except DroneProxyUnavailableError as exc:
            raise HTTPException(status_code=502, detail=f"Drone {drone_id} unreachable: {exc}") from exc
        except DroneProxyResponseError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @router.get("/drone/{drone_id}/ulog/downloads/{job_id}/content")
    async def download_drone_ulog_content(drone_id: int, job_id: str):
        """Proxy staged onboard ULog file bytes from drone to browser."""
        from log_proxy import (
            DroneProxyResponseError,
            DroneProxyUnavailableError,
            open_drone_ulog_download_stream,
            resolve_drone_ip,
        )

        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")

        try:
            client, upstream = await open_drone_ulog_download_stream(ip, job_id)
        except DroneProxyUnavailableError as exc:
            raise HTTPException(status_code=502, detail=f"Drone {drone_id} unreachable: {exc}") from exc
        except DroneProxyResponseError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

        async def iter_content():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        response_headers = {}
        content_disposition = upstream.headers.get("content-disposition")
        if content_disposition:
            response_headers["Content-Disposition"] = content_disposition
        content_length = upstream.headers.get("content-length")
        if content_length:
            response_headers["Content-Length"] = content_length

        return StreamingResponse(
            iter_content(),
            media_type=upstream.headers.get("content-type", "application/octet-stream"),
            headers=response_headers,
        )

    @router.post("/drone/{drone_id}/ulog/erase-all", response_model=OnboardUlogEraseAllResponse)
    async def erase_all_drone_ulogs_route(drone_id: int):
        """Erase all onboard PX4 ULogs on a specific drone."""
        from log_proxy import (
            DroneProxyResponseError,
            DroneProxyUnavailableError,
            erase_all_drone_ulogs as erase_all,
            resolve_drone_ip,
        )

        ip = resolve_drone_ip(drone_id)
        if ip is None:
            raise HTTPException(status_code=404, detail=f"Drone {drone_id} not found in config")
        try:
            return await erase_all(ip)
        except DroneProxyUnavailableError as exc:
            raise HTTPException(status_code=502, detail=f"Drone {drone_id} unreachable: {exc}") from exc
        except DroneProxyResponseError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    # --- Runtime config toggle ---

    @router.post("/config", response_model=LogStatusResponse)
    async def update_log_config(config: LogConfigUpdateRequest):
        """Update runtime log configuration (e.g., background pull toggle)."""
        if _puller is not None and config.background_pull is not None:
            _puller.set_enabled(config.background_pull)
        return {"status": "updated"}

    return router
