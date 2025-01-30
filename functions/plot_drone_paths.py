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
    plt.rcParams['font.sans-serif'] = ['Liberation Sans', 'DejaVu Sans']
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
    Extract numerical drone ID from a filename like 'Drone1.csv' -> '1'.
    """
    return ''.join(filter(str.isdigit, filename))

def compute_plot_limits(data_list: List[pd.DataFrame]) -> Tuple[float, float, float, float, float, float]:
    """
    Compute consistent 3D plot limits in N–E–Up for multiple drones.
    Each DataFrame in data_list has columns:
      px -> 'north' in Blender sense
      py -> 'west'
      pz -> 'down' (already flipped from 'up')

    We want real N–E–Up:
      North = px
      East  = -py
      Up    = -pz

    Returns (n_min, n_max, e_min, e_max, u_min, u_max)
    used to scale the 3D axes uniformly.
    """
    all_north = []
    all_east  = []
    all_up    = []

    for df in data_list:
        n = df['px']
        e = -df['py']   # flip West -> East
        u = -df['pz']   # flip Down -> Up
        all_north.append(n)
        all_east.append(e)
        all_up.append(u)

    # Combine all into single Series
    all_north = pd.concat(all_north)
    all_east  = pd.concat(all_east)
    all_up    = pd.concat(all_up)

    # Determine a uniform max_range
    max_range = np.array([
        all_north.max() - all_north.min(),
        all_east.max()  - all_east.min(),
        all_up.max()    - all_up.min()
    ]).max() / 2.0

    mid_north = (all_north.max() + all_north.min()) * 0.5
    mid_east  = (all_east.max()  + all_east.min())  * 0.5
    mid_up    = (all_up.max()    + all_up.min())    * 0.5

    return (
        mid_north - max_range, mid_north + max_range,
        mid_east  - max_range, mid_east  + max_range,
        mid_up    - max_range, mid_up    + max_range
    )

def plot_drone_paths(base_dir: str, show_plots: bool = False, high_quality: bool = True):
    """
    Advanced drone path visualization in a standard North–East–Up frame.

    By default, it detects SITL vs. real mode from Params, reading:
      - shapes_sitl/swarm/processed or shapes/swarm/processed
    Then writes plots to:
      - shapes_sitl/swarm/plots or shapes/swarm/plots

    The pipeline CSV data columns are:
      px -> 'north' (Blender-based)
      py -> 'west'
      pz -> 'down' (inverted from 'up')
    We convert them to N–E–Up as:
      north = px
      east  = -py
      up    = -pz
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    if high_quality:
        setup_matplotlib_style()

    # SITL or real folder
    base_folder = 'shapes_sitl' if Params.sim_mode else 'shapes'
    processed_dir = os.path.join(base_dir, base_folder, 'swarm', 'processed')
    plots_dir    = os.path.join(base_dir, base_folder, 'swarm', 'plots')
    os.makedirs(plots_dir, exist_ok=True)

    processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]
    if not processed_files:
        logging.warning("[plot_drone_paths] No processed CSV files found in the directory.")
        return

    # Create colormap for the drones
    num_drones = len(processed_files)
    colormap   = plt.colormaps.get('viridis', plt.cm.viridis)
    color_indices = np.linspace(0, 1, num_drones)

    # Collect data for combined plot
    drone_data = []
    color_dict = {file: colormap(color_indices[i]) for i, file in enumerate(processed_files)}

    ###################################################
    # Individual Drone Plots
    ###################################################
    for file in processed_files:
        df_path = os.path.join(processed_dir, file)
        df = pd.read_csv(df_path)
        drone_data.append(df)

        # Convert to N–E–Up
        north = df['px']
        east  = -df['py']   # west -> east
        up    = -df['pz']   # down -> up

        # Create figure
        fig = plt.figure(figsize=(14, 10))
        ax = fig.add_subplot(111, projection='3d')

        color = color_dict[file]
        drone_id = extract_drone_id(file)

        # Plot trajectory
        ax.plot(north, east, up, color=color, linewidth=3, alpha=0.8)
        # Mark start
        ax.scatter(north.iloc[0], east.iloc[0], up.iloc[0],
                   color=color, s=100, edgecolor='black')

        # Label the starting position
        ax.text(north.iloc[0], east.iloc[0], up.iloc[0],
                f"Drone {drone_id}", color=color, fontsize=12)

        ax.set_title(f"Drone Path: {drone_id}", fontweight='bold')
        ax.set_xlabel('North (m)', fontweight='bold')
        ax.set_ylabel('East (m)',  fontweight='bold')
        ax.set_zlabel('Up (m)',    fontweight='bold')

        plt.tight_layout()

        # Save
        out_filename = os.path.join(plots_dir, f'drone_{drone_id}_path.png')
        plt.savefig(out_filename, dpi=300)

        if show_plots:
            plt.show()
        plt.close(fig)

    ###################################################
    # Combined Plot of All Drones
    ###################################################
    fig_c = plt.figure(figsize=(16, 12))
    ax_c = fig_c.add_subplot(111, projection='3d')

    # Compute consistent bounds across all drones
    n_min, n_max, e_min, e_max, u_min, u_max = compute_plot_limits(drone_data)
    ax_c.set_xlim(n_min, n_max)
    ax_c.set_ylim(e_min, e_max)
    ax_c.set_zlim(u_min, u_max)

    for file in processed_files:
        df_path = os.path.join(processed_dir, file)
        df = pd.read_csv(df_path)
        color = color_dict[file]
        drone_id = extract_drone_id(file)

        # N–E–Up again
        north = df['px']
        east  = -df['py']
        up    = -df['pz']

        ax_c.plot(north, east, up, color=color, linewidth=2, label=f"Drone {drone_id}")
        # Mark initial position
        ax_c.scatter(north.iloc[0], east.iloc[0], up.iloc[0], color=color, s=50)

    ax_c.set_title('Combined Drone Paths (N–E–Up)', fontweight='bold')
    ax_c.set_xlabel('North (m)', fontweight='bold')
    ax_c.set_ylabel('East (m)',  fontweight='bold')
    ax_c.set_zlabel('Up (m)',    fontweight='bold')
    ax_c.legend(loc='best', title='Drone IDs')

    plt.tight_layout()
    combined_out = os.path.join(plots_dir, 'combined_drone_paths.png')
    plt.savefig(combined_out, dpi=300)

    if show_plots:
        plt.show()
    plt.close(fig_c)

    logging.info("[plot_drone_paths] Drone path visualization in N–E–Up is complete.")

if __name__ == "__main__":
    # Example usage
    from src.params import Params
    base_test_dir = os.getcwd()
    plot_drone_paths(base_test_dir, show_plots=False)
