"""Typed, time-truthful safety evidence for vehicle action boundaries.

MAVSDK subscriptions may immediately replay the plugin's latest cached value.
Local receipt therefore proves only *when this process received a value*; it
does not prove when PX4 produced it.  This module keeps those clocks separate,
requires a live connection throughout each observation, and invalidates a
mixed snapshot after disconnect/reconnect or an observed autopilot boot-clock
rollback.

The same snapshot contract is used by action admission (takeoff, Hold and the
ground arm/disarm test) and mission-startup/live-armability probes.  Callers no
longer invent ``fresh: true`` beside a newly generated local timestamp.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping

from src.async_stream_utils import (
    managed_async_stream,
    monotonic_deadline,
    next_stream_sample,
)


ACTION_STATE_OBSERVATION_TIMEOUT_SEC = 3.0
SAFETY_EVIDENCE_VALIDITY_MS = 2_000
SAFETY_SOURCE_CLOCK_FUTURE_TOLERANCE_MS = 250
SAFETY_BOOT_CLOCK_ROLLBACK_TOLERANCE_MS = 250

# TAKE_OFF and TEST perform bounded, shielded recovery after cooperative
# process termination.  The process manager grants a little additional time
# for terminal-result emission and pipe teardown before it may force-kill.
ACTION_SAFETY_CLEANUP_TIMEOUT_SEC = 25.0
ACTION_PROCESS_CLEANUP_GRACE_SEC = 30.0

AIRBORNE_MIN_RELATIVE_ALTITUDE_M = 0.5
GROUND_MAX_RELATIVE_ALTITUDE_M = 0.5


class EvidenceFreshness(str, Enum):
    """Truthful freshness state for one safety-bearing field."""

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


def _wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


def _enum_name(value: Any) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if name:
        return str(name).upper()
    text = str(value).strip()
    if not text:
        return None
    return text.rsplit(".", 1)[-1].upper()


def _finite_float(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _bounded_error(exc: BaseException) -> str:
    text = " ".join(str(exc or type(exc).__name__).split())
    return text[:160] or type(exc).__name__


def _json_value(value: Any) -> Any:
    """Return bounded evidence-friendly data without pretending SDK objects are JSON."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    enum_name = getattr(value, "name", None)
    if enum_name:
        return str(enum_name)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in list(value.items())[:24]}
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return {
            str(key): _json_value(item)
            for key, item in list(attributes.items())[:24]
            if not str(key).startswith("_")
        }
    return str(value)[:160]


@dataclass(frozen=True)
class SafetyFieldEvidence:
    """One value with independent local-receipt and source-clock evidence."""

    name: str
    source: str
    value: Any = None
    received_at_ms: int | None = None
    receipt_age_ms: int | None = None
    source_timestamp_ms: int | None = None
    source_age_ms: int | None = None
    source_time_boot_ms: int | None = None
    receipt_freshness: EvidenceFreshness = EvidenceFreshness.UNKNOWN
    source_freshness: EvidenceFreshness = EvidenceFreshness.UNKNOWN
    freshness: EvidenceFreshness = EvidenceFreshness.UNKNOWN
    error: str | None = None
    stale_reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.error is None and self.value is not None and self.freshness is EvidenceFreshness.FRESH

    def as_dict(self, *, include_value: bool = True) -> dict[str, Any]:
        result = {
            "source": self.source,
            "received_at_ms": self.received_at_ms,
            "receipt_age_ms": self.receipt_age_ms,
            "source_timestamp_ms": self.source_timestamp_ms,
            "source_age_ms": self.source_age_ms,
            "source_time_boot_ms": self.source_time_boot_ms,
            "receipt_freshness": self.receipt_freshness.value,
            "source_freshness": self.source_freshness.value,
            "freshness": self.freshness.value,
            "error": self.error,
            "stale_reason": self.stale_reason,
        }
        if include_value:
            result["value"] = _json_value(self.value)
        return result


