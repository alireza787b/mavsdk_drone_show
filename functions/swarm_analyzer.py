"""
Swarm Structure Analyzer
Analyzes swarm data to identify leaders, followers, and hierarchies
"""
import pandas as pd
import logging
import requests
import os

logger = logging.getLogger(__name__)

def get_backend_url():
    """Get backend URL, defaulting to localhost"""
    return os.getenv('BACKEND_URL', 'http://localhost:5000')

def fetch_swarm_data():
    """Fetch swarm data from the backend API"""
    try:
        backend_url = get_backend_url()
        response = requests.get(f"{backend_url}/get-swarm-data", timeout=10)
        
        if response.status_code == 200:
            swarm_data = response.json()
            logger.info(f"Fetched swarm data from API: {len(swarm_data)} drones")
            return swarm_data
        else:
            raise Exception(f"API returned status {response.status_code}: {response.text}")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch swarm data from API: {e}")
        raise Exception(f"Could not connect to backend API: {e}")
    except Exception as e:
        logger.error(f"Error processing swarm data: {e}")
        raise

def analyze_swarm_structure(swarm_data=None):
    """
    Analyze swarm data to identify leaders, followers, and hierarchies
    Args:
        swarm_data: Optional swarm data list. If None, fetches from API.
    Returns: {
        'top_leaders': [1, 2, 23, ...],
        'hierarchies': {1: [2, 3, 4, ...], 2: [5, 6, ...]}
    }
    """
    try:
        # Fetch swarm data from backend API if not provided
        if swarm_data is None:
            swarm_data = fetch_swarm_data()
        
        # Convert to DataFrame for processing
        swarm_df = pd.DataFrame(swarm_data)
        
        # Convert string values to appropriate types
        swarm_df['hw_id'] = pd.to_numeric(swarm_df['hw_id'], errors='coerce')
        swarm_df['follow'] = pd.to_numeric(swarm_df['follow'], errors='coerce')
        swarm_df['offset_n'] = pd.to_numeric(swarm_df['offset_n'], errors='coerce')
        swarm_df['offset_e'] = pd.to_numeric(swarm_df['offset_e'], errors='coerce')
        swarm_df['offset_alt'] = pd.to_numeric(swarm_df['offset_alt'], errors='coerce')
        swarm_df['body_coord'] = pd.to_numeric(swarm_df['body_coord'], errors='coerce')
        
        # Remove any rows with invalid data
        swarm_df = swarm_df.dropna(subset=['hw_id', 'follow'])
        
        logger.info(f"Loaded swarm configuration with {len(swarm_df)} drones")
        
        # Find top leaders (follow == 0)
        top_leaders = swarm_df[swarm_df['follow'] == 0]['hw_id'].tolist()
        logger.info(f"Found {len(top_leaders)} top leaders: {top_leaders}")
        
        # Build hierarchy map for each leader
        hierarchies = {}
        for leader_id in top_leaders:
            followers = get_all_followers(leader_id, swarm_df)
            hierarchies[leader_id] = followers
            logger.debug(f"Leader {leader_id} has {len(followers)} total followers")
        
        return {
            'top_leaders': top_leaders,
            'hierarchies': hierarchies,
            'swarm_config': swarm_df.set_index('hw_id').to_dict('index')
        }
        
    except Exception as e:
        logger.error(f"Failed to analyze swarm structure: {e}")
        raise

def get_all_followers(leader_id, swarm_df):
    """Get all followers for a specific leader (recursive)"""
    direct_followers = swarm_df[swarm_df['follow'] == leader_id]['hw_id'].tolist()
    all_followers = direct_followers.copy()
    
    # Recursively get sub-followers
    for follower in direct_followers:
        sub_followers = get_all_followers(follower, swarm_df)
        all_followers.extend(sub_followers)
    
    return all_followers

def get_drone_config(hw_id, swarm_config):
    """Get configuration for specific drone"""
    if hw_id not in swarm_config:
        raise ValueError(f"Drone {hw_id} not found in swarm configuration")
    return swarm_config[hw_id]

def find_ultimate_leader(hw_id, swarm_df=None):
    """Find the top-level leader for any drone"""
    if swarm_df is None:
        # Fetch swarm data if not provided
        swarm_data = fetch_swarm_data()
        swarm_df = pd.DataFrame(swarm_data)
        # Apply same data type conversions
        swarm_df['hw_id'] = pd.to_numeric(swarm_df['hw_id'], errors='coerce')
        swarm_df['follow'] = pd.to_numeric(swarm_df['follow'], errors='coerce')
        swarm_df = swarm_df.dropna(subset=['hw_id', 'follow'])
    
    current_id = hw_id
    visited = set()
    
    while current_id not in visited:
        visited.add(current_id)
        drone_row = swarm_df[swarm_df['hw_id'] == current_id]
        
        if drone_row.empty:
            raise ValueError(f"Drone {current_id} not found in swarm configuration")
            
        follow_id = drone_row.iloc[0]['follow']
        
        if follow_id == 0:  # This is a top leader
            return current_id
            
        current_id = follow_id
    
    raise ValueError(f"Circular dependency detected for drone {hw_id}")