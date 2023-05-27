from matplotlib import pyplot as plt
import numpy as np
import pandas as pd

from functions.shape_functions import rotate


def plot_points(points, viewer_position):
    """
    Plot the generated drone positions in 3D and the viewer's position.

    Args:
        points (pd.DataFrame): Drone positions.
        viewer_position (tuple): Viewer's position.
    """
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')

    # Scatter plot for 3D positions of the drones
    ax.scatter(points['px'], points['py'], -points['pz'])  # negating 'pz' to make the plot visually intuitive

    # Plot viewer's position
    ax.scatter(*viewer_position, color='red', s=100)  # viewer's position marked as a red circle

    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')

    # Save the plot
    plt.savefig('shapes/static_shapes/active/3d_plot.png')
    # Show the plot
    plt.show()

    return fig

def plot_2d_observer(points, heading, plane):
    """
    Plot the generated drone positions in 2D from the observer's POV.

    Args:
        points (pd.DataFrame): Drone positions.
        heading (float): Heading angle in degrees.
        plane (str): 'vertical' or 'horizontal'.
    """
    heading_rad = -np.radians(heading)
    
    # Rotate points for 2D observer view
    points_rotated = rotate(points[['px', 'py', 'pz']].to_numpy(), heading_rad)  # Only use px, py, pz for rotation
    points_rotated = pd.DataFrame(points_rotated, columns=['px', 'py', 'pz'])
    
    fig = plt.figure()
    if plane == 'vertical':
        # 2D plot for vertical plane (XZ)
        plt.scatter(points_rotated['px'], -points_rotated['pz'], c=points_rotated['py'], cmap='viridis')
    elif plane == 'horizontal':
        # 2D plot for horizontal plane (XY)
        plt.scatter(points_rotated['px'], points_rotated['py'], c=-points_rotated['pz'], cmap='viridis')

    plt.xlabel('X')
    plt.ylabel('Y' if plane == 'horizontal' else 'Z')
    plt.title('2D View (Observer at (0,0,0) facing heading {})'.format(np.rad2deg(heading_rad)))
    plt.colorbar(label='Depth')  # changed 'Altitude' to 'Depth'
    
    # Save the plot
    plt.savefig('shapes/static_shapes/active/2d_observer.png')
    # Show the plot
    plt.show()

    return fig