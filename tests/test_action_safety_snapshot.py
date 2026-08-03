import asyncio
from types import SimpleNamespace

import pytest

from src.action_safety import (
    EvidenceFreshness,
    SafetySnapshot,
    SafetyStreamSpec,
    observe_safety_snapshot,
)


async def _stable_stream(value, *, delay=0.0):
    if delay:
        await asyncio.sleep(delay)
    yield value
    await asyncio.Event().wait()


def _stable_connection():
    return _stable_stream(SimpleNamespace(is_connected=True))


def _drone(connection_factory=_stable_connection):
    return SimpleNamespace(core=SimpleNamespace(connection_state=connection_factory))


@pytest.mark.asyncio
async def test_disconnect_reconnect_during_sampling_invalidates_mixed_snapshot():
    async def changing_connection():
        yield SimpleNamespace(is_connected=True)
        await asyncio.sleep(0.005)
        yield SimpleNamespace(is_connected=False)
        await asyncio.sleep(0.005)
        yield SimpleNamespace(is_connected=True)
        await asyncio.Event().wait()

    drone = _drone(changing_connection)
    snapshot = await observe_safety_snapshot(
        drone,
        timeout=0.2,
        field_specs={
            "armed": SafetyStreamSpec(
                source="test.armed",
                stream_factory=lambda: _stable_stream(True, delay=0.02),
            )
        },
    )

    assert snapshot.connection_live is True
    assert snapshot.connection_interrupted is True
    assert snapshot.complete is False
    assert "connection_continuity" in snapshot.field_errors


@pytest.mark.asyncio
async def test_new_post_reconnect_snapshot_can_become_complete():
    calls = 0

    def connection_factory():
        nonlocal calls
        calls += 1
        return _stable_stream(SimpleNamespace(is_connected=calls > 1))

    drone = _drone(connection_factory)
    field_specs = {
        "armed": SafetyStreamSpec(
            source="test.armed",
            stream_factory=lambda: _stable_stream(False),
        )
    }

    disconnected = await observe_safety_snapshot(
        drone,
        timeout=0.1,
        field_specs=field_specs,
    )
    reconnected = await observe_safety_snapshot(
        drone,
        timeout=0.1,
        field_specs=field_specs,
    )

    assert disconnected.complete is False
    assert disconnected.connection_live is False
    assert reconnected.complete is True
    assert reconnected.connection_live is True


@pytest.mark.asyncio
async def test_recently_replayed_but_source_stale_cache_is_not_usable():
    old_source_ms = 1_785_000_000_000
    sample = SimpleNamespace(
        value=True,
        _mds_source_timestamp_ms=old_source_ms,
    )
    snapshot = await observe_safety_snapshot(
        _drone(),
        timeout=0.1,
        field_specs={
            "armed": SafetyStreamSpec(
                source="test.cached_armed",
                stream_factory=lambda: _stable_stream(sample),
                normalize=lambda item: item.value,
            )
        },
    )

    evidence = snapshot.fields["armed"]
    assert evidence.receipt_freshness is EvidenceFreshness.FRESH
    assert evidence.source_freshness is EvidenceFreshness.STALE
    assert evidence.freshness is EvidenceFreshness.STALE
    assert snapshot.complete is False


@pytest.mark.asyncio
async def test_boot_clock_rollback_invalidates_once_then_accepts_new_epoch():
    boot_times = iter([5_000, 100, 200])

    def boot_sample_stream():
        sample = SimpleNamespace(
            value=False,
            _mds_source_time_boot_ms=next(boot_times),
        )
        return _stable_stream(sample)

    drone = _drone()
    specs = {
        "armed": SafetyStreamSpec(
            source="test.boot_armed",
            stream_factory=boot_sample_stream,
            normalize=lambda item: item.value,
        )
    }

    before_reset = await observe_safety_snapshot(drone, timeout=0.1, field_specs=specs)
    reset_boundary = await observe_safety_snapshot(drone, timeout=0.1, field_specs=specs)
    after_reset = await observe_safety_snapshot(drone, timeout=0.1, field_specs=specs)

    assert before_reset.complete is True
    assert reset_boundary.complete is False
    assert reset_boundary.source_boot_reset is True
    assert reset_boundary.fields["armed"].stale_reason == "source boot clock moved backwards"
    assert after_reset.complete is True


