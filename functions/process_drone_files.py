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
    The original CSV is expected to have:
      - Time [msec]
      - x [m], y [m], z [m] (all in NWU: x=North, y=West, z=Up)
      - Red, Green, Blue (LED intensities)
    """
    required_columns = ['Time [msec]', 'x [m]', 'y [m]', 'z [m]', 'Red', 'Green', 'Blue']
    return all(col in df.columns for col in required_columns) and len(df) > 2

def smooth_trajectory(data: np.ndarray, window_length: int = 11, poly_order: int = 3) -> np.ndarray:
    """
    Apply Savitzky-Golay filter to smooth a 1D trajectory array.
    Used for optional smoothing of positions or derived velocities.
    """
    # Ensure the smoothing window doesn't exceed data length
    window_length = min(window_length, len(data)) if len(data) > 1 else 3
    # Savitzky-Golay requires an odd window length
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
    Process all drone CSV files in 'skybrush_dir' and output them (with interpolated
    and optionally smoothed time steps) into 'processed_dir'.
    
    The input CSVs are expected to be in North–West–Up (NWU) frame:
      - x [m] = North
      - y [m] = West
      - z [m] = Up

    This function temporarily flips z to negative for internal usage (some workflows
    find it convenient to treat "down" as positive), and flips it back at the end
    so the final CSV remains NWU.
    
    Args:
        skybrush_dir (str): Directory containing the original drone CSV files (NWU).
        processed_dir (str): Directory to place the processed CSV files (still NWU).
        method (str): Interpolation method ('cubic', 'akima', or 'linear').
        dt (float): Time step for resampling (seconds).
        smoothing (bool): If True, apply a Savitzky-Golay filter to position data.

    Returns:
        List[str]: List of file paths for the processed CSVs.
    """
    logging.info("[process_drone_files] Starting processing pipeline...")
    ensure_directory_exists(skybrush_dir)
    ensure_directory_exists(processed_dir)

    # Clear out any old CSVs in the processed directory
    clear_directory(processed_dir)

    processed_files = []
    csv_files = [f for f in os.listdir(skybrush_dir) if f.endswith(".csv")]
    logging.info(f"[process_drone_files] Found {len(csv_files)} CSV file(s) in '{skybrush_dir}'.")

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

            # Convert time from msec to sec
            x_sec = df['Time [msec]'] / 1000.0

            # ------------------------------------------------------------------
            # TEMPORARY FLIP Z (Up -> Down) FOR INTERNAL USAGE
            # ------------------------------------------------------------------
            # If your internal math or partial derivatives assume z>0 = down,
            # we do this flip. We'll revert it below before saving.
            df['z [m]'] *= -1

            # Build interpolators for position & LED
            # We treat (x,y,z) as (north,west,**down**) here after the flip
            cs_pos = Interpolator(x_sec, df[['x [m]', 'y [m]', 'z [m]']])
            cs_led = Interpolator(x_sec, df[['Red', 'Green', 'Blue']])

            # Create uniform time vector for resampling
            t_end = x_sec.iloc[-1]
            t_new = np.arange(0, t_end, dt)

            # Evaluate position
            pos_new = cs_pos(t_new)         # shape (N,3)
            vel_new = cs_pos.derivative()(t_new)
            acc_new = cs_pos.derivative().derivative()(t_new)

            # Evaluate LED channels
            led_new = cs_led(t_new)         # shape (N,3)

            # Optional smoothing
            if smoothing and len(t_new) > 2:
                # Smooth each position column, then recalc velocity & accel
                pos_new_sm = np.column_stack([
                    smooth_trajectory(pos_new[:, 0]),
                    smooth_trajectory(pos_new[:, 1]),
                    smooth_trajectory(pos_new[:, 2]),
                ])
                vel_new_sm = np.gradient(pos_new_sm, dt, axis=0)
                acc_new_sm = np.gradient(vel_new_sm, dt, axis=0)

                pos_new = pos_new_sm
                vel_new = vel_new_sm
                acc_new = acc_new_sm

            # ------------------------------------------------------------------
            # REVERT Z BACK TO UP FOR THE FINAL CSV
            # ------------------------------------------------------------------
            # Because we multiplied z by -1 earlier, everything in that column
            # is currently 'down'. Convert back to 'up' (NWU).
            pos_new[:, 2] *= -1
            vel_new[:, 2] *= -1
            acc_new[:, 2] *= -1

            # Prepare final output columns
            out_data = {
                'idx': np.arange(len(t_new)),
                't': t_new,
                'px': pos_new[:, 0],  # x = north
                'py': pos_new[:, 1],  # y = west
                'pz': pos_new[:, 2],  # z = up again
                'vx': vel_new[:, 0],
                'vy': vel_new[:, 1],
                'vz': vel_new[:, 2],
                'ax': acc_new[:, 0],
                'ay': acc_new[:, 1],
                'az': acc_new[:, 2],
                'yaw': np.zeros_like(t_new),         # Placeholder
                'mode': np.full_like(t_new, 70),     # Example mode
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

    logging.info(f"[process_drone_files] Completed processing {len(processed_files)} file(s).")
    return processed_files
