"""Bounded temporary exports, never a long-lived raw-log archive."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from mds_logging.session_query import LogQueryError, normalize_query, read_session_page

MAX_EXPORT_BYTES = 128 * 1024 * 1024
MIN_FREE_BYTES = 512 * 1024 * 1024
EXPORT_DEADLINE_SEC = 60
_slots = asyncio.Semaphore(2)
_reserved_bytes = 0


async def create_log_export(request, *, log_dir=None, drone_id=None, remote_page=None):
    """Materialize bounded JSONL/ZIP outside memory, before sending success.

    One reader contract serves local and remote sources. Every page is fetched;
    applying a page limit must never silently truncate a whole-session export.
    """
    global _reserved_bytes
    ids = request.session_ids
    if not ids or len(ids) != len(set(ids)):
        raise HTTPException(status_code=400, detail="Choose unique sessions to export.")
    filters = request.filters.model_dump(exclude_none=True) if request.filters else {}
    try:
        normalize_query(**filters)
    except LogQueryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if _slots.locked():
        raise HTTPException(status_code=429, detail="Log export is busy. Try again after the current export finishes.")
    await _slots.acquire()
    temp = None
    handed_off = False
    reservation = 0
    released = False
    def release_export():
        global _reserved_bytes
        nonlocal released
        if not released:
            released = True
            if temp is not None:
                temp.cleanup()
            _reserved_bytes -= reservation
            _slots.release()
    try:
        if shutil.disk_usage(tempfile.gettempdir()).free - _reserved_bytes < MIN_FREE_BYTES + 2 * MAX_EXPORT_BYTES:
            raise HTTPException(status_code=507, detail="Not enough temporary space to prepare this export.")
        reservation = 2 * MAX_EXPORT_BYTES
        _reserved_bytes += reservation
        temp = tempfile.TemporaryDirectory(prefix="mds-log-export-")
        directory = Path(temp.name)
        total = records = skipped = 0
        deadline = time.monotonic() + EXPORT_DEADLINE_SEC
        paths = []
        for session_id in ids:
            # Reject names before they can become an archive entry or disk path.
            from mds_logging.session import get_session_filepath
            try:
                get_session_filepath(directory, session_id)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail="Session not found.") from exc
            path = directory / f"{session_id}.jsonl"
            cursor, snapshot_id = None, None
            with path.open("wb") as output:
                while True:
                    if time.monotonic() > deadline:
                        raise HTTPException(status_code=504, detail="Export preparation timed out. Choose fewer sessions or a narrower time range.")
                    try:
                        if remote_page:
                            page = await remote_page(session_id, limit=500, cursor=cursor, **filters)
                            if page is None:
                                raise HTTPException(status_code=502, detail="Aircraft log source is unavailable.")
                            if page.get("schema_version") != "1.1":
                                raise HTTPException(status_code=409, detail="Update the companion to export complete paged sessions.")
                        else:
                            page = await asyncio.to_thread(read_session_page, log_dir, session_id,
                                                           limit=500, cursor=cursor, **filters)
                            if page is None:
                                raise HTTPException(status_code=404, detail="Session not found.")
                    except LogQueryError as exc:
                        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
                    if snapshot_id is not None and snapshot_id != page.get("snapshot_id"):
                        raise HTTPException(status_code=409, detail="Session changed during export. Refresh and try again.")
                    snapshot_id = page.get("snapshot_id")
                    content = b"".join((json.dumps(row, ensure_ascii=False) + "\n").encode() for row in page["lines"])
                    total += len(content)
                    if total > MAX_EXPORT_BYTES:
                        raise HTTPException(status_code=413, detail="Export exceeds 128 MiB. Choose fewer sessions or use a time filter.")
                    await asyncio.to_thread(output.write, content)
                    records += len(page["lines"])
                    coverage = page.get("coverage") or {}
                    skipped += sum(coverage.get(key, 0) for key in ("malformed_records", "oversized_records", "incomplete_records"))
                    next_cursor = page.get("next_cursor")
                    if not page.get("has_more"):
                        break
                    if not next_cursor or next_cursor == cursor:
                        raise HTTPException(status_code=502, detail="Log source did not provide a valid export continuation.")
                    cursor = next_cursor
            paths.append(path)
        zipped = request.format == "zip" or len(paths) > 1
        if zipped:
            artifact = directory / "logs.zip"
            def compress():
                with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in paths:
                        if time.monotonic() > deadline:
                            raise HTTPException(status_code=504, detail="Export compression timed out.")
                        archive.write(path, path.name)
            await asyncio.to_thread(compress)
        else:
            artifact = paths[0]
        scope = f"drone_{drone_id}" if drone_id is not None else "gcs"
        filename = f"mds_logs_{scope}.zip" if zipped else paths[0].name

        async def content_stream():
            try:
                with artifact.open("rb") as content:
                    while chunk := await asyncio.to_thread(content.read, 256 * 1024):
                        yield chunk
            finally:
                release_export()
        from starlette.background import BackgroundTask
        response = StreamingResponse(content_stream(),
            media_type="application/zip" if zipped else "application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{filename}"',
                     "Content-Length": str(artifact.stat().st_size),
                     "X-MDS-Export-Records": str(records), "X-MDS-Export-Skipped": str(skipped),
                     "X-MDS-Export-Scope": "filtered" if filters else "full-sessions"},
            background=BackgroundTask(release_export))
        handed_off = True
        return response
    finally:
        if not handed_off:
            release_export()
