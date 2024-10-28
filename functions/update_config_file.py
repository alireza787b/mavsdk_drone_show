# functions/update_config_file.py
import pandas as pd
from functions.file_management import ensure_directory_exists, setup_logging
import logging
import os

def update_config_file(skybrush_dir, config_file):
    setup_logging()
    logging.info("Starting update of the config file...")

    # Ensure the directory exists
    ensure_directory_exists(skybrush_dir)

    try:
        config_df = pd.read_csv(config_file)
        for filename in os.listdir(skybrush_dir):
            if filename.endswith(".csv"):
                filepath = os.path.join(skybrush_dir, filename)
                df = pd.read_csv(filepath)
                initial_x = df.loc[0, 'x [m]']
                initial_y = df.loc[0, 'y [m]']
                drone_id = int(filename.replace('Drone', '').replace('.csv', ''))
                config_df.loc[config_df['pos_id'] == drone_id, ['x', 'y']] = [initial_x, initial_y]
        config_df.to_csv(config_file, index=False)
        logging.info(f"Config file updated: {config_file}")
    except Exception as e:
        logging.error(f"Failed to update config file: {e}")

