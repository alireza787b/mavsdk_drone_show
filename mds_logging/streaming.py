"""SSE framing shared by native and GCS log streams."""
from __future__ import annotations

import asyncio
import json
import math

from mds_logging.watcher import LogStreamEvent, LogWatcher


def encode_sse_event(event: LogStreamEvent) -> str:
    fields = []
    if event.kind == "entry" and event.event_id:
        if any(char in event.event_id for char in "\r\n\x00"):
            raise ValueError("invalid SSE event identity")
        fields.append(f"id: {event.event_id}")
    elif event.kind in {"status", "gap"}:
        fields.append(f"event: {event.kind}")
    fields.append("data: " + json.dumps(event.data, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    return "\n".join(fields) + "\n\n"


async def sse_log_stream(watcher: LogWatcher, *, last_event_id=None, level=None,
                         component=None, source=None, drone_id=None, heartbeat_seconds=15.0):
    """Yield entries and quiet-stream heartbeats, not fabricated aircraft health."""
    if not isinstance(heartbeat_seconds, (int, float)) or not math.isfinite(heartbeat_seconds) or heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be positive and finite")
    events = watcher.subscribe_events(level, component, source, drone_id, last_event_id=last_event_id)
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(events))
            # Keep the read alive through quiet intervals; cancelling anext on
            # each heartbeat would close the subscription and invalidate replay.
            ready, _ = await asyncio.wait({pending}, timeout=heartbeat_seconds)
            if not ready:
                status = watcher.stream_status()
                status["heartbeat"] = True
                yield encode_sse_event(LogStreamEvent("status", status))
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                break
            pending = None
            try:
                frame = encode_sse_event(event)
            except (TypeError, ValueError, OverflowError):
                if event.kind != "entry":
                    raise
                # A malformed extra value (for example NaN) cannot be valid
                # browser JSON. Disclose the missing record and keep the rest
                # of the source usable rather than fabricating a replacement.
                frame = encode_sse_event(LogStreamEvent("gap", {
                    "reason": "invalid_record", "epoch": watcher.epoch,
                    "coverage": "partial", "history_complete": False,
                    "from_event_id": event.event_id, "to_event_id": event.event_id,
                    "lost_count": 1,
                }))
            yield frame
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await events.aclose()
