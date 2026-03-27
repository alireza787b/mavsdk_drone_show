import pandas as pd
import numpy as np
from scipy.interpolate import CubicSpline, Akima1DInterpolator, interp1d
from scipy.signal import savgol_filter
from functions.file_management import ensure_directory_exists, clear_directory
import logging
import os
from typing import List
from pathlib import Path

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
    return all(col in df.columns for col in required_columns) and len(df) >= 2

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
        window_length -= 1
    if window_length < 3:
        return data
    poly_order = min(poly_order, window_length - 1)
    if poly_order < 1:
        return data
    return savgol_filter(data, window_length, poly_order)


def build_output_time_vector(t_end: float, dt: float) -> np.ndarray:
    """
    Build a stable output time vector that always includes the final timestamp.
    """
    if t_end <= 0:
        return np.array([0.0], dtype=float)

    t_new = np.arange(0, t_end + (dt * 0.5), dt, dtype=float)
    if t_new.size == 0:
        return np.array([0.0, t_end], dtype=float)

    if t_new[-1] < t_end:
        t_new = np.append(t_new, t_end)
    else:
        t_new[-1] = t_end

    return t_new


def _build_interpolator(method: str, t_original: np.ndarray, values: pd.DataFrame | np.ndarray):
    """Build an interpolator with a stable sample axis across all methods."""
    samples = np.asarray(values, dtype=float)

    if method == 'linear':
        return interp1d(
            t_original,
            samples,
            axis=0,
            bounds_error=False,
            fill_value='extrapolate',
        )

    if method == 'akima':
        return Akima1DInterpolator(t_original, samples, axis=0)

    return CubicSpline(t_original, samples, axis=0)

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
    logging.info("[process_drone_files] ============================================")
    logging.info("[process_drone_files] Starting drone show processing pipeline...")
    logging.info("[process_drone_files] ============================================")
    ensure_directory_exists(skybrush_dir)
    ensure_directory_exists(processed_dir)

    # Clear out old processed CSVs
    clear_directory(processed_dir)

    processed_files = []
    csv_paths = sorted(p for p in Path(skybrush_dir).rglob("*.csv") if p.is_file())
    csv_files = [str(path.relative_to(skybrush_dir)) for path in csv_paths]
    logging.info(f"[process_drone_files] ✅ Found {len(csv_files)} CSV file(s) in '{skybrush_dir}'.")

    # List all files for verification
    if csv_files:
        logging.info(f"[process_drone_files] Raw input files: {sorted(csv_files)}")

    basenames = [path.name for path in csv_paths]
    duplicate_basenames = sorted({name for name in basenames if basenames.count(name) > 1})
    if duplicate_basenames:
        raise RuntimeError(
            f"Duplicate CSV filenames detected in SkyBrush import: {duplicate_basenames}. "
            "Each drone CSV must have a unique filename."
        )

    for filepath in csv_paths:
        filename = filepath.name
        logging.debug(f"[process_drone_files] Reading {filepath.relative_to(skybrush_dir)} ...")
        try:
            df = pd.read_csv(filepath)
            if not validate_drone_data(df):
                logging.warning(f"[process_drone_files] Invalid data in {filename}, skipping.")
                continue

            # Convert timestamps from msec to sec
            df = df.sort_values('Time [msec]').drop_duplicates(subset='Time [msec]', keep='last').reset_index(drop=True)
            t_original = (df['Time [msec]'] / 1000.0).astype(float)

            # Convert Blender NWU -> NED
            #    X (north) => X (north) : unchanged
            #    Y (west)  => Y (east)  : multiply by -1
            #    Z (up)    => Z (down)  : multiply by -1
            df['y [m]'] = -df['y [m]']
            df['z [m]'] = -df['z [m]']

            # Short trajectories cannot support higher-order interpolation reliably.
            effective_method = method
            if len(t_original) < 4 and method == 'cubic':
                effective_method = 'linear'
                logging.info(
                    f"[process_drone_files] Using linear interpolation for {filename} "
                    f"because it only has {len(t_original)} points."
                )

            # Prepare interpolators for position (x,y,z) and LED (r,g,b)
            cs_pos = _build_interpolator(effective_method, t_original, df[['x [m]', 'y [m]', 'z [m]']])
            cs_led = _build_interpolator(effective_method, t_original, df[['Red', 'Green', 'Blue']])

            # Create uniform time vector (0..t_end) with step dt
            t_end = t_original.iloc[-1]
            t_new = build_output_time_vector(t_end, dt)

            # Interpolate position
            pos_new = np.asarray(cs_pos(t_new), dtype=float)  # shape: (N, 3)
            if hasattr(cs_pos, 'derivative'):
                vel_new = cs_pos.derivative()(t_new)
                acc_new = cs_pos.derivative().derivative()(t_new)
            else:
                vel_new = np.gradient(pos_new, dt, axis=0)
                acc_new = np.gradient(vel_new, dt, axis=0)

            # Interpolate LED
            led_new = np.asarray(cs_led(t_new), dtype=float)  # shape: (N, 3)

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
            logging.error(f"[process_drone_files] ❌ ERROR processing {filepath.relative_to(skybrush_dir)}: {e}", exc_info=True)

    # ====================================================================
    # CRITICAL VALIDATION: Verify all input files were processed
    # ====================================================================
    input_count = len(csv_files)
    output_count = len(processed_files)

    logging.info(f"[process_drone_files] ============================================")
    logging.info(f"[process_drone_files] Processing Summary:")
    logging.info(f"[process_drone_files]   Input files:  {input_count}")
    logging.info(f"[process_drone_files]   Output files: {output_count}")

    if output_count == input_count:
        logging.info(f"[process_drone_files] ✅ SUCCESS: All {input_count} drones processed correctly!")
        logging.info(f"[process_drone_files] Processed files: {[os.path.basename(f) for f in processed_files]}")
    else:
        missing_count = input_count - output_count
        logging.error(f"[process_drone_files] ⚠️ WARNING: {missing_count} file(s) failed to process!")

        # Identify which files failed
        input_basenames = {f.replace('.csv', '') for f in csv_files}
        output_basenames = {os.path.basename(f).replace('.csv', '') for f in processed_files}
        failed_files = input_basenames - output_basenames

        if failed_files:
            logging.error(f"[process_drone_files] Failed files: {sorted(failed_files)}")

        # Raise an exception to prevent silent failures
        raise RuntimeError(
            f"Processing incomplete: {output_count}/{input_count} files processed successfully. "
            f"Failed files: {sorted(failed_files)}"
        )

    logging.info(f"[process_drone_files] ============================================")
    return processed_files
