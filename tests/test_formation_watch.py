"""Formation transport is latest-state delivery, not flight-command delivery."""
import asyncio
import copy
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from formation_watch import FormationWatch, matches_etag, notify_formation_saved, snapshot
from api_routes.swarm import create_swarm_router
from smart_swarm_src.config_transport import FormationSubscription


def formation(offset=6):
    return [{"hw_id": 1, "follow": 0}, {"hw_id": 2, "follow": 1, "offset_x": offset}]


def test_atomic_save_preserves_existing_file_on_replace_failure(tmp_path, monkeypatch):
    import config as gcs_config
    path = tmp_path / 'swarm.json'
    gcs_config.save_swarm(formation(), file_path=str(path))
    original = path.read_bytes()
    def fail(*_):
        raise OSError('injected disk failure')
    monkeypatch.setattr(gcs_config.os, 'replace', fail)
    with pytest.raises(OSError):
        gcs_config.save_swarm(formation(9), file_path=str(path))
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_save_preserves_symlink_and_permissions(tmp_path):
    import config as gcs_config
    path = tmp_path / 'actual.json'
    gcs_config.save_swarm(formation(), file_path=str(path))
    path.chmod(0o640)
    link = tmp_path / 'swarm.json'
    link.symlink_to(path)
    gcs_config.save_swarm(formation(8), file_path=str(link))
    assert link.is_symlink()
    assert path.stat().st_mode & 0o777 == 0o640
    assert gcs_config.load_swarm(file_path=str(path))[1]['offset_x'] == 8


@pytest.mark.asyncio
async def test_canonical_save_wakes_watch_without_polling(tmp_path, monkeypatch):
    import config as gcs_config
    path = tmp_path / 'swarm.json'
    monkeypatch.setattr(gcs_config, 'SWARM_FILE_PATH', str(path))
    gcs_config.save_swarm(formation())
    watch = FormationWatch(gcs_config.load_swarm, interval=60)
    async with watch.subscribe() as queue:
        await queue.get()
        await asyncio.sleep(0.02)
        while not queue.empty():
            queue.get_nowait()
        gcs_config.save_swarm(formation(9))
        received = await asyncio.wait_for(queue.get(), 0.5)
        assert received['revision'] == snapshot(formation(9))['revision']


@pytest.mark.parametrize("header,expected", [
    ('"abc"', True), ('W/"abc"', True), ('"other", W/"abc"', True),
    ("*", True), ('"other"', False), (None, False), ("abc", False),
])
def test_http_validator(header, expected):
    assert matches_etag(header, "abc") is expected


def test_config_get_conditional_read():
    app = FastAPI()
    app.include_router(create_swarm_router(SimpleNamespace(load_swarm=formation)))
    with TestClient(app) as client:
        response = client.get("/api/v1/config/swarm")
        assert response.status_code == 200
        etag = response.headers["etag"]
        unchanged = client.get("/api/v1/config/swarm", headers={"If-None-Match": etag})
        assert unchanged.status_code == 304
        assert unchanged.content == b""
        assert unchanged.headers["etag"] == etag


def test_watch_authorizes_before_accept(monkeypatch):
    async def deny(socket, **_kwargs):
        await socket.close(code=1008)
        return None
    monkeypatch.setattr('api_routes.swarm.authorize_websocket', deny)
    app = FastAPI()
    app.include_router(create_swarm_router(SimpleNamespace(load_swarm=formation)))
    from starlette.websockets import WebSocketDisconnect
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect('/ws/swarm-config'):
            pass
    assert error.value.code == 1008


def test_watch_initial_resource(monkeypatch):
    async def allow(_, **_kwargs):
        return {'kind': 'test'}
    monkeypatch.setattr('api_routes.swarm.authorize_websocket', allow)
    app = FastAPI()
    app.include_router(create_swarm_router(SimpleNamespace(load_swarm=formation)))
    with TestClient(app) as client:
        with client.websocket_connect('/ws/swarm-config') as socket:
            message = socket.receive_json()
            assert message == {'type': 'swarm_config', 'data': snapshot(formation())}


@pytest.mark.asyncio
@pytest.mark.parametrize('api_auth,machine,allowed', [(False, True, True), (True, True, False), (False, False, False)])
async def test_machine_watch_matches_http_auth_posture(monkeypatch, api_auth, machine, allowed):
    from unittest.mock import AsyncMock
    from auth_runtime import authorize_websocket
    service = SimpleNamespace(
        settings=SimpleNamespace(any_auth_enabled=True, api_auth_enabled=api_auth),
        authenticate_bearer=lambda *_args, **_kwargs: None,
        verify_session=lambda *_args: None,
    )
    monkeypatch.setattr('auth_runtime.build_auth_service', lambda: service)
    socket = SimpleNamespace(headers={}, query_params={}, cookies={}, client=None, close=AsyncMock())
    result = await authorize_websocket(socket, machine_endpoint=machine)
    assert bool(result) is allowed
    if allowed:
        socket.close.assert_not_awaited()
    else:
        socket.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_latest_only_initial_snapshot_and_external_reconciliation():
    current = formation()
    watch = FormationWatch(lambda: copy.deepcopy(current), interval=0.02)
    async with watch.subscribe() as queue:
        assert (await queue.get())["revision"] == snapshot(current)["revision"]
        current = formation(7)
        notify_formation_saved()
        await asyncio.sleep(0.04)
        current = formation(8)
        # Simulates a Git/external replacement without a save notification.
        await asyncio.sleep(0.06)
        assert queue.qsize() == 1
        assert (await queue.get())["revision"] == snapshot(current)["revision"]
    assert watch.task is None
    assert not watch.queues


