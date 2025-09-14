"""
Main Swarm Trajectory Processor
Orchestrates the complete swarm trajectory processing pipeline
"""
import os
import logging
import pandas as pd
from typing import Dict, Any, List

from functions.file_management import ensure_directory_exists, clear_directory
from functions.swarm_analyzer import analyze_swarm_structure, get_drone_config, find_ultimate_leader, fetch_swarm_data
from functions.swarm_global_calculator import calculate_formation_origin, calculate_follower_global_position, calculate_follower_yaw
from functions.swarm_trajectory_smoother import smooth_trajectory_with_waypoints
from functions.swarm_plotter import generate_swarm_plots
from functions.swarm_trajectory_utils import get_swarm_trajectory_folders
from functions.swarm_session_manager import SwarmSessionManager
from src.params import Params

logger = logging.getLogger(__name__)

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

def clear_processed_data(force_clear: bool = False) -> Dict[str, Any]:
    """Clear all processed trajectory data and plots"""
    try:
        folders = get_swarm_trajectory_folders()
        cleared_items = []

        # Clear processed trajectories
        if os.path.exists(folders['processed']):
            files = [f for f in os.listdir(folders['processed']) if f.endswith('.csv')]
            for file in files:
                file_path = os.path.join(folders['processed'], file)
                os.remove(file_path)
                cleared_items.append(f"processed/{file}")
            logger.info(f"Cleared {len(files)} processed trajectory files")

        # Clear plots
        if os.path.exists(folders['plots']):
            files = [f for f in os.listdir(folders['plots']) if f.endswith(('.jpg', '.png'))]
            for file in files:
                file_path = os.path.join(folders['plots'], file)
                os.remove(file_path)
                cleared_items.append(f"plots/{file}")
            logger.info(f"Cleared {len(files)} plot files")

        # Clear session data
        session_manager = SwarmSessionManager()
        session_manager.clear_session()
        cleared_items.append("session_data")

        return {
            'success': True,
            'cleared_items': cleared_items,
            'message': f'Cleared {len(cleared_items)} items successfully'
        }

    except Exception as e:
        logger.error(f"Failed to clear processed data: {e}")
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to clear processed data'
        }

def auto_reload_missing_leaders(uploaded_leaders: List[int]) -> List[int]:
    """Auto-reload trajectory files for unchanged clusters"""
    try:
        folders = get_swarm_trajectory_folders()
        raw_dir = folders['raw']
        reloaded = []

        if not os.path.exists(raw_dir):
            return reloaded

        # Check for existing files that weren't explicitly uploaded this session
        for filename in os.listdir(raw_dir):
            if filename.endswith('.csv') and filename.startswith('Drone '):
                try:
                    drone_id = int(filename.replace('Drone ', '').replace('.csv', ''))
                    if drone_id not in uploaded_leaders:
                        # This file exists but wasn't uploaded this session - auto-include it
                        reloaded.append(drone_id)
                        logger.info(f"Auto-reloaded existing trajectory for drone {drone_id}")
                except ValueError:
                    continue

        return reloaded

    except Exception as e:
        logger.error(f"Failed to auto-reload leaders: {e}")
        return []

def get_processing_recommendation() -> Dict[str, Any]:
    """Get smart recommendation for processing approach"""
    session_manager = SwarmSessionManager()
    return session_manager.get_processing_recommendation()

