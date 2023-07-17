from filterpy.kalman import KalmanFilter
import numpy as np

class DroneKalmanFilter:
    def __init__(self, initial_state, initial_uncertainty):
        # State: [x_position, y_position, z_position, x_velocity, y_velocity, z_velocity]
        self.filter = KalmanFilter(dim_x=6, dim_z=3)

        # Initial state
        self.filter.x = initial_state

        # State transition matrix
        self.filter.F = np.array([[1, 0, 0, 1, 0, 0],
                                  [0, 1, 0, 0, 1, 0],
                                  [0, 0, 1, 0, 0, 1],
                                  [0, 0, 0, 1, 0, 0],
                                  [0, 0, 0, 0, 1, 0],
                                  [0, 0, 0, 0, 0, 1]])

        # Measurement function
        self.filter.H = np.array([[1, 0, 0, 0, 0, 0],
                                  [0, 1, 0, 0, 0, 0],
                                  [0, 0, 1, 0, 0, 0]])

        # Initial uncertainty
        self.filter.P *= initial_uncertainty

        # Measurement uncertainty
        self.filter.R *= 1

        # Process uncertainty
        self.filter.Q = Q_discrete_white_noise(dim=6, dt=1, var=0.01)

    def update(self, measurement):
        self.filter.update(measurement)

    def predict(self):
        self.filter.predict()
