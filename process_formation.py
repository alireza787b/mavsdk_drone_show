# process_formation.py
# Use python process_formation --r for manual execution
import logging
import argparse
import os
import sys
from typing import Optional, List

from functions.plot_drone_paths import plot_drone_paths
from functions.process_drone_files import process_drone_files
from functions.update_config_file import update_config_file
from src.params import Params

def setup_logging(log_level: int = logging.INFO) -> None:
    """
    Configure logging with consistent formatting and output.
    
    Args:
        log_level (int): Logging level (default: logging.INFO)
    """
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('formation_process.log')
        ]
    )

def get_swarm_directory(base_dir: str) -> tuple[str, str]:
    """
    Determine the correct swarm directories based on simulation mode.
    
    Args:
        base_dir (str): Base directory for processing
    
    Returns:
        tuple: (skybrush_dir, processed_dir) paths
    
    Raises:
        ValueError: If required directories do not exist
    """
    # Determine directory structure based on simulation mode
    mode = "SITL" if Params.sim_mode else "real"
    base_folder = 'shapes_sitl' if Params.sim_mode else 'shapes'
    
    # Construct directory paths
    skybrush_dir = os.path.join(base_dir, base_folder, 'swarm', 'skybrush')
    processed_dir = os.path.join(base_dir, base_folder, 'swarm', 'processed')
    
    # Validate directory existence
    missing = [d for d in (skybrush_dir, processed_dir) if not os.path.exists(d)]
    if missing:
        raise ValueError(
            f"Missing directories in {mode} mode: {', '.join(missing)}"
        )
    
    return skybrush_dir, processed_dir

def run_formation_process(base_dir: Optional[str] = None) -> str:
    """
    Execute drone formation processing workflow with mode awareness.
    
    Args:
        base_dir (Optional[str]): Base directory for processing. 
                                  Defaults to current working directory.
    
    Returns:
        str: Processing result message
    """
    setup_logging()
    logging.info("Starting process_formation")
    logging.info(f"Operating in {'SITL' if Params.sim_mode else 'real'} mode")

    try:
        # Set base directory
        base_dir = base_dir or os.getcwd()
        logging.debug(f"Using base directory: {base_dir}")

        # Validate and get directories
        skybrush_dir, processed_dir = get_swarm_directory(base_dir)
        logging.info(f"Using skybrush directory: {skybrush_dir}")
        logging.info(f"Using processed directory: {processed_dir}")

        # Configure paths
        config_file = os.path.join(base_dir, Params.config_csv_name)
        logging.debug(f"Using config file: {config_file}")

        # Execute processing pipeline
        process_drone_files(skybrush_dir, processed_dir, 'cubic', 0.05)
        update_config_file(skybrush_dir, config_file)
        plot_drone_paths(base_dir, show_plot=False)
        
        logging.info("Processing complete!")
        return "Processing completed successfully!"

    except Exception as e:
        logging.error(f"Processing failed: {str(e)}", exc_info=True)
        return f"Processing error: {str(e)}"

def main():
    """
    Command-line interface for drone formation processing with mode awareness.
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
        # Configure debug logging if requested
        log_level = logging.DEBUG if args.verbose else logging.INFO
        setup_logging(log_level)
        
        result = run_formation_process(args.directory)
        print(result)

if __name__ == "__main__":
    main()