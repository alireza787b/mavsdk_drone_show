from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.simurgh import create_simurgh_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_simurgh_router())
    return TestClient(app)


def test_simurgh_status_enables_non_executing_runtime_by_default_and_uses_repo_relative_paths(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "real")
    client = _client()

    response = client.get("/api/v1/simurgh/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_enabled"] is True
    assert payload["mcp_enabled"] is False
    assert payload["gcs_mode"] == "real"
    assert payload["gcs_mode_source"] == "env:MDS_MODE"
    assert payload["mode"] == "read_only"
    assert payload["action_circuit_breaker_enabled"] is True
    assert payload["always_confirm_before_action"] is True
    assert payload["tool_count"] >= 20
    assert payload["allowed_tool_count"] > 0
    assert payload["excluded_tool_count"] > 0
    assert payload["assistant_provider"] == "mock"
    assert payload["assistant_model"] == "mock-local"
    assert payload["assistant_external_provider"] is False
    assert payload["assistant_external_provider_auth_required"] is False
    assert payload["policy_path"] == "config/agent_policy.yaml"
    assert payload["tool_registry_path"] == "config/agent_tools.yaml"
    assert payload["context_index_path"] == "docs/agent-context/context-index.yaml"
    assert payload["warnings"] == []


def test_simurgh_tools_expose_registry_metadata_without_executing_tools():
    client = _client()

    response = client.get("/api/v1/simurgh/tools", params={"include_excluded": "false"})

    assert response.status_code == 200
    tools = response.json()["tools"]
    assert any(tool["id"] == "mds.system.health.read" for tool in tools)
    assert all(tool["exposure"] != "exclude" for tool in tools)
    assert not any(tool["boundary"] != "gcs" for tool in tools)

    raw_response = client.get("/api/v1/simurgh/tools/mds.commands.raw_submit")
    assert raw_response.status_code == 200
    assert raw_response.json()["exposure"] == "exclude"

    missing_response = client.get("/api/v1/simurgh/tools/not-a-tool")
    assert missing_response.status_code == 404


def test_simurgh_context_lists_and_reads_public_context():
    client = _client()

    list_response = client.get("/api/v1/simurgh/context")

    assert list_response.status_code == 200
    resources = list_response.json()["resources"]
    assert any(resource["id"] == "simurgh.safety_policy" for resource in resources)
    assert all(resource["content_hash"] for resource in resources)

    content_response = client.get("/api/v1/simurgh/context/simurgh.safety_policy")
    assert content_response.status_code == 200
    assert "Raw GCS command submission" in content_response.json()["content"]

    missing_response = client.get("/api/v1/simurgh/context/not-a-resource")
    assert missing_response.status_code == 404


def test_simurgh_session_lifecycle_records_audit_events(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    create_response = client.post(
        "/api/v1/simurgh/sessions",
        json={"actor": "operator", "metadata": {"channel": "dashboard"}},
    )

    assert create_response.status_code == 200
    session = create_response.json()
    assert session["actor"] == "operator"
    assert session["mode"] == "read_only"
    assert session["closed"] is False

    list_response = client.get("/api/v1/simurgh/sessions", params={"include_closed": "false"})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["sessions"]] == [session["id"]]

    close_response = client.delete(f"/api/v1/simurgh/sessions/{session['id']}")
    assert close_response.status_code == 200
    assert close_response.json()["closed"] is True

    filtered_response = client.get("/api/v1/simurgh/sessions", params={"include_closed": "false"})
    assert filtered_response.status_code == 200
    assert filtered_response.json()["sessions"] == []

    audit_response = client.get("/api/v1/simurgh/audit", params={"session_id": session["id"]})
    assert audit_response.status_code == 200
    event_types = [event["event_type"] for event in audit_response.json()["events"]]
    assert event_types == ["session_created", "session_closed"]
    assert all(event["payload_hash"] for event in audit_response.json()["events"])


def test_simurgh_session_creation_sanitizes_metadata(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    create_response = client.post(
        "/api/v1/simurgh/sessions",
        json={
            "actor": "operator",
            "metadata": {
                "channel": "dashboard",
                "source": "simurgh-ui",
                "raw_prompt": "AIRFRAME-01 stopped streaming on 192.168.1.10",
                "notes": "customer field evidence",
            },
        },
    )

    assert create_response.status_code == 200
    session = create_response.json()
    assert session["metadata"] == {"channel": "dashboard", "source": "simurgh-ui"}

    list_response = client.get("/api/v1/simurgh/sessions")
    assert list_response.status_code == 200
    serialized = str(list_response.json())
    assert "raw_prompt" not in serialized
    assert "AIRFRAME-01" not in serialized
    assert "192.168.1.10" not in serialized


def test_simurgh_session_metadata_rejects_sensitive_allowed_key_values(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    create_response = client.post(
        "/api/v1/simurgh/sessions",
        json={
            "actor": "operator",
            "metadata": {
                "channel": "AIRFRAME-01",
                "source": "192.168.1.10",
            },
        },
    )

    assert create_response.status_code == 200
    assert create_response.json()["metadata"] == {}
    list_response = client.get("/api/v1/simurgh/sessions")
    serialized = str(list_response.json())
    assert "AIRFRAME-01" not in serialized
    assert "192.168.1.10" not in serialized


def test_simurgh_status_reports_external_assistant_provider(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client()

    response = client.get("/api/v1/simurgh/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_provider"] == "openai"
    assert payload["assistant_model"] == "gpt-5.5"
    assert payload["assistant_external_provider"] is True
    assert payload["assistant_external_provider_auth_required"] is True


def test_simurgh_status_warns_when_policy_profile_diverges_from_real_gcs(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "real")
    monkeypatch.setenv("MDS_AGENT_MODE", "sitl")
    client = _client()

    response = client.get("/api/v1/simurgh/status")

    assert response.status_code == 200
    warnings = response.json()["warnings"]
    assert any("not read_only" in warning for warning in warnings)
    assert any("GCS is in real mode" in warning for warning in warnings)


def test_simurgh_session_creation_requires_enabled_runtime(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "false")
    client = _client()

    response = client.post("/api/v1/simurgh/sessions", json={"actor": "operator"})

    assert response.status_code == 403


def test_simurgh_session_rejects_unknown_mode(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post("/api/v1/simurgh/sessions", json={"actor": "operator", "mode": "unsafe"})

    assert response.status_code == 400


def test_simurgh_status_reports_invalid_mode_as_config_error(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_MODE", "unsafe")
    client = _client()

    response = client.get("/api/v1/simurgh/status")

    assert response.status_code == 500
    assert "unknown Simurgh mode" in response.json()["detail"]
