"""
Swarm Structure Analyzer
Analyzes swarm data to identify leaders, followers, and hierarchies
"""
import pandas as pd
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _validate_follow_chains(swarm_df):
    """Reject follow graphs with cycles or missing parent references."""
    follow_map = {
        int(row['hw_id']): int(row['follow'])
        for _, row in swarm_df.iterrows()
    }

    for hw_id in follow_map:
        current_id = hw_id
        visited = set()

        while current_id != 0:
            if current_id in visited:
                raise ValueError(f"Circular dependency detected involving drone {current_id}")
            visited.add(current_id)

            if current_id not in follow_map:
                raise ValueError(f"Drone {hw_id} references missing leader {current_id}")

            current_id = follow_map[current_id]

def get_backend_url():
    """Get backend URL, defaulting to localhost"""
    return os.getenv('BACKEND_URL', 'http://localhost:5030')

def fetch_swarm_data():
    """Load swarm data locally, falling back to the backend API if needed."""
    try:
        from config import load_swarm

        swarm_data = load_swarm()
        if isinstance(swarm_data, list):
            logger.info(f"Loaded swarm data locally: {len(swarm_data)} drones")
            return swarm_data
    except Exception as e:
        logger.warning(f"Local swarm config load failed, falling back to API: {e}")

    try:
        backend_url = get_backend_url()
        response = requests.get(f"{backend_url}/api/v1/config/swarm", timeout=10)
        
        if response.status_code == 200:
            swarm_data = response.json()
            if isinstance(swarm_data, dict) and isinstance(swarm_data.get("assignments"), list):
                swarm_data = swarm_data["assignments"]
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
        swarm_df['offset_x'] = pd.to_numeric(swarm_df['offset_x'], errors='coerce')
        swarm_df['offset_y'] = pd.to_numeric(swarm_df['offset_y'], errors='coerce')
        swarm_df['offset_z'] = pd.to_numeric(swarm_df['offset_z'], errors='coerce')
        
        # Remove any rows with invalid data
        swarm_df = swarm_df.dropna(subset=['hw_id', 'follow'])
        swarm_df['hw_id'] = swarm_df['hw_id'].astype(int)
        swarm_df['follow'] = swarm_df['follow'].astype(int)

        _validate_follow_chains(swarm_df)
        
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

def get_all_followers(leader_id, swarm_df, lineage=None):
    """Get all followers for a specific leader while rejecting circular chains."""
    lineage = set() if lineage is None else set(lineage)
    if leader_id in lineage:
        raise ValueError(f"Circular dependency detected involving drone {leader_id}")

    lineage.add(leader_id)
    direct_followers = swarm_df[swarm_df['follow'] == leader_id]['hw_id'].tolist()
    all_followers = direct_followers.copy()

    # Recursively get sub-followers while preserving the current ancestry path.
    for follower in direct_followers:
        sub_followers = get_all_followers(follower, swarm_df, lineage)
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
