import numpy as np
import logging

class KalmanFilter:

    def __init__(self):
        """
        Initialize the Kalman Filter without setting any initial parameters.
        """
        self.is_initialized = False
        self.reliability_score = 0
        logging.debug("Kalman Filter object created, awaiting initialization.")

    def initialize(self, initial_state, initial_covariance, process_noise, measurement_noise):
        """
        Initialize the Kalman Filter with initial parameters.
        
        Parameters:
        - initial_state: Initial state estimate as a numpy array
        - initial_covariance: Initial state covariance as a numpy array
        - process_noise: Process noise covariance as a numpy array
        - measurement_noise: Measurement noise covariance as a numpy array
        """
        # Set initialized flag to True
        self.is_initialized = True
        logging.info("Kalman Filter initialized.")

        # 1.1 Initialize State
        self.state = np.array(initial_state, dtype=float)

        # 1.2 Initialize State Covariance
        self.P = np.array(initial_covariance, dtype=float)

        # 1.3 Initialize State Transition Matrix (A)
        self.A = np.array([
            [1, 0, 0, 0, 0, 0, 0, 0, 0],  # x to x
            [0, 1, 0, 0, 0, 0, 0, 0, 0],  # vx to vx
            [0, 0, 1, 0, 0, 0, 0, 0, 0],  # ax to ax
            [0, 0, 0, 1, 0, 0, 0, 0, 0],  # y to y
            [0, 0, 0, 0, 1, 0, 0, 0, 0],  # vy to vy
            [0, 0, 0, 0, 0, 1, 0, 0, 0],  # ay to ay
            [0, 0, 0, 0, 0, 0, 1, 0, 0],  # z to z
            [0, 0, 0, 0, 0, 0, 0, 1, 0],  # vz to vz
            [0, 0, 0, 0, 0, 0, 0, 0, 1],  # az to az
        ], dtype=float)

        # 1.4 Initialize Observation Matrix (H)
        self.H = np.identity(9, dtype=float)  # Assuming 9 states

        # 1.5 Initialize Process Noise Covariance (Q)
        self.Q = np.array(process_noise, dtype=float)

        # 1.6 Initialize Measurement Noise Covariance (R)
        self.R = np.array(measurement_noise, dtype=float)
        
        
    def initialize_if_needed(self, position_setpoint, velocity_setpoint):
        if not self.is_initialized:
            initial_state = [
                position_setpoint['north'],
                velocity_setpoint['north'],  # Initial velocity in North direction
                0,  # Initial acceleration in North direction
                position_setpoint['east'],
                velocity_setpoint['east'],  # Initial velocity in East direction
                0,  # Initial acceleration in East direction
                position_setpoint['down'],
                velocity_setpoint['down'],  # Initial velocity in Down direction
                0   # Initial acceleration in Down direction
            ]

            # Assuming that initial covariance, process noise, and measurement noise are pre-defined
            initial_covariance = np.identity(9)  # 9x9 identity matrix as an example
            process_noise = np.identity(9)  # 9x9 identity matrix as an example
            measurement_noise = np.identity(9)  # 9x9 identity matrix as an example

            self.initialize(initial_state, initial_covariance, process_noise, measurement_noise)
            logging.info("Kalman Filter initialized with the first setpoint.")

    def predict(self):
        """
        Predict the next state and error covariance.
        """
        if not self.is_initialized:
            logging.warning("Kalman Filter not initialized. Call initialize() first.")
            return

        # Predicted state estimate: x_hat(k|k-1) = A * x_hat(k-1|k-1)
        self.state = np.dot(self.A, self.state)

        # Predicted estimate covariance: P(k|k-1) = A * P(k-1|k-1) * A' + Q
        self.P = np.dot(np.dot(self.A, self.P), self.A.T) + self.Q

        logging.debug(f"Kalman Filter state predicted. State: {self.state}")
        # Compute reliability measure based on diagonal elements of P
        reliability = np.diagonal(self.P)
        self.reliability_score = 100 * (1 - reliability / np.sum(reliability))
        logging.debug(f"Reliability Score: {self.reliability_score}")

    def update(self, measurement):
        """
        Update the state and error covariance based on a measurement.

        Parameters:
        - measurement: The measurement value as a numpy array
        """
        if not self.is_initialized:
            logging.warning("Kalman Filter not initialized. Call initialize() first.")
            return

        # Innovation or measurement residual: y(k) = z(k) - H * x_hat(k|k-1)
        y = measurement - np.dot(self.H, self.state)

        # Innovation (or residual) covariance: S(k) = H * P(k|k-1) * H' + R
        S = np.dot(np.dot(self.H, self.P), self.H.T) + self.R

        # Optimal Kalman gain: K(k) = P(k|k-1) * H' * inv(S)
        K = np.dot(np.dot(self.P, self.H.T), np.linalg.inv(S))

        # Updated (a posteriori) state estimate: x_hat(k|k) = x_hat(k|k-1) + K * y
        self.state = self.state + np.dot(K, y)

        # Updated (a posteriori) estimate covariance: P(k|k) = (I - K * H) * P(k|k-1)
        self.P = self.P - np.dot(np.dot(K, self.H), self.P)

        logging.debug("Kalman Filter state updated.")

    def get_current_state(self):
            """
            Retrieve the current state estimate.

            Returns:
            - Dictionary containing current estimates of position, velocity, and acceleration
            """
            return {
                'position': {'north': self.state[0], 'east': self.state[3], 'down': self.state[6]},
                'velocity': {'north': self.state[1], 'east': self.state[4], 'down': self.state[7]},
                'acceleration': {'north': self.state[2], 'east': self.state[5], 'down': self.state[8]}
            }