@dataclass
class SafetyEvidenceTracker:
    """Process-local continuity guard; it stores no safety decision or cached value."""

    connection_live: bool | None = None
    connection_generation: int = 0
    last_source_time_boot_ms: dict[str, int] = field(default_factory=dict)

    def record_connection(self, live: bool) -> None:
        if self.connection_live is not None and self.connection_live is not live:
            self.connection_generation += 1
        self.connection_live = live

    def record_source_boot_time(self, field_name: str, source_time_boot_ms: int | None) -> bool:
        if source_time_boot_ms is None:
            return False
        previous = self.last_source_time_boot_ms.get(field_name)
        self.last_source_time_boot_ms[field_name] = source_time_boot_ms
        return bool(
            previous is not None
            and source_time_boot_ms + SAFETY_BOOT_CLOCK_ROLLBACK_TOLERANCE_MS < previous
        )


@dataclass(frozen=True)
class SafetyStreamSpec:
    """How a named field is sampled and normalized for a safety snapshot."""

    source: str
    stream_factory: Callable[[], Any]
    normalize: Callable[[Any], Any] = lambda value: value


@dataclass(frozen=True)
class SafetySnapshot:
    """One connection-bound snapshot of named safety-bearing fields."""

    observed_at_ms: int
    connection: SafetyFieldEvidence
    fields: dict[str, SafetyFieldEvidence]
    required_fields: tuple[str, ...]
    connection_interrupted: bool = False
    source_boot_reset: bool = False
    observation_error: str | None = None
    source: str = "mavsdk.telemetry"
    schema_version: int = 1

    @property
    def connection_live(self) -> bool | None:
        return self.connection.value if type(self.connection.value) is bool else None

    @property
    def complete(self) -> bool:
        return bool(
            self.connection_live is True
            and self.connection.usable
            and not self.connection_interrupted
            and not self.source_boot_reset
            and self.observation_error is None
            and all(
                name in self.fields and self.fields[name].usable
                for name in self.required_fields
            )
        )

    @property
    def field_errors(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        if self.connection_live is not True:
            errors["connection"] = self.connection.error or "vehicle connection is not live"
        elif not self.connection.usable:
            errors["connection"] = self.connection.error or "vehicle connection evidence is stale or unknown"
        if self.connection_interrupted:
            errors["connection_continuity"] = "connection changed while safety fields were sampled"
        if self.source_boot_reset:
            errors["source_boot"] = "autopilot boot clock reset while safety fields were sampled"
        if self.observation_error:
            errors["observation"] = self.observation_error
        for name in self.required_fields:
            evidence = self.fields.get(name)
            if evidence is None:
                errors[name] = "field was not sampled"
            elif not evidence.usable:
                errors[name] = evidence.error or evidence.stale_reason or (
                    f"field freshness is {evidence.freshness.value}"
                )
        return errors

    def field_value(self, name: str) -> Any:
        evidence = self.fields.get(name)
        return evidence.value if evidence is not None else None

    @property
    def armed(self) -> bool | None:
        value = self.field_value("armed")
        return value if type(value) is bool else None

    @property
    def landed_state(self) -> str | None:
        value = self.field_value("landed_state")
        return str(value) if isinstance(value, str) and value else None

    @property
    def relative_altitude_m(self) -> float | None:
        return _finite_float(self.field_value("relative_altitude_m"))

    @property
    def on_ground(self) -> bool:
        return self.complete and self.landed_state == "ON_GROUND"

    @property
    def airborne(self) -> bool:
        return bool(
            self.complete
            and self.armed is True
            and self.landed_state == "IN_AIR"
            and self.relative_altitude_m is not None
            and self.relative_altitude_m >= AIRBORNE_MIN_RELATIVE_ALTITUDE_M
        )

    @property
    def safe_ground_disarmed(self) -> bool:
        return bool(
            self.complete
            and self.armed is False
            and self.landed_state == "ON_GROUND"
            and self.relative_altitude_m is not None
            and abs(self.relative_altitude_m) <= GROUND_MAX_RELATIVE_ALTITUDE_M
        )

    def as_dict(self) -> dict[str, Any]:
        """Preserve concise legacy state keys while exposing full clock evidence."""

        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "observed_at_ms": self.observed_at_ms,
            "fresh": self.complete,
            "complete": self.complete,
            "connection_live": self.connection_live,
            "connection_interrupted": self.connection_interrupted,
            "source_boot_reset": self.source_boot_reset,
            "armed": self.armed,
            "landed_state": self.landed_state,
            "relative_altitude_m": self.relative_altitude_m,
            "field_errors": self.field_errors,
            "connection": self.connection.as_dict(),
            "fields": {
                name: evidence.as_dict()
                for name, evidence in self.fields.items()
            },
        }

    @classmethod
    def from_values(
        cls,
        *,
        armed: bool | None,
        landed_state: str | None,
        relative_altitude_m: float | None,
        connection_live: bool | None = True,
        observed_at_ms: int | None = None,
        receipt_ages_ms: Mapping[str, int | None] | None = None,
        source_ages_ms: Mapping[str, int | None] | None = None,
        errors: Mapping[str, str] | None = None,
    ) -> "SafetySnapshot":
        """Build deterministic synthetic evidence for tests and adapters."""

        now_ms = _wall_clock_ms() if observed_at_ms is None else int(observed_at_ms)
        receipt_ages_ms = dict(receipt_ages_ms or {})
        source_ages_ms = dict(source_ages_ms or {})
        errors = dict(errors or {})

        def evidence(name: str, source: str, value: Any) -> SafetyFieldEvidence:
            receipt_age = receipt_ages_ms.get(name, 0 if value is not None else None)
            source_age = source_ages_ms.get(name)
            return build_safety_field_evidence(
                name=name,
                source=source,
                value=value,
                received_at_ms=(now_ms - receipt_age if receipt_age is not None else None),
                now_ms=now_ms,
                receipt_age_ms=receipt_age,
                source_timestamp_ms=(now_ms - source_age if source_age is not None else None),
                error=errors.get(name),
            )

        connection = evidence(
            "connection",
            "mavsdk.core.connection_state",
            connection_live,
        )
        fields = {
            "armed": evidence("armed", "mavsdk.telemetry.armed", armed),
            "landed_state": evidence(
                "landed_state",
                "mavsdk.telemetry.landed_state",
                landed_state,
            ),
            "relative_altitude_m": evidence(
                "relative_altitude_m",
                "mavsdk.telemetry.position.relative_altitude_m",
                relative_altitude_m,
            ),
        }
        return cls(
            observed_at_ms=now_ms,
            connection=connection,
            fields=fields,
            required_fields=tuple(fields),
        )


