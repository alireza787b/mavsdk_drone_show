import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from dataclasses import dataclass
from scipy.spatial import distance
import matplotlib.pyplot as plt
import os
import matplotlib.pyplot as plt
from functions.circle import generate_circle
from functions.seven_segment import generate_seven_segment
from functions.shapeParameters import *
from functions.shape_functions import check_collision, closest_drones, rotate
from functions.shape_plots import plot_2d_observer, plot_points




#-----------------------------------------------------------------------
#-----------------------------------------------------------------------
#-----------------------------------------------------------------------
#-----------------------------------------------------------------------
#-----------------------------------------------------------------------
#-----------------------------------------------------------------------


#Circle

# Define parameters
params = CircleParameters(num_drones=36, radius=10, heading=0, distance=20, offset=0, base_altitude=10, plane='vertical', viewer_position=(0,0,0))

# Generate the drone positions and print them
points = generate_circle(params)



# -----------------------------------------------------------------------


# Seven Segement 
# (try to have *7n drones +1 . at least 36 drone is recommended)

#Define parameters
params = SevenSegmentParameters(num_drones=36, digit=2, heading=0, distance=50, viewer_position=(0,0,0),base_altitude=30, offset=1, segment_length=10,plane="vertical")

# Generate the drone positions and print them
points = generate_seven_segment(params)



#-----------------------------------------------------------------------
#-----------------------------------------------------------------------
#-----------------------------------------------------------------------
#-----------------------------------------------------------------------



#Check Collision
points = check_collision(points)


# Results

# Add 'drone_id' column
points = points.assign(drone_id=range(0, len(points)))
points = points[['drone_id', 'px', 'py', 'pz']]  # Reordering columns

# Results
pd.set_option('display.float_format', '{:.2f}'.format)
print(points.to_string(index=False))

points.to_csv('shapes/static_shapes/active/drone_positions.csv', index=False)

# Plot the generated drone positions in 3D
fig_3d = plot_points(points,params.viewer_position)

# Plot the generated drone positions in 2D from the observer's POV
fig_2d = plot_2d_observer(points, params.heading, params.plane)

# Find the pair of drones that are closest to each other
closest_pair = closest_drones(points[['px', 'py', 'pz']].to_numpy())
closest_distance = distance.euclidean(points.iloc[closest_pair[0]], points.iloc[closest_pair[1]])
print(f"The closest drones are {closest_pair[0]} and {closest_pair[1]} with a distance of {closest_distance:.2f} m.")

