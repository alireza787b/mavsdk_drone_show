# gcs-server/sar/terrain.py
"""
QuickScout SAR - Terrain Helpers

Batch elevation queries and terrain-following altitude adjustment.
Reuses the existing get_elevation() from gcs-server/get_elevation.py.
"""

import os
import sys
import asyncio
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from get_elevation import get_elevation
from sar.schemas import CoverageWaypoint, QuickScoutTerrainSummary
from mds_logging import get_logger

logger = get_logger("terrain")


def _is_finite_number(value: Any) -> bool:
    try:
        return value is not None and value == value and float("-inf") < float(value) < float("inf")
    except (TypeError, ValueError):
        return False


def _first_elevation_result(provider_payload: Dict[str, Any]) -> Dict[str, Any]:
    results = provider_payload.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return {}


def _normalize_elevation_payload(provider_payload: Any) -> Dict[str, Any]:
    if _is_finite_number(provider_payload):
        return {
            "elevation_m": float(provider_payload),
            "status": "ok",
            "source": "backend",
            "provider": "backend",
            "confidence": "reported",
            "message": None,
            "sample_time": None,
        }

    if not isinstance(provider_payload, dict):
        return {
            "elevation_m": None,
            "status": "unavailable",
            "source": "unavailable",
            "provider": "unavailable",
            "confidence": "none",
            "message": "Elevation value was not returned.",
            "sample_time": None,
        }

    result_payload = _first_elevation_result(provider_payload)
    elevation = (
        provider_payload.get("elevation")
        if provider_payload.get("elevation") is not None
        else provider_payload.get("elevation_m")
    )
    if elevation is None:
        elevation = result_payload.get("elevation")
    if elevation is None:
        elevation = result_payload.get("elevation_m")

    source = (
        provider_payload.get("source")
        or result_payload.get("source")
        or provider_payload.get("dataset")
        or result_payload.get("dataset")
        or ("opentopodata" if result_payload else "backend")
    )
    provider = provider_payload.get("provider") or source
    confidence = provider_payload.get("confidence") or result_payload.get("confidence")
    sample_time = (
        provider_payload.get("sample_time")
        or provider_payload.get("timestamp")
        or result_payload.get("sample_time")
        or result_payload.get("timestamp")
    )

    if _is_finite_number(elevation):
        return {
            "elevation_m": float(elevation),
            "status": "ok",
            "source": str(source),
            "provider": str(provider),
            "confidence": str(confidence or "reported"),
            "message": provider_payload.get("message") or result_payload.get("message"),
            "sample_time": sample_time,
        }

    return {
        "elevation_m": None,
        "status": "unavailable",
        "source": str(source or "unavailable"),
        "provider": str(provider or source or "unavailable"),
        "confidence": str(confidence or "none"),
        "message": str(
            provider_payload.get("error")
            or result_payload.get("error")
            or provider_payload.get("message")
            or "Elevation value was not returned."
        ),
        "sample_time": sample_time,
    }


async def batch_get_elevations(points: List[dict], chunk_size: int = 100) -> List[Optional[float]]:
    """
    Batch elevation queries for a list of points.
    Runs synchronous get_elevation() in a thread to avoid blocking the event loop.

    Args:
        points: List of dicts with 'lat' and 'lng' keys.
        chunk_size: Max points per batch (API limit).

    Returns:
        List of elevation values (meters MSL) or None for failures.
    """
    results = []
    for point in points:
        try:
            data = await asyncio.to_thread(get_elevation, point['lat'], point['lng'])
            if data and 'results' in data and data['results']:
                elev = data['results'][0].get('elevation')
                results.append(elev)
            else:
                results.append(None)
        except Exception as e:
            logger.warning(f"Elevation query failed for ({point['lat']}, {point['lng']}): {e}")
            results.append(None)
    return results


