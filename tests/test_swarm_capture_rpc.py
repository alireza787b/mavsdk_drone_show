import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

from fleet_rpc import FleetRPCService
from src.drone_api_routes import DRONE_SWARM_STATE_ROUTE


def _params():
    return SimpleNamespace(drone_api_port=7070, GCS_COMMAND_HTTP_TIMEOUT_SEC=.2,
        GCS_FLEET_RPC_CONCURRENCY=2, GCS_FLEET_RECOVERY_CONCURRENCY=1)


@pytest.mark.asyncio
async def test_capture_rpc_is_get_only_and_preserves_native_clock_evidence():
    requests = []

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'hw_id': 1, 'emitted_at_ms': 1234,
            'global_position_timestamp_ms': 1200, 'attitude_timestamp_ms': 1100})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        records = await FleetRPCService(_params(), client=client).read_swarm_samples([{'hw_id': '1', 'ip': 'node1'}])
    assert [(r.method, r.url.path) for r in requests] == [('GET', DRONE_SWARM_STATE_ROUTE)]
    record = records['1']
    assert record['sample']['emitted_at_ms'] == 1234
    assert record['sample']['global_position_timestamp_ms'] == 1200
    assert record['sample']['attitude_timestamp_ms'] == 1100
    assert record['round_trip_ms'] >= 0
    assert 0 <= time.monotonic() - record['received_monotonic'] < 1


@pytest.mark.asyncio
async def test_capture_rpc_offline_peer_does_not_stall_healthy_sample():
    async def respond(request):
        if request.url.host == 'node1':
            await asyncio.sleep(1)
        return httpx.Response(200, json={'hw_id': 2})

    drones = [{'hw_id': str(i), 'ip': f'node{i}'} for i in (1, 2)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        records = await FleetRPCService(_params(), client=client).read_swarm_samples(drones)
    assert records['1']['sample'] == {}
    assert records['2']['sample']['hw_id'] == 2


@pytest.mark.asyncio
async def test_capture_rpc_rejects_mismatched_hardware_without_retrying_commands():
    async def respond(request):
        assert request.method == 'GET'
        return httpx.Response(200, json={'hw_id': 99})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        records = await FleetRPCService(_params(), client=client).read_swarm_samples([{'hw_id': '1', 'ip': 'node1'}])
    assert records['1']['sample'] == {}
