"""Bounded JSONL pages with query-bound, append-stable continuations.

Tokens are process-local: restart/rotation requires Refresh, never another
file silently occupying an old view. Appends are excluded by a pinned byte end.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone

from mds_logging.session import _resolve_session_filepath

DEFAULT_PAGE_LINES = 500
MAX_PAGE_LINES = 2000
MAX_RECORD_BYTES = 256 * 1024
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_SCAN_BYTES = 16 * 1024 * 1024
_TOKEN_KEY = secrets.token_bytes(32)
_LEVELS = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}


class LogQueryError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _timestamp(value):
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise LogQueryError("Use a valid ISO date/time. Times without an offset are interpreted as UTC.")


def normalize_query(*, level=None, component=None, search=None, since=None, until=None):
    if level and level not in _LEVELS:
        raise LogQueryError("Unknown log severity.")
    if component is not None and (not isinstance(component, str) or len(component) > 128):
        raise LogQueryError("Component filter exceeds 128 characters.")
    if search is not None and (not isinstance(search, str) or len(search) > 256):
        raise LogQueryError("Search exceeds 256 characters.")
    start, end = _timestamp(since), _timestamp(until)
    if start and end and end < start:
        raise LogQueryError("End time must be after start time.")
    return {"level": level or None, "component": component or None,
            "search": search.casefold() if search else None,
            "since": start.isoformat() if start else None,
            "until": end.isoformat() if end else None}


def _sign(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(hmac.digest(_TOKEN_KEY, raw, "sha256") + raw).decode().rstrip("=")


def _decode(token):
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError()
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        if not hmac.compare_digest(raw[:32], hmac.digest(_TOKEN_KEY, raw[32:], "sha256")):
            raise ValueError()
        payload = json.loads(raw[32:])
        if not isinstance(payload, dict):
            raise ValueError()
        return payload
    except Exception as exc:
        raise LogQueryError("This session view expired or changed. Refresh the session.", 409) from exc


def _edges(handle, size):
    handle.seek(0)
    first = handle.read(min(size, 4096))
    handle.seek(max(0, size - 4096))
    last = handle.read(min(size, 4096))
    return hashlib.sha256(first + last).hexdigest()


def _matches(entry, query):
    if query["level"] and _LEVELS.get(entry.get("level"), -1) < _LEVELS[query["level"]]:
        return False
    if query["component"] and entry.get("component") != query["component"]:
        return False
    if query["since"] or query["until"]:
        try:
            stamp = _timestamp(entry.get("ts"))
        except LogQueryError:
            return False
        if stamp is None:
            return False
        if query["since"] and stamp <= _timestamp(query["since"]):
            return False
        if query["until"] and stamp > _timestamp(query["until"]):
            return False
    return not query["search"] or query["search"] in json.dumps(entry, ensure_ascii=False).casefold()


def _invalid_constant(value):
    raise ValueError(f"Non-finite JSON value: {value}")


def read_session_page(log_dir, session_id, *, level=None, component=None, limit=None,
                      offset=0, since=None, until=None, search=None, cursor=None):
    limit = DEFAULT_PAGE_LINES if limit is None else limit
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_LINES:
        raise LogQueryError(f"Page limit must be between 1 and {MAX_PAGE_LINES}.")
    if type(offset) is not int or not 0 <= offset <= 100000:
        raise LogQueryError("Offset must be between 0 and 100000.")
    query = normalize_query(level=level, component=component, search=search, since=since, until=until)
    path = _resolve_session_filepath(log_dir, session_id)
    if path is None:
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LogQueryError("Session file is unavailable. Refresh the session.", 409) from exc
    with os.fdopen(fd, "rb") as handle:
        stat = os.fstat(handle.fileno())
        current = {"dev": stat.st_dev, "ino": stat.st_ino, "size": stat.st_size}
        if cursor:
            pin = _decode(cursor)
            if pin.get("session") != session_id or pin.get("query") != query:
                raise LogQueryError("The source or filters changed. Refresh the session.", 409)
            if any(pin[key] != current[key] for key in ("dev", "ino")) or current["size"] < pin["size"]:
                raise LogQueryError("Session rotated or was truncated. Refresh the session.", 409)
            if pin["edges"] != _edges(handle, pin["size"]):
                raise LogQueryError("Session contents changed. Refresh the session.", 409)
        else:
            pin = {**current, "session": session_id, "query": query, "position": 0, "skip": offset,
                   "edges": _edges(handle, current["size"])}
        start = pin["position"]
        handle.seek(start)
        lines, positions = [], []
        malformed = oversized = incomplete = used = 0
        while handle.tell() < pin["size"] and len(lines) < limit and handle.tell() - start < MAX_SCAN_BYTES:
            position = handle.tell()
            line = handle.readline(min(MAX_RECORD_BYTES + 1, pin["size"] - position))
            if len(line) > MAX_RECORD_BYTES:
                oversized += 1
                while line and not line.endswith(b"\n") and handle.tell() < pin["size"]:
                    if handle.tell() - position >= MAX_SCAN_BYTES:
                        raise LogQueryError("A record exceeds the viewer limit. Export the session to inspect it.", 413)
                    line = handle.readline(min(MAX_RECORD_BYTES, pin["size"] - handle.tell()))
                continue
            if not line.strip():
                continue
            try:
                entry = json.loads(line, parse_constant=_invalid_constant)
                if not isinstance(entry, dict) or ("level" in entry and not isinstance(entry["level"], str)):
                    raise ValueError()
            except (ValueError, UnicodeDecodeError, RecursionError):
                if not line.endswith(b"\n") and handle.tell() == pin["size"]:
                    incomplete += 1
                else:
                    malformed += 1
                continue
            if not _matches(entry, query):
                continue
            if pin["skip"]:
                pin["skip"] -= 1
                continue
            cost = len(json.dumps(entry, ensure_ascii=False).encode())
            if used + cost > MAX_PAGE_BYTES:
                handle.seek(position)
                break
            used += cost
            lines.append(entry)
            positions.append(position)
        pin["position"] = handle.tell()
        more = pin["position"] < pin["size"]
        identity = {key: pin[key] for key in ("session", "dev", "ino", "size", "edges")}
        return {"session_id": session_id, "count": len(lines), "lines": lines,
                "schema_version": "1.1", "entry_offsets": positions,
                "snapshot_id": hashlib.sha256(_sign(identity).encode()).hexdigest()[:24],
                "next_cursor": _sign(pin) if more else None, "has_more": more,
                "coverage": {"scope": "page", "byte_start": start, "byte_end": pin["position"],
                             "snapshot_size_bytes": pin["size"], "source_size_bytes": current["size"],
                             "malformed_records": malformed, "oversized_records": oversized,
                             "incomplete_records": incomplete}}
