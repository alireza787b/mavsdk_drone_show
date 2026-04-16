# smart_swarm_src/pd_controller.py

import numpy as np

class PDController:
    def __init__(self, kp, kd, max_velocity, max_acceleration=None, max_jerk=None):
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
        self.max_acceleration = max_acceleration
        self.max_jerk = max_jerk
        self.previous_error = None
        self.previous_command = None
        self.previous_acceleration = None

    def reset(self):
        """Clear controller history after topology/offset/role changes."""
        self.previous_error = None
        self.previous_command = None
        self.previous_acceleration = None

    def compute(
        self,
        position_error,
        dt,
        velocity_error=None,
        feedforward_velocity=None,
        velocity_feedforward=None,
        gain_scale=1.0,
    ):
        """
        Computes the velocity command for a moving target.

        Args:
            position_error (np.ndarray): Position error [n, e, d].
            dt (float): Time since last update (seconds).
            velocity_error (np.ndarray): Relative velocity error [n, e, d].
            feedforward_velocity (np.ndarray): Target velocity feedforward [n, e, d].
            velocity_feedforward (np.ndarray): Legacy alias for feedforward_velocity.
            gain_scale (float): Transition scale factor for reconfiguration ramps.

        Returns:
            np.ndarray: Velocity command [vel_n, vel_e, vel_d].
        """
        if dt <= 0:
            dt = 1e-3

        if velocity_error is not None:
            derivative = velocity_error
        elif self.previous_error is None:
            derivative = np.zeros_like(position_error)
        else:
            derivative = (position_error - self.previous_error) / dt

        self.previous_error = position_error

        if feedforward_velocity is None and velocity_feedforward is not None:
            feedforward_velocity = velocity_feedforward

        feedforward = (
            np.array(feedforward_velocity, dtype=float)
            if feedforward_velocity is not None else
            np.zeros_like(position_error, dtype=float)
        )
        feedback = gain_scale * (self.kp * position_error + self.kd * derivative)
        velocity_command = feedforward + feedback

        if self.max_acceleration is not None and self.previous_command is not None:
            delta = velocity_command - self.previous_command
            max_delta = self.max_acceleration * dt
            delta_norm = np.linalg.norm(delta)
            if delta_norm > max_delta > 0:
                delta = (delta / delta_norm) * max_delta
                velocity_command = self.previous_command + delta

        if self.max_jerk is not None and self.previous_command is not None and self.previous_acceleration is not None:
            current_acceleration = (velocity_command - self.previous_command) / dt
            accel_delta = current_acceleration - self.previous_acceleration
            max_accel_delta = self.max_jerk * dt
            accel_delta_norm = np.linalg.norm(accel_delta)
            if accel_delta_norm > max_accel_delta > 0:
                accel_delta = (accel_delta / accel_delta_norm) * max_accel_delta
                current_acceleration = self.previous_acceleration + accel_delta
                velocity_command = self.previous_command + current_acceleration * dt
            self.previous_acceleration = current_acceleration
        elif self.previous_command is not None:
            self.previous_acceleration = (velocity_command - self.previous_command) / dt

        # Limit the velocity to max_velocity
        speed = np.linalg.norm(velocity_command)
        if speed > self.max_velocity:
            velocity_command = (velocity_command / speed) * self.max_velocity

        self.previous_command = velocity_command.copy()
        return velocity_command
