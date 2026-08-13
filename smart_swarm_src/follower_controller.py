"""Pure, testable Smart Swarm follower motion controller.

This module owns the complete path from formation error to the command sent to
PX4.  The formation guard decides whether movement is allowed, the feedback
law produces a requested velocity, and the command shaper enforces continuity
from the first sample.  Network and MAVSDK concerns stay in ``smart_swarm.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np

from smart_swarm_src.formation_guard import FormationGuard, FormationGuardDecision
from smart_swarm_src.velocity_command_shaper import NedVelocityCommandShaper


def _finite_ned(values: Sequence[float], label: str) -> np.ndarray:
    try:
        vector = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a numeric NED vector") from exc
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError(f"{label} must contain exactly three finite NED values")
    return vector


def _normalize_yaw_deg(value: float) -> float:
    try:
        yaw = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("yaw must be finite") from exc
    if not math.isfinite(yaw):
        raise ValueError("yaw must be finite")
    return yaw % 360.0


def _clamp_confidence(value: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("motion confidence must be finite") from exc
    if not math.isfinite(confidence):
        raise ValueError("motion confidence must be finite")
    return min(1.0, max(0.0, confidence))


@dataclass(frozen=True)
class FollowerControlDecision:
    """One shaped follower command and its admission evidence."""

    velocity_ned: np.ndarray
    yaw_deg: float
    requested_velocity_ned: np.ndarray
    tracking_allowed: bool
    status: str
    detail: str
    confidence: float
    horizontal_error_m: float | None = None
    vertical_error_m: float | None = None


class FollowerMotionController:
    """Produce smooth NED/yaw commands for one follower."""

    def __init__(
        self,
        *,
        position_gain: float,
        velocity_gain: float,
        leader_velocity_feedforward: float,
        max_yaw_rate_deg_s: float,
        max_dt_s: float,
        seed_yaw_deg: float,
        formation_guard: FormationGuard,
        velocity_shaper: NedVelocityCommandShaper,
    ) -> None:
        self.position_gain = self._nonnegative(position_gain, "position_gain")
        self.velocity_gain = self._nonnegative(velocity_gain, "velocity_gain")
        self.leader_velocity_feedforward = self._nonnegative(
            leader_velocity_feedforward,
            "leader_velocity_feedforward",
        )
        self.max_yaw_rate_deg_s = self._positive(
            max_yaw_rate_deg_s,
            "max_yaw_rate_deg_s",
        )
        self.max_dt_s = self._positive(max_dt_s, "max_dt_s")
        self.formation_guard = formation_guard
        self.velocity_shaper = velocity_shaper
        self._yaw_deg = _normalize_yaw_deg(seed_yaw_deg)

    @staticmethod
    def _positive(value: float, label: str) -> float:
        numeric = float(value)
        if not math.isfinite(numeric) or numeric <= 0:
            raise ValueError(f"{label} must be finite and greater than zero")
        return numeric

    @staticmethod
    def _nonnegative(value: float, label: str) -> float:
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError(f"{label} must be finite and non-negative")
        return numeric

    @property
    def velocity_ned(self) -> np.ndarray:
        return self.velocity_shaper.velocity_ned

    @property
    def yaw_deg(self) -> float:
        return self._yaw_deg

    def require_new_capture(self) -> None:
        """Suspend formation motion without discarding command continuity."""
        self.formation_guard.reset()

    def reset_after_offboard_hold(self, *, seed_yaw_deg: float) -> None:
        """Reset to the exact zero setpoint used for a fresh Offboard entry."""
        self.formation_guard.reset()
        self.velocity_shaper.reset()
        self._yaw_deg = _normalize_yaw_deg(seed_yaw_deg)

    def suspend(self, *, dt_s: float, reason: str) -> FollowerControlDecision:
        """Smoothly approach zero velocity and retain the current yaw command."""
        self.formation_guard.reset()
        command = self.velocity_shaper.shape((0.0, 0.0, 0.0), dt_s)
        return FollowerControlDecision(
            velocity_ned=command,
            yaw_deg=self._yaw_deg,
            requested_velocity_ned=np.zeros(3, dtype=float),
            tracking_allowed=False,
            status="suspended",
            detail=reason,
            confidence=0.0,
        )

    def compute(
        self,
        *,
        desired_position_ned: Sequence[float],
        own_position_ned: Sequence[float],
        leader_velocity_ned: Sequence[float],
        own_velocity_ned: Sequence[float],
        target_yaw_deg: float,
        confidence: float,
        dt_s: float,
        now_s: float,
    ) -> FollowerControlDecision:
        desired_position = _finite_ned(desired_position_ned, "desired_position_ned")
        own_position = _finite_ned(own_position_ned, "own_position_ned")
        leader_velocity = _finite_ned(leader_velocity_ned, "leader_velocity_ned")
        own_velocity = _finite_ned(own_velocity_ned, "own_velocity_ned")
        target_yaw = _normalize_yaw_deg(target_yaw_deg)
        motion_confidence = _clamp_confidence(confidence)

        guard = self.formation_guard.evaluate(
            desired_position,
            own_position,
            now_s=now_s,
        )
        if guard.tracking_allowed:
            position_error = desired_position - own_position
            velocity_error = leader_velocity - own_velocity
            raw_request = (
                self.leader_velocity_feedforward * leader_velocity
                + self.position_gain * position_error
                + self.velocity_gain * velocity_error
            )
            requested = motion_confidence * raw_request
            yaw_request = target_yaw
        else:
            requested = np.zeros(3, dtype=float)
            yaw_request = self._yaw_deg

        command = self.velocity_shaper.shape(requested, dt_s)
        self._yaw_deg = self._shape_yaw(yaw_request, dt_s)
        return self._decision(command, requested, guard, motion_confidence)

    def _shape_yaw(self, target_yaw_deg: float, dt_s: float) -> float:
        dt = self._positive(dt_s, "dt_s")
        effective_dt = min(dt, self.max_dt_s)
        delta = (target_yaw_deg - self._yaw_deg + 180.0) % 360.0 - 180.0
        max_delta = self.max_yaw_rate_deg_s * effective_dt
        delta = min(max(delta, -max_delta), max_delta)
        return (self._yaw_deg + delta) % 360.0

    def _decision(
        self,
        command: np.ndarray,
        requested: np.ndarray,
        guard: FormationGuardDecision,
        confidence: float,
    ) -> FollowerControlDecision:
        status = guard.status
        detail = guard.detail
        if guard.tracking_allowed and confidence < 1.0:
            status = "tracking_degraded"
            detail = f"Leader motion confidence reduced to {confidence:.2f}."
        return FollowerControlDecision(
            velocity_ned=command,
            yaw_deg=self._yaw_deg,
            requested_velocity_ned=requested.copy(),
            tracking_allowed=guard.tracking_allowed,
            status=status,
            detail=detail,
            confidence=confidence,
            horizontal_error_m=guard.horizontal_error_m,
            vertical_error_m=guard.vertical_error_m,
        )