@pytest.mark.asyncio
async def test_mixed_source_ages_fail_closed_per_field():
    now_ms = 1_900_000_000_000
    fresh = SimpleNamespace(value=True, _mds_source_timestamp_ms=now_ms - 100)
    stale = SimpleNamespace(value=False, _mds_source_timestamp_ms=now_ms - 10_000)

    # The source timestamps are deliberately evaluated against a fixed wall
    # clock so the test describes ages rather than today's date.
    from src import action_safety

    original_clock = action_safety._wall_clock_ms
    action_safety._wall_clock_ms = lambda: now_ms
    try:
        snapshot = await observe_safety_snapshot(
            _drone(),
            timeout=0.1,
            field_specs={
                "health": SafetyStreamSpec(
                    source="test.health",
                    stream_factory=lambda: _stable_stream(fresh),
                    normalize=lambda item: item.value,
                ),
                "battery": SafetyStreamSpec(
                    source="test.battery",
                    stream_factory=lambda: _stable_stream(stale),
                    normalize=lambda item: item.value,
                ),
            },
        )
    finally:
        action_safety._wall_clock_ms = original_clock

    assert snapshot.fields["health"].freshness is EvidenceFreshness.FRESH
    assert snapshot.fields["battery"].freshness is EvidenceFreshness.STALE
    assert snapshot.complete is False
    assert "battery" in snapshot.field_errors


@pytest.mark.asyncio
async def test_missing_source_clock_is_explicit_not_invented():
    snapshot = await observe_safety_snapshot(
        _drone(),
        timeout=0.1,
        field_specs={
            "health": SafetyStreamSpec(
                source="mavsdk.telemetry.health",
                stream_factory=lambda: _stable_stream(SimpleNamespace(is_armable=True)),
            )
        },
    )

    evidence = snapshot.fields["health"]
    assert evidence.freshness is EvidenceFreshness.FRESH
    assert evidence.source_freshness is EvidenceFreshness.UNKNOWN
    assert evidence.source_age_ms is None
    assert snapshot.complete is True


@pytest.mark.parametrize("landed_state", ["TAKING_OFF", "LANDING"])
def test_recovery_airborne_state_does_not_weaken_strict_airborne_truth(landed_state):
    snapshot = SafetySnapshot.from_values(
        armed=True,
        landed_state=landed_state,
        relative_altitude_m=6.0,
    )

    assert snapshot.airborne is False
    assert snapshot.airborne_for_recovery is True


@pytest.mark.parametrize(
    ("armed", "landed_state", "relative_altitude_m", "expected"),
    [
        (True, "IN_AIR", 0.5, True),
        (True, "TAKING_OFF", 0.5, True),
        (True, "LANDING", 0.5, True),
        (True, "ON_GROUND", 6.0, False),
        (False, "IN_AIR", 6.0, False),
        (True, "IN_AIR", 0.49, False),
        (True, "UNKNOWN", 6.0, False),
    ],
)
def test_recovery_airborne_gate_fails_closed(
    armed,
    landed_state,
    relative_altitude_m,
    expected,
):
    snapshot = SafetySnapshot.from_values(
        armed=armed,
        landed_state=landed_state,
        relative_altitude_m=relative_altitude_m,
    )

    assert snapshot.airborne_for_recovery is expected


def test_recovery_airborne_gate_rejects_incomplete_evidence():
    snapshot = SafetySnapshot.from_values(
        armed=True,
        landed_state="TAKING_OFF",
        relative_altitude_m=None,
        errors={"relative_altitude_m": "timeout"},
    )

    assert snapshot.complete is False
    assert snapshot.airborne_for_recovery is False
