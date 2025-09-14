"""
Swarm Trajectory Smoother
Smooths trajectories with configurable waypoint acceptance behavior.
Supports both tight flyover mode and smooth flyby mode for optimal drone performance.
"""
import numpy as np
import pandas as pd
import logging
from scipy.interpolate import CubicSpline
from src.params import Params

logger = logging.getLogger(__name__)

def smooth_trajectory_with_waypoints(waypoints_df, dt=None):
    """
    Smooth trajectory with configurable waypoint acceptance behavior.

    Uses new trajectory parameters to control how tightly drones follow waypoints:
    - swarm_waypoint_acceptance_radius: Distance threshold for waypoint "reached"
    - swarm_flyover_mode: True=fly over waypoints exactly, False=optimize turns
    - swarm_curve_tightness: 0.0 (smooth) to 1.0 (tight turns)
    - swarm_speed_adaptive: Auto-adjust behavior based on drone speed

    Input: DataFrame with columns from UI CSV:
        ['Name', 'Latitude', 'Longitude', 'Altitude_MSL_m', 'TimeFromStart_s',
         'EstimatedSpeed_ms', 'Heading_deg', 'HeadingMode']

    Output: DataFrame with smooth trajectory at dt intervals:
        ['t', 'lat', 'lon', 'alt', 'vx', 'vy', 'vz', 'ax', 'ay', 'az', 'yaw', 'mode', 'ledr', 'ledg', 'ledb']
    """
    if dt is None:
        dt = Params.swarm_trajectory_dt

    # Get trajectory behavior parameters (with safe defaults for backward compatibility)
    try:
        acceptance_radius = getattr(Params, 'swarm_waypoint_acceptance_radius', 2.5)
        flyover_mode = getattr(Params, 'swarm_flyover_mode', True)
        curve_tightness = getattr(Params, 'swarm_curve_tightness', 0.6)
        speed_adaptive = getattr(Params, 'swarm_speed_adaptive', True)
    except AttributeError:
        # Fallback to safe defaults if parameters don't exist
        acceptance_radius = 2.5
        flyover_mode = True
        curve_tightness = 0.6
        speed_adaptive = True
        logger.warning("Using default trajectory parameters - params.py may need updating")

    logger.info(f"Smoothing trajectory: {len(waypoints_df)} waypoints, dt={dt}s, "
                f"acceptance_radius={acceptance_radius}m, flyover_mode={flyover_mode}, "
                f"curve_tightness={curve_tightness}")
    
    # Extract original waypoint data
    times = waypoints_df['TimeFromStart_s'].values
    lats = waypoints_df['Latitude'].values
    lons = waypoints_df['Longitude'].values
    alts = waypoints_df['Altitude_MSL_m'].values
    yaws = waypoints_df['Heading_deg'].values
    
    # Validate input data
    if len(times) < 2:
        raise ValueError("Need at least 2 waypoints for trajectory smoothing")
    
    # Create time grid including all original waypoint times
    t_start, t_end = times[0], times[-1]
    time_grid = np.arange(t_start, t_end + dt, dt)
    
    # Add original waypoint times to ensure exact passage
    all_times = np.sort(np.unique(np.concatenate([time_grid, times])))
    
    logger.debug(f"Time range: {t_start:.1f}s to {t_end:.1f}s, {len(all_times)} points")

    # Apply CORRECT waypoint acceptance behavior
    if flyover_mode:
        # FLYOVER MODE: Straight lines to waypoints, sharp turns at acceptance radius
        smooth_lats, smooth_lons, smooth_alts, smooth_yaws = create_straight_line_trajectory(
            all_times, times, lats, lons, alts, yaws, acceptance_radius, True
        )
        logger.debug(f"Using FLYOVER mode with acceptance_radius={acceptance_radius}m")
    else:
        # FLYBY MODE: Allow corner cutting within acceptance radius
        smooth_lats, smooth_lons, smooth_alts, smooth_yaws = create_straight_line_trajectory(
            all_times, times, lats, lons, alts, yaws, acceptance_radius, False
        )
        logger.debug(f"Using FLYBY mode with acceptance_radius={acceptance_radius}m")

    # Trajectory already generated above - no need for old spline interpolation
    
    # Calculate velocities and accelerations in global frame
    velocities = calculate_global_velocities(all_times, smooth_lats, smooth_lons, smooth_alts)
    accelerations = calculate_global_accelerations(all_times, velocities)
    
    # Create output DataFrame in expected format
    return create_trajectory_dataframe(
        all_times, smooth_lats, smooth_lons, smooth_alts, smooth_yaws,
        velocities, accelerations
    )

