"""Project validated PX4 motion without estimating the autopilot estimate again.

The producer already supplies fused position and velocity. Repeated prediction
must not move a filter's measurement clock or retain velocity after a measured
stop. Noise treatment belongs to the one follower controller downstream.
"""
import math
import numpy as np


def project_leader_motion(sample, *, now_s, max_prediction_s):
    """Return [N, E, D, vN, vE, vD] projected from the original sample.

    Source validity/identity and stale-data recovery are owned by the runtime.
    Prediction is bounded independently and never mutates the source sample.
    """
    state = np.array([sample[k] for k in ('pos_n', 'pos_e', 'pos_d', 'vel_n', 'vel_e', 'vel_d')], dtype=float)
    age = float(now_s) - float(sample['update_time'])
    horizon = float(max_prediction_s)
    if not np.all(np.isfinite(state)) or not math.isfinite(age):
        raise ValueError('Leader motion projection requires finite state and time')
    if not math.isfinite(horizon) or horizon < 0:
        raise ValueError('Leader prediction horizon must be finite and non-negative')
    state[:3] += state[3:] * min(max(0.0, age), horizon)
    if not np.all(np.isfinite(state)):
        raise ValueError('Projected leader motion is non-finite')
    return state
