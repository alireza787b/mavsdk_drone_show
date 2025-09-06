"""
Main Swarm Trajectory Processor
Orchestrates the complete swarm trajectory processing pipeline
"""
import os
import logging
import pandas as pd
from typing import Dict, Any

from functions.file_management import ensure_directory_exists, clear_directory
from functions.swarm_analyzer import analyze_swarm_structure, get_drone_config, find_ultimate_leader, fetch_swarm_data
from functions.swarm_global_calculator import calculate_formation_origin, calculate_follower_global_position, calculate_follower_yaw
from functions.swarm_trajectory_smoother import smooth_trajectory_with_waypoints
from functions.swarm_plotter import generate_swarm_plots
from src.params import Params

logger = logging.getLogger(__name__)

def get_swarm_trajectory_folders():
    """Get folder paths following existing pattern"""
    # Get the root project directory (parent of current working directory if in gcs-server)
    import os
    current_dir = os.getcwd()
    if current_dir.endswith('gcs-server'):
        root_dir = os.path.dirname(current_dir)
    else:
        root_dir = current_dir
    
    base_folder = 'shapes_sitl' if Params.sim_mode else 'shapes'
    base_path = os.path.join(root_dir, base_folder)
    
    return {
        'base': base_path,
        'raw': os.path.join(base_path, 'swarm_trajectory', 'raw'),
        'processed': os.path.join(base_path, 'swarm_trajectory', 'processed'),
        'plots': os.path.join(base_path, 'swarm_trajectory', 'plots')
    }

def load_leader_trajectories(raw_dir: str, top_leaders: list) -> Dict[int, pd.DataFrame]:
    """Load drone trajectory CSV files from raw directory"""
    leader_trajectories = {}
    missing_leaders = []
    
    for leader_id in top_leaders:
        csv_path = os.path.join(raw_dir, f'Drone {leader_id}.csv')
        
        if os.path.exists(csv_path):
            try:
                trajectory_df = pd.read_csv(csv_path)
                
                # Validate CSV format (should match UI export format)
                required_columns = ['Name', 'Latitude', 'Longitude', 'Altitude_MSL_m', 
                                  'TimeFromStart_s', 'EstimatedSpeed_ms', 'Heading_deg', 'HeadingMode']
                
                if not all(col in trajectory_df.columns for col in required_columns):
                    logger.error(f"Leader {leader_id} CSV missing required columns")
                    missing_leaders.append(leader_id)
                    continue
                
                leader_trajectories[leader_id] = trajectory_df
                logger.info(f"Loaded drone {leader_id} trajectory with {len(trajectory_df)} waypoints")
                
            except Exception as e:
                logger.error(f"Failed to load drone {leader_id} trajectory: {e}")
                missing_leaders.append(leader_id)
        else:
            logger.warning(f"Drone {leader_id} trajectory file not found: {csv_path}")
            missing_leaders.append(leader_id)
    
    if missing_leaders:
        if Params.swarm_missing_leader_strategy == 'error':
            raise FileNotFoundError(f"Missing leader trajectories: {missing_leaders}")
        else:
            logger.warning(f"Skipping missing leaders: {missing_leaders}")
    
    return leader_trajectories

def calculate_follower_trajectory(leader_trajectory: pd.DataFrame, drone_config: Dict[str, Any], 
                                formation_origin: Dict[str, float]) -> pd.DataFrame:
    """Calculate follower trajectory based on leader trajectory and offset configuration"""
    
    follower_data = []
    
    for _, leader_row in leader_trajectory.iterrows():
        # Calculate follower position
        follower_lat, follower_lon, follower_alt = calculate_follower_global_position(
            leader_row['lat'], leader_row['lon'], leader_row['alt'], leader_row['yaw'],
            drone_config, formation_origin
        )
        
        # Calculate follower yaw
        follower_yaw = calculate_follower_yaw(leader_row['yaw'], drone_config)
        
        # Create follower data point
        follower_point = leader_row.copy()
        follower_point['lat'] = follower_lat
        follower_point['lon'] = follower_lon
        follower_point['alt'] = follower_alt
        follower_point['yaw'] = follower_yaw
        
        # Update LED colors for followers
        follower_point['ledr'] = Params.swarm_follower_led_color[0]
        follower_point['ledg'] = Params.swarm_follower_led_color[1]
        follower_point['ledb'] = Params.swarm_follower_led_color[2]
        
        follower_data.append(follower_point)
    
    return pd.DataFrame(follower_data)

def save_drone_trajectory(hw_id: int, trajectory: pd.DataFrame, processed_dir: str):
    """Save individual drone trajectory to processed directory"""
    ensure_directory_exists(processed_dir)
    
    # Format filename following existing pattern  
    csv_path = os.path.join(processed_dir, f'Drone {hw_id}.csv')
    
    # Save CSV in format expected by execution scripts
    trajectory.to_csv(csv_path, index=False)
    logger.info(f"Saved drone {hw_id} trajectory to {csv_path}")

