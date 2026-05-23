from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_runtime import AgentRuntimeError, OpenAIResponsesAssistantAdapter
from api_routes.simurgh import create_simurgh_router


@pytest.fixture(autouse=True)
def _assistant_history_file(monkeypatch, tmp_path):
    path = tmp_path / "assistant_turns.jsonl"
    monkeypatch.setenv("MDS_AGENT_ASSISTANT_HISTORY_FILE", str(path))
    return path


def _client(auth_context=None) -> TestClient:
    app = FastAPI()
    if auth_context is not None:
        @app.middleware("http")
        async def _inject_auth_context(request, call_next):  # noqa: ANN001
            request.state.mds_auth_context = auth_context
            return await call_next(request)

    app.include_router(create_simurgh_router())
    return TestClient(app)


def _write_restricted_key(path, value="test-openai-key\n"):
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_simurgh_assistant_turn_requires_enabled_agent(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "false")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Explain Simurgh status."},
    )

    assert response.status_code == 403
    assert "disabled" in response.json()["detail"]


def test_simurgh_assistant_turn_creates_mock_session_and_audit(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Can you arm drone 1?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mock"
    assert payload["session"]["id"].startswith("session-")
    assert "arm" in payload["blocked_intents"]
    assert payload["context_resources"]
    assert all("content_hash" in resource for resource in payload["context_resources"])
    assert "No provider SDK was called." in payload["safety_notes"]

    sessions = client.get("/api/v1/simurgh/sessions").json()["sessions"]
    assert [session["id"] for session in sessions] == [payload["session"]["id"]]

    audit_events = client.get("/api/v1/simurgh/audit").json()["events"]
    assert [event["event_type"] for event in audit_events] == ["assistant_turn_created"]
    assert audit_events[0]["payload_hash"]
    assert audit_events[0]["metadata"]["provider"] == "mock"
    assert "drone 1" not in str(audit_events[0])

    history = client.get("/api/v1/simurgh/assistant/turns", params={"actor": "operator"}).json()["turns"]
    assert [turn["id"] for turn in history] == [payload["id"]]
    assert history[0]["message"] == ""
    assert history[0]["content"] == ""
    assert history[0]["message_hash"]
    assert history[0]["model"] == "mock-local"
    assert history[0]["adapter_version"] == "mock-v1"


def test_simurgh_assistant_turn_can_use_existing_session(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    session = client.post("/api/v1/simurgh/sessions", json={"actor": "operator"}).json()
    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": session["id"],
            "message": "Summarize safety policy.",
            "context_resource_ids": ["simurgh.safety_policy"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["id"] == session["id"]
    assert [resource["id"] for resource in payload["context_resources"]] == ["simurgh.safety_policy"]


def test_simurgh_assistant_turn_rejects_cross_actor_session_reuse(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    session = client.post("/api/v1/simurgh/sessions", json={"actor": "operator-a"}).json()
    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator-b",
            "session_id": session["id"],
            "message": "Summarize safety policy.",
        },
    )

    assert response.status_code == 403
    assert "different actor" in response.json()["detail"]


def test_simurgh_assistant_turn_rejects_oversized_metadata(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Summarize safety policy.",
            "metadata": {"blob": "x" * 5000},
        },
    )

    assert response.status_code == 400
    assert "metadata exceeds" in response.json()["detail"]


def test_simurgh_assistant_turn_does_not_reflect_raw_metadata_to_sessions(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Summarize safety policy.",
            "metadata": {
                "source": "simurgh-dashboard",
                "raw_prompt": "AIRFRAME-01 stopped streaming on 192.168.1.10",
            },
        },
    )

    assert response.status_code == 200
    sessions = client.get("/api/v1/simurgh/sessions").json()["sessions"]
    assert sessions[0]["metadata"] == {"channel": "assistant", "source": "simurgh-dashboard"}


def test_simurgh_assistant_turn_rejects_sensitive_metadata_source(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Summarize safety policy.",
            "metadata": {
                "source": "AIRFRAME-01",
            },
        },
    )

    assert response.status_code == 200
    session = response.json()["session"]
    assert session["metadata"] == {"channel": "assistant"}
    serialized = str(client.get("/api/v1/simurgh/sessions").json())
    assert "AIRFRAME-01" not in serialized


