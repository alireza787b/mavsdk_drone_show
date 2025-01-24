# process_formation.py
# use python process_formation --r for manual execution
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

def validate_directories(base_dir: str) -> List[str]:
    """
    Validate and prepare required directories.
    
    Args:
        base_dir (str): Base directory for processing
    
    Returns:
        List of validated directory paths
    
    Raises:
        ValueError: If required directories do not exist
    """
    skybrush_dir = os.path.join(base_dir, 'shapes/swarm/skybrush')
    processed_dir = os.path.join(base_dir, 'shapes/swarm/processed')
    
    for directory in [skybrush_dir, processed_dir]:
        if not os.path.exists(directory):
            raise ValueError(f"Required directory not found: {directory}")
    
    return [skybrush_dir, processed_dir]

def run_formation_process(base_dir: Optional[str] = None) -> str:
    """
    Execute drone formation processing workflow.
    
    Args:
        base_dir (Optional[str]): Base directory for processing. 
                                  Defaults to current working directory.
    
    Returns:
        str: Processing result message
    """
    # Setup logging
    setup_logging()
    logging.info("Starting process_formation")

    try:
        # Use current directory if no base directory specified
        base_dir = base_dir or os.getcwd()
        
        # Validate directories
        skybrush_dir, processed_dir = validate_directories(base_dir)
        
        # Prepare config file path
        config_file = os.path.join(base_dir, Params.config_csv_name)
        
        # Execute processing steps
        process_drone_files(skybrush_dir, processed_dir, 'cubic', 0.05)
        update_config_file(skybrush_dir, config_file)
        plot_drone_paths(base_dir, False)
        
        logging.info("Processing complete!")
        return "Processing completed successfully!"
    
    except Exception as e:
        logging.error(f"Processing failed: {str(e)}")
        return f"Processing error: {str(e)}"

def main():
    """
    Command-line interface for drone formation processing.
    """
    parser = argparse.ArgumentParser(description="Process drone formation data")
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
    
    args = parser.parse_args()

    if args.run:
        result = run_formation_process(args.directory)
        print(result)

if __name__ == "__main__":
    main()