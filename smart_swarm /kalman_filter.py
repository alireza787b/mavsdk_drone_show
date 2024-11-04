# smart_swarm/kalman_filter.py

import numpy as np
from filterpy.kalman import KalmanFilter
from filterpy.common import Q_discrete_white_noise

class LeaderKalmanFilter:
    def __init__(self):
        """
        Initializes the Kalman filter for estimating the leader's state.
        """
        # State vector: [pos_n, pos_e, pos_d, vel_n, vel_e, vel_d]
        self.kf = KalmanFilter(dim_x=6, dim_z=6)
        self._initialize_filter()
        self.last_update_time = None

    def _initialize_filter(self):
        """
        Sets up the Kalman filter matrices.
        """
        # State transition matrix (will be updated with dt)
        self.kf.F = np.eye(6)

        # Measurement function: direct measurement of positions and velocities
        self.kf.H = np.eye(6)

        # Initial state covariance
        self.kf.P *= 10.0

        # Measurement noise covariance
        position_variance = 5.0  # Variance in position measurements (meters^2)
        velocity_variance = 1.0  # Variance in velocity measurements ((m/s)^2)
        self.kf.R = np.diag([position_variance]*3 + [velocity_variance]*3)

        # Process noise covariance (will be updated with dt)
        self.q_variance = 0.1  # Process noise variance
        self.kf.Q = np.eye(6)

        # Initial state
        self.kf.x = np.zeros((6, 1))

    def reset(self):
        """
        Resets the Kalman filter to its initial state.
        """
        self._initialize_filter()
        self.last_update_time = None

    def predict(self, current_time):
        """
        Predicts the current state of the leader based on elapsed time since last update.

        Args:
            current_time (float): Current timestamp in seconds since epoch.

        Returns:
            np.ndarray: Predicted state vector [pos_n, pos_e, pos_d, vel_n, vel_e, vel_d].
        """
        if self.last_update_time is None:
            dt = 0.0
        else:
            dt = current_time - self.last_update_time
            if dt < 0.0:
                dt = 0.0  # Ensure non-negative time difference

        # Update the state transition matrix with dt
        self.kf.F = np.array([
            [1, 0, 0, dt, 0,  0],
            [0, 1, 0, 0,  dt, 0],
            [0, 0, 1, 0,  0,  dt],
            [0, 0, 0, 1,  0,  0],
            [0, 0, 0, 0,  1,  0],
            [0, 0, 0, 0,  0,  1],
        ])

        # Update the process noise covariance matrix with dt
        q = Q_discrete_white_noise(dim=2, dt=dt, var=self.q_variance)
        self.kf.Q = np.block([
            [q, np.zeros((2, 4))],
            [np.zeros((4, 2)), np.zeros((4, 4))]
        ])
        self.kf.Q = np.kron(np.eye(3), q)

        self.kf.predict()
        return self.kf.x.flatten()

    def update(self, measurement, measurement_time):
        """
        Updates the Kalman filter with a new measurement if the timestamp has advanced.

        Args:
            measurement (dict): Measurement containing position and velocity.
                Expected keys: 'pos_n', 'pos_e', 'pos_d', 'vel_n', 'vel_e', 'vel_d'
            measurement_time (float): Timestamp of the measurement.

        Returns:
            None
        """
        if self.last_update_time is None or measurement_time > self.last_update_time:
            dt = measurement_time - self.last_update_time if self.last_update_time else 0.0
            if dt < 0.0:
                dt = 0.0  # Ensure non-negative time difference

            # Update last update time
            self.last_update_time = measurement_time

            # Prepare measurement vector
            z = np.array([
                measurement['pos_n'],
                measurement['pos_e'],
                measurement['pos_d'],
                measurement['vel_n'],
                measurement['vel_e'],
                measurement['vel_d']
            ]).reshape(6, 1)

            # Update the state transition matrix with dt
            self.kf.F = np.array([
                [1, 0, 0, dt, 0,  0],
                [0, 1, 0, 0,  dt, 0],
                [0, 0, 1, 0,  0,  dt],
                [0, 0, 0, 1,  0,  0],
                [0, 0, 0, 0,  1,  0],
                [0, 0, 0, 0,  0,  1],
            ])

            # Update process noise covariance with dt
            q = Q_discrete_white_noise(dim=2, dt=dt, var=self.q_variance)
            self.kf.Q = np.kron(np.eye(3), q)

            # Predict to current time
            self.kf.predict()

            # Update with new measurement
            self.kf.update(z)
        else:
            # Duplicate or outdated measurement; ignore
            pass

    def get_state(self):
        """
        Returns the current estimated state.

        Returns:
            dict: Estimated state with keys 'pos_n', 'pos_e', 'pos_d', 'vel_n', 'vel_e', 'vel_d'
        """
        state = self.kf.x.flatten()
        return {
            'pos_n': state[0],
            'pos_e': state[1],
            'pos_d': state[2],
            'vel_n': state[3],
            'vel_e': state[4],
            'vel_d': state[5]
        }
