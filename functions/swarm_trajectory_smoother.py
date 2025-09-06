"""
Swarm Trajectory Smoother
Smooths trajectories while forcing passage through original waypoints
"""
import numpy as np
import pandas as pd
import logging
from scipy.interpolate import CubicSpline
from src.params import Params

logger = logging.getLogger(__name__)

def smooth_trajectory_with_waypoints(waypoints_df, dt=None):
    """
    Smooth trajectory forcing passage through original waypoints
    
    Input: DataFrame with columns from UI CSV:
        ['Name', 'Latitude', 'Longitude', 'Altitude_MSL_m', 'TimeFromStart_s', 
         'EstimatedSpeed_ms', 'Heading_deg', 'HeadingMode']
    
    Output: DataFrame with smooth trajectory at dt intervals:
        ['t', 'lat', 'lon', 'alt', 'vx', 'vy', 'vz', 'ax', 'ay', 'az', 'yaw', 'mode', 'ledr', 'ledg', 'ledb']
    """
    if dt is None:
        dt = Params.swarm_trajectory_dt
    
    logger.info(f"Smoothing trajectory with {len(waypoints_df)} waypoints at {dt}s intervals")
    
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
    
    # Cubic spline interpolation (forces passage through waypoints)
    lat_spline = CubicSpline(times, lats)
    lon_spline = CubicSpline(times, lons) 
    alt_spline = CubicSpline(times, alts)
    yaw_spline = CubicSpline(times, yaws)
    
    # Generate smooth trajectory
    smooth_lats = lat_spline(all_times)
    smooth_lons = lon_spline(all_times)
    smooth_alts = alt_spline(all_times)
    smooth_yaws = yaw_spline(all_times)
    
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