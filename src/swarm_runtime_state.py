import json
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, Optional

from mds_logging import get_logger


logger = get_logger("swarm_runtime_state")

_ENV_PATH = "MDS_SWARM_RUNTIME_ASSIGNMENT_PATH"
_DEFAULT_FILENAME = "smart_swarm_assignment.json"


def get_runtime_assignment_path() -> Path:
    override = os.getenv(_ENV_PATH)
    if override:
        return Path(override)

    project_root = Path(__file__).resolve().parent.parent
    return project_root / "logs" / "runtime" / _DEFAULT_FILENAME


def build_runtime_swarm_assignment(
    hw_id: Any,
    assignment: Optional[Dict[str, Any]],
    *,
    force_follow: Optional[Any] = None,
    session_id: Optional[str] = None,
    active: Optional[bool] = None,
) -> Dict[str, Any]:
    """Canonicalize a live Smart Swarm assignment for cross-process consumers."""

    source = assignment or {}
    follow_value = force_follow if force_follow is not None else source.get("follow", 0)

    payload = {
        "hw_id": int(hw_id),
        "follow": int(follow_value or 0),
        "offset_x": float(source.get("offset_x", 0.0) or 0.0),
        "offset_y": float(source.get("offset_y", 0.0) or 0.0),
        "offset_z": float(source.get("offset_z", 0.0) or 0.0),
        "frame": str(source.get("frame", "body") or "body").lower(),
    }
    if session_id or active is not None:
        payload.update({"schema_version": 2, "session_id": str(session_id or source.get("session_id") or "").strip() or None,
                       "active": bool(active)})
    return payload


def write_runtime_swarm_assignment(assignment: Optional[Dict[str, Any]]) -> None:
    """Persist the latest live Smart Swarm assignment for local cross-process readers."""
    path = get_runtime_assignment_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {"assignment": assignment or {}, "owner_pid": os.getpid(),
               "updated_monotonic": time.monotonic()}

    with NamedTemporaryFile("w", dir=path.parent, prefix=path.name, suffix=".tmp", delete=False) as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)

    temp_path.replace(path)


def clear_runtime_swarm_assignment(*, session_id: Optional[str] = None, phase: Optional[str] = None) -> bool:
    """Mark the runtime assignment inactive without deleting diagnostics.

    Readers can distinguish a saved topology from a live process after a
    restart or external pilot takeover.  A session guard prevents an older
    process from clearing a newer assignment during concurrent recovery.
    """
    current = read_runtime_swarm_assignment()
    if not current:
        return False
    if session_id and str(current.get("session_id") or "") != str(session_id):
        return False
    current = dict(current)
    current["active"] = False
    if phase is not None:
        current["phase"] = phase
    current["ended_at_ms"] = int(time.time() * 1000)
    write_runtime_swarm_assignment(current)
    return True


def read_runtime_swarm_assignment(*, active_only: bool = False) -> Optional[Dict[str, Any]]:
    """Read the latest persisted live Smart Swarm assignment, if present."""
    path = get_runtime_assignment_path()
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        logger.debug("Failed to read runtime swarm assignment from %s: %s", path, exc)
        return None

    assignment = payload.get("assignment") if isinstance(payload, dict) else None
    if not isinstance(assignment, dict) or not assignment:
        return None
    if active_only:
        if assignment.get("active") is not True:
            return None
        try:
            age = time.monotonic() - float(payload["updated_monotonic"])
            if not 0 <= age <= 10.0:
                return None
            os.kill(int(payload["owner_pid"]), 0)
        except (KeyError, TypeError, ValueError, OSError):
            return None
    return assignment
