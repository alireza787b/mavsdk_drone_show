"""Runtime environment and mode resolution helpers."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from src.settings.env_files import read_env_assignments

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_ENV_PATH = Path("/etc/mds/local.env")
DEFAULT_NODE_IDENTITY_PATH = Path("/etc/mds/node_identity.json")

_LOCAL_ENV_PRELOADED = False
_LOCAL_ENV_PRELOADED_PATH: Path | None = None
_LOCAL_ENV_INJECTED_VALUES: dict[str, str] = {}


def get_local_env_path() -> Path:
    return Path(os.environ.get("MDS_LOCAL_ENV_FILE", str(DEFAULT_LOCAL_ENV_PATH)))


def get_node_identity_path() -> Path:
    return Path(os.environ.get("MDS_NODE_IDENTITY_FILE", str(DEFAULT_NODE_IDENTITY_PATH)))


def preload_local_env(log: logging.Logger | None = None) -> Path:
    """Load /etc/mds/local.env into os.environ without overriding process env."""
    global _LOCAL_ENV_PRELOADED, _LOCAL_ENV_PRELOADED_PATH, _LOCAL_ENV_INJECTED_VALUES

    target_logger = log or logger
    env_path = get_local_env_path()

    if _LOCAL_ENV_PRELOADED and _LOCAL_ENV_PRELOADED_PATH == env_path:
        return env_path

    if _LOCAL_ENV_PRELOADED_PATH is not None and _LOCAL_ENV_PRELOADED_PATH != env_path:
        for key, injected_value in list(_LOCAL_ENV_INJECTED_VALUES.items()):
            if os.environ.get(key) == injected_value:
                os.environ.pop(key, None)
        _LOCAL_ENV_INJECTED_VALUES = {}

    if env_path.exists():
        try:
            for key, value in read_env_assignments(env_path).items():
                if key not in os.environ:
                    os.environ[key] = value
                    _LOCAL_ENV_INJECTED_VALUES[key] = value
            target_logger.debug("Loaded local config from %s", env_path)
        except Exception as exc:  # pragma: no cover - defensive log path
            target_logger.warning("Failed to load local config from %s: %s", env_path, exc)

    _LOCAL_ENV_PRELOADED = True
    _LOCAL_ENV_PRELOADED_PATH = env_path
    return env_path


def reset_preloaded_local_env_state() -> None:
    """Reset preload state and remove injected env values.

    This is intended for tests so each test can exercise the runtime-env
    resolution logic without inheriting mutated process state from earlier
    env-file-backed calls.
    """
    global _LOCAL_ENV_PRELOADED, _LOCAL_ENV_PRELOADED_PATH, _LOCAL_ENV_INJECTED_VALUES

    for key, injected_value in list(_LOCAL_ENV_INJECTED_VALUES.items()):
        if os.environ.get(key) == injected_value:
            os.environ.pop(key, None)

    _LOCAL_ENV_PRELOADED = False
    _LOCAL_ENV_PRELOADED_PATH = None
    _LOCAL_ENV_INJECTED_VALUES = {}


@dataclass(frozen=True)
class RuntimeModeInfo:
    """Resolved runtime mode and its provenance."""

    mode: str
    sim_mode: bool
    source: str


def _normalize_runtime_mode(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized == "real":
        return "real"
    if normalized == "sitl":
        return "sitl"
    return None


def resolve_runtime_mode() -> RuntimeModeInfo:
    """
    Resolve canonical runtime mode.

    Priority:
    1. MDS_MODE
    2. default sitl
    """

    preload_local_env()

    env_mode = _normalize_runtime_mode(os.environ.get("MDS_MODE"))
    if env_mode:
        return RuntimeModeInfo(mode=env_mode, sim_mode=(env_mode == "sitl"), source="env:MDS_MODE")

    raw_env_mode = os.environ.get("MDS_MODE")
    if raw_env_mode:
        logger.warning("Invalid MDS_MODE=%r; defaulting to sitl", raw_env_mode)

    return RuntimeModeInfo(mode="sitl", sim_mode=True, source="default:sitl")
