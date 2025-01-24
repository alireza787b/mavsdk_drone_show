# functions/process_drone_files.py
import pandas as pd
import numpy as np
from scipy.interpolate import CubicSpline, Akima1DInterpolator, interp1d
from scipy.signal import savgol_filter
from functions.file_management import ensure_directory_exists, clear_directory, setup_logging
import logging
import os
from typing import Optional, Union, List, Tuple

def validate_drone_data(df: pd.DataFrame) -> bool:
    """
    Validate input drone data for required columns and basic sanity checks.
    
    Args:
        df (pd.DataFrame): Input drone data DataFrame
    
    Returns:
        bool: Whether the data is valid for processing
    """
    required_columns = ['Time [msec]', 'x [m]', 'y [m]', 'z [m]', 'Red', 'Green', 'Blue']
    return all(col in df.columns for col in required_columns) and len(df) > 2

def smooth_trajectory(data: np.ndarray, window_length: int = 11, poly_order: int = 3) -> np.ndarray:
    """
    Apply Savitzky-Golay filter to smooth trajectory data.
    
    Args:
        data (np.ndarray): Input trajectory data
        window_length (int): Smoothing window length (odd number)
        poly_order (int): Polynomial order for smoothing
    
    Returns:
        np.ndarray: Smoothed trajectory data
    """
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
    
    Args:
        skybrush_dir (str): Source directory for drone files
        processed_dir (str): Destination directory for processed files
        method (str): Interpolation method ('cubic', 'akima')
        dt (float): Time step for resampling
        smoothing (bool): Apply trajectory smoothing
    
    Returns:
        List[str]: Processed file paths
    """
    setup_logging()
    logging.info("Starting advanced drone file processing...")

    # Prepare directories
    ensure_directory_exists(skybrush_dir)
    ensure_directory_exists(processed_dir)
    clear_directory(processed_dir)

    processed_files = []
    csv_files = [f for f in os.listdir(skybrush_dir) if f.endswith(".csv")]
    logging.info(f"Detected {len(csv_files)} CSV files for processing.")

    # Select interpolation method
    interpolation_methods = {
        'cubic': CubicSpline,
        'akima': Akima1DInterpolator,
        'linear': interp1d
    }
    Interpolator = interpolation_methods.get(method, CubicSpline)

    for filename in csv_files:
        filepath = os.path.join(skybrush_dir, filename)
        try:
            df = pd.read_csv(filepath)
            
            # Validate data
            if not validate_drone_data(df):
                logging.warning(f"Invalid data in {filename}. Skipping.")
                continue

            # Normalize time to seconds
            x = df['Time [msec]'] / 1000
            
            # Adjust Z axis (if needed)
            df['z [m]'] *= -1

            # Interpolate trajectories
            cs_pos = Interpolator(x, df[['x [m]', 'y [m]', 'z [m]']])
            cs_led = Interpolator(x, df[['Red', 'Green', 'Blue']])

            # Generate new time points
            t_new = np.arange(0, x.iloc[-1], dt)
            
            # Compute trajectories
            pos_new = cs_pos(t_new)
            vel_new = cs_pos.derivative()(t_new)
            acc_new = cs_pos.derivative().derivative()(t_new)
            led_new = cs_led(t_new)

            # Optional smoothing
            if smoothing:
                pos_new = np.array([
                    smooth_trajectory(pos_new[:, 0]),
                    smooth_trajectory(pos_new[:, 1]),
                    smooth_trajectory(pos_new[:, 2])
                ]).T
                vel_new = np.gradient(pos_new, dt, axis=0)
                acc_new = np.gradient(vel_new, dt, axis=0)

            # Prepare processed data
            data = {
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
                'yaw': np.zeros_like(t_new),  # Placeholder
                'mode': np.full_like(t_new, 70),  # Placeholder
                'ledr': led_new[:, 0],
                'ledg': led_new[:, 1],
                'ledb': led_new[:, 2],
            }

            # Save processed file
            df_new = pd.DataFrame(data)
            new_filepath = os.path.join(processed_dir, filename)
            df_new.to_csv(new_filepath, index=False)
            
            processed_files.append(new_filepath)
            logging.info(f"Processed file saved: {new_filepath}")

        except Exception as e:
            logging.error(f"Error processing {filename}: {e}")

    logging.info(f"Processed {len(processed_files)} drone files.")
    return processed_files

if __name__ == "__main__":
    # Example usage
    skybrush_dir = "/root/mavsdk_drone_show/shapes/swarm/skybrush"
    processed_dir = "/root/mavsdk_drone_show/shapes/swarm/processed"
    process_drone_files(skybrush_dir, processed_dir)