async def batch_get_elevation_results(
    points: List[dict],
    provider: Optional[Callable[[float, float], Any]] = None,
) -> Dict[str, Any]:
    """Return typed per-point elevation status without raising on provider misses."""
    elevation_provider = provider or get_elevation
    results: List[Dict[str, Any]] = []
    for point in points:
        lat = float(point["lat"])
        lng = float(point["lng"])
        result: Dict[str, Any] = {
            "id": point.get("id"),
            "lat": lat,
            "lng": lng,
            "elevation_m": None,
            "status": "unavailable",
            "source": "unavailable",
            "provider": "unavailable",
            "confidence": "none",
            "message": "Elevation provider is unavailable.",
            "sample_time": None,
        }
        if elevation_provider is not None:
            try:
                normalized = _normalize_elevation_payload(
                    await asyncio.to_thread(elevation_provider, lat, lng)
                )
                result.update(normalized)
            except Exception as exc:
                logger.warning("Elevation lookup failed for (%s, %s): %s", lat, lng, exc)
                result["message"] = f"Elevation lookup failed: {exc}"
        results.append(result)

    resolved = sum(1 for item in results if item["status"] == "ok")
    return {
        "success": True,
        "elevations": [item["elevation_m"] for item in results],
        "results": results,
        "summary": {
            "requested": len(points),
            "resolved": resolved,
            "unavailable": len(points) - resolved,
            "status": "ok" if resolved == len(points) else "partial" if resolved else "unavailable",
        },
        "count": len(points),
    }


async def apply_terrain_following(
    waypoints: List[CoverageWaypoint],
    survey_alt_agl: float,
    cruise_alt_msl: float,
) -> List[CoverageWaypoint]:
    adjusted, _ = await apply_terrain_following_with_report(waypoints, survey_alt_agl, cruise_alt_msl)
    return adjusted


async def apply_terrain_following_with_report(
    waypoints: List[CoverageWaypoint],
    survey_alt_agl: float,
    cruise_alt_msl: float,
) -> tuple[List[CoverageWaypoint], QuickScoutTerrainSummary]:
    """
    Adjust waypoint altitudes for terrain following.

    For survey legs: altitude = ground_elevation + survey_alt_agl
    For transit legs: altitude = cruise_alt_msl (fixed)
    Fallback: if elevation unavailable, use cruise_alt_msl for all.

    Args:
        waypoints: List of waypoints to adjust.
        survey_alt_agl: Desired altitude above ground for survey legs (m).
        cruise_alt_msl: Fixed cruise altitude MSL for transit legs (m).

    Returns:
        New list of waypoints with adjusted altitudes and a terrain lookup summary.
    """
    # Collect survey waypoints for batch elevation query
    survey_indices = [i for i, wp in enumerate(waypoints) if wp.is_survey_leg]
    survey_points = [{'lat': waypoints[i].lat, 'lng': waypoints[i].lng} for i in survey_indices]

    elevations = await batch_get_elevations(survey_points) if survey_points else []

    # Build elevation map
    elev_map = {}
    for idx, elev in zip(survey_indices, elevations):
        elev_map[idx] = elev

    adjusted = []
    resolved_count = 0
    missing_count = 0
    for i, wp in enumerate(waypoints):
        # Create new waypoint with adjusted altitude
        new_data = wp.model_dump()

        if wp.is_survey_leg and i in elev_map and elev_map[i] is not None:
            ground_elev = elev_map[i]
            new_data['alt_msl'] = ground_elev + survey_alt_agl
            new_data['alt_agl'] = survey_alt_agl
            new_data['ground_elevation'] = ground_elev
            resolved_count += 1
        else:
            # Transit or elevation unavailable: use cruise altitude
            new_data['alt_msl'] = cruise_alt_msl
            if wp.is_survey_leg:
                missing_count += 1

        adjusted.append(CoverageWaypoint(**new_data))

    if not survey_indices:
        status = "skipped"
        message = "No survey legs required terrain elevation lookup."
    elif missing_count == 0:
        status = "ok"
        message = "Terrain elevations resolved for all survey waypoints."
    elif resolved_count == 0:
        status = "unavailable"
        message = "Terrain provider returned no elevations for survey waypoints."
    else:
        status = "partial"
        message = "Terrain provider returned partial elevations for survey waypoints."

    return adjusted, QuickScoutTerrainSummary(
        requested=True,
        status=status,
        queried_waypoints=len(survey_indices),
        resolved_waypoints=resolved_count,
        missing_waypoints=missing_count,
        message=message,
    )
