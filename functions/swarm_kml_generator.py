"""
Swarm Trajectory KML Generator
Generates KML files for Google Earth visualization with time-based animation
"""
import os
import logging
import pandas as pd
from datetime import datetime, timedelta
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString

logger = logging.getLogger(__name__)

def generate_kml_for_drone(drone_id: int, trajectory_df: pd.DataFrame, output_dir: str) -> str:
    """
    Generate KML file for a single drone's trajectory with time animation
    
    Args:
        drone_id: Drone hardware ID
        trajectory_df: DataFrame with columns [t, lat, lon, alt, ...]
        output_dir: Directory to save KML file
    
    Returns:
        str: Path to generated KML file
    """
    try:
        # Create KML root structure
        kml = Element('kml', xmlns='http://www.opengis.net/kml/2.2')
        document = SubElement(kml, 'Document')
        
        # Document metadata
        name = SubElement(document, 'name')
        name.text = f'Drone {drone_id} Trajectory'
        
        description = SubElement(document, 'description')
        description.text = f'Swarm trajectory for Drone {drone_id} with {len(trajectory_df)} waypoints'
        
        # Define styles for drone visualization
        _add_drone_styles(document, drone_id)
        
        # Create animated trajectory with time stamps
        _add_animated_trajectory(document, drone_id, trajectory_df)
        
        # Add static path line for reference
        _add_static_path(document, drone_id, trajectory_df)
        
        # Generate formatted KML string
        rough_string = tostring(kml, encoding='unicode')
        reparsed = parseString(rough_string)
        formatted_kml = reparsed.toprettyxml(indent='  ')
        
        # Save to file
        kml_filename = f'Drone {drone_id}_trajectory.kml'
        kml_path = os.path.join(output_dir, kml_filename)
        
        with open(kml_path, 'w', encoding='utf-8') as f:
            f.write(formatted_kml)
        
        logger.info(f"Generated KML for Drone {drone_id}: {kml_path}")
        return kml_path
        
    except Exception as e:
        logger.error(f"Failed to generate KML for Drone {drone_id}: {e}")
        raise

def _add_drone_styles(document: Element, drone_id: int):
    """Add KML styles for drone visualization"""
    
    # Animated drone icon style
    drone_style = SubElement(document, 'Style', id=f'drone{drone_id}_animated')
    icon_style = SubElement(drone_style, 'IconStyle')
    
    # Scale and color
    scale = SubElement(icon_style, 'scale')
    scale.text = '1.2'
    
    # Use drone icon (or default placemark)
    icon = SubElement(icon_style, 'Icon')
    href = SubElement(icon, 'href')
    href.text = 'http://maps.google.com/mapfiles/kml/shapes/airports.png'
    
    # Label style
    label_style = SubElement(drone_style, 'LabelStyle')
    label_scale = SubElement(label_style, 'scale')
    label_scale.text = '0.8'
    
    # Path line style
    path_style = SubElement(document, 'Style', id=f'drone{drone_id}_path')
    line_style = SubElement(path_style, 'LineStyle')
    
    # Color based on drone ID (cycling through colors)
    colors = ['ff0000ff', 'ff00ff00', 'ffff0000', 'ff00ffff', 'ffff00ff', 'ffffff00']
    color = SubElement(line_style, 'color')
    color.text = colors[drone_id % len(colors)]  # Cycle through colors
    
    width = SubElement(line_style, 'width')
    width.text = '3'

