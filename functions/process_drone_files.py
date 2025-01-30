# functions/process_drone_files.py
import pandas as pd
import numpy as np
from scipy.interpolate import CubicSpline, Akima1DInterpolator, interp1d
from scipy.signal import savgol_filter
from functions.file_management import ensure_directory_exists, clear_directory
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
    # Ensure window doesn't exceed data length
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
    Process drone files in 'skybrush_dir' -> 'processed_dir'.
    We'll rely on the top-level logging config from process_formation.
    """
    logging.info("[process_drone_files] Starting processing pipeline...")
    ensure_directory_exists(skybrush_dir)
    ensure_directory_exists(processed_dir)

    # Clear old processed CSVs
    clear_directory(processed_dir)

    processed_files = []
    csv_files = [f for f in os.listdir(skybrush_dir) if f.endswith(".csv")]
    logging.info(f"[process_drone_files] Found {len(csv_files)} CSV files in {skybrush_dir}.")

    interpolation_methods = {
        'cubic': CubicSpline,
        'akima': Akima1DInterpolator,
        'linear': interp1d
    }
    Interpolator = interpolation_methods.get(method, CubicSpline)

    for filename in csv_files:
        filepath = os.path.join(skybrush_dir, filename)
        logging.debug(f"[process_drone_files] Reading {filename} ...")
        try:
            df = pd.read_csv(filepath)
            if not validate_drone_data(df):
                logging.warning(f"[process_drone_files] Invalid data in {filename}, skipping.")
                continue

            # Convert time to seconds
            x_sec = df['Time [msec]'] / 1000.0

            # Flip z for internal usage
            df['z [m]'] *= -1

            # Build interpolators
            cs_pos = Interpolator(x_sec, df[['x [m]', 'y [m]', 'z [m]']])
            cs_led = Interpolator(x_sec, df[['Red', 'Green', 'Blue']])

            # Generate new time steps
            t_end = x_sec.iloc[-1]
            t_new = np.arange(0, t_end, dt)

            # Evaluate position, velocity, acceleration
            pos_new = cs_pos(t_new)
            vel_new = cs_pos.derivative()(t_new)
            acc_new = cs_pos.derivative().derivative()(t_new)
            led_new = cs_led(t_new)

            if smoothing and len(t_new) > 2:
                pos_new = np.column_stack([
                    smooth_trajectory(pos_new[:, 0]),
                    smooth_trajectory(pos_new[:, 1]),
                    smooth_trajectory(pos_new[:, 2])
                ])
                vel_new = np.gradient(pos_new, dt, axis=0)
                acc_new = np.gradient(vel_new, dt, axis=0)

            out_data = {
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
                'ledb': led_new[:, 2]
            }

            out_path = os.path.join(processed_dir, filename)
            pd.DataFrame(out_data).to_csv(out_path, index=False)
            processed_files.append(out_path)
            logging.info(f"[process_drone_files] Processed and saved: {out_path}")

        except Exception as e:
            logging.error(f"[process_drone_files] Error processing {filename}: {e}", exc_info=True)

    logging.info(f"[process_drone_files] Completed processing {len(processed_files)} files.")
    return processed_files
