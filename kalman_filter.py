from filterpy.kalman import KalmanFilter
from filterpy.common import Q_discrete_white_noise
import numpy as np

class DroneKalmanFilter:
    def __init__(self, dim_x, dim_z):
        self.dim_x = dim_x
        self.dim_z = dim_z
        self.initialized = False

    def init_filter(self, initial_state, initial_uncertainty):
        self.filter = KalmanFilter(dim_x=self.dim_x, dim_z=self.dim_z)
        self.filter.x = initial_state
        # Define the state transition matrix
        self.filter.F = np.array([[1, 0, 0, 1, 0, 0],
                                  [0, 1, 0, 0, 1, 0],
                                  [0, 0, 1, 0, 0, 1],
                                  [0, 0, 0, 1, 0, 0],
                                  [0, 0, 0, 0, 1, 0],
                                  [0, 0, 0, 0, 0, 1]])
        # Define the measurement function matrix
        self.filter.H = np.eye(self.dim_x)
        self.initialized = True
        self.filter.P = np.diag(initial_uncertainty)
        self.filter.R = np.eye(self.dim_z) * 1
        self.filter.Q = Q_discrete_white_noise(dim=self.dim_x, dt=1, var=0.01)

    def update(self, measurement):
        self.filter.update(measurement)

    def predict(self):
        self.filter.predict()