"""Compact environment posture summaries for GCS and node diagnostics."""

from __future__ import annotations

from typing import Any

from src.settings.env_files import read_env_assignments
from src.settings.env_registry import EnvRegistryEntry, EnvRegistryError, coerce_value, load_env_registry, redact_value
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


def build_env_value_payload(entry: EnvRegistryEntry, values: dict[str, str]) -> dict[str, Any]:
    """Return one registry entry paired with a safe current value."""
    value_present = entry.name in values
    raw_value = values.get(entry.name)
    return {
        "name": entry.name,
        "title": entry.title,
        "scope": entry.scope,
        "domain": entry.domain,
        "source_of_truth": entry.source_of_truth,
        "value_type": entry.value_type,
        "value": redact_value(entry, raw_value) if value_present else None,
        "value_present": value_present,
        "secret": entry.secret,
        "secret_configured": bool(entry.secret and raw_value),
        "default": redact_value(entry, entry.default),
        "editable": entry.editable,
        "ui_visibility": entry.ui_visibility,
        "restart_required": entry.restart_required,
        "apply_action": entry.apply_action,
        "allowed_values": list(entry.allowed_values),
        "docs": entry.docs,
        "deprecated": entry.deprecated,
        "replacement": entry.replacement,
        "notes": entry.notes,
    }


def build_node_env_response(*, include_hidden: bool = False) -> dict[str, Any]:
    """Return node-local env values with registry metadata and safe redaction."""
    registry = load_env_registry()
    local_env_path = get_local_env_path()
    values = read_env_assignments(local_env_path)
    classified = registry.classify_keys(values)
    summary = build_node_env_summary()
    warnings = list(summary.get("warnings") or [])

    return {
        "config_path": str(local_env_path),
        "config_present": local_env_path.is_file(),
        "registry_version": registry.version,
        "registry_hash": registry.content_hash,
        "values": [
            build_env_value_payload(entry, values)
            for entry in registry.list_entries(scope="node", include_hidden=include_hidden)
        ],
        "unknown_keys": classified["unknown"],
        "deprecated_keys": classified["deprecated"],
        "summary": summary,
        "warnings": warnings,
    }


def validate_node_env_updates(updates: dict[str, Any]) -> tuple[dict[str, str], list[str], list[str], bool]:
    """Validate node-local env updates against the canonical registry."""
    registry = load_env_registry()
    validated: dict[str, str] = {}
    warnings: list[str] = []
    apply_actions: set[str] = set()
    restart_required = False

    for key, value in updates.items():
        entry = registry.get(key)
        if entry is None:
            raise EnvRegistryError(f"{key} is not registered in the MDS environment registry")
        if entry.scope != "node":
            raise EnvRegistryError(f"{key} is a {entry.scope} key and cannot be written to node local.env")
        if entry.deprecated:
            replacement = f"; use {entry.replacement}" if entry.replacement else ""
            raise EnvRegistryError(f"{key} is deprecated{replacement}")
        if not entry.editable:
            raise EnvRegistryError(f"{key} is not editable through the node env API")

        validated[key] = coerce_value(entry, value)
        apply_actions.add(entry.apply_action)
        if entry.restart_required != "none" or entry.apply_action != "none":
            restart_required = True
        if entry.ui_visibility == "advanced":
            warnings.append(f"{key} is an advanced node setting; verify recovery access before applying.")

    return validated, warnings, sorted(action for action in apply_actions if action != "none"), restart_required


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
