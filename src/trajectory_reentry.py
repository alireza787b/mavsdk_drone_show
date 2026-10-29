"""Pure synchronized re-entry geometry for a fleet already settled in Hold.

Every aircraft follows its straight displacement with the same quintic progress
``s(u) = 10u**3 - 15u**4 + 6u**5``, u in [0, 1]. The common duration enforces
isotropic 3D speed, acceleration and jerk limits. Relative positions are affine
in s, so closest pair separation is evaluated analytically over the *whole*
transition, not inferred from a sampling grid.

This is not an execution controller or a collision guarantee for real aircraft.
It assumes synchronized execution, stationary initial conditions and a common
NED frame. Tracking uncertainty, clock skew, obstacles and terrain require
separate admission checks. It ends at zero velocity/acceleration: continuing a
paused route with nonzero derivatives requires a coordinated clock ramp or
derivative-matched handoff, not an immediate jump to normal-speed playback.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Mapping, Sequence


Vector3 = tuple[float, float, float]

# Exact extrema of the dimensionless quintic derivatives on [0, 1].
_MAX_SPEED = 15.0 / 8.0
_MAX_ACCELERATION = 10.0 / math.sqrt(3.0)
_MAX_JERK = 60.0


def _number(value: Real, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{label} must be a finite number')
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f'{label} must be finite' + (' and greater than zero' if positive else ''))
    return result


def _vector(value: Sequence[Real], label: str) -> Vector3:
    try:
        valid_shape = not isinstance(value, (str, bytes)) and len(value) == 3
    except TypeError:
        valid_shape = False
    if not valid_shape:
        raise ValueError(f'{label} must contain exactly three NED coordinates')
    return tuple(_number(component, label) for component in value)


@dataclass(frozen=True)
class ReentryLimits:
    speed_m_s: float
    acceleration_m_s2: float
    jerk_m_s3: float
    minimum_duration_s: float = 1.0

    def __post_init__(self):
        for name in ('speed_m_s', 'acceleration_m_s2', 'jerk_m_s3', 'minimum_duration_s'):
            object.__setattr__(self, name, _number(getattr(self, name), name, positive=True))


@dataclass(frozen=True)
class ReentryPath:
    aircraft_id: str
    held_ned_m: Vector3
    target_ned_m: Vector3


@dataclass(frozen=True)
class SeparationEvidence:
    aircraft_ids: tuple[str, str]
    distance_m: float
    # Common geometric progress, not elapsed-time fraction.
    progress: float


class ReentrySeparationError(ValueError):
    def __init__(self, evidence: SeparationEvidence, required_m: float):
        self.evidence = evidence
        self.required_m = required_m
        super().__init__(
            f'Re-entry paths for {evidence.aircraft_ids[0]} and {evidence.aircraft_ids[1]} '
            f'approach to {evidence.distance_m:.3f} m; required separation is {required_m:.3f} m'
        )


@dataclass(frozen=True)
class ReentrySetpoint:
    aircraft_id: str
    position_ned_m: Vector3
    velocity_ned_m_s: Vector3
    acceleration_ned_m_s2: Vector3
    jerk_ned_m_s3: Vector3


@dataclass(frozen=True)
class ReentryPlan:
    duration_s: float
    paths: tuple[ReentryPath, ...]
    limits: ReentryLimits
    minimum_separation_m: float
    closest_approach: SeparationEvidence | None

    def sample(self, elapsed_s: float) -> tuple[ReentrySetpoint, ...]:
        """Evaluate commanded kinematics; time outside the transition is rejected."""
        elapsed = _number(elapsed_s, 'elapsed_s')
        if not 0 <= elapsed <= self.duration_s:
            raise ValueError('elapsed_s must be within the re-entry duration')
        u = elapsed / self.duration_s
        s = min(1.0, max(0.0, u**3 * (10.0 + u * (-15.0 + 6.0 * u))))
        ds = 30.0 * u**2 * (1.0 - u)**2 / self.duration_s
        dds = 60.0 * u * (1.0 - u) * (1.0 - 2.0 * u) / self.duration_s / self.duration_s
        ddds = (60.0 - 360.0 * u + 360.0 * u**2) / self.duration_s / self.duration_s / self.duration_s
        results = []
        for path in self.paths:
            displacement = tuple(b - a for a, b in zip(path.held_ned_m, path.target_ned_m))
            position = tuple(a * (1.0 - s) + b * s for a, b in zip(path.held_ned_m, path.target_ned_m))
            results.append(ReentrySetpoint(
                aircraft_id=path.aircraft_id,
                position_ned_m=position,
                velocity_ned_m_s=tuple(d * ds for d in displacement),
                acceleration_ned_m_s2=tuple(d * dds for d in displacement),
                jerk_ned_m_s3=tuple(d * ddds for d in displacement),
            ))
        return tuple(results)


def _closest_approach(first: ReentryPath, second: ReentryPath) -> SeparationEvidence:
    initial = tuple(a - b for a, b in zip(first.held_ned_m, second.held_ned_m))
    final = tuple(a - b for a, b in zip(first.target_ned_m, second.target_ned_m))
    change = tuple(b - a for a, b in zip(initial, final))
    if not all(math.isfinite(value) for value in (*initial, *final, *change)):
        raise ValueError('Relative re-entry geometry exceeds finite numeric range')
    # Scale before dot products to avoid needless overflow for large coordinates.
    scale = max(map(abs, (*initial, *change)))
    if scale == 0:
        progress = 0.0
    else:
        origin = tuple(value / scale for value in initial)
        delta = tuple(value / scale for value in change)
        denominator = sum(value * value for value in delta)
        progress = 0.0 if denominator == 0 else min(1.0, max(
            0.0, -sum(a * b for a, b in zip(origin, delta)) / denominator))
    distance = math.hypot(*(a * (1.0 - progress) + b * progress for a, b in zip(initial, final)))
    if not math.isfinite(distance):
        raise ValueError('Re-entry separation exceeds finite numeric range')
    return SeparationEvidence((first.aircraft_id, second.aircraft_id), distance, progress)


def plan_reentry(
    held_positions: Mapping[str, Sequence[Real]],
    paused_targets: Mapping[str, Sequence[Real]],
    limits: ReentryLimits,
    *,
    minimum_separation_m: float,
) -> ReentryPlan:
    """Plan one common-duration transition or reject invalid/crossing geometry.

    The caller supplies an explicit separation requirement; zero is permitted for
    simulation/math use but does not provide physical collision separation.
    Aircraft identities are opaque nonempty strings and must match exactly.
    """
    separation = _number(minimum_separation_m, 'minimum_separation_m')
    if separation < 0:
        raise ValueError('minimum_separation_m must be nonnegative')
    if not isinstance(limits, ReentryLimits):
        raise ValueError('limits must be ReentryLimits')
    if (not isinstance(held_positions, Mapping) or not isinstance(paused_targets, Mapping)
            or not held_positions or set(held_positions) != set(paused_targets)):
        raise ValueError('Held and target aircraft sets must be identical and nonempty')
    if any(not isinstance(identity, str) or not identity for identity in held_positions):
        raise ValueError('Aircraft identities must be nonempty strings')
    paths = tuple(ReentryPath(
        identity, _vector(held_positions[identity], f'{identity} held position'),
        _vector(paused_targets[identity], f'{identity} target position'),
    ) for identity in sorted(held_positions))
    distance = max(math.dist(path.held_ned_m, path.target_ned_m) for path in paths)
    if not math.isfinite(distance):
        raise ValueError('Re-entry displacement exceeds finite numeric range')
    duration = max(
        limits.minimum_duration_s,
        _MAX_SPEED * (distance / limits.speed_m_s),
        math.sqrt(_MAX_ACCELERATION) * math.sqrt(distance / limits.acceleration_m_s2),
        math.cbrt(_MAX_JERK) * math.cbrt(distance / limits.jerk_m_s3),
    )
    if not math.isfinite(duration):
        raise ValueError('Required re-entry duration exceeds finite numeric range')
    closest = None
    for index, first in enumerate(paths):
        for second in paths[index + 1:]:
            evidence = _closest_approach(first, second)
            if closest is None or evidence.distance_m < closest.distance_m:
                closest = evidence
    if closest is not None and closest.distance_m < separation:
        raise ReentrySeparationError(closest, separation)
    return ReentryPlan(duration, paths, limits, separation, closest)
