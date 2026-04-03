"""Tests for GCS-side log API endpoints (local — no drone proxy)."""
import json
import os
import sys
import pytest

# Add gcs-server to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'gcs-server'))

from fastapi.testclient import TestClient
from fastapi import FastAPI

from mds_logging.watcher import LogWatcher
from mds_logging.registry import register_component, clear_registry


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


def _make_gcs_app(log_dir, watcher=None):
    """Build a minimal FastAPI app with the GCS log router."""
    from log_routes import create_log_router
    app = FastAPI()
    router = create_log_router(log_dir=log_dir, watcher=watcher)
    app.include_router(router)
    return app


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
