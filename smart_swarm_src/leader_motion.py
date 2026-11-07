"""Project validated PX4 motion without estimating the autopilot estimate again.

The producer already supplies fused position and velocity. Repeated prediction
must not move a filter's measurement clock or retain velocity after a measured
stop. Noise treatment belongs to the one follower controller downstream.
"""
import math
import numpy as np


def leader_heading_rate_deg_s(sample, previous_sample, *, max_sample_interval_s):
    """Use measured Euler heading rate or a source-clock heading difference.

    There is deliberately no comparison with the follower yaw-command limit:
    that limit does not make a faster leader measurement invalid. Differencing
    requires distinct integer-millisecond attitude samples within the existing
    freshness interval; transport arrival time must never set its denominator.
    """
    try:
        streamed = float(sample.get('yaw_rate_deg_s'))
    except (TypeError, ValueError, OverflowError):
        streamed = float('nan')
    if math.isfinite(streamed):
        return streamed

    try:
        previous_yaw = float(previous_sample['yaw'])
        current_yaw = float(sample.get('yaw_deg', sample.get('yaw')))
        previous_ms = float(previous_sample['attitude_timestamp_ms'])
        current_ms = float(sample['attitude_timestamp_ms'])
        max_interval = float(max_sample_interval_s)
    except (KeyError, TypeError, ValueError, OverflowError):
        return 0.0
    if not all(math.isfinite(value) for value in (
        previous_yaw, current_yaw, previous_ms, current_ms, max_interval,
    )):
        return 0.0
    if (
        previous_ms <= 0 or current_ms <= previous_ms
        or not previous_ms.is_integer() or not current_ms.is_integer()
        or max_interval <= 0
    ):
        return 0.0
    dt_s = (current_ms - previous_ms) / 1000.0
    if dt_s > max_interval:
        return 0.0
    delta_deg = (current_yaw - previous_yaw + 180.0) % 360.0 - 180.0
    return delta_deg / dt_s


def project_leader_heading(sample, *, now_s, max_prediction_s):
    """Project heading from its own source time, bounded like motion prediction.

    The original sample is never modified, so repeated control iterations do
    not accumulate an extrapolation or advance its measurement clock. A valid
    heading without an available rate is retained without inventing rotation.
    """
    yaw = float(sample['yaw'])
    age = float(now_s) - float(sample['attitude_update_time'])
    horizon = float(max_prediction_s)
    if not math.isfinite(yaw) or not math.isfinite(age):
        raise ValueError('Leader heading projection requires finite state and time')
    if not math.isfinite(horizon) or horizon < 0:
        raise ValueError('Leader prediction horizon must be finite and non-negative')
    try:
        rate = float(sample.get('yaw_rate_deg_s'))
    except (TypeError, ValueError, OverflowError):
        rate = 0.0
    if not math.isfinite(rate):
        rate = 0.0
    projected = yaw + rate * min(max(0.0, age), horizon)
    if not math.isfinite(projected):
        raise ValueError('Projected leader heading is non-finite')
    return projected % 360.0


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
