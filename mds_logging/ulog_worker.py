"""Isolated worker process for bounded PX4 ULog parsing."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


RESULT_PREFIX = "MDS_ULOG_SUMMARY_RESULT:"
DEFAULT_MAX_MEMORY_MB = 1024
DEFAULT_MAX_CPU_SECONDS = 60
DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_OPEN_FILES = 64


def _bounded_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        configured = int(os.getenv(name, default))
    except (TypeError, ValueError):
        configured = default
    return max(minimum, min(configured, maximum))


def _set_resource_limit(resource_module: Any, resource_name: str, value: int) -> None:
    resource_id = getattr(resource_module, resource_name, None)
    if resource_id is None:
        return
    try:
        _soft, hard = resource_module.getrlimit(resource_id)
        effective = value if hard == resource_module.RLIM_INFINITY else min(value, hard)
        resource_module.setrlimit(resource_id, (effective, effective))
    except (OSError, ValueError):
        pass


def _apply_resource_limits() -> None:
    try:
        import resource
    except ImportError:
        return

    memory_bytes = _bounded_env_int(
        "MDS_ULOG_SUMMARY_MAX_MEMORY_MB",
        DEFAULT_MAX_MEMORY_MB,
        minimum=128,
        maximum=4096,
    ) * 1024 * 1024
    cpu_seconds = _bounded_env_int(
        "MDS_ULOG_SUMMARY_MAX_CPU_SEC",
        DEFAULT_MAX_CPU_SECONDS,
        minimum=1,
        maximum=300,
    )
    output_bytes = _bounded_env_int(
        "MDS_ULOG_SUMMARY_MAX_OUTPUT_BYTES",
        DEFAULT_MAX_OUTPUT_BYTES,
        minimum=1024 * 1024,
        maximum=64 * 1024 * 1024,
    )
    open_files = _bounded_env_int(
        "MDS_ULOG_SUMMARY_MAX_OPEN_FILES",
        DEFAULT_MAX_OPEN_FILES,
        minimum=16,
        maximum=256,
    )
    _set_resource_limit(resource, "RLIMIT_AS", memory_bytes)
    _set_resource_limit(resource, "RLIMIT_CPU", cpu_seconds)
    _set_resource_limit(resource, "RLIMIT_FSIZE", output_bytes)
    _set_resource_limit(resource, "RLIMIT_NOFILE", open_files)
    _set_resource_limit(resource, "RLIMIT_CORE", 0)


def _apply_runtime_guards() -> None:
    """Prevent ordinary parser code from opening network or child-process paths."""

    os.umask(0o077)
    if sys.platform.startswith("linux"):
        try:
            import ctypes

            libc = ctypes.CDLL(None, use_errno=True)
            libc.prctl(38, 1, 0, 0, 0)  # PR_SET_NO_NEW_PRIVS
        except Exception:
            pass

    blocked_events = {
        "socket.__new__",
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.posix_spawnp",
    }

    def reject_external_io(event: str, _args: tuple[Any, ...]) -> None:
        if event in blocked_events:
            raise PermissionError(f"ULog parser worker blocked operation: {event}")

    sys.addaudithook(reject_external_io)


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(RESULT_PREFIX + json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        if not isinstance(request, dict):
            raise ValueError("worker request must be an object")
        path = str(request.get("path") or "").strip()
        if not path:
            raise ValueError("worker request path is required")
        source_metadata = request.get("source_metadata")
        if not isinstance(source_metadata, dict):
            source_metadata = {}
        max_bytes = request.get("max_bytes")
    except Exception as exc:
        _emit(
            {
                "ok": False,
                "code": "ulog_summary_worker_invalid_request",
                "http_status": 500,
                "error": str(exc)[:500],
            }
        )
        return 2

    _apply_resource_limits()
    _apply_runtime_guards()
    try:
        from mds_logging.ulog_analysis import summarize_ulog_file

        summary = summarize_ulog_file(
            path,
            source_metadata=source_metadata,
            max_bytes=max_bytes,
        )
    except MemoryError:
        _emit(
            {
                "ok": False,
                "code": "ulog_summary_memory_limit",
                "http_status": 413,
                "error": "ULog parser exceeded its memory limit",
            }
        )
        return 3
    except Exception as exc:
        _emit(
            {
                "ok": False,
                "code": "ulog_summary_worker_failed",
                "http_status": 500,
                "error": str(exc)[:500],
            }
        )
        return 4

    _emit({"ok": True, "summary": summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
