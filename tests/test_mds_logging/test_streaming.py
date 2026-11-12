import asyncio
import json

from mds_logging.streaming import encode_sse_event, sse_log_stream
from mds_logging.watcher import LogStreamEvent, LogWatcher


def _data(frame):
    return json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))


def test_plain_entry_sse_preserves_json_and_native_identity():
    entry = {"msg": "first\nsecond 😀", "level": "WARNING"}
    frame = encode_sse_event(LogStreamEvent("entry", entry, "epoch:7"))
    assert frame.startswith("id: epoch:7\n")
    assert "event: entry" not in frame
    assert _data(frame) == entry


def test_named_control_events_do_not_advance_entry_cursor():
    for kind in ("status", "gap"):
        frame = encode_sse_event(LogStreamEvent(kind, {"coverage": "partial"}))
        assert frame.startswith(f"event: {kind}\n")
        assert "\nid:" not in frame


async def test_quiet_heartbeat_does_not_cancel_subscription_or_fabricate_log_records():
    watcher = LogWatcher(max_buffer=0)
    stream = sse_log_stream(watcher, heartbeat_seconds=0.01)
    assert (await anext(stream)).startswith("event: status\n")
    heartbeat = await asyncio.wait_for(anext(stream), timeout=1)
    assert _data(heartbeat)["heartbeat"] is True
    assert "level" not in _data(heartbeat)
    assert "armed" not in _data(heartbeat)
    watcher.publish({"msg": "after quiet interval"})
    entry = await asyncio.wait_for(anext(stream), timeout=1)
    assert _data(entry)["msg"] == "after quiet interval"
    assert entry.startswith(f"id: {watcher.epoch}:1\n")
    await stream.aclose()
    assert not watcher._subscribers


async def test_cancelled_stream_releases_pending_subscriber_read():
    watcher = LogWatcher()
    stream = sse_log_stream(watcher, heartbeat_seconds=60)
    await anext(stream)
    read = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    read.cancel()
    await asyncio.gather(read, return_exceptions=True)
    await stream.aclose()
    assert not watcher._subscribers


async def test_malformed_live_record_reports_gap_without_losing_following_records():
    watcher = LogWatcher()
    watcher.publish({"msg": "invalid extra", "extra": {"value": float("nan")}})
    watcher.publish({"msg": "valid next record"})
    stream = sse_log_stream(watcher)
    await anext(stream)
    gap = await anext(stream)
    assert gap.startswith("event: gap\n")
    assert _data(gap)["reason"] == "invalid_record"
    assert _data(gap)["lost_count"] == 1
    assert _data(await anext(stream))["msg"] == "valid next record"
    await stream.aclose()
