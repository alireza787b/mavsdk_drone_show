from matplotlib import pyplot as plt
import numpy as np
import pandas as pd
from functions.shape_functions import rotate
import matplotlib.cm as cm

def plot_points(points, viewer_position):
    """
    Plot the generated drone trajectories in 3D and the viewer's position.

    Args:
        points (pd.DataFrame): Drone positions with optional 'drone_id' column.
        viewer_position (tuple): Viewer's position.
    """
    fig = plt.figure(figsize=(12, 9))
    ax = fig.add_subplot(111, projection='3d')

    # Check if 'drone_id' is in points DataFrame to plot trajectories
    if 'drone_id' in points.columns:
        drones = points['drone_id'].unique()
        colors = cm.get_cmap('tab20', len(drones))

        for idx, drone_id in enumerate(drones):
            drone_points = points[points['drone_id'] == drone_id]
            ax.plot(
                drone_points['px'],
                drone_points['py'],
                -drone_points['pz'],
                label=f'Drone {drone_id}',
                color=colors(idx),
                linewidth=2
            )
    else:
        # Scatter plot for positions if 'drone_id' is not available
        ax.scatter(
            points['px'],
            points['py'],
            -points['pz'],
            c='blue',
            marker='o',
            s=50,
            alpha=0.7,
            label='Drone Positions'
        )

    # Plot viewer's position
    ax.scatter(
        *viewer_position,
        color='red',
        s=100,
        marker='^',
        label='Viewer Position'
    )

    ax.set_xlabel('X (North)')
    ax.set_ylabel('Y (East)')
    ax.set_zlabel('Z (Altitude)')
    ax.set_title('3D Drone Trajectories', fontsize=16)

    # Add legend and grid
    ax.legend()
    ax.grid(True)

    # Adjust the aspect ratio for better visualization
    max_range = np.array([
        points['px'].max() - points['px'].min(),
        points['py'].max() - points['py'].min(),
        points['pz'].max() - points['pz'].min()
    ]).max() / 2.0

    mid_x = (points['px'].max() + points['px'].min()) * 0.5
    mid_y = (points['py'].max() + points['py'].min()) * 0.5
    mid_z = (-points['pz'].max() + -points['pz'].min()) * 0.5

    ax.set_xlim(mid_x - max_range, mid_x + max_range)
    ax.set_ylim(mid_y - max_range, mid_y + max_range)
    ax.set_zlim(mid_z - max_range, mid_z + max_range)

    # Save and show the plot
    plt.savefig('shapes/static_shapes/active/3d_plot.png', dpi=80, bbox_inches='tight', optimize=True)
    plt.show()

    return fig

def plot_2d_observer(points, heading, plane):
    """
    Plot the generated drone trajectories in 2D from the observer's POV.

    Args:
        points (pd.DataFrame): Drone positions with optional 'drone_id' column.
        heading (float): Heading angle in degrees.
        plane (str): 'vertical' or 'horizontal'.
    """
    heading_rad = -np.radians(heading)
    
    # Rotate points for 2D observer view
    rotated_coords = rotate(points[['px', 'py', 'pz']].to_numpy(), heading_rad)
    points_rotated = pd.DataFrame(rotated_coords, columns=['px', 'py', 'pz'])
    
    # Include 'drone_id' if present
    if 'drone_id' in points.columns:
        points_rotated['drone_id'] = points['drone_id']
    
    fig, ax = plt.subplots(figsize=(12, 9))

    if plane == 'vertical':
        # 2D plot for vertical plane (XZ)
        xlabel = 'X (North)'
        ylabel = 'Z (Altitude)'
        x_data = points_rotated['px']
        y_data = -points_rotated['pz']  # Negate Z for visual intuition
    elif plane == 'horizontal':
        # 2D plot for horizontal plane (XY)
        xlabel = 'X (North)'
        ylabel = 'Y (East)'
        x_data = points_rotated['px']
        y_data = points_rotated['py']
    else:
        raise ValueError("Plane must be 'vertical' or 'horizontal'.")

    # Plot trajectories or positions
    if 'drone_id' in points_rotated.columns:
        drones = points_rotated['drone_id'].unique()
        colors = cm.get_cmap('tab20', len(drones))
        for idx, drone_id in enumerate(drones):
            drone_points = points_rotated[points_rotated['drone_id'] == drone_id]
            ax.plot(
                drone_points['px'],
                drone_points['py'] if plane == 'horizontal' else -drone_points['pz'],
                label=f'Drone {drone_id}',
                color=colors(idx),
                linewidth=2
            )
    else:
        scatter = ax.scatter(
            x_data,
            y_data,
            c=-points_rotated['pz'],
            cmap='viridis',
            s=50,
            alpha=0.7
        )
        plt.colorbar(scatter, label='Depth')

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(f"2D View (Observer at (0,0,0) facing heading {heading}°)", fontsize=16)

    # Add legend and grid
    if 'drone_id' in points_rotated.columns:
        ax.legend()
    ax.grid(True)

    # Save and show the plot
    plt.savefig('shapes/static_shapes/active/2d_observer.png', dpi=80, bbox_inches='tight', optimize=True)
    plt.show()

    return fig
