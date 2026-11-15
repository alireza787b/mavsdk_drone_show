import asyncio
import json

import pytest

from src.latest_state_publisher import LatestStatePublisher, SubscriberLimitExceeded


@pytest.mark.asyncio
async def test_one_immutable_encoded_generation_for_all_clients():
    source = {"position": {"north": 1}}
    calls = []
    def sample():
        calls.append(True)
        return source
    publisher = LatestStatePublisher(sample, interval=100, error_payload=lambda: {"error": "unavailable"})
    async with publisher.subscribe() as first, publisher.subscribe() as second:
        one, two = await asyncio.wait_for(asyncio.gather(first.get(), second.get()), 1)
        assert one is two
        assert len(calls) == 1
        source["position"]["north"] = 9
        assert json.loads(one)["position"]["north"] == 1
    assert publisher._task is None
    assert not publisher._queues


@pytest.mark.asyncio
async def test_slow_reader_coalesces_while_healthy_reader_advances():
    generation = [0]
    def sample():
        generation[0] += 1
        return {"generation": generation[0]}
    publisher = LatestStatePublisher(sample, interval=0.005, error_payload=lambda: {})
    async with publisher.subscribe() as slow, publisher.subscribe() as healthy:
        values = []
        for _ in range(5):
            values.append(json.loads(await asyncio.wait_for(healthy.get(), 1))["generation"])
        assert values == sorted(set(values))
        assert slow.qsize() == 1
        assert json.loads(slow.get_nowait())["generation"] == values[-1]


@pytest.mark.asyncio
async def test_slow_send_has_deadline_without_stalling_other_clients():
    publisher = LatestStatePublisher(lambda: {"ok": True}, interval=0.005, error_payload=lambda: {})
    class SlowSocket:
        async def send_text(self, _frame):
            await asyncio.Event().wait()
    async with publisher.subscribe() as slow, publisher.subscribe() as healthy:
        sending = asyncio.create_task(publisher.send(slow, SlowSocket(), timeout=0.03))
        for _ in range(3):
            assert json.loads(await asyncio.wait_for(healthy.get(), 1)) == {"ok": True}
        with pytest.raises(asyncio.TimeoutError):
            await sending
        assert publisher._task is not None and not publisher._task.done()
    assert publisher._task is None


@pytest.mark.asyncio
async def test_subscriber_limit_and_disconnect_restart_have_bounded_lifecycle():
    publisher = LatestStatePublisher(lambda: {"ok": True}, interval=100,
                                     error_payload=lambda: {}, max_subscribers=1)
    async with publisher.subscribe() as queue:
        first = await asyncio.wait_for(queue.get(), 1)
        with pytest.raises(SubscriberLimitExceeded):
            async with publisher.subscribe():
                pass
    async with publisher.subscribe() as queue:
        assert await asyncio.wait_for(queue.get(), 1) == first
    assert publisher._task is None


@pytest.mark.asyncio
async def test_source_failure_is_not_a_fresh_native_sample_and_can_recover():
    fail = [True]
    def sample():
        if fail[0]:
            raise ValueError("injected invalid snapshot")
        return {"native_timestamp_ms": 123, "ok": True}
    publisher = LatestStatePublisher(sample, interval=0.005,
                                     error_payload=lambda: {"error": "unavailable"})
    async with publisher.subscribe() as queue:
        assert json.loads(await asyncio.wait_for(queue.get(), 1)) == {"error": "unavailable"}
        fail[0] = False
        for _ in range(5):
            value = json.loads(await asyncio.wait_for(queue.get(), 1))
            if value.get("ok"):
                break
        assert value == {"native_timestamp_ms": 123, "ok": True}


@pytest.mark.asyncio
async def test_oversized_utf8_state_and_error_frames_stay_bounded_and_recover():
    source = {"value": "é" * 200}
    publisher = LatestStatePublisher(lambda: source, interval=0.005,
                                     error_payload=lambda: source, max_frame_bytes=256)
    async with publisher.subscribe() as queue:
        frame = await asyncio.wait_for(queue.get(), 1)
        assert len(frame.encode("utf-8")) <= 256
        assert json.loads(frame) == {"error": "State unavailable"}
        source.clear()
        source["native_timestamp_ms"] = 123
        for _ in range(5):
            frame = await asyncio.wait_for(queue.get(), 1)
            if "native_timestamp_ms" in json.loads(frame):
                break
        assert json.loads(frame) == {"native_timestamp_ms": 123}
