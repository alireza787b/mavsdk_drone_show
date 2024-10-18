import logging
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Set up logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def plot_drone_paths(base_dir, show_plots=True):
    """
    Plots the drone paths from processed data, with drone IDs labeled at initial points.

    Parameters:
        base_dir (str): The base directory containing the 'shapes/swarm' subdirectories.
        show_plots (bool): Flag to display plots. Defaults to True.
    """
    # Define directory paths
    processed_dir = os.path.join(base_dir, 'shapes/swarm/processed')
    plots_dir = os.path.join(base_dir, 'shapes/swarm/plots')

    # Ensure the plots directory exists
    os.makedirs(plots_dir, exist_ok=True)

    # Get a list of all the drone CSV files in the processed directory
    processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]

    # Create a colormap with enough colors
    num_drones = len(processed_files)
    colormap = plt.cm.get_cmap('tab20', num_drones)

    # Create color_dict to save colors assigned to each file
    color_dict = {file: colormap(i) for i, file in enumerate(processed_files)}

    # Set global font sizes for better readability
    plt.rcParams.update({
        'font.size': 12,
        'axes.titlesize': 14,
        'axes.labelsize': 12,
        'legend.fontsize': 12,
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
    })

    # Loop through the drone files and plot each one
    for i, file in enumerate(processed_files):
        fig = plt.figure(figsize=(12, 8))
        ax = fig.add_subplot(111, projection='3d')
        data = pd.read_csv(os.path.join(processed_dir, file))
        color = color_dict[file]

        # Extract coordinates and adjust altitude
        east = data['py']  # East corresponds to 'py'
        north = data['px']  # North corresponds to 'px'
        altitude = -data['pz']  # Invert 'pz' to represent altitude upwards

        # Plot the drone path
        ax.plot(east, north, altitude, color=color, linewidth=2)

        # Plot the initial point with a small marker
        ax.scatter(east.iloc[0], north.iloc[0], altitude.iloc[0], color=color, s=20)

        # Extract drone ID from file name (assuming format 'drone<ID>.csv')
        drone_id = ''.join(filter(str.isdigit, file))

        # Add drone ID label near the initial point
        ax.text(
            east.iloc[0], north.iloc[0], altitude.iloc[0],
            f' {drone_id}',  # Prepend a space for better spacing
            color=color, fontsize=8, ha='left', va='center'
        )

        # Set plot titles and labels
        ax.set_title(f'Drone Path for Drone {drone_id}')
        ax.set_xlabel('East (m)')
        ax.set_ylabel('North (m)')
        ax.set_zlabel('Altitude (m)')

        # Adjust view angle for better visibility
        ax.view_init(elev=30, azim=-60)

        # Set equal scaling
        max_range = np.array([
            east.max() - east.min(),
            north.max() - north.min(),
            altitude.max() - altitude.min()
        ]).max() / 2.0

        mid_east = (east.max() + east.min()) * 0.5
        mid_north = (north.max() + north.min()) * 0.5
        mid_altitude = (altitude.max() + altitude.min()) * 0.5

        ax.set_xlim(mid_east - max_range, mid_east + max_range)
        ax.set_ylim(mid_north - max_range, mid_north + max_range)
        ax.set_zlim(0, mid_altitude + max_range)

        # Save the individual plot
        plt.tight_layout()
        plt.savefig(os.path.join(plots_dir, file.split('.')[0] + '.png'))

        # Show the plot if required
        if show_plots:
            plt.show()
        plt.close(fig)

    # Combined plot for all drones
    fig_all = plt.figure(figsize=(14, 10))
    ax_all = fig_all.add_subplot(111, projection='3d')

    # Loop through all the files again to plot all drones on the same plot
    for i, file in enumerate(processed_files):
        data = pd.read_csv(os.path.join(processed_dir, file))
        color = color_dict[file]
        east = data['py']
        north = data['px']
        altitude = -data['pz']  # Invert 'pz' for correct altitude

        ax_all.plot(east, north, altitude, color=color, linewidth=2)

        # Plot the initial point with a small marker
        ax_all.scatter(east.iloc[0], north.iloc[0], altitude.iloc[0], color=color, s=20)

        # Extract drone ID from file name
        drone_id = ''.join(filter(str.isdigit, file))

        # Add drone ID label near the initial point
        ax_all.text(
            east.iloc[0], north.iloc[0], altitude.iloc[0],
            f' {drone_id}',  # Prepend a space for better spacing
            color=color, fontsize=8, ha='left', va='center'
        )

    # Set combined plot titles and labels
    ax_all.set_title('Drone Paths for All Drones')
    ax_all.set_xlabel('East (m)')
    ax_all.set_ylabel('North (m)')
    ax_all.set_zlabel('Altitude (m)')

    # Adjust view angle
    ax_all.view_init(elev=30, azim=-60)

    # Set equal scaling
    all_east = pd.concat([pd.read_csv(os.path.join(processed_dir, f))['py'] for f in processed_files])
    all_north = pd.concat([pd.read_csv(os.path.join(processed_dir, f))['px'] for f in processed_files])
    all_altitude = pd.concat([-pd.read_csv(os.path.join(processed_dir, f))['pz'] for f in processed_files])  # Invert 'pz'

    max_range = np.array([
        all_east.max() - all_east.min(),
        all_north.max() - all_north.min(),
        all_altitude.max() - all_altitude.min()
    ]).max() / 2.0

    mid_east = (all_east.max() + all_east.min()) * 0.5
    mid_north = (all_north.max() + all_north.min()) * 0.5
    mid_altitude = (all_altitude.max() + all_altitude.min()) * 0.5

    ax_all.set_xlim(mid_east - max_range, mid_east + max_range)
    ax_all.set_ylim(mid_north - max_range, mid_north + max_range)
    ax_all.set_zlim(0, mid_altitude + max_range)

    # Save the combined plot
    plt.tight_layout()
    plt.savefig(os.path.join(plots_dir, 'all_drones.png'))

    # Show the combined plot if required
    if show_plots:
        plt.show()

    # Log completion
    logging.info("All individual and combined plots are generated.")

# Example usage
# plot_drone_paths('/path/to/base_dir')
