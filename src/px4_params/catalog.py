"""PX4 parameter metadata catalog loading."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from glob import glob
from html import unescape
from pathlib import Path
from typing import Any

from src.px4_param_models import Px4ParamMetadataSource


@dataclass(frozen=True)
class Px4ParamCatalogEntry:
    name: str
    source: Px4ParamMetadataSource = Px4ParamMetadataSource.PX4_BUILD_CATALOG
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


_ONLINE_FAILURE_BACKOFF_UNTIL = 0.0


def load_px4_param_catalog_index(params: Any) -> dict[str, Px4ParamCatalogEntry]:
    catalog_path = resolve_px4_param_catalog_path(params)
    if catalog_path is None:
        return load_px4_docs_reference_catalog_index(params)
    stat = catalog_path.stat()
    return _load_catalog_from_path(str(catalog_path), stat.st_mtime_ns)


def load_px4_docs_reference_catalog_index(params: Any) -> dict[str, Px4ParamCatalogEntry]:
    """Load optional official PX4 docs metadata with bounded local caching.

    This is intentionally a fallback. Vehicle-served component metadata or a
    matching build `parameters.json` is safer for custom firmware. The docs
    cache is useful reference metadata when the runtime has only live values.
    """
    if not _coerce_bool(getattr(params, "PX4_PARAMETER_ONLINE_DOCS_METADATA_ENABLED", True), default=True):
        return {}

    version = str(getattr(params, "PX4_PARAMETER_DOCS_VERSION", "main") or "main").strip() or "main"
    base_template = getattr(
        params,
        "PX4_PARAMETER_DOCS_BASE_TEMPLATE",
        "https://docs.px4.io/{version}/en/advanced_config/parameter_reference.html",
    )
    if not isinstance(base_template, str) or not base_template.startswith("http"):
        base_template = "https://docs.px4.io/{version}/en/advanced_config/parameter_reference.html"
    url = base_template.format(version=version)

    cache_dir = Path(os.path.expanduser(str(
        getattr(params, "PX4_PARAMETER_METADATA_CACHE_DIR", "~/.cache/mds/px4-param-docs")
    )))
    ttl_days = _coerce_number(getattr(params, "PX4_PARAMETER_METADATA_CACHE_TTL_DAYS", 14)) or 14
    timeout_raw = _coerce_number(getattr(params, "PX4_PARAMETER_METADATA_FETCH_TIMEOUT_SEC", 2.5)) or 2.5
    max_entries_raw = _coerce_int(getattr(params, "PX4_PARAMETER_METADATA_CACHE_MAX_ENTRIES", 4)) or 4
    ttl_sec = max(3600, int(float(ttl_days) * 86400))
    timeout_sec = max(0.5, float(timeout_raw))
    max_entries = max(1, int(max_entries_raw))
    cache_path = _docs_cache_path(cache_dir, version, url)

    cached = _load_docs_cache_file(cache_path)
    if cached and time.time() - cache_path.stat().st_mtime <= ttl_sec:
        return cached

    if _online_fetch_backoff_active():
        return cached or {}

    try:
        entries = _fetch_and_parse_docs_reference(url, timeout_sec=timeout_sec)
    except (OSError, ValueError, urllib.error.URLError):
        _record_online_fetch_failure()
        return cached or {}

    if not entries:
        _record_online_fetch_failure()
        return cached or {}

    _write_docs_cache_file(cache_path, url=url, version=version, entries=entries)
    _prune_docs_cache(cache_dir, max_entries=max_entries, ttl_sec=ttl_sec)
    return entries


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
            source=Px4ParamMetadataSource.PX4_BUILD_CATALOG,
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


def _fetch_and_parse_docs_reference(url: str, *, timeout_sec: float) -> dict[str, Px4ParamCatalogEntry]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MDS-PX4-Parameter-Metadata/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        html_text = response.read().decode(charset, errors="replace")
    return parse_px4_parameter_reference_html(html_text)


def parse_px4_parameter_reference_html(html_text: str) -> dict[str, Px4ParamCatalogEntry]:
    """Parse the generated PX4 parameter-reference HTML into a lightweight catalog."""
    if not html_text:
        return {}

    compact_html = re.sub(r"<(script|style)\b.*?</\1>", "", html_text, flags=re.IGNORECASE | re.DOTALL)
    heading_pattern = re.compile(r"<h([2-4])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
    headings = list(heading_pattern.finditer(compact_html))
    rows: dict[str, Px4ParamCatalogEntry] = {}
    current_group: str | None = None

    for index, heading in enumerate(headings):
        level = int(heading.group(1))
        heading_text = _clean_html_text(heading.group(2))
        if level == 2:
            current_group = heading_text
            continue

        param_name = _extract_parameter_name(heading_text)
        if not param_name:
            continue

        next_start = headings[index + 1].start() if index + 1 < len(headings) else len(compact_html)
        section_html = compact_html[heading.end():next_start]
        table_values = _extract_first_metadata_table(section_html)
        descriptions = _extract_paragraph_text(section_html)
        short_description = descriptions[0] if descriptions else None
        long_description = "\n\n".join(descriptions) if descriptions else None

        rows[param_name] = Px4ParamCatalogEntry(
            name=param_name,
            source=Px4ParamMetadataSource.PX4_DOCS_CACHE,
            short_description=short_description,
            long_description=long_description,
            unit=_clean_text(table_values.get("unit")),
            default_value=_coerce_scalar(table_values.get("default")),
            min_value=_coerce_number(table_values.get("minvalue") or table_values.get("min")),
            max_value=_coerce_number(table_values.get("maxvalue") or table_values.get("max")),
            reboot_required=_coerce_reboot_required(table_values.get("reboot")),
            group=current_group,
            increment=_coerce_number(table_values.get("increment")),
            enum_values=_extract_enum_values(section_html),
        )

    return rows


def _extract_parameter_name(text: str) -> str | None:
    match = re.match(r"\s*([A-Z][A-Z0-9_]{1,15})(?:\s|\(|$)", text)
    if not match:
        return None
    return _normalize_name(match.group(1))


def _extract_first_metadata_table(section_html: str) -> dict[str, str]:
    table_match = re.search(r"<table\b[^>]*>(.*?)</table>", section_html, flags=re.IGNORECASE | re.DOTALL)
    if not table_match:
        return {}

    table_html = table_match.group(1)
    headers = [
        _normalize_table_key(_clean_html_text(match.group(1)))
        for match in re.finditer(r"<th\b[^>]*>(.*?)</th>", table_html, flags=re.IGNORECASE | re.DOTALL)
    ]
    cells = [
        _clean_html_text(match.group(1))
        for match in re.finditer(r"<td\b[^>]*>(.*?)</td>", table_html, flags=re.IGNORECASE | re.DOTALL)
    ]
    if not headers or not cells:
        return {}

    return {
        header: value
        for header, value in zip(headers, cells[:len(headers)])
        if header
    }


def _extract_paragraph_text(section_html: str) -> list[str]:
    table_start = section_html.lower().find("<table")
    text_region = section_html if table_start < 0 else section_html[:table_start]
    values = []
    for match in re.finditer(r"<p\b[^>]*>(.*?)</p>", text_region, flags=re.IGNORECASE | re.DOTALL):
        text = _clean_html_text(match.group(1))
        if text:
            values.append(text)
    return values


def _extract_enum_values(section_html: str) -> list[dict[str, Any]]:
    values = []
    for match in re.finditer(r"<li\b[^>]*>(.*?)</li>", section_html, flags=re.IGNORECASE | re.DOTALL):
        text = _clean_html_text(match.group(1))
        enum_match = re.match(r"`?(-?\d+(?:\.\d+)?)`?\s*:\s*(.+)", text)
        if not enum_match:
            continue
        values.append({
            "value": _coerce_scalar(enum_match.group(1)),
            "description": enum_match.group(2).strip(),
        })
    return values


def _clean_html_text(raw_value: Any) -> str:
    value = re.sub(r"<[^>]+>", " ", str(raw_value or ""))
    value = unescape(value)
    value = value.replace("#", " ")
    return re.sub(r"\s+", " ", value).strip()


def _normalize_table_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _coerce_reboot_required(raw_value: Any) -> bool | None:
    value = _clean_text(raw_value)
    if not value:
        return None
    normalized = value.lower()
    if normalized in {"true", "yes", "1", "required", "reboot required"}:
        return True
    if normalized in {"false", "no", "0", "not required"}:
        return False
    return True


def _docs_cache_path(cache_dir: Path, version: str, url: str) -> Path:
    safe_version = re.sub(r"[^A-Za-z0-9_.-]+", "_", version)[:80] or "main"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"parameter_reference_{safe_version}_{url_hash}.json"


def _load_docs_cache_file(path: Path) -> dict[str, Px4ParamCatalogEntry]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

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
            source=Px4ParamMetadataSource.PX4_DOCS_CACHE,
            short_description=_clean_text(raw_row.get("short_description")),
            long_description=_clean_text(raw_row.get("long_description")),
            unit=_clean_text(raw_row.get("unit")),
            default_value=_coerce_scalar(raw_row.get("default_value")),
            min_value=_coerce_number(raw_row.get("min_value")),
            max_value=_coerce_number(raw_row.get("max_value")),
            reboot_required=_coerce_bool(raw_row.get("reboot_required")),
            group=_clean_text(raw_row.get("group")),
            category=_clean_text(raw_row.get("category")),
            increment=_coerce_number(raw_row.get("increment")),
            enum_values=_coerce_enum_values(raw_row.get("enum_values")),
        )
    return rows


def _write_docs_cache_file(
    path: Path,
    *,
    url: str,
    version: str,
    entries: dict[str, Px4ParamCatalogEntry],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": Px4ParamMetadataSource.PX4_DOCS_CACHE.value,
        "source_url": url,
        "version": version,
        "cached_at": int(time.time()),
        "parameters": [
            {
                "name": entry.name,
                "short_description": entry.short_description,
                "long_description": entry.long_description,
                "unit": entry.unit,
                "default_value": entry.default_value,
                "min_value": entry.min_value,
                "max_value": entry.max_value,
                "reboot_required": entry.reboot_required,
                "group": entry.group,
                "category": entry.category,
                "increment": entry.increment,
                "enum_values": entry.enum_values,
            }
            for entry in sorted(entries.values(), key=lambda item: item.name)
        ],
    }
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _prune_docs_cache(cache_dir: Path, *, max_entries: int, ttl_sec: int) -> None:
    try:
        candidates = sorted(
            cache_dir.glob("parameter_reference_*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return

    now = time.time()
    for index, path in enumerate(candidates):
        try:
            too_many = index >= max_entries
            too_old = now - path.stat().st_mtime > ttl_sec * 2
            if too_many or too_old:
                path.unlink(missing_ok=True)
        except OSError:
            continue


def _online_fetch_backoff_active() -> bool:
    return time.time() < _ONLINE_FAILURE_BACKOFF_UNTIL


def _record_online_fetch_failure() -> None:
    global _ONLINE_FAILURE_BACKOFF_UNTIL
    _ONLINE_FAILURE_BACKOFF_UNTIL = time.time() + 3600


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


def _coerce_bool(raw_value: Any, default: bool | None = None) -> bool | None:
    if isinstance(raw_value, bool):
        return raw_value
    if raw_value is None:
        return default
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off"}:
            return False
    return default


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