def _add_animated_trajectory(document: Element, drone_id: int, trajectory_df: pd.DataFrame):
    """Add time-animated trajectory points"""
    
    # Create folder for trajectory points
    folder = SubElement(document, 'Folder')
    folder_name = SubElement(folder, 'name')
    folder_name.text = f'Drone {drone_id} Animation'
    
    # Set base time (current time for demo, could be configurable)
    base_time = datetime.now()
    
    # Sample points for animation (every 5 seconds to avoid too many points)
    sample_interval = 5.0  # seconds
    sampled_df = trajectory_df[trajectory_df['t'] % sample_interval == 0].copy()
    
    for _, row in sampled_df.iterrows():
        placemark = SubElement(folder, 'Placemark')
        
        # Point name with timestamp
        name = SubElement(placemark, 'name')
        name.text = f'Drone {drone_id} @ T+{row["t"]:.1f}s'
        
        # Description with flight data
        desc = SubElement(placemark, 'description')
        desc.text = f'''
        <![CDATA[
        <b>Drone {drone_id} Flight Data</b><br/>
        Time: {row["t"]:.2f}s<br/>
        Altitude: {row["alt"]:.1f}m MSL<br/>
        Coordinates: {row["lat"]:.6f}, {row["lon"]:.6f}<br/>
        ]]>
        '''
        
        # Time span for animation
        time_span = SubElement(placemark, 'TimeSpan')
        begin = SubElement(time_span, 'begin')
        end = SubElement(time_span, 'end')
        
        point_time = base_time + timedelta(seconds=row['t'])
        next_time = base_time + timedelta(seconds=row['t'] + sample_interval)
        
        begin.text = point_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        end.text = next_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Style reference
        style_url = SubElement(placemark, 'styleUrl')
        style_url.text = f'#drone{drone_id}_animated'
        
        # Point coordinates
        point = SubElement(placemark, 'Point')
        coordinates = SubElement(point, 'coordinates')
        coordinates.text = f'{row["lon"]:.8f},{row["lat"]:.8f},{row["alt"]:.2f}'
        
        # Altitude mode
        altitude_mode = SubElement(point, 'altitudeMode')
        altitude_mode.text = 'absolute'

