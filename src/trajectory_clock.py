"""Pure, continuous trajectory-clock ramps for coordinated pause/resume design.

This module does not dispatch commands or establish fleet synchronization. A
coordinator must agree the same start/time anchor with every participant before
using a ramp. Retimed kinematic bounds must be validated against aircraft limits;
smooth clock derivatives alone are not proof of feasible flight dynamics.
"""
from dataclasses import dataclass
import math
from numbers import Real
from typing import Literal


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return float(value)


@dataclass(frozen=True)
class ClockState:
    route_time_s: float
    rate: float
    rate_derivative: float
    rate_second_derivative: float


@dataclass(frozen=True)
class TrajectoryClockRamp:
    """Quintic rate ramp: pause 1→0, resume 0→1, with no clock discontinuity.

    start_time_s is in the caller's agreed execution-clock domain. The route
    advances duration/2 during either ramp; re-entry and stopped holds must not
    consume route time. Resume starts at the paused route anchor, not wall time.
    """
    action: Literal['pause', 'resume']
    start_time_s: float
    route_time_s: float
    duration_s: float

    def __post_init__(self):
        if self.action not in ('pause', 'resume'):
            raise ValueError('Clock ramp action must be pause or resume')
        for name in ('start_time_s', 'route_time_s', 'duration_s'):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.route_time_s < 0 or self.duration_s <= 0:
            raise ValueError('Route time must be nonnegative and ramp duration positive')
        if not math.isfinite(self.route_time_s + self.duration_s / 2):
            raise ValueError('Clock ramp exceeds numeric range')
        if not math.isfinite(60 / self.duration_s / self.duration_s):
            raise ValueError('Clock ramp duration is too small for finite derivatives')

    def sample(self, execution_time_s: float) -> ClockState:
        elapsed = _finite(execution_time_s, 'execution_time_s') - self.start_time_s
        if not math.isfinite(elapsed):
            raise ValueError('Clock elapsed time exceeds numeric range')
        starting_rate = 1.0 if self.action == 'pause' else 0.0
        final_rate = 1.0 - starting_rate
        if elapsed <= 0:
            value = self.route_time_s + starting_rate * elapsed
            if value < 0 or not math.isfinite(value):
                raise ValueError('Sample precedes the mission clock or exceeds numeric range')
            return ClockState(value, starting_rate, 0, 0)
        if elapsed >= self.duration_s:
            value = self.route_time_s + self.duration_s / 2 + final_rate * (elapsed - self.duration_s)
            if not math.isfinite(value):
                raise ValueError('Clock state exceeds numeric range')
            return ClockState(value, final_rate, 0, 0)
        u = elapsed / self.duration_s
        rate = u**3 * (10 + u * (-15 + 6*u))
        integrated_rate = self.duration_s * u**4 * (2.5 + u * (-3 + u))
        derivative = 30*u*u*(1-u)**2 / self.duration_s
        second = 60*u*(1-u)*(1-2*u) / self.duration_s / self.duration_s
        sign = -1 if self.action == 'pause' else 1
        offset = elapsed - integrated_rate if self.action == 'pause' else integrated_rate
        return ClockState(self.route_time_s + offset, starting_rate + sign*rate,
                          sign*derivative, sign*second)


def retime_kinematics(velocity, acceleration, jerk, clock: ClockState):
    """Apply chain-rule derivatives for position(path_time(execution_time))."""
    vectors = []
    for name, vector in (('velocity', velocity), ('acceleration', acceleration), ('jerk', jerk)):
        if len(vector) != 3:
            raise ValueError(f'{name} must contain three components in the same coordinate frame')
        vectors.append(tuple(_finite(value, name) for value in vector))
    rate = _finite(clock.rate, 'clock rate')
    first = _finite(clock.rate_derivative, 'clock rate derivative')
    second = _finite(clock.rate_second_derivative, 'clock rate second derivative')
    if not 0 <= rate <= 1:
        raise ValueError('Clock rate must be between zero and one')
    v, a, j = vectors
    result = (tuple(x*rate for x in v), tuple(x*rate*rate+y*first for x,y in zip(a,v)),
              tuple(x*rate**3+3*y*rate*first+z*second for x,y,z in zip(j,a,v)))
    if not all(math.isfinite(value) for vector in result for value in vector):
        raise ValueError('Retimed kinematics exceed numeric range')
    return result
