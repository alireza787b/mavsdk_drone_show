"""Bounded reacquisition after protective Hold; never edits formation roles."""
from __future__ import annotations

import math


class LeaderRecoveryWindow:
    def __init__(self, *, started_at: float, wait_sec: float, stable_sec: float):
        if not all(math.isfinite(v) for v in (started_at, wait_sec, stable_sec)):
            raise ValueError("Leader recovery timing must be finite")
        if not 0 < stable_sec < wait_sec:
            raise ValueError("Leader recovery requires 0 < stable time < wait time")
        self.deadline = started_at + wait_sec
        self.stable_sec = stable_sec
        self.fresh_since = None
        self.terminal = None

    def observe(self, *, now: float, ready: bool, cancelled: bool = False) -> str:
        # Pilot takeover wins even if fresh data arrives on the same iteration.
        if cancelled:
            self.terminal = "cancelled"
        if self.terminal:
            return self.terminal
        if not math.isfinite(now) or now >= self.deadline:
            self.terminal = "expired"
        elif not ready:
            self.fresh_since = None
        elif self.fresh_since is None:
            self.fresh_since = now
        elif now - self.fresh_since >= self.stable_sec:
            self.terminal = "recovered"
        return self.terminal or "waiting"
