"""Bounded read-only state fanout; never use this lossy channel for commands."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager


class SubscriberLimitExceeded(RuntimeError):
    pass


class LatestStatePublisher:
    """Sample/encode once per generation, with one pending frame per subscriber."""

    def __init__(self, source, *, interval, error_payload, max_subscribers=256,
                 max_frame_bytes=1024 * 1024):
        self.source = source
        self.interval = interval
        self.error_payload = error_payload
        self.max_subscribers = max_subscribers
        if max_frame_bytes < 256:
            raise ValueError("State frame limit must be at least 256 bytes")
        self.max_frame_bytes = max_frame_bytes
        self._queues = set()
        self._task = None
        self._latest = None
        self.logger = logging.getLogger(__name__)

    async def _run(self):
        failed = False
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            try:
                value = self.source()
                frame = json.dumps(value, separators=(",", ":"), allow_nan=False)
                if len(frame.encode("utf-8")) > self.max_frame_bytes:
                    raise ValueError("State snapshot exceeds frame byte limit")
                if failed:
                    self.logger.info("State publisher source recovered")
                failed = False
            except Exception:
                if not failed:
                    self.logger.warning("State publisher source unavailable", exc_info=True)
                failed = True
                try:
                    frame = json.dumps(self.error_payload(), separators=(",", ":"), allow_nan=False)
                    if len(frame.encode("utf-8")) > self.max_frame_bytes:
                        raise ValueError("State error snapshot exceeds frame byte limit")
                except Exception:
                    frame = '{"error":"State unavailable"}'
            # A string is immutable: all clients see this exact generation,
            # without sharing a mutable source dictionary or reserializing it.
            self._latest = frame
            for queue in tuple(self._queues):
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(frame)
            await asyncio.sleep(max(0.0, self.interval - (loop.time() - started)))

    @asynccontextmanager
    async def subscribe(self):
        if len(self._queues) >= self.max_subscribers:
            raise SubscriberLimitExceeded("State subscriber capacity reached")
        queue = asyncio.Queue(maxsize=1)
        self._queues.add(queue)
        if self._latest is not None:
            queue.put_nowait(self._latest)
        if self._task is None:
            self._task = asyncio.create_task(self._run())
        try:
            yield queue
        finally:
            self._queues.discard(queue)
            if not self._queues:
                await self.close()

    async def send(self, queue, websocket, *, timeout):
        """Bound each send and the client's rate, dropping superseded state."""
        loop = asyncio.get_running_loop()
        while True:
            frame = await queue.get()
            started = loop.time()
            await asyncio.wait_for(websocket.send_text(frame), timeout=timeout)
            await asyncio.sleep(max(0.0, self.interval - (loop.time() - started)))

    async def close(self):
        task, self._task = self._task, None
        self._latest = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
