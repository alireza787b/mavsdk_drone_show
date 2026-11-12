"""Tests for mds_logging.watcher — in-memory pub/sub for SSE."""
import asyncio
import threading
import pytest
from mds_logging.watcher import LogWatcher


class TestLogWatcher:
    def test_publish_to_empty_watcher(self):
        """Publishing with no subscribers should not error."""
        watcher = LogWatcher()
        watcher.publish({"msg": "test"})  # no error

    def test_buffer_stores_recent_entries(self):
        watcher = LogWatcher(max_buffer=5)
        for i in range(10):
            watcher.publish({"msg": f"entry_{i}"})
        assert len(watcher._buffer) == 5
        assert watcher._buffer[0]["msg"] == "entry_5"

    @pytest.mark.asyncio
    async def test_subscribe_receives_published(self):
        watcher = LogWatcher()
        received = []

        async def consumer():
            async for entry in watcher.subscribe():
                received.append(entry)
                if len(received) >= 3:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        for i in range(3):
            watcher.publish({"msg": f"live_{i}"})
        await asyncio.wait_for(task, timeout=2.0)
        assert len(received) == 3

    @pytest.mark.asyncio
    async def test_subscribe_with_level_filter(self):
        watcher = LogWatcher()
        received = []

        async def consumer():
            async for entry in watcher.subscribe(level="ERROR"):
                received.append(entry)
                if len(received) >= 1:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        watcher.publish({"level": "INFO", "msg": "skip"})
        watcher.publish({"level": "ERROR", "msg": "catch"})
        await asyncio.wait_for(task, timeout=2.0)
        assert received[0]["msg"] == "catch"


async def test_atomic_snapshot_and_registration_deliver_each_publication_once():
    watcher = LogWatcher()
    watcher.publish({"msg": "same warning", "level": "WARNING"})
    events = watcher.subscribe_events()
    status = await anext(events)  # Registration and replay snapshot are committed.
    assert status.kind == "status"
    watcher.publish({"msg": "same warning", "level": "WARNING"})
    first, second = await anext(events), await anext(events)
    assert first.data == second.data  # Identical text is still two real events.
    assert first.event_id != second.event_id
    assert first.event_id.endswith(":1")
    assert second.event_id.endswith(":2")
    await events.aclose()
    assert not watcher._subscribers


async def test_logger_thread_publish_wakes_only_the_subscriber_loop():
    watcher = LogWatcher(max_buffer=0)
    events = watcher.subscribe_events()
    await anext(events)
    reader = asyncio.create_task(anext(events))
    await asyncio.sleep(0)
    errors = []

    def publish():
        try:
            watcher.publish({"msg": "from logger thread"})
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=publish)
    thread.start()
    thread.join()
    entry = await asyncio.wait_for(reader, timeout=1)
    assert not errors
    assert entry.data["msg"] == "from logger thread"
    await events.aclose()


async def test_replay_cursor_only_returns_later_native_identities():
    watcher = LogWatcher()
    for index in range(3):
        watcher.publish({"msg": "repeat", "index": index})
    events = watcher.subscribe_events(last_event_id=f"{watcher.epoch}:1")
    status, second, third = await anext(events), await anext(events), await anext(events)
    assert status.data["replayed_count"] == 2
    assert [second.event_id, third.event_id] == [f"{watcher.epoch}:2", f"{watcher.epoch}:3"]
    await events.aclose()


async def test_retention_gap_has_exact_known_loss_without_claiming_full_history():
    watcher = LogWatcher(max_buffer=2)
    for index in range(5):
        watcher.publish({"msg": str(index)})
    events = watcher.subscribe_events(last_event_id=f"{watcher.epoch}:1")
    status, gap, fourth = await anext(events), await anext(events), await anext(events)
    assert status.data["history_complete"] is False
    assert gap.kind == "gap" and gap.data["reason"] == "retention"
    assert gap.data["lost_count"] == 2
    assert gap.data["from_event_id"].endswith(":2")
    assert gap.data["to_event_id"].endswith(":3")
    assert fourth.event_id.endswith(":4")
    await events.aclose()


@pytest.mark.parametrize("cursor,reason", [("previousepoch:4", "stream_restarted"), ("bad", "invalid_cursor")])
async def test_unrecoverable_cursor_reports_unknown_loss(cursor, reason):
    watcher = LogWatcher()
    watcher.publish({"msg": "current process"})
    events = watcher.subscribe_events(last_event_id=cursor)
    await anext(events)
    gap = await anext(events)
    assert gap.data["reason"] == reason
    assert gap.data["lost_count"] is None
    assert (await anext(events)).kind == "entry"
    await events.aclose()


async def test_slow_subscriber_queue_is_bounded_and_reports_dropped_matching_events():
    watcher = LogWatcher(max_buffer=0, max_pending=2)
    events = watcher.subscribe_events(level="WARNING")
    await anext(events)
    for index in range(5):
        watcher.publish({"level": "WARNING", "msg": str(index)})
        watcher.publish({"level": "DEBUG", "msg": "filtered"})
    assert len(watcher._subscribers[0].pending) == 2
    gap = await anext(events)
    assert gap.data["reason"] == "slow_subscriber"
    assert gap.data["lost_count"] == 3
    assert [(await anext(events)).data["msg"], (await anext(events)).data["msg"]] == ["3", "4"]
    await events.aclose()
