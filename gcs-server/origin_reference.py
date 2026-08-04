"""Authoritative validation for drone-referenced formation origins."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class OriginReferenceError(ValueError):
    """Typed operational failure while resolving a drone origin reference."""

    code: str
    message: str
    status_code: int = 409

    def __str__(self) -> str:
        return self.message


def _identity(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _positive_int(value: Any) -> int | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def coerce_valid_origin_values(lat: Any, lon: Any, alt: Any) -> tuple[float, float, float]:
    """Return finite, range-checked WGS84/MSL origin values.

    This is the shared persistence and computed-candidate boundary. Zero
    latitude/longitude are legitimate; callers that require a live vehicle
    position must separately reject the `(0, 0)` unavailable sentinel.
    """

    latitude = _finite_float(lat)
    longitude = _finite_float(lon)
    altitude_msl = _finite_float(alt)
    if latitude is None or not -90.0 <= latitude <= 90.0:
        raise ValueError("origin latitude must be a finite value in [-90, 90]")
    if longitude is None or not -180.0 <= longitude <= 180.0:
        raise ValueError("origin longitude must be a finite value in [-180, 180]")
    if altitude_msl is None:
        raise ValueError("origin altitude MSL must be finite")
    return latitude, longitude, altitude_msl


def validate_fresh_global_position(
    telemetry_row: Mapping[str, Any],
    *,
    hw_id: Any,
    now_ms: int,
    max_age_ms: int,
    require_disarmed: bool,
) -> dict[str, Any]:
    """Validate one telemetry row as fresh PX4 global-position evidence."""

    requested_hw_id = _identity(hw_id)
    reported_hw_id = _identity(telemetry_row.get("hw_id"))
    if not reported_hw_id or reported_hw_id != requested_hw_id:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_IDENTITY_MISMATCH",
            f"Telemetry identity for Drone HW {requested_hw_id} is inconsistent. Refresh fleet state before retrying.",
        )

    if telemetry_row.get("telemetry_available") is not True:
        reason = str(telemetry_row.get("telemetry_error") or "Live telemetry is unavailable.")
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_TELEMETRY_UNAVAILABLE",
            f"Drone HW {requested_hw_id} cannot be used as a position reference: {reason}",
        )

    if require_disarmed and telemetry_row.get("is_armed") is not False:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_ARMED",
            f"Drone HW {requested_hw_id} must be disarmed before it can define the formation origin.",
        )

    gps_fix_type = _positive_int(telemetry_row.get("gps_fix_type")) or 0
    if gps_fix_type < 3:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_GPS_FIX_INSUFFICIENT",
            f"Drone HW {requested_hw_id} does not have a 3D GPS fix yet.",
        )

    if telemetry_row.get("global_position_valid") is not True:
        reason = str(
            telemetry_row.get("position_unavailable_reason")
            or "PX4 has not published a valid current global position."
        )
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_GLOBAL_POSITION_UNAVAILABLE",
            (
                f"Drone HW {requested_hw_id} has a GPS receiver fix, but no usable PX4 global position: "
                f"{reason}"
            ),
        )

    position_source = str(telemetry_row.get("position_source") or "unavailable")
    if position_source != "global_position_int":
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_SOURCE_INVALID",
            (
                f"Drone HW {requested_hw_id} position source is {position_source}; "
                "a current PX4 global position is required."
            ),
        )

    try:
        latitude, longitude, altitude_msl = coerce_valid_origin_values(
            telemetry_row.get("position_lat"),
            telemetry_row.get("position_long"),
            telemetry_row.get("position_alt"),
        )
    except ValueError as exc:
        if "altitude" in str(exc):
            raise OriginReferenceError(
                "ORIGIN_REFERENCE_ALTITUDE_UNAVAILABLE",
                f"Drone HW {requested_hw_id} does not have a valid absolute MSL altitude.",
            ) from exc
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_COORDINATES_INVALID",
            f"Drone HW {requested_hw_id} does not have valid current latitude/longitude telemetry.",
        ) from exc
    if abs(latitude) <= 0.000001 and abs(longitude) <= 0.000001:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_COORDINATES_INVALID",
            f"Drone HW {requested_hw_id} does not have valid current latitude/longitude telemetry.",
        )

    try:
        position_timestamp_ms = int(telemetry_row.get("global_position_timestamp_ms") or 0)
    except (TypeError, ValueError):
        position_timestamp_ms = 0
    if position_timestamp_ms <= 0:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_TIMESTAMP_MISSING",
            f"Drone HW {requested_hw_id} global-position timestamp is unavailable; retry after telemetry refreshes.",
        )

    bounded_max_age_ms = max(1, int(max_age_ms))
    position_age_ms = max(0, int(now_ms) - position_timestamp_ms)
    if position_age_ms > bounded_max_age_ms:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_POSITION_STALE",
            (
                f"Drone HW {requested_hw_id} global position is {position_age_ms / 1000.0:.1f}s old; "
                f"a sample no older than {bounded_max_age_ms / 1000.0:.1f}s is required."
            ),
        )

    return {
        "hw_id": requested_hw_id,
        "latitude": latitude,
        "longitude": longitude,
        "altitude_msl": altitude_msl,
        "position_source": position_source,
        "position_timestamp_ms": position_timestamp_ms,
        "position_age_ms": position_age_ms,
        "gps_fix_type": gps_fix_type,
    }


def resolve_origin_reference(
    *,
    hw_id: Any,
    drones_config: Sequence[Mapping[str, Any]],
    telemetry_snapshot: Mapping[Any, Mapping[str, Any]],
    now_ms: int,
    max_age_ms: int,
) -> dict[str, Any]:
    """Resolve one configured, disarmed drone with fresh PX4 global position.

    Raw GPS fix alone is deliberately insufficient. Formation-origin altitude
    must be absolute MSL from the same valid GLOBAL_POSITION_INT sample.
    """

    requested_hw_id = _identity(hw_id)
    if not requested_hw_id:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_ID_REQUIRED",
            "Select a configured drone to compute the origin.",
            422,
        )

    configured_matches = [
        dict(drone)
        for drone in drones_config
        if _identity(drone.get("hw_id")) == requested_hw_id
    ]
    if not configured_matches:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_NOT_CONFIGURED",
            f"Drone HW {requested_hw_id} is not configured.",
            404,
        )
    if len(configured_matches) != 1:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_CONFIG_AMBIGUOUS",
            f"Drone HW {requested_hw_id} has duplicate fleet assignments. Repair Mission Config first.",
        )

    config_row = configured_matches[0]
    pos_id = _positive_int(config_row.get("pos_id"))
    if pos_id is None:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_SLOT_INVALID",
            f"Drone HW {requested_hw_id} does not have a valid assigned show slot.",
        )

    telemetry_row: Mapping[str, Any] | None = None
    for key, candidate in telemetry_snapshot.items():
        if _identity(key) != requested_hw_id:
            continue
        if not isinstance(candidate, Mapping):
            break
        telemetry_row = candidate
        break

    if telemetry_row is None:
        raise OriginReferenceError(
            "ORIGIN_REFERENCE_TELEMETRY_MISSING",
            f"No telemetry row is available for Drone HW {requested_hw_id}.",
        )

    position = validate_fresh_global_position(
        telemetry_row,
        hw_id=requested_hw_id,
        now_ms=now_ms,
        max_age_ms=max_age_ms,
        require_disarmed=True,
    )
    return {**position, "pos_id": pos_id}
