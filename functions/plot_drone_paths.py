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
    Extract digits from 'Drone10.csv' -> '10'
    """
    return ''.join(filter(str.isdigit, filename))

def compute_plot_limits(data_list: List[pd.DataFrame]) -> Tuple[float, float, float, float, float, float]:
    """
    Determine a uniform bounding box for all drones so we can 
    keep the same scale on the combined plot.
    """
    all_east = pd.concat([df['py'] for df in data_list])
    all_north = pd.concat([df['px'] for df in data_list])
    # Use negative pz as altitude
    all_altitude = pd.concat([-df['pz'] for df in data_list])

    max_range = np.array([
        all_east.max() - all_east.min(),
        all_north.max() - all_north.min(),
        all_altitude.max() - all_altitude.min()
    ]).max() / 2.0

    mid_east = (all_east.max() + all_east.min()) * 0.5
    mid_north = (all_north.max() + all_north.min()) * 0.5
    mid_alt = (all_altitude.max() + all_altitude.min()) * 0.5

    return (
        mid_east - max_range, mid_east + max_range,
        mid_north - max_range, mid_north + max_range,
        0, mid_alt + max_range
    )

def plot_drone_paths(base_dir: str, show_plots: bool = False, high_quality: bool = True):
    """
    Generate both individual and combined 3D path plots for each drone.

    By default, checks if sim_mode is True or False:
      - True -> uses shapes_sitl/swarm/processed, shapes_sitl/swarm/plots
      - False -> uses shapes/swarm/processed, shapes/swarm/plots
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    if high_quality:
        setup_matplotlib_style()

    # Which folder to read from?
    base_folder = 'shapes_sitl' if Params.sim_mode else 'shapes'
    processed_dir = os.path.join(base_dir, base_folder, 'swarm', 'processed')
    plots_dir = os.path.join(base_dir, base_folder, 'swarm', 'plots')

    os.makedirs(plots_dir, exist_ok=True)

    processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]
    if not processed_files:
        logging.warning("[plot_drone_paths] No processed CSV files found to plot.")
        return

    num_drones = len(processed_files)
    colormap = plt.colormaps['viridis']
    color_indices = np.linspace(0, 1, num_drones)

    # For combined plot, gather data
    all_data = []
    color_map = {}

    for i, filename in enumerate(processed_files):
        color_map[filename] = colormap(color_indices[i])

    # Plot each drone individually
    for filename in processed_files:
        path = os.path.join(processed_dir, filename)
        df = pd.read_csv(path)
        all_data.append(df)

        fig = plt.figure(figsize=(14, 10))
        ax = fig.add_subplot(111, projection='3d')
        color = color_map[filename]
        drone_id = extract_drone_id(filename)

        east = df['py']
        north = df['px']
        alt = -df['pz']  # negative sign to match altitude

        ax.plot(east, north, alt, color=color, linewidth=3, alpha=0.8)
        ax.scatter(east.iloc[0], north.iloc[0], alt.iloc[0],
                   color=color, s=100, edgecolor='black')
        ax.text(east.iloc[0], north.iloc[0], alt.iloc[0],
                f"Drone {drone_id}", color=color, fontsize=12)

        ax.set_title(f"Drone Path: Drone {drone_id}", fontweight='bold')
        ax.set_xlabel("East (m)", fontweight='bold')
        ax.set_ylabel("North (m)", fontweight='bold')
        ax.set_zlabel("Altitude (m)", fontweight='bold')

        plt.tight_layout()
        out_path = os.path.join(plots_dir, f"drone_{drone_id}_path.png")
        plt.savefig(out_path, dpi=300)

        if show_plots:
            plt.show()
        plt.close(fig)

    # Combined 3D plot
    if all_data:
        fig_c = plt.figure(figsize=(16, 12))
        ax_c = fig_c.add_subplot(111, projection='3d')

        xlim_min, xlim_max, ylim_min, ylim_max, zlim_min, zlim_max = compute_plot_limits(all_data)
        ax_c.set_xlim(xlim_min, xlim_max)
        ax_c.set_ylim(ylim_min, ylim_max)
        ax_c.set_zlim(zlim_min, zlim_max)

        for filename in processed_files:
            path = os.path.join(processed_dir, filename)
            df = pd.read_csv(path)
            color = color_map[filename]
            drone_id = extract_drone_id(filename)

            east = df['py']
            north = df['px']
            alt = -df['pz']

            ax_c.plot(east, north, alt, color=color, linewidth=2, label=f"Drone {drone_id}")
            ax_c.scatter(east.iloc[0], north.iloc[0], alt.iloc[0],
                         color=color, s=50)

        ax_c.set_title("Combined Drone Paths", fontweight='bold')
        ax_c.set_xlabel("East (m)", fontweight='bold')
        ax_c.set_ylabel("North (m)", fontweight='bold')
        ax_c.set_zlabel("Altitude (m)", fontweight='bold')
        ax_c.legend(loc='best', title='Drone IDs')

        plt.tight_layout()
        combined_path = os.path.join(plots_dir, "combined_drone_paths.png")
        plt.savefig(combined_path, dpi=300)

        if show_plots:
            plt.show()
        plt.close(fig_c)

    logging.info("[plot_drone_paths] Finished plotting all drone paths.")

if __name__ == "__main__":
    # Example usage
    base_test_dir = os.getcwd()
    plot_drone_paths(base_test_dir, show_plots=False)
