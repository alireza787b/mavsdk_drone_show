"""Stateful geometry admission for Smart Swarm.

Geometry admission is deliberately not a small-distance gate.  A follower may
smoothly acquire a valid formation from a large separation; the motion
controller owns the speed/acceleration envelope.  This module only rejects
non-finite data. Capture thresholds describe progress, not permission to move.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class FormationGuardDecision:
    """One deterministic formation-admission decision."""

    tracking_allowed: bool
    status: str
    detail: str
    horizontal_error_m: float | None = None
    vertical_error_m: float | None = None


def _ned_vector(values: Sequence[float], label: str) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError(f"{label} must contain exactly three NED values")
    vector = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in vector):
        raise ValueError(f"{label} contains a non-finite NED value")
    return vector


class FormationGuard:
    """Describe formation acquisition and settling without a distance gate."""

    def __init__(
        self,
        *,
        capture_horizontal_m: float,
        capture_vertical_m: float,
        capture_stable_sec: float,
        tracking_horizontal_m: float,
        tracking_vertical_m: float,
        target_step_horizontal_m: float | None = None,
        target_step_vertical_m: float | None = None,
        acquisition_horizontal_m: float | None = None,
        acquisition_vertical_m: float | None = None,
    ) -> None:
        values = {
            "capture_horizontal_m": capture_horizontal_m,
            "capture_vertical_m": capture_vertical_m,
            "capture_stable_sec": capture_stable_sec,
            "tracking_horizontal_m": tracking_horizontal_m,
            "tracking_vertical_m": tracking_vertical_m,
        }
        normalized = {name: float(value) for name, value in values.items()}
        if not all(math.isfinite(value) and value > 0 for value in normalized.values()):
            raise ValueError("formation guard limits must be finite and greater than zero")

        self.capture_horizontal_m = normalized["capture_horizontal_m"]
        self.capture_vertical_m = normalized["capture_vertical_m"]
        self.capture_stable_sec = normalized["capture_stable_sec"]
        self.tracking_horizontal_m = normalized["tracking_horizontal_m"]
        self.tracking_vertical_m = normalized["tracking_vertical_m"]
        # Legacy step/acquisition arguments remain accepted for older callers only.
        # Neither argument can reject a finite target or change motion policy.
        self.reset()

    def reset(self) -> None:
        """Return to acquisition without forcing a zero command."""
        self._captured = False
        self._capture_started_at: float | None = None

    @property
    def captured(self) -> bool:
        return self._captured

    def evaluate(
        self,
        desired_position_ned: Sequence[float],
        own_position_ned: Sequence[float],
        *,
        now_s: float,
    ) -> FormationGuardDecision:
        """Return whether the current geometry may be controlled smoothly.

        The old implementation treated the small capture envelope as a hard
        admission gate.  That left a valid but distant follower permanently
        stationary.  ``tracking_allowed`` now means that the geometry is
        numerically valid; ``status``
        distinguishes acquisition from settled tracking for the operator.
        """
        try:
            desired = _ned_vector(desired_position_ned, "desired position")
            own = _ned_vector(own_position_ned, "own position")
            now = float(now_s)
            if not math.isfinite(now):
                raise ValueError("evaluation time is non-finite")
        except (TypeError, ValueError) as exc:
            self.reset()
            return FormationGuardDecision(False, "invalid", str(exc))

        error_n = desired[0] - own[0]
        error_e = desired[1] - own[1]
        error_d = desired[2] - own[2]
        horizontal_error = math.hypot(error_n, error_e)
        vertical_error = abs(error_d)

        # Target samples can legitimately move by more than one loop period
        # during a leader jog.  The controller filters and shapes that change;
        # rejecting it here would recreate the hard-stop bug.

        if not math.isfinite(horizontal_error) or not math.isfinite(vertical_error):
            self.reset()
            return FormationGuardDecision(
                False,
                "invalid",
                "Formation error is non-finite.",
                horizontal_error,
                vertical_error,
            )

        if self._captured and (
            horizontal_error > self.tracking_horizontal_m
            or vertical_error > self.tracking_vertical_m
        ):
            self._captured = False
            self._capture_started_at = None

        if not self._captured:
            inside_capture = (
                horizontal_error <= self.capture_horizontal_m
                and vertical_error <= self.capture_vertical_m
            )
            if not inside_capture:
                self._capture_started_at = None
                return FormationGuardDecision(
                    True,
                    "acquiring",
                    (
                        "Follower is smoothly acquiring the formation "
                        f"(horizontal error {horizontal_error:.2f}m, vertical error {vertical_error:.2f}m)."
                    ),
                    horizontal_error,
                    vertical_error,
                )

            if self._capture_started_at is None or now < self._capture_started_at:
                self._capture_started_at = now

            dwell = max(0.0, now - self._capture_started_at)
            if dwell < self.capture_stable_sec:
                return FormationGuardDecision(
                    True,
                    "settling",
                    (
                        "Formation geometry is inside the capture envelope and settling "
                        f"({dwell:.2f}/{self.capture_stable_sec:.2f}s)."
                    ),
                    horizontal_error,
                    vertical_error,
                )
            self._captured = True

        return FormationGuardDecision(
            True,
            "tracking",
            (
                "Formation capture is stable "
                f"(horizontal {horizontal_error:.2f}m, vertical {vertical_error:.2f}m)."
            ),
            horizontal_error,
            vertical_error,
        )
