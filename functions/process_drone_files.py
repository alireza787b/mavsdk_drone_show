# functions/process_drone_files.py
import pandas as pd
import numpy as np
from scipy.interpolate import CubicSpline, Akima1DInterpolator
from functions.file_management import ensure_directory_exists, clear_directory, setup_logging
import logging
import os

def process_drone_files(skybrush_dir, processed_dir, method='cubic', dt=0.05):
    setup_logging()
    logging.info("Starting processing of drone files...")

    # Ensure directories exist
    ensure_directory_exists(skybrush_dir)
    ensure_directory_exists(processed_dir)

    # Clear processed directory to avoid data mixing
    clear_directory(processed_dir)

    all_files = os.listdir(skybrush_dir)
    csv_files = [f for f in all_files if f.endswith(".csv")]
    logging.info(f"Detected {len(csv_files)} CSV files for processing.")

    for filename in csv_files:
        filepath = os.path.join(skybrush_dir, filename)
        logging.info(f"Processing {filename}...")

        try:
            df = pd.read_csv(filepath)
            required_columns = ['Time [msec]', 'x [m]', 'y [m]', 'z [m]', 'Red', 'Green', 'Blue']
            if not all(col in df.columns for col in required_columns):
                logging.error(f"Missing one or more required columns in {filename}.")
                continue

            x = df['Time [msec]'] / 1000
            df['z [m]'] = df['z [m]'] * -1  # Adjust Z axis if necessary

            if method == 'cubic':
                Interpolator = CubicSpline
            elif method == 'akima':
                Interpolator = Akima1DInterpolator
            else:
                logging.warning(f"Unknown interpolation method '{method}'. Using 'cubic'.")
                Interpolator = CubicSpline

            cs_pos = Interpolator(x, df[['x [m]', 'y [m]', 'z [m]']])
            cs_led = Interpolator(x, df[['Red', 'Green', 'Blue']])

            t_new = np.arange(0, x.iloc[-1], dt)
            pos_new = cs_pos(t_new)
            led_new = cs_led(t_new)
            vel_new = cs_pos.derivative()(t_new)
            acc_new = cs_pos.derivative().derivative()(t_new)

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
                'yaw': 0,  # placeholder
                'mode': 70,  # placeholder
                'ledr': led_new[:, 0],
                'ledg': led_new[:, 1],
                'ledb': led_new[:, 2],
            }
            df_new = pd.DataFrame(data)
            new_filepath = os.path.join(processed_dir, filename)
            df_new.to_csv(new_filepath, index=False)
            logging.info(f"Processed file saved to {new_filepath}")
        except Exception as e:
            logging.error(f"Error processing {filename}: {e}")

    logging.info("Processing of drone files complete!")