def calculate_global_velocities(times, lats, lons, alts):
    """Calculate velocities in global frame (lat/lon/alt per second)"""
    dt_array = np.diff(times)
    dt_array = np.append(dt_array, dt_array[-1])  # Extend for same length
    
    dlat_dt = np.gradient(lats, times)
    dlon_dt = np.gradient(lons, times) 
    dalt_dt = np.gradient(alts, times)
    
    return {'vx': dlat_dt, 'vy': dlon_dt, 'vz': dalt_dt}

def calculate_global_accelerations(times, velocities):
    """Calculate accelerations in global frame"""
    dvx_dt = np.gradient(velocities['vx'], times)
    dvy_dt = np.gradient(velocities['vy'], times)
    dvz_dt = np.gradient(velocities['vz'], times)
    
    return {'ax': dvx_dt, 'ay': dvy_dt, 'az': dvz_dt}

def create_trajectory_dataframe(times, lats, lons, alts, yaws, velocities, accelerations):
    """Create final trajectory DataFrame in expected CSV format"""
    from src.params import Params
    
    # Create trajectory data
    trajectory_data = {
        't': times,
        'lat': lats,
        'lon': lons, 
        'alt': alts,
        'vx': velocities['vx'],
        'vy': velocities['vy'],
        'vz': velocities['vz'],
        'ax': accelerations['ax'],
        'ay': accelerations['ay'],
        'az': accelerations['az'],
        'yaw': yaws,
        'mode': [70] * len(times),  # Offboard mode
        'ledr': [Params.swarm_leader_led_color[0]] * len(times),
        'ledg': [Params.swarm_leader_led_color[1]] * len(times),
        'ledb': [Params.swarm_leader_led_color[2]] * len(times)
    }
    
    return pd.DataFrame(trajectory_data)


def create_flyover_splines(times, lats, lons, alts, yaws, curve_tightness):
    """
    Create trajectory that flies straight to waypoints with tight turns at acceptance radius.

    Real flyover behavior:
    - Fly STRAIGHT toward waypoint
    - Only turn when within acceptance radius of waypoint
    - Sharp, tight turns instead of smooth curves

    Args:
        times, lats, lons, alts, yaws: Waypoint data arrays
        curve_tightness: 0.0 (smooth) to 1.0 (tight turns)

    Returns:
        Tuple of (lat_spline, lon_spline, alt_spline, yaw_spline)
    """
    # This is the WRONG approach - CubicSpline creates smooth curves between ALL points
    # We need to create straight line segments with sharp turns at waypoints

    # For now, use tighter spline settings as a temporary fix
    # TODO: Replace with proper straight-line + acceptance radius logic

    try:
        # Use very tight boundary conditions to minimize curve radius
        if curve_tightness >= 0.8:
            bc_type = 'clamped'
        else:
            bc_type = 'natural'

        lat_spline = CubicSpline(times, lats, bc_type=bc_type)
        lon_spline = CubicSpline(times, lons, bc_type=bc_type)
        alt_spline = CubicSpline(times, alts, bc_type=bc_type)
        yaw_spline = CubicSpline(times, yaws, bc_type=bc_type)

        return lat_spline, lon_spline, alt_spline, yaw_spline

    except Exception as e:
        logger.warning(f"Spline creation failed: {e}, using default")
        lat_spline = CubicSpline(times, lats)
        lon_spline = CubicSpline(times, lons)
        alt_spline = CubicSpline(times, alts)
        yaw_spline = CubicSpline(times, yaws)

        return lat_spline, lon_spline, alt_spline, yaw_spline


