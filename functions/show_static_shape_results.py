import pandas as pd
from scipy.spatial import distance

from functions.shape_functions import closest_drones
from functions.shape_plots import plot_2d_observer, plot_points

def show_static_shape_results(points, params):
    """
    Show the results of the static shape.

    Args:
        points (pd.DataFrame): Drone positions.
        params (object): Object that contains parameters of the viewer's position, heading angle, and plane.
    """
    # Add 'drone_id' column
    points = points.assign(drone_id=range(0, len(points)))
    points = points[['drone_id', 'px', 'py', 'pz']]  # Reordering columns

    # Display results
    pd.set_option('display.float_format', '{:.2f}'.format)
    print(points.to_string(index=False))

    points.to_csv('shapes/static_shapes/active/drone_positions.csv', index=False)

    # Plot the generated drone positions in 3D
    fig_3d = plot_points(points, params.viewer_position)

    # Plot the generated drone positions in 2D from the observer's POV
    fig_2d = plot_2d_observer(points, params.heading, params.plane)

    # Find the pair of drones that are closest to each other
    closest_pair = closest_drones(points[['px', 'py', 'pz']].to_numpy())
    closest_distance = distance.euclidean(points.iloc[closest_pair[0]], points.iloc[closest_pair[1]])
    print(f"The closest drones are {closest_pair[0]} and {closest_pair[1]} with a distance of {closest_distance:.2f} m.")



