import pandas as pd
import os
import re
import logging
from functions.file_management import ensure_directory_exists, setup_logging

def update_config_file(skybrush_dir, config_file):
    """
    Update the SITL or real config file with initial positions from 
    each 'DroneX.csv' in the given skybrush_dir.
    
    If SITL -> config_file is 'config_sitl.csv',
    otherwise -> 'config.csv'.
    """
    setup_logging()
    logging.info(f"[update_config_file] Reading from {skybrush_dir} and updating {config_file}...")

    ensure_directory_exists(skybrush_dir)

    # If config_file does not exist, let's just create an empty one
    if not os.path.exists(config_file):
        logging.warning(f"No config file found at {config_file}; creating an empty one.")
        open(config_file, 'a').close()

    try:
        config_df = pd.read_csv(config_file)
    except pd.errors.EmptyDataError:
        # If it's empty, create basic structure
        logging.warning("Config file is empty. Initializing with columns: pos_id, x, y")
        config_df = pd.DataFrame(columns=['pos_id','x','y'])

    drone_file_pattern = re.compile(r'^Drone(\d+)\.csv$')

    # For each Drone<number>.csv, update config
    for filename in os.listdir(skybrush_dir):
        match = drone_file_pattern.match(filename)
        if match:
            drone_id = int(match.group(1))
            filepath = os.path.join(skybrush_dir, filename)
            try:
                df = pd.read_csv(filepath)

                initial_x = df.loc[0, 'x [m]']
                initial_y = df.loc[0, 'y [m]']

                # If this pos_id doesn't exist in config, add a new row.
                if not (config_df['pos_id'] == drone_id).any():
                    config_df = config_df.append(
                        {'pos_id': drone_id, 'x': initial_x, 'y': initial_y},
                        ignore_index=True
                    )
                else:
                    # Otherwise update existing
                    config_df.loc[config_df['pos_id'] == drone_id, ['x','y']] = [initial_x, initial_y]
                logging.info(f"Updated Drone {drone_id} => x={initial_x}, y={initial_y}")

            except (KeyError, ValueError, IndexError) as e:
                logging.warning(f"Skipping {filename}: {e}")
            except Exception as e:
                logging.error(f"Error processing {filename}: {e}")

    config_df.to_csv(config_file, index=False)
    logging.info(f"[update_config_file] Successfully updated {config_file}")

if __name__ == "__main__":
    # Basic test usage
    test_skybrush = "./some_temp_skybrush"
    test_config = "./config_sitl.csv"
    update_config_file(test_skybrush, test_config)
