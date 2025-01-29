import logging
import argparse
import os
import shutil
import sys
from typing import Optional, Tuple
from functions.plot_drone_paths import plot_drone_paths
from functions.process_drone_files import process_drone_files
from functions.update_config_file import update_config_file
from functions.file_management import ensure_directory_exists, clear_directory
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
    Return the correct folder for SITL vs. real mode:
    - SITL mode -> 'shapes_sitl'
    - Real mode -> 'shapes'
    """
    return 'shapes_sitl' if Params.sim_mode else 'shapes'

def get_config_file(base_dir: str) -> str:
    """
    Return the correct config file name for SITL vs. real mode:
    - SITL -> 'config_sitl.csv'
    - Real -> 'config.csv'
    """
    if Params.sim_mode:
        return os.path.join(base_dir, 'config_sitl.csv')
    else:
        return os.path.join(base_dir, 'config.csv')

def get_swarm_directories(base_dir: str) -> Tuple[str, str, str]:
    """
    Return the (skybrush_dir, processed_dir, plots_dir) 
    corresponding to SITL or real mode. 
    Each subfolder is under shapes_sitl/swarm or shapes/swarm.
    """
    base_folder = get_base_folder()
    skybrush_dir = os.path.join(base_dir, base_folder, 'swarm', 'skybrush')
    processed_dir = os.path.join(base_dir, base_folder, 'swarm', 'processed')
    plots_dir = os.path.join(base_dir, base_folder, 'swarm', 'plots')
    return skybrush_dir, processed_dir, plots_dir

def run_pipeline_in_temp(base_dir: str, uploaded_csv_dir: str) -> str:
    """
    Run the entire pipeline (process, config update, plots) in a 
    temporary staging directory using the newly uploaded CSV files.

    If everything completes with no errors, return the path to 
    the temp folder so we can finalize/copy results from there.
    Otherwise, raise an exception.
    
    Args:
        base_dir (str): The root of your project (e.g. /root/mavsdk_drone_show).
        uploaded_csv_dir (str): A folder containing newly uploaded CSV files 
                                from the user (e.g. an unzipped location).
    
    Returns:
        str: The path to the staging directory that now holds processed CSV & plots.
    """
    logging.info("[run_pipeline_in_temp] Starting pipeline in a temp staging area...")
    
    # Create a local temp folder for staging
    temp_base = os.path.join(base_dir, 'tmp_upload')
    skybrush_temp = os.path.join(temp_base, 'skybrush')
    processed_temp = os.path.join(temp_base, 'processed')
    plots_temp = os.path.join(temp_base, 'plots')
    
    # Clean up and recreate the staging area
    if os.path.exists(temp_base):
        shutil.rmtree(temp_base)
    ensure_directory_exists(skybrush_temp)
    ensure_directory_exists(processed_temp)
    ensure_directory_exists(plots_temp)
    
    # Copy newly uploaded CSVs -> skybrush_temp
    # This ensures the pipeline only sees the "new" files
    for file in os.listdir(uploaded_csv_dir):
        if file.endswith(".csv"):
            shutil.copy2(os.path.join(uploaded_csv_dir, file), skybrush_temp)
    logging.info(f"Copied uploaded CSVs into staging area: {skybrush_temp}")
    
    # We also pick which config file to use for SITL or real
    config_file = get_config_file(base_dir)
    if not os.path.exists(config_file):
        # optionally create a blank config if missing, or raise an error
        open(config_file, 'a').close()  # create empty
        logging.warning(f"Created an empty config file: {config_file}")

    # 1) Process new CSV in staging area
    process_drone_files(
        skybrush_dir=skybrush_temp,
        processed_dir=processed_temp,
        method='cubic',
        dt=0.05
    )
    # 2) Update config (using the staging skybrush data)
    update_config_file(skybrush_temp, config_file)
    # 3) Generate plots, but point the plot routine to use 
    #    *staging* folders so it won't pollute real directories.
    # 
    # Here we pass a special argument "override_dirs" so we can do 
    # a custom location for processed & plots:
    plot_drone_paths(
        base_dir=base_dir, 
        show_plots=False,
        high_quality=True,
        override_processed=processed_temp, 
        override_plots=plots_temp
    )

    # If we got here, pipeline was success
    logging.info("[run_pipeline_in_temp] Pipeline in staging area was successful!")
    return temp_base

def finalize_results_into_real(base_dir: str, temp_base: str) -> None:
    """
    Once the pipeline in the temp staging folder succeeds, 
    finalize by removing old real-mode or SITL-mode folders and 
    copying the new data from the staging folder. 
    Then you can do a git sync if desired.

    Args:
        base_dir (str): The root of your project
        temp_base (str): The path returned by run_pipeline_in_temp()
    """
    logging.info("[finalize_results_into_real] Promoting staged data to real SITL/real folders...")

    # Identify actual SITL/real directories
    skybrush_dir, processed_dir, plots_dir = get_swarm_directories(base_dir)
    
    # Remove all contents from the real directories
    clear_directory(skybrush_dir)
    clear_directory(processed_dir)
    clear_directory(plots_dir)
    
    skybrush_temp = os.path.join(temp_base, 'skybrush')
    processed_temp = os.path.join(temp_base, 'processed')
    plots_temp = os.path.join(temp_base, 'plots')

    # Copy the newly uploaded CSV (staged) to the real skybrush folder
    for f in os.listdir(skybrush_temp):
        src = os.path.join(skybrush_temp, f)
        dst = os.path.join(skybrush_dir, f)
        shutil.copy2(src, dst)
    # Copy processed CSV to real processed folder
    for f in os.listdir(processed_temp):
        src = os.path.join(processed_temp, f)
        dst = os.path.join(processed_dir, f)
        shutil.copy2(src, dst)
    # Copy new plots
    for f in os.listdir(plots_temp):
        src = os.path.join(plots_temp, f)
        dst = os.path.join(plots_dir, f)
        shutil.copy2(src, dst)

    logging.info("[finalize_results_into_real] Real SITL/real folders updated with new data!")

    # (Optionally) do a git sync here if desired
    # e.g. run a git command or trigger some sync function
    # git_sync_function()

def run_formation_process(base_dir: Optional[str], uploaded_csv_dir: str) -> str:
    """
    Full process when you have new uploaded CSVs:
      1. Create a staging area
      2. Run pipeline (process, config, plots) in staging
      3. If success, finalize to the real SITL or real folders
      4. If fail, do not touch the real SITL/real data

    Args:
        base_dir (str): The root of your project
        uploaded_csv_dir (str): Where the new CSV files are located 
            (unzipped from the user’s upload)

    Returns:
        str: A success/fail message
    """
    # Setup logging and confirm mode
    setup_logging()
    mode_str = 'SITL' if Params.sim_mode else 'real'
    logging.info(f"Starting run_formation_process in {mode_str} mode")

    # Use the user-provided or current directory if missing
    base = base_dir or os.getcwd()

    try:
        # 1) Run pipeline in a temporary staging area
        temp_path = run_pipeline_in_temp(base, uploaded_csv_dir)

        # 2) If we made it here, the pipeline worked. So finalize.
        finalize_results_into_real(base, temp_path)

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
    
    Usage example:
      python process_formation.py --run -d /root/mavsdk_drone_show --upload ./my_uploaded_csvs
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
        '--upload', 
        type=str, 
        help='Path to newly uploaded CSV files (unzipped folder).'
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

        base_dir = args.directory or os.getcwd()
        uploaded_csv_dir = args.upload or os.path.join(base_dir, "uploaded_files")

        result = run_formation_process(base_dir, uploaded_csv_dir)
        print(result)

if __name__ == "__main__":
    main()
