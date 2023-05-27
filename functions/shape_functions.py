

from scipy.spatial import distance

import numpy as np


def rotate(points, heading):
    """
    Rotate points around the z-axis by the 'heading' angle.

    Args:
        points (np.ndarray): Points to rotate.
        heading (float): Heading angle in radians.

    Returns:
        np.ndarray: Rotated points.
    """
    rotation_matrix = np.array([
        [np.cos(heading), -np.sin(heading), 0],
        [np.sin(heading), np.cos(heading), 0],
        [0, 0, 1]
    ])
    # Dot product to rotate the points
    return np.dot(points, rotation_matrix)






def closest_drones(points):
    """
    Find the pair of drones that are closest to each other.

    Args:
        points (pd.DataFrame): Drone positions.

    Returns:
        tuple: Indices of the drones that are closest to each other.
    """
    # Compute the pairwise distances
    dists = distance.squareform(distance.pdist(points))
    # Set the diagonal to infinity to exclude self-pairs
    np.fill_diagonal(dists, np.inf)
    # Find the minimum distance
    closest_pair_idx = np.unravel_index(np.argmin(dists), dists.shape)
    return closest_pair_idx

def check_collision(points,treshhold=0.5):
    """
    Checks for collisions in drone positions and slightly alters position if found.

    Args:
        points (pd.DataFrame): Drone positions.

    Returns:
        pd.DataFrame: Drone positions after collision checks.
    """
    # Loop through the points and check for collisions
    for i in range(len(points)):
        for j in range(i+1, len(points)):
            # If a collision is detected
            if points.iloc[i].equals(points.iloc[j]):
                print(f"Collision Detected between drone {i} and {j}. Correcting to add {treshhold}")
                # Slightly alter the position of the second drone
                points.at[j, 'px'] += treshhold
                points.at[j, 'py'] += treshhold
                points.at[j, 'pz'] -= treshhold

    return points