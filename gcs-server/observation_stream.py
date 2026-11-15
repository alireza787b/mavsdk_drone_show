"""Bounded, latest-only observations; never command delivery or an event archive.

One router-owned publisher validates/serializes each generation once. Consumers
share immutable-by-convention publications, not independent polling loops. A
sequence gap is expected for slow consumers; reconnect always starts at the
latest complete snapshot. Native aircraft sample clocks are never changed here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any, Callable

from starlette.websockets import WebSocket, WebSocketDisconnect

from auth_runtime import revalidate_websocket
from schemas import ObservationSnapshotMetadata


logger = logging.getLogger(__name__)
SEND_TIMEOUT_SEC = 5.0
AUTH_RECHECK_SEC = 5.0
IDLE_TIMEOUT_SEC = 15.0
MAX_SUBSCRIBERS = 128
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


class ObservationCapacityError(RuntimeError):
    """The topic has reached its bounded connection budget."""


class ObservationUnavailableError(RuntimeError):
    """A complete, valid observation cannot currently be published."""


@dataclass(frozen=True)
class PublishedObservation:
    body: dict[str, Any]
    metadata: dict[str, Any]
    legacy_json: str
    versioned_json: str

    def http_body(self) -> dict[str, Any]:
        return {**self.body, **self.metadata}


class LatestObservationPublisher:
    """Single-loop producer with one bounded latest slot per subscriber.

    HTTP versioned reads share the cached generation for at most ``interval``.
    Background publication exists only while a socket subscriber exists. Build
    failures invalidate the cache and terminate subscribers; a retained old
    snapshot must never masquerade as a fresh empty/healthy fleet.
    """

    def __init__(
        self,
        build: Callable[[], dict[str, Any]],
        message: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        interval: float,
        modern_fields: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        max_subscribers: int = MAX_SUBSCRIBERS,
        max_snapshot_bytes: int = MAX_SNAPSHOT_BYTES,
    ):
        if interval <= 0 or max_subscribers < 1 or max_snapshot_bytes < 1:
            raise ValueError("Observation publication bounds must be positive")
        self.build = build
        self.message = message
        self.interval = interval
        self.modern_fields = modern_fields or (lambda _: {})
        self.max_subscribers = max_subscribers
        self.max_snapshot_bytes = max_snapshot_bytes
        self.stream_id = str(uuid.uuid4())
        self.sequence = 0
        self.latest: PublishedObservation | None = None
        self.published_monotonic = 0.0
        self.queues: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None
        self.failed = False

    @staticmethod
    def _offer(queue: asyncio.Queue, value: Any) -> None:
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(value)

    def current(self) -> PublishedObservation:
        """Read/build atomically on the owning event loop, without awaiting I/O."""
        now = time.monotonic()
        if self.latest is not None and now - self.published_monotonic < self.interval:
            return self.latest
        try:
            body = self.build()
            metadata = ObservationSnapshotMetadata(
                protocol_version=1,
                stream_id=self.stream_id,
                sequence=self.sequence + 1,
                published_at_ms=int(time.time() * 1000),
                delivery="latest_snapshot",
            ).model_dump()
            message = self.message(body)
            modern = {**message, **self.modern_fields(body), **metadata}
            legacy_json = json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            versioned_json = json.dumps(modern, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            if max(len(legacy_json.encode("utf-8")), len(versioned_json.encode("utf-8"))) > self.max_snapshot_bytes:
                raise ValueError("Observation exceeds its bounded snapshot byte budget")
            publication = PublishedObservation(body, metadata, legacy_json, versioned_json)
        except Exception as exc:
            self.latest = None
            if not self.failed:
                logger.warning("Observation source cannot publish a valid snapshot", exc_info=True)
            self.failed = True
            raise ObservationUnavailableError("A valid observation snapshot is unavailable") from exc
        if self.failed:
            logger.info("Observation source publication recovered")
        self.failed = False
        self.latest = publication
        self.sequence += 1
        self.published_monotonic = now
        for queue in tuple(self.queues):
            self._offer(queue, publication)
        return publication

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            try:
                self.current()
            except ObservationUnavailableError as exc:
                for queue in tuple(self.queues):
                    self._offer(queue, exc)
                return

    @asynccontextmanager
    async def subscribe(self):
        if len(self.queues) >= self.max_subscribers:
            raise ObservationCapacityError("Observation subscriber capacity reached")
        queue = asyncio.Queue(maxsize=1)
        # Register before the initial snapshot; neither operation yields, so a
        # generation cannot be missed between registration and initial delivery.
        self.queues.add(queue)
        try:
            self._offer(queue, self.current())
            if self.task is None or self.task.done():
                self.task = asyncio.create_task(self._run(), name="mds-observation-publisher")
            yield queue
        finally:
            self.queues.discard(queue)
            if not self.queues and self.task is not None:
                task, self.task = self.task, None
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def _watch_peer(websocket: WebSocket) -> None:
    """Observe disconnect promptly even when no outbound publication is due."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        # This is a server-to-client observation stream, not an inbound command
        # channel. Reject application messages instead of consuming unbounded input.
        await websocket.close(code=1008, reason="observation_stream_is_read_only")
        return


