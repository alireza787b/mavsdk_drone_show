"""Installed assignment revisions for telemetry readers, never acquisition on read."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class AssignmentRevision:
    # Canonical JSON is immutable, detached from configuration/producer objects.
    payload: str
    revision: int
    installed_monotonic: float


class SwarmAssignmentCache:
    """Keep saved desired state separate from short-lived runtime ownership.

    Acquisition workers install snapshots. Readers get detached dictionaries and
    cannot mutate either revision. A stopped runtime reader cannot freeze a live
    assignment indefinitely; no telemetry or flight timestamp is manufactured.
    """

    def __init__(self, saved, *, runtime_cache_ttl=1.0, clock=time.monotonic):
        self._lock = threading.Lock()
        self._clock = clock
        self._runtime_cache_ttl = runtime_cache_ttl
        self._saved = AssignmentRevision(self._encode(saved), 0, clock())
        self._runtime = None

    @staticmethod
    def _encode(value):
        return json.dumps(value if isinstance(value, dict) else {}, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)

    def install_saved(self, value):
        encoded = self._encode(value)
        with self._lock:
            if encoded == self._saved.payload:
                return False
            self._saved = AssignmentRevision(encoded, self._saved.revision + 1, self._clock())
            return True

    def install_runtime(self, value):
        encoded = self._encode(value) if value else None
        with self._lock:
            if encoded is None:
                self._runtime = None
                return
            previous = self._runtime
            revision = (previous.revision if previous and previous.payload == encoded
                        else (previous.revision + 1 if previous else 1))
            self._runtime = AssignmentRevision(encoded, revision, self._clock())

    def snapshot(self):
        with self._lock:
            revision = self._saved
            if self._runtime is not None:
                age = self._clock() - self._runtime.installed_monotonic
                if 0 <= age <= self._runtime_cache_ttl:
                    revision = self._runtime
        return json.loads(revision.payload)

    @property
    def saved_revision(self):
        with self._lock:
            return self._saved.revision
