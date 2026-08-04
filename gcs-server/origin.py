# gcs-server/origin.py

import math
import os
import json
import time
from datetime import datetime
from typing import Any, Dict, Optional

from params import Params
from pyproj import Proj, Transformer
from scipy.optimize import minimize
from coordinate_utils import get_expected_position_from_trajectory
from mds_logging import get_logger
from origin_reference import (
    OriginReferenceError,
    coerce_valid_origin_values,
    validate_fresh_global_position,
)

logger = get_logger("origin")


def _get_telemetry_record_for_hw_id(telemetry_snapshot, hw_id):
    """Handle legacy int-key and current string-key telemetry stores consistently."""
    if hw_id in telemetry_snapshot:
        return telemetry_snapshot.get(hw_id, {})

    normalized_hw_id = str(hw_id)
    if normalized_hw_id in telemetry_snapshot:
        return telemetry_snapshot.get(normalized_hw_id, {})

    try:
        numeric_hw_id = int(normalized_hw_id)
    except (TypeError, ValueError):
        numeric_hw_id = None

    if numeric_hw_id is not None and numeric_hw_id in telemetry_snapshot:
        return telemetry_snapshot.get(numeric_hw_id, {})

    return {}

# Define the path for storing origin data
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
origin_file_path = os.path.join(BASE_DIR, 'data', 'origin.json')
sitl_default_origin_file_path = os.path.join(BASE_DIR, 'data', 'origin.sitl.default.json')

# Ensure the data directory exists
if not os.path.exists(os.path.dirname(origin_file_path)):
    os.makedirs(os.path.dirname(origin_file_path))


def _normalize_origin_payload(data: Dict[str, Any], *, default_alt_source: str) -> Dict[str, Any]:
    """Normalize origin payloads from runtime or packaged defaults."""
    lat = data.get('lat')
    lon = data.get('lon')

    normalized = {
        'lat': '' if lat in (None, '') else float(lat),
        'lon': '' if lon in (None, '') else float(lon),
        'alt': float(data.get('alt', 0) or 0),
        'alt_source': data.get('alt_source', default_alt_source),
        'version': int(data.get('version', 2) or 2),
    }

    for metadata_key in (
        'reference_hw_id',
        'reference_pos_id',
        'reference_position_timestamp_ms',
    ):
        if data.get(metadata_key) not in (None, ''):
            normalized[metadata_key] = data.get(metadata_key)

    if data.get('timestamp'):
        normalized['timestamp'] = data.get('timestamp')

    return normalized


def _load_json_origin_file(path: str, *, default_alt_source: str) -> Optional[Dict[str, Any]]:
    """Load and normalize an origin JSON file."""
    if not os.path.exists(path):
        return None

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return _normalize_origin_payload(data, default_alt_source=default_alt_source)


def load_sitl_default_origin() -> Optional[Dict[str, Any]]:
    """Return the tracked default SITL origin when available."""
    if not getattr(Params, 'sim_mode', False):
        return None

    try:
        origin = _load_json_origin_file(
            sitl_default_origin_file_path,
            default_alt_source='sitl_default',
        )
        if origin:
            logger.debug("Using packaged SITL default origin.")
        return origin
    except Exception as e:
        logger.error(f"Error loading packaged SITL default origin: {e}")
        return None

def save_origin(data):
    """
    Save the origin coordinates to a JSON file (v2 schema with altitude support).

    Schema v2:
      - lat: float (required) - Latitude in decimal degrees
      - lon: float (required) - Longitude in decimal degrees
      - alt: float (optional, default 0) - MSL altitude in meters
      - alt_source: str (optional) - 'manual' | 'drone' | 'elevation_api'
      - timestamp: ISO datetime string
      - version: int (schema version)

    :param data: Dictionary containing origin data
    """
    try:
        # Build v2 schema with backwards compatibility
        latitude, longitude, altitude_msl = coerce_valid_origin_values(
            data.get('lat'),
            data.get('lon'),
            data.get('alt', 0),
        )
        origin_data = {
            'lat': latitude,
            'lon': longitude,
            'alt': altitude_msl,  # Default to 0 for backwards compatibility.
            'alt_source': data.get('alt_source', 'manual'),
            'timestamp': datetime.now().isoformat(),
            'version': 2
        }

        for metadata_key in (
            'reference_hw_id',
            'reference_pos_id',
            'reference_position_timestamp_ms',
        ):
            if data.get(metadata_key) not in (None, ''):
                origin_data[metadata_key] = data.get(metadata_key)

        with open(origin_file_path, 'w', encoding='utf-8') as f:
            json.dump(origin_data, f, indent=2, allow_nan=False)

        logger.info(f"Origin coordinates saved successfully: lat={origin_data['lat']}, "
                   f"lon={origin_data['lon']}, alt={origin_data['alt']}m")
    except Exception as e:
        logger.error(f"Error saving origin coordinates: {e}")
        raise

