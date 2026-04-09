"""PX4 parameter metadata catalog loading."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from glob import glob
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Px4ParamCatalogEntry:
    name: str
    short_description: str | None = None
    long_description: str | None = None
    unit: str | None = None
    decimal_places: int | None = None
    default_value: int | float | str | None = None
    min_value: int | float | None = None
    max_value: int | float | None = None
    reboot_required: bool | None = None
    group: str | None = None
    category: str | None = None
    increment: int | float | None = None
    enum_values: list[dict[str, Any]] = field(default_factory=list)


def load_px4_param_catalog_index(params: Any) -> dict[str, Px4ParamCatalogEntry]:
    catalog_path = resolve_px4_param_catalog_path(params)
    if catalog_path is None:
        return {}
    stat = catalog_path.stat()
    return _load_catalog_from_path(str(catalog_path), stat.st_mtime_ns)


def resolve_px4_param_catalog_path(params: Any) -> Path | None:
    candidates: list[Path] = []
    configured_paths = _normalize_configured_paths(
        getattr(params, "PX4_PARAMETER_METADATA_CATALOG_PATHS", "")
    )
    patterns = configured_paths or _default_catalog_patterns()

    for raw_pattern in patterns:
        expanded = os.path.expanduser(raw_pattern)
        matches = glob(expanded) if any(ch in expanded for ch in "*?[]") else [expanded]
        for match in matches:
            path = Path(match)
            if path.is_file() and path.suffix.lower() == ".json":
                candidates.append(path)

    if not candidates:
        return None

    candidates.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    return candidates[0]


def _normalize_configured_paths(raw_value: Any) -> list[str]:
    if not raw_value:
        return []
    if isinstance(raw_value, str):
        return [segment.strip() for segment in raw_value.split(os.pathsep) if segment.strip()]
    if isinstance(raw_value, (list, tuple, set)):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    return []


def _default_catalog_patterns() -> list[str]:
    cwd = Path.cwd()
    return [
        str(cwd / "PX4-Autopilot" / "build" / "*" / "parameters.json"),
        str(cwd.parent / "PX4-Autopilot" / "build" / "*" / "parameters.json"),
        "/root/PX4-Autopilot/build/*/parameters.json",
        "/workspace/PX4-Autopilot/build/*/parameters.json",
    ]


@lru_cache(maxsize=8)
def _load_catalog_from_path(path_str: str, mtime_ns: int) -> dict[str, Px4ParamCatalogEntry]:
    del mtime_ns
    payload = json.loads(Path(path_str).read_text(encoding="utf-8"))
    raw_rows = payload.get("parameters", []) if isinstance(payload, dict) else []
    rows: dict[str, Px4ParamCatalogEntry] = {}
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        name = _normalize_name(raw_row.get("name"))
        if not name:
            continue
        rows[name] = Px4ParamCatalogEntry(
            name=name,
            short_description=_clean_text(raw_row.get("shortDesc")),
            long_description=_clean_text(raw_row.get("longDesc")),
            unit=_clean_text(raw_row.get("units")),
            decimal_places=_coerce_int(raw_row.get("decimalPlaces")),
            default_value=_coerce_scalar(raw_row.get("default")),
            min_value=_coerce_number(raw_row.get("min")),
            max_value=_coerce_number(raw_row.get("max")),
            reboot_required=_coerce_bool(raw_row.get("rebootRequired")),
            group=_clean_text(raw_row.get("group")),
            category=_clean_text(raw_row.get("category")),
            increment=_coerce_number(raw_row.get("increment")),
            enum_values=_coerce_enum_values(raw_row.get("values")),
        )
    return rows


def _normalize_name(raw_value: Any) -> str:
    return str(raw_value or "").strip().upper()


def _clean_text(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None


def _coerce_int(raw_value: Any) -> int | None:
    if raw_value is None or raw_value == "":
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _coerce_number(raw_value: Any) -> int | float | None:
    if raw_value is None or raw_value == "":
        return None
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return raw_value
    try:
        numeric = float(raw_value)
    except (TypeError, ValueError):
        return None
    if numeric.is_integer():
        return int(numeric)
    return numeric


def _coerce_scalar(raw_value: Any) -> int | float | str | None:
    numeric = _coerce_number(raw_value)
    if numeric is not None:
        return numeric
    return _clean_text(raw_value)


def _coerce_bool(raw_value: Any) -> bool | None:
    if isinstance(raw_value, bool):
        return raw_value
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def _coerce_enum_values(raw_value: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_value, list):
        return []

    values: list[dict[str, Any]] = []
    for item in raw_value:
        if not isinstance(item, dict):
            continue
        description = _clean_text(item.get("description"))
        value = _coerce_scalar(item.get("value"))
        if description is None and value is None:
            continue
        values.append(
            {
                "value": value if value is not None else "",
                "description": description,
            }
        )
    return values
