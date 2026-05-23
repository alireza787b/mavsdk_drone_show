"""Canonical MDS environment-variable registry helpers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_REGISTRY_PATH = REPO_ROOT / "resources" / "config" / "mds_env_registry.json"

VALID_SCOPES = {"deployment", "gcs", "node", "frontend", "bootstrap", "agent"}
VALID_DOMAINS = {
    "agent",
    "auth",
    "connectivity",
    "frontend",
    "git",
    "logging",
    "mavlink",
    "px4",
    "runtime",
    "sitl",
    "system",
}
VALID_VALUE_TYPES = {"boolean", "csv", "duration_hours", "float", "integer", "path", "string", "url"}
VALID_UI_VISIBILITIES = {"operator", "advanced", "diagnostic", "hidden"}
VALID_RESTART_REQUIREMENTS = {"none", "gcs", "node_service", "sidecar_reconcile", "frontend_rebuild", "manual"}
VALID_APPLY_ACTIONS = {"none", "restart_gcs", "restart_node_service", "reconcile_sidecar", "rebuild_frontend", "manual"}
SECRET_VALUE_SENTINEL = "<secret-redacted>"


class EnvRegistryError(ValueError):
    """Raised when the MDS env registry is malformed."""


@dataclass(frozen=True)
class EnvRegistryEntry:
    """Single canonical environment-variable metadata record."""

    name: str
    title: str
    scope: str
    domain: str
    source_of_truth: str
    value_type: str
    default: Any
    secret: bool
    editable: bool
    ui_visibility: str
    restart_required: str
    docs: str
    apply_action: str = "manual"
    allowed_values: tuple[Any, ...] = ()
    aliases: tuple[str, ...] = ()
    deprecated: bool = False
    replacement: str | None = None
    consumers: tuple[str, ...] = ()
    notes: str = ""
    owner: str = "platform"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EnvRegistryEntry":
        required = {
            "name",
            "title",
            "scope",
            "domain",
            "source_of_truth",
            "value_type",
            "default",
            "secret",
            "editable",
            "ui_visibility",
            "restart_required",
            "docs",
        }
        missing = sorted(required - set(payload))
        if missing:
            raise EnvRegistryError(f"registry entry is missing required field(s): {', '.join(missing)}")

        entry = cls(
            name=str(payload["name"]),
            title=str(payload["title"]),
            scope=str(payload["scope"]),
            domain=str(payload["domain"]),
            source_of_truth=str(payload["source_of_truth"]),
            value_type=str(payload["value_type"]),
            default=payload.get("default"),
            secret=bool(payload["secret"]),
            editable=bool(payload["editable"]),
            ui_visibility=str(payload["ui_visibility"]),
            restart_required=str(payload["restart_required"]),
            apply_action=str(payload.get("apply_action") or "manual"),
            allowed_values=tuple(payload.get("allowed_values") or ()),
            aliases=tuple(str(value) for value in payload.get("aliases") or ()),
            deprecated=bool(payload.get("deprecated", False)),
            replacement=payload.get("replacement"),
            docs=str(payload["docs"]),
            consumers=tuple(str(value) for value in payload.get("consumers") or ()),
            notes=str(payload.get("notes") or ""),
            owner=str(payload.get("owner") or "platform"),
        )
        entry.validate()
        return entry

    def validate(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum() or self.name.upper() != self.name:
            raise EnvRegistryError(f"invalid env registry key name: {self.name!r}")
        if self.scope not in VALID_SCOPES:
            raise EnvRegistryError(f"{self.name}: invalid scope {self.scope!r}")
        if self.domain not in VALID_DOMAINS:
            raise EnvRegistryError(f"{self.name}: invalid domain {self.domain!r}")
        if self.value_type not in VALID_VALUE_TYPES:
            raise EnvRegistryError(f"{self.name}: invalid value_type {self.value_type!r}")
        if self.ui_visibility not in VALID_UI_VISIBILITIES:
            raise EnvRegistryError(f"{self.name}: invalid ui_visibility {self.ui_visibility!r}")
        if self.restart_required not in VALID_RESTART_REQUIREMENTS:
            raise EnvRegistryError(f"{self.name}: invalid restart_required {self.restart_required!r}")
        if self.apply_action not in VALID_APPLY_ACTIONS:
            raise EnvRegistryError(f"{self.name}: invalid apply_action {self.apply_action!r}")
        if self.deprecated and self.editable:
            raise EnvRegistryError(f"{self.name}: deprecated entries must not be editable")
        if self.secret and self.editable:
            raise EnvRegistryError(f"{self.name}: raw secret entries must not be editable")
        if self.replacement is not None and not str(self.replacement).strip():
            raise EnvRegistryError(f"{self.name}: replacement must be non-empty when present")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "scope": self.scope,
            "domain": self.domain,
            "source_of_truth": self.source_of_truth,
            "value_type": self.value_type,
            "default": redact_value(self, self.default),
            "secret": self.secret,
            "editable": self.editable,
            "ui_visibility": self.ui_visibility,
            "restart_required": self.restart_required,
            "apply_action": self.apply_action,
            "allowed_values": list(self.allowed_values),
            "aliases": list(self.aliases),
            "deprecated": self.deprecated,
            "replacement": self.replacement,
            "docs": self.docs,
            "consumers": list(self.consumers),
            "notes": self.notes,
            "owner": self.owner,
        }


@dataclass(frozen=True)
class EnvRegistry:
    """Loaded env registry plus lookup helpers."""

    version: int
    path: Path
    entries: dict[str, EnvRegistryEntry] = field(default_factory=dict)
    content_hash: str = ""

    def get(self, name: str) -> EnvRegistryEntry | None:
        return self.entries.get(str(name))

    def require(self, name: str) -> EnvRegistryEntry:
        entry = self.get(name)
        if entry is None:
            raise KeyError(f"unknown MDS env key: {name}")
        return entry

    def list_entries(
        self,
        *,
        scope: str | None = None,
        domain: str | None = None,
        include_hidden: bool = True,
        include_deprecated: bool = True,
    ) -> list[EnvRegistryEntry]:
        values = list(self.entries.values())
        if scope is not None:
            values = [entry for entry in values if entry.scope == scope]
        if domain is not None:
            values = [entry for entry in values if entry.domain == domain]
        if not include_hidden:
            values = [entry for entry in values if entry.ui_visibility != "hidden"]
        if not include_deprecated:
            values = [entry for entry in values if not entry.deprecated]
        return sorted(values, key=lambda entry: (entry.scope, entry.domain, entry.name))

    def public_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "registry_hash": self.content_hash,
            "path": str(self.path),
            "entries": [entry.to_public_dict() for entry in self.list_entries()],
        }

    def classify_keys(self, values: dict[str, Any]) -> dict[str, list[str]]:
        unknown: list[str] = []
        deprecated: list[str] = []
        known: list[str] = []
        for key in sorted(values):
            entry = self.get(key)
            if entry is None:
                unknown.append(key)
            elif entry.deprecated:
                deprecated.append(key)
            else:
                known.append(key)
        return {"known": known, "unknown": unknown, "deprecated": deprecated}


def get_env_registry_path() -> Path:
    return Path(os.environ.get("MDS_ENV_REGISTRY_FILE", str(DEFAULT_ENV_REGISTRY_PATH)))


def redact_value(entry: EnvRegistryEntry, value: Any) -> Any:
    if value in (None, ""):
        return value
    if entry.secret:
        return SECRET_VALUE_SENTINEL
    return value


def coerce_value(entry: EnvRegistryEntry, value: Any) -> str:
    """Validate and convert an operator-supplied value for env-file storage."""
    if entry.secret:
        raise EnvRegistryError(f"{entry.name} is a raw secret and cannot be written through env APIs")

    if value is None:
        return ""

    if entry.value_type == "boolean":
        if isinstance(value, bool):
            normalized = value
        else:
            raw = str(value).strip().lower()
            if raw in {"1", "true", "yes", "on", "enabled"}:
                normalized = True
            elif raw in {"0", "false", "no", "off", "disabled"}:
                normalized = False
            else:
                raise EnvRegistryError(f"{entry.name} must be boolean")
        coerced = "true" if normalized else "false"
    elif entry.value_type in {"integer", "duration_hours"}:
        try:
            coerced = str(int(value))
        except (TypeError, ValueError) as exc:
            raise EnvRegistryError(f"{entry.name} must be an integer") from exc
    elif entry.value_type == "float":
        try:
            coerced = str(float(value))
        except (TypeError, ValueError) as exc:
            raise EnvRegistryError(f"{entry.name} must be a number") from exc
    else:
        coerced = str(value).strip()

    if entry.allowed_values:
        allowed = {str(item).lower() for item in entry.allowed_values}
        if coerced.lower() not in allowed:
            raise EnvRegistryError(
                f"{entry.name} must be one of: {', '.join(str(item) for item in entry.allowed_values)}"
            )

    return coerced


def _build_registry_from_payload(path: Path, payload: dict[str, Any], content_hash: str) -> EnvRegistry:
    try:
        version = int(payload["version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EnvRegistryError("registry version must be an integer") from exc

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise EnvRegistryError("registry entries must be a list")

    entries: dict[str, EnvRegistryEntry] = {}
    aliases: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise EnvRegistryError("registry entry must be an object")
        entry = EnvRegistryEntry.from_dict(raw_entry)
        if entry.name in entries:
            raise EnvRegistryError(f"duplicate registry entry: {entry.name}")
        entries[entry.name] = entry
        for alias in entry.aliases:
            if alias in entries:
                raise EnvRegistryError(f"{entry.name}: alias {alias!r} conflicts with a registry entry name")
            if alias in aliases:
                raise EnvRegistryError(f"duplicate registry alias: {alias}")
            aliases.add(alias)

    entry_names = set(entries)
    alias_conflicts = sorted(alias for alias in aliases if alias in entry_names)
    if alias_conflicts:
        raise EnvRegistryError(
            f"registry aliases conflict with canonical entry names: {', '.join(alias_conflicts)}"
        )

    for entry in entries.values():
        if entry.replacement is not None and entry.replacement not in entries:
            raise EnvRegistryError(f"{entry.name}: replacement {entry.replacement!r} is not registered")

    return EnvRegistry(version=version, path=path, entries=entries, content_hash=content_hash)


@lru_cache(maxsize=8)
def _load_env_registry_cached(path_value: str) -> EnvRegistry:
    path = Path(path_value)
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise EnvRegistryError(f"failed to read env registry {path}: {exc}") from exc

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise EnvRegistryError(f"failed to parse env registry {path}: {exc}") from exc

    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    return _build_registry_from_payload(path, payload, content_hash)


def load_env_registry(path: str | Path | None = None) -> EnvRegistry:
    registry_path = Path(path) if path is not None else get_env_registry_path()
    return _load_env_registry_cached(str(registry_path))


def reset_env_registry_cache() -> None:
    _load_env_registry_cached.cache_clear()
