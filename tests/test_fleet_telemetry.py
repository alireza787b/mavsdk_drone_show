import asyncio
from types import SimpleNamespace

import aiohttp
import httpx
import pytest

from fleet_telemetry import FleetTelemetryPoller, _valid_sample


async def no_stream(*_args, **_kwargs):
    raise OSError('injected HTTP-only companion')


class StateSocket:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.closed = False

    async def receive_json(self):
        message = await self.messages.get()
        if isinstance(message, Exception):
            raise message
        return message

    async def close(self):
        self.closed = True


async def until(predicate, timeout=1):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.002)


async def stop(task):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


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
            lambda d, data, error: samples.append((d['hw_id'], data, error)), client=client, ws_connect=no_stream)
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
        return httpx.Response(200, json={'endpoint': req.url.host, 'update_time': 123})
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        poller = FleetTelemetryPoller(params(), lambda: targets,
            lambda d, data, error: samples.append((d['ip'], data)), client=client, ws_connect=no_stream)
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
        task = asyncio.create_task(FleetTelemetryPoller(params(), lambda: targets, lambda *_: None,
            client=client, ws_connect=no_stream).run())
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
            lambda drone, data, error: seen.append(drone['pos_id']), client=client, ws_connect=no_stream).run())
        try:
            await asyncio.wait_for(started.wait(), 1)
            targets[:] = [{'hw_id': '1', 'ip': 'node', 'pos_id': 2}]
            release.set()
            await asyncio.sleep(0.04)
            assert seen and all(slot == 2 for slot in seen)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize('payload', [
    {}, [], {'error': 'not available', 'timestamp': 123},
    {'hw_id': '2', 'update_time': 123}, {'hw_id': None, 'update_time': 123},
    {'hw_id': True, 'update_time': 123}, {'hw_id': '1', 'timestamp': float('nan')},
    {'hw_id': '1', 'update_time': 0}, {'hw_id': '1', 'timestamp': True},
])
def test_invalid_or_foreign_state_cannot_establish_transport_health(payload):
    for stream in (True, False):
        with pytest.raises(ValueError):
            _valid_sample(payload, '1', stream=stream)


def test_legacy_http_identity_strategy_preserves_native_clocks():
    legacy = {'update_time': 123, 'global_position_timestamp_ms': 1000}
    assert _valid_sample(legacy, '1', stream=False) is legacy
    with pytest.raises(ValueError, match='identity is missing'):
        _valid_sample(legacy, '1', stream=True)
    modern = {'hw_id': 1, 'update_time': 123, 'timestamp': 123000}
    assert _valid_sample(modern, '01', stream=True) is modern
    assert modern == {'hw_id': 1, 'update_time': 123, 'timestamp': 123000}


