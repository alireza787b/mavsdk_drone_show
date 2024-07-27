# process_formation.py
# use python process_formation --r for manual execution

import logging
import argparse
from functions.plot_drone_paths import plot_drone_paths
from functions.process_drone_files import process_drone_files
from functions.update_config_file import update_config_file

def run_formation_process():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Starting process_formation")

    skybrush_dir = 'shapes/swarm/skybrush'
    processed_dir = 'shapes/swarm/processed'
    method = 'cubic'
    dt = 0.05
    show_plots = False
    config_file = 'config.csv'

    try:
        process_drone_files(skybrush_dir, processed_dir, method, dt)
        update_config_file(skybrush_dir, config_file)
        plot_drone_paths(skybrush_dir, processed_dir, show_plots)
        logging.info("Processing complete!")
        return "Processing completed successfully!"
    except Exception as e:
        logging.error(f"An error occurred during processing: {e}")
        return str(e)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process drone formation data.")
    parser.add_argument('-r', '--run', action='store_true', help='Run the processing immediately')
    args = parser.parse_args()

    if args.run:
        result = run_formation_process()
        print(result)
