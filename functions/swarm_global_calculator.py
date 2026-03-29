"""
Swarm Global Coordinate Calculator
Calculates follower positions in global coordinates using per-leader offset
configurations.
"""
import logging
import navpy
from smart_swarm_src.utils import transform_body_to_nea

logger = logging.getLogger(__name__)

def calculate_formation_origin(leader_trajectories):
    """
    Calculate formation origin as center of all leader trajectories
    Returns: {'lat': center_lat, 'lon': center_lon, 'alt': center_alt}
    """
    if not leader_trajectories:
        raise ValueError("No leader trajectories provided")
    
    all_lats, all_lons, all_alts = [], [], []
    
    for leader_id, trajectory in leader_trajectories.items():
        all_lats.extend(trajectory['Latitude'].values)
        all_lons.extend(trajectory['Longitude'].values) 
        all_alts.extend(trajectory['Altitude_MSL_m'].values)
    
    origin = {
        'lat': sum(all_lats) / len(all_lats),
        'lon': sum(all_lons) / len(all_lons),
        'alt': sum(all_alts) / len(all_alts)
    }
    
    logger.info(f"Formation origin: {origin['lat']:.6f}, {origin['lon']:.6f}, {origin['alt']:.1f}m")
    return origin

def calculate_follower_global_position(leader_lat, leader_lon, leader_alt, leader_yaw,
                                     offset_config, formation_origin=None):
    """
    Calculate follower position in global coordinates.

    Offsets are applied in the leader's instantaneous local NED frame so the
    generated follower geometry remains accurate even when the route spans far
    beyond any original formation centroid.
    
    Args:
        leader_lat, leader_lon, leader_alt: Leader's global position
        leader_yaw: Leader's yaw angle in degrees
        offset_config: Dict with offset_x, offset_y, offset_z, frame
        formation_origin: Retained for backward compatibility; no longer used
            for offset geometry.
    """
    try:
        # Apply offset based on coordinate frame
        if offset_config['frame'] == "body":
            # Body coordinate mode: offset_x=Forward, offset_y=Right
            offset_x_ned, offset_y_ned = transform_body_to_nea(
                offset_config['offset_x'], offset_config['offset_y'], leader_yaw
            )
            logger.debug(f"Body offset: Forward={offset_config['offset_x']}, Right={offset_config['offset_y']} -> N={offset_x_ned:.2f}, E={offset_y_ned:.2f}")
        else:
            # NED coordinate mode: offset_x=North, offset_y=East
            offset_x_ned = offset_config['offset_x']
            offset_y_ned = offset_config['offset_y']
            logger.debug(f"NED offset: N={offset_x_ned}, E={offset_y_ned}")

        # Swarm Design defines positive offset_z as Up. Convert to NED down.
        follower_ned = [
            offset_x_ned,
            offset_y_ned,
            -offset_config['offset_z'],
        ]

        # Convert back to global coordinates around the leader's instantaneous
        # position instead of a fixed mission centroid.
        follower_lla = navpy.ned2lla(
            follower_ned,
            leader_lat, leader_lon, leader_alt,
            latlon_unit='deg', alt_unit='m', model='wgs84'
        )
        
        return follower_lla[0], follower_lla[1], follower_lla[2]  # lat, lon, alt
        
    except Exception as e:
        logger.error(f"Failed to calculate follower position: {e}")
        raise

def calculate_follower_yaw(leader_yaw, offset_config):
    """
    Calculate follower yaw angle
    For now, simply copy leader's yaw (can be enhanced later)
    """
    return leader_yaw
