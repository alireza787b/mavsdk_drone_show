"""Bounded log publication with atomic replay and thread-safe SSE subscribers."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import threading
from typing import Literal
import uuid

# Level ordering for filtering
_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}


def _matches_filter(entry: dict, level: str | None = None, component: str | None = None,
                    source: str | None = None, drone_id: int | None = None) -> bool:
    """Check if a log entry matches the given filters."""
    if level and _LEVEL_ORDER.get(entry.get("level", ""), 0) < _LEVEL_ORDER.get(level, 0):
        return False
    if component and entry.get("component") != component:
        return False
    if source and entry.get("source") != source:
        return False
    if drone_id is not None and entry.get("drone_id") != drone_id:
        return False
    return True


@dataclass(frozen=True)
class LogStreamEvent:
    kind: Literal["entry", "status", "gap"]
    data: dict
    event_id: str | None = None


@dataclass(eq=False)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    wake: asyncio.Event
    filters: dict
    pending: deque = field(default_factory=deque)
    notified: bool = False
    closed: bool = False
    dropped_first: str | None = None
    dropped_last: str | None = None
    dropped_count: int = 0


class LogWatcher:
    """A process epoch, retained history and bounded subscriber delivery.

    Logger threads only touch locked deques. Coalesced wakeups execute on the
    subscribing loop, never touching an asyncio.Queue from a logger thread.
    Repeated message text is never deduplicated.
    """

    def __init__(self, max_buffer: int = 100, *, max_pending: int = 200):
        if type(max_buffer) is not int or not 0 <= max_buffer <= 100000:
            raise ValueError("max_buffer must be between 0 and 100000")
        if type(max_pending) is not int or not 1 <= max_pending <= 100000:
            raise ValueError("max_pending must be between 1 and 100000")
        self._buffer: deque = deque(maxlen=max_buffer)  # Legacy dict indexing.
        self._retained: deque = deque(maxlen=max_buffer)
        self._subscribers: list[_Subscriber] = []
        self._max_pending = max_pending
        self._lock = threading.Lock()
        self.epoch = uuid.uuid4().hex
        self._sequence = 0

    def _status_locked(self) -> dict:
        return {
            "state": "connected", "epoch": self.epoch,
            "coverage": "retained_buffer" if self._buffer.maxlen else "live_only",
            "history_complete": False, "retained_count": len(self._retained),
            "retained_from_id": self._retained[0].event_id if self._retained else None,
            "retained_to_id": self._retained[-1].event_id if self._retained else None,
            "latest_event_id": f"{self.epoch}:{self._sequence}",
        }

    def stream_status(self) -> dict:
        """Stream coverage evidence, never an aircraft health assertion."""
        with self._lock:
            return self._status_locked()

    def _gap(self, reason, first=None, last=None, count=None):
        return LogStreamEvent("gap", {
            "reason": reason, "epoch": self.epoch, "coverage": "partial",
            "history_complete": False, "from_event_id": first,
            "to_event_id": last, "lost_count": count,
        })

    def _wake_subscriber(self, subscriber):
        if not subscriber.closed:
            subscriber.wake.set()  # Runs on this subscriber's event loop.

    def publish(self, log_entry: dict) -> None:
        if not isinstance(log_entry, dict):
            raise ValueError("log entry must be an object")
        entry = dict(log_entry)
        notifications = []
        with self._lock:
            self._sequence += 1
            event = LogStreamEvent("entry", entry, f"{self.epoch}:{self._sequence}")
            self._buffer.append(entry)
            self._retained.append(event)
            for subscriber in self._subscribers:
                if subscriber.closed or not _matches_filter(entry, **subscriber.filters):
                    continue
                if len(subscriber.pending) >= self._max_pending:
                    dropped = subscriber.pending.popleft()
                    subscriber.dropped_first = subscriber.dropped_first or dropped.event_id
                    subscriber.dropped_last = dropped.event_id
                    subscriber.dropped_count += 1
                subscriber.pending.append(event)
                if not subscriber.notified:
                    subscriber.notified = True
                    notifications.append(subscriber)
        for subscriber in notifications:
            try:
                subscriber.loop.call_soon_threadsafe(self._wake_subscriber, subscriber)
            except RuntimeError:
                with self._lock:
                    subscriber.closed = True
                    if subscriber in self._subscribers:
                        self._subscribers.remove(subscriber)

    async def subscribe_events(self, level=None, component=None, source=None, drone_id=None,
                               *, last_event_id: str | None = None):
        """Yield typed replay/status/gap events from one atomic subscription edge."""
        subscriber = _Subscriber(asyncio.get_running_loop(), asyncio.Event(), {
            "level": level, "component": component, "source": source, "drone_id": drone_id,
        })
        gap = None
        with self._lock:
            buffered = list(self._retained)
            start_after = 0
            if last_event_id:
                try:
                    epoch, raw_sequence = last_event_id.rsplit(":", 1)
                    sequence = int(raw_sequence)
                    if not epoch or sequence < 0 or str(sequence) != raw_sequence:
                        raise ValueError("invalid cursor")
                except (ValueError, AttributeError):
                    gap = self._gap("invalid_cursor")
                else:
                    if epoch != self.epoch:
                        gap = self._gap("stream_restarted")
                    elif sequence > self._sequence:
                        gap = self._gap("cursor_ahead")
                    else:
                        start_after = sequence
                        first_retained = self._sequence - len(buffered) + 1
                        if sequence < first_retained - 1:
                            gap = self._gap("retention", f"{self.epoch}:{sequence+1}",
                                            f"{self.epoch}:{first_retained-1}", first_retained-sequence-1)
            buffered = [event for event in buffered
                        if int(event.event_id.rsplit(":", 1)[1]) > start_after
                        and _matches_filter(event.data, **subscriber.filters)]
            status = self._status_locked()
            status["replayed_count"] = len(buffered)
            # Snapshot and registration share this lock; later publications are
            # only live events, never also part of this replay snapshot.
            self._subscribers.append(subscriber)
        try:
            yield LogStreamEvent("status", status)
            if gap:
                yield gap
            for event in buffered:
                yield event
            while True:
                with self._lock:
                    subscriber.wake.clear()
                    subscriber.notified = False
                    pending = list(subscriber.pending)
                    subscriber.pending.clear()
                    pending_gap = None
                    if subscriber.dropped_count:
                        pending_gap = self._gap("slow_subscriber", subscriber.dropped_first,
                                                subscriber.dropped_last, subscriber.dropped_count)
                        subscriber.dropped_first = subscriber.dropped_last = None
                        subscriber.dropped_count = 0
                if pending_gap:
                    yield pending_gap
                for event in pending:
                    yield event
                if not pending:
                    await subscriber.wake.wait()
        finally:
            with self._lock:
                subscriber.closed = True
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)

    async def subscribe(self, level=None, component=None, source=None, drone_id=None):
        """Legacy interface: only plain log dictionaries, not control events."""
        events = self.subscribe_events(level, component, source, drone_id)
        try:
            async for event in events:
                if event.kind == "entry":
                    yield event.data
        finally:
            await events.aclose()


# Global watcher instance — shared across the process
_watcher = LogWatcher()


def get_watcher() -> LogWatcher:
    """Get the global LogWatcher instance."""
    return _watcher
