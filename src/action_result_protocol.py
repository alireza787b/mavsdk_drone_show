"""Versioned terminal-result protocol for short-lived action processes.

The preferred transport is a dedicated, inherited file descriptor named by
``MDS_ACTION_RESULT_FD``.  A single bounded JSON object is written to that
descriptor when the child exits.  ``MDS_ACTION_RESULT=...`` on stdout remains
as a compatibility transport for direct/manual execution and rolling upgrades;
it is deliberately strict and bounded and must not be treated as general log
scraping.

Human-readable stdout/stderr remain diagnostics.  They are never authoritative
for action success or the operator-facing root cause when a valid result is
available.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional


SCHEMA_VERSION = 1
ACTION_RESULT_FD_ENV = "MDS_ACTION_RESULT_FD"
ACTION_RESULT_SENTINEL = "MDS_ACTION_RESULT="
MAX_RESULT_BYTES = 4096
MAX_COMPAT_SCAN_BYTES = 64 * 1024
MAX_OPERATOR_MESSAGE_CHARS = 500
MAX_CODE_CHARS = 64
MAX_PHASE_CHARS = 64
MAX_MAPPING_ITEMS = 16
MAX_SEQUENCE_ITEMS = 16
MAX_VALUE_CHARS = 256

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_PHASE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_REQUIRED_FIELDS = {
    "schema_version",
    "success",
    "code",
    "phase",
    "operator_message",
    "retryable",
    "evidence",
    "final_vehicle_state",
}


class ActionResultProtocolError(ValueError):
    """Raised when a child terminal result violates the protocol."""


@dataclass(frozen=True)
class TerminalActionResult:
    """The only authoritative terminal result emitted by ``actions.py``."""

    schema_version: int
    success: bool
    code: str
    phase: str
    operator_message: str
    retryable: bool
    evidence: dict[str, Any]
    final_vehicle_state: Optional[dict[str, Any]]


def _sanitize_text(value: Any, *, limit: int) -> str:
    text = str(value or "")
    # Keep reports single-line and remove terminal/control-sequence building
    # blocks.  Ordinary whitespace is normalized for stable operator output.
    text = "".join(character if character >= " " else " " for character in text)
    text = " ".join(text.split())
    return text[:limit]


def _sanitize_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 2:
        return _sanitize_text(value, limit=MAX_VALUE_CHARS)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _sanitize_text(value, limit=MAX_VALUE_CHARS)
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:MAX_MAPPING_ITEMS]:
            key = _sanitize_text(raw_key, limit=64)
            if key:
                sanitized[key] = _sanitize_json_value(raw_value, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_json_value(item, depth=depth + 1)
            for item in list(value)[:MAX_SEQUENCE_ITEMS]
        ]
    return _sanitize_text(value, limit=MAX_VALUE_CHARS)


def make_terminal_result(
    *,
    success: bool,
    code: str,
    phase: str,
    operator_message: str,
    retryable: bool = False,
    evidence: Optional[Mapping[str, Any]] = None,
    final_vehicle_state: Optional[Mapping[str, Any]] = None,
) -> TerminalActionResult:
    """Build and validate a bounded version-1 terminal result."""

    normalized_code = _sanitize_text(code, limit=MAX_CODE_CHARS)
    normalized_phase = _sanitize_text(phase, limit=MAX_PHASE_CHARS).lower()
    normalized_message = _sanitize_text(
        operator_message,
        limit=MAX_OPERATOR_MESSAGE_CHARS,
    )
    if not _CODE_RE.fullmatch(normalized_code):
        raise ActionResultProtocolError(f"invalid result code: {normalized_code!r}")
    if not _PHASE_RE.fullmatch(normalized_phase):
        raise ActionResultProtocolError(f"invalid result phase: {normalized_phase!r}")
    if not normalized_message:
        raise ActionResultProtocolError("operator_message must not be empty")

    sanitized_evidence = _sanitize_json_value(dict(evidence or {}))
    sanitized_state = (
        None
        if final_vehicle_state is None
        else _sanitize_json_value(dict(final_vehicle_state))
    )
    return TerminalActionResult(
        schema_version=SCHEMA_VERSION,
        success=bool(success),
        code=normalized_code,
        phase=normalized_phase,
        operator_message=normalized_message,
        retryable=bool(retryable),
        evidence=sanitized_evidence,
        final_vehicle_state=sanitized_state,
    )


def encode_terminal_result(result: TerminalActionResult) -> bytes:
    """Serialize one result as compact, newline-terminated UTF-8 JSON."""

    # Rebuild through the validator so manually-constructed dataclass values do
    # not bypass bounds or field normalization.
    validated = make_terminal_result(
        success=result.success,
        code=result.code,
        phase=result.phase,
        operator_message=result.operator_message,
        retryable=result.retryable,
        evidence=result.evidence,
        final_vehicle_state=result.final_vehicle_state,
    )
    payload = (
        json.dumps(
            asdict(validated),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    if len(payload) > MAX_RESULT_BYTES:
        raise ActionResultProtocolError("terminal result exceeds protocol byte limit")
    return payload


def decode_terminal_result(payload: bytes | str) -> TerminalActionResult:
    """Parse one strict, bounded result payload."""

    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if not raw or len(raw) > MAX_RESULT_BYTES:
        raise ActionResultProtocolError("terminal result is empty or oversized")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ActionResultProtocolError("terminal result is not valid UTF-8") from exc
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ActionResultProtocolError("terminal result must contain exactly one line")
    try:
        document = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ActionResultProtocolError("terminal result is not valid JSON") from exc
    if not isinstance(document, dict) or set(document) != _REQUIRED_FIELDS:
        raise ActionResultProtocolError("terminal result fields do not match schema")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ActionResultProtocolError("unsupported terminal result schema version")
    if (
        type(document.get("success")) is not bool
        or type(document.get("retryable")) is not bool
    ):
        raise ActionResultProtocolError("success and retryable must be booleans")
    if not isinstance(document.get("evidence"), dict):
        raise ActionResultProtocolError("evidence must be an object")
    if document.get("final_vehicle_state") is not None and not isinstance(
        document.get("final_vehicle_state"), dict
    ):
        raise ActionResultProtocolError("final_vehicle_state must be an object or null")

    # make_terminal_result applies the same validation and defensive bounds on
    # received strings and nested evidence.
    return make_terminal_result(
        success=document["success"],
        code=document["code"],
        phase=document["phase"],
        operator_message=document["operator_message"],
        retryable=document["retryable"],
        evidence=document["evidence"],
        final_vehicle_state=document["final_vehicle_state"],
    )


def extract_terminal_result(
    *,
    dedicated_payload: bytes | str | None,
    stdout: bytes | str | None,
) -> Optional[TerminalActionResult]:
    """Prefer the dedicated channel, then try one stdout compatibility line."""

    if dedicated_payload:
        try:
            return decode_terminal_result(dedicated_payload)
        except ActionResultProtocolError:
            # A partial/broken dedicated write may accompany the complete
            # compatibility line.  Try that bounded transport before falling
            # back to explicitly-labelled legacy diagnostics.
            pass

    stdout_raw = (
        stdout.encode("utf-8") if isinstance(stdout, str) else bytes(stdout or b"")
    )
    scan = stdout_raw[-MAX_COMPAT_SCAN_BYTES:]
    text = scan.decode("utf-8", errors="replace")
    candidates = [
        line[len(ACTION_RESULT_SENTINEL) :]
        for line in text.splitlines()
        if line.startswith(ACTION_RESULT_SENTINEL)
    ]
    if len(candidates) != 1:
        return None
    try:
        return decode_terminal_result(candidates[0])
    except ActionResultProtocolError:
        return None


def emit_terminal_result(result: TerminalActionResult) -> None:
    """Emit exactly one authoritative result through the best available channel."""

    payload = encode_terminal_result(result)
    fd_text = os.environ.get(ACTION_RESULT_FD_ENV, "").strip()
    if fd_text:
        try:
            result_fd = int(fd_text)
            if result_fd < 3:
                raise ValueError("reserved descriptor")
            view = memoryview(payload)
            while view:
                written = os.write(result_fd, view)
                if written <= 0:
                    raise OSError("terminal result write made no progress")
                view = view[written:]
            os.close(result_fd)
            return
        except (OSError, ValueError):
            # A rolling-upgrade/manual environment can provide a stale FD.
            # Emit the same result once through the compatibility transport.
            try:
                result_fd = int(fd_text)
                if result_fd >= 3:
                    os.close(result_fd)
            except (OSError, ValueError):
                pass

    line = ACTION_RESULT_SENTINEL.encode("ascii") + payload
    sys_stdout = sys.stdout
    sys_stdout.buffer.write(line) if hasattr(
        sys_stdout, "buffer"
    ) else sys_stdout.write(line.decode("utf-8"))
    sys_stdout.flush()


def read_bounded_result_fd(result_fd: int) -> bytes:
    """Read and close a result pipe without allowing unbounded child output."""

    chunks: list[bytes] = []
    remaining = MAX_RESULT_BYTES + 1
    try:
        while remaining > 0:
            chunk = os.read(result_fd, min(remaining, 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        try:
            os.close(result_fd)
        except OSError:
            pass
    return b"".join(chunks)


def format_legacy_diagnostics(
    *,
    stdout: bytes | str | None,
    stderr: bytes | str | None,
    limit: int = 500,
) -> str:
    """Return bounded, labelled diagnostics; never infer a root cause from them."""

    def _decode(value: bytes | str | None) -> str:
        if isinstance(value, bytes):
            value = value[-MAX_COMPAT_SCAN_BYTES:].decode("utf-8", errors="replace")
        return _sanitize_text(value or "", limit=max(1, limit // 2))

    stdout_text = _decode(stdout)
    stderr_text = _decode(stderr)
    parts = []
    if stdout_text:
        parts.append(f"Legacy stdout (diagnostic only): {stdout_text}")
    if stderr_text:
        parts.append(f"Legacy stderr (diagnostic only): {stderr_text}")
    return " | ".join(parts)[:limit]
