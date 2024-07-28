#functions/plot_drone_paths.py
import logging
import os
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
from matplotlib.legend_handler import HandlerTuple

def plot_drone_paths(base_dir, show_plots=True):
    skybrush_dir = os.path.join(base_dir, 'shapes/swarm/skybrush')
    processed_dir = os.path.join(base_dir, 'shapes/swarm/processed')
    plots_dir = os.path.join(base_dir, 'shapes/swarm/plots')

    # Ensure plot directory exists
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
        ax.plot(skybrush_data['x [m]'], skybrush_data['y [m]'], skybrush_data['z [m]'], color=color, alpha=0.2)
        ax.scatter(skybrush_data['x [m]'], skybrush_data['y [m]'], skybrush_data['z [m]'], color=color, s=20)
        
        if file in processed_files:
            processed_data = pd.read_csv(os.path.join(processed_dir, file))
            ax.plot(processed_data['px'], processed_data['py'], processed_data['pz'], color=color)
            ax.scatter(processed_data['px'], processed_data['py'], processed_data['pz'], color=color, s=5, alpha=0.2)

        ax.set_title('Drone Paths for ' + file.replace('.csv', ''))
        ax.set_xlabel('North (m)')
        ax.set_ylabel('East (m)')
        ax.set_zlabel('Height (m)')
        ax.legend(['Raw setpoints', 'Smoothed path'], loc='best')
        
        plt.savefig(os.path.join(plots_dir, file.split('.')[0] + '.png'))
        if show_plots:
            plt.show()
        plt.close(fig)

    logging.info("All individual and combined plots are generated.")
