import logging
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.legend_handler import HandlerTuple

# Set up logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def plot_drone_paths(base_dir, show_plots=True):
    """
    Plots the drone paths from Skybrush and processed data with enhanced visualization.

    Parameters:
        base_dir (str): The base directory containing the 'shapes/swarm' subdirectories.
        show_plots (bool): Flag to display plots. Defaults to True.
    """
    # Define directory paths
    skybrush_dir = os.path.join(base_dir, 'shapes/swarm/skybrush')
    processed_dir = os.path.join(base_dir, 'shapes/swarm/processed')
    plots_dir = os.path.join(base_dir, 'shapes/swarm/plots')

    # Ensure the plots directory exists
    os.makedirs(plots_dir, exist_ok=True)

    # Get a list of all the drone CSV files in the specified directories
    skybrush_files = [f for f in os.listdir(skybrush_dir) if f.endswith('.csv')]
    processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]

    # Create a colormap with enough colors
    num_drones = len(skybrush_files)
    colormap = plt.cm.get_cmap('tab20', num_drones)

    # Create color_dict to save colors assigned to each file
    color_dict = {file: colormap(i) for i, file in enumerate(skybrush_files)}

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
    for i, file in enumerate(skybrush_files):
        fig = plt.figure(figsize=(12, 8))
        ax = fig.add_subplot(111, projection='3d')
        skybrush_data = pd.read_csv(os.path.join(skybrush_dir, file))
        color = color_dict[file]

        # Extract coordinates
        east = skybrush_data['y [m]']  # East corresponds to 'y [m]'
        north = skybrush_data['x [m]']  # North corresponds to 'x [m]'
        altitude = skybrush_data['z [m]']

        # Plot the raw setpoints (Skybrush data)
        skybrush_path, = ax.plot(east, north, altitude, color=color, linestyle='--', linewidth=1, alpha=0.7, label='Raw setpoints')
        skybrush_points = ax.scatter(east, north, altitude, color=color, s=20, alpha=0.7)

        # Add arrows to indicate direction
        arrow_indices = np.linspace(0, len(east) - 1, num=10, dtype=int)
        for idx in arrow_indices:
            if idx + 1 < len(east):
                ax.quiver(
                    east.iloc[idx], north.iloc[idx], altitude.iloc[idx],
                    east.iloc[idx + 1] - east.iloc[idx],
                    north.iloc[idx + 1] - north.iloc[idx],
                    altitude.iloc[idx + 1] - altitude.iloc[idx],
                    color=color, arrow_length_ratio=0.1, linewidth=0.5
                )

        # Plot processed data if available
        if file in processed_files:
            processed_data = pd.read_csv(os.path.join(processed_dir, file))
            peast = processed_data['py']  # East corresponds to 'py'
            pnorth = processed_data['px']  # North corresponds to 'px'
            paltitude = processed_data['pz']
            processed_path, = ax.plot(peast, pnorth, paltitude, color=color, linewidth=2, label='Smoothed path')
            processed_points = ax.scatter(peast, pnorth, paltitude, color=color, s=5, alpha=0.5)

            # Add arrows to indicate direction for processed data
            arrow_indices = np.linspace(0, len(peast) - 1, num=10, dtype=int)
            for idx in arrow_indices:
                if idx + 1 < len(peast):
                    ax.quiver(
                        peast.iloc[idx], pnorth.iloc[idx], paltitude.iloc[idx],
                        peast.iloc[idx + 1] - peast.iloc[idx],
                        pnorth.iloc[idx + 1] - pnorth.iloc[idx],
                        paltitude.iloc[idx + 1] - paltitude.iloc[idx],
                        color=color, arrow_length_ratio=0.1, linewidth=0.5
                    )

            # Annotate start and end points
            ax.text(peast.iloc[0], pnorth.iloc[0], paltitude.iloc[0], 'Start', color='green', fontsize=10)
            ax.text(peast.iloc[-1], pnorth.iloc[-1], paltitude.iloc[-1], 'End', color='red', fontsize=10)

        # Set plot titles and labels
        ax.set_title('Drone Path for ' + file.replace('.csv', ''))
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

        # Add a legend
        ax.legend()

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
    for file in skybrush_files:
        skybrush_data = pd.read_csv(os.path.join(skybrush_dir, file))
        color = color_dict[file]
        east = skybrush_data['y [m]']
        north = skybrush_data['x [m]']
        altitude = skybrush_data['z [m]']
        ax_all.plot(east, north, altitude, color=color, linestyle='--', linewidth=1, alpha=0.7)
        ax_all.scatter(east, north, altitude, color=color, s=20, alpha=0.7)

        # Add arrows to indicate direction
        arrow_indices = np.linspace(0, len(east) - 1, num=10, dtype=int)
        for idx in arrow_indices:
            if idx + 1 < len(east):
                ax_all.quiver(
                    east.iloc[idx], north.iloc[idx], altitude.iloc[idx],
                    east.iloc[idx + 1] - east.iloc[idx],
                    north.iloc[idx + 1] - north.iloc[idx],
                    altitude.iloc[idx + 1] - altitude.iloc[idx],
                    color=color, arrow_length_ratio=0.1, linewidth=0.5
                )

    for file in processed_files:
        processed_data = pd.read_csv(os.path.join(processed_dir, file))
        color = color_dict[file] if file in color_dict else 'blue'
        peast = processed_data['py']
        pnorth = processed_data['px']
        paltitude = processed_data['pz']
        ax_all.plot(peast, pnorth, paltitude, color=color, linewidth=2)
        ax_all.scatter(peast, pnorth, paltitude, color=color, s=5, alpha=0.5)

        # Add arrows to indicate direction
        arrow_indices = np.linspace(0, len(peast) - 1, num=10, dtype=int)
        for idx in arrow_indices:
            if idx + 1 < len(peast):
                ax_all.quiver(
                    peast.iloc[idx], pnorth.iloc[idx], paltitude.iloc[idx],
                    peast.iloc[idx + 1] - peast.iloc[idx],
                    pnorth.iloc[idx + 1] - pnorth.iloc[idx],
                    paltitude.iloc[idx + 1] - paltitude.iloc[idx],
                    color=color, arrow_length_ratio=0.1, linewidth=0.5
                )

        # Annotate start and end points
        ax_all.text(peast.iloc[0], pnorth.iloc[0], paltitude.iloc[0], 'Start', color='green', fontsize=10)
        ax_all.text(peast.iloc[-1], pnorth.iloc[-1], paltitude.iloc[-1], 'End', color='red', fontsize=10)

    # Set combined plot titles and labels
    ax_all.set_title('Drone Paths for All Drones')
    ax_all.set_xlabel('East (m)')
    ax_all.set_ylabel('North (m)')
    ax_all.set_zlabel('Altitude (m)')

    # Adjust view angle
    ax_all.view_init(elev=30, azim=-60)

    # Set equal scaling
    all_east = np.concatenate([pd.read_csv(os.path.join(skybrush_dir, f))['y [m]'] for f in skybrush_files])
    all_north = np.concatenate([pd.read_csv(os.path.join(skybrush_dir, f))['x [m]'] for f in skybrush_files])
    all_altitude = np.concatenate([pd.read_csv(os.path.join(skybrush_dir, f))['z [m]'] for f in skybrush_files])
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

    # Add a legend
    ax_all.legend(['Raw setpoints', 'Smoothed path'], loc='upper right')

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
