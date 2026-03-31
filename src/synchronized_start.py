"""Shared helpers for evaluating synchronized mission start timing."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Optional


@dataclass(frozen=True)
class SynchronizedStartDecision:
    effective_start_time: float
    wait_seconds: float
    late_by_seconds: float
    should_wait: bool
    should_abort: bool
    reason: str


def resolve_requested_start_time(
    requested_start_time: Optional[float],
    *,
    logger: logging.Logger | None = None,
) -> Optional[float]:
    """Normalize external start-time input before mission startup work begins."""
    if requested_start_time in (None, "", 0, "0"):
        if logger is not None:
            logger.info(
                "No synchronized start time provided. Immediate launch will anchor at the local startup gate."
            )
        return None

    try:
        normalized = float(requested_start_time)
    except (TypeError, ValueError):
        if logger is not None:
            logger.warning(
                "Invalid synchronized start time provided. Immediate launch will anchor at the local startup gate."
            )
        return None

    if normalized <= 0:
        if logger is not None:
            logger.info(
                "Immediate synchronized launch requested. Start time will anchor at the local startup gate."
            )
        return None

    if logger is not None:
        logger.info("Synchronized start time provided: %s.", time.ctime(normalized))
    return normalized


def evaluate_synchronized_start(
    synchronized_start_time: Optional[float],
    *,
    late_tolerance_sec: float = 0.0,
    now: Optional[float] = None,
) -> SynchronizedStartDecision:
    """Resolve whether a synchronized mission should wait, proceed, or abort.

    `synchronized_start_time` is expected to be an epoch-second timestamp.
    A value of `None`, `0`, or a negative number means "start immediately".
    """
    resolved_now = float(time.time() if now is None else now)
    tolerance = max(0.0, float(late_tolerance_sec))

    if synchronized_start_time is None:
        return SynchronizedStartDecision(
            effective_start_time=resolved_now,
            wait_seconds=0.0,
            late_by_seconds=0.0,
            should_wait=False,
            should_abort=False,
            reason="No start_time provided; using now.",
        )

    try:
        requested_start_time = float(synchronized_start_time)
    except (TypeError, ValueError):
        return SynchronizedStartDecision(
            effective_start_time=resolved_now,
            wait_seconds=0.0,
            late_by_seconds=0.0,
            should_wait=False,
            should_abort=False,
            reason="Invalid start_time provided; using now.",
        )

    if requested_start_time <= 0:
        return SynchronizedStartDecision(
            effective_start_time=resolved_now,
            wait_seconds=0.0,
            late_by_seconds=0.0,
            should_wait=False,
            should_abort=False,
            reason="Immediate execution requested.",
        )

    if requested_start_time > resolved_now:
        wait_seconds = requested_start_time - resolved_now
        return SynchronizedStartDecision(
            effective_start_time=requested_start_time,
            wait_seconds=wait_seconds,
            late_by_seconds=0.0,
            should_wait=True,
            should_abort=False,
            reason=f"Waiting {wait_seconds:.2f}s until synchronized start time.",
        )

    late_by_seconds = resolved_now - requested_start_time
    if late_by_seconds > tolerance:
        return SynchronizedStartDecision(
            effective_start_time=requested_start_time,
            wait_seconds=0.0,
            late_by_seconds=late_by_seconds,
            should_wait=False,
            should_abort=True,
            reason=(
                f"Start time was {late_by_seconds:.2f}s ago, exceeding the "
                f"{tolerance:.2f}s late-start tolerance."
            ),
        )

    return SynchronizedStartDecision(
        effective_start_time=requested_start_time,
        wait_seconds=0.0,
        late_by_seconds=late_by_seconds,
        should_wait=False,
        should_abort=False,
        reason=(
            f"Start time was {late_by_seconds:.2f}s ago; continuing within the "
            f"{tolerance:.2f}s late-start tolerance."
        ),
    )
