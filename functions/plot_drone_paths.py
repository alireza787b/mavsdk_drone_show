# functions/plot_drone_paths.py
import logging
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from typing import List, Tuple
from src.params import Params

def setup_matplotlib_style():
    """
    Configure global Matplotlib styling for professional visualizations.
    """
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Liberation Sans', 'DejaVu Sans']  # Fallback fonts
    plt.rcParams.update({
        'axes.facecolor': 'white',
        'figure.facecolor': 'white',
        'font.size': 12,
        'axes.titlesize': 14,
        'axes.labelsize': 12,
        'legend.fontsize': 10,
        'figure.dpi': 300
    })

def extract_drone_id(filename: str) -> str:
    """
    Extract numerical drone ID from a filename such as Drone1.csv -> '1'.
    
    Args:
        filename (str): Input filename
    
    Returns:
        str: Extracted digits as string
    """
    return ''.join(filter(str.isdigit, filename))

def compute_plot_limits(data_list: List[pd.DataFrame]) -> Tuple[float, float, float, float, float, float]:
    """
    Compute consistent plot limits for 3D visualization across multiple drones.
    
    Args:
        data_list (List[pd.DataFrame]): List of drone trajectory DataFrames
    
    Returns:
        (east_min, east_max, north_min, north_max, altitude_min, altitude_max)
    """
    all_east = pd.concat([df['py'] for df in data_list])
    all_north = pd.concat([df['px'] for df in data_list])
    all_altitude = pd.concat([-df['pz'] for df in data_list])

    max_range = np.array([
        all_east.max() - all_east.min(),
        all_north.max() - all_north.min(),
        all_altitude.max() - all_altitude.min()
    ]).max() / 2.0

    mid_east = (all_east.max() + all_east.min()) * 0.5
    mid_north = (all_north.max() + all_north.min()) * 0.5
    mid_altitude = (all_altitude.max() + all_altitude.min()) * 0.5

    return (
        mid_east - max_range, mid_east + max_range,
        mid_north - max_range, mid_north + max_range,
        0, mid_altitude + max_range
    )

def plot_drone_paths(base_dir: str, show_plots: bool = False, high_quality: bool = True):
    """
    Advanced drone path visualization with enhanced styling and analysis.

    Dynamically detects SITL vs. real mode from Params, so it reads from:
      - shapes_sitl/swarm/processed or
      - shapes/swarm/processed

    and saves plots to:
      - shapes_sitl/swarm/plots or
      - shapes/swarm/plots

    Args:
        base_dir (str): Base directory for swarm data
        show_plots (bool): Display plots interactively if True
        high_quality (bool): Enable high-quality rendering if True
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    if high_quality:
        setup_matplotlib_style()

    # Decide which folder to use based on SITL vs. real
    base_folder = 'shapes_sitl' if Params.sim_mode else 'shapes'
    processed_dir = os.path.join(base_dir, base_folder, 'swarm', 'processed')
    plots_dir = os.path.join(base_dir, base_folder, 'swarm', 'plots')
    os.makedirs(plots_dir, exist_ok=True)

    processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]
    if not processed_files:
        logging.warning("No processed CSV files found in the specified directory.")
        return

    num_drones = len(processed_files)
    colormap = plt.colormaps['viridis']
    color_indices = np.linspace(0, 1, num_drones)

    # Prepare data for combined plotting
    drone_data = []
    color_dict = {file: colormap(color_indices[i]) for i, file in enumerate(processed_files)}

    # Plot each drone path individually
    for file in processed_files:
        data = pd.read_csv(os.path.join(processed_dir, file))
        drone_data.append(data)
        
        fig = plt.figure(figsize=(14, 10))
        ax = fig.add_subplot(111, projection='3d')
        
        color = color_dict[file]
        drone_id = extract_drone_id(file)
        
        east = data['py']
        north = data['px']
        altitude = -data['pz']
        
        ax.plot(east, north, altitude, color=color, linewidth=3, alpha=0.8)
        ax.scatter(east.iloc[0], north.iloc[0], altitude.iloc[0], 
                   color=color, s=100, edgecolor='black')
        
        ax.text(east.iloc[0], north.iloc[0], altitude.iloc[0], 
                f' Drone {drone_id}', color=color, fontsize=12)
        
        ax.set_title(f'Drone Path: Drone {drone_id}', fontweight='bold')
        ax.set_xlabel('East (m)', fontweight='bold')
        ax.set_ylabel('North (m)', fontweight='bold')
        ax.set_zlabel('Altitude (m)', fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(os.path.join(plots_dir, f'drone_{drone_id}_path.png'), dpi=300)
        
        if show_plots:
            plt.show()
        plt.close(fig)

    # Create combined 3D plot
    fig_combined = plt.figure(figsize=(16, 12))
    ax_combined = fig_combined.add_subplot(111, projection='3d')

    # Compute uniform axis limits
    plot_limits = compute_plot_limits(drone_data)
    ax_combined.set_xlim(plot_limits[0], plot_limits[1])
    ax_combined.set_ylim(plot_limits[2], plot_limits[3])
    ax_combined.set_zlim(plot_limits[4], plot_limits[5])

    for file in processed_files:
        data = pd.read_csv(os.path.join(processed_dir, file))
        color = color_dict[file]
        drone_id = extract_drone_id(file)

        east = data['py']
        north = data['px']
        altitude = -data['pz']

        ax_combined.plot(east, north, altitude, color=color, linewidth=2, label=f'Drone {drone_id}')
        ax_combined.scatter(east.iloc[0], north.iloc[0], altitude.iloc[0], 
                            color=color, s=50)

    ax_combined.set_title('Combined Drone Paths', fontweight='bold')
    ax_combined.set_xlabel('East (m)', fontweight='bold')
    ax_combined.set_ylabel('North (m)', fontweight='bold')
    ax_combined.set_zlabel('Altitude (m)', fontweight='bold')
    
    ax_combined.legend(loc='best', title='Drone IDs')
    plt.tight_layout()
    
    plt.savefig(os.path.join(plots_dir, 'combined_drone_paths.png'), dpi=300)
    if show_plots:
        plt.show()

    logging.info("Drone path visualization complete.")

if __name__ == "__main__":
    """
    Example usage. Typically called by process_formation.py,
    but you can run it directly for a quick test.
    """
    from src.params import Params

    base_dir = "/root/mavsdk_drone_show"
    plot_drone_paths(base_dir, show_plots=False)
