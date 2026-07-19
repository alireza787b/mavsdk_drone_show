# src/coordinate_utils.py
"""
Coordinate Utilities
====================
Shared coordinate transformation and trajectory reading utilities.

This module consolidates duplicate coordinate transformation functions
that were previously scattered across multiple files.
"""

import csv
import logging
import math
import os
from pathlib import Path
from typing import Optional, Tuple

from pyproj import Proj, Transformer

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent


def _candidate_base_dirs(base_dir: Optional[str] = None) -> list[Path]:
    """Return ordered candidate roots for trajectory lookups."""
    candidates = []
    seen = set()

    raw_candidates = [
        base_dir,
        os.environ.get("MDS_BASE_DIR"),
        os.getcwd(),
        str(REPO_ROOT),
    ]

    for raw_candidate in raw_candidates:
        if not raw_candidate:
            continue
        candidate = Path(raw_candidate).expanduser().resolve()
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        candidates.append(candidate)

    return candidates


def latlon_to_ne(
    lat: float,
    lon: float,
    origin_lat: float,
    origin_lon: float
) -> Tuple[float, float]:
    """
    Convert latitude/longitude coordinates to North-East (NE) coordinates
    relative to an origin point.

    Uses a Transverse Mercator projection centered at the origin to convert
    WGS84 geodetic coordinates to a local Cartesian coordinate system.

    Args:
        lat: Latitude of the point to convert (degrees)
        lon: Longitude of the point to convert (degrees)
        origin_lat: Latitude of the origin point (degrees)
        origin_lon: Longitude of the origin point (degrees)

    Returns:
        Tuple of (north, east) coordinates in meters relative to origin

    Raises:
        ValueError: If coordinate transformation fails

    Example:
        >>> north, east = latlon_to_ne(37.7750, -122.4194, 37.7749, -122.4193)
        >>> print(f"North: {north:.2f}m, East: {east:.2f}m")
    """
    try:
        # Define a local Transverse Mercator projection centered at the origin
        proj_string = (
            f"+proj=tmerc +lat_0={origin_lat} +lon_0={origin_lon} "
            f"+k=1 +units=m +ellps=WGS84"
        )
        transformer = Transformer.from_proj(
            Proj('epsg:4326'),  # WGS84 coordinate system
            Proj(proj_string),
            always_xy=True  # Ensure consistent (lon, lat) input order
        )
        # With always_xy=True, input order is (x, y) = (lon, lat)
        east, north = transformer.transform(lon, lat)
        return north, east
    except Exception as e:
        logger.error(f"Error in coordinate transformation: {e}", exc_info=True)
        raise ValueError(f"Coordinate transformation failed: {e}") from e


def get_expected_position_from_trajectory(
    pos_id: int,
    sim_mode: bool = False,
    base_dir: Optional[str] = None
) -> Tuple[Optional[float], Optional[float]]:
    """
    Get the expected starting position from a trajectory CSV file.

    Reads the first waypoint from the trajectory CSV file corresponding
    to the given position ID. This is the single source of truth for
    expected position, especially critical when hw_id != pos_id.

    Args:
        pos_id: Position ID (determines which trajectory file to read)
        sim_mode: Whether in simulation mode (uses shapes_sitl vs shapes)
        base_dir: Base directory for trajectory files. If None, uses current
                  working directory.

    Returns:
        Tuple of (north, east) coordinates from first waypoint in meters,
        or (None, None) on error

    Example:
        When hw_id=10 performs pos_id=1's show, this function reads
        "Drone 1.csv" first row to get the expected starting position.
    """
    try:
        shapes_dir = 'shapes_sitl' if sim_mode else 'shapes'
        relative_path = Path(shapes_dir) / 'swarm' / 'processed' / f"Drone {pos_id}.csv"

        trajectory_file = None
        searched_paths = []
        for candidate_base_dir in _candidate_base_dirs(base_dir):
            candidate_file = candidate_base_dir / relative_path
            searched_paths.append(str(candidate_file))
            if candidate_file.exists():
                trajectory_file = candidate_file
                break

        if trajectory_file is None:
            logger.error(
                "Trajectory file not found for pos_id=%s. Searched: %s",
                pos_id,
                ", ".join(searched_paths),
            )
            return None, None

        # Read first waypoint from CSV
        with trajectory_file.open('r') as f:
            reader = csv.DictReader(f)
            first_waypoint = next(reader, None)

            if first_waypoint is None:
                logger.error(f"Trajectory file is empty: {trajectory_file}")
                return None, None

            # Extract px (North) and py (East) from first waypoint
            # These represent the canonical expected position for this pos_id
            expected_north = float(first_waypoint.get('px', 0))
            expected_east = float(first_waypoint.get('py', 0))

            if not (math.isfinite(expected_north) and math.isfinite(expected_east)):
                logger.error(
                    f"Non-finite first waypoint coordinates for pos_id={pos_id}: "
                    f"North={expected_north!r}, East={expected_east!r} "
                    f"(from {trajectory_file})"
                )
                return None, None

            logger.debug(
                f"Expected position for pos_id={pos_id}: "
                f"North={expected_north:.2f}m, East={expected_east:.2f}m "
                f"(from {trajectory_file})"
            )

            return expected_north, expected_east

    except (ValueError, KeyError) as e:
        logger.error(
            f"Error parsing trajectory file for pos_id={pos_id}: {e}"
        )
        return None, None
    except Exception as e:
        logger.error(
            f"Unexpected error reading trajectory file for pos_id={pos_id}: {e}"
        )
        return None, None
