"""Tests for GCS-side log API endpoints (local — no drone proxy)."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
import pytest

# Add gcs-server to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'gcs-server'))

from fastapi import FastAPI
from auth_runtime import MDSAuthMiddleware

from mds_logging.watcher import LogWatcher
from mds_logging.registry import register_component, clear_registry
from tests.conftest import SyncASGITestClient as TestClient
from src.security.auth import (
    AuthService,
    AuthSettings,
    MACHINE_CREDENTIAL_HEADER,
    ULOG_OP_DOWNLOAD_CREATE,
    ULOG_OP_FILES_READ,
    verify_machine_credential,
)


@pytest.fixture(autouse=True)
def clean_registry(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MDS_AUTH_SESSION_SECRET_FILE",
        str(tmp_path / "session-secret"),
    )
    clear_registry()
    yield
    clear_registry()


def _make_gcs_app(log_dir, watcher=None):
    """Build a minimal FastAPI app with the GCS log router."""
    from log_routes import create_log_router
    app = FastAPI()
    app.add_middleware(MDSAuthMiddleware)
    router = create_log_router(log_dir=log_dir, watcher=watcher)
    app.include_router(router)
    return app


def _create_drone_machine_token(monkeypatch, tmp_path):
    auth_dir = tmp_path / "machine-auth"
    monkeypatch.setenv("MDS_API_TOKENS_FILE", str(auth_dir / "api_tokens.json"))
    monkeypatch.setenv("MDS_AUTH_USERS_FILE", str(auth_dir / "users.json"))
    monkeypatch.setenv("MDS_AUTH_SESSION_SECRET_FILE", str(auth_dir / "session_secret"))
    monkeypatch.setenv("MDS_AUTH_CSRF_SECRET_FILE", str(auth_dir / "csrf_secret"))
    service = AuthService(AuthSettings.from_env())
    created = service.store.create_token(
        "drone-5",
        scopes=["drone"],
        ttl_seconds=3600,
    )
    return created["token"]


class TestGetSources:
    def test_returns_empty_registry(self, tmp_path):
        app = _make_gcs_app(str(tmp_path))
        client = TestClient(app)
        resp = client.get("/api/logs/sources")
        assert resp.status_code == 200
        assert resp.json()["components"] == {}

    def test_returns_registered_components(self, tmp_path):
        register_component("coordinator", "drone", "System init")
        register_component("gcs", "gcs", "GCS server")
        app = _make_gcs_app(str(tmp_path))
        client = TestClient(app)
        resp = client.get("/api/logs/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert "coordinator" in data["components"]
        assert "gcs" in data["components"]


class TestGCSSessions:
    def test_list_sessions_empty(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.get("/api/logs/sessions")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_list_sessions(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        with open(os.path.join(log_dir, "s_20260319_100000.jsonl"), "w") as f:
            f.write(json.dumps({"level": "INFO", "msg": "test"}) + "\n")
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.get("/api/logs/sessions")
        data = resp.json()
        assert len(data["sessions"]) == 1

    def test_get_session_content(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        with open(os.path.join(log_dir, "s_20260319_100000.jsonl"), "w") as f:
            f.write(json.dumps({"level": "INFO", "msg": "hello"}) + "\n")
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.get("/api/logs/sessions/s_20260319_100000")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_get_session_not_found(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.get("/api/logs/sessions/s_nonexistent")
        assert resp.status_code == 404


class TestGCSStream:
    def test_stream_endpoint_registered(self, tmp_path):
        """Verify SSE stream endpoint is registered."""
        app = _make_gcs_app(str(tmp_path))
        routes = [r.path for r in app.routes]
        assert "/api/logs/stream" in routes


class TestFrontendReport:
    def test_post_frontend_error(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.post("/api/logs/frontend", json={
            "level": "ERROR",
            "component": "LogViewer",
            "msg": "React render error",
            "extra": {"stack": "Error at ..."},
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"


    def test_rejects_invalid_level(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.post("/api/logs/frontend", json={
            "level": "BOGUS",
            "msg": "test",
        })
        assert resp.status_code == 400
        assert "Invalid log level" in resp.json()["detail"]


class TestUlogSummaryUpload:
    def test_upload_ulog_summary_returns_derived_metrics_and_deletes_temp(self, tmp_path, monkeypatch):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        captured = {}

        async def fake_summary(path, *, source_metadata=None, max_bytes=None, timeout_seconds=None):  # noqa: ANN001
            captured["path"] = str(path)
            captured["exists_during_parse"] = Path(path).exists()
            captured["source_metadata"] = dict(source_metadata or {})
            captured["max_bytes"] = max_bytes
            captured["timeout_seconds"] = timeout_seconds
            return {
                "source": {
                    "source_kind": "uploaded_file",
                    "log_id": 0,
                    "size_bytes": captured["source_metadata"]["size_bytes"],
                },
                "parser": {"name": "pyulog", "available": True, "status": "ok"},
                "parsed": True,
                "duration_sec": 12.5,
                "dropouts": {"count": 0},
                "logged_messages": {"count": 0, "raw_text_included": False},
                "system": {},
                "local_position": {"max_horizontal_distance_from_start_m": 3.0},
                "raw_content_included": False,
            }

        monkeypatch.setattr("mds_logging.ulog_analysis.summarize_ulog_file_async", fake_summary)
        client = TestClient(_make_gcs_app(log_dir))

        resp = client.post(
            "/api/logs/ulog/summary",
            files={"file": ("flight.ulg", b"fake-ulog-bytes", "application/octet-stream")},
        )

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["hw_id"] == "uploaded"
        assert payload["log_id"] == 0
        assert payload["parsed"] is True
        assert payload["duration_sec"] == 12.5
        assert payload["raw_content_included"] is False
        assert captured["exists_during_parse"] is True
        assert captured["source_metadata"]["source_kind"] == "uploaded_file"
        assert captured["source_metadata"]["size_bytes"] == len(b"fake-ulog-bytes")
        assert not Path(captured["path"]).exists()

    def test_upload_ulog_summary_rejects_oversize_upload(self, tmp_path, monkeypatch):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        monkeypatch.setenv("MDS_ULOG_UPLOAD_SUMMARY_MAX_BYTES", "4")
        client = TestClient(_make_gcs_app(log_dir))

        resp = client.post(
            "/api/logs/ulog/summary",
            files={"file": ("flight.ulg", b"too-large", "application/octet-stream")},
        )

        assert resp.status_code == 413


class TestExport:
    def test_export_single_session_jsonl(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        with open(os.path.join(log_dir, "s_20260319_100000.jsonl"), "w") as f:
            f.write(json.dumps({"level": "INFO", "msg": "test"}) + "\n")
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.post("/api/logs/export", json={
            "session_ids": ["s_20260319_100000"],
            "format": "jsonl",
        })
        assert resp.status_code == 200
        assert "application/x-ndjson" in resp.headers["content-type"]
        assert "test" in resp.text

    def test_export_multiple_sessions_zip(self, tmp_path):
        import zipfile
        import io
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        for sid in ["s_20260319_100000", "s_20260319_110000"]:
            with open(os.path.join(log_dir, f"{sid}.jsonl"), "w") as f:
                f.write(json.dumps({"level": "INFO", "msg": sid}) + "\n")
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.post("/api/logs/export", json={
            "session_ids": ["s_20260319_100000", "s_20260319_110000"],
            "format": "zip",
        })
        assert resp.status_code == 200
        assert "application/zip" in resp.headers["content-type"]
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert len(zf.namelist()) == 2

    def test_export_session_not_found(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.post("/api/logs/export", json={
            "session_ids": ["s_nonexistent"],
            "format": "jsonl",
        })
        assert resp.status_code == 404

    def test_export_rejects_path_traversal_session_id(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.post("/api/logs/export", json={
            "session_ids": ["../escape"],
            "format": "jsonl",
        })
        assert resp.status_code == 404

    def test_export_empty_session_ids(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.post("/api/logs/export", json={
            "session_ids": [],
            "format": "jsonl",
        })
        assert resp.status_code == 400

    def test_export_rejects_invalid_format(self, tmp_path):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)
        client = TestClient(_make_gcs_app(log_dir))
        resp = client.post("/api/logs/export", json={
            "session_ids": ["s_20260319_100000"],
            "format": "csv",
        })
        assert resp.status_code == 422

    def test_export_drone_session_jsonl(self, tmp_path, monkeypatch):
        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)

        import log_proxy

        monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda drone_id: "10.0.0.5")

        async def fake_fetch(drone_ip, session_id, **_kwargs):
            assert drone_ip == "10.0.0.5"
            return {
                "session_id": session_id,
                "lines": [{"level": "INFO", "msg": "hello from drone"}],
            }

        monkeypatch.setattr(log_proxy, "fetch_drone_session_content", fake_fetch)

        client = TestClient(_make_gcs_app(log_dir))
        resp = client.post("/api/logs/drone/5/export", json={
            "session_ids": ["s_20260319_100000"],
            "format": "jsonl",
        })

        assert resp.status_code == 200
        assert "application/x-ndjson" in resp.headers["content-type"]
        assert "hello from drone" in resp.text

    def test_export_drone_sessions_zip(self, tmp_path, monkeypatch):
        import io
        import zipfile
        import log_proxy

        log_dir = str(tmp_path / "sessions")
        os.makedirs(log_dir)

        monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda drone_id: "10.0.0.5")

        async def fake_fetch(_drone_ip, session_id, **_kwargs):
            return {
                "session_id": session_id,
                "lines": [{"level": "INFO", "msg": session_id}],
            }

        monkeypatch.setattr(log_proxy, "fetch_drone_session_content", fake_fetch)

        client = TestClient(_make_gcs_app(log_dir))
        resp = client.post("/api/logs/drone/5/export", json={
            "session_ids": ["s_20260319_100000", "s_20260319_110000"],
            "format": "zip",
        })

        assert resp.status_code == 200
        assert "application/zip" in resp.headers["content-type"]
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert sorted(zf.namelist()) == ["s_20260319_100000.jsonl", "s_20260319_110000.jsonl"]


class TestDroneOnboardUlogProxy:
    def test_proxy_attaches_scoped_node_credential_server_side(
        self,
        tmp_path,
        monkeypatch,
    ):
        import log_proxy

        node_token = _create_drone_machine_token(monkeypatch, tmp_path)
        monkeypatch.setattr(
            log_proxy,
            "load_config",
            lambda: [{"hw_id": "5", "ip": "10.0.0.5"}],
        )
        captured = []

        class FakeResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"ok": True}

        class FakeAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def request(self, method, url, **kwargs):
                captured.append((method, url, kwargs))
                return FakeResponse()

        monkeypatch.setattr(log_proxy.httpx, "AsyncClient", FakeAsyncClient)

        asyncio.run(log_proxy.fetch_drone_ulog_files("10.0.0.5"))
        asyncio.run(
            log_proxy.create_drone_ulog_download_job(
                "10.0.0.5",
                12,
                access_token="raw-job-capability",
            )
        )

        files_headers = captured[0][2]["headers"]
        create_headers = captured[1][2]["headers"]
        assert MACHINE_CREDENTIAL_HEADER in files_headers
        assert verify_machine_credential(
            files_headers[MACHINE_CREDENTIAL_HEADER],
            bearer_token=node_token,
            audience="mds-drone:5",
            operation=ULOG_OP_FILES_READ,
            consume_nonce=False,
        )
        assert create_headers["X-MDS-ULog-Job-Token"] == "raw-job-capability"
        assert verify_machine_credential(
            create_headers[MACHINE_CREDENTIAL_HEADER],
            bearer_token=node_token,
            audience="mds-drone:5",
            operation=ULOG_OP_DOWNLOAD_CREATE,
            consume_nonce=False,
        )

    def test_proxy_fails_closed_without_drone_machine_token(
        self,
        tmp_path,
        monkeypatch,
    ):
        import log_proxy

        auth_dir = tmp_path / "empty-auth"
        monkeypatch.setenv("MDS_API_TOKENS_FILE", str(auth_dir / "api_tokens.json"))
        monkeypatch.setenv("MDS_API_AUTH_ENABLED", "true")
        monkeypatch.setattr(
            log_proxy,
            "load_config",
            lambda: [{"hw_id": "5", "ip": "10.0.0.5"}],
        )

        with pytest.raises(log_proxy.DroneProxyResponseError) as error:
            asyncio.run(log_proxy.fetch_drone_ulog_files("10.0.0.5"))

        assert error.value.status_code == 503

    def test_proxy_allows_zero_config_trusted_network_demo(
        self,
        tmp_path,
        monkeypatch,
    ):
        import log_proxy

        auth_dir = tmp_path / "empty-auth"
        monkeypatch.setenv("MDS_API_TOKENS_FILE", str(auth_dir / "api_tokens.json"))
        monkeypatch.setenv("MDS_API_AUTH_ENABLED", "false")
        monkeypatch.delenv("MDS_SITL_GCS_API_TOKEN_FILE", raising=False)
        monkeypatch.setattr(
            log_proxy,
            "load_config",
            lambda: [{"hw_id": "5", "ip": "10.0.0.5"}],
        )

        assert (
            log_proxy._authenticated_ulog_headers(
                "GET",
                "10.0.0.5",
                "/api/v1/ulog/files",
            )
            is None
        )

    def test_proxy_fails_closed_for_incomplete_hardened_sitl_config(
        self,
        tmp_path,
        monkeypatch,
    ):
        import log_proxy

        auth_dir = tmp_path / "empty-auth"
        monkeypatch.setenv("MDS_API_TOKENS_FILE", str(auth_dir / "api_tokens.json"))
        monkeypatch.setenv("MDS_API_AUTH_ENABLED", "false")
        monkeypatch.setenv(
            "MDS_SITL_GCS_API_TOKEN_FILE",
            str(tmp_path / "missing-sitl-token"),
        )
        monkeypatch.setattr(
            log_proxy,
            "load_config",
            lambda: [{"hw_id": "5", "ip": "10.0.0.5"}],
        )

        with pytest.raises(log_proxy.DroneProxyResponseError) as error:
            log_proxy._authenticated_ulog_headers(
                "GET",
                "10.0.0.5",
                "/api/v1/ulog/files",
            )

        assert error.value.status_code == 503

    def test_get_drone_ulog_policy(self, tmp_path, monkeypatch):
        import log_proxy

        app = _make_gcs_app(str(tmp_path))
        client = TestClient(app)

        monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda drone_id: "10.0.0.5")

        async def fake_fetch(_drone_ip):
            return {
                "hw_id": "5",
                "pos_id": 2,
                "policy": {
                    "supported": True,
                    "transport": "mavsdk_log_files",
                    "storage_mode": "file_backed",
                    "list_supported": True,
                    "download_supported": True,
                    "erase_all_supported": True,
                    "single_delete_supported": False,
                    "download_requires_disarmed": True,
                    "erase_requires_disarmed": True,
                    "staged_download_ttl_sec": 900,
                    "notes": [],
                },
                "timestamp": 123,
            }

        monkeypatch.setattr(log_proxy, "fetch_drone_ulog_policy", fake_fetch)

        resp = client.get("/api/logs/drone/5/ulog/policy")

        assert resp.status_code == 200
        assert resp.json()["policy"]["storage_mode"] == "file_backed"

    def test_create_drone_ulog_download_job(self, tmp_path, monkeypatch):
        import log_proxy

        app = _make_gcs_app(str(tmp_path))
        client = TestClient(app)

        monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda drone_id: "10.0.0.5")

        async def fake_create(_drone_ip, log_id, *, access_token):
            assert log_id == 12
            assert access_token
            return {
                "job": {
                    "job_id": "job-12",
                    "hw_id": "5",
                    "pos_id": 2,
                    "log_id": 12,
                    "date_utc": "2026-04-11T11:00:00Z",
                    "size_bytes": 1024,
                    "status": "queued",
                    "progress": 0.0,
                    "staged_filename": "5-job.ulg",
                    "download_filename": "mds-ulog_P2_H5_20260411T110000Z_L12.ulg",
                    "created_at": 1,
                    "updated_at": 1,
                    "expires_at": int(time.time() * 1000) + 60_000,
                    "error": None,
                },
                "timestamp": 1,
            }

        monkeypatch.setattr(log_proxy, "create_drone_ulog_download_job", fake_create)

        resp = client.post("/api/logs/drone/5/ulog/files/12/download")

        assert resp.status_code == 200
        assert resp.json()["job"]["job_id"] != "job-12"

    def test_download_drone_ulog_content_stream(self, tmp_path, monkeypatch):
        import log_proxy

        class FakeAsyncClient:
            async def aclose(self):
                return None

        class FakeAsyncResponse:
            status_code = 200
            headers = {
                "content-type": "application/octet-stream",
                "content-disposition": "attachment; filename=mds-ulog_P2_H5.ulg",
                "content-length": "4",
            }

            async def aiter_bytes(self):
                yield b"ulog"

            async def aclose(self):
                return None

        app = _make_gcs_app(str(tmp_path))
        client = TestClient(app)

        monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda drone_id: "10.0.0.5")

        async def fake_create(_drone_ip, log_id, *, access_token):
            assert log_id == 1
            assert access_token
            return {
                "job": {
                    "job_id": "job-1",
                    "hw_id": "5",
                    "pos_id": 2,
                    "log_id": 1,
                    "date_utc": "2026-04-11T11:00:00Z",
                    "size_bytes": 4,
                    "status": "ready",
                    "progress": 1.0,
                    "staged_filename": "5-job.ulg",
                    "download_filename": "mds-ulog_P2_H5.ulg",
                    "created_at": 1,
                    "updated_at": 1,
                    "expires_at": int(time.time() * 1000) + 60_000,
                    "error": None,
                },
                "timestamp": 1,
            }

        async def fake_open(_drone_ip, job_id, *, access_token):
            assert job_id == "job-1"
            assert access_token
            return FakeAsyncClient(), FakeAsyncResponse()

        monkeypatch.setattr(log_proxy, "create_drone_ulog_download_job", fake_create)
        monkeypatch.setattr(log_proxy, "open_drone_ulog_download_stream", fake_open)

        created = client.post("/api/logs/drone/5/ulog/files/1/download")
        handle = created.json()["job"]["job_id"]
        resp = client.get(f"/api/logs/drone/5/ulog/downloads/{handle}/content")

        assert resp.status_code == 200
        assert resp.content == b"ulog"
        assert "attachment;" in resp.headers["content-disposition"]

    def test_erase_all_drone_ulogs_maps_unavailable_to_502(self, tmp_path, monkeypatch):
        import log_proxy

        app = _make_gcs_app(str(tmp_path))
        client = TestClient(app)

        monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda drone_id: "10.0.0.5")

        async def fake_erase(_drone_ip):
            raise log_proxy.DroneProxyUnavailableError("timeout")

        monkeypatch.setattr(log_proxy, "erase_all_drone_ulogs", fake_erase)

        resp = client.post("/api/logs/drone/5/ulog/erase-all")

        assert resp.status_code == 502
        assert "unreachable" in resp.json()["detail"]

    def test_erase_all_drone_ulogs_requires_admin_role(self, tmp_path, monkeypatch):
        import log_proxy

        auth_dir = tmp_path / "role-auth"
        monkeypatch.setenv("MDS_AUTH_ENABLED", "true")
        monkeypatch.setenv("MDS_API_AUTH_ENABLED", "true")
        monkeypatch.setenv("MDS_AUTH_USERS_FILE", str(auth_dir / "users.json"))
        monkeypatch.setenv("MDS_API_TOKENS_FILE", str(auth_dir / "api_tokens.json"))
        monkeypatch.setenv("MDS_AUTH_SESSION_SECRET_FILE", str(auth_dir / "session_secret"))
        monkeypatch.setenv("MDS_AUTH_CSRF_SECRET_FILE", str(auth_dir / "csrf_secret"))
        service = AuthService(AuthSettings.from_env())
        viewer_token = service.store.create_token(
            "viewer",
            scopes=["viewer"],
            ttl_seconds=3600,
        )["token"]
        operator_token = service.store.create_token(
            "operator",
            scopes=["operator"],
            ttl_seconds=3600,
        )["token"]
        admin_token = service.store.create_token(
            "admin",
            scopes=["admin"],
            ttl_seconds=3600,
        )["token"]
        calls = []

        monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda drone_id: "10.0.0.5")

        async def fake_erase(drone_ip):
            calls.append(drone_ip)
            return {
                "status": "accepted",
                "hw_id": "5",
                "pos_id": 2,
                "erased_count": 1,
                "timestamp": 1,
            }

        monkeypatch.setattr(log_proxy, "erase_all_drone_ulogs", fake_erase)
        client = TestClient(_make_gcs_app(str(tmp_path)))

        viewer = client.post(
            "/api/logs/drone/5/ulog/erase-all",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        operator = client.post(
            "/api/logs/drone/5/ulog/erase-all",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        admin = client.post(
            "/api/logs/drone/5/ulog/erase-all",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert viewer.status_code == 403
        assert operator.status_code == 403
        assert admin.status_code == 200
        assert calls == ["10.0.0.5"]
