"""Stateful formation-capture and tracking envelopes for Smart Swarm.

The guard owns *whether* formation tracking may produce a non-zero command.
Velocity shaping remains a separate concern.  Keeping those responsibilities
separate makes a bad initial layout, a large telemetry jump, or sustained
tracking divergence stop motion without hiding the underlying evidence.
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
    """Require safe capture geometry and reject implausible target changes."""

    def __init__(
        self,
        *,
        capture_horizontal_m: float,
        capture_vertical_m: float,
        capture_stable_sec: float,
        tracking_horizontal_m: float,
        tracking_vertical_m: float,
        target_step_horizontal_m: float,
        target_step_vertical_m: float,
    ) -> None:
        values = {
            "capture_horizontal_m": capture_horizontal_m,
            "capture_vertical_m": capture_vertical_m,
            "capture_stable_sec": capture_stable_sec,
            "tracking_horizontal_m": tracking_horizontal_m,
            "tracking_vertical_m": tracking_vertical_m,
            "target_step_horizontal_m": target_step_horizontal_m,
            "target_step_vertical_m": target_step_vertical_m,
        }
        normalized = {name: float(value) for name, value in values.items()}
        if not all(math.isfinite(value) and value > 0 for value in normalized.values()):
            raise ValueError("formation guard limits must be finite and greater than zero")
        if normalized["tracking_horizontal_m"] < normalized["capture_horizontal_m"]:
            raise ValueError("tracking horizontal envelope must include the capture envelope")
        if normalized["tracking_vertical_m"] < normalized["capture_vertical_m"]:
            raise ValueError("tracking vertical envelope must include the capture envelope")

        self.capture_horizontal_m = normalized["capture_horizontal_m"]
        self.capture_vertical_m = normalized["capture_vertical_m"]
        self.capture_stable_sec = normalized["capture_stable_sec"]
        self.tracking_horizontal_m = normalized["tracking_horizontal_m"]
        self.tracking_vertical_m = normalized["tracking_vertical_m"]
        self.target_step_horizontal_m = normalized["target_step_horizontal_m"]
        self.target_step_vertical_m = normalized["target_step_vertical_m"]
        self.reset()

    def reset(self) -> None:
        """Require a new stable capture after startup or reconfiguration."""
        self._captured = False
        self._capture_started_at: float | None = None
        self._last_target: tuple[float, float, float] | None = None

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
        """Return whether the current target is safe to track.

        A rejected target resets capture.  Tracking can resume only after the
        aircraft is again inside the smaller capture envelope for the complete
        stability dwell.  The caller should keep streaming a shaped zero
        velocity while ``tracking_allowed`` is false.
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

        if self._captured and self._last_target is not None:
            step_n = desired[0] - self._last_target[0]
            step_e = desired[1] - self._last_target[1]
            step_d = desired[2] - self._last_target[2]
            horizontal_step = math.hypot(step_n, step_e)
            vertical_step = abs(step_d)
            if (
                horizontal_step > self.target_step_horizontal_m
                or vertical_step > self.target_step_vertical_m
            ):
                self.reset()
                return FormationGuardDecision(
                    False,
                    "target_jump",
                    (
                        "Formation target changed implausibly between samples "
                        f"(horizontal {horizontal_step:.2f}m, vertical {vertical_step:.2f}m)."
                    ),
                    horizontal_error,
                    vertical_error,
                )

        if self._captured and (
            horizontal_error > self.tracking_horizontal_m
            or vertical_error > self.tracking_vertical_m
        ):
            self.reset()
            return FormationGuardDecision(
                False,
                "tracking_diverged",
                (
                    "Formation tracking left the safe envelope "
                    f"(horizontal {horizontal_error:.2f}m, vertical {vertical_error:.2f}m)."
                ),
                horizontal_error,
                vertical_error,
            )

        if not self._captured:
            inside_capture = (
                horizontal_error <= self.capture_horizontal_m
                and vertical_error <= self.capture_vertical_m
            )
            if not inside_capture:
                self._capture_started_at = None
                return FormationGuardDecision(
                    False,
                    "waiting_geometry",
                    (
                        "Follower is outside the formation capture envelope "
                        f"(horizontal {horizontal_error:.2f}m, vertical {vertical_error:.2f}m)."
                    ),
                    horizontal_error,
                    vertical_error,
                )

            if self._capture_started_at is None or now < self._capture_started_at:
                self._capture_started_at = now

            dwell = max(0.0, now - self._capture_started_at)
            if dwell < self.capture_stable_sec:
                return FormationGuardDecision(
                    False,
                    "settling",
                    (
                        "Formation geometry is inside the capture envelope and settling "
                        f"({dwell:.2f}/{self.capture_stable_sec:.2f}s)."
                    ),
                    horizontal_error,
                    vertical_error,
                )
            self._captured = True

        self._last_target = desired
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
