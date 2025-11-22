#gcs-server/config.py
import csv
import os
import logging
import subprocess
import requests
from params import Params
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, Params.config_csv_name)
SWARM_FILE_PATH = os.path.join(BASE_DIR, Params.swarm_csv_name)

logger = logging.getLogger(__name__)

# Define the expected column order
# Note: x,y removed - positions are now always fetched from trajectory CSV (single source of truth)
CONFIG_COLUMNS = ['hw_id', 'pos_id', 'ip', 'mavlink_port', 'serial_port', 'baudrate']
SWARM_COLUMNS = ['hw_id' , 'follow' , 'offset_n' , 'offset_e' , 'offset_alt' , 'body_coord']


def load_csv(file_path):
    """General function to load data from a CSV file."""
    data = []
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return data

    try:
        with open(file_path, mode='r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                data.append(row)

        if not data:
            logger.warning(f"File is empty: {file_path}")
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
    except csv.Error as e:
        logger.error(f"Error reading CSV file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error loading file {file_path}: {e}")

    return data

def save_csv(data, file_path, fieldnames=None):
    """General function to save data to a CSV file with a specified column order."""
    if not data:
        logger.warning(f"No data provided to save in {file_path}. Operation aborted.")
        return

    try:
        with open(file_path, mode='w', newline='') as file:
            # Use the provided fieldnames if available, otherwise use the keys from the data
            writer = csv.DictWriter(file, fieldnames=fieldnames or data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        logger.info(f"Data successfully saved to {file_path}")
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
    except csv.Error as e:
        logger.error(f"Error writing CSV file {file_path}: {e}")
    except IOError as e:
        logger.error(f"IO error saving file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error saving file {file_path}: {e}")

def load_config(file_path=CONFIG_FILE_PATH):
    return load_csv(file_path)

def save_config(config, file_path=CONFIG_FILE_PATH):
    # Pass the expected column order to ensure consistent column placement
    save_csv(config, file_path, fieldnames=CONFIG_COLUMNS)

def load_swarm(file_path=SWARM_FILE_PATH):
    return load_csv(file_path)

def save_swarm(swarm, file_path=SWARM_FILE_PATH):
    save_csv(swarm, file_path,fieldnames=SWARM_COLUMNS)


def get_gcs_git_report():
    """Retrieve the Git status of the GCS."""
    try:
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).strip().decode('utf-8')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf-8')
        author_name = subprocess.check_output(['git', 'show', '-s', '--format=%an', commit]).strip().decode('utf-8')
        author_email = subprocess.check_output(['git', 'show', '-s', '--format=%ae', commit]).strip().decode('utf-8')
        commit_date = subprocess.check_output(['git', 'show', '-s', '--format=%cd', '--date=iso-strict', commit]).strip().decode('utf-8')
        commit_message = subprocess.check_output(['git', 'show', '-s', '--format=%B', commit]).strip().decode('utf-8')
        remote_url = subprocess.check_output(['git', 'config', '--get', 'remote.origin.url']).strip().decode('utf-8')
        tracking_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}']).strip().decode('utf-8')
        status = subprocess.check_output(['git', 'status', '--porcelain']).strip().decode('utf-8')

        return {
            'branch': branch,
            'commit': commit,
            'author_name': author_name,
            'author_email': author_email,
            'commit_date': commit_date,
            'commit_message': commit_message,
            'remote_url': remote_url,
            'tracking_branch': tracking_branch,
            'status': 'clean' if not status else 'dirty',
            'uncommitted_changes': status.splitlines() if status else []
        }
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get Git status: {e}")
        return {'error': f"Git command failed: {str(e)}"}

def get_drone_git_status(drone_uri):
    """Retrieve the Git status from a specific drone."""
    try:
        logging.debug(f"Sending request to {drone_uri}/get-git-status")
        response = requests.get(f"{drone_uri}/get-git-status")  # Make sure it's `requests`
        logging.debug(f"Received response with status code {response.status_code}")

        if response.status_code == 200:
            try:
                json_data = response.json()
                logging.debug(f"Response JSON: {json_data}")
                return json_data
            except ValueError as ve:
                logging.error(f"Error decoding JSON: {str(ve)}")
                return {'error': 'Failed to decode JSON from response'}
        else:
            logging.error(f"Failed to retrieve status, status code: {response.status_code}")
            return {'error': f"Failed to retrieve status from {drone_uri}"}
    except Exception as e:
        logging.error(f"Error contacting drone {drone_uri}: {str(e)}")
        return {'error': f"Error contacting drone {drone_uri}: {str(e)}"}


