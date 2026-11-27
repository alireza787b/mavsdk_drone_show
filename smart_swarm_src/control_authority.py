"""One latch for PX4 takeover; deliberately not a leader-election policy."""
from __future__ import annotations

import asyncio
import time


MODE_OBSERVATION_TIMEOUT_SEC = 2.5
ENTRY_TIMEOUT_SEC = 3.0

OFFBOARD_ENTRY_MODES = frozenset({
    "HOLD", "MISSION", "FOLLOW_ME", "MANUAL", "ALTCTL", "POSCTL",
    "ACRO", "STABILIZED", "RATTITUDE",
})


def mode_name(value):
    return str(getattr(value, "name", value)).upper().rsplit(".", 1)[-1]


class ControlAuthority:
    def __init__(self, stop_setpoint_sender=None):
        self.mode = None
        self.mode_at = 0.0
        self.mode_changes = 0
        self.armed = None
        self.landed = None
        self.follower_owned = False
        self.internal_hold = False
        self.pending_mode = None
        self.pending_until = 0.0
        self._entry_origin = None
        self._entry_accepted = False
        self._entry_observed = False
        self.takeover_reason = None
        self.handoff_unconfirmed = False
        self.releasing = False
        self._stop_setpoint_sender = stop_setpoint_sender
        self._mode_updated = asyncio.Event()
        self.setpoint_lock = asyncio.Lock()

    def relinquish_unconfirmed(self, reason):
        if not self.takeover_reason:
            had_sender = self.follower_owned or self.pending_mode == "OFFBOARD"
            self.pending_mode = None
            self.follower_owned = self.internal_hold = False
            self.handoff_unconfirmed = True
            self.takeover_reason = reason
            if self._stop_setpoint_sender and had_sender:
                self._stop_setpoint_sender()
        self._mode_updated.set()

    async def next_mode(self, timeout=MODE_OBSERVATION_TIMEOUT_SEC):
        """Authorize a mode change only from a report received after this decision."""
        if not self.takeover_reason:
            self._mode_updated.clear()
            try:
                await asyncio.wait_for(self._mode_updated.wait(), timeout)
            except asyncio.TimeoutError:
                self.relinquish_unconfirmed("PX4 mode observation timed out")
        return not self.takeover_reason

    async def watch_owned_mode(self):
        """End the owned setpoint stream when telemetry goes silent during tracking."""
        while not self.takeover_reason:
            remaining = MODE_OBSERVATION_TIMEOUT_SEC
            if self.follower_owned or self.pending_mode == "OFFBOARD":
                remaining -= time.monotonic() - self.mode_at
                if remaining <= 0:
                    self.relinquish_unconfirmed("PX4 mode observation expired")
                    return
            await asyncio.sleep(remaining)

    def expect(self, mode, *, now=None):
        if self.takeover_reason or (mode == "OFFBOARD" and self.pending_mode is not None):
            return False
        self.pending_mode = mode
        self.pending_until = (time.monotonic() if now is None else now) + ENTRY_TIMEOUT_SEC
        if mode == "OFFBOARD":
            self._entry_origin = self.mode
            self._entry_accepted = self._entry_observed = False
            self.follower_owned = False
        if mode == "HOLD":
            self.internal_hold = True
        return True

    def accept_offboard_request(self, *, now=None):
        now = time.monotonic() if now is None else now
        if self.takeover_reason or self.pending_mode != "OFFBOARD":
            return False
        if now >= self.pending_until:
            self.relinquish_unconfirmed("PX4 Offboard acceptance was late")
            return False
        self._entry_accepted = True
        self._claim_confirmed_entry()
        return True

    def _claim_confirmed_entry(self):
        if self._entry_accepted and self._entry_observed:
            self.follower_owned = True
            self.pending_mode = None
            self.internal_hold = False

    def preserve_external(self, reason):
        pending_start = self.pending_mode == "OFFBOARD"
        self.pending_mode = None
        self.follower_owned = self.internal_hold = self.handoff_unconfirmed = False
        self.takeover_reason = reason
        self._mode_updated.set()
        if pending_start and self._stop_setpoint_sender:
            self._stop_setpoint_sender()

    def has_fresh_mode(self, *, now=None):
        now = time.monotonic() if now is None else now
        return self.mode is not None and 0 <= now - self.mode_at <= MODE_OBSERVATION_TIMEOUT_SEC

    def can_request_offboard(self, *, now=None):
        return (not self.takeover_reason and self.has_fresh_mode(now=now)
                and self.armed is True and self.mode in OFFBOARD_ENTRY_MODES
                and (not self.follower_owned or self.internal_hold and self.mode == "HOLD"))

    def never_requested_follower_control(self):
        return not self.follower_owned and self.pending_mode != "OFFBOARD"

    def update_mode(self, value, *, leader, now=None):
        now = time.monotonic() if now is None else now
        observed = mode_name(value)
        if self.mode != observed:
            self.mode_changes += 1
        self.mode, self.mode_at = observed, now
        self._mode_updated.set()
        if self.mode == "UNKNOWN" and (self.follower_owned or self.pending_mode == "OFFBOARD"):
            self.relinquish_unconfirmed("PX4 flight mode is unknown")
        elif self.mode in {"RETURN_TO_LAUNCH", "RETURN", "RTL", "LAND"}:
            self.preserve_external(f"PX4 {self.mode}")
        elif self.takeover_reason:
            return self.takeover_reason
        elif self.pending_mode and now >= self.pending_until:
            self.relinquish_unconfirmed("PX4 mode request readback expired")
        elif leader:
            # The leader may be flown by RC, QGC, or another mission. Switching
            # Position/Hold/Mission on the leader is NOT follower takeover.
            self.follower_owned = False
        elif self.mode == "OFFBOARD":
            if self.pending_mode == "OFFBOARD":
                self._entry_observed = True
                self._claim_confirmed_entry()
            elif self.internal_hold and self.pending_mode != "HOLD":
                self.preserve_external("PX4 entered Offboard outside the follower session")
        elif self.pending_mode == "OFFBOARD" and (self._entry_observed or self.mode != self._entry_origin):
            self.preserve_external(f"PX4 changed to {self.mode} during follower entry")
        elif self.mode == "HOLD" and self.internal_hold:
            if self.pending_mode == "HOLD":
                self.pending_mode = None
        elif self.follower_owned:
            self.preserve_external(f"Pilot/autopilot changed follower mode to {self.mode}")
        return self.takeover_reason

    def update_armed(self, armed):
        self.armed = bool(armed)
        if not self.armed:
            self.preserve_external("PX4 disarmed")

    def update_landed(self, landed):
        self.landed = mode_name(landed)
        if self.landed in {"ON_GROUND", "LANDING"}:
            self.preserve_external(f"PX4 {self.landed}")

    def owns_fresh_offboard(self, *, now=None):
        now = time.monotonic() if now is None else now
        return (not self.takeover_reason and self.follower_owned and not self.internal_hold
                and self.mode == "OFFBOARD"
                and self.has_fresh_mode(now=now) and self.armed is True)
