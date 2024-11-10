# smart_swarm_src/pd_controller.py

import numpy as np

class PDController:
    def __init__(self, kp, kd, max_velocity):
        """
        Initializes the PD controller with given gains and maximum velocity.

        Args:
            kp (float): Proportional gain.
            kd (float): Derivative gain.
            max_velocity (float): Maximum allowed velocity (m/s).
        """
        self.kp = kp
        self.kd = kd
        self.max_velocity = max_velocity
        self.previous_error = None

    def compute(self, position_error, dt):
        """
        Computes the velocity command based on position error.

        Args:
            position_error (np.ndarray): Position error [n, e, d].
            dt (float): Time since last update (seconds).

        Returns:
            np.ndarray: Velocity command [vel_n, vel_e, vel_d].
        """
        if self.previous_error is None:
            derivative = np.zeros_like(position_error)
        else:
            derivative = (position_error - self.previous_error) / dt

        self.previous_error = position_error

        velocity_command = self.kp * position_error + self.kd * derivative

        # Limit the velocity to max_velocity
        speed = np.linalg.norm(velocity_command)
        if speed > self.max_velocity:
            velocity_command = (velocity_command / speed) * self.max_velocity

        return velocity_command
