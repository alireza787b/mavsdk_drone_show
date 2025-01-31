# functions/update_config_file.py
import pandas as pd
import os
import re
import logging
from functions.file_management import ensure_directory_exists

def blender_north_west_up_to_ned(x_b, y_b, z_b=0.0):
    """
    Convert from Blender (X=North, Y=West, Z=Up) to NED (N, E, D).
    """
    n = x_b
    e = -y_b
    d = -z_b
    return (n, e, d)

def update_config_file(skybrush_dir: str, config_file: str):
    """
    For each Drone<number>.csv in skybrush_dir:
      1) Read first row's x[m], y[m] (Blender coords)
      2) Convert to NED (only store n,e in config)
      3) Save to config_file in columns x, y for that pos_id.

    Must match the regex r'^Drone(\d+)\.csv$'.
    """
    logging.info(f"[update_config_file] Checking folder={skybrush_dir} to update config={config_file} ...")

    ensure_directory_exists(skybrush_dir)

    # Ensure config_file exists
    if not os.path.exists(config_file):
        logging.warning(f"[update_config_file] {config_file} not found. Creating empty.")
        open(config_file, 'w').close()

    # Load or create basic structure
    try:
        config_df = pd.read_csv(config_file)
        logging.debug(f"[update_config_file] Loaded existing config with {len(config_df)} rows.")
    except pd.errors.EmptyDataError:
        logging.warning("[update_config_file] Config file empty, initializing with columns [pos_id, x, y]")
        config_df = pd.DataFrame(columns=['pos_id', 'x', 'y'])

    # Regex for Drone1.csv, Drone2.csv, etc.
    drone_file_pattern = re.compile(r'^Drone (\d+)\.csv$')
    all_files = os.listdir(skybrush_dir)
    logging.debug(f"[update_config_file] Found files in skybrush: {all_files}")

    for filename in all_files:
        match = drone_file_pattern.match(filename)
        if match:
            drone_id = int(match.group(1))
            filepath = os.path.join(skybrush_dir, filename)
            logging.debug(f"[update_config_file] Found matching Drone file: {filename}, drone_id={drone_id}")
            try:
                df = pd.read_csv(filepath)
                blender_x = df.loc[0, 'x [m]']
                blender_y = df.loc[0, 'y [m]']
                # If needed: blender_z = df.loc[0, 'z [m]']
                n, e, _ = blender_north_west_up_to_ned(blender_x, blender_y, 0.0)

                # Insert or update row
                if not (config_df['pos_id'] == drone_id).any():
                    logging.debug(f"[update_config_file] Inserting new row for drone={drone_id}")
                    new_row = {'pos_id': drone_id, 'x': n, 'y': e}
                    config_df = config_df.append(new_row, ignore_index=True)
                else:
                    logging.debug(f"[update_config_file] Updating existing row for drone={drone_id}")
                    config_df.loc[config_df['pos_id'] == drone_id, ['x','y']] = [n, e]

                logging.info(f"[update_config_file] Drone {drone_id} => Blender(N={blender_x},W={blender_y}) => (n={n},e={e})")

            except (KeyError, ValueError, IndexError) as e:
                logging.warning(f"[update_config_file] Skipping {filename}: {e}")
            except Exception as e:
                logging.error(f"[update_config_file] Error reading {filename}: {e}", exc_info=True)
        else:
            logging.debug(f"[update_config_file] {filename} does not match 'Drone(\\d+).csv'")

    # Save
    config_df.to_csv(config_file, index=False)
    logging.info(f"[update_config_file] Config updated => {config_file}")