@pytest.mark.asyncio
async def test_hanging_stream_probes_do_not_interrupt_sequential_http_fallback():
    calls, active_http, peak_http, active_probes, peak_probes = 0, 0, 0, 0, 0

    async def request(_):
        nonlocal calls, active_http, peak_http
        active_http += 1
        peak_http = max(peak_http, active_http)
        try:
            await asyncio.sleep(0.002)
            calls += 1
            return httpx.Response(200, json={'hw_id': '1', 'update_time': 123})
        finally:
            active_http -= 1

    async def connect(*_args, **_kwargs):
        nonlocal active_probes, peak_probes
        active_probes += 1
        peak_probes = max(peak_probes, active_probes)
        try:
            await asyncio.Event().wait()
        finally:
            active_probes -= 1

    settings = params(1)
    settings.GCS_TELEMETRY_WS_CONNECT_TIMEOUT_SEC = 0.02
    targets = [{'hw_id': '1', 'ip': 'node'}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        owner = FleetTelemetryPoller(settings, lambda: targets, lambda *_: None, client=client, ws_connect=connect)
        owner._retry_delay = lambda *_args, **_kwargs: 0.01
        task = asyncio.create_task(owner.run())
        try:
            await until(lambda: calls >= 5)
            assert peak_http == peak_probes == 1
        finally:
            await stop(task)
        assert active_http == active_probes == 0


@pytest.mark.asyncio
async def test_valid_stream_takes_over_and_fences_older_http_response():
    socket, started, release = StateSocket(), asyncio.Event(), asyncio.Event()
    samples, calls = [], 0
    async def request(_):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return httpx.Response(200, json={'hw_id': '1', 'update_time': 122, 'via': 'old-http'})
    async def connect(*_args, **_kwargs):
        return socket
    targets = [{'hw_id': '1', 'ip': 'node'}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        task = asyncio.create_task(FleetTelemetryPoller(params(), lambda: targets,
            lambda _drone, data, error: samples.append((data, error)), client=client, ws_connect=connect).run())
        try:
            await asyncio.wait_for(started.wait(), 1)
            sample = {'hw_id': 1, 'update_time': 123, 'timestamp': 123000,
                      'global_position_timestamp_ms': 120000, 'stream_seq': 8, 'via': 'ws'}
            await socket.messages.put(sample)
            await until(lambda: bool(samples))
            release.set()
            await asyncio.sleep(0.04)
            assert calls == 1
            assert samples == [(sample, None)]
            assert sample['update_time'] == 123 and sample['global_position_timestamp_ms'] == 120000
        finally:
            await stop(task)
        assert socket.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('junk_frames', [False, True])
async def test_stream_silence_or_invalid_frame_traffic_resumes_http(junk_frames):
    class Socket(StateSocket):
        async def receive_json(self):
            if self.messages.empty() and junk_frames:
                await asyncio.sleep(0.003)
                raise ValueError('invalid JSON')
            return await super().receive_json()
    socket, samples, calls = Socket(), [], 0
    await socket.messages.put({'hw_id': '1', 'update_time': 123, 'via': 'ws'})
    async def connect(*_args, **_kwargs):
        return socket
    async def request(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={'hw_id': '1', 'update_time': 124, 'via': 'http'})
    settings = params()
    settings.GCS_TELEMETRY_WS_IDLE_TIMEOUT_SEC = 0.04
    targets = [{'hw_id': '1', 'ip': 'node'}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        task = asyncio.create_task(FleetTelemetryPoller(settings, lambda: targets,
            lambda _drone, data, _error: samples.append(data), client=client, ws_connect=connect).run())
        try:
            await until(lambda: any(row and row.get('via') == 'ws' for row in samples))
            before = calls
            await until(lambda: socket.closed and calls > before)
            assert samples[-1]['via'] == 'http'
        finally:
            await stop(task)


@pytest.mark.asyncio
async def test_foreign_stream_does_not_disable_http_or_publish_foreign_identity():
    socket, samples = StateSocket(), []
    await socket.messages.put({'hw_id': '2', 'update_time': 123})
    async def connect(*_args, **_kwargs):
        return socket
    async def request(_):
        return httpx.Response(200, json={'hw_id': '1', 'update_time': 123})
    targets = [{'hw_id': '1', 'ip': 'node'}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        task = asyncio.create_task(FleetTelemetryPoller(params(), lambda: targets,
            lambda _drone, data, error: samples.append((data, error)), client=client, ws_connect=connect).run())
        try:
            await until(lambda: len(samples) >= 3)
            assert socket.closed
            assert all(data['hw_id'] == '1' and error is None for data, error in samples)
        finally:
            await stop(task)


@pytest.mark.asyncio
async def test_foreign_http_identity_is_unavailable_not_relabelled_as_expected_aircraft():
    samples = []
    async def request(_):
        return httpx.Response(200, json={'hw_id': '99', 'update_time': 123})
    targets = [{'hw_id': '1', 'ip': 'node'}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        task = asyncio.create_task(FleetTelemetryPoller(params(), lambda: targets,
            lambda _drone, data, error: samples.append((data, error)), client=client, ws_connect=no_stream).run())
        try:
            await until(lambda: bool(samples))
            assert samples[0][0] is None
            assert 'identity does not match H1' in samples[0][1]
        finally:
            await stop(task)


@pytest.mark.asyncio
async def test_probe_capacity_does_not_consume_http_capacity():
    active, peak, samples = 0, 0, []
    async def connect(*_args, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
    async def request(req):
        return httpx.Response(200, json={'hw_id': req.url.host.split('-')[1], 'update_time': 123})
    targets = [{'hw_id': str(i), 'ip': f'node-{i}'} for i in range(12)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        task = asyncio.create_task(FleetTelemetryPoller(params(2), lambda: targets,
            lambda drone, data, error: samples.append((drone['hw_id'], data, error)),
            client=client, ws_connect=connect).run())
        try:
            await until(lambda: len({row[0] for row in samples}) == 12)
            assert peak == 2
            assert all(row[1] is not None and row[2] is None for row in samples)
        finally:
            await stop(task)
        assert active == 0


@pytest.mark.asyncio
async def test_http_only_companion_uses_slow_capability_probes_without_pausing_http():
    probes, samples = 0, []
    async def connect(*_args, **_kwargs):
        nonlocal probes
        probes += 1
        raise aiohttp.WSServerHandshakeError(SimpleNamespace(real_url='http://node/ws/drone-state'),
                                            (), status=404, message='HTTP-only legacy node')
    async def request(_):
        return httpx.Response(200, json={'update_time': 123})
    targets = [{'hw_id': '1', 'ip': 'node'}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        task = asyncio.create_task(FleetTelemetryPoller(params(), lambda: targets,
            lambda _drone, data, error: samples.append((data, error)), client=client, ws_connect=connect).run())
        try:
            await until(lambda: len(samples) >= 4)
            assert probes == 1
            assert all(data == {'update_time': 123} and error is None for data, error in samples)
        finally:
            await stop(task)


@pytest.mark.asyncio
async def test_more_than_probe_limit_can_keep_established_streams():
    targets = [{'hw_id': str(i), 'ip': f'node-{i}'} for i in range(101)]
    sockets, observed = [], set()
    async def connect(url, **_kwargs):
        socket = StateSocket()
        sockets.append(socket)
        hw_id = httpx.URL(url).host.split('-')[1]
        await socket.messages.put({'hw_id': hw_id, 'update_time': 123, 'via': 'ws'})
        return socket
    async def request(req):
        return httpx.Response(200, json={'hw_id': req.url.host.split('-')[1], 'update_time': 123})
    def publish(drone, data, _error):
        if data and data.get('via') == 'ws':
            observed.add(drone['hw_id'])
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        task = asyncio.create_task(FleetTelemetryPoller(params(2), lambda: targets, publish,
            client=client, ws_connect=connect).run())
        try:
            await until(lambda: len(observed) == 101)
            assert len(sockets) == 101
            assert not any(socket.closed for socket in sockets)
        finally:
            await stop(task)
        assert all(socket.closed for socket in sockets)


def test_offline_backoff_is_capped_and_duplicate_identity_has_one_owner(monkeypatch):
    monkeypatch.setattr('fleet_telemetry.random.uniform', lambda *_: 1)
    settings = params()
    settings.telem_poll_interval = 1
    targets = [{'hw_id': '01', 'ip': 'old'}, {'hw_id': 1, 'ip': 'current'}]
    owner = FleetTelemetryPoller(settings, lambda: targets, lambda *_: None, ws_connect=no_stream)
    assert list(owner.current()) == [('1', 'current')]
    assert [owner._retry_delay(i) for i in (1, 2, 3, 4, 5, 100)] == [2, 4, 8, 16, 30, 30]


@pytest.mark.asyncio
async def test_stream_endpoint_reassignment_closes_old_socket_and_uses_current_metadata():
    sockets = {'old': StateSocket(), 'new': StateSocket()}
    targets, samples = [{'hw_id': '1', 'ip': 'old', 'pos_id': 1}], []
    async def connect(url, **_kwargs):
        host = httpx.URL(url).host
        return sockets[host]
    async def request(req):
        return httpx.Response(200, json={'hw_id': '1', 'update_time': 123, 'endpoint': req.url.host})
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        task = asyncio.create_task(FleetTelemetryPoller(params(), lambda: targets,
            lambda drone, data, error: samples.append((dict(drone), data, error)), client=client, ws_connect=connect).run())
        try:
            await sockets['old'].messages.put({'hw_id': '1', 'update_time': 123, 'endpoint': 'old'})
            await until(lambda: any(row[1] and row[1].get('endpoint') == 'old' for row in samples))
            samples.clear()
            targets[:] = [{'hw_id': '1', 'ip': 'new', 'pos_id': 2}]
            await sockets['old'].messages.put({'hw_id': '1', 'update_time': 124, 'endpoint': 'old'})
            await sockets['new'].messages.put({'hw_id': '1', 'update_time': 125, 'endpoint': 'new'})
            await until(lambda: sockets['old'].closed and bool(samples))
            assert all(drone['ip'] == 'new' and drone['pos_id'] == 2 and data['endpoint'] == 'new'
                       for drone, data, error in samples)
        finally:
            await stop(task)
        assert all(socket.closed for socket in sockets.values())


@pytest.mark.asyncio
async def test_stream_publication_programming_failure_is_not_hidden_as_transport_retry():
    socket = StateSocket()
    await socket.messages.put({'hw_id': '1', 'update_time': 123})
    async def connect(*_args, **_kwargs):
        return socket
    async def request(_):
        await asyncio.Event().wait()
    def publish(*_args):
        raise ValueError('injected publication failure')
    targets = [{'hw_id': '1', 'ip': 'node'}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(request)) as client:
        owner = FleetTelemetryPoller(params(), lambda: targets, publish, client=client, ws_connect=connect)
        with pytest.raises(ValueError, match='injected publication failure'):
            await asyncio.wait_for(owner.run(), timeout=1)
        assert socket.closed
