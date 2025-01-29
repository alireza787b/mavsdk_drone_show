# functions/update_config_file.py
import pandas as pd
import os
import re
import logging
from functions.file_management import ensure_directory_exists, setup_logging

def update_config_file(skybrush_dir, config_file):
    """
    Update configuration file with the initial positions from drone CSV files.
    
    The function reads all CSV files in 'skybrush_dir' that match the pattern 
    Drone<number>.csv (e.g. Drone1.csv). For each matching drone, it extracts
    the first x and y positions and updates them in the config CSV file.

    Args:
        skybrush_dir (str): Directory containing the original drone CSV files
        config_file (str): Path to the config CSV file
    """
    setup_logging()
    logging.info("Starting update of the config file...")

    # Ensure the directory exists
    ensure_directory_exists(skybrush_dir)

    try:
        config_df = pd.read_csv(config_file)

        # Regex to match Drone1.csv, Drone2.csv, etc.
        drone_file_pattern = re.compile(r'^Drone(\d+)\.csv$')

        # Process relevant CSV files
        for filename in os.listdir(skybrush_dir):
            match = drone_file_pattern.match(filename)
            if match:
                drone_id = int(match.group(1))
                filepath = os.path.join(skybrush_dir, filename)
                try:
                    df = pd.read_csv(filepath)

                    # Extract initial x and y
                    initial_x = df.loc[0, 'x [m]']
                    initial_y = df.loc[0, 'y [m]']

                    # Update config dataframe
                    config_df.loc[config_df['pos_id'] == drone_id, ['x', 'y']] = [initial_x, initial_y]
                    logging.info(f"Updated position for Drone {drone_id}")

                except (KeyError, ValueError, IndexError) as e:
                    logging.warning(f"Skipping {filename}: {e}")
                except Exception as e:
                    logging.error(f"Error processing {filename}: {e}")

        # Save updated config
        config_df.to_csv(config_file, index=False)
        logging.info(f"Config file updated: {config_file}")

    except Exception as e:
        logging.error(f"Failed to update config file: {e}")
        raise

if __name__ == "__main__":
    """
    Example usage for SITL/real modes. Typically triggered by process_formation.py.
    """
    from src.params import Params

    base_dir = "/root/mavsdk_drone_show"
    base_folder = 'shapes_sitl' if Params.sim_mode else 'shapes'
    skybrush_dir = os.path.join(base_dir, base_folder, 'swarm', 'skybrush')
    config_file = os.path.join(base_dir, "config.csv")  # or param-based
    update_config_file(skybrush_dir, config_file)
