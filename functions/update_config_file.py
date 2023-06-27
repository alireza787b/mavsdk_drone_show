import pandas as pd
import os

def update_config_file(skybrush_dir, config_file):
    """
    Function to update the 'x' and 'y' columns of the config file with the initial position of each drone.
    
    Args:
    skybrush_dir (str): The directory containing the drone files.
    config_file (str): The path of the config file to be updated.
    
    Returns:
    None
    """
    # Check if directories exist
    if not os.path.exists(skybrush_dir):
        print(f"Directory not found: {skybrush_dir}")
        return
    
    # Load the config file
    config_df = pd.read_csv(config_file)

    # Process all csv files in the skybrush directory
    for filename in os.listdir(skybrush_dir):
        if filename.endswith(".csv"):

            try:
                # Load csv data
                filepath = os.path.join(skybrush_dir, filename)
                df = pd.read_csv(filepath)
                
                # Get the initial position
                initial_x = df.loc[0, 'x [m]']
                initial_y = df.loc[0, 'y [m]']

                # Get the drone ID
                drone_id = int(filename.replace('Drone', '').replace('.csv', ''))

                # Update the config file
                config_df.loc[config_df['pos_id'] == drone_id, 'x'] = initial_x
                config_df.loc[config_df['pos_id'] == drone_id, 'y'] = initial_y

            except Exception as e:
                print(f"Error processing file {filename}: {e}")
                
    # Save the updated config file
    config_df.to_csv(config_file, index=False)
    print(f"Config file updated: {config_file}")
