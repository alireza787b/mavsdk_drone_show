"""Shared observations remain bounded, truthful and independent of actuation."""
import asyncio
import json
import time
from contextlib import AsyncExitStack
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import observation_stream as stream
from api_routes.core import create_core_router
from api_routes.core import _build_typed_telemetry_response
from api_routes.git_status import create_git_router
from schemas import TelemetrySnapshotStreamMessage
from tests.test_gcs_core_routes import _make_deps
from tests.test_gcs_api_websocket import _make_git_deps


def make_publisher(**kwargs):
    calls = []
    def build():
        calls.append(True)
        return {"timestamp": 1000, "value": len(calls)}
    return stream.LatestObservationPublisher(
        build, lambda body: {"type": "test", "timestamp": body["timestamp"], "data": body},
        interval=60, **kwargs,
    ), calls


@pytest.mark.asyncio
async def test_one_build_and_serialization_per_generation_with_latest_only_subscribers():
    publisher, calls = make_publisher()
    async with publisher.subscribe() as first, publisher.subscribe() as second:
        initial = await first.get()
        assert await second.get() is initial
        assert len(calls) == 1
        assert publisher.current() is initial
        for _ in range(3):
            publisher.published_monotonic -= 61
            newest = publisher.current()
        assert len(calls) == 4
        assert first.qsize() == second.qsize() == 1
        assert await first.get() is await second.get() is newest
        assert newest.metadata["sequence"] == 4
        assert newest.metadata["stream_id"] == initial.metadata["stream_id"]
        assert json.loads(newest.versioned_json)["delivery"] == "latest_snapshot"
    assert not publisher.queues
    assert publisher.task is None


@pytest.mark.asyncio
async def test_subscriber_capacity_and_build_failure_do_not_invent_empty_success():
    publisher, _ = make_publisher(max_subscribers=1)
    async with publisher.subscribe():
        with pytest.raises(stream.ObservationCapacityError):
            async with publisher.subscribe():
                pass
    def fail():
        raise ValueError("Invalid native observation")
    publisher.build = fail
    publisher.published_monotonic -= 61
    with pytest.raises(stream.ObservationUnavailableError):
        publisher.current()
    assert publisher.latest is None


def test_publication_epoch_and_payload_bytes_are_bounded():
    first, _ = make_publisher()
    second, _ = make_publisher()
    assert first.current().metadata["stream_id"] != second.current().metadata["stream_id"]
    bounded, _ = make_publisher(max_snapshot_bytes=1)
    with pytest.raises(stream.ObservationUnavailableError):
        bounded.current()
    assert bounded.sequence == 0


@pytest.mark.asyncio
async def test_peer_disconnect_cancels_sender_and_retires_publisher():
    publisher, _ = make_publisher()
    socket = SimpleNamespace(
        query_params={}, receive=AsyncMock(return_value={"type": "websocket.disconnect"}),
        send_text=AsyncMock(), close=AsyncMock(),
    )
    await stream.serve_observations(socket, publisher)
    assert not publisher.queues and publisher.task is None


@pytest.mark.asyncio
async def test_slow_consumer_send_is_bounded_and_cleanup_is_complete(monkeypatch):
    publisher, _ = make_publisher()
    stopped = asyncio.Event()
    async def blocked():
        await stopped.wait()
    socket = SimpleNamespace(
        query_params={}, receive=blocked, send_text=AsyncMock(side_effect=lambda _: blocked()), close=AsyncMock(),
    )
    # AsyncMock does not await a coroutine returned by a synchronous side effect.
    async def send(_):
        await blocked()
    socket.send_text = send
    monkeypatch.setattr(stream, "SEND_TIMEOUT_SEC", 0.01)
    await asyncio.wait_for(stream.serve_observations(socket, publisher), 1)
    socket.close.assert_awaited_once_with(code=1013, reason="slow_observation_consumer")
    assert not publisher.queues and publisher.task is None


