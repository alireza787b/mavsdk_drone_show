"""Read companion software reports on a bounded maintenance connection pool."""

import asyncio
import time

import httpx

from drone_api_routes import DRONE_GIT_STATUS_ROUTE


async def poll_git_reports(client, targets, *, port, timeout, concurrency, publish):
    """Publish each read independently so a slow companion cannot hold up its peers."""
    slots = asyncio.Semaphore(concurrency)

    async def read(drone):
        async with slots:
            hw_id = str(drone["hw_id"])
            started = int(time.time() * 1000)
            report = {"status": "unknown"}
            try:
                response = await client.get(f"http://{drone['ip']}:{port}{DRONE_GIT_STATUS_ROUTE}", timeout=timeout)
                response.raise_for_status()
                candidate = response.json()
                if isinstance(candidate, dict) and str(candidate.get("hw_id")) == hw_id and not candidate.get("error"):
                    report = {**candidate, "last_check": int(time.time() * 1000)}
            except (httpx.HTTPError, ValueError):
                pass
            publish(hw_id, started, report)

    await asyncio.gather(*(read(drone) for drone in targets))
