import asyncio
from types import SimpleNamespace

import httpx
import pytest

from fleet_telemetry import FleetTelemetryPoller


def params(limit=2):
    return SimpleNamespace(GCS_FLEET_RPC_CONCURRENCY=limit, telem_poll_interval=0.01,
                           drone_api_port=7070, GCS_TELEMETRY_REQUEST_TIMEOUT_SEC=0.1)


@pytest.mark.asyncio
async def test_slow_peer_does_not_delay_healthy_aircraft():
    samples = []
    async def request(req):
        if req.url.host == 'slow':
            await asyncio.sleep(0.15)
            raise httpx.ReadTimeout('injected outage')
        return httpx.Response(200, json={'update_time': 123})
    targets = [{'hw_id': '1', 'ip': 'slow'}, {'hw_id': '2', 'ip': 'healthy'}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        poller = FleetTelemetryPoller(params(), lambda: targets,
            lambda d, data, error: samples.append((d['hw_id'], data, error)), client=client)
        task = asyncio.create_task(poller.run())
        try:
            await asyncio.sleep(0.07)
            healthy = [s for s in samples if s[0] == '2']
            assert len(healthy) >= 3
            assert all(s[1]['update_time'] == 123 for s in healthy)
            assert not any(s[0] == '1' for s in samples)
            await asyncio.sleep(0.12)
            assert any(s[0] == '1' and s[1] is None and s[2] for s in samples)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_reassigned_peer_cannot_publish_old_endpoint_reply():
    gate, started = asyncio.Event(), asyncio.Event()
    samples = []
    targets = [{'hw_id': '1', 'ip': 'old'}]
    async def request(req):
        if req.url.host == 'old':
            started.set()
            await gate.wait()
        return httpx.Response(200, json={'endpoint': req.url.host})
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        poller = FleetTelemetryPoller(params(), lambda: targets,
            lambda d, data, error: samples.append((d['ip'], data)), client=client)
        task = asyncio.create_task(poller.run())
        try:
            await asyncio.wait_for(started.wait(), 1)
            targets[:] = [{'hw_id': '1', 'ip': 'new'}]
            gate.set()
            await asyncio.sleep(0.06)
            assert samples
            assert all(ip == 'new' and value['endpoint'] == 'new' for ip, value in samples)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_bounded_concurrency_and_shutdown_cancel_pending_requests():
    active, peak, ended = 0, 0, 0
    async def request(_):
        nonlocal active, peak, ended
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
            ended += 1
    targets = [{'hw_id': str(i), 'ip': f'node-{i}'} for i in range(10)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        task = asyncio.create_task(FleetTelemetryPoller(params(), lambda: targets, lambda *_: None, client=client).run())
        await asyncio.sleep(0.03)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert peak == 2
        assert active == 0 and ended == 2


@pytest.mark.asyncio
async def test_metadata_change_uses_current_slot_for_unavailable_peer():
    started, release = asyncio.Event(), asyncio.Event()
    targets = [{'hw_id': '1', 'ip': 'node', 'pos_id': 1}]
    seen = []
    async def request(_):
        started.set()
        await release.wait()
        raise httpx.ReadTimeout('injected outage')
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        task = asyncio.create_task(FleetTelemetryPoller(params(), lambda: targets,
            lambda drone, data, error: seen.append(drone['pos_id']), client=client).run())
        try:
            await asyncio.wait_for(started.wait(), 1)
            targets[:] = [{'hw_id': '1', 'ip': 'node', 'pos_id': 2}]
            release.set()
            await asyncio.sleep(0.04)
            assert seen and all(slot == 2 for slot in seen)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