def process_swarm_trajectories(force_clear: bool = False, auto_reload: bool = True) -> Dict[str, Any]:
    """
    Smart trajectory processing with change detection and session management

    Args:
        force_clear: Force clear all processed data before processing
        auto_reload: Auto-reload existing trajectory files for unchanged clusters
    """
    mode_str = "SITL" if Params.sim_mode else "real"
    logger.info(f"Starting smart swarm trajectory processing in {mode_str} mode")

    try:
        # Initialize session manager
        session_manager = SwarmSessionManager()

        # Get processing recommendation
        recommendation = session_manager.get_processing_recommendation()
        logger.info(f"Processing recommendation: {recommendation['action']}")

        # Handle mandatory clearing scenarios
        if force_clear or recommendation['action'] in ['mandatory_full_reprocess', 'recommended_full_reprocess']:
            clear_result = clear_processed_data()
            if not clear_result['success']:
                return {
                    'success': False,
                    'error': f"Failed to clear data: {clear_result['error']}",
                    'recommendation': recommendation
                }
            logger.info(f"Cleared processed data: {clear_result['message']}")

        # Get uploaded leaders
        uploaded_leaders = session_manager.get_uploaded_leaders()

        # Auto-reload existing files if enabled
        reloaded_leaders = []
        if auto_reload and not force_clear:
            reloaded_leaders = auto_reload_missing_leaders(uploaded_leaders)

        all_available_leaders = sorted(set(uploaded_leaders + reloaded_leaders))

        logger.info(f"Processing leaders: {len(uploaded_leaders)} uploaded, {len(reloaded_leaders)} auto-reloaded")

        if not all_available_leaders:
            return {
                'success': False,
                'error': 'No trajectory files available for processing',
                'recommendation': recommendation,
                'uploaded_count': len(uploaded_leaders)
            }

        # Continue with actual processing
        return _execute_trajectory_processing(all_available_leaders, session_manager, recommendation)

    except Exception as e:
        logger.error(f"Smart processing failed: {e}")
        return {
            'success': False,
            'error': str(e),
            'processing_stage': 'initialization'
        }

def _execute_trajectory_processing(available_leaders: List[int], session_manager: SwarmSessionManager, recommendation: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the actual trajectory processing"""
    mode_str = "SITL" if Params.sim_mode else "real"

    try:
        # Get folder structure
        folders = get_swarm_trajectory_folders()

        # Ensure directories exist
        ensure_directory_exists(folders['processed'])
        ensure_directory_exists(folders['plots'])

        # Step 1: Analyze swarm structure
        swarm_structure = analyze_swarm_structure()
        logger.info(f"Found {len(swarm_structure['top_leaders'])} top leaders")

        # Check for leader structure mismatch (critical edge case)
        missing_leaders = [leader for leader in swarm_structure['top_leaders'] if leader not in available_leaders]
        extra_leaders = [leader for leader in available_leaders if leader not in swarm_structure['top_leaders']]

        if missing_leaders:
            logger.warning(f"Top leaders missing trajectories: {missing_leaders}")
        if extra_leaders:
            logger.info(f"Extra trajectory files uploaded (will be ignored): {extra_leaders}")

        # Filter available leaders to only include valid top leaders
        valid_leaders = [leader for leader in available_leaders if leader in swarm_structure['top_leaders']]

        if not valid_leaders:
            return {
                'success': False,
                'error': 'No valid leader trajectories found for current swarm structure',
                'recommendation': recommendation,
                'available_leaders': available_leaders,
                'expected_leaders': swarm_structure['top_leaders']
            }

        # Step 2: Load leader trajectories
        leader_trajectories = load_leader_trajectories(folders['raw'], valid_leaders)

        if not leader_trajectories:
            return {
                'success': False,
                'error': 'Failed to load leader trajectory files',
                'recommendation': recommendation
            }

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

            except Exception as e:
                logger.error(f"Failed to process drone {hw_id}: {e}")
                processing_stats['errors'] += 1
                continue

        # Step 5: Generate plots
        logger.info("Generating visualization plots...")
        generate_swarm_plots(all_trajectories, swarm_structure, folders['plots'])

        # Step 6: Create processing session
        total_processed = processing_stats['leaders'] + processing_stats['followers']
        processed_leaders = list(leader_trajectories.keys())
        session = session_manager.create_processing_session(processed_leaders, total_processed)

        logger.info(f"Processing complete: {total_processed} drones processed ({processing_stats['leaders']} leaders, {processing_stats['followers']} followers, {processing_stats['errors']} errors)")

        return {
            'success': True,
            'processed_drones': total_processed,
            'statistics': processing_stats,
            'session_id': session.session_id,
            'recommendation': recommendation,
            'processed_leaders': processed_leaders,
            'missing_leaders': missing_leaders,
            'auto_reloaded': extra_leaders  # Leaders that were auto-included
        }

    except Exception as e:
        logger.error(f"Trajectory processing execution failed: {e}")
        return {
            'success': False,
            'error': str(e),
            'processing_stage': 'execution',
            'recommendation': recommendation
        }