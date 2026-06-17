from __future__ import annotations

import json
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.simurgh import create_simurgh_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_simurgh_router())
    return TestClient(app)


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = "message"
    data_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if data_lines:
                events.append((event_name, json.loads("\n".join(data_lines))))
            event_name = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    if data_lines:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


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
    assert payload["mode"] == "real"
    assert payload["actions_blocked"] is True
    assert payload["action_policy_source"] == "circuit_breaker_and_mds_mode"
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


def test_simurgh_assistant_stream_emits_structured_activity_contract(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns/stream",
        json={"actor": "operator", "message": "what drones are connected right now?"},
    )

    assert response.status_code == 200
    events = _sse_events(response.text)
    progress_payloads = [payload for event, payload in events if event == "progress"]
    understanding = [
        payload
        for payload in progress_payloads
        if payload.get("stage") == "understanding" and payload.get("state") == "complete"
    ]
    assert understanding
    assert understanding[0]["domain"] == "fleet"
    assert understanding[0]["response_mode"] == "status"
    assert "Understanding:" in understanding[0]["label"]
    assert "fleet" in understanding[0]["label"].lower()
    assert any(payload.get("stage") in {"tool", "provider", "search"} for payload in progress_payloads)
    assert not any(event == "delta" for event, _payload in events)
    assert any(event == "final" and payload.get("trace") for event, payload in events)


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


