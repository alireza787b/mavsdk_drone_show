# gcs-server/sar/terrain.py
"""
QuickScout SAR - Terrain Helpers

Batch elevation queries and terrain-following altitude adjustment.
Reuses the existing get_elevation() from gcs-server/get_elevation.py.
"""

import os
import sys
import asyncio
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from get_elevation import get_elevation
from sar.schemas import CoverageWaypoint, QuickScoutTerrainSummary
from mds_logging import get_logger

logger = get_logger("terrain")


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