# Compatibility name retained for focused callers while the implementation is
# one canonical snapshot type, not a parallel observation model.
VehicleStateObservation = SafetySnapshot


class ActionSafetyError(RuntimeError):
    """Typed action failure with bounded operator evidence and final state."""

    def __init__(
        self,
        *,
        code: str,
        phase: str,
        message: str,
        retryable: bool = False,
        evidence: dict[str, Any] | None = None,
        final_vehicle_state: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.phase = phase
        self.retryable = retryable
        self.evidence = dict(evidence or {})
        self.final_vehicle_state = (
            dict(final_vehicle_state) if final_vehicle_state is not None else None
        )
        super().__init__(message)


def _coerce_epoch_timestamp_ms(value: Any) -> int | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    # Epoch milliseconds after 2000-01-01. Smaller positive values are source
    # boot clocks, not wall time, and must never be subtracted from UTC.
    return timestamp if timestamp >= 946_684_800_000 else None


def _coerce_boot_timestamp_ms(value: Any) -> int | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return timestamp if 0 <= timestamp < 946_684_800_000 else None


def _sample_source_clocks(sample: Any) -> tuple[int | None, int | None]:
    source_timestamp = _coerce_epoch_timestamp_ms(
        getattr(sample, "_mds_source_timestamp_ms", None)
    )
    source_boot = _coerce_boot_timestamp_ms(
        getattr(sample, "_mds_source_time_boot_ms", None)
    )
    if source_timestamp is None:
        raw_timestamp = getattr(sample, "timestamp_ms", None)
        source_timestamp = _coerce_epoch_timestamp_ms(raw_timestamp)
        if source_timestamp is None and source_boot is None:
            source_boot = _coerce_boot_timestamp_ms(raw_timestamp)
    if source_boot is None:
        source_boot = _coerce_boot_timestamp_ms(getattr(sample, "time_boot_ms", None))
    return source_timestamp, source_boot


def build_safety_field_evidence(
    *,
    name: str,
    source: str,
    value: Any,
    received_at_ms: int | None,
    now_ms: int | None = None,
    receipt_age_ms: int | None = None,
    source_timestamp_ms: int | None = None,
    source_time_boot_ms: int | None = None,
    error: str | None = None,
    validity_ms: int = SAFETY_EVIDENCE_VALIDITY_MS,
    tracker: SafetyEvidenceTracker | None = None,
) -> SafetyFieldEvidence:
    """Classify a field without conflating receipt and source timestamps."""

    now_ms = _wall_clock_ms() if now_ms is None else int(now_ms)
    if receipt_age_ms is None and received_at_ms is not None:
        receipt_age_ms = max(0, now_ms - int(received_at_ms))

    if received_at_ms is None or receipt_age_ms is None:
        receipt_freshness = EvidenceFreshness.UNKNOWN
    elif receipt_age_ms <= validity_ms:
        receipt_freshness = EvidenceFreshness.FRESH
    else:
        receipt_freshness = EvidenceFreshness.STALE

    source_age_ms = None
    source_freshness = EvidenceFreshness.UNKNOWN
    stale_reason = None
    if source_timestamp_ms is not None:
        source_age_ms = now_ms - int(source_timestamp_ms)
        if source_age_ms < -SAFETY_SOURCE_CLOCK_FUTURE_TOLERANCE_MS:
            source_freshness = EvidenceFreshness.STALE
            stale_reason = "source timestamp is implausibly in the future"
        else:
            source_age_ms = max(0, source_age_ms)
            source_freshness = (
                EvidenceFreshness.FRESH
                if source_age_ms <= validity_ms
                else EvidenceFreshness.STALE
            )
            if source_freshness is EvidenceFreshness.STALE:
                stale_reason = "source timestamp is stale"

    boot_reset = bool(
        tracker is not None
        and tracker.record_source_boot_time(name, source_time_boot_ms)
    )
    if boot_reset:
        source_freshness = EvidenceFreshness.STALE
        stale_reason = "source boot clock moved backwards"

    if error is not None or value is None:
        freshness = EvidenceFreshness.UNKNOWN
    elif receipt_freshness is EvidenceFreshness.STALE or source_freshness is EvidenceFreshness.STALE:
        freshness = EvidenceFreshness.STALE
    elif receipt_freshness is EvidenceFreshness.FRESH:
        # A missing source clock remains explicitly UNKNOWN in source_freshness;
        # the field is usable because it arrived over a continuously live
        # subscription inside the bounded observation window.
        freshness = EvidenceFreshness.FRESH
    else:
        freshness = EvidenceFreshness.UNKNOWN

    if stale_reason is None and receipt_freshness is EvidenceFreshness.STALE:
        stale_reason = "local receipt is stale"

    return SafetyFieldEvidence(
        name=name,
        source=source,
        value=value,
        received_at_ms=received_at_ms,
        receipt_age_ms=receipt_age_ms,
        source_timestamp_ms=source_timestamp_ms,
        source_age_ms=source_age_ms,
        source_time_boot_ms=source_time_boot_ms,
        receipt_freshness=receipt_freshness,
        source_freshness=source_freshness,
        freshness=freshness,
        error=error,
        stale_reason=stale_reason,
    )


def _tracker_for(drone: Any) -> SafetyEvidenceTracker:
    attributes = getattr(drone, "__dict__", None)
    if isinstance(attributes, dict):
        tracker = attributes.get("_mds_safety_evidence_tracker")
        if isinstance(tracker, SafetyEvidenceTracker):
            return tracker
    tracker = SafetyEvidenceTracker()
    with contextlib.suppress(Exception):
        setattr(drone, "_mds_safety_evidence_tracker", tracker)
    return tracker


async def _sample_field(
    name: str,
    spec: SafetyStreamSpec,
    *,
    deadline: float,
) -> tuple[str, Any, int, float, int | None, int | None] | tuple[str, BaseException]:
    try:
        async with managed_async_stream(spec.stream_factory) as stream:
            sample = await next_stream_sample(
                stream,
                deadline=deadline,
                description=f"{name} safety telemetry",
            )
        received_monotonic = time.monotonic()
        received_at_ms = _wall_clock_ms()
        value = spec.normalize(sample)
        source_timestamp_ms, source_time_boot_ms = _sample_source_clocks(sample)
        return (
            name,
            value,
            received_at_ms,
            received_monotonic,
            source_timestamp_ms,
            source_time_boot_ms,
        )
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        return name, exc


def _connection_value(sample: Any) -> bool | None:
    value = getattr(sample, "is_connected", sample)
    return value if type(value) is bool else None


async def observe_safety_snapshot(
    drone: Any,
    *,
    field_specs: Mapping[str, SafetyStreamSpec],
    timeout: float = ACTION_STATE_OBSERVATION_TIMEOUT_SEC,
    required_fields: tuple[str, ...] | None = None,
) -> SafetySnapshot:
    """Sample fields while continuously monitoring the MAVSDK connection.

    A disconnect at any point invalidates the complete snapshot, including a
    disconnect followed by reconnect before the call returns.  The next call
    starts a new connection generation and can establish fresh evidence.
    """

    deadline = monotonic_deadline(max(0.001, float(timeout)))
    tracker = _tracker_for(drone)
    required = tuple(field_specs) if required_fields is None else tuple(required_fields)
    started_generation = tracker.connection_generation
    connection_interrupted = False
    connection_monitor_error: str | None = None
    latest_connection: tuple[bool | None, int, float] | None = None

    try:
        connection_factory = drone.core.connection_state
    except Exception as exc:
        connection = build_safety_field_evidence(
            name="connection",
            source="mavsdk.core.connection_state",
            value=None,
            received_at_ms=None,
            error=_bounded_error(exc),
        )
        return SafetySnapshot(
            observed_at_ms=_wall_clock_ms(),
            connection=connection,
            fields={},
            required_fields=required,
            observation_error="connection stream unavailable",
        )

    monitor_task: asyncio.Task | None = None
    field_results: list[Any] = []
    try:
        async with managed_async_stream(connection_factory) as connection_stream:
            initial_sample = await next_stream_sample(
                connection_stream,
                deadline=deadline,
                description="vehicle connection safety state",
            )
            initial_live = _connection_value(initial_sample)
            initial_received_at_ms = _wall_clock_ms()
            initial_received_monotonic = time.monotonic()
            latest_connection = (
                initial_live,
                initial_received_at_ms,
                initial_received_monotonic,
            )
            if initial_live is not None:
                tracker.record_connection(initial_live)
                # A reconnect observed before any field receipt starts a new,
                # valid generation. Only transitions during this snapshot
                # invalidate the mixed field set.
                started_generation = tracker.connection_generation

            if initial_live is not True:
                connection = build_safety_field_evidence(
                    name="connection",
                    source="mavsdk.core.connection_state",
                    value=initial_live,
                    received_at_ms=initial_received_at_ms,
                    receipt_age_ms=0,
                    error=(None if initial_live is False else "invalid connection sample"),
                )
                return SafetySnapshot(
                    observed_at_ms=_wall_clock_ms(),
                    connection=connection,
                    fields={},
                    required_fields=required,
                )

            async def monitor_connection() -> None:
                nonlocal connection_interrupted, connection_monitor_error, latest_connection
                try:
                    while True:
                        sample = await next_stream_sample(
                            connection_stream,
                            deadline=deadline,
                            description="vehicle connection continuity",
                        )
                        live = _connection_value(sample)
                        received_at_ms = _wall_clock_ms()
                        received_monotonic = time.monotonic()
                        latest_connection = (live, received_at_ms, received_monotonic)
                        if live is None:
                            connection_monitor_error = "invalid connection sample"
                            connection_interrupted = True
                            return
                        tracker.record_connection(live)
                        if live is False:
                            connection_interrupted = True
                except asyncio.CancelledError:
                    raise
                except TimeoutError:
                    # No connection change before the shared field deadline is
                    # normal; the initial live sample remains explicit.
                    return
                except BaseException as exc:
                    connection_monitor_error = _bounded_error(exc)

            monitor_task = asyncio.create_task(monitor_connection())
            field_results = await asyncio.gather(
                *(
                    _sample_field(name, spec, deadline=deadline)
                    for name, spec in field_specs.items()
                )
            )
            # Let a connection event already queued by MAVSDK reach the monitor
            # before freezing the snapshot.
            await asyncio.sleep(0)
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        connection_monitor_error = _bounded_error(exc)
    finally:
        if monitor_task is not None:
            monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor_task

    completed_monotonic = time.monotonic()
    completed_at_ms = _wall_clock_ms()
    if latest_connection is None:
        connection = build_safety_field_evidence(
            name="connection",
            source="mavsdk.core.connection_state",
            value=None,
            received_at_ms=None,
            error=connection_monitor_error or "connection observation unavailable",
        )
    else:
        live, received_at_ms, received_monotonic = latest_connection
        connection = build_safety_field_evidence(
            name="connection",
            source="mavsdk.core.connection_state",
            value=live,
            received_at_ms=received_at_ms,
            receipt_age_ms=max(0, int((completed_monotonic - received_monotonic) * 1_000)),
            error=(None if live is not None else "invalid connection sample"),
        )

    fields: dict[str, SafetyFieldEvidence] = {}
    source_boot_reset = False
    for result in field_results:
        name = result[0]
        spec = field_specs[name]
        if len(result) == 2 and isinstance(result[1], BaseException):
            fields[name] = build_safety_field_evidence(
                name=name,
                source=spec.source,
                value=None,
                received_at_ms=None,
                error=_bounded_error(result[1]),
            )
            continue
        _, value, received_at_ms, received_monotonic, source_timestamp_ms, source_time_boot_ms = result
        evidence = build_safety_field_evidence(
            name=name,
            source=spec.source,
            value=value,
            received_at_ms=received_at_ms,
            receipt_age_ms=max(0, int((completed_monotonic - received_monotonic) * 1_000)),
            source_timestamp_ms=source_timestamp_ms,
            source_time_boot_ms=source_time_boot_ms,
            tracker=tracker,
        )
        if evidence.stale_reason == "source boot clock moved backwards":
            source_boot_reset = True
        fields[name] = evidence

    connection_interrupted = bool(
        connection_interrupted
        or tracker.connection_generation != started_generation
        or connection.value is not True
    )
    return SafetySnapshot(
        observed_at_ms=completed_at_ms,
        connection=connection,
        fields=fields,
        required_fields=required,
        connection_interrupted=connection_interrupted,
        source_boot_reset=source_boot_reset,
        observation_error=connection_monitor_error,
    )


async def observe_authoritative_vehicle_state(
    drone: Any,
    *,
    timeout: float = ACTION_STATE_OBSERVATION_TIMEOUT_SEC,
) -> SafetySnapshot:
    """Return connection-bound armed, landed and relative-altitude evidence."""

    return await observe_safety_snapshot(
        drone,
        timeout=timeout,
        field_specs={
            "armed": SafetyStreamSpec(
                source="mavsdk.telemetry.armed",
                stream_factory=drone.telemetry.armed,
                normalize=lambda sample: sample if type(sample) is bool else None,
            ),
            "landed_state": SafetyStreamSpec(
                source="mavsdk.telemetry.landed_state",
                stream_factory=drone.telemetry.landed_state,
                normalize=_enum_name,
            ),
            "relative_altitude_m": SafetyStreamSpec(
                source="mavsdk.telemetry.position.relative_altitude_m",
                stream_factory=drone.telemetry.position,
                normalize=lambda sample: _finite_float(
                    getattr(sample, "relative_altitude_m", None)
                ),
            ),
        },
    )


__all__ = [
    "ACTION_PROCESS_CLEANUP_GRACE_SEC",
    "ACTION_SAFETY_CLEANUP_TIMEOUT_SEC",
    "ACTION_STATE_OBSERVATION_TIMEOUT_SEC",
    "AIRBORNE_MIN_RELATIVE_ALTITUDE_M",
    "ActionSafetyError",
    "EvidenceFreshness",
    "GROUND_MAX_RELATIVE_ALTITUDE_M",
    "SAFETY_EVIDENCE_VALIDITY_MS",
    "SafetyEvidenceTracker",
    "SafetyFieldEvidence",
    "SafetySnapshot",
    "SafetyStreamSpec",
    "VehicleStateObservation",
    "build_safety_field_evidence",
    "observe_authoritative_vehicle_state",
    "observe_safety_snapshot",
]