def _add_static_path(document: Element, drone_id: int, trajectory_df: pd.DataFrame):
    """Add static path line for complete trajectory overview"""
    
    placemark = SubElement(document, 'Placemark')
    
    name = SubElement(placemark, 'name')
    name.text = f'Drone {drone_id} Complete Path'
    
    description = SubElement(placemark, 'description')
    description.text = f'''
    <![CDATA[
    <b>Complete trajectory path for Drone {drone_id}</b><br/>
    Total waypoints: {len(trajectory_df)}<br/>
    Duration: {trajectory_df["t"].max():.1f} seconds<br/>
    Max altitude: {trajectory_df["alt"].max():.1f}m MSL<br/>
    Min altitude: {trajectory_df["alt"].min():.1f}m MSL<br/>
    ]]>
    '''
    
    # Style reference
    style_url = SubElement(placemark, 'styleUrl')
    style_url.text = f'#drone{drone_id}_path'
    
    # LineString for path
    line_string = SubElement(placemark, 'LineString')
    
    # Tessellate for ground following
    tessellate = SubElement(line_string, 'tessellate')
    tessellate.text = '1'
    
    # Altitude mode
    altitude_mode = SubElement(line_string, 'altitudeMode')
    altitude_mode.text = 'absolute'
    
    # Coordinates (sample every few points to reduce file size)
    coords_list = []
    sample_step = max(1, len(trajectory_df) // 1000)  # Max 1000 points
    
    for i in range(0, len(trajectory_df), sample_step):
        row = trajectory_df.iloc[i]
        coords_list.append(f'{row["lon"]:.8f},{row["lat"]:.8f},{row["alt"]:.2f}')
    
    coordinates = SubElement(line_string, 'coordinates')
    coordinates.text = ' '.join(coords_list)

def generate_cluster_kml(cluster_leader_id: int, cluster_drones: list, processed_dir: str, output_dir: str) -> str:
    """
    Generate KML file for a complete cluster (leader + followers) with multiple trajectories
    
    Args:
        cluster_leader_id: ID of the cluster leader
        cluster_drones: List of all drone IDs in cluster (leader + followers)
        processed_dir: Directory containing processed CSV files
        output_dir: Directory to save KML file
    
    Returns:
        str: Path to generated cluster KML file
    """
    try:
        # Create KML root structure
        kml = Element('kml', xmlns='http://www.opengis.net/kml/2.2')
        document = SubElement(kml, 'Document')
        
        # Document metadata
        name = SubElement(document, 'name')
        name.text = f'Cluster {cluster_leader_id} Formation'
        
        description = SubElement(document, 'description')
        description.text = f'Complete swarm cluster formation with {len(cluster_drones)} drones (Leader: {cluster_leader_id})'
        
        # Define styles for all drones in cluster
        _add_cluster_styles(document, cluster_drones, cluster_leader_id)
        
        # Load all drone trajectories
        cluster_trajectories = {}
        for drone_id in cluster_drones:
            csv_filename = f'Drone {drone_id}.csv'
            csv_path = os.path.join(processed_dir, csv_filename)
            
            if os.path.exists(csv_path):
                try:
                    trajectory_df = pd.read_csv(csv_path)
                    required_cols = ['t', 'lat', 'lon', 'alt']
                    if all(col in trajectory_df.columns for col in required_cols):
                        cluster_trajectories[drone_id] = trajectory_df
                        logger.debug(f"Loaded trajectory for drone {drone_id} in cluster {cluster_leader_id}")
                    else:
                        logger.warning(f"Missing required columns for drone {drone_id}")
                except Exception as e:
                    logger.warning(f"Failed to load trajectory for drone {drone_id}: {e}")
            else:
                logger.warning(f"Trajectory file not found for drone {drone_id}: {csv_path}")
        
        if not cluster_trajectories:
            raise ValueError(f"No valid trajectories found for cluster {cluster_leader_id}")
        
        # Create folder for each drone's trajectory
        for drone_id, trajectory_df in cluster_trajectories.items():
            drone_folder = SubElement(document, 'Folder')
            folder_name = SubElement(drone_folder, 'name')
            folder_name.text = f'{"Leader" if drone_id == cluster_leader_id else "Follower"} Drone {drone_id}'
            
            # Add animated trajectory for this drone
            _add_cluster_animated_trajectory(drone_folder, drone_id, trajectory_df, cluster_leader_id)
            
            # Add static path for this drone
            _add_cluster_static_path(drone_folder, drone_id, trajectory_df, cluster_leader_id)
        
        # Add cluster overview folder
        _add_cluster_overview(document, cluster_trajectories, cluster_leader_id)
        
        # Generate formatted KML string
        rough_string = tostring(kml, encoding='unicode')
        reparsed = parseString(rough_string)
        formatted_kml = reparsed.toprettyxml(indent='  ')
        
        # Save to file
        kml_filename = f'Cluster_Leader_{cluster_leader_id}.kml'
        kml_path = os.path.join(output_dir, kml_filename)
        
        with open(kml_path, 'w', encoding='utf-8') as f:
            f.write(formatted_kml)
        
        logger.info(f"Generated cluster KML for Leader {cluster_leader_id} with {len(cluster_trajectories)} drones: {kml_path}")
        return kml_path
        
    except Exception as e:
        logger.error(f"Failed to generate cluster KML for Leader {cluster_leader_id}: {e}")
        raise

def _add_cluster_styles(document: Element, cluster_drones: list, leader_id: int):
    """Add KML styles for all drones in cluster with distinct colors"""
    
    # Enhanced color palette for better distinction
    colors = [
        'ff0000ff',  # Red - typically for leader
        'ff00ff00',  # Green
        'ffff0000',  # Blue  
        'ff00ffff',  # Yellow
        'ffff00ff',  # Magenta
        'ffffff00',  # Cyan
        'ff8000ff',  # Orange
        'ff0080ff',  # Pink
        'ff80ff00',  # Lime
        'ff8080ff',  # Light red
        'ff00ff80',  # Light green
        'ffff8000',  # Light blue
    ]
    
    for i, drone_id in enumerate(cluster_drones):
        # Use specific color for leader (red), cycle others
        if drone_id == leader_id:
            color = 'ff0000ff'  # Red for leader
            icon_href = 'http://maps.google.com/mapfiles/kml/shapes/airports.png'
            scale = '1.5'  # Larger for leader
        else:
            color = colors[(i % len(colors))]
            icon_href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'
            scale = '1.2'
        
        # Animated drone icon style
        drone_style = SubElement(document, 'Style', id=f'cluster_drone{drone_id}_animated')
        icon_style = SubElement(drone_style, 'IconStyle')
        
        icon_scale = SubElement(icon_style, 'scale')
        icon_scale.text = scale
        
        icon_color = SubElement(icon_style, 'color')
        icon_color.text = color
        
        icon = SubElement(icon_style, 'Icon')
        href = SubElement(icon, 'href')
        href.text = icon_href
        
        # Label style
        label_style = SubElement(drone_style, 'LabelStyle')
        label_scale = SubElement(label_style, 'scale')
        label_scale.text = '0.9'
        
        # Path line style
        path_style = SubElement(document, 'Style', id=f'cluster_drone{drone_id}_path')
        line_style = SubElement(path_style, 'LineStyle')
        
        path_color = SubElement(line_style, 'color')
        path_color.text = color
        
        width = SubElement(line_style, 'width')
        width.text = '4' if drone_id == leader_id else '2'

def _add_cluster_animated_trajectory(folder: Element, drone_id: int, trajectory_df: pd.DataFrame, leader_id: int):
    """Add time-animated trajectory points for cluster drone"""
    
    # Set base time (current time for demo)
    base_time = datetime.now()
    
    # Sample interval for animation (every 10 seconds for clusters to avoid overcrowding)
    sample_interval = 10.0  # seconds
    sampled_df = trajectory_df[trajectory_df['t'] % sample_interval == 0].copy()
    
    for _, row in sampled_df.iterrows():
        placemark = SubElement(folder, 'Placemark')
        
        # Point name with timestamp
        name = SubElement(placemark, 'name')
        role = "Leader" if drone_id == leader_id else "Follower"
        name.text = f'{role} {drone_id} @ T+{row["t"]:.1f}s'
        
        # Description with flight data
        desc = SubElement(placemark, 'description')
        desc.text = f'''
        <![CDATA[
        <b>{role} Drone {drone_id} Flight Data</b><br/>
        Time: {row["t"]:.2f}s<br/>
        Latitude: {row["lat"]:.6f}°<br/>
        Longitude: {row["lon"]:.6f}°<br/>
        Altitude: {row["alt"]:.1f}m MSL<br/>
        Speed: {getattr(row, 'speed', 'N/A')}<br/>
        Heading: {getattr(row, 'yaw', 'N/A')}°<br/>
        ]]>
        '''
        
        # Time span for animation
        time_span = SubElement(placemark, 'TimeSpan')
        begin = SubElement(time_span, 'begin')
        end = SubElement(time_span, 'end')
        
        point_time = base_time + timedelta(seconds=row['t'])
        next_time = base_time + timedelta(seconds=row['t'] + sample_interval)
        
        begin.text = point_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        end.text = next_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Style reference
        style_url = SubElement(placemark, 'styleUrl')
        style_url.text = f'#cluster_drone{drone_id}_animated'
        
        # Point coordinates
        point = SubElement(placemark, 'Point')
        coordinates = SubElement(point, 'coordinates')
        coordinates.text = f'{row["lon"]:.8f},{row["lat"]:.8f},{row["alt"]:.2f}'
        
        # Altitude mode
        altitude_mode = SubElement(point, 'altitudeMode')
        altitude_mode.text = 'absolute'

def _add_cluster_static_path(folder: Element, drone_id: int, trajectory_df: pd.DataFrame, leader_id: int):
    """Add static path line for drone in cluster"""
    
    placemark = SubElement(folder, 'Placemark')
    
    name = SubElement(placemark, 'name')
    role = "Leader" if drone_id == leader_id else "Follower"
    name.text = f'{role} {drone_id} Complete Path'
    
    description = SubElement(placemark, 'description')
    description.text = f'''
    <![CDATA[
    <b>Complete trajectory path for {role} Drone {drone_id}</b><br/>
    Total waypoints: {len(trajectory_df)}<br/>
    Duration: {trajectory_df["t"].max():.1f} seconds<br/>
    Max altitude: {trajectory_df["alt"].max():.1f}m MSL<br/>
    Min altitude: {trajectory_df["alt"].min():.1f}m MSL<br/>
    Distance covered: {_calculate_path_distance(trajectory_df):.1f}m<br/>
    ]]>
    '''
    
    # Style reference
    style_url = SubElement(placemark, 'styleUrl')
    style_url.text = f'#cluster_drone{drone_id}_path'
    
    # LineString for path
    line_string = SubElement(placemark, 'LineString')
    
    # Tessellate for ground following
    tessellate = SubElement(line_string, 'tessellate')
    tessellate.text = '1'
    
    # Altitude mode
    altitude_mode = SubElement(line_string, 'altitudeMode')
    altitude_mode.text = 'absolute'
    
    # Coordinates (sample to keep file manageable)
    coords_list = []
    sample_step = max(1, len(trajectory_df) // 500)  # Max 500 points per drone
    
    for i in range(0, len(trajectory_df), sample_step):
        row = trajectory_df.iloc[i]
        coords_list.append(f'{row["lon"]:.8f},{row["lat"]:.8f},{row["alt"]:.2f}')
    
    coordinates = SubElement(line_string, 'coordinates')
    coordinates.text = ' '.join(coords_list)

def _add_cluster_overview(document: Element, cluster_trajectories: dict, leader_id: int):
    """Add cluster overview with formation statistics"""
    
    overview_folder = SubElement(document, 'Folder')
    folder_name = SubElement(overview_folder, 'name')
    folder_name.text = f'Cluster {leader_id} Overview'
    
    # Calculate cluster statistics
    total_waypoints = sum(len(df) for df in cluster_trajectories.values())
    max_duration = max(df['t'].max() for df in cluster_trajectories.values())
    
    # Formation center point (average of all starting positions)
    start_lats = [df['lat'].iloc[0] for df in cluster_trajectories.values()]
    start_lons = [df['lon'].iloc[0] for df in cluster_trajectories.values()]
    start_alts = [df['alt'].iloc[0] for df in cluster_trajectories.values()]
    
    center_lat = sum(start_lats) / len(start_lats)
    center_lon = sum(start_lons) / len(start_lons)
    center_alt = sum(start_alts) / len(start_alts)
    
    # Create center point placemark
    placemark = SubElement(overview_folder, 'Placemark')
    
    name = SubElement(placemark, 'name')
    name.text = f'Cluster {leader_id} Formation Center'
    
    description = SubElement(placemark, 'description')
    description.text = f'''
    <![CDATA[
    <b>Cluster {leader_id} Formation Statistics</b><br/>
    Leader Drone: {leader_id}<br/>
    Total Drones: {len(cluster_trajectories)}<br/>
    Formation Center: {center_lat:.6f}°, {center_lon:.6f}°<br/>
    Average Start Altitude: {center_alt:.1f}m MSL<br/>
    Total Waypoints: {total_waypoints}<br/>
    Mission Duration: {max_duration:.1f} seconds<br/>
    <br/>
    <b>Drone List:</b><br/>
    {"<br/>".join([f"Drone {did}: {len(df)} waypoints" for did, df in cluster_trajectories.items()])}
    ]]>
    '''
    
    # Center point
    point = SubElement(placemark, 'Point')
    coordinates = SubElement(point, 'coordinates')
    coordinates.text = f'{center_lon:.8f},{center_lat:.8f},{center_alt:.2f}'
    
    altitude_mode = SubElement(point, 'altitudeMode')
    altitude_mode.text = 'absolute'

def _calculate_path_distance(trajectory_df: pd.DataFrame) -> float:
    """Calculate approximate path distance in meters"""
    try:
        import math
        
        total_distance = 0.0
        for i in range(1, len(trajectory_df)):
            lat1, lon1, alt1 = trajectory_df.iloc[i-1][['lat', 'lon', 'alt']]
            lat2, lon2, alt2 = trajectory_df.iloc[i][['lat', 'lon', 'alt']]
            
            # Haversine formula for ground distance
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
            ground_dist = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)) * 6371000  # Earth radius in meters
            
            # Add altitude difference
            alt_diff = abs(alt2 - alt1)
            total_distance += math.sqrt(ground_dist**2 + alt_diff**2)
        
        return total_distance
    except:
        return 0.0

