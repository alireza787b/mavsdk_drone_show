"""Stateful, fail-closed shaping for Smart Swarm NED velocity commands.

The follower controller produces a requested velocity.  This module owns the
continuity contract between that request and the value sent to PX4:

* horizontal and vertical speed envelopes are independent;
* acceleration and jerk apply from the first shaped command;
* an event-loop stall cannot enlarge the permitted command step; and
* invalid numeric input never contaminates the last known-good state.

The shaper starts from the same zero-velocity, zero-acceleration seed used when
entering Offboard mode.  Callers may explicitly reset it to another measured or
previously-commanded seed when continuity must be preserved across a runtime
transition.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np


class VelocityCommandShapeError(ValueError):
    """Raised when a command cannot be shaped without violating its contract."""


class NedVelocityCommandShaper:
    """Shape requested NED velocity into a bounded, continuous command stream."""

    _ZERO = np.zeros(3, dtype=float)
    _TOLERANCE = 1e-9

    def __init__(
        self,
        *,
        max_horizontal_speed_m_s: float,
        max_vertical_speed_m_s: float,
        max_acceleration_m_s2: float,
        max_jerk_m_s3: float,
        max_dt_s: float,
        seed_velocity_ned: Iterable[float] = (0.0, 0.0, 0.0),
        seed_acceleration_ned: Iterable[float] = (0.0, 0.0, 0.0),
    ) -> None:
        self.max_horizontal_speed_m_s = self._positive_finite(
            max_horizontal_speed_m_s,
            "max_horizontal_speed_m_s",
        )
        self.max_vertical_speed_m_s = self._positive_finite(
            max_vertical_speed_m_s,
            "max_vertical_speed_m_s",
        )
        self.max_acceleration_m_s2 = self._positive_finite(
            max_acceleration_m_s2,
            "max_acceleration_m_s2",
        )
        self.max_jerk_m_s3 = self._positive_finite(
            max_jerk_m_s3,
            "max_jerk_m_s3",
        )
        self.max_dt_s = self._positive_finite(max_dt_s, "max_dt_s")

        self._velocity = self._ZERO.copy()
        self._acceleration = self._ZERO.copy()
        self.reset(
            seed_velocity_ned=seed_velocity_ned,
            seed_acceleration_ned=seed_acceleration_ned,
        )

    @property
    def velocity_ned(self) -> np.ndarray:
        """Return a copy of the last shaped velocity command."""
        return self._velocity.copy()

    @property
    def acceleration_ned(self) -> np.ndarray:
        """Return a copy of the acceleration associated with the last command."""
        return self._acceleration.copy()

    def reset(
        self,
        *,
        seed_velocity_ned: Iterable[float] = (0.0, 0.0, 0.0),
        seed_acceleration_ned: Iterable[float] = (0.0, 0.0, 0.0),
    ) -> None:
        """Reset state to an explicit, already-safe continuity seed.

        The seed is stored exactly; it is never silently clipped.  A caller that
        supplies a seed outside the configured envelope receives a typed error,
        and the previous state remains unchanged.
        """

        velocity = self._finite_ned_vector(seed_velocity_ned, "seed_velocity_ned")
        acceleration = self._finite_ned_vector(
            seed_acceleration_ned,
            "seed_acceleration_ned",
        )
        self._require_speed_within_envelope(velocity, "seed_velocity_ned")

        acceleration_norm = float(np.linalg.norm(acceleration))
        if acceleration_norm > self.max_acceleration_m_s2 + self._TOLERANCE:
            raise VelocityCommandShapeError(
                "seed_acceleration_ned exceeds max_acceleration_m_s2"
            )

        self._require_speed_within_envelope(
            self._braking_endpoint(velocity, acceleration), "seed braking reserve"
        )

        self._velocity = velocity.copy()
        self._acceleration = acceleration.copy()

    def shape(self, requested_velocity_ned: Iterable[float], dt_s: float) -> np.ndarray:
        """Return the next safe NED velocity command.

        ``dt_s`` is capped at ``max_dt_s``.  This means a delayed control-loop
        iteration cannot spend the whole scheduling gap as an acceleration or
        jerk budget and emit a large catch-up step.

        Invalid input or an infeasible hard-envelope transition raises
        :class:`VelocityCommandShapeError` without changing shaper state.
        """

        requested = self._finite_ned_vector(
            requested_velocity_ned,
            "requested_velocity_ned",
        )
        dt = self._positive_finite(dt_s, "dt_s")
        effective_dt = min(dt, self.max_dt_s)
        target = self._clip_speed(requested)

        velocity = self._velocity
        acceleration = self._acceleration
        velocity_error = target - velocity
        error_distance = float(np.linalg.norm(velocity_error))
        jerk_step = self.max_jerk_m_s3 * effective_dt

        exact_acceleration = velocity_error / effective_dt
        exact_is_feasible = (
            float(np.linalg.norm(exact_acceleration))
            <= self.max_acceleration_m_s2 + self._TOLERANCE
            and float(np.linalg.norm(exact_acceleration - acceleration))
            <= jerk_step + self._TOLERANCE
            # Reaching the target with more acceleration than can be removed on
            # the following iteration would force an overshoot or a jerk jump.
            and float(np.linalg.norm(exact_acceleration))
            <= jerk_step + self._TOLERANCE
        )

        if exact_is_feasible:
            next_acceleration = exact_acceleration
        elif error_distance <= self._TOLERANCE:
            next_acceleration = self._move_towards(
                acceleration,
                self._ZERO,
                jerk_step,
            )
        else:
            direction = velocity_error / error_distance
            acceleration_towards_target = direction * self.max_acceleration_m_s2
            prospective_acceleration = self._move_towards(
                acceleration,
                acceleration_towards_target,
                jerk_step,
            )
            prospective_norm = float(np.linalg.norm(prospective_acceleration))
            distance_to_accelerate_then_brake = (
                prospective_norm * effective_dt
                + self._discrete_braking_distance(
                    prospective_norm,
                    self.max_jerk_m_s3,
                    effective_dt,
                )
            )

            if distance_to_accelerate_then_brake <= error_distance + self._TOLERANCE:
                next_acceleration = prospective_acceleration
            else:
                next_acceleration = self._move_towards(
                    acceleration,
                    self._ZERO,
                    jerk_step,
                )

        next_acceleration = self._limit_norm(
            next_acceleration,
            self.max_acceleration_m_s2,
        )
        # Keep a braking reserve in velocity space, not merely a valid next
        # sample. This remains conservative across changing loop intervals.
        # Braking follows a straight segment inside the convex speed cylinder.
        def viable(candidate):
            next_v = velocity + candidate * effective_dt
            stop_v = self._braking_endpoint(next_v, candidate)
            return all(
                np.linalg.norm(v[:2]) <= self.max_horizontal_speed_m_s
                and abs(v[2]) <= self.max_vertical_speed_m_s
                for v in (next_v, stop_v)
            )

        if not viable(next_acceleration):
            brake = self._move_towards(acceleration, self._ZERO, jerk_step)
            if not viable(brake):
                raise VelocityCommandShapeError("continuity seed has no braking reserve")
            # Both accelerations satisfy the convex acceleration/jerk limits.
            # Find a viable interpolation from the guaranteed braking option.
            low, high = 0.0, 1.0
            for _ in range(40):
                mid = (low + high) / 2.0
                if viable(brake + mid * (next_acceleration - brake)):
                    low = mid
                else:
                    high = mid
            next_acceleration = brake + low * (next_acceleration - brake)
        next_velocity = velocity + next_acceleration * effective_dt

        if not np.all(np.isfinite(next_velocity)) or not np.all(np.isfinite(next_acceleration)):
            raise VelocityCommandShapeError("shaped command became non-finite")

        try:
            self._require_speed_within_envelope(next_velocity, "shaped velocity")
        except VelocityCommandShapeError as exc:
            # A hard speed envelope has priority over producing a command whose
            # derivative cannot be represented honestly.  Preserve the last
            # known-good state and let the caller enter its explicit HOLD path.
            raise VelocityCommandShapeError(
                "no jerk-continuous command remains inside the speed envelope"
            ) from exc

        actual_acceleration = (next_velocity - velocity) / effective_dt
        if (
            float(np.linalg.norm(actual_acceleration))
            > self.max_acceleration_m_s2 + self._TOLERANCE
        ):
            raise VelocityCommandShapeError("shaped command exceeds acceleration limit")
        if (
            float(np.linalg.norm(actual_acceleration - acceleration))
            > jerk_step + self._TOLERANCE
        ):
            raise VelocityCommandShapeError("shaped command exceeds jerk limit")

        self._velocity = next_velocity.copy()
        self._acceleration = actual_acceleration.copy()
        return next_velocity.copy()

    @classmethod
    def _finite_ned_vector(cls, value: Iterable[float], name: str) -> np.ndarray:
        try:
            vector = np.asarray(value, dtype=float)
        except (TypeError, ValueError) as exc:
            raise VelocityCommandShapeError(f"{name} must be a numeric NED vector") from exc
        if vector.shape != (3,):
            raise VelocityCommandShapeError(f"{name} must contain exactly three values")
        if not np.all(np.isfinite(vector)):
            raise VelocityCommandShapeError(f"{name} must contain only finite values")
        return vector

    @staticmethod
    def _positive_finite(value: float, name: str) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise VelocityCommandShapeError(f"{name} must be a positive finite number") from exc
        if not math.isfinite(numeric) or numeric <= 0.0:
            raise VelocityCommandShapeError(f"{name} must be a positive finite number")
        return numeric

    @staticmethod
    def _limit_norm(vector: np.ndarray, maximum: float) -> np.ndarray:
        norm = float(np.linalg.norm(vector))
        if norm <= maximum or norm == 0.0:
            return vector.copy()
        return vector * (maximum / norm)

    @classmethod
    def _move_towards(
        cls,
        current: np.ndarray,
        target: np.ndarray,
        max_delta: float,
    ) -> np.ndarray:
        delta = target - current
        delta_norm = float(np.linalg.norm(delta))
        if delta_norm <= max_delta or delta_norm <= cls._TOLERANCE:
            return target.copy()
        return current + delta * (max_delta / delta_norm)

    @staticmethod
    def _discrete_braking_distance(
        acceleration_magnitude: float,
        max_jerk_m_s3: float,
        dt_s: float,
    ) -> float:
        """Conservative path length while reducing acceleration to zero."""

        jerk_step = max_jerk_m_s3 * dt_s
        if acceleration_magnitude <= jerk_step:
            return 0.0
        positive_steps = int(math.ceil(acceleration_magnitude / jerk_step)) - 1
        acceleration_sum = (
            positive_steps * acceleration_magnitude
            - jerk_step * positive_steps * (positive_steps + 1) / 2.0
        )
        return max(0.0, acceleration_sum * dt_s)

    def _clip_speed(self, velocity: np.ndarray) -> np.ndarray:
        clipped = velocity.copy()
        horizontal_norm = float(np.linalg.norm(clipped[:2]))
        if horizontal_norm > self.max_horizontal_speed_m_s:
            clipped[:2] *= self.max_horizontal_speed_m_s / horizontal_norm
        clipped[2] = float(
            np.clip(
                clipped[2],
                -self.max_vertical_speed_m_s,
                self.max_vertical_speed_m_s,
            )
        )
        return clipped

    def _braking_endpoint(self, velocity: np.ndarray, acceleration: np.ndarray) -> np.ndarray:
        """Conservative velocity endpoint when jerk reduces acceleration to zero.

        The continuous triangular braking area is enlarged by a half maximum
        sample interval. This reserves room before saturation, including when
        the next loop interval differs. Braking stays on the segment between
        the current velocity and this endpoint, inside the convex speed limits.
        """
        return velocity + acceleration * (
            float(np.linalg.norm(acceleration)) / (2.0 * self.max_jerk_m_s3)
            + self.max_dt_s / 2.0
        )

    def _require_speed_within_envelope(self, velocity: np.ndarray, name: str) -> None:
        horizontal_norm = float(np.linalg.norm(velocity[:2]))
        if horizontal_norm > self.max_horizontal_speed_m_s + self._TOLERANCE:
            raise VelocityCommandShapeError(
                f"{name} exceeds max_horizontal_speed_m_s"
            )
        if abs(float(velocity[2])) > self.max_vertical_speed_m_s + self._TOLERANCE:
            raise VelocityCommandShapeError(
                f"{name} exceeds max_vertical_speed_m_s"
            )
