import numpy as np
from filterpy.kalman import KalmanFilter

class DroneKalmanFilter:
    def __init__(self, dt):
        self.kf = KalmanFilter(dim_x=6, dim_z=6)  # We're considering x, y, z each for position and velocity
        self.dt = dt
        self.initialize_kalman_filter()

    def initialize_kalman_filter(self):
        """
        Initializes the Kalman filter for position and velocity in 3D space (NED: North, East, Down).
        """
        # Initial state [north_pos, east_pos, down_pos, north_vel, east_vel, down_vel]
        self.kf.x = np.array([0, 0, 0, 0, 0, 0])

        # State transition matrix (A) - assuming a linear motion model
        self.kf.F = np.array([
            [1, 0, 0, self.dt, 0, 0],
            [0, 1, 0, 0, self.dt, 0],
            [0, 0, 1, 0, 0, self.dt],
            [0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 1]
        ])

        # Measurement matrix (H) - we're measuring both position and velocity directly
        self.kf.H = np.eye(6)

        # Measurement noise covariance (R) - assumes all measurements have same noise, which is probably not the case in real-world
        self.kf.R = np.eye(6) * 0.1

        # Process noise covariance (Q) - this can be tuned based on how much we trust our motion model
        self.kf.Q = np.eye(6) * 0.01

    def update(self, pos, vel):
        """
        Updates the Kalman filter with new position and velocity measurements.
        """
        z = np.array([pos['north'], pos['east'], pos['down'], vel['north'], vel['east'], vel['down']])
        self.kf.update(z)
        self.kf.predict()

    def get_state(self):
        """
        Retrieves the filtered position and velocity.
        """
        filtered_state = self.kf.x
        return {
            'pos': {'north': filtered_state[0], 'east': filtered_state[1], 'down': filtered_state[2]},
            'vel': {'north': filtered_state[3], 'east': filtered_state[4], 'down': filtered_state[5]}
        }
