"""Latest-state formation delivery; notifications are never flight commands."""
from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from contextlib import asynccontextmanager

from src.smart_swarm_contract import normalize_topology, topology_revision

_watchers = weakref.WeakSet()
_watchers_lock = threading.RLock()
logger = logging.getLogger(__name__)


def notify_formation_saved():
    """Wake subscribers after canonical persistence, including non-HTTP writers."""
    with _watchers_lock:
        watchers = list(_watchers)
    for watcher in watchers:
        watcher.wake()


def snapshot(assignments):
    members = normalize_topology(assignments)
    if not members:
        raise ValueError("Formation snapshot is empty")
    return {"version": 1, "assignments": members, "revision": topology_revision(members)}


class FormationWatch:
    """One reconciliation reader per process, bounded latest-only subscriber queues."""

    def __init__(self, load, interval=1.0):
        self.load = load
        self.interval = interval
        self.queues = set()
        self.task = None
        self.loop = None
        self.changed = None
        self.read_lock = None
        with _watchers_lock:
            _watchers.add(self)

    def wake(self):
        loop, changed = self.loop, self.changed
        if loop is not None and changed is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(changed.set)
            except RuntimeError:
                # The server loop may close concurrently with a worker save.
                pass

    @staticmethod
    def offer(queue, value):
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(value)

    async def _run(self):
        previous = None
        failed = False
        while True:
            self.changed.clear()
            try:
                async with self.read_lock:
                    value = snapshot(await asyncio.to_thread(self.load))
                    if value["revision"] != previous:
                        previous = value["revision"]
                        for queue in tuple(self.queues):
                            self.offer(queue, value)
                if failed:
                    logger.info("Formation watch reconciliation recovered")
                failed = False
            except Exception:
                if not failed:
                    logger.warning("Formation watch cannot read a valid snapshot; retaining last revision", exc_info=True)
                failed = True
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    @asynccontextmanager
    async def subscribe(self):
        queue = asyncio.Queue(maxsize=1)
        # Registration precedes reading so a concurrent save cannot be missed.
        self.queues.add(queue)
        try:
            if self.task is None:
                self.loop = asyncio.get_running_loop()
                self.changed = asyncio.Event()
                self.read_lock = asyncio.Lock()
                self.task = asyncio.create_task(self._run())
            async with self.read_lock:
                self.offer(queue, snapshot(await asyncio.to_thread(self.load)))
            yield queue
        finally:
            self.queues.discard(queue)
            if not self.queues and self.task is not None:
                task = self.task
                self.task = None
                self.loop = None
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


def matches_etag(header, revision):
    """GET validators use weak comparison, including wildcard/multiple tags."""
    for value in (header or "").split(","):
        value = value.strip()
        if value == "*" or value.removeprefix("W/") == f'"{revision}"':
            return True
    return False
