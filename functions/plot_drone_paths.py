import os
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
from matplotlib.legend_handler import HandlerTuple

def plot_drone_paths(skybrush_dir, processed_dir, show_plots=True):
    # Get a list of all the drone CSV files in the specified directories
    skybrush_files = [f for f in os.listdir(skybrush_dir) if f.endswith('.csv')]
    processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]
    
    # Create a colormap
    colormap = plt.cm.get_cmap('tab10')
    
    # Create color_dict to save colors assigned to each file
    color_dict = {file: colormap(i % 10) for i, file in enumerate(skybrush_files)}
    
    # Loop through the drone files and plot each one
    for i, file in enumerate(skybrush_files):
        # Create a 3D figure and axis object for each drone
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')

        # Load the data from the SkyBrush CSV file
        skybrush_data = pd.read_csv(os.path.join(skybrush_dir, file))

        # Get a color from the colormap using color_dict
        color = color_dict[file]

        # Plot the SkyBrush drone path as a line and points, convert Z to height
        skybrush_path, = ax.plot(skybrush_data['x [m]'], skybrush_data['y [m]'], skybrush_data['z [m]'], color=color, alpha=0.2)
        skybrush_points = ax.scatter(skybrush_data['x [m]'], skybrush_data['y [m]'], skybrush_data['z [m]'], color=color, s=20)

        # Check if corresponding processed file exists
        if file in processed_files:
            # Load the data from the processed CSV file
            processed_data = pd.read_csv(os.path.join(processed_dir, file))

            # Plot the processed drone path as a line and points, convert Z to height
            processed_path, = ax.plot(processed_data['px'], processed_data['py'], processed_data['pz'], color=color)
            processed_points = ax.scatter(processed_data['px'], processed_data['py'], processed_data['pz'], color=color, s=5, alpha=0.2)

        # Set the title (without .csv) and axis labels
        ax.set_title('Drone Paths for ' + file.replace('.csv', ''))
        ax.set_xlabel('North (m)')
        ax.set_ylabel('East (m)')
        ax.set_zlabel('Height (m)')

        # Add a legend
        ax.legend([(skybrush_points, skybrush_path), (processed_points, processed_path)],
                  ['Raw setpoints', 'Smoothed path'],
                  handler_map={tuple: HandlerTuple(ndivide=None)})

        # Save the plot as an image
        plt.savefig('shapes/swarm/plots/' + file.split('.')[0] + '.png') 

        # Show the plot
        if show_plots:
            plt.show()

    # Create a 3D figure and axis object for all drones plot
    fig_all = plt.figure()
    ax_all = fig_all.add_subplot(111, projection='3d')

    # Loop through all the files again to plot all drones on the same plot
    for file in skybrush_files + processed_files:
        # Load the data from the CSV file
        data = pd.read_csv(os.path.join(skybrush_dir if file in skybrush_files else processed_dir, file))

        # Get a color from the colormap using color_dict
        color = color_dict[file] if file in skybrush_files else 'blue'  # for processed_files which were not in skybrush_files, use default color 'blue'

        # Plot the drone path as a simple line and points, convert Z to height
        path, = ax_all.plot(data['x [m]' if file in skybrush_files else 'px'], 
                            data['y [m]' if file in skybrush_files else 'py'], 
                            data['z [m]' if file in skybrush_files else 'pz'], 
                            color=color, 
                            alpha=0.2 if file in skybrush_files else 1.0)
        points = ax_all.scatter(data['x [m]' if file in skybrush_files else 'px'], 
                                data['y [m]' if file in skybrush_files else 'py'], 
                                data['z [m]' if file in skybrush_files else 'pz'], 
                                color=color, 
                                s=20 if file in skybrush_files else 5, 
                                alpha=0.5)

    # Set the title and axis labels
    ax_all.set_title('Drone Paths for All Drones')
    ax_all.set_xlabel('North (m)')
    ax_all.set_ylabel('East (m)')
    ax_all.set_zlabel('Height (m)')

    # Add a legend
    ax_all.legend([(skybrush_points, skybrush_path), (processed_points, processed_path)],
                  ['Raw setpoints', 'Smoothed path'],
                  handler_map={tuple: HandlerTuple(ndivide=None)})

    # Save the plot as an image
    plt.savefig('shapes/swarm/plots/all_drones.png')

    # Show the plot
    if show_plots:
        plt.show()
