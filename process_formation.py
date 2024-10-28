# process_formation.py
# use python process_formation --r for manual execution

import logging
import argparse
import os
from functions.plot_drone_paths import plot_drone_paths
from functions.process_drone_files import process_drone_files
from functions.update_config_file import update_config_file
from src.params import Params
def run_formation_process(base_dir=None):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Starting process_formation")

    if base_dir is None:
        base_dir = os.getcwd()

    skybrush_dir = os.path.join(base_dir, 'shapes/swarm/skybrush')
    processed_dir = os.path.join(base_dir, 'shapes/swarm/processed')
    config_file = os.path.join(base_dir, Params.config_csv_name)

    try:
        process_drone_files(skybrush_dir, processed_dir, 'cubic', 0.05)
        update_config_file(skybrush_dir, config_file)
        plot_drone_paths(base_dir, False)
        logging.info("Processing complete!")
        return "Processing completed successfully!"
    except Exception as e:
        logging.error(f"An error occurred during processing: {str(e)}")
        return str(e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process drone formation data.")
    parser.add_argument('-r', '--run', action='store_true', help='Run the processing immediately')
    args = parser.parse_args()

    if args.run:
        result = run_formation_process()
        print(result)