def process_swarm_trajectories() -> Dict[str, Any]:
    """
    Main processing function following existing process_formation.py pattern
    """
    mode_str = "SITL" if Params.sim_mode else "real"
    logger.info(f"Starting swarm trajectory processing in {mode_str} mode")
    
    try:
        # Get folder structure
        folders = get_swarm_trajectory_folders()
        
        # Ensure directories exist
        ensure_directory_exists(folders['processed'])
        ensure_directory_exists(folders['plots'])
        
        # Step 1: Analyze swarm structure
        swarm_structure = analyze_swarm_structure()
        logger.info(f"Found {len(swarm_structure['top_leaders'])} top leaders")
        
        # Step 2: Load leader trajectories
        leader_trajectories = load_leader_trajectories(folders['raw'], swarm_structure['top_leaders'])
        
        if not leader_trajectories:
            raise ValueError("No leader trajectories found")
        
        # Step 3: Calculate formation origin
        formation_origin = calculate_formation_origin(leader_trajectories)
        
        # Step 4: Process each drone
        all_trajectories = {}
        processing_stats = {'leaders': 0, 'followers': 0, 'errors': 0}
        
        # Load swarm data from API for drone configurations
        swarm_data = fetch_swarm_data()
        swarm_df = pd.DataFrame(swarm_data)
        
        # Convert string values to appropriate types (same as in analyzer)
        swarm_df['hw_id'] = pd.to_numeric(swarm_df['hw_id'], errors='coerce')
        swarm_df['follow'] = pd.to_numeric(swarm_df['follow'], errors='coerce')
        swarm_df['offset_n'] = pd.to_numeric(swarm_df['offset_n'], errors='coerce')
        swarm_df['offset_e'] = pd.to_numeric(swarm_df['offset_e'], errors='coerce')
        swarm_df['offset_alt'] = pd.to_numeric(swarm_df['offset_alt'], errors='coerce')
        swarm_df['body_coord'] = pd.to_numeric(swarm_df['body_coord'], errors='coerce')
        
        # Remove any rows with invalid data
        swarm_df = swarm_df.dropna(subset=['hw_id', 'follow'])
        
        for _, drone_row in swarm_df.iterrows():
            hw_id = int(drone_row['hw_id'])  # Ensure integer type
            
            try:
                if hw_id in swarm_structure['top_leaders']:
                    # Lead drone: smooth uploaded trajectory
                    if hw_id in leader_trajectories:
                        waypoints_df = leader_trajectories[hw_id]
                        trajectory = smooth_trajectory_with_waypoints(waypoints_df)
                        processing_stats['leaders'] += 1
                        logger.info(f"Processed lead drone {hw_id} with {len(trajectory)} trajectory points")
                    else:
                        logger.warning(f"Skipping lead drone {hw_id} - no trajectory uploaded")
                        continue
                        
                else:
                    # Follower: calculate from leader
                    ultimate_leader_id = find_ultimate_leader(hw_id, swarm_df)
                    
                    if ultimate_leader_id not in all_trajectories:
                        logger.warning(f"Skipping follower {hw_id} - leader {ultimate_leader_id} not processed")
                        continue
                    
                    leader_trajectory = all_trajectories[ultimate_leader_id]
                    drone_config = drone_row.to_dict()
                    
                    trajectory = calculate_follower_trajectory(
                        leader_trajectory, drone_config, formation_origin
                    )
                    processing_stats['followers'] += 1
                    logger.info(f"Processed follower {hw_id} following leader {ultimate_leader_id}")
                
                # Save trajectory
                save_drone_trajectory(hw_id, trajectory, folders['processed'])
                all_trajectories[hw_id] = trajectory
                
                logger.debug(f"Processed drone {hw_id} ({len(trajectory)} points)")
                
            except Exception as e:
                logger.error(f"Failed to process drone {hw_id}: {e}")
                processing_stats['errors'] += 1
                continue
        
        # Step 5: Generate plots
        logger.info("Generating visualization plots...")
        generate_swarm_plots(all_trajectories, swarm_structure, folders['plots'])
        
        # Note: KML files are generated on-demand when requested (no pre-generation needed)
        
        # Summary
        total_processed = processing_stats['leaders'] + processing_stats['followers']
        logger.info(f"Processing complete: {total_processed} drones processed ({processing_stats['leaders']} leaders, {processing_stats['followers']} followers, {processing_stats['errors']} errors)")
        
        return {
            'success': True,
            'processed_drones': total_processed,
            'statistics': processing_stats,
            'folders': folders
        }
        
    except Exception as e:
        logger.error(f"Swarm trajectory processing failed: {e}")
        return {'success': False, 'error': str(e)}