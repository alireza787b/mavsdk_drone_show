"""Actual GCS router recovery contract, using isolated actors and native fakes."""

import time

import pytest
from fastapi import FastAPI

import log_proxy
import log_routes
from src.ulog_request_receipts import native_download_job_id
from tests.conftest import SyncASGITestClient as TestClient
from ulog_download_requests import UlogDownloadRequests


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("MDS_AUTH_SESSION_SECRET_FILE", str(tmp_path / "session-secret"))
    requests = UlogDownloadRequests(str(tmp_path / "requests"), "sitl-runtime")
    monkeypatch.setattr(log_routes, "get_ulog_download_requests", lambda: requests)
    monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda drone_id: f"192.0.2.{drone_id}")
    app = FastAPI()
    @app.middleware("http")
    async def actor(request, call_next):
        request.state.mds_auth_context = {
            "kind": "session", "role": request.headers.get("test-role", "operator"),
            "username": request.headers.get("test-actor", "alice"),
            "sid": request.headers.get("test-actor", "alice") + "-session",
        }
        return await call_next(request)
    app.include_router(log_routes.create_log_router(log_dir=str(tmp_path / "logs")))
    return TestClient(app), requests, tmp_path


def native_job(log_id, job_id, status="queued"):
    now = int(time.time() * 1000)
    return {"job": {
        "job_id": job_id, "hw_id": "5", "pos_id": 2, "log_id": log_id,
        "date_utc": "2026-11-12T12:00:00Z", "size_bytes": 64,
        "status": status, "progress": 1 if status == "ready" else 0,
        "staged_filename": "native-stage.ulg", "download_filename": "H5.ulg",
        "created_at": now, "updated_at": now, "expires_at": now + 60_000,
    }, "timestamp": now}


BASE = "/api/logs/drone/5/ulog"


def test_create_receipt_precedes_native_and_same_request_does_not_create_twice(setup, monkeypatch):
    client, receipts, _ = setup
    calls = []
    async def create(ip, log_id, *, access_token, request_id, pos_id=None):
        calls.append(request_id)
        # The durable row exists before the only native create is attempted.
        with receipts.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM ulog_requests").fetchone()[0] == 1
        return native_job(log_id, native_download_job_id("5", request_id, access_token))
    monkeypatch.setattr(log_proxy, "create_drone_ulog_download_job", create)
    first = client.post(BASE + "/files/9/download", json={"request_id": "request-one"})
    assert first.status_code == 200
    assert first.json()["request_id"] == "request-one"
    second = client.post(BASE + "/files/9/download", json={"request_id": "request-one"})
    assert second.status_code == 200 and second.json()["job"]["job_id"] == first.json()["job"]["job_id"]
    recovery = client.get(BASE + "/download-requests/request-one")
    assert recovery.status_code == 200 and recovery.json()["status"] == "accepted"
    assert recovery.json()["job"]["job_id"] == first.json()["job"]["job_id"]
    assert calls == ["request-one"]


def test_lost_response_recovers_by_native_get_only(setup, monkeypatch):
    client, _, _ = setup
    calls, jobs = [], {}
    async def create(ip, log_id, *, access_token, request_id, pos_id=None):
        calls.append("POST")
        job_id = native_download_job_id("5", request_id, access_token)
        jobs[job_id] = (access_token, native_job(log_id, job_id, status="ready"))
        raise log_proxy.DroneProxyUnavailableError("create response lost")
    async def get(ip, job_id, *, access_token):
        calls.append("GET")
        assert jobs[job_id][0] == access_token
        return jobs[job_id][1]
    monkeypatch.setattr(log_proxy, "create_drone_ulog_download_job", create)
    monkeypatch.setattr(log_proxy, "fetch_drone_ulog_download_job", get)
    response = client.post(BASE + "/files/9/download", json={"request_id": "request-lost"})
    assert response.status_code == 502
    assert response.json()["detail"]["creation_status"] == "unknown"
    assert client.post(BASE + "/files/9/download", json={"request_id": "request-lost"}).status_code == 409
    recovery = client.get(BASE + "/download-requests/request-lost")
    assert recovery.json()["status"] == "accepted" and recovery.json()["job"]["status"] == "ready"
    assert calls == ["POST", "GET"]
    assert "access_token" not in str(recovery.json())


def test_restart_with_unknown_native_state_never_recreates(setup, monkeypatch):
    client, receipts, tmp_path = setup
    calls = []
    async def create(*args, **kwargs):
        calls.append("POST")
        raise log_proxy.DroneProxyUnavailableError("create response lost")
    async def get(*args, **kwargs):
        calls.append("GET")
        raise log_proxy.DroneProxyResponseError(404, "node restarted")
    monkeypatch.setattr(log_proxy, "create_drone_ulog_download_job", create)
    monkeypatch.setattr(log_proxy, "fetch_drone_ulog_download_job", get)
    assert client.post(BASE + "/files/9/download", json={"request_id": "request-restart"}).status_code == 502
    reopened = UlogDownloadRequests(str(tmp_path / "requests"), "sitl-runtime")
    monkeypatch.setattr(log_routes, "get_ulog_download_requests", lambda: reopened)
    response = client.get(BASE + "/download-requests/request-restart")
    assert response.status_code == 200 and response.json()["status"] == "unknown"
    assert response.json()["job"] is None
    assert client.post(BASE + "/files/9/download", json={"request_id": "request-restart"}).status_code == 409
    assert calls == ["POST", "GET"]


def test_actor_aircraft_log_and_runtime_are_bound(setup, monkeypatch):
    client, _, tmp_path = setup
    calls = []
    async def create(ip, log_id, *, access_token, request_id, pos_id=None):
        calls.append(request_id)
        return native_job(log_id, native_download_job_id("5", request_id, access_token))
    monkeypatch.setattr(log_proxy, "create_drone_ulog_download_job", create)
    assert client.post(BASE + "/files/9/download", json={"request_id": "request-bound"}).status_code == 200
    assert client.get(BASE + "/download-requests/request-bound", headers={"test-actor": "bob"}).status_code == 404
    assert client.get("/api/logs/drone/6/ulog/download-requests/request-bound").status_code == 404
    assert client.post(BASE + "/files/10/download", json={"request_id": "request-bound"}).status_code == 409
    assert client.post("/api/logs/drone/6/ulog/files/9/download", json={"request_id": "request-bound"}).status_code == 409
    monkeypatch.setattr(log_routes, "get_ulog_download_requests", lambda: UlogDownloadRequests(str(tmp_path / "requests"), "real-runtime"))
    assert client.get(BASE + "/download-requests/request-bound").status_code == 404
    assert calls == ["request-bound"]


def test_viewer_and_malformed_ids_reject_without_native_create(setup, monkeypatch):
    client, _, _ = setup
    async def unexpected(*args, **kwargs):
        pytest.fail("Invalid/viewer requests must not reach native staging")
    monkeypatch.setattr(log_proxy, "create_drone_ulog_download_job", unexpected)
    assert client.post(BASE + "/files/9/download", json={"request_id": "viewer-id"}, headers={"test-role": "viewer"}).status_code == 403
    assert client.get(BASE + "/download-requests/viewer-id", headers={"test-role": "viewer"}).status_code == 403
    assert client.post(BASE + "/files/9/download", json={"request_id": "bad/path"}).status_code == 422
    assert client.post(BASE + "/files/-1/download", json={"request_id": "valid-id"}).status_code == 422
