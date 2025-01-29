import pandas as pd
import numpy as np
from scipy.interpolate import CubicSpline, Akima1DInterpolator, interp1d
from scipy.signal import savgol_filter
from functions.file_management import ensure_directory_exists, clear_directory, setup_logging
import logging
import os
from typing import List

def validate_drone_data(df: pd.DataFrame) -> bool:
    """
    Validate input drone data for required columns and basic sanity checks.
    """
    required_columns = ['Time [msec]', 'x [m]', 'y [m]', 'z [m]', 'Red', 'Green', 'Blue']
    return all(col in df.columns for col in required_columns) and len(df) > 2

def smooth_trajectory(data: np.ndarray, window_length: int = 11, poly_order: int = 3) -> np.ndarray:
    """
    Apply Savitzky-Golay filter to smooth trajectory data.
    """
    # Ensure window_length doesn't exceed data length
    window_length = min(window_length, len(data)) if len(data) > 1 else 3
    if window_length % 2 == 0:
        window_length += 1
    return savgol_filter(data, window_length, poly_order)

def process_drone_files(
    skybrush_dir: str, 
    processed_dir: str, 
    method: str = 'cubic', 
    dt: float = 0.05, 
    smoothing: bool = True
) -> List[str]:
    """
    Process drone files with advanced trajectory generation.
    - Clears the existing processed_dir,
    - Reads CSVs from skybrush_dir,
    - Outputs processed CSVs to processed_dir.

    Returns:
        A list of processed file paths.
    """
    setup_logging()
    logging.info(f"[process_drone_files] Starting with skybrush_dir={skybrush_dir}, processed_dir={processed_dir}")

    ensure_directory_exists(skybrush_dir)
    ensure_directory_exists(processed_dir)
    # Remove old processed files
    clear_directory(processed_dir)

    processed_files = []
    csv_files = [f for f in os.listdir(skybrush_dir) if f.endswith(".csv")]
    logging.info(f"Detected {len(csv_files)} CSV files in {skybrush_dir} to process.")

    # Choose interpolation
    interpolation_methods = {
        'cubic': CubicSpline,
        'akima': Akima1DInterpolator,
        'linear': interp1d
    }
    Interpolator = interpolation_methods.get(method, CubicSpline)

    for filename in csv_files:
        src_path = os.path.join(skybrush_dir, filename)
        try:
            df = pd.read_csv(src_path)

            if not validate_drone_data(df):
                logging.warning(f"[process_drone_files] Invalid data in {filename}, skipping.")
                continue

            # Time in seconds
            t_sec = df['Time [msec]'] / 1000
            # Invert Z if needed
            df['z [m]'] *= -1

            # Build interpolators
            cs_pos = Interpolator(t_sec, df[['x [m]', 'y [m]', 'z [m]']])
            cs_led = Interpolator(t_sec, df[['Red', 'Green', 'Blue']])

            # Make new timeline
            t_end = t_sec.iloc[-1]
            t_new = np.arange(0, t_end, dt)

            # Interpolate
            pos_new = cs_pos(t_new)
            vel_new = cs_pos.derivative()(t_new)
            acc_new = cs_pos.derivative().derivative()(t_new)
            led_new = cs_led(t_new)

            # Optional smoothing
            if smoothing and len(t_new) > 2:
                pos_new = np.column_stack([
                    smooth_trajectory(pos_new[:, 0]),
                    smooth_trajectory(pos_new[:, 1]),
                    smooth_trajectory(pos_new[:, 2])
                ])
                vel_new = np.gradient(pos_new, dt, axis=0)
                acc_new = np.gradient(vel_new, dt, axis=0)

            out_df = pd.DataFrame({
                'idx': np.arange(len(t_new)),
                't': t_new,
                'px': pos_new[:, 0],
                'py': pos_new[:, 1],
                'pz': pos_new[:, 2],
                'vx': vel_new[:, 0],
                'vy': vel_new[:, 1],
                'vz': vel_new[:, 2],
                'ax': acc_new[:, 0],
                'ay': acc_new[:, 1],
                'az': acc_new[:, 2],
                'yaw': np.zeros_like(t_new),
                'mode': np.full_like(t_new, 70),
                'ledr': led_new[:, 0],
                'ledg': led_new[:, 1],
                'ledb': led_new[:, 2],
            })

            processed_filepath = os.path.join(processed_dir, filename)
            out_df.to_csv(processed_filepath, index=False)
            processed_files.append(processed_filepath)
            logging.info(f"[process_drone_files] Processed -> {processed_filepath}")

        except Exception as ex:
            logging.error(f"[process_drone_files] Error processing {filename}: {ex}", exc_info=True)

    logging.info(f"[process_drone_files] Finished. {len(processed_files)} files processed.")
    return processed_files

if __name__ == "__main__":
    # Example usage or debugging
    skybrush_test = "./shapes/swarm/skybrush"
    processed_test = "./shapes/swarm/processed"
    process_drone_files(skybrush_test, processed_test)
