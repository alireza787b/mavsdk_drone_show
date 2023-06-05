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
from functions.show_static_shape_results import show_static_shape_results





#-----------------------------------------------------------------------


#Circle

# Define parameters
params = CircleParameters(num_drones=4,
                          radius=10,
                          heading=0,
                          distance=20,
                          offset=0,
                          base_altitude=10,
                          plane='vertical',
                          viewer_position=(0,0,0))
points = generate_circle(params) 

#-----------------------------------------------------------------------


#seven segment

# Define parameters
# params = SevenSegmentParameters(num_drones=36,
#                                 digit=9,
#                                 heading=0,
#                                 distance=50,
#                                 viewer_position=(0,0,0),
#                                 base_altitude=30,
#                                 offset=2,
#                                 segment_length=10,
#                                 plane="vertical")
# points = generate_seven_segment(params)




#Check Collision and offset if needed
points = check_collision(points)



# display results
show_static_shape_results(points, params)