@pytest.mark.asyncio
async def test_idle_publication_and_revocation_checks_are_bounded(monkeypatch):
    publisher, _ = make_publisher()
    stopped = asyncio.Event()
    async def blocked():
        await stopped.wait()
    socket = SimpleNamespace(query_params={"protocol_version": "1"}, receive=blocked,
        send_text=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(stream, "IDLE_TIMEOUT_SEC", 0.02)
    await asyncio.wait_for(stream.serve_observations(socket, publisher), 1)
    socket.close.assert_awaited_once_with(code=1013, reason="observation_idle")
    assert not publisher.queues and publisher.task is None

    monkeypatch.setattr(stream, "IDLE_TIMEOUT_SEC", 15)
    monkeypatch.setattr(stream, "AUTH_RECHECK_SEC", 0.01)
    check = AsyncMock(return_value=False)
    monkeypatch.setattr(stream, "revalidate_websocket", check)
    await asyncio.wait_for(stream.serve_observations(socket, publisher, auth_context={"kind": "bearer"}), 1)
    check.assert_awaited_once()
    assert not publisher.queues and publisher.task is None


def test_versioned_http_and_websocket_share_generation_and_native_evidence(monkeypatch):
    monkeypatch.setenv("MDS_AUTH_ENABLED", "false")
    monkeypatch.setenv("MDS_API_AUTH_ENABLED", "false")
    deps = _make_deps()
    native = deps.telemetry_data_all_drones["1"]
    native.update(telemetry_available=False, update_time=1000, is_armed=True, landed_state=None)
    before = deepcopy(native)
    deps.get_all_heartbeats = lambda: {"1": {"received_at_gcs_ms": 1700000001234,
        "timestamp": 9999999999999, "network_info": {"wifi": {"ssid": "New"}}}}
    app = FastAPI()
    app.include_router(create_core_router(deps))
    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry?protocol_version=1") as socket:
            message = socket.receive_json()
            TelemetrySnapshotStreamMessage.model_validate(message)
            body = client.get("/api/v1/fleet/telemetry?protocol_version=1").json()
            assert body["telemetry"] == message["data"]
            for key in ("stream_id", "sequence", "published_at_ms", "display_policy"):
                assert body[key] == message[key]
        legacy = client.get("/api/v1/fleet/telemetry").json()
        assert "protocol_version" not in legacy and "stream_id" not in legacy
    row = message["data"]["1"]
    assert row["heartbeat_last_seen"] == 1700000001234
    assert row["timestamp"] == before["timestamp"]
    assert row["update_time"] == 1000 and row["is_armed"] is True
    assert row["telemetry_available"] is False and row["landed_state"] is None
    assert native == before


def test_heartbeat_versioned_http_parity_and_explicit_rejected_receipt(monkeypatch):
    monkeypatch.setenv("MDS_AUTH_ENABLED", "false")
    monkeypatch.setenv("MDS_API_AUTH_ENABLED", "false")
    deps = _make_deps()
    deps.handle_heartbeat_post.return_value = {"accepted": False, "message": "Runtime mode mismatch"}
    app = FastAPI()
    app.include_router(create_core_router(deps))
    with TestClient(app) as client:
        with client.websocket_connect("/ws/heartbeats?protocol_version=1") as socket:
            message = socket.receive_json()
            body = client.get("/api/v1/fleet/heartbeats?protocol_version=1").json()
            assert message["data"] == body["heartbeats"]
            assert message["sequence"] == body["sequence"]
        receipt = client.post("/api/v1/fleet/heartbeats", json={"hw_id": "1", "pos_id": 1}).json()
        assert receipt["success"] is True and receipt["accepted"] is False
        assert receipt["message"] == "Runtime mode mismatch"


def test_git_build_failure_closes_stream_instead_of_reporting_zero_aircraft(monkeypatch):
    monkeypatch.setenv("MDS_AUTH_ENABLED", "false")
    monkeypatch.setenv("MDS_API_AUTH_ENABLED", "false")
    deps = _make_git_deps()
    deps.load_config = lambda: (_ for _ in ()).throw(ValueError("Invalid configuration"))
    app = FastAPI()
    app.include_router(create_git_router(deps))
    with TestClient(app) as client:
        with client.websocket_connect("/ws/git-status?protocol_version=1") as socket:
            with pytest.raises(WebSocketDisconnect) as error:
                socket.receive_json()
        assert error.value.code == 1011
        assert error.value.reason == "observation_unavailable"


def test_unknown_protocol_closes_explicitly_without_fallback_claim(monkeypatch):
    monkeypatch.setenv("MDS_AUTH_ENABLED", "false")
    monkeypatch.setenv("MDS_API_AUTH_ENABLED", "false")
    app = FastAPI()
    app.include_router(create_core_router(_make_deps()))
    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry?protocol_version=2") as socket:
            with pytest.raises(WebSocketDisconnect) as error:
                socket.receive_json()
        assert error.value.code == 1002


@pytest.mark.asyncio
async def test_synthetic_100_aircraft_five_clients_measured_publication_cost(monkeypatch, record_property):
    """Deterministic work/byte accounting, not a network-throughput benchmark.

    Four clients drain every generation. The fifth drains only at the end. The
    former per-client path is measured with the identical typed fleet/envelope;
    modern metadata adds bytes rather than pretending snapshots compress data.
    """
    deps = _make_deps()
    template = deps.telemetry_data_all_drones["1"]
    native_start = int(time.time() * 1000) - 1200
    deps.telemetry_data_all_drones = {
        str(index): {**deepcopy(template), "hw_id": str(index), "pos_id": index,
            "timestamp": native_start, "update_time": native_start}
        for index in range(1, 101)
    }
    builds = 0
    serializations = 0
    real_dumps = json.dumps
    def measured_dumps(*args, **kwargs):
        nonlocal serializations
        serializations += 1
        return real_dumps(*args, **kwargs)
    monkeypatch.setattr(stream.json, "dumps", measured_dumps)
    def build():
        nonlocal builds
        builds += 1
        return _build_typed_telemetry_response(deps).model_dump(mode="json")
    publisher = stream.LatestObservationPublisher(
        build,
        lambda body: {"type": "telemetry", "timestamp": body["timestamp"], "data": body["telemetry"]},
        interval=60,
        modern_fields=lambda body: {"display_policy": body["display_policy"]},
    )
    old_full_bytes = modern_full_bytes = delivered_bytes = old_builds = 0
    source_ages, old_source_ages = [], []
    max_queue_depth = 0
    async with AsyncExitStack() as stack:
        queues = [await stack.enter_async_context(publisher.subscribe()) for _ in range(5)]
        for generation in range(10):
            if generation:
                for row in deps.telemetry_data_all_drones.values():
                    row["timestamp"] = native_start + generation * 10
                    row["update_time"] = row["timestamp"]
                publisher.published_monotonic -= 61
            publication = publisher.current()
            for _ in range(5):
                # Exercise the old independently built/encoded read path for
                # each client, not an extrapolated server-work percentage.
                old_body = _build_typed_telemetry_response(deps).model_dump(mode="json")
                old_message = {"type": "telemetry", "timestamp": old_body["timestamp"], "data": old_body["telemetry"]}
                old_frame = real_dumps(old_message, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
                old_full_bytes += len(old_frame.encode("utf-8"))
                old_builds += 1
                old_source_ages.extend(old_body["timestamp"] - row["timestamp"] for row in old_body["telemetry"].values())
            modern_full_bytes += len(publication.versioned_json.encode("utf-8")) * 5
            for queue in queues[:4]:
                received = await queue.get()
                assert received is publication
                delivered_bytes += len(received.versioned_json.encode("utf-8"))
            max_queue_depth = max(max_queue_depth, *(queue.qsize() for queue in queues))
            for hw_id, row in publication.body["telemetry"].items():
                assert row["timestamp"] == deps.telemetry_data_all_drones[hw_id]["timestamp"]
                assert row["update_time"] == row["timestamp"]
                source_ages.append(publication.metadata["published_at_ms"] - row["timestamp"])
        slow_latest = await queues[-1].get()
        assert slow_latest.metadata["sequence"] == 10
        delivered_bytes += len(slow_latest.versioned_json.encode("utf-8"))
    assert builds == 10 and old_builds == 50
    assert serializations == 20  # Legacy and v1 encodings, each once/generation.
    assert max_queue_depth == 1
    assert modern_full_bytes > old_full_bytes  # Metadata is overhead, not compression.
    assert not publisher.queues and publisher.task is None
    record_property("observation_synthetic_metrics", real_dumps({
        "aircraft": 100, "clients": 5, "generations": 10,
        "old_per_client_builds": old_builds, "shared_builds": builds,
        "old_per_client_serializations": old_builds, "shared_legacy_plus_v1_serializations": serializations,
        "old_full_payload_bytes_5_clients": old_full_bytes,
        "shared_v1_full_payload_bytes_5_clients": modern_full_bytes,
        "shared_v1_delivered_bytes_4_fast_1_coalesced": delivered_bytes,
        "source_age_ms_min": min(source_ages), "source_age_ms_max": max(source_ages),
        "old_source_age_ms_min": min(old_source_ages), "old_source_age_ms_max": max(old_source_ages),
        "max_pending_per_client": max_queue_depth,
        "scope": "synthetic JSON payloads; excludes framing, networking, FC acquisition and runtime latency",
    }, sort_keys=True))
