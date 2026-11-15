"""Recoverable motion acquisition; flight authority and sample admission stay local.

HTTP fallback runs independently of bounded WebSocket probes. Only an accepted,
advancing motion sample makes a stream healthy; TCP/Pong/error traffic cannot.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Callable

import aiohttp

from src.drone_api_routes import DRONE_SWARM_STATE_ROUTE, DRONE_WS_SWARM_STATE_ROUTE


@dataclass(frozen=True)
class LeaderTransportPolicy:
    port: int
    poll_interval: float
    request_timeout: float
    connect_timeout: float
    sample_idle_timeout: float
    backoff_initial: float
    backoff_max: float
    stream_enabled: bool = True
    http_enabled: bool = True


class LeaderStateSupervisor:
    """One target generation, two acquisition paths, no flight-command retries.

    ``apply_sample`` is synchronous and returns true only when native motion
    validation and ordering have accepted the sample. The target callback and
    change event belong to the same asyncio loop as assignment changes.
    """

    def __init__(self, current_target: Callable, target_changed: asyncio.Event,
                 apply_sample: Callable, policy: LeaderTransportPolicy, *, client=None):
        self.current_target = current_target
        self.target_changed = target_changed
        self.apply_sample = apply_sample
        self.policy = policy
        self.client = client
        self.logger = logging.getLogger(__name__)

    def _offer(self, target, data, source):
        # A response can outlive a role/IP change. Fence immediately before the
        # synchronous admission callback, including changes to the same hw_id/IP.
        if target != self.current_target() or not isinstance(data, dict) or data.get("error"):
            return False
        try:
            return bool(self.apply_sample(data, source))
        except (ValueError, TypeError, KeyError, OverflowError):
            self.logger.debug("Malformed leader motion sample via %s", source, exc_info=True)
            return False

    async def _wait_target_changed(self, target):
        while target == self.current_target():
            await self.target_changed.wait()
            self.target_changed.clear()

    async def _http(self, target, fallback_needed):
        url = f"http://{target[2]}:{self.policy.port}{DRONE_SWARM_STATE_ROUTE}"
        timeout = aiohttp.ClientTimeout(total=self.policy.request_timeout)
        while True:
            await fallback_needed.wait()
            started = asyncio.get_running_loop().time()
            try:
                async with self.client.get(url, timeout=timeout) as response:
                    response.raise_for_status()
                    data = await response.json()
                self._offer(target, data, "http-fallback")
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
                self.logger.debug("Leader HTTP fallback unavailable", exc_info=True)
            # Probe duration/backoff never inserts a hole into HTTP acquisition.
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, self.policy.poll_interval - elapsed))

    async def _watch(self, target, fallback_needed):
        url = f"ws://{target[2]}:{self.policy.port}{DRONE_WS_SWARM_STATE_ROUTE}"
        backoff = self.policy.backoff_initial
        unavailable = False
        while True:
            websocket = None
            try:
                # sock_connect alone does not bound an HTTP upgrade handshake.
                websocket = await asyncio.wait_for(
                    self.client.ws_connect(url, heartbeat=15),
                    timeout=self.policy.connect_timeout,
                )
                deadline = asyncio.get_running_loop().time() + self.policy.sample_idle_timeout
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError("No advancing valid leader motion")
                    message = await asyncio.wait_for(websocket.receive(), timeout=remaining)
                    if message.type == aiohttp.WSMsgType.TEXT:
                        if self._offer(target, message.json(), "ws"):
                            deadline = asyncio.get_running_loop().time() + self.policy.sample_idle_timeout
                            fallback_needed.clear()
                            backoff = self.policy.backoff_initial
                            if unavailable:
                                self.logger.info("Leader motion stream recovered")
                                unavailable = False
                    elif message.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED,
                                          aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSE):
                        raise RuntimeError("Leader motion stream closed")
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, RuntimeError):
                if not unavailable:
                    self.logger.warning("Leader motion stream unavailable; using HTTP fallback when enabled")
                unavailable = True
            finally:
                fallback_needed.set()
                if websocket is not None:
                    try:
                        await asyncio.wait_for(websocket.close(), timeout=min(1.0, self.policy.connect_timeout))
                    except (aiohttp.ClientError, asyncio.TimeoutError):
                        pass
            await asyncio.sleep(random.uniform(backoff / 2, backoff))
            backoff = min(self.policy.backoff_max, backoff * 2)

    async def run(self):
        owned = self.client is None
        if owned:
            self.client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None))
        try:
            while True:
                self.target_changed.clear()
                target = self.current_target()
                if not target[2]:
                    await self._wait_target_changed(target)
                    continue
                fallback_needed = asyncio.Event()
                fallback_needed.set()
                tasks = [asyncio.create_task(self._wait_target_changed(target))]
                if self.policy.stream_enabled:
                    tasks.append(asyncio.create_task(self._watch(target, fallback_needed)))
                if self.policy.http_enabled:
                    tasks.append(asyncio.create_task(self._http(target, fallback_needed)))
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if owned:
                await self.client.close()
                self.client = None
