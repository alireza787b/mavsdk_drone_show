import numpy as np
import pandas as pd
from .shapeParameters import *
from .shape_functions import rotate

def generate_circle(params: CircleParameters):
    """
    Generate positions of drones to form a circle in the sky.

    Args:
        params (CircleParameters): Parameters defining the circle.

    Returns:
        pandas.DataFrame: Drone positions in a DataFrame with columns ['px', 'py', 'pz'].
    """
    assert isinstance(params, CircleParameters), "params must be an instance of CircleParameters"
    
    # Convert degrees to radians for the heading
    heading_rad = np.radians(params.heading)
    
    # Define angles for the drones positions around the circle
    angles = np.linspace(0, 2*np.pi, params.num_drones, endpoint=False)
    
    if params.plane == 'vertical':
        # Create circle in xz plane 
        x = params.radius * np.sin(angles)
        y = np.array([i*params.offset for i in range(params.num_drones)], dtype=float)
        z = -1*(params.radius * np.cos(angles) + params.base_altitude)
    elif params.plane == 'horizontal':
        # Create circle in xy plane
        x = params.radius * np.cos(angles)
        y = params.radius * np.sin(angles)
        z = params.base_altitude + np.array([i*params.offset for i in range(params.num_drones)], dtype=float)
    else:
        raise ValueError("Invalid plane. Plane must be either 'vertical' or 'horizontal'.")
        
    # Shift the circle so that its center is at a given 'distance' along the 'heading'
    shift_x = params.distance * np.sin(heading_rad)
    shift_y = params.distance * np.cos(heading_rad)
    x += shift_x
    y += shift_y
    
    points = np.column_stack((x, y, z))
    
    # Rotate points around z-axis by the 'heading' angle
    points = rotate(points, heading_rad)
    
    return pd.DataFrame(points, columns=['px', 'py', 'pz'])