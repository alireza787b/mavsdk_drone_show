"""Bounded per-aircraft polling: an offline peer cannot stall healthy peers."""
from __future__ import annotations

import asyncio
import random

import httpx

from src.drone_api_routes import DRONE_STATE_ROUTE


class FleetTelemetryPoller:
    def __init__(self, params, targets, publish, *, client=None):
        self.params, self.targets, self.publish = params, targets, publish
        self.client = client
        self.limit = max(1, int(getattr(params, 'GCS_FLEET_RPC_CONCURRENCY', 48)))
        self.slots = asyncio.Semaphore(self.limit)
        self.interval = max(0.01, float(params.telem_poll_interval))

    def current(self):
        return {(str(d['hw_id']), d['ip']): d for d in self.targets()}

    async def _worker(self, key, drone):
        failures = 0
        while key in self.current():
            data, error = None, None
            try:
                async with self.slots:
                    response = await self.client.get(
                        f"http://{drone['ip']}:{self.params.drone_api_port}{DRONE_STATE_ROUTE}",
                        timeout=self.params.GCS_TELEMETRY_REQUEST_TIMEOUT_SEC,
                    )
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict):
                        raise ValueError('Drone telemetry must be an object')
                failures = 0
            except (httpx.HTTPError, ValueError):
                failures += 1
                error = 'Unable to obtain valid drone telemetry.'
            # A removed/reassigned endpoint's late reply cannot overwrite its
            # replacement. Native timestamps are left untouched.
            current_target = self.current().get(key)
            if current_target is None:
                return
            self.publish(current_target, data if error is None else None, error)
            delay = self.interval if not failures else min(30.0, self.interval * 2 ** min(failures, 5))
            await asyncio.sleep(delay if not failures else delay * random.uniform(0.8, 1.2))

    async def run(self):
        workers = {}
        owned = self.client is None
        if owned:
            self.client = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=self.limit, max_keepalive_connections=self.limit),
                trust_env=False,
            )
        try:
            while True:
                targets = self.current()
                removed = [key for key in workers if key not in targets]
                for key in removed:
                    workers[key].cancel()
                if removed:
                    await asyncio.gather(*(workers.pop(key) for key in removed), return_exceptions=True)
                for key, drone in targets.items():
                    if key not in workers:
                        workers[key] = asyncio.create_task(self._worker(key, drone))
                    elif workers[key].done():
                        # Surface programmer/callback failures rather than
                        # silently abandoning an aircraft's monitoring task.
                        workers[key].result()
                        workers[key] = asyncio.create_task(self._worker(key, drone))
                await asyncio.sleep(min(0.25, self.interval))
        finally:
            for task in workers.values():
                task.cancel()
            await asyncio.gather(*workers.values(), return_exceptions=True)
            if owned:
                await self.client.aclose()
                self.client = None
