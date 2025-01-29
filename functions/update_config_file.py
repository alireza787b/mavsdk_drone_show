# functions/update_config_file.py
import pandas as pd
import os
import re
import logging
from functions.file_management import ensure_directory_exists, setup_logging

def update_config_file(skybrush_dir: str, config_file: str):
    """
    Update the SITL or real config file using the initial positions from CSVs
    in skybrush_dir that match the pattern Drone<number>.csv.

    E.g., Drone1.csv => pos_id=1, x=<first x>, y=<first y>
    """
    setup_logging()
    logging.info(f"[update_config_file] Updating config={config_file} from folder={skybrush_dir}...")

    ensure_directory_exists(skybrush_dir)

    # If config_file doesn't exist, create an empty one so we can read/write
    if not os.path.exists(config_file):
        logging.warning(f"{config_file} not found. Creating an empty config.")
        open(config_file, 'w').close()

    try:
        # Attempt reading config
        config_df = pd.read_csv(config_file)
    except pd.errors.EmptyDataError:
        # If it's empty, create basic columns
        logging.warning("Config file is empty. Initializing with default columns.")
        config_df = pd.DataFrame(columns=['pos_id', 'x', 'y'])

    # Pattern for Drone1.csv, Drone2.csv, etc.
    drone_file_pattern = re.compile(r'^Drone(\d+)\.csv$')

    for filename in os.listdir(skybrush_dir):
        match = drone_file_pattern.match(filename)
        if match:
            drone_id = int(match.group(1))
            filepath = os.path.join(skybrush_dir, filename)
            try:
                df = pd.read_csv(filepath)
                # First row x,y
                initial_x = df.loc[0, 'x [m]']
                initial_y = df.loc[0, 'y [m]']

                # If pos_id not in config, append; else update
                if not (config_df['pos_id'] == drone_id).any():
                    config_df = config_df.append(
                        {'pos_id': drone_id, 'x': initial_x, 'y': initial_y},
                        ignore_index=True
                    )
                else:
                    config_df.loc[config_df['pos_id'] == drone_id, ['x','y']] = [initial_x, initial_y]

                logging.info(f"Set Drone {drone_id} => x={initial_x}, y={initial_y}")
            except (KeyError, ValueError, IndexError) as e:
                logging.warning(f"Skipping {filename}: {e}")
            except Exception as e:
                logging.error(f"Error reading {filename}: {e}", exc_info=True)

    # Save updated config
    config_df.to_csv(config_file, index=False)
    logging.info(f"[update_config_file] Successfully updated {config_file}")

if __name__ == "__main__":
    # Example usage
    test_dir = "./test_skybrush"
    test_config = "./config_sitl.csv"
    update_config_file(test_dir, test_config)
