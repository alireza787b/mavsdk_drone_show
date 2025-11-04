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

    Returns:
        str: Success message or error description
    """
    mode_str = "SITL" if Params.sim_mode else "real"
    logging.info(f"[run_formation_process] ========================================")
    logging.info(f"[run_formation_process] Starting Formation Processing Pipeline")
    logging.info(f"[run_formation_process] Mode: {mode_str}")
    logging.info(f"[run_formation_process] ========================================")

    try:
        base_dir = base_dir or os.getcwd()
        base_folder = get_base_folder()

        skybrush_dir = os.path.join(base_dir, base_folder, 'swarm', 'skybrush')
        processed_dir = os.path.join(base_dir, base_folder, 'swarm', 'processed')
        plots_dir    = os.path.join(base_dir, base_folder, 'swarm', 'plots')

        config_csv_name = get_config_filename()
        config_file = os.path.join(base_dir, config_csv_name)

        logging.info(f"[run_formation_process] Directories:")
        logging.info(f"[run_formation_process]   Skybrush:  {skybrush_dir}")
        logging.info(f"[run_formation_process]   Processed: {processed_dir}")
        logging.info(f"[run_formation_process]   Plots:     {plots_dir}")
        logging.info(f"[run_formation_process]   Config:    {config_file}")

        # Count input files for validation
        input_files = [f for f in os.listdir(skybrush_dir) if f.endswith('.csv')]
        input_count = len(input_files)
        logging.info(f"[run_formation_process] Input drone count: {input_count}")

        # 1) Process new CSV (this will raise exception if any file fails)
        logging.info(f"[run_formation_process] Step 1/3: Processing drone trajectory files...")
        processed_files = process_drone_files(skybrush_dir, processed_dir, method='cubic', dt=Params.csv_dt)

        # 2) Update config
        logging.info(f"[run_formation_process] Step 2/3: Updating configuration file...")
        update_config_file(skybrush_dir, config_file)

        # 3) Plot
        logging.info(f"[run_formation_process] Step 3/3: Generating 3D visualizations...")
        plot_drone_paths(base_dir, show_plots=False)

        # ====================================================================
        # FINAL VALIDATION: Verify complete processing pipeline
        # ====================================================================
        processed_count = len([f for f in os.listdir(processed_dir) if f.endswith('.csv')])
        plot_count = len([f for f in os.listdir(plots_dir) if f.endswith('.jpg')])
        expected_plots = input_count + 1  # Individual + combined

        logging.info(f"[run_formation_process] ========================================")
        logging.info(f"[run_formation_process] Pipeline Completion Summary:")
        logging.info(f"[run_formation_process]   Input files (raw):        {input_count}")
        logging.info(f"[run_formation_process]   Processed files:          {processed_count}")
        logging.info(f"[run_formation_process]   Generated plots:          {plot_count}")
        logging.info(f"[run_formation_process]   Expected plots:           {expected_plots}")

        # Validate everything matches
        validation_passed = True
        if processed_count != input_count:
            logging.error(f"[run_formation_process] ❌ VALIDATION FAILED: Processed count ({processed_count}) != Input count ({input_count})")
            validation_passed = False

        if plot_count != expected_plots:
            logging.warning(f"[run_formation_process] ⚠️ WARNING: Plot count ({plot_count}) != Expected ({expected_plots})")
            # Don't fail on plot mismatch, just warn

        if validation_passed:
            msg = f"✅ Processing completed successfully! {input_count} drones processed, {plot_count} plots generated."
            logging.info(f"[run_formation_process] {msg}")
            logging.info(f"[run_formation_process] ========================================")
            return msg
        else:
            err_msg = f"❌ Processing completed with errors: {processed_count}/{input_count} drones processed"
            logging.error(f"[run_formation_process] {err_msg}")
            logging.info(f"[run_formation_process] ========================================")
            raise RuntimeError(err_msg)

    except Exception as e:
        err = f"Processing error: {str(e)}"
        logging.error(f"[run_formation_process] ❌ FATAL ERROR: {err}", exc_info=True)
        logging.info(f"[run_formation_process] ========================================")
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
