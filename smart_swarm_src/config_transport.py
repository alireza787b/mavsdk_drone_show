"""Recoverable desired-state subscription, independent of motion/control policy."""
from __future__ import annotations

import asyncio
import logging
import random
from contextlib import asynccontextmanager

import aiohttp

from src.smart_swarm_contract import normalize_topology, topology_revision
from src.gcs_api_routes import GCS_CONFIG_SWARM_ROUTE, GCS_WS_SWARM_CONFIG_ROUTE


class FormationSubscription:
    def __init__(self, url, headers, *, fallback_sec=2.0, reconcile_sec=30.0,
                 request_timeout_sec=2.0, backoff_max_sec=15.0):
        self.url = url
        self.ws_url = url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        self.ws_url = self.ws_url.rsplit(GCS_CONFIG_SWARM_ROUTE, 1)[0] + GCS_WS_SWARM_CONFIG_ROUTE
        self.headers = headers
        self.fallback_sec = fallback_sec
        self.reconcile_sec = reconcile_sec
        self.request_timeout_sec = request_timeout_sec
        self.backoff_max_sec = backoff_max_sec
        self.connected = False
        self.latest = None
        self.revision = None
        self.generation = 0
        self.queue = asyncio.Queue(maxsize=1)
        self.client = None
        self.logger = logging.getLogger(__name__)

    def accept(self, resource):
        entries = resource.get("assignments", resource) if isinstance(resource, dict) else resource
        entries = normalize_topology(entries)
        if not entries:
            raise ValueError("Formation snapshot is empty")
        revision = topology_revision(entries)
        if isinstance(resource, dict) and resource.get("revision", revision) != revision:
            raise ValueError("Formation snapshot revision mismatch")
        if revision == self.revision:
            return False
        self.latest, self.revision = entries, revision
        self.generation += 1
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(entries)
        return True

    async def _watch(self):
        attempt = 0
        unavailable = False
        while True:
            try:
                async with self.client.ws_connect(
                    self.ws_url, headers=self.headers, heartbeat=10, receive_timeout=25,
                    timeout=aiohttp.ClientWSTimeout(ws_close=3) if hasattr(aiohttp, "ClientWSTimeout") else 3,
                ) as websocket:
                    # Handshake is not proof that this server implements snapshots.
                    async for message in websocket:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = message.json()
                            if not isinstance(payload, dict):
                                raise ValueError("Formation watch envelope must be an object")
                            if payload.get("type") == "swarm_config":
                                self.accept(payload["data"])
                                self.connected = True
                                attempt = 0
                                if unavailable:
                                    self.logger.info("Formation watch recovered; current plan reconciled")
                                    unavailable = False
                            elif payload.get("type") != "heartbeat":
                                raise ValueError("Unexpected formation watch message")
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            raise websocket.exception() or RuntimeError("Formation watch failed")
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError, RuntimeError):
                if not unavailable:
                    self.logger.warning("Formation watch unavailable; retaining plan and using HTTP reconciliation")
                unavailable = True
            finally:
                self.connected = False
            cap = min(self.backoff_max_sec, 0.5 * 2 ** min(attempt, 6))
            attempt += 1
            await asyncio.sleep(random.uniform(cap / 2, cap))

    async def _reconcile(self):
        failed = False
        while True:
            generation = self.generation
            headers = dict(self.headers)
            if self.revision:
                headers["If-None-Match"] = f'"{self.revision}"'
            try:
                async with self.client.get(
                    self.url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout_sec),
                ) as response:
                    if response.status != 304:
                        response.raise_for_status()
                        resource = await response.json()
                        # An HTTP response begun before a newer push cannot undo it.
                        if generation == self.generation:
                            self.accept(resource)
                if failed:
                    self.logger.info("Formation HTTP reconciliation recovered")
                failed = False
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError):
                if not failed:
                    self.logger.warning("Formation reconciliation unavailable; retaining current plan")
                failed = True
            # Check connection state frequently without fetching while healthy.
            elapsed = 0.0
            while elapsed < (self.reconcile_sec if self.connected else self.fallback_sec):
                await asyncio.sleep(min(0.5, self.fallback_sec))
                elapsed += min(0.5, self.fallback_sec)

    @asynccontextmanager
    async def run(self):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.request_timeout_sec)) as client:
            self.client = client
            tasks = [asyncio.create_task(self._watch()), asyncio.create_task(self._reconcile())]
            try:
                yield self
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self.client = None

    async def updates(self):
        while True:
            try:
                yield await asyncio.wait_for(self.queue.get(), timeout=self.fallback_sec)
            except asyncio.TimeoutError:
                if self.latest is not None:
                    # Retry deferred local authority transitions without network polling.
                    yield self.latest
