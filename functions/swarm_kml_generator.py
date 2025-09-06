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