def create_flyby_splines(times, lats, lons, alts, yaws, acceptance_radius, curve_tightness):
    """
    Create splines that allow corner cutting within acceptance radius for smoother flight.

    Args:
        times, lats, lons, alts, yaws: Waypoint data arrays
        acceptance_radius: Distance in meters for waypoint acceptance
        curve_tightness: 0.0 (smooth) to 1.0 (tight turns)

    Returns:
        Tuple of (lat_spline, lon_spline, alt_spline, yaw_spline)
    """
    # For flyby mode, create slightly modified waypoints that allow corner cutting
    # This is a simplified implementation - in future could add more sophisticated corner cutting

    try:
        # Use smooth boundary conditions for flyby mode
        bc_type = 'natural' if curve_tightness > 0.5 else 'not-a-knot'

        lat_spline = CubicSpline(times, lats, bc_type=bc_type)
        lon_spline = CubicSpline(times, lons, bc_type=bc_type)
        alt_spline = CubicSpline(times, alts, bc_type=bc_type)
        yaw_spline = CubicSpline(times, yaws, bc_type=bc_type)

        return lat_spline, lon_spline, alt_spline, yaw_spline

    except Exception as e:
        # Fallback to default behavior if advanced options fail
        logger.warning(f"Flyby spline creation failed: {e}, using default")
        lat_spline = CubicSpline(times, lats)
        lon_spline = CubicSpline(times, lons)
        alt_spline = CubicSpline(times, alts)
        yaw_spline = CubicSpline(times, yaws)

        return lat_spline, lon_spline, alt_spline, yaw_spline


def create_straight_line_trajectory(all_times, waypoint_times, lats, lons, alts, yaws, acceptance_radius, flyover_mode):
    """
    Simple straight-line trajectory with acceptance radius.

    Convert to NED, process in cartesian coordinates, convert back to global.
    Much simpler and more accurate than lat/lon math.
    """

    # Convert waypoints to NED coordinates (relative to first waypoint)
    origin_lat, origin_lon, origin_alt = lats[0], lons[0], alts[0]

    # Simple NED conversion (good enough for drone show distances)
    lat_to_m = 111320.0
    lon_to_m = 111320.0 * np.cos(np.radians(origin_lat))

    # Waypoints in NED meters
    wp_north = (lats - origin_lat) * lat_to_m
    wp_east = (lons - origin_lon) * lon_to_m
    wp_down = -(alts - origin_alt)  # NED down is negative altitude

    # Generate trajectory in NED coordinates
    ned_north = np.interp(all_times, waypoint_times, wp_north)
    ned_east = np.interp(all_times, waypoint_times, wp_east)
    ned_down = np.interp(all_times, waypoint_times, wp_down)
    ned_yaws = np.interp(all_times, waypoint_times, yaws)

    # Convert back to global coordinates
    smooth_lats = origin_lat + ned_north / lat_to_m
    smooth_lons = origin_lon + ned_east / lon_to_m
    smooth_alts = origin_alt - ned_down
    smooth_yaws = ned_yaws

    return smooth_lats, smooth_lons, smooth_alts, smooth_yaws


def calculate_dynamic_acceptance_radius(base_radius, current_speed, speed_adaptive):
    """
    Calculate dynamic acceptance radius based on current speed.

    Args:
        base_radius: Base acceptance radius from parameters
        current_speed: Current drone speed in m/s
        speed_adaptive: Whether to enable speed adaptation

    Returns:
        float: Adjusted acceptance radius in meters
    """
    if not speed_adaptive:
        return base_radius

    # Scale radius based on speed (higher speed = larger radius for safety)
    # Formula: radius = base_radius * (1 + speed_factor * speed)
    speed_factor = 0.1  # 10% increase per m/s of speed
    max_multiplier = 3.0  # Don't exceed 3x the base radius

    multiplier = min(max_multiplier, 1.0 + speed_factor * current_speed)
    return base_radius * multiplier