def load_origin():
    """
    Load the origin coordinates from a JSON file with backwards compatibility.

    Automatically migrates v1 format (lat/lon only) to v2 (with altitude).

    :return: Dictionary containing origin data in v2 format
    """
    if os.path.exists(origin_file_path):
        try:
            with open(origin_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Check version and migrate if needed
            if 'version' not in data or data.get('version') == 1:
                # Migrate from v1 to v2
                logger.info("Migrating origin data from v1 to v2 schema")
                data = {
                    'lat': data.get('lat', ''),
                    'lon': data.get('lon', ''),
                    'alt': 0,  # Old format assumed ground level
                    'alt_source': 'manual',
                    'timestamp': datetime.now().isoformat(),
                    'version': 2
                }
                # Save migrated data
                try:
                    save_origin(data)
                except Exception:
                    pass  # Don't fail if save fails during migration

            logger.debug("Origin coordinates loaded successfully.")
            return _normalize_origin_payload(data, default_alt_source='manual')

        except Exception as e:
            logger.error(f"Error loading origin coordinates: {e}")
            return {'lat': '', 'lon': '', 'alt': 0, 'version': 2}

    default_origin = load_sitl_default_origin()
    if default_origin:
        return default_origin

    logger.debug("Origin file does not exist yet. Returning default values.")
    return {'lat': '', 'lon': '', 'alt': 0, 'version': 2}

def rotate_north_east(north: float, east: float, heading_deg: float) -> tuple[float, float]:
    """Rotate formation offsets clockwise by the requested heading."""
    heading_rad = math.radians(float(heading_deg) % 360.0)
    rotated_north = (float(north) * math.cos(heading_rad)) - (float(east) * math.sin(heading_rad))
    rotated_east = (float(north) * math.sin(heading_rad)) + (float(east) * math.cos(heading_rad))
    return rotated_north, rotated_east


def build_position_deviation_report(
    telemetry_data_all_drones,
    drones_config,
    origin_lat: float,
    origin_lon: float,
    origin_alt: float = 0.0,
    trajectory_resolver=None,
):
    """Build the richer deviation payload exposed by the GCS API."""
    import pymap3d as pm

    deviations = {}
    summary_stats = {
        'total_drones': len(drones_config),
        'online': 0,
        'within_threshold': 0,
        'warnings': 0,
        'errors': 0,
        'no_telemetry': 0,
        'best_deviation': float('inf'),
        'worst_deviation': 0,
        'total_deviation_sum': 0,
    }

    threshold_warning = Params.acceptable_deviation
    threshold_error = threshold_warning * 2.5
    position_max_age_ms = max(
        1,
        int(float(getattr(Params, 'LOCAL_MAVLINK_STALE_TIMEOUT_SEC', 15)) * 1000),
    )
    sim_mode = getattr(Params, 'sim_mode', False)
    resolve_trajectory = trajectory_resolver or (
        lambda pos_id, current_sim_mode: get_expected_position_from_trajectory(
            pos_id,
            current_sim_mode,
            base_dir=BASE_DIR,
        )
    )

    for drone in drones_config:
        hw_id = drone.get('hw_id')
        pos_id = drone.get('pos_id', hw_id)

        if not hw_id:
            continue

        expected_north, expected_east = resolve_trajectory(pos_id, sim_mode)

        if expected_north is None or expected_east is None:
            deviations[hw_id] = {
                'hw_id': hw_id,
                'pos_id': pos_id,
                'status': 'error',
                'message': f'Could not read trajectory file for pos_id={pos_id}',
            }
            summary_stats['errors'] += 1
            continue

        try:
            expected_lat, expected_lon, expected_alt = pm.ned2geodetic(
                expected_north,
                expected_east,
                0,
                origin_lat,
                origin_lon,
                origin_alt,
            )
        except Exception as exc:
            deviations[hw_id] = {
                'hw_id': hw_id,
                'pos_id': pos_id,
                'status': 'error',
                'message': f'Coordinate conversion error: {exc}',
            }
            summary_stats['errors'] += 1
            continue

        drone_telemetry = _get_telemetry_record_for_hw_id(telemetry_data_all_drones, hw_id)
        try:
            position = validate_fresh_global_position(
                drone_telemetry,
                hw_id=hw_id,
                now_ms=int(time.time() * 1000),
                max_age_ms=position_max_age_ms,
                require_disarmed=False,
            )
        except OriginReferenceError as exc:
            deviations[hw_id] = {
                'hw_id': hw_id,
                'pos_id': pos_id,
                'expected': {
                    'lat': expected_lat,
                    'lon': expected_lon,
                    'north': expected_north,
                    'east': expected_east,
                },
                'current': None,
                'deviation': None,
                'status': 'no_telemetry',
                'message': exc.message,
            }
            summary_stats['no_telemetry'] += 1
            continue

        current_lat = position['latitude']
        current_lon = position['longitude']

        current_north, current_east, _current_down = pm.geodetic2ned(
            current_lat,
            current_lon,
            origin_alt,
            origin_lat,
            origin_lon,
            origin_alt,
        )

        deviation_north = current_north - expected_north
        deviation_east = current_east - expected_east
        deviation_horizontal = math.sqrt(deviation_north ** 2 + deviation_east ** 2)

        if deviation_horizontal > threshold_error:
            status = 'error'
            message = (
                f'Deviation exceeds error threshold ({deviation_horizontal:.2f}m > {threshold_error}m)'
            )
            summary_stats['errors'] += 1
        elif deviation_horizontal > threshold_warning:
            status = 'warning'
            message = (
                f'Deviation exceeds warning threshold ({deviation_horizontal:.2f}m > {threshold_warning}m)'
            )
            summary_stats['warnings'] += 1
        else:
            status = 'ok'
            message = 'Position within acceptable range'
            summary_stats['within_threshold'] += 1

        summary_stats['online'] += 1
        summary_stats['total_deviation_sum'] += deviation_horizontal
        summary_stats['best_deviation'] = min(summary_stats['best_deviation'], deviation_horizontal)
        summary_stats['worst_deviation'] = max(summary_stats['worst_deviation'], deviation_horizontal)

        deviations[hw_id] = {
            'hw_id': hw_id,
            'pos_id': pos_id,
            'expected': {
                'lat': expected_lat,
                'lon': expected_lon,
                'north': expected_north,
                'east': expected_east,
            },
            'current': {
                'lat': current_lat,
                'lon': current_lon,
                'north': current_north,
                'east': current_east,
                'position_source': position['position_source'],
                'position_age_ms': position['position_age_ms'],
            },
            'deviation': {
                'north': deviation_north,
                'east': deviation_east,
                'horizontal': deviation_horizontal,
                'within_threshold': deviation_horizontal <= threshold_warning,
            },
            'status': status,
            'message': message,
        }

    if summary_stats['online'] > 0:
        summary_stats['average_deviation'] = (
            summary_stats['total_deviation_sum'] / summary_stats['online']
        )
    else:
        summary_stats['average_deviation'] = 0

    if summary_stats['best_deviation'] == float('inf'):
        summary_stats['best_deviation'] = 0

    del summary_stats['total_deviation_sum']

    return {
        'status': 'success',
        'origin': {
            'lat': origin_lat,
            'lon': origin_lon,
            'alt': origin_alt,
        },
        'deviations': deviations,
        'summary': summary_stats,
    }


def build_desired_launch_positions_report(
    drones_config,
    origin_lat: float,
    origin_lon: float,
    origin_alt: float = 0.0,
    heading_deg: float = 0.0,
    sim_mode: Optional[bool] = None,
    trajectory_resolver=None,
):
    """Build desired launch positions with heading rotation applied."""
    import pymap3d as pm

    effective_sim_mode = getattr(Params, 'sim_mode', False) if sim_mode is None else bool(sim_mode)
    normalized_heading = float(heading_deg) % 360.0
    resolve_trajectory = trajectory_resolver or (
        lambda pos_id, current_sim_mode: get_expected_position_from_trajectory(
            pos_id,
            current_sim_mode,
            base_dir=BASE_DIR,
        )
    )
    positions = []

    for drone in drones_config:
        pos_id = drone.get('pos_id', drone.get('hw_id'))
        raw_north, raw_east = resolve_trajectory(pos_id, effective_sim_mode)
        if raw_north is None or raw_east is None:
            continue

        rotated_north, rotated_east = rotate_north_east(raw_north, raw_east, normalized_heading)
        lat, lon, alt = pm.ned2geodetic(
            rotated_north,
            rotated_east,
            0,
            origin_lat,
            origin_lon,
            origin_alt,
        )

        positions.append({
            'pos_id': pos_id,
            'hw_id': drone.get('hw_id'),
            'latitude': lat,
            'longitude': lon,
            'altitude': alt,
            'north': rotated_north,
            'east': rotated_east,
            'trajectory_north': float(raw_north),
            'trajectory_east': float(raw_east),
        })

    positions.sort(key=lambda item: (str(item.get('pos_id')), str(item.get('hw_id'))))

    return {
        'origin': {
            'lat': origin_lat,
            'lon': origin_lon,
            'alt': origin_alt,
        },
        'positions': positions,
        'total_drones': len(positions),
        'heading': normalized_heading,
    }

def compute_origin_from_drone(current_lat, current_lon, intended_north, intended_east):
    """
    Computes the origin lat/lon based on the drone's current lat/lon and intended N,E positions.
    """
    try:
        logger.info(f"Starting origin computation with current_lat={current_lat}, current_lon={current_lon}, intended_north={intended_north}, intended_east={intended_east}")

        # Define the error function to minimize
        def error_function(origin_coords):
            try:
                origin_lat, origin_lon = origin_coords

                # Define the projection
                proj_string = f"+proj=tmerc +lat_0={origin_lat} +lon_0={origin_lon} +k=1 +units=m +ellps=WGS84"
                transformer = Transformer.from_proj(
                    Proj('epsg:4326'),  # WGS84
                    Proj(proj_string),
                    always_xy=True
                )

                # Compute N,E positions of the drone's current lat/lon relative to this origin
                east, north = transformer.transform(current_lon, current_lat)

                # Compute the difference between computed N,E and intended N,E
                delta_north = north - intended_north
                delta_east = east - intended_east

                error = delta_north ** 2 + delta_east ** 2

                logger.debug(f"Origin ({origin_lat}, {origin_lon}): Delta N={delta_north}, Delta E={delta_east}, Error={error}")

                return error
            except Exception as e:
                logger.error(f"Exception in error_function with origin_coords={origin_coords}: {e}", exc_info=True)
                return 1e10  # Return a large error to penalize invalid origins

        # Initial guess for the origin is the drone's current position
        initial_guess = [current_lat, current_lon]
        logger.debug(f"Initial guess for origin: {initial_guess}")

        # Set bounds for latitude and longitude
        bounds = [(-90, 90), (-180, 180)]

        # Use scipy.optimize to minimize the error function
        result = minimize(
            error_function,
            initial_guess,
            method='L-BFGS-B',
            bounds=bounds
        )

        logger.info(f"Optimization result: {result}")

        solution_error = float(result.fun) if getattr(result, 'fun', None) is not None else float('inf')
        solution_coords = getattr(result, 'x', None)
        has_finite_solution = (
            solution_coords is not None
            and len(solution_coords) == 2
            and math.isfinite(solution_coords[0])
            and math.isfinite(solution_coords[1])
        )
        acceptable_residual = solution_error <= 1e-6

        if result.success or (has_finite_solution and acceptable_residual):
            origin_lat, origin_lon = result.x
            if not result.success:
                logger.warning(
                    "Accepting origin optimization despite non-success status because residual is within tolerance: %s (fun=%s)",
                    result.message,
                    solution_error,
                )
            logger.info(f"Origin computed successfully: ({origin_lat}, {origin_lon})")
            return origin_lat, origin_lon
        else:
            logger.error(f"Optimization failed: {result.message}")
            raise Exception(f"Optimization failed: {result.message}")

    except Exception as e:
        logger.error(f"Error computing origin from drone: {e}", exc_info=True)
        raise
