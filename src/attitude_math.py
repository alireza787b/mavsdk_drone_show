"""Frame-explicit attitude math independent of MAVLink transport and control."""

import math


def body_rates_to_heading_rate_deg_s(roll_rad, pitch_rad, pitch_rate_rad_s, yaw_rate_rad_s):
    """Convert body angular rates q/r to the Euler heading derivative.

    ATTITUDE's angular rates are body-axis rates, not Euler-angle derivatives.
    Missing/non-finite data and the ill-conditioned pitch singularity have no
    usable heading rate; callers must not substitute body-z rate in that case.
    The cosine tolerance is a numerical guard, not a flight-envelope setting.
    """
    values = (roll_rad, pitch_rad, pitch_rate_rad_s, yaw_rate_rad_s)
    try:
        if any(isinstance(value, bool) for value in values):
            return None
        roll, pitch, pitch_rate, yaw_rate = map(float, values)
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(value) for value in (roll, pitch, pitch_rate, yaw_rate)):
        return None
    cos_pitch = math.cos(pitch)
    if abs(cos_pitch) <= 1e-6:
        return None
    heading_rate = math.degrees(
        (pitch_rate * math.sin(roll) + yaw_rate * math.cos(roll)) / cos_pitch
    )
    return heading_rate if math.isfinite(heading_rate) else None
