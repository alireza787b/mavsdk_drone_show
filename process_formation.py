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
    """
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('formation_process.log')
        ]
    )

def get_base_folder() -> str:
    """
    Return the correct folder name based on simulation mode:
    - SITL -> 'shapes_sitl'
    - Real -> 'shapes'
    """
    return 'shapes_sitl' if Params.sim_mode else 'shapes'

def get_config_filename() -> str:
    """
    Return the correct config file name based on simulation mode:
    - SITL -> 'config_sitl.csv'
    - Real -> 'config.csv'
    """
    return 'config_sitl.csv' if Params.sim_mode else 'config.csv'

def run_formation_process(base_dir: Optional[str] = None) -> str:
    """
    Execute the entire drone formation processing workflow, 
    automatically choosing SITL or real directories and config.

    Steps:
    1) Identify correct shapes folder (shapes_sitl vs. shapes).
    2) Identify correct config file (config_sitl.csv vs. config.csv).
    3) Process new CSVs in skybrush_dir -> output to processed_dir.
    4) Update config file with initial positions from DroneX.csv 
       (with coordinate transform from Blender -> NED).
    5) Generate & save plots in plots_dir.

    Return a success or error message string.
    """
    setup_logging()
    mode_str = "SITL" if Params.sim_mode else "real"
    logging.info(f"[run_formation_process] Starting in {mode_str} mode")

    try:
        # Determine the base directory
        base_dir = base_dir or os.getcwd()

        # For SITL or real?
        base_folder = get_base_folder()

        # Build subfolders
        skybrush_dir = os.path.join(base_dir, base_folder, 'swarm', 'skybrush')
        processed_dir = os.path.join(base_dir, base_folder, 'swarm', 'processed')
        plots_dir    = os.path.join(base_dir, base_folder, 'swarm', 'plots')

        # Pick which config file
        config_csv_name = get_config_filename()
        config_file = os.path.join(base_dir, config_csv_name)

        logging.debug(f"Skybrush dir:  {skybrush_dir}")
        logging.debug(f"Processed dir: {processed_dir}")
        logging.debug(f"Plots dir:     {plots_dir}")
        logging.debug(f"Config file:   {config_file}")

        # 1) Process the raw CSVs (skybrush -> processed)
        process_drone_files(
            skybrush_dir=skybrush_dir, 
            processed_dir=processed_dir, 
            method='cubic', 
            dt=0.05
        )

        # 2) Update config file from the raw CSV's first line
        #    and do coordinate transform from Blender -> NED
        update_config_file(skybrush_dir, config_file)

        # 3) Generate 3D path plots
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
    Command-line interface for drone formation processing with SITL/real mode support.
    Example usage:
      python process_formation.py --run -d /root/mavsdk_drone_show
    """
    parser = argparse.ArgumentParser(
        description="Process drone formation data with SITL/real mode support"
    )
    parser.add_argument(
        '-r', '--run', 
        action='store_true', 
        help='Run the processing immediately'
    )
    parser.add_argument(
        '-d', '--directory', 
        type=str, 
        help='Specify base directory for processing'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging (debug level)'
    )

    args = parser.parse_args()

    if args.run:
        log_level = logging.DEBUG if args.verbose else logging.INFO
        setup_logging(log_level)
        
        result = run_formation_process(args.directory)
        print(result)

if __name__ == "__main__":
    main()
