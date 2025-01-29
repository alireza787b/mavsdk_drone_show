import logging
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from typing import List, Tuple, Optional
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
    Extract numerical drone ID from 'Drone1.csv' -> '1'
    """
    return ''.join(filter(str.isdigit, filename))

def compute_plot_limits(data_list: List[pd.DataFrame]) -> Tuple[float, float, float, float, float, float]:
    """
    Compute consistent plot limits for 3D visualization across multiple drones.
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

def plot_drone_paths(
    base_dir: str, 
    show_plots: bool = False, 
    high_quality: bool = True,
    override_processed: Optional[str] = None,
    override_plots: Optional[str] = None
):
    """
    Advanced drone path visualization with enhanced styling and analysis.
    
    By default, reads/writes from SITL or real:
      - SITL -> shapes_sitl/swarm/processed + shapes_sitl/swarm/plots
      - Real -> shapes/swarm/processed + shapes/swarm/plots
    
    If override_processed or override_plots are specified, 
    those folders are used instead (for staging in a temp directory).
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    if high_quality:
        setup_matplotlib_style()

    # Figure out processed/plots directories
    if override_processed and override_plots:
        processed_dir = override_processed
        plots_dir = override_plots
    else:
        # Fallback to SITL or real
        base_folder = 'shapes_sitl' if Params.sim_mode else 'shapes'
        processed_dir = os.path.join(base_dir, base_folder, 'swarm', 'processed')
        plots_dir = os.path.join(base_dir, base_folder, 'swarm', 'plots')

    os.makedirs(plots_dir, exist_ok=True)

    processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]
    if not processed_files:
        logging.warning("[plot_drone_paths] No processed CSV files found.")
        return

    num_drones = len(processed_files)
    colormap = plt.colormaps['viridis']
    color_indices = np.linspace(0, 1, num_drones)

    # Prepare data for combined plotting
    drone_data = []
    color_dict = {
        file: colormap(color_indices[i]) for i, file in enumerate(processed_files)
    }

    # Plot each drone separately
    for file in processed_files:
        path = os.path.join(processed_dir, file)
        df = pd.read_csv(path)
        drone_data.append(df)

        fig = plt.figure(figsize=(14, 10))
        ax = fig.add_subplot(111, projection='3d')

        color = color_dict[file]
        drone_id = extract_drone_id(file)

        east = df['py']
        north = df['px']
        altitude = -df['pz']  # negative sign to match real altitude

        ax.plot(east, north, altitude, color=color, linewidth=3, alpha=0.8)
        ax.scatter(east.iloc[0], north.iloc[0], altitude.iloc[0],
                   color=color, s=100, edgecolor='black')

        ax.text(east.iloc[0], north.iloc[0], altitude.iloc[0],
                f" Drone {drone_id}", color=color, fontsize=12)

        ax.set_title(f'Drone Path: Drone {drone_id}', fontweight='bold')
        ax.set_xlabel('East (m)', fontweight='bold')
        ax.set_ylabel('North (m)', fontweight='bold')
        ax.set_zlabel('Altitude (m)', fontweight='bold')

        plt.tight_layout()
        out_file = os.path.join(plots_dir, f'drone_{drone_id}_path.png')
        plt.savefig(out_file, dpi=300)
        if show_plots:
            plt.show()
        plt.close(fig)

    # Combined 3D plot
    fig_c = plt.figure(figsize=(16, 12))
    ax_c = fig_c.add_subplot(111, projection='3d')

    plot_limits = compute_plot_limits(drone_data)
    ax_c.set_xlim(plot_limits[0], plot_limits[1])
    ax_c.set_ylim(plot_limits[2], plot_limits[3])
    ax_c.set_zlim(plot_limits[4], plot_limits[5])

    for file in processed_files:
        path = os.path.join(processed_dir, file)
        df = pd.read_csv(path)
        color = color_dict[file]
        drone_id = extract_drone_id(file)

        east = df['py']
        north = df['px']
        altitude = -df['pz']

        ax_c.plot(east, north, altitude, color=color, linewidth=2, label=f'Drone {drone_id}')
        ax_c.scatter(east.iloc[0], north.iloc[0], altitude.iloc[0],
                     color=color, s=50)

    ax_c.set_title('Combined Drone Paths', fontweight='bold')
    ax_c.set_xlabel('East (m)', fontweight='bold')
    ax_c.set_ylabel('North (m)', fontweight='bold')
    ax_c.set_zlabel('Altitude (m)', fontweight='bold')
    ax_c.legend(loc='best', title='Drone IDs')

    plt.tight_layout()
    out_combined = os.path.join(plots_dir, 'combined_drone_paths.png')
    plt.savefig(out_combined, dpi=300)
    if show_plots:
        plt.show()
    plt.close(fig_c)

    logging.info("[plot_drone_paths] Finished generating drone path plots.")