@pytest.mark.asyncio
async def test_invalid_external_file_never_replaces_last_valid_snapshot():
    current = formation()
    watch = FormationWatch(lambda: copy.deepcopy(current), interval=0.02)
    async with watch.subscribe() as queue:
        await queue.get()
        await asyncio.sleep(0.04)
        while not queue.empty():
            queue.get_nowait()
        current = []
        await asyncio.sleep(0.05)
        assert queue.empty()
        current = formation(9)
        assert (await asyncio.wait_for(queue.get(), 0.2))["revision"] == snapshot(current)["revision"]


def test_subscription_validates_deduplicates_and_coalesces():
    client = FormationSubscription("http://gcs:5030/api/v1/config/swarm", {})
    assert client.accept(snapshot(formation()))
    assert not client.accept(snapshot(formation()))
    assert client.accept(snapshot(formation(8)))
    assert client.queue.qsize() == 1
    assert client.queue.get_nowait()[1]["offset_x"] == 8
    with pytest.raises(ValueError):
        client.accept({**snapshot(formation()), "revision": "0" * 64})
    with pytest.raises(ValueError):
        client.accept([])
    assert client.latest[1]["offset_x"] == 8


@pytest.mark.asyncio
async def test_websocket_initial_push_updates_and_cleanup():
    connected = asyncio.Event()
    publish = asyncio.Event()

    async def stream(request):
        assert request.headers["Authorization"] == "Bearer test-only"
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        await socket.send_json({"type": "swarm_config", "data": snapshot(formation())})
        connected.set()
        await publish.wait()
        await socket.send_json({"type": "swarm_config", "data": snapshot(formation(9))})
        async for _ in socket:
            pass
        return socket

    async def read(_):
        return web.json_response(snapshot(formation()))

    app = web.Application()
    app.router.add_get("/ws/swarm-config", stream)
    app.router.add_get("/api/v1/config/swarm", read)
    async with TestServer(app) as server:
        client = FormationSubscription(str(server.make_url("/api/v1/config/swarm")),
                                       {"Authorization": "Bearer test-only"})
        async with client.run():
            await asyncio.wait_for(connected.wait(), 1)
            await asyncio.sleep(0.02)
            assert client.connected
            publish.set()
            for _ in range(30):
                if client.latest[1]["offset_x"] == 9:
                    break
                await asyncio.sleep(0.01)
            assert client.latest[1]["offset_x"] == 9
        assert client.client is None
        assert not client.connected


@pytest.mark.asyncio
async def test_old_server_http_fallback_and_conditional_requests():
    seen = []
    async def read(request):
        seen.append(request.headers.get("If-None-Match"))
        if seen[-1]:
            return web.Response(status=304)
        return web.json_response(snapshot(formation()))
    app = web.Application()
    app.router.add_get("/api/v1/config/swarm", read)
    async with TestServer(app) as server:
        client = FormationSubscription(str(server.make_url("/api/v1/config/swarm")), {}, fallback_sec=0.02)
        async with client.run():
            for _ in range(30):
                if len(seen) >= 2:
                    break
                await asyncio.sleep(0.01)
            assert client.latest[1]["offset_x"] == 6
            assert seen[0] is None
            assert seen[1] == f'"{client.revision}"'
            assert not client.connected


@pytest.mark.asyncio
async def test_watch_reconnect_resynchronizes_current_snapshot():
    attempts = 0
    current = formation()
    async def stream(request):
        nonlocal attempts, current
        attempts += 1
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        if attempts > 1:
            current = formation(11)
        await socket.send_json({'type': 'swarm_config', 'data': snapshot(current)})
        if attempts == 1:
            await socket.close()
        else:
            async for _ in socket:
                pass
        return socket
    async def read(_):
        return web.json_response(snapshot(current))
    app = web.Application()
    app.router.add_get('/ws/swarm-config', stream)
    app.router.add_get('/api/v1/config/swarm', read)
    async with TestServer(app) as server:
        client = FormationSubscription(str(server.make_url('/api/v1/config/swarm')), {},
                                       fallback_sec=0.02, backoff_max_sec=0.02)
        async with client.run():
            for _ in range(100):
                if client.latest and client.latest[1]['offset_x'] == 11:
                    break
                await asyncio.sleep(0.01)
            assert attempts >= 2
            assert client.latest[1]['offset_x'] == 11


@pytest.mark.asyncio
async def test_healthy_watch_does_not_keep_two_second_http_poll():
    reads = 0
    async def stream(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        await socket.send_json({'type': 'swarm_config', 'data': snapshot(formation())})
        async for _ in socket:
            pass
        return socket
    async def read(_):
        nonlocal reads
        reads += 1
        return web.json_response(snapshot(formation()))
    app = web.Application()
    app.router.add_get('/ws/swarm-config', stream)
    app.router.add_get('/api/v1/config/swarm', read)
    async with TestServer(app) as server:
        client = FormationSubscription(str(server.make_url('/api/v1/config/swarm')), {})
        async with client.run():
            await asyncio.sleep(2.2)
            assert client.connected
            assert reads == 1


@pytest.mark.asyncio
async def test_http_response_cannot_undo_newer_stream_update():
    started, release = asyncio.Event(), asyncio.Event()
    async def read(_):
        started.set()
        await release.wait()
        return web.json_response(snapshot(formation()))
    app = web.Application()
    app.router.add_get("/api/v1/config/swarm", read)
    async with TestServer(app) as server:
        client = FormationSubscription(str(server.make_url("/api/v1/config/swarm")), {})
        async with client.run():
            await asyncio.wait_for(started.wait(), 1)
            client.accept(snapshot(formation(10)))
            release.set()
            await asyncio.sleep(0.05)
            assert client.latest[1]["offset_x"] == 10
