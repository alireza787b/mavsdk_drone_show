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

    The expected columns in the source CSV are:
      - 'Time [msec]'
      - 'x [m]' (Blender X = North)
      - 'y [m]' (Blender Y = West)
      - 'z [m]' (Blender Z = Up)
      - 'Red', 'Green', 'Blue' for LED colors
    """
    required_columns = ['Time [msec]', 'x [m]', 'y [m]', 'z [m]', 'Red', 'Green', 'Blue']
    return all(col in df.columns for col in required_columns) and len(df) > 2

def smooth_trajectory(data: np.ndarray, window_length: int = 11, poly_order: int = 3) -> np.ndarray:
    """
    Apply Savitzky-Golay filter to smooth trajectory data (1D).
    
    If the data length is smaller than 'window_length', we reduce the window 
    to fit. We also ensure the window_length is odd, as required by Savitzky-Golay.
    """
    n_points = len(data)
    if n_points <= 2:
        return data  # Not enough points to smooth meaningfully
    window_length = min(window_length, n_points)
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
    Process and interpolate (x,y,z) + LED data from original Blender NWU CSVs in 'skybrush_dir', 
    then output them in NED format to 'processed_dir'.

    The steps:
      1) Read each CSV and ensure columns 'x [m], y [m], z [m]' are in Blender NWU (North, West, Up).
      2) Convert them to NED (North, East, Down) by flipping the sign of y and z:
         - y_east = -y_west
         - z_down = -z_up
      3) Interpolate position, velocity, and acceleration in the time domain (0..t_end) at intervals dt.
      4) Optionally apply a Savitzky-Golay filter to smooth the position, then recompute velocity/acceleration via np.gradient.
      5) Save the final CSV with px,py,pz in NED, meaning:
         - px = north (m)
         - py = east  (m)
         - pz = down  (m)
         similarly for vx,vy,vz and ax,ay,az.

    Args:
        skybrush_dir (str): Directory with original NWU CSV files from Skybrush exports.
        processed_dir (str): Directory to place the final CSVs, now in NED.
        method (str): Interpolation method ('cubic', 'akima', or 'linear').
        dt (float): Output time step in seconds (e.g., 0.05 => 20 Hz).
        smoothing (bool): Whether to apply Savitzky-Golay smoothing to position data.

    Returns:
        List[str]: List of file paths for the processed CSVs.
    """
    logging.info("[process_drone_files] Starting processing pipeline...")
    ensure_directory_exists(skybrush_dir)
    ensure_directory_exists(processed_dir)

    # Clear out old processed CSVs
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

            # Convert timestamps from msec to sec
            t_original = df['Time [msec]'] / 1000.0

            # Convert Blender NWU -> NED
            #    X (north) => X (north) : unchanged
            #    Y (west)  => Y (east)  : multiply by -1
            #    Z (up)    => Z (down)  : multiply by -1
            df['y [m]'] = -df['y [m]']
            df['z [m]'] = -df['z [m]']

            # Prepare interpolators for position (x,y,z) and LED (r,g,b)
            cs_pos = Interpolator(t_original, df[['x [m]', 'y [m]', 'z [m]']])
            cs_led = Interpolator(t_original, df[['Red', 'Green', 'Blue']])

            # Create uniform time vector (0..t_end) with step dt
            t_end = t_original.iloc[-1]
            t_new = np.arange(0, t_end, dt)

            # Interpolate position
            pos_new = cs_pos(t_new)         # shape: (N, 3)
            vel_new = cs_pos.derivative()(t_new)
            acc_new = cs_pos.derivative().derivative()(t_new)

            # Interpolate LED
            led_new = cs_led(t_new)         # shape: (N, 3)

            # Optional smoothing of position data
            if smoothing and len(t_new) > 2:
                # Smooth each position axis (north, east, down)
                pos_smoothed = np.column_stack([
                    smooth_trajectory(pos_new[:, 0]),
                    smooth_trajectory(pos_new[:, 1]),
                    smooth_trajectory(pos_new[:, 2]),
                ])
                vel_smoothed = np.gradient(pos_smoothed, dt, axis=0)
                acc_smoothed = np.gradient(vel_smoothed, dt, axis=0)

                pos_new = pos_smoothed
                vel_new = vel_smoothed
                acc_new = acc_smoothed

            # Build final output data
            out_data = {
                'idx': np.arange(len(t_new)),
                't': t_new,
                'px': pos_new[:, 0],  # N
                'py': pos_new[:, 1],  # E
                'pz': pos_new[:, 2],  # D
                'vx': vel_new[:, 0],
                'vy': vel_new[:, 1],
                'vz': vel_new[:, 2],
                'ax': acc_new[:, 0],
                'ay': acc_new[:, 1],
                'az': acc_new[:, 2],
                'yaw': np.zeros_like(t_new),        # optional placeholder
                'mode': np.full_like(t_new, 70),    # optional placeholder
                'ledr': led_new[:, 0],
                'ledg': led_new[:, 1],
                'ledb': led_new[:, 2],
            }

            out_path = os.path.join(processed_dir, filename)
            pd.DataFrame(out_data).to_csv(out_path, index=False)
            processed_files.append(out_path)
            logging.info(f"[process_drone_files] Processed and saved NED CSV: {out_path}")

        except Exception as e:
            logging.error(f"[process_drone_files] Error processing {filename}: {e}", exc_info=True)

    logging.info(f"[process_drone_files] Completed processing {len(processed_files)} file(s).")
    return processed_files
