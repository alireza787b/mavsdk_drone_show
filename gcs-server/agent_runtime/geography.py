"""Offline, deterministic geography helpers for Simurgh.

Country lookup is deliberately isolated from telemetry rendering and provider
availability.  The resolver uses packaged polygon data, performs no network
request, and reports provenance/uncertainty so an informational country label
cannot be mistaken for navigation or airspace authority.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any


COUNTRY_LOOKUP_TOOL_ID = "simurgh.country_from_coordinates.read"
COUNTRY_LOOKUP_SOURCE = "offline_country_boundaries"
COUNTRY_LOOKUP_DATASET = "geo-intel-offline packaged Natural Earth boundaries"
COUNTRY_LOOKUP_DISCLAIMER = (
    "Country is an approximate informational lookup from offline boundary data; "
    "it is not navigation, airspace, legal, or flight-authorization evidence."
)

_LATITUDE_RE = re.compile(
    r"\b(?:lat|latitude)\b\s*[:=]?\s*(?P<value>[-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_LONGITUDE_RE = re.compile(
    r"\b(?:lon|long|lng|longitude)\b\s*[:=]?\s*(?P<value>[-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class CountryResolution:
    """One bounded coordinate-to-country result."""

    latitude: float
    longitude: float
    status: str
    country: str | None = None
    iso2: str | None = None
    iso3: str | None = None
    continent: str | None = None
    confidence: float = 0.0
    source: str = COUNTRY_LOOKUP_SOURCE
    dataset: str = COUNTRY_LOOKUP_DATASET
    detail: str = ""

    @property
    def label(self) -> str:
        return self.country or "unavailable"

    def public_payload(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "status": self.status,
            "country": self.country,
            "iso2": self.iso2,
            "iso3": self.iso3,
            "continent": self.continent,
            "confidence": round(float(self.confidence), 3),
            "source": self.source,
            "dataset": self.dataset,
            "detail": self.detail,
            "disclaimer": COUNTRY_LOOKUP_DISCLAIMER,
        }


def extract_latitude_longitude(message: str) -> tuple[float, float] | None:
    """Extract one WGS84 latitude/longitude pair from an operator question.

    Labeled values may appear in either order.  An unlabeled two-number pair is
    interpreted using the conventional ``latitude, longitude`` order only when
    both values form a valid coordinate.  Extra numbers are not guessed around.
    """

    text = str(message or "")
    latitude_match = _LATITUDE_RE.search(text)
    longitude_match = _LONGITUDE_RE.search(text)
    if latitude_match and longitude_match:
        pair = (
            _finite_float(latitude_match.group("value")),
            _finite_float(longitude_match.group("value")),
        )
        return pair if _valid_coordinate_pair(*pair) else None

    values = tuple(_finite_float(match.group(0)) for match in _NUMBER_RE.finditer(text))
    if len(values) != 2:
        return None
    return values if _valid_coordinate_pair(*values) else None


def resolve_country(latitude: float, longitude: float) -> CountryResolution:
    """Resolve a WGS84 point using packaged offline country polygons."""

    lat = _finite_float(latitude)
    lon = _finite_float(longitude)
    if not _valid_coordinate_pair(lat, lon):
        return CountryResolution(
            latitude=lat,
            longitude=lon,
            status="invalid",
            detail="Latitude must be within [-90, 90] and longitude within [-180, 180].",
        )
    # A five-decimal key is stable to roughly metre scale and prevents a moving
    # telemetry stream from filling the bounded cache with equivalent lookups.
    return _resolve_country_cached(round(lat, 5), round(lon, 5))


@lru_cache(maxsize=2048)
def _resolve_country_cached(latitude: float, longitude: float) -> CountryResolution:
    try:
        from geo_intel_offline import resolve
    except (ImportError, ModuleNotFoundError) as exc:
        return CountryResolution(
            latitude=latitude,
            longitude=longitude,
            status="unavailable",
            detail=f"Offline country resolver is not installed: {type(exc).__name__}.",
        )

    try:
        raw = resolve(latitude, longitude)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        return CountryResolution(
            latitude=latitude,
            longitude=longitude,
            status="unavailable",
            detail=f"Offline country resolver could not load its boundary data: {type(exc).__name__}.",
        )
    except Exception as exc:
        # Keep an optional informational lookup from breaking authoritative
        # fleet telemetry.  The exception type is safe to expose; raw package
        # paths or payloads are intentionally omitted.
        return CountryResolution(
            latitude=latitude,
            longitude=longitude,
            status="unavailable",
            detail=f"Offline country lookup failed: {type(exc).__name__}.",
        )

    country = _optional_text(getattr(raw, "country", None))
    confidence = _bounded_confidence(getattr(raw, "confidence", 0.0))
    if not country:
        return CountryResolution(
            latitude=latitude,
            longitude=longitude,
            status="not_found",
            confidence=confidence,
            detail="No containing country polygon matched this coordinate.",
        )
    return CountryResolution(
        latitude=latitude,
        longitude=longitude,
        status="resolved",
        country=country,
        iso2=_optional_text(getattr(raw, "iso2", None)),
        iso3=_optional_text(getattr(raw, "iso3", None)),
        continent=_optional_text(getattr(raw, "continent", None)),
        confidence=confidence,
        detail="Resolved locally without an external provider or geocoding request.",
    )


def format_country_resolution(result: CountryResolution) -> str:
    """Return a concise operator-facing rendering for the local tool."""

    if result.status == "resolved":
        code = f" ({result.iso2})" if result.iso2 else ""
        lead = f"Country: **{result.country}{code}**."
    elif result.status == "not_found":
        lead = "Country: **unavailable**; no containing country boundary matched the coordinate."
    else:
        lead = f"Country: **unavailable**; {result.detail}"
    return "\n\n".join(
        (
            lead,
            (
                f"Coordinate: latitude {result.latitude:.7f}, "
                f"longitude {result.longitude:.7f} (WGS84)."
            ),
            COUNTRY_LOOKUP_DISCLAIMER,
        )
    )


def _finite_float(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return math.nan
    return parsed if math.isfinite(parsed) else math.nan


def _valid_coordinate_pair(latitude: float, longitude: float) -> bool:
    return bool(
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90.0 <= latitude <= 90.0
        and -180.0 <= longitude <= 180.0
    )


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bounded_confidence(value: object) -> float:
    parsed = _finite_float(value)
    return max(0.0, min(1.0, parsed)) if math.isfinite(parsed) else 0.0
