"""Real GCS routes: complete bounded exports and explicit page coverage."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from log_routes import create_log_router

SID = "s_20261112_120000"


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(create_log_router(log_dir=str(tmp_path)))
    return TestClient(app)


def records(tmp_path, count=1805):
    (tmp_path / f"{SID}.jsonl").write_text("".join(json.dumps({
        "msg": f"event {i}", "component": "coordinator", "level": "INFO",
        "ts": "2026-11-12T12:00:00Z"}) + "\n" for i in range(count)))


@pytest.mark.parametrize("query", ["limit=0", "limit=-1", "limit=2001", "offset=-1", "level=WRONG", "since=bad"])
def test_actual_http_query_validation(client, tmp_path, query):
    records(tmp_path, 2)
    response = client.get(f"/api/logs/sessions/{SID}?{query}")
    assert response.status_code == 422


def test_actual_read_is_bounded_with_continuation(client, tmp_path):
    records(tmp_path)
    response = client.get(f"/api/logs/sessions/{SID}").json()
    assert response["count"] == 500 and response["has_more"] is True
    assert response["coverage"]["scope"] == "page"
    next_page = client.get(f"/api/logs/sessions/{SID}", params={"cursor": response["next_cursor"]}).json()
    assert next_page["lines"][0]["msg"] == "event 500"


def test_export_visits_all_pages_without_truncation(client, tmp_path):
    records(tmp_path)
    response = client.post("/api/logs/export", json={"session_ids": [SID]})
    assert response.status_code == 200
    lines = response.text.strip().splitlines()
    assert len(lines) == 1805
    assert json.loads(lines[-1])["msg"] == "event 1804"
    assert response.headers["x-mds-export-records"] == "1805"
    assert response.headers["x-mds-export-scope"] == "full-sessions"


def test_export_filters_apply_to_whole_snapshot_not_loaded_page(client, tmp_path):
    records(tmp_path)
    response = client.post("/api/logs/export", json={"session_ids": [SID], "filters": {"search": "event 1804"}})
    assert response.status_code == 200
    assert len(response.text.strip().splitlines()) == 1
    assert json.loads(response.text)["msg"] == "event 1804"
    assert response.headers["x-mds-export-scope"] == "filtered"


def test_export_reports_malformed_record_coverage(client, tmp_path):
    records(tmp_path, 2)
    with (tmp_path / f"{SID}.jsonl").open("a") as handle:
        handle.write("[]\ninvalid json\n")
    response = client.post("/api/logs/export", json={"session_ids": [SID]})
    assert response.status_code == 200
    assert response.headers["x-mds-export-skipped"] == "2"
    assert len(response.text.strip().splitlines()) == 2


def test_export_size_and_disk_reserve_errors_do_not_leak_temporary_files(client, tmp_path, monkeypatch):
    import log_exports
    records(tmp_path, 5)
    monkeypatch.setattr(log_exports.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(log_exports.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**10))
    monkeypatch.setattr(log_exports, "MAX_EXPORT_BYTES", 20)
    response = client.post("/api/logs/export", json={"session_ids": [SID]})
    assert response.status_code == 413 and not list(tmp_path.glob("mds-log-export-*"))
    monkeypatch.setattr(log_exports.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    response = client.post("/api/logs/export", json={"session_ids": [SID]})
    assert response.status_code == 507


def test_source_cannot_claim_old_unpaged_response_is_a_complete_export(client, monkeypatch):
    import log_proxy
    monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda _: "192.0.2.5")
    async def old_page(*args, **kwargs):
        return {"session_id": SID, "lines": [{"msg": "only first old page"}]}
    monkeypatch.setattr(log_proxy, "fetch_drone_session_content", old_page)
    response = client.post("/api/logs/drone/5/export", json={"session_ids": [SID]})
    assert response.status_code == 409
