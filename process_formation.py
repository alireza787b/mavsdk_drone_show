# process_formation.py
import logging
import argparse
import os
import sys
from typing import Optional
from functions.plot_drone_paths import plot_drone_paths
from functions.process_drone_files import process_drone_files
from functions.update_config_file import update_config_file
from src.params import Params

def setup_logging(log_level: int = logging.INFO) -> None:
    """
    Configure logging with consistent formatting and output.
    If --verbose is used, log_level=DEBUG, else INFO.
    """
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('formation_process.log')
        ]
    )
    logging.debug("[setup_logging] Logging configured.")

def get_base_folder() -> str:
    """
    Return 'shapes_sitl' if Params.sim_mode=True, else 'shapes'.
    """
    return 'shapes_sitl' if Params.sim_mode else 'shapes'

def get_config_filename() -> str:
    """
    Return 'config_sitl.csv' if sim_mode=True, else 'config.csv'.
    """
    return 'config_sitl.csv' if Params.sim_mode else 'config.csv'

def run_formation_process(base_dir: Optional[str] = None) -> str:
    """
    Full pipeline: 
      1) Identify SITL or real 
      2) process CSV (skybrush->processed)
      3) update config (via transform Blender->NED)
      4) generate plots
    """
    mode_str = "SITL" if Params.sim_mode else "real"
    logging.info(f"[run_formation_process] Starting in {mode_str} mode")

    try:
        base_dir = base_dir or os.getcwd()
        base_folder = get_base_folder()

        skybrush_dir = os.path.join(base_dir, base_folder, 'swarm', 'skybrush')
        processed_dir = os.path.join(base_dir, base_folder, 'swarm', 'processed')
        plots_dir    = os.path.join(base_dir, base_folder, 'swarm', 'plots')

        config_csv_name = get_config_filename()
        config_file = os.path.join(base_dir, config_csv_name)

        logging.debug(f"Skybrush:  {skybrush_dir}")
        logging.debug(f"Processed: {processed_dir}")
        logging.debug(f"Plots:     {plots_dir}")
        logging.debug(f"Config:    {config_file}")

        # 1) Process new CSV
        process_drone_files(skybrush_dir, processed_dir, method='cubic', dt=Params.csv_dt)

        # 2) Update config
        update_config_file(skybrush_dir, config_file)

        # 3) Plot
        plot_drone_paths(base_dir, show_plots=False)

        msg = "Processing completed successfully!"
        logging.info(msg)
        return msg

    except Exception as e:
        err = f"Processing error: {str(e)}"
        logging.error(err, exc_info=True)
        return err

def main():
    """
    CLI usage:
      python process_formation.py --run --directory /root/mavsdk_drone_show --verbose
    """
    parser = argparse.ArgumentParser(description="Process drone formation data with SITL/real mode support")
    parser.add_argument('-r', '--run', action='store_true', help='Run the processing immediately')
    parser.add_argument('-d', '--directory', type=str, help='Specify base directory for processing')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging (debug level)')

    args = parser.parse_args()

    if args.run:
        log_level = logging.DEBUG if args.verbose else logging.INFO
        setup_logging(log_level)

        result = run_formation_process(args.directory)
        print(result)

if __name__ == "__main__":
    main()