async def _send_latest(websocket, queue, *, protocol_version, interval, auth_context):
    next_send = 0.0
    next_auth = time.monotonic() + AUTH_RECHECK_SEC
    last_publication = time.monotonic()
    pending = None
    while True:
        now = time.monotonic()
        if now - last_publication >= IDLE_TIMEOUT_SEC:
            await websocket.close(code=1013, reason="observation_idle")
            return
        if now >= next_auth:
            if not await revalidate_websocket(websocket, auth_context):
                return
            next_auth = time.monotonic() + AUTH_RECHECK_SEC
        if pending is not None and now >= next_send:
            # A slow interval keeps only the newest complete publication.
            while not queue.empty():
                pending = queue.get_nowait()
            if isinstance(pending, ObservationUnavailableError):
                raise pending
            message = pending.versioned_json if protocol_version == 1 else pending.legacy_json
            await asyncio.wait_for(websocket.send_text(message), timeout=SEND_TIMEOUT_SEC)
            next_send = time.monotonic() + interval
            pending = None
            continue
        timeout = max(0.001, min(next_auth - now, IDLE_TIMEOUT_SEC - (now - last_publication)))
        if pending is not None:
            timeout = min(timeout, max(0.001, next_send - now))
        try:
            pending = await asyncio.wait_for(queue.get(), timeout=timeout)
            last_publication = time.monotonic()
            if isinstance(pending, ObservationUnavailableError):
                raise pending
        except asyncio.TimeoutError:
            pass


async def serve_observations(websocket, publisher, *, interval=None, auth_context=None):
    """Bound send latency, peer lifetime and credential checks for one subscriber."""
    requested = websocket.query_params.get("protocol_version", "0")
    if requested not in {"0", "1"}:
        await websocket.close(code=1002, reason="unsupported_observation_protocol")
        return
    protocol_version = int(requested)
    tasks = []
    try:
        async with publisher.subscribe() as queue:
            tasks = [
                asyncio.create_task(_watch_peer(websocket)),
                asyncio.create_task(_send_latest(
                    websocket, queue, protocol_version=protocol_version,
                    interval=publisher.interval if interval is None else interval,
                    auth_context=auth_context,
                )),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except ObservationCapacityError:
        await websocket.close(code=1013, reason="observation_capacity")
    except ObservationUnavailableError:
        await websocket.close(code=1011, reason="observation_unavailable")
    except asyncio.TimeoutError:
        with suppress(RuntimeError, OSError):
            await websocket.close(code=1013, reason="slow_observation_consumer")
    except (WebSocketDisconnect, OSError, RuntimeError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