def test_simurgh_assistant_history_filters_by_actor(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    client.post("/api/v1/simurgh/assistant/turns", json={"actor": "operator-a", "message": "A question."})
    client.post("/api/v1/simurgh/assistant/turns", json={"actor": "operator-b", "message": "B question."})

    history = client.get("/api/v1/simurgh/assistant/turns", params={"actor": "operator-b"}).json()["turns"]
    assert [turn["actor"] for turn in history] == ["operator-b"]
    assert history[0]["message"] == ""
    assert history[0]["message_hash"]


def test_simurgh_router_startup_survives_corrupt_history_file(monkeypatch, _assistant_history_file):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    _assistant_history_file.write_text("{not json}\n", encoding="utf-8")

    client = _client()

    status = client.get("/api/v1/simurgh/status")
    history = client.get("/api/v1/simurgh/assistant/turns", params={"actor": "operator"})
    assert status.status_code == 200
    assert history.status_code == 500
    assert "invalid record" in history.json()["detail"]


def test_simurgh_assistant_turn_rejects_unknown_context(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Summarize a missing context.",
            "context_resource_ids": ["missing.resource"],
        },
    )

    assert response.status_code == 404


def test_simurgh_assistant_turn_rejects_external_provider_without_auth(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 403
    assert "require MDS auth" in response.json()["detail"]


@pytest.mark.parametrize(
    "auth_context",
    [
        {"kind": "session", "role": "viewer", "username": "viewer"},
        {"kind": "bearer", "role": "operator", "username": "drone-token", "scopes": ["drone"]},
        {"kind": "bearer", "role": "viewer", "username": "viewer-token", "scopes": ["viewer"]},
    ],
)
def test_simurgh_assistant_turn_rejects_external_provider_without_operator_or_agent_scope(
    monkeypatch,
    tmp_path,
    auth_context,
):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    provider_called = False

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        nonlocal provider_called
        provider_called = True
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Provider answer."}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client(auth_context=auth_context)

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 403
    assert "agent, operator, or admin scope" in response.json()["detail"]
    assert provider_called is False


@pytest.mark.parametrize(
    "auth_context",
    [
        {"kind": "session", "role": "operator", "username": "operator"},
        {"kind": "session", "role": "admin", "username": "admin"},
        {"kind": "bearer", "role": "operator", "username": "agent-token", "scopes": ["agent"]},
        {"kind": "bearer", "role": "operator", "username": "operator-token", "scopes": ["operator"]},
        {"kind": "bearer", "role": "admin", "username": "admin-token", "scopes": ["admin"]},
    ],
)
def test_simurgh_assistant_turn_allows_external_provider_for_operator_or_agent_scope(
    monkeypatch,
    tmp_path,
    auth_context,
):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Provider answer."}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client(auth_context=auth_context)

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "openai"


def test_simurgh_assistant_turn_uses_openai_provider_with_safe_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        captured["api_key"] = api_key
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Provider answer."}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client(auth_context={"kind": "session", "role": "operator", "username": "operator"})

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-5.5"
    assert payload["adapter_version"] == "openai-responses-v1"
    assert payload["content"] == "Provider answer."
    assert captured["api_key"] == "test-openai-key"
    assert captured["store"] is False
    assert captured["tools"] == []
    assert captured["tool_choice"] == "none"

    audit_event = client.get("/api/v1/simurgh/audit").json()["events"][0]
    assert audit_event["metadata"]["provider"] == "openai"
    assert "test-openai-key" not in str(audit_event)
    assert "Use a provider" not in str(audit_event)

    history = client.get("/api/v1/simurgh/assistant/turns", params={"actor": "operator"}).json()["turns"]
    assert history[0]["model"] == "gpt-5.5"
    assert history[0]["adapter_version"] == "openai-responses-v1"


def test_simurgh_assistant_turn_returns_safe_openai_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key", "test-secret-should-not-leak\n")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fail_post(self, payload, *, api_key):  # noqa: ANN001
        raise AgentRuntimeError("OpenAI assistant request failed with HTTP 500")

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fail_post)
    client = _client(auth_context={"kind": "session", "role": "operator", "username": "operator"})

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "OpenAI assistant request failed with HTTP 500"
    assert "test-secret" not in str(response.json())


def test_simurgh_assistant_turn_rejects_unsupported_provider(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "anthropic")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 501
    assert "not implemented" in response.json()["detail"]
