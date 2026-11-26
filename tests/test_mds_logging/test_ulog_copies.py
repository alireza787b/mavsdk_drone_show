"""Exercise managed ULogs through the GCS router and real HTTP responses."""

import asyncio
import hashlib
import time

import httpx
import pytest
from fastapi import FastAPI

import log_proxy
import log_routes
import ulog_copies
from mds_logging import ulog_analysis
from src.ulog_request_receipts import native_download_job_id
from ulog_download_requests import UlogDownloadRequests


class AircraftBody(httpx.AsyncByteStream):
    def __init__(self, data, link_loss=False):
        self.data = data
        self.link_loss = link_loss

    async def __aiter__(self):
        yield self.data[:23]
        await asyncio.sleep(0)
        if self.link_loss:
            raise httpx.ReadError("radio disconnected")
        yield self.data[23:]


@pytest.fixture
def gcs(tmp_path, monkeypatch):
    monkeypatch.setenv("MDS_AUTH_SESSION_SECRET_FILE", str(tmp_path / "session-secret"))
    requests = UlogDownloadRequests(str(tmp_path), "test")
    monkeypatch.setattr(log_routes, "get_ulog_download_requests", lambda: requests)
    monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda _: "192.0.2.5")
    copies = ulog_copies.GcsUlogCopies(tmp_path / "cache")
    monkeypatch.setattr(ulog_copies, "get_ulog_copies", lambda: copies)
    app = FastAPI()

    @app.middleware("http")
    async def actor(request, call_next):
        request.state.mds_auth_context = {
            "kind": "session", "role": request.headers.get("test-role", "operator"),
            "username": request.headers.get("test-actor", "alice"),
            "sid": "fixture-session",
        }
        return await call_next(request)

    app.include_router(log_routes.create_log_router(log_dir=str(tmp_path / "logs")))
    return app, copies


def install_node(monkeypatch, data, *, staged_size=None, lose_first_copy=False):
    now = int(time.time() * 1000)
    job = {
        "hw_id": "5", "log_id": 9, "size_bytes": staged_size or len(data),
        "status": "ready", "progress": 1, "download_filename": "H5.ulg",
        "created_at": now, "updated_at": now, "expires_at": now + 60000,
    }
    calls = []

    async def create(ip, log_id, *, access_token, request_id, pos_id):
        calls.append("create")
        job["job_id"] = native_download_job_id("5", request_id, access_token)
        return {"job": job, "timestamp": now}

    async def content(ip, job_id, *, access_token):
        assert job_id == job["job_id"]
        calls.append("content")
        response = httpx.Response(200, headers={"content-length": str(job["size_bytes"])},
                                  stream=AircraftBody(data, lose_first_copy and calls.count("content") == 1))
        return httpx.AsyncClient(), response

    monkeypatch.setattr(log_proxy, "create_drone_ulog_download_job", create)
    monkeypatch.setattr(log_proxy, "open_drone_ulog_download_stream", content)
    return calls


BASE = "/api/logs/drone/5/ulog"
RECEIPT = BASE + "/download-requests/test-copy"
VALID = b"ULog\x01\x12\x35\x01" + b"\0" * 8 + bytes(range(64))


async def prepare(client, copies, expected_size):
    accepted = await client.post(BASE + "/files/9/download",
                                 params={"gcs_copy": "true", "expected_size": expected_size},
                                 json={"request_id": "test-copy"})
    assert accepted.status_code == 200
    await asyncio.wait_for(asyncio.gather(*copies.tasks.values()), 5)
    status = (await client.get(RECEIPT)).json()["job"]
    return status, BASE + "/downloads/" + status["job_id"]


@pytest.mark.asyncio
async def test_copy_resumes_browser_at_exact_offset_after_aircraft_and_gcs_restart(gcs, monkeypatch):
    app, copies = gcs
    calls = install_node(monkeypatch, VALID, lose_first_copy=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        job, path = await prepare(client, copies, len(VALID))
        assert job["phase"] == "verified"
        assert calls == ["create", "content", "content"]
        monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda _: None)
        reopened = ulog_copies.GcsUlogCopies(copies.root)
        monkeypatch.setattr(ulog_copies, "get_ulog_copies", lambda: reopened)
        assert (await client.get(RECEIPT)).json()["job"]["status"] == "ready"
        content = path + "/content?gcs_copy=true"
        first = await client.get(content, headers={"Range": "bytes=0-19"})
        assert first.status_code == 206
        etag = first.headers["etag"]
        last = await client.get(content, headers={"Range": "bytes=20-", "If-Range": etag})
        assert last.status_code == 206
        assert hashlib.sha256(first.content + last.content).hexdigest() == etag.strip('"')
        assert first.content + last.content == VALID
        assert (await client.get(content, headers={"Range": "bytes=800-"})).status_code == 416
        assert (await client.get(content, headers={"Range": "bytes=20-", "If-Range": '"old"'})).content == VALID
        assert (await client.head(content)).headers["content-length"] == str(len(VALID))
        assert (await client.get(content, headers={"test-role": "viewer"})).status_code == 403
        assert (await client.get(content, headers={"test-actor": "bob"})).status_code == 404

        async def summarize(path, **kwargs):
            assert path.read_bytes() == VALID
            return {"parsed": True, "parser": {"status": "ok"}, "duration_sec": 42}

        monkeypatch.setattr(ulog_analysis, "summarize_ulog_file_async", summarize)
        result = await client.get(path + "/summary")
        assert result.status_code == 200 and result.json()["duration_sec"] == 42
        assert (await client.get(path + "/summary", headers={"test-role": "viewer"})).status_code == 403
        assert (await client.delete(path + "?gcs_copy=true")).status_code == 200
        assert (await client.get(RECEIPT)).json()["job"]["status"] == "expired"
        assert (await client.get(content)).status_code == 409
        assert calls == ["create", "content", "content"]


@pytest.mark.parametrize(("data", "advertised", "staged_size", "error"), [
    (b"finished-ulog", 512, 13, "size"),
    (VALID[:20], len(VALID), len(VALID), "incomplete"),
    (b"bad" + VALID, len(VALID) + 3, None, "invalid PX4 ULog header"),
])
@pytest.mark.asyncio
async def test_invalid_logs_are_never_served(gcs, monkeypatch, data, advertised, staged_size, error):
    app, copies = gcs
    install_node(monkeypatch, data, staged_size=staged_size)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        job, path = await prepare(client, copies, advertised)
        assert job["status"] == "failed"
        assert error in job["error"]
        assert (await client.get(path + "/content?gcs_copy=true")).status_code == 409
        assert not list(copies.root.glob("*.ulg"))
        assert not list(copies.root.glob("*.part"))


@pytest.mark.asyncio
async def test_low_disk_space_refuses_copy_before_opening_aircraft_stream(gcs, monkeypatch):
    app, copies = gcs
    calls = install_node(monkeypatch, VALID)
    monkeypatch.setattr(ulog_copies, "ulog_download_min_free_bytes", lambda: 1 << 60)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        job, _ = await prepare(client, copies, len(VALID))
        assert job["status"] == "failed"
        assert "insufficient free space" in job["error"]
        assert calls == ["create"]
