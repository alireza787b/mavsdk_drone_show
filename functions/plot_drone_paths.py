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
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Liberation Sans']
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
    Extract numerical drone ID from filenames like 'Drone1.csv' -> '1'.
    """
    return ''.join(filter(str.isdigit, filename))

def compute_plot_limits(data_list: List[pd.DataFrame]) -> Tuple[float, float, float, float, float, float]:
    """
    Determine consistent 3D plot bounds in an N–E–Up system:
      n=px, e=-py, up=-pz
    Returns (n_min,n_max, e_min,e_max, u_min,u_max).
    """
    all_n, all_e, all_up = [], [], []
    for df in data_list:
        n = df['px']
        e = -df['py']
        u = -df['pz']
        all_n.append(n)
        all_e.append(e)
        all_up.append(u)

    all_n  = pd.concat(all_n)
    all_e  = pd.concat(all_e)
    all_up = pd.concat(all_up)

    max_range = np.array([
        all_n.max() - all_n.min(),
        all_e.max() - all_e.min(),
        all_up.max() - all_up.min()
    ]).max() / 2.0

    mid_n  = (all_n.max()  + all_n.min())  * 0.5
    mid_e  = (all_e.max()  + all_e.min())  * 0.5
    mid_up = (all_up.max() + all_up.min()) * 0.5

    return (
        mid_n - max_range,  mid_n + max_range,
        mid_e - max_range,  mid_e + max_range,
        mid_up - max_range, mid_up + max_range
    )


def plot_drone_paths(base_dir: str, show_plots: bool = False, high_quality: bool = True):
    """
    3D path visualization in a North–East–Up frame (axes labeled with <-> to indicate opposite directions).
    By default, we read from SITL or real:
      shapes_sitl/swarm/processed -> shapes_sitl/swarm/plots
      shapes/swarm/processed      -> shapes/swarm/plots

    Steps:
      1) Draw single-drone plots with axis named 'North <-> South (m)' etc.
         - Title includes "Drone X"
         - No label on the drone's start point (less clutter).
      2) Draw a combined plot with a legend "Drone X" for each path,
         but label the launch point with "(X)" offset so it doesn't collide.
      3) Use a vantage angle that orients North 'up' and East 'right'.
    """
    logging.info("[plot_drone_paths] Generating 3D path visuals...")

    if high_quality:
        setup_matplotlib_style()

    # SITL or real
    base_folder  = 'shapes_sitl' if Params.sim_mode else 'shapes'
    processed_dir= os.path.join(base_dir, base_folder, 'swarm', 'processed')
    plots_dir    = os.path.join(base_dir, base_folder, 'swarm', 'plots')
    os.makedirs(plots_dir, exist_ok=True)

    processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]
    if not processed_files:
        logging.warning("[plot_drone_paths] No processed CSV files found.")
        return

    # Color mapping
    num_drones    = len(processed_files)
    colormap      = plt.colormaps.get('viridis', plt.cm.viridis)
    color_indices = np.linspace(0, 1, num_drones)

    # For combined plot bounding
    drone_data = []
    color_dict = {file: colormap(color_indices[i]) for i, file in enumerate(processed_files)}

    ###################################################
    # Single-Drone Plots
    ###################################################
    for file in processed_files:
        df_path = os.path.join(processed_dir, file)
        df = pd.read_csv(df_path)
        drone_data.append(df)

        # Convert px->North, py->West => East, pz->Down => Up
        north = df['px']
        east  = -df['py']
        up    = -df['pz']

        fig = plt.figure(figsize=(14, 10))
        ax  = fig.add_subplot(111, projection='3d')

        drone_id = extract_drone_id(file)
        color    = color_dict[file]

        # Plot path
        ax.plot(north, east, up, color=color, linewidth=3, alpha=0.85)
        # Mark the starting point - no text label here
        ax.scatter(north.iloc[0], east.iloc[0], up.iloc[0],
                   color=color, s=100, edgecolor='black')

        # Axes with "N <-> S", "E <-> W", "U <-> D"
        ax.set_xlabel('← South | North → (m)', fontweight='bold')
        ax.set_ylabel('← West | East → (m)',   fontweight='bold')
        ax.set_zlabel('← Down | Up → (m)',     fontweight='bold')

        # Title referencing the drone
        ax.set_title(f"Drone {drone_id} Path (N–E–Up)", fontweight='bold')

        # Rotate view so north is "up"
        ax.view_init(elev=30, azim=-60)

        plt.tight_layout()
        single_out = os.path.join(plots_dir, f'drone_{drone_id}_path.png')
        plt.savefig(single_out, dpi=300)

        if show_plots:
            plt.show()
        plt.close(fig)

    ###################################################
    # Combined Plot
    ###################################################
    fig_c = plt.figure(figsize=(16, 12))
    ax_c  = fig_c.add_subplot(111, projection='3d')

    # Uniform bounding
    n_min, n_max, e_min, e_max, u_min, u_max = compute_plot_limits(drone_data)
    ax_c.set_xlim(n_min, n_max)
    ax_c.set_ylim(e_min, e_max)
    ax_c.set_zlim(u_min, u_max)

    # We'll use some fraction of the bounding box for an offset
    offset_n = 0.02 * (n_max - n_min)  # 2% of the n-range
    offset_e = 0.02 * (e_max - e_min)  # 2% of the e-range

    for file in processed_files:
        df      = pd.read_csv(os.path.join(processed_dir, file))
        color   = color_dict[file]
        drone_id= extract_drone_id(file)

        north = df['px']
        east  = -df['py']
        up    = -df['pz']

        # Plot the path
        ax_c.plot(north, east, up, color=color, linewidth=2, label=f"Drone {drone_id}")
        # Mark & label launch with "(drone_id)"
        ln, le, lu = north.iloc[0], east.iloc[0], up.iloc[0]
        ax_c.scatter(ln, le, lu, color=color, s=50)

        # Position the text with slight offset so it doesn't collide
        ax_c.text(ln + offset_n, le + offset_e, lu,
                  f"({drone_id})",
                  color=color, fontsize=10)

    # Axis labels with <->
    ax_c.set_xlabel('← South | North → (m)', fontweight='bold')
    ax_c.set_ylabel('← West | East → (m)',   fontweight='bold')
    ax_c.set_zlabel('← Down | Up → (m)',     fontweight='bold')

    ax_c.set_title('Combined Drone Paths (N–E–Up)', fontweight='bold')
    ax_c.legend(loc='best', title='Drone IDs')

    # Similar vantage angle
    ax_c.view_init(elev=30, azim=-60)

    plt.tight_layout()
    combined_out = os.path.join(plots_dir, 'combined_drone_paths.png')
    plt.savefig(combined_out, dpi=300)

    if show_plots:
        plt.show()
    plt.close(fig_c)

    logging.info("[plot_drone_paths] All plots generated with user-friendly orientation and labeling.")
