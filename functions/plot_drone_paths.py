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
    return ''.join(filter(str.isdigit, filename))

def compute_plot_limits(data_list: List[pd.DataFrame]) -> Tuple[float, float, float, float, float, float]:
    """
    Determine uniform 3D plot bounds for N–E–Up:
      n = px, e = -py, up = -pz
    """
    all_n, all_e, all_up = [], [], []
    for df in data_list:
        n = df['px']
        e = -df['py']
        up= -df['pz']
        all_n.append(n)
        all_e.append(e)
        all_up.append(up)
    all_n = pd.concat(all_n)
    all_e = pd.concat(all_e)
    all_up= pd.concat(all_up)

    max_range = np.array([
        all_n.max() - all_n.min(),
        all_e.max() - all_e.min(),
        all_up.max() - all_up.min()
    ]).max() / 2.0

    mid_n  = (all_n.max() + all_n.min()) * 0.5
    mid_e  = (all_e.max() + all_e.min()) * 0.5
    mid_up = (all_up.max() + all_up.min()) * 0.5

    return (mid_n - max_range, mid_n + max_range,
            mid_e - max_range, mid_e + max_range,
            mid_up - max_range, mid_up + max_range)

def plot_drone_paths(base_dir: str, show_plots: bool = False, high_quality: bool = True):
    """
    3D path visualization in N–E–Up, for SITL or real mode.

    We'll rely on the main script's logging config.
    """
    logging.info("[plot_drone_paths] Generating 3D path visuals...")

    if high_quality:
        setup_matplotlib_style()

    base_folder = 'shapes_sitl' if Params.sim_mode else 'shapes'
    processed_dir = os.path.join(base_dir, base_folder, 'swarm', 'processed')
    plots_dir    = os.path.join(base_dir, base_folder, 'swarm', 'plots')
    os.makedirs(plots_dir, exist_ok=True)

    processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]
    if not processed_files:
        logging.warning("[plot_drone_paths] No processed CSV files found.")
        return

    num_drones = len(processed_files)
    colormap = plt.colormaps.get('viridis', plt.cm.viridis)
    color_indices = np.linspace(0, 1, num_drones)

    # For combined plot
    drone_data = []
    color_dict = {file: colormap(color_indices[i]) for i, file in enumerate(processed_files)}

    # Individual plots
    for file in processed_files:
        df_path = os.path.join(processed_dir, file)
        df = pd.read_csv(df_path)
        drone_data.append(df)

        # N–E–Up
        north = df['px']
        east  = -df['py']
        up    = -df['pz']

        fig = plt.figure(figsize=(14, 10))
        ax  = fig.add_subplot(111, projection='3d')

        color    = color_dict[file]
        drone_id = extract_drone_id(file)

        ax.plot(north, east, up, color=color, linewidth=3, alpha=0.8)
        ax.scatter(north.iloc[0], east.iloc[0], up.iloc[0],
                   color=color, s=100, edgecolor='black')
        ax.text(north.iloc[0], east.iloc[0], up.iloc[0],
                f"Drone {drone_id}", color=color, fontsize=12)

        ax.set_title(f"Drone Path: {drone_id}", fontweight='bold')
        ax.set_xlabel('North (m)', fontweight='bold')
        ax.set_ylabel('East (m)',  fontweight='bold')
        ax.set_zlabel('Up (m)',    fontweight='bold')

        plt.tight_layout()
        out_filename = os.path.join(plots_dir, f'drone_{drone_id}_path.png')
        plt.savefig(out_filename, dpi=300)
        if show_plots:
            plt.show()
        plt.close(fig)

    # Combined plot
    fig_c = plt.figure(figsize=(16, 12))
    ax_c = fig_c.add_subplot(111, projection='3d')

    n_min, n_max, e_min, e_max, u_min, u_max = compute_plot_limits(drone_data)
    ax_c.set_xlim(n_min, n_max)
    ax_c.set_ylim(e_min, e_max)
    ax_c.set_zlim(u_min, u_max)

    for file in processed_files:
        df_path = os.path.join(processed_dir, file)
        df = pd.read_csv(df_path)

        color = color_dict[file]
        drone_id = extract_drone_id(file)

        north = df['px']
        east  = -df['py']
        up    = -df['pz']

        ax_c.plot(north, east, up, color=color, linewidth=2, label=f"Drone {drone_id}")
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

    logging.info("[plot_drone_paths] Done generating 3D path visuals.")
