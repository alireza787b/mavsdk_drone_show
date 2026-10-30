import asyncio
import time
from types import SimpleNamespace

import pytest

from src.action_state_sampler import ActionStateSampler


def native_drone():
    queues = {name: asyncio.Queue() for name in ("connection", "armed", "landed", "position")}
    closed, opened = set(), []
    def factory(name):
        async def stream():
            opened.append(name)
            try:
                while True:
                    yield await queues[name].get()
            finally:
                closed.add(name)
        return stream
    drone = SimpleNamespace(core=SimpleNamespace(connection_state=factory("connection")),
        telemetry=SimpleNamespace(armed=factory("armed"), landed_state=factory("landed"), position=factory("position")))
    queues["connection"].put_nowait(SimpleNamespace(is_connected=True))
    queues["armed"].put_nowait(True)
    queues["landed"].put_nowait("ON_GROUND")
    queues["position"].put_nowait(SimpleNamespace(absolute_altitude_m=100))
    return drone, queues, opened, closed


@pytest.mark.asyncio
async def test_one_hz_armed_source_allows_fast_snapshots_without_reopening_or_fake_receipts():
    drone, queues, opened, closed = native_drone()
    async with ActionStateSampler(drone) as sampler:
        first = await sampler.observe()
        assert first.complete
        receipt = first.fields["armed"].received_at_ms
        for _ in range(4):
            await asyncio.sleep(.2)
            current = await sampler.observe()
            assert current.complete
            assert current.fields["armed"].received_at_ms == receipt
            assert current.fields["armed"].receipt_age_ms >= 150
        await asyncio.sleep(.2)
        queues["armed"].put_nowait(True)
        await asyncio.sleep(0)
        current = await sampler.observe()
        assert current.complete
        assert current.fields["armed"].received_at_ms > receipt
        assert sorted(opened) == ["armed", "connection", "landed", "position"]
    assert sorted(closed) == sorted(opened)
    assert not sampler.tasks


@pytest.mark.asyncio
async def test_stale_native_armed_receipt_stays_stale_even_while_snapshots_are_polled():
    drone, _, _, _ = native_drone()
    async with ActionStateSampler(drone) as sampler:
        assert (await sampler.observe()).complete
        value, receipt, _, source, boot = sampler.values["armed"]
        sampler.values["armed"] = (value, receipt, time.monotonic()-3, source, boot)
        snapshot = await sampler.observe()
        assert not snapshot.complete
        assert snapshot.fields["armed"].received_at_ms == receipt
        assert snapshot.fields["armed"].receipt_age_ms >= 3000
        assert not snapshot.connection.usable


@pytest.mark.asyncio
async def test_disconnect_latches_abort_and_does_not_mix_reconnected_field_generations():
    drone, queues, _, closed = native_drone()
    async with ActionStateSampler(drone) as sampler:
        assert (await sampler.observe()).complete
        queues["connection"].put_nowait(SimpleNamespace(is_connected=False))
        await asyncio.sleep(0)
        assert not (await sampler.observe()).complete
        queues["connection"].put_nowait(SimpleNamespace(is_connected=True))
        await asyncio.sleep(0)
        snapshot = await sampler.observe()
        assert snapshot.connection_interrupted and not snapshot.complete
    assert len(closed) == 4


@pytest.mark.asyncio
async def test_sampler_subscriptions_are_closed_when_owner_is_cancelled():
    drone, _, _, closed = native_drone()
    ready = asyncio.Event()
    async def owner():
        async with ActionStateSampler(drone) as sampler:
            assert (await sampler.observe()).complete
            ready.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(owner())
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(closed) == 4
