# functions/update_config_file.py
import pandas as pd
import os
import re
import logging
from functions.file_management import ensure_directory_exists, setup_logging

def update_config_file(skybrush_dir, config_file):
    """
    Update configuration file with initial positions from drone CSV files.
    
    Args:
        skybrush_dir (str): Directory containing drone CSV files
        config_file (str): Path to the configuration CSV file
    """
    setup_logging()
    logging.info("Starting update of the config file...")

    # Ensure the directory exists
    ensure_directory_exists(skybrush_dir)

    try:
        # Read config file
        config_df = pd.read_csv(config_file)

        # Regex pattern to match drone files (Drone1.csv, Drone2.csv, etc.)
        drone_file_pattern = re.compile(r'^Drone(\d+)\.csv$')

        # Process only files matching the drone file pattern
        for filename in os.listdir(skybrush_dir):
            match = drone_file_pattern.match(filename)
            if match:
                try:
                    filepath = os.path.join(skybrush_dir, filename)
                    df = pd.read_csv(filepath)

                    # Extract drone ID from filename
                    drone_id = int(match.group(1))

                    # Get initial x and y positions
                    initial_x = df.loc[0, 'x [m]']
                    initial_y = df.loc[0, 'y [m]']

                    # Update config dataframe
                    config_df.loc[config_df['pos_id'] == drone_id, ['x', 'y']] = [initial_x, initial_y]

                    logging.info(f"Updated position for Drone {drone_id}")

                except (KeyError, ValueError, IndexError) as e:
                    logging.warning(f"Skipping {filename}: {e}")
                except Exception as e:
                    logging.error(f"Error processing {filename}: {e}")

        # Save updated config file
        config_df.to_csv(config_file, index=False)
        logging.info(f"Config file updated: {config_file}")

    except Exception as e:
        logging.error(f"Failed to update config file: {e}")
        raise

if __name__ == "__main__":
    # Example usage for real modes
    skybrush_dir = "/root/mavsdk_drone_show/shapes/swarm/skybrush"
    config_file = "/root/mavsdk_drone_show/config.csv"
    update_config_file(skybrush_dir, config_file)