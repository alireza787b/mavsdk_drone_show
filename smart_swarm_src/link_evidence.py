"""Passive follower-link evidence. Only the writer thread calls logging handlers."""
from __future__ import annotations

import math
import queue
import threading
import time

from mds_logging import get_logger
from src.smart_swarm_contract import LINK_SUMMARY_INTERVAL_SEC


def _age_ms(now, stamp):
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 < stamp <= now:
        return None
    return round((now - stamp) * 1000)


class LinkEvidence:
    """One session, one current leader, fixed memory regardless of sample rate."""

    def __init__(self, session_id, *, logger=None, queue_size=64):
        self.session_id = session_id
        self._log = logger or get_logger("smart_swarm.link")
        self._queue = queue.Queue(maxsize=queue_size)
        self._closed = threading.Event()
        self._dropped = 0
        self._write_failures = 0
        self._last_dropped = None
        self._sequence = 0
        self.reset_target()
        self._thread = threading.Thread(target=self._write, name="swarm-link-log", daemon=True)
        self._thread.start()

    def reset_target(self):
        self.accepted = self.rejected = self.duplicate = self.fallback_attempts = 0
        self.last_rejection = self.last_receipt = self.max_gap_ms = None
        self.last_transport_error = None
        self.max_setpoint_send_ms = self.max_setpoint_gap_ms = self.last_setpoint = None
        self.setpoint_count = 0
        self.last_summary_time = None
        self.latest = None

    def sample_accepted(self, received):
        gap = _age_ms(received, self.last_receipt)
        if gap is not None:
            self.max_gap_ms = max(gap, self.max_gap_ms or 0)
        self.last_receipt = received
        self.accepted += 1

    def sample_rejected(self, reason):
        self.rejected += 1
        self.last_rejection = reason

    def transport_event(self, reason):
        if reason == "fallback_attempt":
            self.fallback_attempts += 1
        elif reason == "malformed_sample":
            self.sample_rejected(reason)
        else:
            self.last_transport_error = reason

    def setpoint_sent(self, duration):
        now = time.monotonic()
        gap = _age_ms(now, self.last_setpoint)
        if gap is not None:
            self.max_setpoint_gap_ms = max(gap, self.max_setpoint_gap_ms or 0)
        self.last_setpoint = now
        self.setpoint_count += 1
        self.max_setpoint_send_ms = max(self.max_setpoint_send_ms or 0, round(duration * 1000))

    def fields(self, *, hw_id, leader_hw_id, leader, own, source_limit, hard_limit):
        now = time.monotonic()
        stamp = time.time_ns() // 1_000_000
        position_age = _age_ms(now, leader.get("update_time"))
        heading_age = _age_ms(now, leader.get("attitude_update_time"))
        state = "missing"
        if position_age is not None and heading_age is not None:
            age_ms = max(position_age, heading_age)
            if age_ms <= source_limit * 1000:
                state = "fresh"
            elif age_ms <= hard_limit * 1000:
                state = "delayed"
        silence = _age_ms(now, self.last_receipt)
        return dict(
            schema_version=1, session_id=self.session_id, hw_id=str(hw_id),
            leader_hw_id=str(leader_hw_id) if leader_hw_id else None,
            observed_at_ms=stamp, valid_until_ms=stamp + 2 * LINK_SUMMARY_INTERVAL_SEC * 1000,
            state=state, transport=leader.get("transport"),
            last_accepted_at_ms=leader.get("received_at_ms"),
            position_age_ms=position_age, heading_age_ms=heading_age,
            own_position_age_ms=_age_ms(now, own.get("updated_monotonic")),
            own_heading_age_ms=_age_ms(now, own.get("yaw_updated_monotonic")),
            accepted=self.accepted, rejected=self.rejected, duplicate=self.duplicate,
            fallback_attempts=self.fallback_attempts,
            max_gap_ms=max(self.max_gap_ms or 0, silence) if silence is not None else self.max_gap_ms,
            last_rejection=self.last_rejection, last_transport_error=self.last_transport_error,
            setpoint_count=self.setpoint_count, max_setpoint_gap_ms=self.max_setpoint_gap_ms,
            max_setpoint_send_ms=self.max_setpoint_send_ms, hard_stale_ms=round(hard_limit * 1000),
        )

    def summary(self, fields):
        now = time.monotonic()
        if self.last_summary_time is None or now - self.last_summary_time >= LINK_SUMMARY_INTERVAL_SEC:
            self.last_summary_time = now
            self.latest = fields()
            self.emit("link_summary", self.latest)
        return self.latest

    def emit(self, event, fields, **details):
        self._sequence += 1
        payload = {**fields, **details, "event": event, "event_sequence": self._sequence,
                   "dropped_before": self._dropped}
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            self._dropped += 1
            self._last_dropped = payload
        else:
            self._dropped = 0
            self._last_dropped = None

    def _write(self):
        while not self._closed.is_set() or not self._queue.empty():
            try:
                payload = self._queue.get(timeout=.1)
            except queue.Empty:
                continue
            self._write_record(payload)
        if self._last_dropped:
            self._write_record({**self._last_dropped, "event": "coverage_gap", "dropped": self._dropped})

    def _write_record(self, payload):
        payload["dropped_before"] += self._write_failures
        try:
            self._log.info("Smart Swarm %s", payload["event"],
                           extra={"mds_drone_id": payload["hw_id"], "mds_extra": payload})
        except Exception:
            # Report these missing records when a custom sink next accepts a write.
            self._write_failures = payload["dropped_before"] + 1
        else:
            self._write_failures = 0

    def close(self):
        self._closed.set()
        self._thread.join(timeout=0.25)
