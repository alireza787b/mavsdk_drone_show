"""Compact environment posture summaries for GCS and node diagnostics."""

from __future__ import annotations

from typing import Any

from src.settings.env_files import read_env_assignments
from src.settings.env_registry import EnvRegistryError, load_env_registry
from src.settings.identity import resolve_hw_id_info
from src.settings.runtime import get_local_env_path, get_node_identity_path, resolve_runtime_mode


def build_node_env_summary() -> dict[str, Any]:
    """Return a safe, read-only node env posture without exposing values."""
    registry = load_env_registry()
    local_env_path = get_local_env_path()
    node_identity_path = get_node_identity_path()
    values = read_env_assignments(local_env_path)
    classified = registry.classify_keys(values)
    runtime_mode = resolve_runtime_mode()
    identity = resolve_hw_id_info()
    node_keys = {entry.name for entry in registry.list_entries(scope="node", include_hidden=True)}
    configured_node_keys = sorted(key for key in classified["known"] if key in node_keys)

    warnings: list[str] = []
    if classified["unknown"]:
        warnings.append("Node local.env contains unregistered keys.")
    if classified["deprecated"]:
        warnings.append("Node local.env contains deprecated keys.")
    if identity.hw_id is None:
        warnings.append("Node hardware identity is unresolved.")

    return {
        "status_source": "registry",
        "registry_version": registry.version,
        "registry_hash": registry.content_hash,
        "local_env_path": str(local_env_path),
        "local_env_present": local_env_path.is_file(),
        "node_identity_path": str(node_identity_path),
        "node_identity_present": node_identity_path.is_file(),
        "runtime_mode": runtime_mode.mode,
        "runtime_mode_source": runtime_mode.source,
        "hw_id": identity.hw_id,
        "hw_id_source": identity.source,
        "configured_key_count": len(classified["known"]),
        "configured_node_key_count": len(configured_node_keys),
        "registered_node_key_count": len(node_keys),
        "unknown_keys": classified["unknown"],
        "deprecated_keys": classified["deprecated"],
        "warnings": warnings,
    }


def build_node_env_summary_safe() -> dict[str, Any]:
    """Best-effort wrapper used by node APIs so env diagnostics never break git status."""
    try:
        return build_node_env_summary()
    except (EnvRegistryError, OSError, ValueError) as exc:
        return {
            "status_source": "error",
            "registry_version": 0,
            "registry_hash": "",
            "local_env_path": str(get_local_env_path()),
            "local_env_present": False,
            "node_identity_path": str(get_node_identity_path()),
            "node_identity_present": False,
            "runtime_mode": "unknown",
            "runtime_mode_source": "error",
            "hw_id": None,
            "hw_id_source": "error",
            "configured_key_count": 0,
            "configured_node_key_count": 0,
            "registered_node_key_count": 0,
            "unknown_keys": [],
            "deprecated_keys": [],
            "warnings": [f"Node env summary unavailable: {exc}"],
        }