def test_simurgh_tool_candidates_are_review_only_and_filterable():
    client = _client()

    response = client.get(
        "/api/v1/simurgh/tool-candidates",
        params={"eligible_read_only": "true", "limit": "5"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact"] == "simurgh_openapi_tool_candidates"
    assert payload["artifact_path"] == "docs/agent-context/generated/simurgh-openapi-tool-candidates.yaml"
    assert payload["policy"]["runtime_loaded"] is False
    assert payload["policy"]["default_callable"] is False
    assert payload["candidate_count"] > 100
    assert payload["filtered_count"] >= payload["returned_count"]
    assert payload["returned_count"] <= 5
    assert payload["summary"]["eligible_read_only_mcp_candidates"] > 0
    assert "promoted_registry_route_matches" in payload["summary"]
    coverage = payload["summary"]["registry_coverage"]
    assert coverage["eligible_route_candidates"] == payload["summary"]["eligible_read_only_mcp_candidates"]
    assert coverage["eligible_promoted_route_matches"] > 0
    assert coverage["eligible_unpromoted_route_count"] == 0
    assert coverage["eligible_promotion_coverage_percent"] == 100.0
    assert coverage["eligible_unpromoted_by_group"] == {}
    assert coverage["eligible_read_only_candidate_count"] == coverage["eligible_route_candidates"]
    assert coverage["promoted_eligible_candidate_count"] == coverage["eligible_promoted_route_matches"]
    assert coverage["unpromoted_eligible_candidate_count"] == coverage["eligible_unpromoted_route_count"]
    assert coverage["promoted_eligible_ratio"] == 1.0
    assert coverage["unpromoted_eligible_by_area"] == []
    assert all(
        set(item) == {"method", "path", "group", "summary"}
        for item in coverage["eligible_unpromoted_routes_preview"]
    )
    assert all(candidate["callable"] is False for candidate in payload["candidates"])
    assert all(candidate["classification"]["eligible_read_only_mcp_candidate"] is True for candidate in payload["candidates"])

    command_response = client.get(
        "/api/v1/simurgh/tool-candidates",
        params={"search": "/api/v1/commands", "limit": "20"},
    )
    assert command_response.status_code == 200
    command_payload = command_response.json()
    assert any(
        "command/control route" in candidate["classification"]["review_reasons"]
        for candidate in command_payload["candidates"]
    )


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

    markdown_response = client.get("/api/v1/simurgh/context/mds.init_setup/markdown")
    assert markdown_response.status_code == 200
    assert "companion" in markdown_response.text.lower()
    assert markdown_response.headers["content-type"].startswith("text/markdown")

    missing_response = client.get("/api/v1/simurgh/context/not-a-resource")
    assert missing_response.status_code == 404


def test_simurgh_context_list_and_read_hide_private_resources(monkeypatch, tmp_path):
    context_file = tmp_path / "context-index.yaml"
    context_file.write_text(
        """version: 1
resources:
  - id: public.fixture
    title: Public Fixture
    path: docs/agent-context/system-guidelines.md
    mime_type: text/markdown
    audience: agent
    sensitivity: public
    summary: Public fixture.
    tags: [test]
  - id: private.fixture
    title: Private Fixture
    path: docs/agent-context/system-guidelines.md
    mime_type: text/markdown
    audience: agent
    sensitivity: private
    summary: Private fixture.
    tags: [test]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MDS_AGENT_CONTEXT_INDEX_FILE", str(context_file))
    client = _client()

    list_response = client.get("/api/v1/simurgh/context")

    assert list_response.status_code == 200
    ids = {resource["id"] for resource in list_response.json()["resources"]}
    assert "public.fixture" in ids
    assert "private.fixture" not in ids

    public_response = client.get("/api/v1/simurgh/context/public.fixture")
    assert public_response.status_code == 200

    private_response = client.get("/api/v1/simurgh/context/private.fixture")
    assert private_response.status_code == 403

    private_markdown_response = client.get("/api/v1/simurgh/context/private.fixture/markdown")
    assert private_markdown_response.status_code == 403


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
    assert session["mode"] == "sitl"
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
                "raw_prompt": "CM4-99 stopped streaming on 192.0.2.33",
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
    assert "CM4-99" not in serialized
    assert "192.0.2.33" not in serialized


def test_simurgh_session_metadata_rejects_sensitive_allowed_key_values(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    create_response = client.post(
        "/api/v1/simurgh/sessions",
        json={
            "actor": "operator",
            "metadata": {
                "channel": "CM4-99",
                "source": "192.0.2.33",
            },
        },
    )

    assert create_response.status_code == 200
    assert create_response.json()["metadata"] == {}
    list_response = client.get("/api/v1/simurgh/sessions")
    serialized = str(list_response.json())
    assert "CM4-99" not in serialized
    assert "192.0.2.33" not in serialized


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


def test_simurgh_runtime_settings_hot_apply_and_persist(monkeypatch, tmp_path):
    env_file = tmp_path / "gcs.env"
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(env_file))
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_OPENAI_MODEL", "gpt-5.5")
    monkeypatch.setenv("MDS_MCP_ENABLED", "false")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.put(
        "/api/v1/simurgh/runtime-settings",
        json={
            "provider": "openai",
            "model": "gpt-5.4-nano",
            "mcp_enabled": True,
            "action_circuit_breaker_enabled": True,
            "always_confirm_before_action": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert payload["openai_model"] == "gpt-5.4-nano"
    assert payload["mcp_enabled"] is True
    assert payload["restart_required"] is False
    assert payload["restart_would_have_been_required"] is True
    assert os.environ["MDS_AGENT_PROVIDER"] == "openai"
    assert "MDS_AGENT_PROVIDER=openai" in env_file.read_text(encoding="utf-8")



def test_simurgh_provider_credentials_store_secret_server_side(monkeypatch, tmp_path):
    env_file = tmp_path / "gcs.env"
    key_file = tmp_path / "openai_api_key"
    fake_openai_key = "-".join(("sk", "test", "123456789012345678901234"))
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(env_file))
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    client = _client()

    response = client.put(
        "/api/v1/simurgh/provider-credentials",
        json={
            "openai_api_key": fake_openai_key,
            "set_provider_openai": True,
            "openai_model": "gpt-5.5",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    serialized = str(payload)
    assert "sk-test" not in serialized
    assert payload["credentials"]["openai"]["ready"] is True
    assert payload["credentials"]["openai"]["fingerprint"]
    assert key_file.read_text(encoding="utf-8").strip() == fake_openai_key
    assert key_file.stat().st_mode & 0o777 == 0o600
    env_text = env_file.read_text(encoding="utf-8")
    assert "MDS_AGENT_OPENAI_API_KEY_FILE=" in env_text
    assert "MDS_AGENT_PROVIDER=openai" in env_text
    assert "sk-test" not in env_text

    status_response = client.get("/api/v1/simurgh/provider-credentials")
    assert status_response.status_code == 200
    assert status_response.json()["openai"]["ready"] is True


def test_simurgh_status_warns_when_real_gcs_circuit_breaker_is_off(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "real")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    client = _client()

    response = client.get("/api/v1/simurgh/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "real"
    assert payload["actions_blocked"] is False
    warnings = payload["warnings"]
    assert any("circuit breaker is off" in warning for warning in warnings)
    assert not any("policy profile" in warning for warning in warnings)


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


def test_simurgh_status_uses_canonical_mds_mode(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    client = _client()

    response = client.get("/api/v1/simurgh/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["gcs_mode"] == "sitl"
    assert payload["mode"] == "sitl"
    assert payload["warnings"] == []
