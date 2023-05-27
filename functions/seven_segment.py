import numpy as np
import pandas as pd
from .shapeParameters import *
from .shape_functions import rotate


def generate_seven_segment(params: SevenSegmentParameters):
    assert isinstance(params, SevenSegmentParameters), "params must be an instance of SevenSegmentParameters"

    # Calculate total length of all active segments
    total_length = 0
    for i in range(7):
        if params.SEGMENT_PATTERNS[params.digit][i]:
            total_length += (2 * params.segment_length) if i in [0, 3, 6] else params.segment_length

    # Generate the points for each segment
    segment_points = []
    for i in range(7):
        if params.SEGMENT_PATTERNS[params.digit][i]:
            # Distribute drones proportional to the length of the segment
            segment_length = (2 * params.segment_length) if i in [0, 3, 6] else params.segment_length
            drones_per_segment = round(params.num_drones * (segment_length / total_length))
            segment_points.append(generate_segment(i, drones_per_segment, params))

    # Concatenate the points for all segments
    points = np.concatenate(segment_points)

    # If we have more points than drones, reduce the points
    if len(points) > params.num_drones:
        indices = np.round(np.linspace(0, len(points) - 1, params.num_drones)).astype(int)
        points = points[indices]

    # Shift and rotate the points
    heading_rad = np.radians(params.heading)
    shift_x = params.distance * np.sin(heading_rad)
    shift_y = params.distance * np.cos(heading_rad)
    points[:, 0] += shift_x
    points[:, 1] += shift_y
    points[:, 2] -= params.base_altitude
    points = rotate(points, heading_rad)

    return pd.DataFrame(points, columns=['px', 'py', 'pz'])




def generate_segment(segment_id, drones_per_segment, params):
    # Generate the points for a single segment
    if segment_id in [0, 3, 6]:  # horizontal segments
        x = np.linspace(-1 * params.segment_length, params.segment_length, drones_per_segment)
        
        if segment_id == 0:
            value = -2 * params.segment_length
        elif segment_id == 3:
            value = 0
        else:  # segment_id == 6
            value = 2 * params.segment_length
        
        if params.plane == 'vertical':
            y = np.full(drones_per_segment, params.viewer_position[1] + params.offset * segment_id)
            z = -np.full(drones_per_segment, value)
        else:  # params.plane == 'horizontal'
            y = np.full(drones_per_segment, value)  # make y constant, same as x for vertical
            z = np.full(drones_per_segment, params.offset * segment_id)  # z remains same
            
    else:  # vertical segments
        if segment_id in [1, 4]:
            value = -1 * params.segment_length
        else:  # segment_id in [2, 5]
            value = params.segment_length

        if params.plane == 'vertical':
            y = np.full(drones_per_segment, params.viewer_position[1] + params.offset * segment_id)
            z = -np.linspace(0, 2 * params.segment_length, drones_per_segment) if segment_id in [1, 2] else -np.linspace(-2 * params.segment_length, 0, drones_per_segment)
        else:  # params.plane == 'horizontal'
            y = np.linspace(0, 2 * params.segment_length, drones_per_segment) if segment_id in [1, 2] else np.linspace(-2 * params.segment_length, 0, drones_per_segment)
            z = np.full(drones_per_segment, params.offset * segment_id)
            
        x = np.full(drones_per_segment, value)
            
    points = np.column_stack((x, y, z))
    return points