def generate_swarm_kml(processed_dir: str, plots_dir: str) -> dict:
    """
    Generate KML files for all processed drone trajectories
    
    Args:
        processed_dir: Directory containing processed CSV files
        plots_dir: Directory to save KML files (reuse plots directory)
        
    Returns:
        dict: {drone_id: kml_file_path} mapping
    """
    kml_files = {}
    
    try:
        # Ensure output directory exists
        os.makedirs(plots_dir, exist_ok=True)
        
        # Process all drone CSV files
        for filename in os.listdir(processed_dir):
            if filename.startswith('Drone ') and filename.endswith('.csv'):
                # Extract drone ID from filename "Drone X.csv"
                try:
                    drone_id = int(filename.split(' ')[1].split('.')[0])
                except (IndexError, ValueError):
                    logger.warning(f"Could not parse drone ID from filename: {filename}")
                    continue
                
                # Load trajectory data
                csv_path = os.path.join(processed_dir, filename)
                trajectory_df = pd.read_csv(csv_path)
                
                # Validate required columns
                required_cols = ['t', 'lat', 'lon', 'alt']
                if not all(col in trajectory_df.columns for col in required_cols):
                    logger.warning(f"Missing required columns in {filename}")
                    continue
                
                # Generate KML
                kml_path = generate_kml_for_drone(drone_id, trajectory_df, plots_dir)
                kml_files[drone_id] = kml_path
        
        logger.info(f"Generated {len(kml_files)} KML files")
        return kml_files
        
    except Exception as e:
        logger.error(f"Failed to generate swarm KML files: {e}")
        return {}