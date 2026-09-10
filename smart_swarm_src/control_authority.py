"""One latch for PX4 takeover; deliberately not a leader-election policy."""
from __future__ import annotations

import time


def mode_name(value):
    return str(getattr(value, "name", value)).upper().rsplit(".", 1)[-1]


class ControlAuthority:
    def __init__(self):
        self.mode = None
        self.mode_at = 0.0
        self.armed = None
        self.landed = None
        self.follower_owned = False
        self.internal_hold = False
        self.pending_mode = None
        self.pending_until = 0.0
        self.takeover_reason = None

    def expect(self, mode, *, now=None):
        if self.takeover_reason:
            return False
        self.pending_mode = mode
        self.pending_until = (time.monotonic() if now is None else now) + 3.0
        if mode == "HOLD":
            self.internal_hold = True
        return True

    def has_fresh_mode(self, *, now=None):
        now = time.monotonic() if now is None else now
        return self.mode is not None and 0 <= now - self.mode_at <= 2.5

    def never_requested_follower_control(self):
        return not self.follower_owned and self.pending_mode != "OFFBOARD"

    def update_mode(self, value, *, leader, now=None):
        now = time.monotonic() if now is None else now
        self.mode, self.mode_at = mode_name(value), now
        if self.mode in {"RETURN_TO_LAUNCH", "RETURN", "RTL", "LAND"}:
            self.takeover_reason = f"PX4 {self.mode}"
        elif leader:
            # The leader may be flown by RC, QGC, or another mission. Switching
            # Position/Hold/Mission on the leader is NOT follower takeover.
            self.follower_owned = False
        elif self.mode == "OFFBOARD":
            self.follower_owned = True
            if self.pending_mode == "OFFBOARD":
                self.pending_mode = None
                self.internal_hold = False
        elif self.mode == "HOLD" and self.internal_hold:
            if self.pending_mode == "HOLD":
                self.pending_mode = None
        elif self.follower_owned:
            self.takeover_reason = f"Pilot/autopilot changed follower mode to {self.mode}"
        return self.takeover_reason

    def update_armed(self, armed):
        self.armed = bool(armed)
        if not self.armed:
            self.takeover_reason = "PX4 disarmed"

    def update_landed(self, landed):
        self.landed = mode_name(landed)
        if self.landed in {"ON_GROUND", "LANDING"}:
            self.takeover_reason = f"PX4 {self.landed}"

    def owns_fresh_offboard(self, *, now=None):
        now = time.monotonic() if now is None else now
        return (not self.takeover_reason and self.mode == "OFFBOARD"
                and self.has_fresh_mode(now=now) and self.armed is True)
