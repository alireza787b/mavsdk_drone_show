"""Real registered DroneAPIServer routes and service hooks; no hardware access."""

import asyncio
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


async def _samples(value):
    yield value
    await asyncio.Event().wait()


@pytest.fixture
def native_ulog(api_server, monkeypatch, tmp_path):
    monkeypatch.delenv("MDS_GCS_API_TOKEN_FILE", raising=False)
    monkeypatch.setattr(api_server.params, "ULOG_DOWNLOAD_REQUIRE_DISARMED", True)
    monkeypatch.setattr(api_server.params, "ULOG_ERASE_REQUIRE_DISARMED", True)
    monkeypatch.setattr(api_server.params, "ULOG_DOWNLOAD_STAGE_DIR", str(tmp_path / "stage"))
    monkeypatch.setattr(api_server.params, "ULOG_FILESYSTEM_FALLBACK_DIRS", [])
    drone = SimpleNamespace(
        armed_value=False,
        core=SimpleNamespace(connection_state=lambda: _samples(SimpleNamespace(is_connected=True))),
        log_files=SimpleNamespace(
            get_entries=AsyncMock(return_value=[SimpleNamespace(id=9, date="2026-11-12T00:00:00Z", size_bytes=23)]),
            erase_all_log_files=AsyncMock(),
        ),
    )
    drone.telemetry = SimpleNamespace(armed=lambda: _samples(drone.armed_value))
    drone.downloads = []

    async def download(entry, path):
        drone.downloads.append(entry.id)
        Path(path).write_bytes(b"ULog\x01\x12\x35\x01" + (123).to_bytes(8, "little") + b"payload")
        yield SimpleNamespace(progress=1.0)

    drone.log_files.download_log_file = download

    async def with_local(operation):
        return await operation(drone)

    scheduled = []
    monkeypatch.setattr(api_server, "_with_local_ulog_system", with_local)
    monkeypatch.setattr(api_server, "_start_ulog_download_task", scheduled.append)
    return SimpleNamespace(server=api_server, drone=drone, scheduled=scheduled, tmp_path=tmp_path)


def _create(client, request_id=None):
    return client.post("/api/v1/ulog/files/9/download", json={"request_id": request_id} if request_id else {},
                       headers={"X-MDS-ULog-Job-Token": "native-test-capability"})


