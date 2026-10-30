"""Action-scoped native subscriptions with re-aged, connection-bound evidence.

Polling a snapshot never refreshes a receipt. The on-change connection stream
is watched continuously; heartbeat-derived armed receipts establish liveness.
"""
import asyncio
import time

from src.action_safety import (
    SafetyEvidenceTracker, SafetySnapshot, build_safety_field_evidence,
    vehicle_state_stream_specs, _sample_source_clocks,
)
from src.async_stream_utils import managed_async_stream


class ActionStateSampler:
    def __init__(self, drone, required_fields=("armed", "landed_state", "absolute_altitude_m")):
        self.drone = drone
        self.required_fields = tuple(required_fields)
        self.specs = {name: spec for name, spec in vehicle_state_stream_specs(drone).items()
            if name in self.required_fields}
        self.tracker = SafetyEvidenceTracker()
        self.values = {}
        self.tasks = []
        self.changed = asyncio.Event()
        self.interrupted = False
        self.boot_reset = False
        self.error = None
        self.warmed = False

    async def __aenter__(self):
        self.tasks = [asyncio.create_task(self._connection())]
        self.tasks.extend(asyncio.create_task(self._field(name, spec)) for name, spec in self.specs.items())
        return self

    async def __aexit__(self, *args):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []

    async def _connection(self):
        try:
            async with managed_async_stream(self.drone.core.connection_state) as stream:
                async for sample in stream:
                    live = getattr(sample, "is_connected", None)
                    if type(live) is not bool:
                        raise ValueError("Invalid connection state")
                    self.tracker.record_connection(live)
                    if not live:
                        self.interrupted = True
                    self.changed.set()
            self.error = "Native connection subscription ended"
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error = "Native connection subscription failed"
        finally:
            self.changed.set()

    async def _field(self, name, spec):
        try:
            async with managed_async_stream(spec.stream_factory) as stream:
                async for sample in stream:
                    # A sample received before connection is established cannot
                    # become authoritative by later observing a connection.
                    if self.tracker.connection_live is not True:
                        continue
                    source_time, boot_time = _sample_source_clocks(sample)
                    self.boot_reset |= self.tracker.record_source_boot_time(name, boot_time)
                    self.values[name] = (spec.normalize(sample), int(time.time()*1000), time.monotonic(), source_time, boot_time)
                    self.changed.set()
            self.error = f"Native {name} subscription ended"
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error = f"Native {name} subscription failed"
        finally:
            self.changed.set()

    def snapshot(self):
        now, mono = int(time.time()*1000), time.monotonic()
        fields = {}
        for name, spec in self.specs.items():
            item = self.values.get(name)
            fields[name] = build_safety_field_evidence(name=name, source=spec.source,
                value=item[0] if item else None, received_at_ms=item[1] if item else None,
                receipt_age_ms=int((mono-item[2])*1000) if item else None,
                source_timestamp_ms=item[3] if item else None,
                source_time_boot_ms=item[4] if item else None, now_ms=now)
        heartbeat = self.values.get("armed")
        connection = build_safety_field_evidence(name="connection",
            source="mavsdk.core.connection_state+mavsdk.telemetry.armed",
            value=self.tracker.connection_live, received_at_ms=heartbeat[1] if heartbeat else None,
            receipt_age_ms=int((mono-heartbeat[2])*1000) if heartbeat else None, now_ms=now)
        return SafetySnapshot(observed_at_ms=now, connection=connection, fields=fields,
            required_fields=self.required_fields, connection_interrupted=self.interrupted,
            source_boot_reset=self.boot_reset, observation_error=self.error)

    async def observe(self, *, timeout=3):
        """Warm up once; afterward return current evidence immediately, even stale."""
        if self.warmed:
            return self.snapshot()
        deadline = time.monotonic()+timeout
        while True:
            self.changed.clear()
            snapshot = self.snapshot()
            if snapshot.complete:
                self.warmed = True
            if snapshot.complete or self.error or self.interrupted or self.boot_reset:
                return snapshot
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                return snapshot
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return self.snapshot()
