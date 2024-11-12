# smart_swarm_src/low_pass_filter.py

import numpy as np

class LowPassFilter:
    def __init__(self, alpha):
        """
        Initializes the low-pass filter.

        Args:
            alpha (float): Smoothing factor between 0 and 1.
        """
        self.alpha = alpha
        self.state = None

    def filter(self, value):
        """
        Filters the input value.

        Args:
            value (np.ndarray): Input value to filter.

        Returns:
            np.ndarray: Filtered value.
        """
        if self.state is None:
            self.state = value
        else:
            self.state = self.alpha * value + (1 - self.alpha) * self.state
        return self.state
