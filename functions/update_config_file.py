import pandas as pd
import os
import re
import logging
from functions.file_management import ensure_directory_exists, setup_logging

def update_config_file(skybrush_dir: str, config_file: str) -> None:
    """
    Update the SITL or real config CSV with the initial x,y from 
    each 'DroneX.csv' in skybrush_dir.
    """
    setup_logging()
    logging.info(f"[update_config_file] Updating config: {config_file} using {skybrush_dir}")

    ensure_directory_exists(skybrush_dir)

    # If config file doesn't exist, create an empty one
    if not os.path.exists(config_file):
        logging.warning(f"{config_file} not found. Creating a new one.")
        open(config_file, 'a').close()

    # Attempt to read config
    try:
        config_df = pd.read_csv(config_file)
    except pd.errors.EmptyDataError:
        logging.warning(f"{config_file} is empty, initializing with columns: pos_id, x, y")
        config_df = pd.DataFrame(columns=['pos_id', 'x', 'y'])

    drone_file_pattern = re.compile(r'^Drone(\d+)\.csv$')

    for filename in os.listdir(skybrush_dir):
        match = drone_file_pattern.match(filename)
        if match:
            drone_id = int(match.group(1))
            file_path = os.path.join(skybrush_dir, filename)
            try:
                df = pd.read_csv(file_path)
                init_x = df.loc[0, 'x [m]']
                init_y = df.loc[0, 'y [m]']

                # If config doesn't have this pos_id, append
                if not (config_df['pos_id'] == drone_id).any():
                    new_row = {'pos_id': drone_id, 'x': init_x, 'y': init_y}
                    config_df = config_df.append(new_row, ignore_index=True)
                else:
                    # Otherwise update existing row
                    config_df.loc[config_df['pos_id'] == drone_id, ['x', 'y']] = [init_x, init_y]

                logging.info(f"[update_config_file] Drone {drone_id}: x={init_x}, y={init_y}")

            except (KeyError, ValueError, IndexError) as e:
                logging.warning(f"[update_config_file] Skipping {filename}: {str(e)}")
            except Exception as e:
                logging.error(f"[update_config_file] Error processing {filename}: {str(e)}")

    config_df.to_csv(config_file, index=False)
    logging.info(f"[update_config_file] Successfully updated {config_file}")

if __name__ == "__main__":
    # Test usage
    skybrush_test = "./shapes/swarm/skybrush"
    config_test = "./config.csv"
    update_config_file(skybrush_test, config_test)
