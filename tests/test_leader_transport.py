"""Transport fault injection only: no SDK, aircraft, Docker or discovery."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import aiohttp
import pytest

from smart_swarm_src.leader_transport import LeaderStateSupervisor, LeaderTransportPolicy


def policy(**changes):
    fields = dict(port=7070, poll_interval=0.01, request_timeout=0.03,
                  connect_timeout=0.04, sample_idle_timeout=0.04,
                  backoff_initial=0.02, backoff_max=0.08)
    fields.update(changes)
    return LeaderTransportPolicy(**fields)


def message(data):
    return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, json=lambda: data)


class Socket:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.closed = asyncio.Event()

    async def receive(self):
        return await self.messages.get()

    async def close(self):
        self.closed.set()


class Client:
    def __init__(self, connect):
        self.connect = connect
        self.http_samples = []
        self.probes = []
        self.count = 0

    async def ws_connect(self, url, **_kwargs):
        self.probes.append(asyncio.get_running_loop().time())
        return await self.connect(url)

    @asynccontextmanager
    async def get(self, url, **_kwargs):
        self.count += 1
        data = {"hw_id": 1, "sequence": self.count}
        self.http_samples.append((asyncio.get_running_loop().time(), url))
        async def json():
            return data
        yield SimpleNamespace(raise_for_status=lambda: None, json=json)


async def stop(task):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.002)
    await asyncio.wait_for(wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_http_continues_during_stalled_upgrade_and_reconnect_backoff():
    async def connect(_):
        await asyncio.Event().wait()
    client = Client(connect)
    accepted = []
    supervisor = LeaderStateSupervisor(lambda: (1, "1", "leader"), asyncio.Event(),
        lambda data, source: accepted.append((data, source)) or True, policy(), client=client)
    task = asyncio.create_task(supervisor.run())
    try:
        await until(lambda: len(client.probes) >= 3)
        assert len(client.http_samples) >= 8
        assert all(source == "http-fallback" for _, source in accepted)
        # Every bounded probe/backoff window contains HTTP work, rather than
        # alternating HTTP-only windows with connection/backoff-only windows.
        for start, end in zip(client.probes, client.probes[1:]):
            assert any(start <= timestamp <= end for timestamp, _ in client.http_samples)
    finally:
        await stop(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("traffic", [None, {"error": "unavailable"}, {"hw_id": 1, "sequence": 1}])
async def test_no_valid_advancing_data_closes_stream_and_enables_fallback(traffic):
    socket = Socket()
    async def connect(_):
        return socket
    client = Client(connect)
    accepted_ws = []
    def accept(data, source):
        if source == "ws" and not accepted_ws:
            accepted_ws.append(data)
            return True
        return source != "ws"
    supervisor = LeaderStateSupervisor(lambda: (1, "1", "leader"), asyncio.Event(), accept,
                                       policy(backoff_initial=0.2, backoff_max=0.2), client=client)
    task = asyncio.create_task(supervisor.run())
    async def inject():
        while True:
            if traffic is not None:
                socket.messages.put_nowait(message(traffic))
            await asyncio.sleep(0.005)
    injector = asyncio.create_task(inject())
    try:
        await asyncio.wait_for(socket.closed.wait(), 1)
        before = len(client.http_samples)
        await until(lambda: len(client.http_samples) >= before + 2)
        assert len(accepted_ws) <= 1
    finally:
        await stop(injector)
        await stop(task)


@pytest.mark.asyncio
async def test_healthy_stream_suppresses_http_until_valid_sample_deadline():
    socket = Socket()
    async def connect(_):
        return socket
    client = Client(connect)
    accepted = asyncio.Event()
    supervisor = LeaderStateSupervisor(lambda: (1, "1", "leader"), asyncio.Event(),
        lambda _data, source: (accepted.set() if source == "ws" else None) or True,
        policy(sample_idle_timeout=0.15), client=client)
    task = asyncio.create_task(supervisor.run())
    try:
        socket.messages.put_nowait(message({"hw_id": 1, "sequence": 1}))
        await asyncio.wait_for(accepted.wait(), 1)
        await asyncio.sleep(0.02)  # let the already-in-flight HTTP turn drain
        before = len(client.http_samples)
        await asyncio.sleep(0.04)
        assert len(client.http_samples) == before
        assert not socket.closed.is_set()
    finally:
        await stop(task)


@pytest.mark.asyncio
async def test_target_change_cancels_quiet_socket_without_waiting_for_a_message():
    socket = Socket()
    new_target = asyncio.Event()
    async def connect(url):
        if "new-leader" in url:
            new_target.set()
        return socket
    current = [(1, "1", "old-leader")]
    changed = asyncio.Event()
    client = Client(connect)
    supervisor = LeaderStateSupervisor(lambda: current[0], changed, lambda *_: True,
        policy(sample_idle_timeout=60, http_enabled=False), client=client)
    task = asyncio.create_task(supervisor.run())
    try:
        await until(lambda: client.probes)
        current[0] = (2, "2", "new-leader")
        changed.set()
        await asyncio.wait_for(new_target.wait(), 0.5)
        assert socket.closed.is_set()
    finally:
        await stop(task)


def test_old_target_reply_is_fenced_even_when_hw_id_and_ip_are_reused():
    current = [(1, "1", "leader")]
    applied = []
    supervisor = LeaderStateSupervisor(lambda: current[0], asyncio.Event(),
        lambda data, source: applied.append((data, source)) or True, policy())
    old = current[0]
    current[0] = (3, "1", "leader")
    assert not supervisor._offer(old, {"hw_id": 1}, "http-fallback")
    assert applied == []
    assert supervisor._offer(current[0], {"hw_id": 1}, "ws")


@pytest.mark.asyncio
async def test_cancellation_drains_http_probe_and_receive_tasks():
    cancelled = asyncio.Event()
    async def connect(_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    client = Client(connect)
    supervisor = LeaderStateSupervisor(lambda: (1, "1", "leader"), asyncio.Event(),
                                       lambda *_: True, policy(), client=client)
    task = asyncio.create_task(supervisor.run())
    await until(lambda: client.probes)
    await stop(task)
    assert cancelled.is_set()
    count = len(client.http_samples)
    await asyncio.sleep(0.02)
    assert len(client.http_samples) == count