@pytest.mark.parametrize("armed", [True, None])
@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/ulog/files/9/download"),
    ("GET", "/api/v1/ulog/files/9/summary"),
    ("POST", "/api/v1/ulog/erase-all"),
])
def test_native_routes_do_not_treat_cached_false_as_live_disarm(test_client, native_ulog, method, path, armed):
    native_ulog.drone.armed_value = armed
    native_ulog.server.drone_config.is_armed = False
    response = test_client.request(method, path, json={}, headers={"X-MDS-ULog-Job-Token": "native-test-capability"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] in {"ulog_vehicle_armed", "ulog_disarm_unconfirmed"}
    assert not native_ulog.scheduled
    assert not native_ulog.drone.downloads
    native_ulog.drone.log_files.erase_all_log_files.assert_not_awaited()


def test_live_disarm_allows_native_job_without_flight_health_or_gps(test_client, native_ulog):
    response = _create(test_client)
    assert response.status_code == 200
    assert response.json()["job"]["status"] == "queued"
    assert native_ulog.scheduled == [response.json()["job"]["job_id"]]


async def test_background_staging_rechecks_arm_state_after_accepted_creation(test_client, native_ulog):
    response = await test_client._request("POST", "/api/v1/ulog/files/9/download", json={},
                                          headers={"X-MDS-ULog-Job-Token": "native-test-capability"})
    assert response.status_code == 200
    job_id = response.json()["job"]["job_id"]
    native_ulog.drone.armed_value = True
    await native_ulog.server._run_ulog_download_job(job_id)
    job = await native_ulog.server._ulog_service.get_job(job_id)
    assert job.job.status == "failed"
    assert "armed" in job.job.error
    assert not native_ulog.drone.downloads


async def test_native_download_rechecks_after_entry_refetch_before_starting_bytes(test_client, native_ulog):
    calls = 0

    async def entries():
        nonlocal calls
        calls += 1
        if calls == 2:
            native_ulog.drone.armed_value = True
        return [SimpleNamespace(id=9, date="2026-11-12T00:00:00Z", size_bytes=23)]

    native_ulog.drone.log_files.get_entries.side_effect = entries
    response = await test_client._request("POST", "/api/v1/ulog/files/9/download", json={},
                                          headers={"X-MDS-ULog-Job-Token": "native-test-capability"})
    assert response.status_code == 200
    job_id = response.json()["job"]["job_id"]
    await native_ulog.server._run_ulog_download_job(job_id)
    job = await native_ulog.server._ulog_service.get_job(job_id)
    assert job.job.status == "failed"
    assert "armed" in job.job.error
    assert calls == 2
    assert not native_ulog.drone.downloads


def test_summary_staging_rechecks_after_inventory_before_fetching_bytes(test_client, native_ulog):
    calls = 0

    async def entries():
        nonlocal calls
        calls += 1
        if calls == 2:
            native_ulog.drone.armed_value = True
        return [SimpleNamespace(id=9, date="2026-11-12T00:00:00Z", size_bytes=23)]

    native_ulog.drone.log_files.get_entries.side_effect = entries
    response = test_client.get("/api/v1/ulog/files/9/summary")
    assert response.status_code == 409
    assert not native_ulog.drone.downloads
    assert not list((native_ulog.tmp_path / "stage").glob("*.ulg"))


def test_same_creation_identity_is_lookup_only_even_if_aircraft_later_arms(test_client, native_ulog, monkeypatch):
    first = _create(test_client, "request-1")
    assert first.status_code == 200
    native_ulog.drone.armed_value = True
    native_ulog.server.drone_config.is_armed = True
    transport = AsyncMock(side_effect=AssertionError("recovery must not reconnect or restage"))
    monkeypatch.setattr(native_ulog.server, "_with_local_ulog_system", transport)
    replay = _create(test_client, "request-1")
    assert replay.status_code == 200
    assert replay.json()["job"]["job_id"] == first.json()["job"]["job_id"]
    assert len(native_ulog.scheduled) == 1
    transport.assert_not_awaited()


def _filesystem_fallback(native_ulog, monkeypatch):
    root = native_ulog.tmp_path / "px4-logs"
    root.mkdir()
    path = root / "test.ulg"
    path.write_bytes(b"ULog\x01\x12\x35\x01" + (123).to_bytes(8, "little") + b"payload")
    monkeypatch.setattr(native_ulog.server.params, "ULOG_FILESYSTEM_FALLBACK_DIRS", [str(root)])
    native_ulog.drone.telemetry = SimpleNamespace()  # No MAVSDK telemetry plugin.
    native_ulog.drone.log_files.get_entries.side_effect = RuntimeError("log-files plugin unavailable")
    return path


@pytest.mark.parametrize("heartbeat,base_mode", [(0, 0), (-10_000, 0), (0, 128)])
def test_filesystem_erase_never_uses_initial_or_derived_disarm(test_client, native_ulog, monkeypatch, heartbeat, base_mode):
    path = _filesystem_fallback(native_ulog, monkeypatch)
    assert test_client.get("/api/v1/ulog/files").status_code == 200
    native_ulog.server.drone_config.is_armed = False
    native_ulog.server.drone_config.base_mode = base_mode
    native_ulog.server.drone_config.heartbeat_timestamp_ms = int(time.time()*1000) + heartbeat if heartbeat or base_mode else 0
    response = test_client.post("/api/v1/ulog/erase-all")
    assert response.status_code == 409
    assert path.exists()
    native_ulog.drone.log_files.erase_all_log_files.assert_not_awaited()


async def test_filesystem_download_keeps_demo_fallback_with_fresh_raw_disarmed_heartbeat(test_client, native_ulog, monkeypatch):
    path = _filesystem_fallback(native_ulog, monkeypatch)
    native_ulog.server.drone_config.base_mode = 0
    native_ulog.server.drone_config.heartbeat_timestamp_ms = int(time.time()*1000)
    inventory = (await test_client._request("GET", "/api/v1/ulog/files")).json()
    log_id = inventory["files"][0]["id"]
    response = await test_client._request("POST", f"/api/v1/ulog/files/{log_id}/download", json={},
                                          headers={"X-MDS-ULog-Job-Token": "native-test-capability"})
    assert response.status_code == 200
    job_id = response.json()["job"]["job_id"]
    await native_ulog.server._run_ulog_download_job(job_id)
    job = await native_ulog.server._ulog_service.get_job(job_id)
    assert job.job.status == "ready"
    assert path.exists()  # Download is not erase.


def test_existing_disarm_policy_opt_out_does_not_create_a_new_flight_gate(test_client, native_ulog, monkeypatch):
    native_ulog.drone.armed_value = None
    monkeypatch.setattr(native_ulog.server.params, "ULOG_ERASE_REQUIRE_DISARMED", False)
    response = test_client.post("/api/v1/ulog/erase-all")
    assert response.status_code == 200
    native_ulog.drone.log_files.erase_all_log_files.assert_awaited_once()


def test_erase_rechecks_after_filesystem_step_before_native_erase(test_client, native_ulog, monkeypatch):
    def filesystem_step():
        native_ulog.drone.armed_value = True
        return False

    monkeypatch.setattr(native_ulog.server._ulog_service, "_erase_filesystem_logs", filesystem_step)
    response = test_client.post("/api/v1/ulog/erase-all")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ulog_vehicle_armed"
    native_ulog.drone.log_files.erase_all_log_files.assert_not_awaited()
