import asyncio
from types import SimpleNamespace

import pytest

from src.drone_api_server import DroneAPIServer


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["connected", "timeout", "cancel"])
async def test_native_probe_closes_its_connection_iterator_on_every_exit(outcome):
    api = object.__new__(DroneAPIServer)
    api.params = SimpleNamespace(LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC=.03)
    started, closed = asyncio.Event(), asyncio.Event()
    async def stream():
        started.set()
        try:
            if outcome == "connected":
                yield SimpleNamespace(is_connected=True)
            await asyncio.Event().wait()
        finally:
            closed.set()
    drone = SimpleNamespace(core=SimpleNamespace(connection_state=stream))
    if outcome == "connected":
        await api._wait_for_mavsdk_connection(drone)
    elif outcome == "timeout":
        with pytest.raises((RuntimeError, TimeoutError, asyncio.TimeoutError)):
            await api._wait_for_mavsdk_connection(drone)
    else:
        task = asyncio.create_task(api._wait_for_mavsdk_connection(drone))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed.is_set()
