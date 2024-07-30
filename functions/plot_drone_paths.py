import logging
import os
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
from matplotlib.legend_handler import HandlerTuple

# Set up logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def plot_drone_paths(base_dir, show_plots=True):
    """
    Plots the drone paths from Skybrush and processed data.

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

    # Create a colormap
    colormap = plt.cm.get_cmap('tab10')

    # Create color_dict to save colors assigned to each file
    color_dict = {file: colormap(i % 10) for i, file in enumerate(skybrush_files)}

    # Loop through the drone files and plot each one
    for i, file in enumerate(skybrush_files):
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
        skybrush_data = pd.read_csv(os.path.join(skybrush_dir, file))
        color = color_dict[file]
        skybrush_path, = ax.plot(skybrush_data['x [m]'], skybrush_data['y [m]'], skybrush_data['z [m]'], color=color, alpha=0.2)
        skybrush_points = ax.scatter(skybrush_data['x [m]'], skybrush_data['y [m]'], skybrush_data['z [m]'], color=color, s=20)

        if file in processed_files:
            processed_data = pd.read_csv(os.path.join(processed_dir, file))
            processed_path, = ax.plot(processed_data['px'], processed_data['py'], processed_data['pz'], color=color)
            processed_points = ax.scatter(processed_data['px'], processed_data['py'], processed_data['pz'], color=color, s=5, alpha=0.2)

        # Set plot titles and labels
        ax.set_title('Drone Paths for ' + file.replace('.csv', ''))
        ax.set_xlabel('North (m)')
        ax.set_ylabel('East (m)')
        ax.set_zlabel('Height (m)')

        # Add a legend
        ax.legend([(skybrush_points, skybrush_path), (processed_points, processed_path)],
                  ['Raw setpoints', 'Smoothed path'],
                  handler_map={tuple: HandlerTuple(ndivide=None)})

        # Save the individual plot
        plt.savefig(os.path.join(plots_dir, file.split('.')[0] + '.png'))

        # Show the plot if required
        if show_plots:
            plt.show()
        plt.close(fig)
    
    # Combined plot for all drones
    fig_all = plt.figure()
    ax_all = fig_all.add_subplot(111, projection='3d')

    # Loop through all the files again to plot all drones on the same plot
    for file in skybrush_files:
        data = pd.read_csv(os.path.join(skybrush_dir, file))
        color = color_dict[file]
        ax_all.plot(data['x [m]'], data['y [m]'], data['z [m]'], color=color, alpha=0.2)
        ax_all.scatter(data['x [m]'], data['y [m]'], data['z [m]'], color=color, s=20)

    for file in processed_files:
        data = pd.read_csv(os.path.join(processed_dir, file))
        color = color_dict[file] if file in color_dict else 'blue'
        ax_all.plot(data['px'], data['py'], data['pz'], color=color)
        ax_all.scatter(data['px'], data['py'], data['pz'], color=color, s=5, alpha=0.2)

    # Set combined plot titles and labels
    ax_all.set_title('Drone Paths for All Drones')
    ax_all.set_xlabel('North (m)')
    ax_all.set_ylabel('East (m)')
    ax_all.set_zlabel('Height (m)')

    # Add a legend
    ax_all.legend([(skybrush_points, skybrush_path), (processed_points, processed_path)],
                  ['Raw setpoints', 'Smoothed path'],
                  handler_map={tuple: HandlerTuple(ndivide=None)})

    # Save the combined plot
    plt.savefig(os.path.join(plots_dir, 'all_drones.png'))

    # Show the combined plot if required
    if show_plots:
        plt.show()

    # Log completion
    logging.info("All individual and combined plots are generated.")

# Example usage
# plot_drone_paths('/path/to/base_dir')
