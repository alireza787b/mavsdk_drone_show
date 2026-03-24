# process_formation.py
import argparse
import os
import sys
from pathlib import Path
from typing import Dict, Optional
from functions.plot_drone_paths import plot_drone_paths
from functions.process_drone_files import process_drone_files
from src.params import Params
from mds_logging import get_logger
from mds_logging.drone import init_drone_logging

logger = get_logger("process_formation")

def get_base_folder() -> str:
    """
    Return 'shapes_sitl' if Params.sim_mode=True, else 'shapes'.
    """
    return 'shapes_sitl' if Params.sim_mode else 'shapes'

def get_config_filename() -> str:
    """Return config filename for current mode."""
    return Params.config_file_name

def run_formation_process(
    base_dir: Optional[str] = None,
    skybrush_dir: Optional[str] = None,
    processed_dir: Optional[str] = None,
    plots_dir: Optional[str] = None,
) -> Dict[str, object]:
    """
    Full pipeline:
      1) Identify SITL or real
      2) process CSV (skybrush->processed)
      3) update config (via transform Blender->NED)
      4) generate plots

    Returns:
        dict: Structured success/error summary.
    """
    mode_str = "SITL" if Params.sim_mode else "real"
    logger.info(f"[run_formation_process] ========================================")
    logger.info(f"[run_formation_process] Starting Formation Processing Pipeline")
    logger.info(f"[run_formation_process] Mode: {mode_str}")
    logger.info(f"[run_formation_process] ========================================")

    try:
        base_dir = base_dir or os.getcwd()
        base_folder = get_base_folder()

        skybrush_dir = skybrush_dir or os.path.join(base_dir, base_folder, 'swarm', 'skybrush')
        processed_dir = processed_dir or os.path.join(base_dir, base_folder, 'swarm', 'processed')
        plots_dir = plots_dir or os.path.join(base_dir, base_folder, 'swarm', 'plots')

        config_name = get_config_filename()
        config_file = os.path.join(base_dir, config_name)

        logger.info(f"[run_formation_process] Directories:")
        logger.info(f"[run_formation_process]   Skybrush:  {skybrush_dir}")
        logger.info(f"[run_formation_process]   Processed: {processed_dir}")
        logger.info(f"[run_formation_process]   Plots:     {plots_dir}")
        logger.info(f"[run_formation_process]   Config:    {config_file}")

        # Count input files for validation
        input_files = [str(path.relative_to(skybrush_dir)) for path in Path(skybrush_dir).rglob('*.csv') if path.is_file()]
        input_count = len(input_files)
        logger.info(f"[run_formation_process] Input drone count: {input_count}")

        # 1) Process new CSV (this will raise exception if any file fails)
        logger.info(f"[run_formation_process] Step 1/2: Processing drone trajectory files...")
        processed_files = process_drone_files(skybrush_dir, processed_dir, method='cubic', dt=Params.csv_dt)

        # 2) Plot
        logger.info(f"[run_formation_process] Step 2/2: Generating 3D visualizations...")
        plot_drone_paths(base_dir, show_plots=False, processed_dir=processed_dir, plots_dir=plots_dir)

        # ====================================================================
        # FINAL VALIDATION: Verify complete processing pipeline
        # ====================================================================
        processed_count = len([f for f in os.listdir(processed_dir) if f.endswith('.csv')])
        plot_count = len([f for f in os.listdir(plots_dir) if f.endswith('.jpg')])
        expected_plots = input_count + 1  # Individual + combined

        logger.info(f"[run_formation_process] ========================================")
        logger.info(f"[run_formation_process] Pipeline Completion Summary:")
        logger.info(f"[run_formation_process]   Input files (raw):        {input_count}")
        logger.info(f"[run_formation_process]   Processed files:          {processed_count}")
        logger.info(f"[run_formation_process]   Generated plots:          {plot_count}")
        logger.info(f"[run_formation_process]   Expected plots:           {expected_plots}")

        # Validate everything matches
        validation_passed = True
        if processed_count != input_count:
            logger.error(f"[run_formation_process] ❌ VALIDATION FAILED: Processed count ({processed_count}) != Input count ({input_count})")
            validation_passed = False

        if plot_count != expected_plots:
            logger.warning(f"[run_formation_process] ⚠️ WARNING: Plot count ({plot_count}) != Expected ({expected_plots})")
            # Don't fail on plot mismatch, just warn

        if validation_passed:
            msg = f"✅ Processing completed successfully! {input_count} drones processed, {plot_count} plots generated."
            logger.info(f"[run_formation_process] {msg}")
            logger.info(f"[run_formation_process] ========================================")
            return {
                'success': True,
                'message': msg,
                'input_count': input_count,
                'processed_count': processed_count,
                'plot_count': plot_count,
                'processed_files': [os.path.basename(path) for path in processed_files],
            }
        else:
            err_msg = f"❌ Processing completed with errors: {processed_count}/{input_count} drones processed"
            logger.error(f"[run_formation_process] {err_msg}")
            logger.info(f"[run_formation_process] ========================================")
            raise RuntimeError(err_msg)

    except Exception as e:
        err = f"Processing error: {str(e)}"
        logger.error(f"[run_formation_process] ❌ FATAL ERROR: {err}", exc_info=True)
        logger.info(f"[run_formation_process] ========================================")
        return {
            'success': False,
            'message': err,
            'input_count': 0,
            'processed_count': 0,
            'plot_count': 0,
            'processed_files': [],
        }

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
        if args.verbose:
            import os
            os.environ["MDS_LOG_LEVEL"] = "DEBUG"
        init_drone_logging()

        result = run_formation_process(args.directory)
        print(result["message"])

if __name__ == "__main__":
    main()
