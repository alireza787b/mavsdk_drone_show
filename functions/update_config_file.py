# functions/update_config_file.py
import pandas as pd
import os
import re
import logging
from functions.file_management import ensure_directory_exists, setup_logging

def blender_north_west_up_to_ned(x_b, y_b, z_b=0.0):
    """
    Convert a 3D vector from Blender-like system:
      X = North
      Y = West
      Z = Up
    into NED coordinates:
      X = North
      Y = East  (east = -west)
      Z = Down  (down = -up)
    """
    n = x_b        # North is unchanged
    e = -y_b       # West => negative East
    d = -z_b       # Up => negative Down
    return (n, e, d)

def update_config_file(skybrush_dir: str, config_file: str):
    """
    Update the SITL or real config file using the initial positions from CSVs
    in skybrush_dir that match the pattern Drone<number>.csv.

    - We read each DroneX.csv
    - The first row is Blender coordinates (x [m], y [m], z [m]).
      Blender: X=North, Y=West, Z=Up
    - Convert them to NED (n,e,d).
    - Save (n, e) into config file under columns x, y.

    E.g., Drone1.csv => pos_id=1, x=<n>, y=<e>
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
        logging.warning("Config file is empty. Initializing with default columns: [pos_id, x, y]")
        config_df = pd.DataFrame(columns=['pos_id', 'x', 'y'])

    # Regex for Drone<number>.csv => e.g. Drone1.csv
    drone_file_pattern = re.compile(r'^Drone(\d+)\.csv$')

    for filename in os.listdir(skybrush_dir):
        match = drone_file_pattern.match(filename)
        if match:
            drone_id = int(match.group(1))
            filepath = os.path.join(skybrush_dir, filename)
            try:
                df = pd.read_csv(filepath)
                # Blender x,y from the first row
                blender_x = df.loc[0, 'x [m]']  # North in Blender
                blender_y = df.loc[0, 'y [m]']  # West in Blender
                # Optionally read z if you want. If the CSV has 'z [m]'
                # For the config, we only need x,y. We'll do transform:
                n, e, _ = blender_north_west_up_to_ned(blender_x, blender_y, 0.0)

                # If pos_id not in config, append; else update
                if not (config_df['pos_id'] == drone_id).any():
                    new_row = {'pos_id': drone_id, 'x': n, 'y': e}
                    config_df = config_df.append(new_row, ignore_index=True)
                else:
                    config_df.loc[config_df['pos_id'] == drone_id, ['x','y']] = [n, e]

                logging.info(f"Set Drone {drone_id} => Blender(N={blender_x},W={blender_y}) => NED(n={n},e={e})")

            except (KeyError, ValueError, IndexError) as e:
                logging.warning(f"Skipping {filename} due to read/parse error: {e}")
            except Exception as e:
                logging.error(f"Error reading {filename}: {e}", exc_info=True)

    # Save updated config
    config_df.to_csv(config_file, index=False)
    logging.info(f"[update_config_file] Successfully updated {config_file}")

if __name__ == "__main__":
    # Quick test
    test_dir = "./test_skybrush"
    test_config = "./config_sitl.csv"
    update_config_file(test_dir, test_config)