def validate_and_process_config(config_data, sim_mode=None):
    """
    Validate drone configuration (positions now come from trajectory CSV only).

    This function:
    1. Validates trajectory CSV exists for each pos_id
    2. Detects duplicate pos_id values (collision risk)
    3. Identifies missing trajectory files
    4. Tracks role swaps (hw_id ≠ pos_id)
    5. Removes x,y fields from config (no longer stored in config.csv)
    6. Returns comprehensive validation report

    NOTE: x,y positions are NOT stored in config.csv. They are always fetched
    from trajectory CSV files (single source of truth). Use get_all_drone_positions()
    or /get-drone-positions API to retrieve positions.

    Args:
        config_data (list): List of drone config dictionaries
        sim_mode (bool): Whether in simulation mode (affects trajectory path)

    Returns:
        dict: Validation report with updated_config, warnings, and changes
    """
    from origin import _get_expected_position_from_trajectory

    # Detect sim_mode if not provided
    if sim_mode is None:
        sim_mode = getattr(Params, 'sim_mode', False)

    # Initialize tracking structures
    updated_config = []
    warnings = {
        "duplicates": [],
        "missing_trajectories": [],
        "role_swaps": []
    }
    changes = {
        "pos_id_changes": []
    }

    # Track pos_id usage for duplicate detection
    pos_id_usage = defaultdict(list)

    # Load original config for comparison
    original_config_list = load_config()
    original_config = {int(d.get('hw_id')): d for d in original_config_list if d.get('hw_id')}

    # Process each drone in new config
    for drone in config_data:
        try:
            hw_id = int(drone.get('hw_id'))
            pos_id = drone.get('pos_id')

            if not pos_id:
                # Fallback: if no pos_id, assume pos_id == hw_id
                pos_id = hw_id
                drone['pos_id'] = pos_id
            else:
                pos_id = int(pos_id)

            # Track pos_id usage for duplicate detection
            pos_id_usage[pos_id].append(hw_id)

            # Track pos_id changes
            if hw_id in original_config:
                orig_pos_id = int(original_config[hw_id].get('pos_id', hw_id))
                if orig_pos_id != pos_id:
                    changes["pos_id_changes"].append({
                        "hw_id": hw_id,
                        "old_pos_id": orig_pos_id,
                        "new_pos_id": pos_id
                    })

            # Track role swaps
            if hw_id != pos_id:
                warnings["role_swaps"].append({
                    "hw_id": hw_id,
                    "pos_id": pos_id
                })

            # Check if trajectory file exists for this pos_id
            expected_north, expected_east = _get_expected_position_from_trajectory(pos_id, sim_mode)

            if expected_north is None or expected_east is None:
                # Missing trajectory file
                warnings["missing_trajectories"].append({
                    "hw_id": hw_id,
                    "pos_id": pos_id,
                    "message": f"Trajectory file 'Drone {pos_id}.csv' not found"
                })

            # Note: x,y removed from config.csv - positions always come from trajectory CSV
            # Just copy the drone config without x,y fields
            updated_drone = dict(drone)
            # Remove x,y if they exist in input (for backward compatibility during migration)
            updated_drone.pop('x', None)
            updated_drone.pop('y', None)

            updated_config.append(updated_drone)

        except Exception as e:
            logger.error(f"Error processing drone config: {e}")
            # Keep original drone config on error
            updated_config.append(dict(drone))

    # Detect duplicate pos_id values
    for pos_id, hw_ids in pos_id_usage.items():
        if len(hw_ids) > 1:
            warnings["duplicates"].append({
                "pos_id": pos_id,
                "hw_ids": hw_ids,
                "message": f"COLLISION RISK: pos_id {pos_id} assigned to drones {hw_ids}"
            })

    # Build comprehensive report
    report = {
        "success": True,
        "updated_config": updated_config,
        "warnings": warnings,
        "changes": changes,
        "summary": {
            "total_drones": len(updated_config),
            "pos_id_changes_count": len(changes["pos_id_changes"]),
            "duplicates_count": len(warnings["duplicates"]),
            "missing_trajectories_count": len(warnings["missing_trajectories"]),
            "role_swaps_count": len(warnings["role_swaps"])
        }
    }

    # Log summary
    logger.info(f"Config validation complete: {report['summary']}")

    return report


def get_all_drone_positions(sim_mode=None):
    """
    Get initial positions for all drones from their trajectory CSV files.

    This is the SINGLE SOURCE OF TRUTH for drone positions. Positions are always
    read from the first row of each drone's trajectory CSV file based on pos_id.

    Args:
        sim_mode (bool): Whether in simulation mode (affects trajectory path)

    Returns:
        list: List of dictionaries with structure:
              [{"hw_id": int, "pos_id": int, "x": float, "y": float}, ...]
              Returns empty list on error.
    """
    from origin import _get_expected_position_from_trajectory

    # Detect sim_mode if not provided
    if sim_mode is None:
        sim_mode = getattr(Params, 'sim_mode', False)

    positions = []

    try:
        # Load current configuration
        config_data = load_config()

        for drone in config_data:
            try:
                hw_id = int(drone.get('hw_id'))
                pos_id = int(drone.get('pos_id', hw_id))  # Fallback to hw_id if no pos_id

                # Get position from trajectory CSV (single source of truth)
                x, y = _get_expected_position_from_trajectory(pos_id, sim_mode)

                if x is not None and y is not None:
                    positions.append({
                        "hw_id": hw_id,
                        "pos_id": pos_id,
                        "x": x,
                        "y": y
                    })
                else:
                    logger.warning(f"Could not get position for hw_id={hw_id}, pos_id={pos_id}")

            except Exception as e:
                logger.error(f"Error getting position for drone {drone}: {e}")
                continue

        logger.info(f"Retrieved positions for {len(positions)} drones")
        return positions

    except Exception as e:
        logger.error(f"Error getting all drone positions: {e}")
        return []