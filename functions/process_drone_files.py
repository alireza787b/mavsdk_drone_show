import pandas as pd
import numpy as np
from scipy.interpolate import CubicSpline, Akima1DInterpolator
import os

def process_drone_files(skybrush_dir, processed_dir, method='cubic', dt=0.05):

    print("Starting processing...")

    # Check directories
    if not os.path.exists(skybrush_dir):
        print(f"Error: Directory not found - {skybrush_dir}")
        return

    if not os.path.exists(processed_dir):
        print(f"Error: Directory not found - {processed_dir}")
        return
    
    all_files = os.listdir(skybrush_dir)
    csv_files = [f for f in all_files if f.endswith(".csv")]
    print(f"Detected {len(csv_files)} CSV files for processing.")
    
    # Process all CSVs
    for filename in csv_files:

        filepath = os.path.join(skybrush_dir, filename)
        print(f"Processing {filename}...")

        # Ensure file can be read and required columns exist
        try:
            df = pd.read_csv(filepath)
            required_columns = ['Time [msec]', 'x [m]', 'y [m]', 'z [m]', 'Red', 'Green', 'Blue']
            for col in required_columns:
                if col not in df.columns:
                    print(f"Error: {filename} is missing column {col}.")
                    continue
        except Exception as e:
            print(f"Error reading file {filename}: {e}")
            continue
        
        try:
            x = df['Time [msec]'] / 1000
            df['z [m]'] = df['z [m]'] * -1

            if method == 'cubic':
                Interpolator = CubicSpline
            elif method == 'akima':
                Interpolator = Akima1DInterpolator
            else:
                print(f"Warning: Unknown interpolation method '{method}'. Using 'cubic'.")
                Interpolator = CubicSpline

            cs_pos = Interpolator(x, df[['x [m]', 'y [m]', 'z [m]']])
            cs_led = Interpolator(x, df[['Red', 'Green', 'Blue']])
        except Exception as e:
            print(f"Error in interpolation for file {filename}: {e}")
            continue
        
        try:
            t_new = np.arange(0, x.iloc[-1], dt)
            pos_new = cs_pos(t_new)
            led_new = cs_led(t_new)
            vel_new = cs_pos.derivative()(t_new)
            acc_new = cs_pos.derivative().derivative()(t_new)
            
            # Create new DataFrame
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
            print(f"Processed file saved to {new_filepath}")
        except Exception as e:
            print(f"Error generating or saving processed data for file {filename}: {e}")

    print("Processing complete!")
